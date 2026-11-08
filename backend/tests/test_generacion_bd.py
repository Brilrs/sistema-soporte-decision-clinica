"""Parte C contra PostgreSQL, con modelos falsos, ChromaDB en memoria y el cliente falso
del modelo de lenguaje (nunca la API real): los casos de punta a punta, cada fila de la
Tabla 10, el bloqueo por el control previo, la lista blanca ante una columna nueva, los
triggers de recomendacion y cita_evidencia y que cdss_generacion no lea texto libre."""
import os
import uuid
from dataclasses import replace
from datetime import date

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.exc import DBAPIError

from app.core.modelos import EmbedderFalso, RerankerFalso
from app.core.vectores import AlmacenMemoria, RegistroVector
from app.rag.bm25 import CacheBM25
from app.rag.cliente_llm import (APROBADA, CITA_INVENTADA, CORTADA_MAX_TOKENS, ERROR_API, ESQUEMA_INVALIDO,
                                 EVIDENCIA_INSUFICIENTE, RECHAZO, TIEMPO_AGOTADO, ClienteFalso)
from app.rag.dominio import FiltroDominio
from app.rag.filtro_texto import HuellasPaciente, IdentidadPaciente, generar_huellas
from app.rag.parametros import parametros_recuperacion
from app.rag.proteccion import construir_solicitud, leer_datos_clinicos, serializar
from app.rag.recuperacion import Servicios
from app.rag.verificacion import MENSAJE_EVIDENCIA_INSUFICIENTE, MENSAJE_NO_EVALUADA
from app.scripts import prueba_punta_a_punta as e2e

SISTEMA = "00000000-0000-0000-0000-000000000001"
GUIA_MINSA = [
    "Suplementación preventiva con hierro en niños de 6 a 11 meses sin anemia: sulfato ferroso en gotas "
    "2 mg/kg/día; se vuelve a medir la hemoglobina a los 6 meses de iniciada la suplementación.",
    "Tratamiento de la anemia leve y moderada en niños de 6 a 59 meses: sulfato ferroso 3 mg/kg/día durante "
    "6 meses, con control de hemoglobina al mes, a los 3 y a los 6 meses de iniciado el tratamiento.",
    "Anemia severa: referir a un establecimiento de mayor capacidad resolutiva para su manejo y seguimiento.",
    "Ajuste de la hemoglobina por la altitud de residencia antes de clasificar la anemia en el niño.",
    "Repetir el tamizaje de hemoglobina cuando el resultado registrado ya no es vigente.",
]
GUIA_OMS = [
    "WHO (OMS) recommends daily iron supplementation (suplementación con hierro) with 30 mg elemental iron "
    "for children aged 24 to 59 months where anaemia prevalence is 40% or higher.",
]


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


def _documento(c, codigo: str, entidad: str, idioma: str, textos: list[str], almacen: AlmacenMemoria) -> dict:
    id_doc = str(uuid.uuid4())
    c.execute(text(
        """INSERT INTO conocimiento.documento_fuente
             (id_documento, titulo, codigo_documento, entidad_emisora, tipo_documento, nivel, anio_publicacion,
              idioma, cargado_por, estado_indexacion, ruta_blob, hash_archivo, total_fragmentos)
           VALUES (:id, :t, :cod, :ent, 'GUIA', 1, 2024, :idioma, :u, 'COMPLETADA', 'local://prueba/c.pdf', :h, :n)"""
    ), {"id": id_doc, "t": f"Guía de prueba {codigo}", "cod": codigo, "ent": entidad, "idioma": idioma, "u": SISTEMA,
        "h": uuid.uuid4().hex * 2, "n": len(textos)})
    ids = []
    for orden, texto in enumerate(textos, start=1):
        id_f = str(uuid.uuid4())
        ids.append(id_f)
        c.execute(text(
            """INSERT INTO conocimiento.fragmento
                 (id_fragmento, id_documento, numero_orden, seccion, pagina_inicio, pagina_fin, texto, numero_tokens,
                  modelo_embedding, vigente)
               VALUES (:id, :doc, :o, :s, :o, :o, :t, 40, 'falso', true)"""),
            {"id": id_f, "doc": id_doc, "o": orden, "s": f"Sección {orden}", "t": texto})
        vector = EmbedderFalso().embeber([texto])[0]
        almacen.agregar([RegistroVector(id_f, vector, texto, {
            "id_documento": id_doc, "nivel": 1, "estado_documento": "VIGENTE", "vigente": True, "idioma": idioma})])
    return {"id_documento": id_doc, "ids": ids}


