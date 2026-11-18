"""Parte G (pendiente P4): regla de punteros «según Tabla N° X».

Unidad: carga de punteros.yaml contra el mapa de la RM 429, patrón, reemplazo del 5.º, tope de un
fragmento, que no se active si la tabla ya está, constancia en la solicitud y control 6.1 con el
fragmento agregado. Base de pruebas: tope de 600 tokens al resolver el destino, origen PUNTERO en
fragmento_recuperado (con posición y puntaje RRF nulos solo con PUNTERO, restricción de la
migración 012), relevancia máxima (6.3) igual con y sin la regla, y la cita del fragmento agregado
en el evento fin y en el GET con origen y referencia."""
import re
import uuid
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.api.routes import consultas as rutas
from app.core.modelos import EmbedderFalso
from app.core.vectores import RegistroVector
from app.rag import punteros as pt
from app.rag import recuperacion as rec
from app.rag import verificacion as ver
from app.rag.cliente_llm import APROBADA, ClienteFalso
from app.rag.normalizacion import normalizar
from app.rag.proteccion import DatosClinicos, construir_solicitud
from app.scripts import prueba_punta_a_punta as e2e
from tests.test_d1_grafo import _caso, _ids, entorno  # noqa: F401 (fixtures)
from tests.test_d2_api import _consultar, _cuerpo, cliente_http, consultas_d2, usar_entorno  # noqa: F401 (fixtures)
from tests.test_generacion_bd import GUIA_MINSA, SISTEMA, engine_clinica, engine_generacion, guia  # noqa: F401

REGLA_PRUEBA = pt.ReglaPuntero(
    id="prueba-tabla9", documento_origen="PRUEBA-G-ORIGEN", patron=re.compile(r"según\s+Tabla\s+N\s*[°º]\s*9\b", re.I),
    documento_destino="PRUEBA-G-DESTINO", marca_seccion="(mod. PRUEBA-G-DESTINO, modificación N.° 1)")
OTRA_REGLA = replace(REGLA_PRUEBA, id="prueba-tabla8", patron=re.compile(r"según\s+Tabla\s+N\s*[°º]\s*8\b", re.I),
                     marca_seccion="(mod. PRUEBA-G-DESTINO, modificación N.° 2)")
# Sin términos de las consultas de prueba: no entra a BM25 y, fuera de la colección vectorial, no es
# candidato de la fusión (el destino agregado queda sin posición ni puntaje RRF).
TABLA_9 = "Tabla N° 9\nCuadro ficticio\n\n| Columna | Valor |\n| --- | --- |\n| Fila uno | Valor uno |"


# ---------------------------------------------------------------------------
# Unidad
# ---------------------------------------------------------------------------
def _frag(id_: str, puntaje: float | None, seleccionado: bool, codigo: str = "OTRO", texto: str = "texto",
          posicion_rrf: int | None = 1) -> rec.FragmentoRecuperado:
    return rec.FragmentoRecuperado(
        id_fragmento=id_, posicion_bm25=None, posicion_vectorial=None, posicion_rrf=posicion_rrf,
        puntaje_rrf=None if posicion_rrf is None else 0.01, puntaje_reranker=puntaje, posicion_final=None,
        seleccionado=seleccionado, id_documento="doc", documento="Documento", codigo_documento=codigo, seccion="s",
        pagina_inicio=1, pagina_fin=1, idioma="es", tipo_contenido="TEXTO", texto=texto)


def _destino(id_: str = "destino"):
    return SimpleNamespace(id_fragmento=id_, id_documento="doc-destino", titulo="Destino",
                           codigo_documento="PRUEBA-G-DESTINO", idioma="es", seccion="Tabla 9 " + REGLA_PRUEBA.marca_seccion,
                           pagina_inicio=6, pagina_fin=6, texto=TABLA_9, tipo_contenido="TABLA", edad_min_meses=None,
                           edad_max_meses=None, poblacion="GENERAL", rango_dudoso=False, numero_tokens=120)


