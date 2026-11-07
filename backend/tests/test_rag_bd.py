"""Parte B contra PostgreSQL, con modelos falsos y ChromaDB en memoria: parámetros,
permisos de cdss_generacion, validación con cdss_clinica y recuperación con
cdss_generacion (fragmentos no vigentes, recomprobación, búsqueda ampliada y campos
para el orquestador)."""
import os
import uuid
from collections import namedtuple
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import ProgrammingError

from app.core.modelos import EmbedderFalso, RerankerFalso
from app.core.vectores import AlmacenMemoria, RegistroVector
from app.rag.bm25 import CacheBM25, Huella, IndiceBM25
from app.rag.normalizacion import normalizar
from app.rag.parametros import ErrorParametro, leer_parametros, parametros_recuperacion
from app.rag.recuperacion import (AMPLIADA, INICIAL, Servicios, buscar_candidatos, leer_texto_filtrado, recuperar,
                                  recuperar_con_ampliacion, seleccionar)
from app.rag.validacion import DATOS_FALTANTES, TAMIZAJE_NO_VIGENTE, VALIDA, validar_tamizaje

SISTEMA = "00000000-0000-0000-0000-000000000001"
LIMA = "150101"
Fila = namedtuple("Fila", "id_fragmento id_documento texto idioma")

TEXTOS = {
    "preventiva": "Suplementación preventiva con hierro en lactantes de 6 a 11 meses: sulfato ferroso en gotas, "
                  "una dosis diaria hasta completar seis meses.",
    "tratamiento": "Tratamiento de la anemia en niños con sulfato ferroso durante seis meses y control de hemoglobina.",
    "vacunas": "Calendario de vacunación del niño menor de un año en el establecimiento de salud.",
    "registro": "Registro de las atenciones en la historia clínica y en el formato HIS.",
    "gestion": "Indicadores de gestión del establecimiento y supervisión de la red de salud.",
    "sustituido": "Suplementación preventiva con hierro en lactantes: sulfato ferroso en gotas, dosis diaria de "
                  "hierro para lactantes, suplementación preventiva con hierro.",
}


def _url(variable: str) -> str:
    url = os.environ.get(variable)
    if not url:
        pytest.fail(f"Falta {variable} en .env.test")
    return url


@pytest.fixture(scope="module")
def engine_generacion():
    return create_engine(_url("DATABASE_URL_GENERACION"))


@pytest.fixture(scope="module")
def engine_clinica():
    return create_engine(_url("DATABASE_URL_CLINICA"))


@pytest.fixture
def guia(super_engine):
    """Documento de nivel 1 indexado, con un fragmento sustituido (no vigente), y su
    almacén vectorial en memoria con los mismos metadatos que escribe el indexador."""
    id_doc = str(uuid.uuid4())
    ids = {clave: str(uuid.uuid4()) for clave in TEXTOS}
    with super_engine.begin() as c:
        c.execute(text(
            """INSERT INTO conocimiento.documento_fuente
                 (id_documento, titulo, codigo_documento, entidad_emisora, tipo_documento, nivel, anio_publicacion,
                  idioma, cargado_por, estado_indexacion, ruta_blob, hash_archivo, total_fragmentos)
               VALUES (:id, 'Guía de prueba de la recuperación', 'PRUEBA-RAG', 'MINSA', 'NORMA_TECNICA', 1, 2024,
                       'es', :u, 'COMPLETADA', 'local://prueba/rag.pdf', :h, :n)"""
        ), {"id": id_doc, "u": SISTEMA, "h": uuid.uuid4().hex * 2, "n": len(TEXTOS)})
        for orden, (clave, texto) in enumerate(TEXTOS.items(), start=1):
            vigente = clave != "sustituido"
            c.execute(text(
                """INSERT INTO conocimiento.fragmento
                     (id_fragmento, id_documento, numero_orden, seccion, pagina_inicio, pagina_fin, texto,
                      numero_tokens, modelo_embedding, vigente, motivo_exclusion)
                   VALUES (:id, :doc, :orden, :seccion, :orden, :orden, :texto, 30, 'falso', :vigente, :motivo)"""
            ), {"id": ids[clave], "doc": id_doc, "orden": orden, "seccion": f"Sección {clave}", "texto": texto,
                "vigente": vigente, "motivo": None if vigente else "Sustituido por RM de prueba"})
    almacen = AlmacenMemoria()
    vectores = EmbedderFalso().embeber(list(TEXTOS.values()))
    for (clave, texto), vector in zip(TEXTOS.items(), vectores):
        # Un almacén desactualizado: el fragmento sustituido sigue marcado como vigente.
        almacen.agregar([RegistroVector(ids[clave], vector, texto, {
            "id_documento": id_doc, "nivel": 1, "estado_documento": "VIGENTE", "vigente": True, "idioma": "es"})])
    yield {"id_documento": id_doc, "ids": ids, "almacen": almacen}
    with super_engine.begin() as c:
        c.execute(text("DELETE FROM conocimiento.fragmento WHERE id_documento = :id"), {"id": id_doc})
        c.execute(text("DELETE FROM conocimiento.documento_fuente WHERE id_documento = :id"), {"id": id_doc})