@pytest.fixture
def guia(super_engine):
    almacen = AlmacenMemoria()
    with super_engine.begin() as c:
        docs = [_documento(c, "PRUEBA-C-MINSA", "MINSA", "es", GUIA_MINSA, almacen),
                _documento(c, "PRUEBA-C-OMS", "OMS", "en", GUIA_OMS, almacen)]
    yield {"almacen": almacen, "docs": docs}
    with super_engine.begin() as c:
        for d in docs:
            c.execute(text("DELETE FROM conocimiento.fragmento WHERE id_documento = :id"), {"id": d["id_documento"]})
            c.execute(text("DELETE FROM conocimiento.documento_fuente WHERE id_documento = :id"),
                      {"id": d["id_documento"]})


@pytest.fixture
def consultas(super_engine):
    """Ids de las consultas creadas; al final se eliminan con la conexión de administración."""
    ids: list[str] = []
    yield ids
    if not ids:
        return
    with super_engine.begin() as c:
        p = {"ids": ids}
        intentos = "(SELECT id_intento FROM asistencia.intento_generacion WHERE id_consulta::text = ANY(:ids))"
        c.execute(text(f"DELETE FROM asistencia.cita_evidencia WHERE id_intento IN {intentos}"), p)
        c.execute(text("DELETE FROM asistencia.recomendacion WHERE id_consulta::text = ANY(:ids)"), p)
        c.execute(text(f"DELETE FROM asistencia.fragmento_recuperado WHERE id_intento IN {intentos}"), p)
        c.execute(text("DELETE FROM asistencia.intento_generacion WHERE id_consulta::text = ANY(:ids)"), p)
        c.execute(text("DELETE FROM asistencia.dato_faltante WHERE id_consulta::text = ANY(:ids)"), p)
        c.execute(text("DELETE FROM asistencia.consulta WHERE id_consulta::text = ANY(:ids)"), p)


@pytest.fixture
def entorno(engine_clinica, engine_generacion, guia):
    servicios = Servicios(EmbedderFalso(), RerankerFalso(), guia["almacen"], CacheBM25())
    fecha, _ = e2e.cargar_casos()
    with engine_generacion.connect() as c:
        # Con el reranker falso los puntajes son proporciones de términos: umbral bajo y
        # todos los fragmentos de la guía de prueba enviados.
        parametros = replace(parametros_recuperacion(c), umbral_relevancia=0.05, fragmentos_enviados=6)
    return e2e.Entorno(engine_clinica, engine_generacion, servicios, FiltroDominio(EmbedderFalso()), fecha, parametros)


def _caso(id_caso: str) -> dict:
    return next(c for c in e2e.cargar_casos()[1] if c["id"] == id_caso)


def _ejecutar(entorno, consultas, caso: dict, modos=None, preferir_ingles=None) -> e2e.ResultadoCaso:
    cliente = e2e.cliente_para(caso, "falso")
    if modos is not None:
        cliente = ClienteFalso(modos, preferir_ingles=bool(preferir_ingles))
    r = e2e.ejecutar_caso(entorno, caso, cliente)
    if r.id_consulta:
        consultas.append(r.id_consulta)
    r.cliente = cliente
    return r