def _cinco(con_puntero_en: int = 1) -> list[rec.FragmentoRecuperado]:
    fr = [_frag(f"f{i}", 0.9 - i / 10, True) for i in range(5)]
    fr[con_puntero_en] = _frag(f"f{con_puntero_en}", fr[con_puntero_en].puntaje_reranker, True, "PRUEBA-G-ORIGEN",
                               "Se mide la hemoglobina según Tabla N° 9, considerando la edad.")
    return fr + [_frag("f5", 0.1, False), _frag("f6", 0.05, False)]


@pytest.fixture
def destinos(monkeypatch):
    """buscar_destino de prueba: un destino por regla (por la marca de la sección)."""
    tabla = {REGLA_PRUEBA.marca_seccion: _destino("destino"), OTRA_REGLA.marca_seccion: _destino("destino-8")}
    monkeypatch.setattr(rec, "buscar_destino", lambda sesion, regla: tabla.get(regla.marca_seccion))
    return tabla


def test_la_regla_de_la_tabla_4_carga_contra_el_mapa_de_la_rm_429():
    (regla,) = pt.cargar_reglas()
    assert regla.id == "nts213-tabla4"
    assert regla.documento_origen == "NTS 213-MINSA/DGIESP-2024"
    assert regla.documento_destino == "RM 429-2024/MINSA"
    assert regla.marca_seccion == "(mod. RM 429-2024/MINSA, modificación N.° 5)"
    puntero = ("A. Medición de hemoglobina La medición de Hb se realiza a toda/o niña/o ... en el primer contacto con "
               "el establecimiento de salud, según Tabla N° 4, considerando los valores")
    assert regla.aplica_a("NTS 213-MINSA/DGIESP-2024", puntero)
    # Por documento y no por número: el mismo texto en otro documento, otra tabla o la OMS no aplican.
    assert not regla.aplica_a("OMS 2024", puntero)
    assert not regla.aplica_a("NTS 213-MINSA/DGIESP-2024", "según Tabla N° 40")
    assert not regla.aplica_a("NTS 213-MINSA/DGIESP-2024", "en la niña menor de 6 meses (Tabla N° 4)")
    assert not regla.aplica_a("OMS 2024", "Table 4 presents a common set of adjustments")