def _servicios(guia, cache=None, reranker=RerankerFalso()) -> Servicios:
    return Servicios(EmbedderFalso(), reranker, guia["almacen"], cache or CacheBM25())


def _parametros(c, **cambios):
    return replace(parametros_recuperacion(c), **{"umbral_relevancia": 0.3, **cambios})


CONSULTA = "dosis de sulfato ferroso preventivo en gotas para lactantes"


# ---------------------------------------------------------------------------
# Parámetros
# ---------------------------------------------------------------------------
def test_lee_los_parametros_vigentes_incluidos_los_del_reranker(engine_generacion):
    with engine_generacion.connect() as c:
        p = parametros_recuperacion(c)
    assert p.rrf_k == 60 and p.candidatos_busqueda == 20 and p.candidatos_busqueda_ampliada == 40
    assert p.fragmentos_enviados == 5 and p.dias_vigencia_tamizaje == 30
    assert p.candidatos_reranker == 8 and p.max_longitud_reranker == 256
    assert p.umbral_relevancia == 0.15 and p.umbral_dominio == 0.65


MIGRACION_005 = Path(__file__).resolve().parents[2] / "db" / "migraciones" / "005_parametros_definitivos_recuperacion.sql"


def test_parametros_definitivos_como_versiones_nuevas_con_historial(super_engine):
    claves = {"CANDIDATOS_RERANKER": ("20", "8"), "MAX_LONGITUD_RERANKER": ("1024", "256"),
              "UMBRAL_RELEVANCIA": ("0.60", "0.15"), "UMBRAL_DOMINIO": ("0.50", "0.65")}
    with super_engine.connect() as c:
        filas = c.execute(text(
            """SELECT clave, valor, vigente_desde, vigente_hasta FROM configuracion.parametro_sistema
               WHERE clave = ANY(:claves) ORDER BY clave, vigente_desde, id_parametro"""),
            {"claves": list(claves)}).all()
    for clave, (inicial, definitivo) in claves.items():
        versiones = [f for f in filas if f.clave == clave]
        anterior = next(f for f in versiones if f.valor == inicial)
        vigente = [f for f in versiones if f.vigente_hasta is None]
        assert [f.valor for f in vigente] == [definitivo]
        assert anterior.vigente_hasta is not None and anterior.vigente_hasta <= vigente[0].vigente_desde


def test_migracion_005_es_idempotente(super_engine):
    with super_engine.connect() as c:
        transaccion = c.begin()
        try:
            antes = c.execute(text("SELECT count(*) FROM configuracion.parametro_sistema")).scalar()
            c.exec_driver_sql(MIGRACION_005.read_text(encoding="utf-8"))
            assert c.execute(text("SELECT count(*) FROM configuracion.parametro_sistema")).scalar() == antes
        finally:
            transaccion.rollback()


def test_respeta_la_vigencia_de_los_parametros(super_engine, engine_generacion):
    with super_engine.begin() as c:
        cerrado = c.execute(text(
            """INSERT INTO configuracion.parametro_sistema
                 (clave, valor, tipo_dato, valor_minimo, valor_maximo, descripcion, vigente_desde, vigente_hasta,
                  modificado_por)
               VALUES ('RRF_K', '10', 'ENTERO', 1, 200, 'prueba', now() - interval '2 days',
                       now() - interval '1 day', :u)
               RETURNING id_parametro"""), {"u": SISTEMA}).scalar()
    try:
        with engine_generacion.connect() as c:
            assert leer_parametros(c, ["RRF_K"])["RRF_K"] == 60
            with pytest.raises(ErrorParametro):
                leer_parametros(c, ["CLAVE_INEXISTENTE"])
    finally:
        with super_engine.begin() as c:
            c.execute(text("DELETE FROM configuracion.parametro_sistema WHERE id_parametro = :i"), {"i": cerrado})