def _intentos(super_engine, id_consulta: str):
    with super_engine.connect() as c:
        return c.execute(text(
            """SELECT numero_intento, tipo_busqueda, resultado, control_identificadores, hash_solicitud,
                      solicitud_enviada::text AS solicitud, tokens_razonamiento, valida_citas, valida_consistencia,
                      valida_evidencia, modelo_llm, version_prompt, costo_usd
                 FROM asistencia.intento_generacion WHERE id_consulta = CAST(:c AS uuid) ORDER BY numero_intento"""),
            {"c": id_consulta}).all()


def _estado(super_engine, id_consulta: str) -> tuple:
    with super_engine.connect() as c:
        return c.execute(text("SELECT estado, numero_intentos, texto_filtrado, idioma_respuesta FROM asistencia.consulta "
                              "WHERE id_consulta = CAST(:c AS uuid)"), {"c": id_consulta}).one()


# ---------------------------------------------------------------------------
# Casos de punta a punta con el cliente falso
# ---------------------------------------------------------------------------
def test_los_casos_de_punta_a_punta_dan_el_estado_esperado(entorno, consultas, super_engine):
    _, casos = e2e.cargar_casos()
    assert {c["id"] for c in casos} == set("abcdefghijkl")
    resultados = {c["id"]: _ejecutar(entorno, consultas, c) for c in casos}
    for id_caso, r in resultados.items():
        assert r.estado == r.esperado, (id_caso, r.estado, r.intentos)
        assert _estado(super_engine, r.id_consulta).estado == r.esperado
        enviados = [i for i in _intentos(super_engine, r.id_consulta) if i.modelo_llm is not None]
        assert all(i.control_identificadores is True and len(i.hash_solicitud) == 64 for i in enviados)
        for i in enviados:
            assert "Mateo" not in i.solicitud and "81234567" not in i.solicitud and "00452" not in i.solicitud
            assert i.version_prompt == "v1.1" and i.costo_usd is not None
        for i in r.intentos:
            assert set(i["tiempos_ms"]) == {"recuperacion", "proteccion", "llamada_modelo", "verificacion"}
            if i.get("generacion"):
                assert i["stop_reason"] and i["fragmentos_enviados"] and i["respuesta_modelo"] is not None

    assert not _intentos(super_engine, resultados["g"].id_consulta)
    assert not _intentos(super_engine, resultados["h"].id_consulta)
    assert resultados["j"].mensaje == MENSAJE_EVIDENCIA_INSUFICIENTE
    assert [i.tipo_busqueda for i in _intentos(super_engine, resultados["j"].id_consulta)] == ["INICIAL", "AMPLIADA"]
    assert resultados["i"].texto_filtrado == ("¿Qué tratamiento con hierro le doy a [PACIENTE], DNI [DNI], HC [HC]? "
                                              "Su mamá llama al [TELEFONO].")
    assert _estado(super_engine, resultados["k"].id_consulta).idioma_respuesta == "en"
    assert resultados["k"].cliente.llamadas[0]["solicitud"]["idioma_respuesta"] == "en"
    assert _estado(super_engine, resultados["a"].id_consulta).idioma_respuesta == "es"

    with super_engine.connect() as c:
        oms = c.execute(text(
            """SELECT ce.texto_citado, ce.extracto_traducido FROM asistencia.cita_evidencia ce
                 JOIN asistencia.recomendacion r ON r.id_recomendacion = ce.id_recomendacion
                 JOIN conocimiento.fragmento f ON f.id_fragmento = ce.id_fragmento
                 JOIN conocimiento.documento_fuente d ON d.id_documento = f.id_documento
                WHERE r.id_consulta = CAST(:c AS uuid) AND d.idioma = 'en'"""),
            {"c": resultados["l"].id_consulta}).all()
        assert oms and all(t is not None for _, t in oms)
        derivacion = c.execute(text("SELECT texto_recomendacion FROM asistencia.recomendacion "
                                    "WHERE id_consulta = CAST(:c AS uuid)"), {"c": resultados["d"].id_consulta}).scalar()
        assert "Referir" in derivacion