def test_una_regla_que_no_coincide_con_el_mapa_no_carga(tmp_path):
    ruta = tmp_path / "punteros.yaml"
    ruta.write_text("reglas:\n  - {id: x, documento_origen: NTS, patron: 'Tabla 4', mapa: rm429_2024.yaml, "
                    "modificacion: 5, numeral: '6.1.1 B Tabla 5'}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="no «6.1.1 B Tabla 5»"):
        pt.cargar_reglas(ruta)
    ruta.write_text("reglas:\n  - {id: x, documento_origen: NTS, patron: 'Tabla 4', mapa: rm429_2024.yaml, "
                    "modificacion: 99, numeral: 'x'}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="no tiene la modificación 99"):
        pt.cargar_reglas(ruta)


def test_el_destino_reemplaza_al_quinto_y_queda_ultimo(destinos):
    fragmentos, no_evaluados = rec.aplicar_punteros(None, _cinco(), [], 5, (REGLA_PRUEBA,))
    enviados = [f for f in fragmentos if f.seleccionado]
    assert [f.id_fragmento for f in enviados] == ["f0", "f1", "f2", "f3", "destino"]
    agregado = enviados[-1]
    assert agregado.origen == pt.PUNTERO and agregado.referido_por == "f1" and agregado.regla_puntero == "prueba-tabla9"
    assert agregado.posicion_rrf is None and agregado.puntaje_rrf is None and agregado.puntaje_reranker is None
    quinto = next(f for f in fragmentos if f.id_fragmento == "f4")
    assert not quinto.seleccionado and quinto.puntaje_reranker == pytest.approx(0.5)
    assert all(f.origen == pt.RERANKER for f in enviados[:-1])


def test_no_se_activa_si_la_tabla_ya_esta_entre_los_enviados(destinos):
    fr = _cinco()
    fr[3] = _frag("destino", 0.6, True, "PRUEBA-G-DESTINO", TABLA_9)
    fragmentos, _ = rec.aplicar_punteros(None, fr, [], 5, (REGLA_PRUEBA,))
    assert [f.id_fragmento for f in fragmentos] == [f.id_fragmento for f in fr]
    assert all(f.origen == pt.RERANKER for f in fragmentos)


def test_sin_puntero_entre_los_enviados_no_cambia_nada(destinos):
    fr = _cinco()
    fr[1].seleccionado = False  # el fragmento con el puntero no se envía
    fragmentos, _ = rec.aplicar_punteros(None, fr, [], 5, (REGLA_PRUEBA,))
    assert not any(f.origen == pt.PUNTERO for f in fragmentos)


def test_tope_de_un_fragmento_agregado_por_intento(destinos):
    fr = _cinco()
    fr[2] = _frag("f2", 0.7, True, "PRUEBA-G-ORIGEN", "Ver la dosis según Tabla N° 8.")
    fragmentos, _ = rec.aplicar_punteros(None, fr, [], 5, (REGLA_PRUEBA, OTRA_REGLA))
    agregados = [f for f in fragmentos if f.origen == pt.PUNTERO]
    assert [f.id_fragmento for f in agregados] == ["destino"]
    assert sum(f.seleccionado for f in fragmentos) == 5


def test_con_menos_de_cinco_se_agrega_sin_quitar(destinos):
    fr = [_frag("f0", 0.9, True), _frag("f1", 0.2, True, "PRUEBA-G-ORIGEN", "según Tabla N° 9")]
    fragmentos, _ = rec.aplicar_punteros(None, fr, [], 5, (REGLA_PRUEBA,))
    assert [f.id_fragmento for f in fragmentos if f.seleccionado] == ["f0", "f1", "destino"]


def test_si_el_puntero_es_el_quinto_sale_el_cuarto(destinos):
    fragmentos, _ = rec.aplicar_punteros(None, _cinco(con_puntero_en=4), [], 5, (REGLA_PRUEBA,))
    assert [f.id_fragmento for f in fragmentos if f.seleccionado] == ["f0", "f1", "f2", "f4", "destino"]


def test_con_un_solo_enviado_que_es_el_puntero_no_hay_lugar(destinos):
    fr = [_frag("f0", 0.9, True, "PRUEBA-G-ORIGEN", "según Tabla N° 9")]
    fragmentos, _ = rec.aplicar_punteros(None, fr, [], 1, (REGLA_PRUEBA,))
    assert [f.id_fragmento for f in fragmentos if f.seleccionado] == ["f0"]


def test_un_destino_ya_candidato_conserva_su_posicion_y_puntaje(destinos):
    fr = _cinco()
    fr[6] = _frag("destino", 0.05, False, "PRUEBA-G-DESTINO", TABLA_9, posicion_rrf=7)
    fragmentos, _ = rec.aplicar_punteros(None, fr, [], 5, (REGLA_PRUEBA,))
    agregado = next(f for f in fragmentos if f.id_fragmento == "destino")
    assert agregado.seleccionado and agregado.origen == pt.PUNTERO
    assert agregado.posicion_rrf == 7 and agregado.puntaje_reranker == 0.05
    assert [f.id_fragmento for f in fragmentos].count("destino") == 1
    # Desde los candidatos no evaluados por el reranker.
    fr = _cinco()
    sin_evaluar = [_frag("destino", None, False, "PRUEBA-G-DESTINO", TABLA_9, posicion_rrf=12)]
    fragmentos, no_evaluados = rec.aplicar_punteros(None, fr, sin_evaluar, 5, (REGLA_PRUEBA,))
    assert no_evaluados == [] and next(f for f in fragmentos if f.id_fragmento == "destino").posicion_rrf == 12


def _datos() -> DatosClinicos:
    return DatosClinicos(edad_meses=8, sexo="F", altitud_msnm=None, hb_observada_g_dl=11.6, hb_ajustada_g_dl=11.6,
                         clasificacion="SIN_ANEMIA", nivel_riesgo="BAJO", requiere_derivacion=False, peso_kg=8.0,
                         suplementacion_hierro=True, lactancia_materna_actual=True, parasitosis_reciente=False,
                         bajo_peso_nacer=False, edad_gestacional="A_TERMINO", sintomas=(), tamizaje_anterior=None)


def test_la_solicitud_deja_constancia_y_el_control_6_1_acepta_citar_el_agregado(destinos):
    fragmentos, _ = rec.aplicar_punteros(None, _cinco(), [], 5, (REGLA_PRUEBA,))
    enviados = [f for f in fragmentos if f.seleccionado]
    solicitud = construir_solicitud(_datos(), "consulta", "es", enviados, {})
    evidencia = solicitud.contenido["evidencia"]
    assert evidencia[-1]["etiqueta"] == "F-05" and evidencia[-1]["agregado_por_referencia_de"] == "F-02"
    assert all("agregado_por_referencia_de" not in e for e in evidencia[:-1])
    respuesta = {"clasificacion_confirmada": "SIN_ANEMIA", "nivel_riesgo": "BAJO", "evidencia_suficiente": True,
                 "resumen": "r", "advertencias": [], "factores_identificados": [],
                 "recomendacion": [{"texto": "Medir la hemoglobina según la tabla.", "tipo": "PREVENCION",
                                    "citas": ["F-05"]}],
                 "citas": [{"etiqueta": "F-05", "extracto": "| Fila uno | Valor uno |",
                            "extracto_traducido": None}]}
    v = ver.verificar(respuesta, solicitud, _datos(), 0.9, 0.15, {f.id_fragmento for f in enviados})
    assert v.valida_citas and v.valida_evidencia, v.motivos


# ---------------------------------------------------------------------------
# Base de pruebas
# ---------------------------------------------------------------------------
def _insertar_documento(c, codigo: str, fragmentos: list[tuple[str, str, int]]) -> tuple[str, list[str]]:
    id_doc = str(uuid.uuid4())
    c.execute(text(
        """INSERT INTO conocimiento.documento_fuente
             (id_documento, titulo, codigo_documento, entidad_emisora, tipo_documento, nivel, anio_publicacion,
              idioma, cargado_por, estado_indexacion, ruta_blob, hash_archivo, total_fragmentos)
           VALUES (:id, :t, :cod, 'MINSA', 'GUIA', 1, 2024, 'es', :u, 'COMPLETADA', 'local://prueba/g.pdf', :h, :n)"""),
        {"id": id_doc, "t": f"Guía de prueba {codigo}", "cod": codigo, "u": SISTEMA, "h": uuid.uuid4().hex * 2,
         "n": len(fragmentos)})
    ids = []
    for orden, (seccion, texto, tokens) in enumerate(fragmentos, start=1):
        ids.append(str(uuid.uuid4()))
        c.execute(text(
            """INSERT INTO conocimiento.fragmento (id_fragmento, id_documento, numero_orden, seccion, pagina_inicio,
                 pagina_fin, texto, numero_tokens, modelo_embedding, vigente, tipo_contenido)
               VALUES (:id, :doc, :o, :s, 6, 6, :t, :n, 'falso', true, 'TABLA')"""),
            {"id": ids[-1], "doc": id_doc, "o": orden, "s": seccion, "t": texto, "n": tokens})
    return id_doc, ids


@pytest.fixture
def documentos_g(super_engine, guia):  # noqa: F811
    """Documento de origen (en la colección vectorial de la guía de prueba) con el puntero y documento
    destino fuera de la colección y sin términos de la consulta: no es candidato de la fusión."""
    puntero = " ".join(GUIA_MINSA) + " La medición se programa según Tabla N° 9, considerando la edad."
    with super_engine.begin() as c:
        _borrar_documentos_g(c)
        origen, (id_puntero,) = _insertar_documento(c, "PRUEBA-G-ORIGEN", [("Puntero de prueba", puntero, 300)])
        destino, (id_tabla, id_larga) = _insertar_documento(c, "PRUEBA-G-DESTINO", [
            (f"Tabla 9 {REGLA_PRUEBA.marca_seccion}", TABLA_9, 120),
            (f"Tabla 8 {OTRA_REGLA.marca_seccion}", "Tabla N° 8 de prueba, larga", 700)])
    guia["almacen"].agregar([RegistroVector(id_puntero, EmbedderFalso().embeber([puntero])[0], puntero, {
        "id_documento": origen, "nivel": 1, "estado_documento": "VIGENTE", "vigente": True, "idioma": "es"})])
    yield {"puntero": id_puntero, "tabla": id_tabla, "larga": id_larga}
    with super_engine.begin() as c:
        _borrar_documentos_g(c)


def _borrar_documentos_g(c) -> None:
    """Borra los documentos PRUEBA-G-* (también los que dejó una corrida interrumpida). Las consultas
    de la prueba HTTP se borran después (consultas_d2): antes, sus referencias a estos fragmentos."""
    fragmentos = """(SELECT f.id_fragmento FROM conocimiento.fragmento f JOIN conocimiento.documento_fuente d
                       USING (id_documento) WHERE d.codigo_documento LIKE 'PRUEBA-G-%')"""
    c.execute(text(f"DELETE FROM asistencia.cita_evidencia WHERE id_fragmento IN {fragmentos}"))
    c.execute(text(f"DELETE FROM asistencia.fragmento_recuperado WHERE id_fragmento IN {fragmentos}"))
    c.execute(text(f"DELETE FROM conocimiento.fragmento WHERE id_fragmento IN {fragmentos}"))
    c.execute(text("DELETE FROM conocimiento.documento_fuente WHERE codigo_documento LIKE 'PRUEBA-G-%'"))


def test_buscar_destino_respeta_el_tope_de_tokens(engine_generacion, documentos_g):
    with engine_generacion.connect() as c:
        assert pt.buscar_destino(c, REGLA_PRUEBA).id_fragmento == documentos_g["tabla"]
        assert pt.buscar_destino(c, OTRA_REGLA) is None  # 700 tokens, más que MAX_TOKENS_AGREGADO
        assert pt.buscar_destino(c, replace(REGLA_PRUEBA, documento_destino="OTRO")) is None


class _ClienteQueCitaElAgregado(ClienteFalso):
    """Cliente falso que cita el fragmento agregado por la regla (el primero de la evidencia)."""

    def _cuerpo(self, modo, solicitud):
        evidencia = solicitud["evidencia"]
        agregado = [e for e in evidencia if "agregado_por_referencia_de" in e]
        return super()._cuerpo(modo, {**solicitud, "evidencia": agregado + [e for e in evidencia if e not in agregado]})


def test_recuperacion_con_la_regla_no_cambia_la_relevancia_maxima(entorno, documentos_g, engine_generacion,  # noqa: F811
                                                                  monkeypatch):
    consulta = normalizar("Suplementación preventiva con hierro y medición de hemoglobina en niños de 6 a 11 meses")
    with engine_generacion.connect() as c:
        monkeypatch.setattr(rec, "reglas_vigentes", lambda: ())
        sin = rec.recuperar(c, consulta, entorno.servicios, entorno.parametros, edad_meses=8)
        monkeypatch.setattr(rec, "reglas_vigentes", lambda: (REGLA_PRUEBA,))
        con = rec.recuperar(c, consulta, entorno.servicios, entorno.parametros, edad_meses=8)
    assert documentos_g["puntero"] in [f.id_fragmento for f in sin.seleccionados]
    assert documentos_g["tabla"] not in [f.id_fragmento for f in sin.fragmentos + sin.no_evaluados]
    assert con.seleccionados[-1].id_fragmento == documentos_g["tabla"]
    assert len(con.seleccionados) <= entorno.parametros.fragmentos_enviados
    assert (con.relevancia_maxima, con.suficiente) == (sin.relevancia_maxima, sin.suficiente)


def test_el_agregado_se_guarda_con_origen_y_se_cita_en_fin_y_en_el_get(cliente_http, cabeceras, consultas_d2,  # noqa: F811
                                                                     super_engine, usar_entorno, documentos_g,
                                                                     monkeypatch):
    monkeypatch.setattr(rec, "reglas_vigentes", lambda: (REGLA_PRUEBA,))
    caso = _caso("b")
    entorno_http = usar_entorno(cliente=_ClienteQueCitaElAgregado([APROBADA]))
    usar_entorno(cliente=entorno_http.cliente,
                 parametros=replace(entorno_http.parametros, fragmentos_enviados=5))
    id_paciente, id_tamizaje, _ = _ids(super_engine, caso)
    _, eventos = _consultar(cliente_http, cabeceras, consultas_d2, id_paciente, _cuerpo(caso, id_tamizaje=id_tamizaje))
    fin = eventos[-1]
    assert fin["tipo"] == "fin" and fin["estado"] == "VERIFICADA", fin
    (cita,) = fin["citas"]
    assert cita["origen"] == "PUNTERO" and cita["puntaje_reranker"] is None
    assert re.fullmatch(r"F-0[1-4]", cita["agregado_por_referencia_de"]), cita
    with super_engine.connect() as c:
        filas = c.execute(text(
            """SELECT r.id_fragmento::text, r.origen, r.enviado_al_llm, r.etiqueta_cita, r.posicion_rrf, r.puntaje_rrf
                 FROM asistencia.fragmento_recuperado r JOIN asistencia.intento_generacion i USING (id_intento)
                WHERE i.id_consulta = CAST(:c AS uuid) AND r.enviado_al_llm ORDER BY r.etiqueta_cita"""),
            {"c": fin["id_consulta"]}).all()
        solicitud = c.execute(text("SELECT solicitud_enviada FROM asistencia.intento_generacion "
                                   "WHERE id_consulta = CAST(:c AS uuid)"), {"c": fin["id_consulta"]}).scalar_one()
    agregado = next(f for f in filas if f.origen == "PUNTERO")
    assert agregado.id_fragmento == documentos_g["tabla"] and agregado.enviado_al_llm
    assert agregado.etiqueta_cita == cita["etiqueta"] and agregado.posicion_rrf is None and agregado.puntaje_rrf is None
    assert len(filas) <= 5 and all(f.origen == "RERANKER" for f in filas if f is not agregado)
    referida = next(f for f in filas if f.etiqueta_cita == cita["agregado_por_referencia_de"])
    assert referida.id_fragmento == documentos_g["puntero"]
    assert next(e for e in solicitud["evidencia"] if e["etiqueta"] == cita["etiqueta"])[
        "agregado_por_referencia_de"] == cita["agregado_por_referencia_de"]
    r = cliente_http.get(f"/api/consultas/{fin['id_consulta']}", headers=cabeceras("med.salazar"))
    resultado = rutas.ResultadoConsulta.model_validate(r.json())
    (guardada,) = resultado.citas
    assert (guardada.origen, guardada.agregado_por_referencia_de, guardada.puntaje_reranker) == (
        "PUNTERO", cita["agregado_por_referencia_de"], None)
    # Restricciones de la migración 012 sobre las filas del intento (cada cambio se revierte): los
    # nulos de la fusión solo valen con PUNTERO, y un PUNTERO siempre está enviado.
    cambios = [
        ("SET posicion_rrf = NULL, puntaje_rrf = NULL", referida.id_fragmento, "fragmento_recuperado_rrf_check"),
        ("SET enviado_al_llm = false, etiqueta_cita = NULL", agregado.id_fragmento, "fragmento_recuperado_origen_check"),
        ("SET origen = 'OTRO'", referida.id_fragmento, "fragmento_recuperado_origen_check"),
        ("SET origen = 'RERANKER'", agregado.id_fragmento, "fragmento_recuperado_rrf_check"),
    ]
    for cambio, id_fragmento, restriccion in cambios:
        with super_engine.connect() as c:
            t = c.begin()
            with pytest.raises(DBAPIError, match=restriccion):
                c.execute(text(f"UPDATE asistencia.fragmento_recuperado {cambio} WHERE id_fragmento = CAST(:f AS uuid) "
                               "AND id_intento IN (SELECT id_intento FROM asistencia.intento_generacion "
                               "WHERE id_consulta = CAST(:c AS uuid))"), {"f": id_fragmento, "c": fin["id_consulta"]})
            t.rollback()


def test_migracion_012_es_idempotente(super_engine):
    sql = (Path(__file__).resolve().parents[2] / "db" / "migraciones" / "012_origen_fragmento.sql").read_text(
        encoding="utf-8")
    for _ in range(2):
        with super_engine.begin() as c:
            c.exec_driver_sql(sql)
    with super_engine.connect() as c:
        columnas = dict(c.execute(text(
            """SELECT column_name, is_nullable FROM information_schema.columns
                WHERE table_schema = 'asistencia' AND table_name = 'fragmento_recuperado'""")).all())
    assert columnas["origen"] == "NO" and columnas["posicion_rrf"] == "YES" and columnas["puntaje_rrf"] == "YES"