# ---------------------------------------------------------------------------
# Permisos de cdss_generacion
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("sql", [
    "SELECT altitud_msnm FROM clinico.distrito LIMIT 1",
    "SELECT texto_consulta FROM asistencia.consulta LIMIT 1",
    "SELECT observaciones FROM clinico.tamizaje LIMIT 1",
    "SELECT * FROM clinico.paciente_identidad LIMIT 1",
])
def test_cdss_generacion_no_lee_distrito_ni_texto_libre_ni_identidad(engine_generacion, sql):
    with engine_generacion.connect() as c, pytest.raises(ProgrammingError, match="permission denied"):
        c.execute(text(sql))


def test_cdss_generacion_lee_lo_que_necesita_la_recuperacion(engine_generacion):
    with engine_generacion.connect() as c:
        for tabla in ("conocimiento.fragmento", "conocimiento.documento_fuente", "configuracion.parametro_sistema",
                      "clinico.resultado_clasificacion"):
            c.execute(text(f"SELECT 1 FROM {tabla} LIMIT 1"))
        c.execute(text("SELECT texto_filtrado FROM asistencia.consulta LIMIT 1"))


# ---------------------------------------------------------------------------
# Validación (sesión de cdss_clinica)
# ---------------------------------------------------------------------------
@pytest.fixture
def crear_tamizaje(super_engine, pacientes_creados):
    consultas: list[str] = []

    def _crear(fecha: date, hemoglobina: float | None = 9.0, edad_meses: int = 14) -> str:
        id_paciente, id_tamizaje = str(uuid.uuid4()), str(uuid.uuid4())
        with super_engine.begin() as c:
            c.execute(text(
                """INSERT INTO clinico.paciente (id_paciente, ubigeo_residencia, fecha_nacimiento, sexo, registrado_por)
                   VALUES (:p, :u, :n, 'F', :s)"""), {"p": id_paciente, "u": LIMA, "s": SISTEMA,
                                                      "n": fecha - timedelta(days=edad_meses * 31)})
            c.execute(text(
                """INSERT INTO clinico.tamizaje (id_tamizaje, id_paciente, id_usuario, fecha_tamizaje, edad_meses,
                                                 hemoglobina_g_dl, observaciones)
                   VALUES (:t, :p, :s, :f, :e, :hb, 'Texto libre que la parte B nunca lee')"""),
                {"t": id_tamizaje, "p": id_paciente, "s": SISTEMA, "f": fecha, "e": edad_meses, "hb": hemoglobina})
        pacientes_creados.append(id_paciente)
        return id_tamizaje

    _crear.consultas = consultas
    yield _crear
    if consultas:
        with super_engine.begin() as c:
            c.execute(text("DELETE FROM asistencia.consulta WHERE id_consulta::text = ANY(:ids)"), {"ids": consultas})


def test_lista_los_datos_faltantes_para_m06(engine_clinica, crear_tamizaje):
    id_tamizaje = crear_tamizaje(date(2026, 10, 1), hemoglobina=None)
    with engine_clinica.begin() as c:
        r = validar_tamizaje(c, id_tamizaje, fecha_referencia=date(2026, 10, 2))
    assert r.estado == DATOS_FALTANTES
    assert [f.campo for f in r.faltantes] == ["hemoglobina_g_dl"]
    assert r.disponibles == {"edad": True, "sexo": True, "altitud": True, "hemoglobina": False,
                             "fecha del tamizaje": True}
    assert r.clasificacion is None


@pytest.mark.parametrize("dias, estado", [(0, VALIDA), (30, VALIDA), (31, TAMIZAJE_NO_VIGENTE)])
def test_vigencia_del_tamizaje_30_dias_si_31_no(engine_clinica, crear_tamizaje, dias, estado):
    fecha = date(2026, 9, 1)
    id_tamizaje = crear_tamizaje(fecha)
    with engine_clinica.begin() as c:
        r = validar_tamizaje(c, id_tamizaje, fecha_referencia=fecha + timedelta(days=dias))
    assert r.estado == estado and r.dias_transcurridos == dias and r.dias_vigencia == 30
    assert (r.clasificacion is None) == (estado == TAMIZAJE_NO_VIGENTE)


def test_continua_con_tamizaje_no_vigente_si_el_profesional_lo_confirma(engine_clinica, crear_tamizaje):
    fecha = date(2026, 9, 1)
    id_tamizaje = crear_tamizaje(fecha)
    with engine_clinica.begin() as c:
        r = validar_tamizaje(c, id_tamizaje, confirma_tamizaje_no_vigente=True,
                             fecha_referencia=fecha + timedelta(days=45))
    assert r.estado == VALIDA and r.continua_con_tamizaje_no_vigente and r.dias_transcurridos == 45