def test_tamizaje_no_vigente_sin_confirmar_no_pasa_a_la_generacion(entorno, consultas, super_engine):
    caso = {**_caso("f"), "confirma_tamizaje_no_vigente": False}
    r = _ejecutar(entorno, consultas, caso)
    assert r.estado == "TAMIZAJE_NO_VIGENTE" and not _intentos(super_engine, r.id_consulta)


def test_rechaza_un_paciente_que_no_es_de_seed_demo(entorno, consultas):
    with pytest.raises(e2e.ErrorCaso):
        _ejecutar(entorno, consultas, {**_caso("b"), "dni": "12345678"})


# ---------------------------------------------------------------------------
# Filas de la Tabla 10 de punta a punta
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("modos, estado, resultados, mensaje", [
    ([CITA_INVENTADA, APROBADA], "VERIFICADA", ["REINTENTO", "APROBADO"], None),
    ([CITA_INVENTADA, CITA_INVENTADA], "EVIDENCIA_INSUFICIENTE", ["REINTENTO", "EVIDENCIA_INSUFICIENTE"],
     MENSAJE_EVIDENCIA_INSUFICIENTE),
    ([ESQUEMA_INVALIDO, APROBADA], "VERIFICADA", ["REINTENTO", "APROBADO"], None),
    ([CORTADA_MAX_TOKENS, APROBADA], "VERIFICADA", ["REINTENTO", "APROBADO"], None),
    ([CORTADA_MAX_TOKENS, CORTADA_MAX_TOKENS], "ERROR", ["REINTENTO", "ERROR"], MENSAJE_NO_EVALUADA),
    ([EVIDENCIA_INSUFICIENTE, APROBADA], "VERIFICADA", ["REINTENTO", "APROBADO"], None),
    ([TIEMPO_AGOTADO], "ERROR", ["ERROR"], MENSAJE_NO_EVALUADA),
    ([RECHAZO], "ERROR", ["ERROR"], MENSAJE_NO_EVALUADA),
    ([ERROR_API], "ERROR", ["ERROR"], MENSAJE_NO_EVALUADA),
])
def test_filas_de_la_tabla_10(entorno, consultas, super_engine, modos, estado, resultados, mensaje):
    r = _ejecutar(entorno, consultas, _caso("b"), modos)
    assert (r.estado, r.mensaje) == (estado, mensaje)
    intentos = _intentos(super_engine, r.id_consulta)
    assert [i.resultado for i in intentos] == resultados
    assert _estado(super_engine, r.id_consulta).numero_intentos == len(resultados)
    assert len(r.cliente.llamadas) == len(resultados)
    if modos[0] == EVIDENCIA_INSUFICIENTE:
        assert [i.tipo_busqueda for i in intentos] == ["INICIAL", "AMPLIADA"]
    elif len(intentos) == 2:
        assert [i.tipo_busqueda for i in intentos] == ["INICIAL", "INICIAL"]
    if modos[0] == CORTADA_MAX_TOKENS:
        assert intentos[0].tokens_razonamiento == r.cliente.llamadas[0]["config"].max_tokens // 2
        assert intentos[0].valida_citas is None
    if modos[0] == CITA_INVENTADA:
        assert intentos[0].valida_citas is False


def test_sin_fragmentos_sobre_el_umbral_no_llama_al_modelo(entorno, consultas, super_engine):
    entorno.parametros = replace(entorno.parametros, umbral_relevancia=0.99)
    r = _ejecutar(entorno, consultas, _caso("b"), [APROBADA])
    assert r.estado == "EVIDENCIA_INSUFICIENTE" and not r.cliente.llamadas
    intentos = _intentos(super_engine, r.id_consulta)
    assert [(i.tipo_busqueda, i.resultado, i.valida_evidencia, i.solicitud) for i in intentos] == [
        ("INICIAL", "REINTENTO", False, None), ("AMPLIADA", "EVIDENCIA_INSUFICIENTE", False, None)]


# ---------------------------------------------------------------------------
# Control previo al envío
# ---------------------------------------------------------------------------
def test_solicitud_bloqueada_queda_en_error_sin_enviarse_y_se_audita(entorno, consultas, super_engine):
    caso = _caso("b")
    r, id_tamizaje, _ = e2e.etapa_clinica(entorno, caso)
    consultas.append(r.id_consulta)
    # Huellas de un «paciente» cuyo apellido aparece en los fragmentos de evidencia.
    huellas = generar_huellas(IdentidadPaciente("Ana Ferroso", "11111111", "99999"))
    cliente = ClienteFalso([APROBADA])
    r = e2e.etapa_generacion(entorno, r, id_tamizaje, huellas, cliente)
    assert (r.estado, r.mensaje) == ("ERROR", MENSAJE_NO_EVALUADA) and not cliente.llamadas
    (i,) = _intentos(super_engine, r.id_consulta)
    assert (i.resultado, i.control_identificadores, i.solicitud, i.modelo_llm) == ("ERROR", False, None, None)
    assert len(i.hash_solicitud) == 64
    with super_engine.connect() as c:
        detalle = c.execute(text("SELECT detalle::text FROM auditoria.evento_auditoria WHERE tipo_evento = "
                                 "'SOLICITUD_BLOQUEADA' AND id_entidad = :c"), {"c": r.id_consulta}).scalar_one()
    assert "ferroso" not in detalle.lower() and i.hash_solicitud in detalle


def test_huellas_vacias_no_bloquean(entorno, consultas):
    caso = _caso("b")
    r, id_tamizaje, _ = e2e.etapa_clinica(entorno, caso)
    consultas.append(r.id_consulta)
    r = e2e.etapa_generacion(entorno, r, id_tamizaje, HuellasPaciente(frozenset()), ClienteFalso([APROBADA]))
    assert r.estado == "VERIFICADA"


# ---------------------------------------------------------------------------
# Lista blanca y permisos
# ---------------------------------------------------------------------------
def _tamizaje_de(engine_clinica, dni: str, fecha: date) -> str:
    with engine_clinica.connect() as c:
        return e2e._tamizaje(c, dni, fecha)


def test_una_columna_nueva_de_la_base_no_llega_a_la_solicitud(super_engine, engine_clinica, engine_generacion):
    id_tamizaje = _tamizaje_de(engine_clinica, "81234567", date(2026, 9, 26))
    with super_engine.begin() as c:
        c.execute(text("ALTER TABLE clinico.paciente ADD COLUMN columna_nueva_prueba TEXT DEFAULT 'VALOR-NUEVO-SECRETO'"))
    try:
        with engine_generacion.connect() as c:
            assert c.execute(text("SELECT columna_nueva_prueba FROM clinico.paciente LIMIT 1")).scalar() \
                == "VALOR-NUEVO-SECRETO"
            datos = leer_datos_clinicos(c, id_tamizaje)
        solicitud = construir_solicitud(datos, "consulta", "es", [], {})
        assert "VALOR-NUEVO-SECRETO" not in solicitud.serializada and "columna_nueva" not in solicitud.serializada
    finally:
        with super_engine.begin() as c:
            c.execute(text("ALTER TABLE clinico.paciente DROP COLUMN columna_nueva_prueba"))


def test_datos_clinicos_con_el_tamizaje_anterior_en_meses(engine_clinica, engine_generacion):
    id_tamizaje = _tamizaje_de(engine_clinica, "81234567", date(2026, 9, 26))
    with engine_generacion.connect() as c:
        datos = leer_datos_clinicos(c, id_tamizaje)
    assert (datos.edad_meses, datos.sexo, datos.clasificacion, datos.peso_kg) == (14, "M", "ANEMIA_LEVE", 9.6)
    assert datos.tamizaje_anterior == {"meses_transcurridos": 4, "hb_g_dl": 10.1, "clasificacion": "ANEMIA_LEVE"}
    assert datos.sintomas == ("Hiporexia", "Palidez")
    texto = serializar(construir_solicitud(datos, "c", "es", [], {}).contenido)
    assert "2026" not in texto and "76.5" not in texto and "poco apetito" not in texto