def test_calcula_y_guarda_la_clasificacion_solo_si_falta(engine_clinica, engine_generacion, crear_tamizaje):
    fecha = date(2026, 10, 1)
    id_tamizaje = crear_tamizaje(fecha, hemoglobina=9.0, edad_meses=14)
    with engine_clinica.begin() as c:
        primera = validar_tamizaje(c, id_tamizaje, fecha_referencia=fecha)
    with engine_clinica.begin() as c:
        segunda = validar_tamizaje(c, id_tamizaje, fecha_referencia=fecha)
    assert primera.clasificacion.calculada_ahora and not segunda.clasificacion.calculada_ahora
    assert primera.clasificacion.categoria == segunda.clasificacion.categoria
    with engine_generacion.connect() as c:
        guardada = c.execute(text(
            "SELECT nivel_riesgo FROM clinico.resultado_clasificacion WHERE id_tamizaje = :t"), {"t": id_tamizaje}
        ).scalar()
    assert guardada == primera.clasificacion.nivel_riesgo


# ---------------------------------------------------------------------------
# Recuperación (sesión de cdss_generacion)
# ---------------------------------------------------------------------------
class CacheDesactualizada:
    """Índice BM25 viejo que todavía contiene el fragmento sustituido y lo pone primero."""

    def __init__(self, guia):
        filas = [Fila(guia["ids"][k], guia["id_documento"], TEXTOS[k], "es") for k in TEXTOS]
        self.indice = IndiceBM25(filas, Huella(len(filas), "vieja"))

    def obtener(self, sesion):
        return self.indice


def test_nunca_devuelve_un_fragmento_no_vigente_aunque_bm25_lo_ponga_primero(engine_generacion, guia):
    sustituido = guia["ids"]["sustituido"]
    servicios = _servicios(guia, cache=CacheDesactualizada(guia))
    with engine_generacion.connect() as c:
        cand = buscar_candidatos(c, normalizar(CONSULTA), servicios, _parametros(c))
        r = seleccionar(c, normalizar(CONSULTA), cand, servicios.reranker, _parametros(c))
    assert cand.posiciones_bm25[sustituido] == 1
    assert sustituido not in {f.id_fragmento for f in r.fragmentos}
    assert sustituido in r.descartados
    assert r.seleccionados and r.seleccionados[0].id_fragmento == guia["ids"]["preventiva"]


def test_el_indice_bm25_real_excluye_los_no_vigentes(engine_generacion, guia):
    with engine_generacion.connect() as c:
        indice = CacheBM25().obtener(c)
    assert guia["ids"]["preventiva"] in indice.ids and guia["ids"]["sustituido"] not in indice.ids


def test_la_recomprobacion_descarta_un_fragmento_marcado_no_vigente_despues(engine_generacion, super_engine, guia):
    preventiva = guia["ids"]["preventiva"]
    servicios = _servicios(guia)
    with engine_generacion.connect() as c:
        p = _parametros(c)
        cand = buscar_candidatos(c, normalizar(CONSULTA), servicios, p)
        assert preventiva in {i for i, _, _ in cand.fusionados}
        with super_engine.begin() as s:
            s.execute(text("""UPDATE conocimiento.fragmento SET vigente = false, motivo_exclusion = 'Prueba'
                               WHERE id_fragmento = :i"""), {"i": preventiva})
        r = seleccionar(c, normalizar(CONSULTA), cand, servicios.reranker, p)
    assert preventiva not in {f.id_fragmento for f in r.fragmentos} and preventiva in r.descartados


def test_el_indice_bm25_se_reconstruye_cuando_cambia_la_base(engine_generacion, super_engine, guia):
    cache = CacheBM25()
    with engine_generacion.connect() as c:
        cache.obtener(c)
        cache.obtener(c)
        assert cache.reconstrucciones == 1
        with super_engine.begin() as s:
            s.execute(text("""UPDATE conocimiento.fragmento SET vigente = false, motivo_exclusion = 'Prueba'
                               WHERE id_fragmento = :i"""), {"i": guia["ids"]["tratamiento"]})
        indice = cache.obtener(c)
    assert cache.reconstrucciones == 2 and guia["ids"]["tratamiento"] not in indice.ids