@pytest.mark.parametrize("sql", [
    "SELECT nombres_apellidos_cifrado FROM clinico.paciente_identidad LIMIT 1",
    "SELECT texto_consulta FROM asistencia.consulta LIMIT 1",
    "UPDATE asistencia.consulta SET texto_filtrado = 'x' WHERE false",
])
def test_cdss_generacion_no_lee_identidad_ni_texto_libre_ni_cambia_el_texto_filtrado(engine_generacion, sql):
    with engine_generacion.connect() as c, pytest.raises(DBAPIError):
        c.execute(text(sql))


def test_cdss_generacion_no_consulta_texto_consulta_ni_observaciones(entorno, consultas, engine_generacion):
    capturadas: list[str] = []

    def _capturar(conn, cursor, sql, parametros, contexto, varios):
        capturadas.append(sql)

    caso = _caso("i")
    r, id_tamizaje, huellas = e2e.etapa_clinica(entorno, caso)
    consultas.append(r.id_consulta)
    event.listen(engine_generacion, "before_cursor_execute", _capturar)
    try:
        r = e2e.etapa_generacion(entorno, r, id_tamizaje, huellas, ClienteFalso([APROBADA]))
    finally:
        event.remove(engine_generacion, "before_cursor_execute", _capturar)
    assert r.estado == "VERIFICADA" and capturadas
    for sql in capturadas:
        assert "texto_consulta" not in sql and "observaciones" not in sql and "paciente_identidad" not in sql


def test_parametros_de_la_generacion(engine_generacion):
    from app.rag.generacion import configuracion_generacion
    with engine_generacion.connect() as c:
        config = configuracion_generacion(c)
    assert (config.llm.modelo, config.llm.max_tokens, config.llm.timeout_s) == ("claude-sonnet-5-5", 1500, 15)
    assert (config.llm.razonamiento, config.llm.esfuerzo, config.version_prompt) == ("between_tools", "medium", "v1.1")
    assert (config.precio_entrada_usd_mtok, config.precio_salida_usd_mtok) == (2, 10)


# ---------------------------------------------------------------------------
# Triggers de la base
# ---------------------------------------------------------------------------
def test_triggers_rechazan_citar_un_fragmento_no_enviado(entorno, consultas, super_engine, engine_generacion, guia):
    r = _ejecutar(entorno, consultas, _caso("b"), [CITA_INVENTADA, APROBADA])
    with super_engine.connect() as c:
        intentos = dict(c.execute(text("SELECT numero_intento, id_intento::text FROM asistencia.intento_generacion "
                                       "WHERE id_consulta = CAST(:c AS uuid)"), {"c": r.id_consulta}).all())
        id_recomendacion = c.execute(text("SELECT id_recomendacion::text FROM asistencia.recomendacion "
                                          "WHERE id_consulta = CAST(:c AS uuid)"), {"c": r.id_consulta}).scalar_one()
    otro = str(uuid.uuid4())
    with super_engine.begin() as c:
        # Un fragmento recuperado en el intento aprobado pero no enviado al modelo.
        no_enviado = guia["docs"][0]["ids"][0]
        c.execute(text("UPDATE asistencia.fragmento_recuperado SET enviado_al_llm = false, etiqueta_cita = NULL "
                       "WHERE id_intento = CAST(:i AS uuid) AND id_fragmento = CAST(:f AS uuid)"),
                  {"i": intentos[2], "f": no_enviado})
    citas = [(intentos[2], no_enviado, "fragmento enviado"), (intentos[1], guia["docs"][0]["ids"][1], "fragmento enviado"),
             (intentos[2], otro, "fragmento enviado")]
    for id_intento, id_fragmento, mensaje in citas:
        with engine_generacion.connect() as c, pytest.raises(DBAPIError, match=mensaje):
            c.execute(text(
                """INSERT INTO asistencia.cita_evidencia (id_recomendacion, id_intento, id_fragmento, orden, texto_citado)
                   VALUES (CAST(:r AS uuid), CAST(:i AS uuid), CAST(:f AS uuid), 99, 'x')"""),
                {"r": id_recomendacion, "i": id_intento, "f": id_fragmento})


def test_trigger_rechaza_una_recomendacion_de_un_intento_no_aprobado(entorno, consultas, super_engine,
                                                                    engine_generacion):
    r = _ejecutar(entorno, consultas, _caso("j"))
    assert r.estado == "EVIDENCIA_INSUFICIENTE"
    for i in _intentos(super_engine, r.id_consulta):
        assert i.resultado != "APROBADO"
    with super_engine.connect() as c:
        id_intento = c.execute(text("SELECT id_intento::text FROM asistencia.intento_generacion "
                                    "WHERE id_consulta = CAST(:c AS uuid) AND numero_intento = 2"),
                               {"c": r.id_consulta}).scalar_one()
    with engine_generacion.connect() as c, pytest.raises(DBAPIError, match="intento aprobado"):
        c.execute(text("""INSERT INTO asistencia.recomendacion (id_consulta, id_intento, texto_recomendacion)
                          VALUES (CAST(:c AS uuid), CAST(:i AS uuid), 'x')"""), {"c": r.id_consulta, "i": id_intento})


MIGRACION_006 = os.path.join(os.path.dirname(__file__), "..", "..", "db", "migraciones", "006_parametros_generacion.sql")


def test_migracion_006_es_idempotente(super_engine):
    sql = open(MIGRACION_006, encoding="utf-8").read()
    consulta = text("SELECT count(*) FROM configuracion.parametro_sistema WHERE clave IN ('RAZONAMIENTO_LLM', 'ESFUERZO_LLM')")
    with super_engine.begin() as c:
        antes = c.execute(consulta).scalar_one()
        c.exec_driver_sql(sql)
        c.exec_driver_sql(sql)
        assert c.execute(consulta).scalar_one() == antes == 2
        assert c.execute(text("SELECT count(*) FROM information_schema.columns WHERE table_schema = 'asistencia' "
                              "AND table_name = 'intento_generacion' AND column_name = 'tokens_razonamiento'")).scalar_one() == 1


MIGRACION_007 = os.path.join(os.path.dirname(__file__), "..", "..", "db", "migraciones", "007_salida_compacta.sql")


def test_migracion_007_sube_max_tokens_y_la_version_del_prompt_con_historial(super_engine):
    sql = open(MIGRACION_007, encoding="utf-8").read()
    with super_engine.begin() as c:
        c.exec_driver_sql(sql)
        c.exec_driver_sql(sql)
        filas = c.execute(text(
            """SELECT clave, valor, vigente_hasta IS NULL AS vigente FROM configuracion.parametro_sistema
                WHERE clave IN ('MAX_TOKENS_SALIDA', 'VERSION_PROMPT') ORDER BY clave, vigente_desde""")).all()
    assert [(f.clave, f.valor, f.vigente) for f in filas] == [
        ("MAX_TOKENS_SALIDA", "1000", False), ("MAX_TOKENS_SALIDA", "1500", True),
        ("VERSION_PROMPT", "v1.0", False), ("VERSION_PROMPT", "v1.1", True)]


def test_la_recuperacion_usa_la_consulta_estructurada_mas_el_texto_filtrado(entorno, consultas, super_engine):
    r = _ejecutar(entorno, consultas, _caso("a"))
    with super_engine.connect() as c:
        reformulada = c.execute(text("SELECT consulta_reformulada FROM asistencia.intento_generacion "
                                     "WHERE id_consulta = CAST(:c AS uuid) AND numero_intento = 1"),
                                {"c": r.id_consulta}).scalar_one()
    assert reformulada.startswith("lactante de 9 meses, sin anemia")
    assert reformulada.endswith("cuando se vuelve a medir la hemoglobina?")
    # Al modelo se le envía como consulta solo la pregunta filtrada.
    assert r.cliente.llamadas[0]["solicitud"]["consulta"] == r.texto_filtrado