def test_busqueda_ampliada_cuando_no_se_alcanza_el_umbral(engine_generacion, guia):
    with engine_generacion.connect() as c:
        p = _parametros(c, umbral_relevancia=0.99)
        pasadas = recuperar_con_ampliacion(c, normalizar("hierro para el bebito"), _servicios(guia), p)
    assert [r.tipo_busqueda for r in pasadas] == [INICIAL, AMPLIADA]
    inicial, ampliada = pasadas
    assert not inicial.suficiente and inicial.candidatos_por_metodo == p.candidatos_busqueda
    assert ampliada.candidatos_por_metodo == p.candidatos_busqueda_ampliada
    assert "lactante" in ampliada.consulta and "iron" in ampliada.consulta


def test_sin_ampliada_cuando_la_inicial_alcanza_el_umbral(engine_generacion, guia):
    with engine_generacion.connect() as c:
        pasadas = recuperar_con_ampliacion(c, normalizar(CONSULTA), _servicios(guia), _parametros(c))
    assert len(pasadas) == 1 and pasadas[0].suficiente


def test_resultado_con_los_campos_que_necesita_el_orquestador(engine_generacion, guia):
    with engine_generacion.connect() as c:
        p = _parametros(c)
        r = recuperar(c, normalizar(CONSULTA), _servicios(guia), p)
    assert r.tipo_busqueda == INICIAL and r.umbral_relevancia == p.umbral_relevancia
    assert r.relevancia_maxima == max(f.puntaje_reranker for f in r.fragmentos)
    assert r.candidatos_evaluados == len(r.fragmentos) + len([d for d in r.descartados if d != guia["ids"]["sustituido"]])
    assert {"embedding", "bm25", "chromadb", "rrf", "postgresql", "reranker", "recomprobacion"} <= r.tiempos_ms.keys()
    assert [f.posicion_final for f in r.fragmentos] == list(range(1, len(r.fragmentos) + 1))
    assert len(r.seleccionados) <= p.fragmentos_enviados
    for f in r.fragmentos:
        assert f.id_fragmento and f.id_documento == guia["id_documento"]
        assert f.posicion_bm25 is not None or f.posicion_vectorial is not None
        assert f.posicion_rrf >= 1 and f.puntaje_rrf > 0 and 0 <= f.puntaje_reranker <= 1
        assert f.documento == "Guía de prueba de la recuperación" and f.codigo_documento == "PRUEBA-RAG"
        assert f.seccion.startswith("Sección") and f.pagina_inicio == f.pagina_fin and f.idioma == "es"
        assert f.texto and f.tipo_contenido == "TEXTO"
        assert f.seleccionado == (f in r.seleccionados)
    assert all(f.puntaje_reranker >= p.umbral_relevancia for f in r.seleccionados)


# ---------------------------------------------------------------------------
# Texto libre sin filtrar
# ---------------------------------------------------------------------------
@pytest.fixture
def sentencias():
    capturadas: list[str] = []

    def _capturar(conn, cursor, sql, parametros, contexto, varios):
        capturadas.append(sql)

    event.listen(Engine, "before_cursor_execute", _capturar)
    yield capturadas
    event.remove(Engine, "before_cursor_execute", _capturar)


def test_ningun_modulo_de_b_consulta_texto_consulta_ni_observaciones(engine_clinica, engine_generacion, super_engine,
                                                                     guia, crear_tamizaje, sentencias):
    fecha = date(2026, 10, 1)
    id_tamizaje = crear_tamizaje(fecha)
    id_consulta = str(uuid.uuid4())
    with super_engine.begin() as c:
        c.execute(text(
            """INSERT INTO asistencia.consulta (id_consulta, id_tamizaje, id_usuario, texto_consulta, texto_filtrado)
               VALUES (:c, :t, :u, 'Texto original con datos que no se leen', :f)"""),
            {"c": id_consulta, "t": id_tamizaje, "u": SISTEMA, "f": CONSULTA})
    crear_tamizaje.consultas.append(id_consulta)
    sentencias.clear()

    with engine_clinica.begin() as c:
        validar_tamizaje(c, id_tamizaje, fecha_referencia=fecha)
    with engine_generacion.connect() as c:
        texto_filtrado = leer_texto_filtrado(c, id_consulta)
        recuperar_con_ampliacion(c, normalizar(texto_filtrado), _servicios(guia), _parametros(c))

    assert texto_filtrado == CONSULTA
    assert sentencias, "no se capturaron sentencias"
    for sql in sentencias:
        assert "texto_consulta" not in sql and "observaciones" not in sql
