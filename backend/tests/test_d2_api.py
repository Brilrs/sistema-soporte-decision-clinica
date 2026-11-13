"""Parte D2 por HTTP, con modelos falsos, ChromaDB en memoria y el cliente falso del modelo
de lenguaje (nunca la API real): estados finales y formato NDJSON, roles (admin.cdss 403),
consultas de otro profesional, cierre de la conexión a mitad del stream, datos faltantes,
decisión del profesional, auditoría sin texto clínico, Nginx, OpenAPI y la comparación de
versiones del prompt."""
import asyncio
import json
import re
import time
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import TypeAdapter
from sqlalchemy import text

from app.api.routes import consultas as rutas
from app.main import app
from app.rag import grafo as g
from app.rag.cliente_llm import APROBADA, TIEMPO_AGOTADO, ClienteFalso
from app.rag.filtro_texto import IdentidadPaciente, generar_huellas
from app.rag.generacion import VERSIONES_PROMPT, cargar_prompt
from app.services import decisiones as dec
from tests.test_d1_grafo import _RerankerLento, _caso, _ids, entorno  # noqa: F401 (fixtures)
from tests.test_generacion_bd import engine_clinica, engine_generacion, guia  # noqa: F401 (fixtures)

NGINX = Path(__file__).resolve().parents[2] / "frontend" / "nginx.conf"
EVENTO = TypeAdapter(rutas.EventoConsulta)
IDENTIDAD_MATEO = ("Mateo", "Quispe", "Huamán", "81234567", "00452", "987654321")


@pytest.fixture
def cliente_http():
    return TestClient(app)


@pytest.fixture
def consultas_d2(super_engine, guia):  # noqa: F811
    """Consultas creadas por la prueba; al final se borran con sus decisiones, antes que la
    guía de prueba que citan (por eso depende de guia)."""
    ids: list[str] = []
    yield ids
    if not ids:
        return
    with super_engine.begin() as c:
        p = {"ids": ids}
        intentos = "(SELECT id_intento FROM asistencia.intento_generacion WHERE id_consulta::text = ANY(:ids))"
        c.execute(text("DELETE FROM asistencia.decision_clinica WHERE id_consulta::text = ANY(:ids)"), p)
        c.execute(text(f"DELETE FROM asistencia.cita_evidencia WHERE id_intento IN {intentos}"), p)
        c.execute(text("DELETE FROM asistencia.recomendacion WHERE id_consulta::text = ANY(:ids)"), p)
        c.execute(text(f"DELETE FROM asistencia.fragmento_recuperado WHERE id_intento IN {intentos}"), p)
        c.execute(text("DELETE FROM asistencia.intento_generacion WHERE id_consulta::text = ANY(:ids)"), p)
        c.execute(text("DELETE FROM asistencia.dato_faltante WHERE id_consulta::text = ANY(:ids)"), p)
        c.execute(text("DELETE FROM asistencia.consulta WHERE id_consulta::text = ANY(:ids)"), p)


@pytest.fixture
def usar_entorno(entorno):  # noqa: F811
    """Reemplaza el entorno de la API por el de prueba; devuelve una función para cambiar el cliente."""
    actual = {"entorno": entorno}
    app.dependency_overrides[rutas.entorno_consultas] = lambda: actual["entorno"]

    def con(modos=None, preferir_ingles=False, **cambios):
        actual["entorno"] = replace(entorno, cliente=ClienteFalso(modos or [APROBADA], preferir_ingles=preferir_ingles),
                                    **cambios)
        return actual["entorno"]
    con()
    yield con
    app.dependency_overrides.pop(rutas.entorno_consultas, None)


def _consultar(cliente_http, cabeceras, consultas_d2, id_paciente, cuerpo, usuario="med.salazar", ruta=None):
    r = cliente_http.post(ruta or f"/api/pacientes/{id_paciente}/consultas", json=cuerpo, headers=cabeceras(usuario))
    if r.status_code != 200:
        return r, []
    eventos = [json.loads(linea) for linea in r.text.splitlines() if linea]
    for e in eventos:
        if e.get("id_consulta") and e["id_consulta"] not in consultas_d2:
            consultas_d2.append(e["id_consulta"])
    return r, eventos


def _cuerpo(caso: dict, **cambios) -> dict:
    return {"texto_consulta": caso["consulta"], "confirma_tamizaje_no_vigente": bool(caso.get("confirma_tamizaje_no_vigente")),
            **cambios}


def _caso_http(cliente_http, cabeceras, consultas_d2, super_engine, usar_entorno, id_caso, usuario="med.salazar",
               **cambios):
    caso = _caso(id_caso)
    falso = caso.get("falso") or {}
    usar_entorno(falso.get("modos"), bool(falso.get("preferir_ingles")))
    id_paciente, id_tamizaje, _ = _ids(super_engine, caso)
    return _consultar(cliente_http, cabeceras, consultas_d2, id_paciente,
                      _cuerpo(caso, id_tamizaje=id_tamizaje, **cambios), usuario)


def _auditoria(super_engine, tipo: str, id_entidad: str) -> list[dict]:
    with super_engine.connect() as c:
        return [r[0] for r in c.execute(text(
            "SELECT detalle FROM auditoria.evento_auditoria WHERE tipo_evento = :t AND id_entidad = :e"),
            {"t": tipo, "e": id_entidad})]


# ---------------------------------------------------------------------------
# NDJSON y estados finales
# ---------------------------------------------------------------------------
def test_el_stream_es_ndjson_valido_con_un_evento_por_etapa(cliente_http, cabeceras, consultas_d2, super_engine,
                                                            usar_entorno):
    r, eventos = _caso_http(cliente_http, cabeceras, consultas_d2, super_engine, usar_entorno, "i")
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/x-ndjson")
    assert r.headers["x-accel-buffering"] == "no" and r.headers["cache-control"] == "no-store"
    assert r.text.endswith("\n") and len(r.text.splitlines()) == len(eventos)
    for e in eventos:
        EVENTO.validate_python(e)
    assert [e["etapa"] for e in eventos if e["tipo"] == "etapa"] == list(g.NODOS)
    fin = eventos[-1]
    assert fin["tipo"] == "fin" and fin["estado"] == "VERIFICADA" and fin["idioma"] == "es"
    assert fin["recomendacion"]["resumen"] and fin["recomendacion"]["recomendacion"]
    assert all(re.fullmatch(r"F-0[1-5]", c["etiqueta"]) for c in fin["citas"])
    assert fin["vigencia"]["dias_vigencia"] == 30
    assert fin["opciones_decision"] == [{"tipo": "ACEPTA_RECOMENDACION", "nota_obligatoria": False},
                                        {"tipo": "MODIFICA_RECOMENDACION", "nota_obligatoria": True},
                                        {"tipo": "CRITERIO_CLINICO_PROPIO", "nota_obligatoria": False}]
    # Ningún evento lleva la identidad ni el texto original (el caso i los escribe en la consulta).
    for dato in IDENTIDAD_MATEO:
        assert dato not in r.text, dato


@pytest.mark.parametrize("id_caso, cambios, estado", [
    ("a", {}, "VERIFICADA"), ("g", {}, "DATOS_FALTANTES"), ("h", {}, "FUERA_DE_DOMINIO"),
    ("f", {"confirma_tamizaje_no_vigente": False}, "TAMIZAJE_NO_VIGENTE"), ("j", {}, "EVIDENCIA_INSUFICIENTE"),
    ("l", {}, "VERIFICADA"),
])
def test_cada_estado_final_por_http(cliente_http, cabeceras, consultas_d2, super_engine, usar_entorno, id_caso,
                                    cambios, estado):
    _, eventos = _caso_http(cliente_http, cabeceras, consultas_d2, super_engine, usar_entorno, id_caso, **cambios)
    fin = eventos[-1]
    assert (fin["tipo"], fin["estado"]) == ("fin", estado)
    if estado == "DATOS_FALTANTES":
        assert fin["datos_faltantes"] == ["hemoglobina"] and fin["opciones_decision"] == []
    if estado == "TAMIZAJE_NO_VIGENTE":
        assert fin["vigencia"]["dias_transcurridos"] > fin["vigencia"]["dias_vigencia"] and fin["mensaje"]
    if estado == "EVIDENCIA_INSUFICIENTE":
        assert fin["opciones_decision"] == [{"tipo": "CRITERIO_CLINICO_PROPIO", "nota_obligatoria": False}]


def test_error_y_solicitud_bloqueada_por_http(cliente_http, cabeceras, consultas_d2, super_engine, usar_entorno,
                                              monkeypatch):
    caso = _caso("b")
    id_paciente, id_tamizaje, _ = _ids(super_engine, caso)
    usar_entorno([TIEMPO_AGOTADO])
    fin = _consultar(cliente_http, cabeceras, consultas_d2, id_paciente, _cuerpo(caso, id_tamizaje=id_tamizaje))[1][-1]
    assert (fin["estado"], fin["opciones_decision"]) == ("ERROR", [{"tipo": "CRITERIO_CLINICO_PROPIO",
                                                                    "nota_obligatoria": False}])
    usar_entorno()
    monkeypatch.setattr(g, "generar_huellas", lambda _: generar_huellas(IdentidadPaciente("Ana Ferroso", "1", "2")))
    fin = _consultar(cliente_http, cabeceras, consultas_d2, id_paciente, _cuerpo(caso, id_tamizaje=id_tamizaje))[1][-1]
    assert fin["estado"] == "SOLICITUD_BLOQUEADA"


def test_tamizaje_no_vigente_y_confirmacion_con_consulta_previa(cliente_http, cabeceras, consultas_d2, super_engine,
                                                                usar_entorno):
    fin = _caso_http(cliente_http, cabeceras, consultas_d2, super_engine, usar_entorno, "f",
                     confirma_tamizaje_no_vigente=False)[1][-1]
    previa = fin["id_consulta"]
    fin = _caso_http(cliente_http, cabeceras, consultas_d2, super_engine, usar_entorno, "f",
                     confirma_tamizaje_no_vigente=True, id_consulta_previa=previa)[1][-1]
    assert (fin["estado"], fin["id_consulta_previa"]) == ("VERIFICADA", previa)
    r, _ = _caso_http(cliente_http, cabeceras, consultas_d2, super_engine, usar_entorno, "f",
                      confirma_tamizaje_no_vigente=True, id_consulta_previa=previa)
    assert r.status_code == 409


def test_errores_antes_del_stream(cliente_http, cabeceras, consultas_d2, super_engine, usar_entorno):
    caso_b, caso_a = _caso("b"), _caso("a")
    id_b, _, _ = _ids(super_engine, caso_b)
    _, tamizaje_a, _ = _ids(super_engine, caso_a)
    r = cliente_http.post("/api/pacientes/00000000-0000-0000-0000-00000000abcd/consultas",
                          json=_cuerpo(caso_b), headers=cabeceras("med.salazar"))
    assert r.status_code == 404
    r = cliente_http.post(f"/api/pacientes/{id_b}/consultas", json=_cuerpo(caso_b, id_tamizaje=tamizaje_a),
                          headers=cabeceras("med.salazar"))
    assert r.status_code == 422 and "no pertenece" in r.json()["detail"]
    r = cliente_http.post(f"/api/pacientes/{id_b}/consultas", json={"texto_consulta": "  "},
                          headers=cabeceras("med.salazar"))
    assert r.status_code == 422
    assert cliente_http.post(f"/api/pacientes/{id_b}/consultas", json=_cuerpo(caso_b)).status_code == 401


# ---------------------------------------------------------------------------
# Roles y consultas de otro profesional
# ---------------------------------------------------------------------------
def test_admin_recibe_403_en_todas_las_rutas(cliente_http, cabeceras, consultas_d2, super_engine, usar_entorno):
    fin = _caso_http(cliente_http, cabeceras, consultas_d2, super_engine, usar_entorno, "b")[1][-1]
    id_paciente, _, _ = _ids(super_engine, _caso("b"))
    admin = cabeceras("admin.cdss")
    c = fin["id_consulta"]
    respuestas = [
        cliente_http.post(f"/api/pacientes/{id_paciente}/consultas", json={"texto_consulta": "anemia"}, headers=admin),
        cliente_http.get(f"/api/consultas/{c}", headers=admin),
        cliente_http.post(f"/api/consultas/{c}/datos-faltantes", json={"hemoglobina_g_dl": "10.5"}, headers=admin),
        cliente_http.post(f"/api/consultas/{c}/decision", json={"tipo_decision": "ACEPTA_RECOMENDACION"},
                          headers=admin)]
    assert [r.status_code for r in respuestas] == [403, 403, 403, 403]


def test_otro_profesional_no_ve_ni_decide_y_queda_auditado(cliente_http, cabeceras, consultas_d2, super_engine,
                                                           usar_entorno):
    fin = _caso_http(cliente_http, cabeceras, consultas_d2, super_engine, usar_entorno, "b")[1][-1]
    c = fin["id_consulta"]
    for usuario in ("enf.rojas", "coord.ortiz"):
        assert cliente_http.get(f"/api/consultas/{c}", headers=cabeceras(usuario)).status_code == 404
        r = cliente_http.post(f"/api/consultas/{c}/decision", json={"tipo_decision": "ACEPTA_RECOMENDACION"},
                              headers=cabeceras(usuario))
        assert r.status_code == 404
    assert sorted(d["accion"] for d in _auditoria(super_engine, "ACCESO_DENEGADO_CONSULTA", c)) == [
        "decidir", "decidir", "ver", "ver"]
    with super_engine.connect() as conexion:
        assert conexion.execute(text("SELECT count(*) FROM asistencia.decision_clinica "
                                     "WHERE id_consulta = CAST(:c AS uuid)"), {"c": c}).scalar_one() == 0
    # El coordinador puede hacer sus propias consultas.
    fin = _caso_http(cliente_http, cabeceras, consultas_d2, super_engine, usar_entorno, "b", usuario="coord.ortiz")[1][-1]
    assert fin["estado"] == "VERIFICADA"
    assert cliente_http.get(f"/api/consultas/{fin['id_consulta']}", headers=cabeceras("coord.ortiz")).status_code == 200


# ---------------------------------------------------------------------------
# Resultado guardado
# ---------------------------------------------------------------------------
def test_resultado_guardado_con_citas_y_traduccion_de_apoyo(cliente_http, cabeceras, consultas_d2, super_engine,
                                                            usar_entorno):
    fin = _caso_http(cliente_http, cabeceras, consultas_d2, super_engine, usar_entorno, "l")[1][-1]
    r = cliente_http.get(f"/api/consultas/{fin['id_consulta']}", headers=cabeceras("med.salazar"))
    assert r.status_code == 200
    resultado = rutas.ResultadoConsulta.model_validate(r.json())
    assert resultado.estado == "VERIFICADA" and resultado.recomendacion is not None
    assert resultado.recomendacion.resumen == fin["recomendacion"]["resumen"]
    assert [c.etiqueta for c in resultado.citas] == [c["etiqueta"] for c in fin["citas"]]
    for c in resultado.citas:
        assert c.documento and c.extracto and c.pagina_inicio is not None and c.seccion
    ingles = [c for c in resultado.citas if c.idioma == "en"]
    assert ingles and all(c.extracto_traducido and c.etiqueta_traduccion == "Traducción de apoyo, no oficial"
                          for c in ingles)
    assert all(c.etiqueta_traduccion is None for c in resultado.citas if c.idioma == "es")
    assert resultado.opciones_decision and resultado.decision is None
    (detalle,) = _auditoria(super_engine, "CONSULTA_VISTA", fin["id_consulta"])
    assert detalle == {"estado": "VERIFICADA"}


def test_la_auditoria_de_inicio_no_lleva_texto_clinico(cliente_http, cabeceras, consultas_d2, super_engine,
                                                       usar_entorno):
    _caso_http(cliente_http, cabeceras, consultas_d2, super_engine, usar_entorno, "i")
    id_paciente, _, _ = _ids(super_engine, _caso("i"))
    detalles = _auditoria(super_engine, "CONSULTA_INICIADA", id_paciente)
    assert detalles and set(detalles[-1]) == {"id_tamizaje", "id_consulta_previa", "confirma_tamizaje_no_vigente"}
    volcado = json.dumps(detalles, ensure_ascii=False)
    assert "tratamiento" not in volcado and not any(d in volcado for d in IDENTIDAD_MATEO)


# ---------------------------------------------------------------------------
# Datos faltantes (M06)
# ---------------------------------------------------------------------------
@pytest.fixture
def tamizaje_sin_hemoglobina(super_engine):
    """El tamizaje del caso g vuelve a quedar sin hemoglobina ni clasificación al terminar."""
    _, id_tamizaje, _ = _ids(super_engine, _caso("g"))
    yield id_tamizaje
    with super_engine.begin() as c:
        c.execute(text("DELETE FROM clinico.resultado_clasificacion WHERE id_tamizaje = CAST(:t AS uuid)"),
                  {"t": id_tamizaje})
        c.execute(text("UPDATE clinico.tamizaje SET hemoglobina_g_dl = NULL, metodo_medicion = NULL "
                       "WHERE id_tamizaje = CAST(:t AS uuid)"), {"t": id_tamizaje})


def test_datos_faltantes_completa_y_reanuda_enlazada(cliente_http, cabeceras, consultas_d2, super_engine, usar_entorno,
                                                     tamizaje_sin_hemoglobina):
    previa = _caso_http(cliente_http, cabeceras, consultas_d2, super_engine, usar_entorno, "g")[1][-1]["id_consulta"]
    ruta = f"/api/consultas/{previa}/datos-faltantes"
    assert cliente_http.post(ruta, json={"hemoglobina_g_dl": "10.4"}, headers=cabeceras("enf.rojas")).status_code == 404
    r, eventos = _consultar(cliente_http, cabeceras, consultas_d2, None,
                            {"hemoglobina_g_dl": "10.4", "metodo_medicion": "HEMOGLOBINOMETRO"}, ruta=ruta)
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/x-ndjson")
    fin = eventos[-1]
    assert fin["id_consulta_previa"] == previa and fin["id_consulta"] != previa
    assert fin["estado"] == "VERIFICADA" and fin["clasificacion"] is not None
    with super_engine.connect() as c:
        hb, metodo = c.execute(text("SELECT hemoglobina_g_dl, metodo_medicion FROM clinico.tamizaje "
                                    "WHERE id_tamizaje = CAST(:t AS uuid)"), {"t": tamizaje_sin_hemoglobina}).one()
        completado = c.execute(text("SELECT bool_and(completado) FROM asistencia.dato_faltante "
                                    "WHERE id_consulta = CAST(:c AS uuid)"), {"c": previa}).scalar_one()
    assert (float(hb), metodo, completado) == (10.4, "HEMOGLOBINOMETRO", True)
    detalles = [d for d in _auditoria(super_engine, "TAMIZAJE_COMPLETADO", tamizaje_sin_hemoglobina)
                if d["id_consulta"] == previa]
    assert detalles == [{"id_consulta": previa, "campos": ["hemoglobina_g_dl"]}]
    # Segunda vez: ya se completó.
    assert cliente_http.post(ruta, json={"hemoglobina_g_dl": "9.0"}, headers=cabeceras("med.salazar")).status_code == 409


def test_datos_faltantes_rechaza_otros_estados_y_la_altitud(cliente_http, cabeceras, consultas_d2, super_engine,
                                                            usar_entorno, tamizaje_sin_hemoglobina):
    verificada = _caso_http(cliente_http, cabeceras, consultas_d2, super_engine, usar_entorno, "b")[1][-1]["id_consulta"]
    r = cliente_http.post(f"/api/consultas/{verificada}/datos-faltantes", json={"hemoglobina_g_dl": "10.0"},
                          headers=cabeceras("med.salazar"))
    assert r.status_code == 409
    previa = _caso_http(cliente_http, cabeceras, consultas_d2, super_engine, usar_entorno, "g")[1][-1]["id_consulta"]
    with super_engine.begin() as c:
        c.execute(text("UPDATE asistencia.dato_faltante SET campo = 'altitud_msnm' WHERE id_consulta = CAST(:c AS uuid)"),
                  {"c": previa})
    r = cliente_http.post(f"/api/consultas/{previa}/datos-faltantes", json={"hemoglobina_g_dl": "10.0"},
                          headers=cabeceras("med.salazar"))
    assert r.status_code == 422 and "altitud" in r.json()["detail"]


# ---------------------------------------------------------------------------
# Decisión del profesional (M07)
# ---------------------------------------------------------------------------
def test_decision_en_una_consulta_verificada(cliente_http, cabeceras, consultas_d2, super_engine, usar_entorno):
    c = _caso_http(cliente_http, cabeceras, consultas_d2, super_engine, usar_entorno, "b")[1][-1]["id_consulta"]
    ruta = f"/api/consultas/{c}/decision"
    r = cliente_http.post(ruta, json={"tipo_decision": "MODIFICA_RECOMENDACION"}, headers=cabeceras("med.salazar"))
    assert r.status_code == 422 and "obligatoria" in r.json()["detail"]
    nota = "Se ajusta la dosis por tolerancia digestiva referida por la madre."
    r = cliente_http.post(ruta, json={"tipo_decision": "MODIFICA_RECOMENDACION", "nota": nota},
                          headers=cabeceras("med.salazar"))
    assert r.status_code == 201
    decision = r.json()
    assert decision["tipo_decision"] == "MODIFICA_RECOMENDACION" and decision["nota"] == nota
    r = cliente_http.post(ruta, json={"tipo_decision": "ACEPTA_RECOMENDACION"}, headers=cabeceras("med.salazar"))
    assert r.status_code == 409
    resultado = cliente_http.get(f"/api/consultas/{c}", headers=cabeceras("med.salazar")).json()
    assert resultado["decision"]["tipo_decision"] == "MODIFICA_RECOMENDACION" and resultado["opciones_decision"] == []
    (detalle,) = _auditoria(super_engine, "DECISION_REGISTRADA", c)
    assert detalle == {"tipo_decision": "MODIFICA_RECOMENDACION", "con_nota": True}


@pytest.mark.parametrize("id_caso, cambios, tipo, codigo", [
    ("j", {}, "ACEPTA_RECOMENDACION", 409), ("j", {}, "CRITERIO_CLINICO_PROPIO", 201),
    ("g", {}, "CRITERIO_CLINICO_PROPIO", 409), ("h", {}, "CRITERIO_CLINICO_PROPIO", 409),
])
def test_decision_segun_el_estado(cliente_http, cabeceras, consultas_d2, super_engine, usar_entorno, id_caso, cambios,
                                  tipo, codigo):
    c = _caso_http(cliente_http, cabeceras, consultas_d2, super_engine, usar_entorno, id_caso, **cambios)[1][-1]
    r = cliente_http.post(f"/api/consultas/{c['id_consulta']}/decision", json={"tipo_decision": tipo},
                          headers=cabeceras("med.salazar"))
    assert r.status_code == codigo, r.text


def test_opciones_de_decision_por_estado():
    assert [o["tipo"] for o in dec.opciones_decision("VERIFICADA")] == list(dec.TIPOS)
    assert dec.opciones_decision("ERROR") == [{"tipo": "CRITERIO_CLINICO_PROPIO", "nota_obligatoria": False}]
    for estado in ("DATOS_FALTANTES", "TAMIZAJE_NO_VIGENTE", "FUERA_DE_DOMINIO", "SOLICITUD_BLOQUEADA", "EN_PROCESO",
                   None):
        assert dec.opciones_decision(estado) == []


# ---------------------------------------------------------------------------
# Cierre de la conexión a mitad del stream
# ---------------------------------------------------------------------------
def test_si_el_cliente_cierra_la_consulta_termina_limpia(cabeceras, consultas_d2, super_engine, usar_entorno):
    entorno = usar_entorno()
    usar_entorno(servicios=replace(entorno.servicios, reranker=_RerankerLento()))
    caso = _caso("b")
    id_paciente, id_tamizaje, _ = _ids(super_engine, caso)
    cuerpo = json.dumps(_cuerpo(caso, id_tamizaje=id_tamizaje)).encode()
    token = cabeceras("med.salazar")["Authorization"].encode()
    recibidos: list[bytes] = []
    estado_cliente = {"cuerpo_enviado": False}
    cerrar = asyncio.Event()

    async def receive():
        if not estado_cliente["cuerpo_enviado"]:
            estado_cliente["cuerpo_enviado"] = True
            return {"type": "http.request", "body": cuerpo, "more_body": False}
        await cerrar.wait()
        return {"type": "http.disconnect"}

    async def send(mensaje):
        if mensaje["type"] == "http.response.body" and mensaje.get("body"):
            recibidos.append(mensaje["body"])
            cerrar.set()  # el cliente cierra apenas recibe el primer evento

    alcance = {"type": "http", "asgi": {"version": "3.0", "spec_version": "2.3"}, "http_version": "1.1",
               "method": "POST", "scheme": "http", "path": f"/api/pacientes/{id_paciente}/consultas",
               "raw_path": b"", "query_string": b"", "root_path": "", "client": ("127.0.0.1", 5000),
               "server": ("testserver", 80),
               "headers": [(b"host", b"testserver"), (b"content-type", b"application/json"),
                           (b"authorization", token), (b"content-length", str(len(cuerpo)).encode())]}
    asyncio.run(asyncio.wait_for(app(alcance, receive, send), timeout=30))
    primero = json.loads(recibidos[0].decode().splitlines()[0])
    assert primero["etapa"] == "validar"
    id_consulta = primero["id_consulta"]
    consultas_d2.append(id_consulta)
    assert len(b"".join(recibidos).decode().splitlines()) < len(g.NODOS)
    # El grafo sigue en su hilo hasta registrar el estado final.
    limite = time.monotonic() + 30
    while True:
        with super_engine.connect() as c:
            estado, tiempos = c.execute(text("SELECT estado, tiempos_ms FROM asistencia.consulta "
                                             "WHERE id_consulta = CAST(:c AS uuid)"), {"c": id_consulta}).one()
        if estado != "EN_PROCESO" or time.monotonic() > limite:
            break
        time.sleep(0.2)
    assert estado == "VERIFICADA" and tiempos["total_ms"] > 0
    with super_engine.connect() as c:
        abiertas = c.execute(text("SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() "
                                  "AND usename IN ('cdss_clinica', 'cdss_generacion') "
                                  "AND state LIKE 'idle in transaction%'")).scalar_one()
    assert abiertas == 0


# ---------------------------------------------------------------------------
# Nginx, OpenAPI y prompt v1.2
# ---------------------------------------------------------------------------
def test_nginx_no_guarda_en_bufer_las_rutas_de_stream():
    conf = NGINX.read_text(encoding="utf-8")
    bloque = re.search(r"location ~ (\S+) \{(.*?)\}", conf, re.S)
    patron, cuerpo = bloque.group(1), bloque.group(2)
    for ruta in ("/api/pacientes/1b2c/consultas", "/api/consultas/1b2c/datos-faltantes"):
        assert re.match(patron, ruta), ruta
    for ruta in ("/api/consultas/1b2c", "/api/consultas/1b2c/decision", "/api/pacientes/1b2c"):
        assert not re.match(patron, ruta), ruta
    assert "proxy_buffering off;" in cuerpo and "proxy_pass http://backend:8000;" in cuerpo
    assert int(re.search(r"proxy_read_timeout (\d+)s;", cuerpo).group(1)) >= 60
    # La ruta general de la API no cambia.
    assert "location /api/ {" in conf and "proxy_read_timeout 60s;" in conf


def test_openapi_documenta_el_ndjson(cliente_http):
    esquema = cliente_http.get("/openapi.json").json()
    operacion = esquema["paths"]["/api/pacientes/{id_paciente}/consultas"]["post"]
    contenido = operacion["responses"]["200"]["content"]
    assert contenido["application/x-ndjson"]["schema"]["$ref"] == "#/components/schemas/EventoConsulta"
    componentes = esquema["components"]["schemas"]
    assert {"EventoEtapa", "EventoEnCola", "EventoFin", "EventoError", "OpcionDecision"} <= set(componentes)
    assert "nota_obligatoria" in componentes["OpcionDecision"]["properties"]
    assert "application/x-ndjson" in esquema["paths"]["/api/consultas/{id_consulta}/datos-faltantes"]["post"][
        "responses"]["200"]["content"]


def test_prompt_v1_2_compacto_existe_sin_reemplazar_v1_1(engine_generacion, entorno, consultas_d2,  # noqa: F811
                                                         super_engine):
    from app.rag.generacion import configuracion_generacion
    from app.services import consultas as srv
    assert {"v1.1", "v1.2"} <= set(VERSIONES_PROMPT)
    v12 = cargar_prompt("v1.2")
    assert "como máximo 2 oraciones" in v12 and "150 caracteres" in v12 and v12 != cargar_prompt("v1.1")
    with engine_generacion.connect() as c:
        assert configuracion_generacion(c).version_prompt == "v1.1"
    caso = _caso("b")
    id_paciente, id_tamizaje, id_usuario = _ids(super_engine, caso)
    solicitud = srv.SolicitudConsulta(id_paciente, id_usuario, caso["consulta"], id_tamizaje)
    eventos = asyncio.run(srv.eventos_de(solicitud, replace(entorno, version_prompt="v1.2")))
    consultas_d2.append(eventos[-1]["id_consulta"])
    with super_engine.connect() as c:
        version = c.execute(text("SELECT version_prompt FROM asistencia.intento_generacion "
                                 "WHERE id_consulta = CAST(:c AS uuid)"), {"c": eventos[-1]["id_consulta"]}).scalar_one()
    assert version == "v1.2"


def test_comparacion_de_versiones_y_veredicto_del_stream():
    from app.scripts.comprobar_stream import veredicto
    from app.scripts.medir_consulta import comparar_versiones, main
    def fila(version, caso, estado, salida, generar):
        return {"version_prompt": version, "caso": caso, "repeticion": 1, "estado": estado, "coincide": True,
                "total_cliente_ms": generar + 4000, "primer_evento_ms": 200,
                "tiempos_ms": {"por_nodo": {"generar": generar}, "espera_ms": {},
                               "etapas": [{"nodo": "generar", "ms": generar}]},
                "intentos": [{"modelo_llm": "m", "tokens_salida": salida, "tokens_entrada": 6000, "costo_usd": 0.02}]}
    c = comparar_versiones([fila("v1.1", "a", "VERIFICADA", 1000, 7500), fila("v1.2", "a", "VERIFICADA", 500, 4000)])
    assert c["v1.1"]["tokens_salida_p50"] == 1000 and c["v1.2"]["generar_ms_p50"] == 4000
    assert c["v1.2"]["estados"] == {"a#1": "VERIFICADA"}
    with pytest.raises(SystemExit):
        main(["--versiones-prompt", "v9.9"])
    assert veredicto([{"llegada_ms": t} for t in (200, 210, 4100, 11000)])["por_etapas"]
    assert not veredicto([{"llegada_ms": 11000} for _ in range(9)])["por_etapas"]


# ---------------------------------------------------------------------------
# Prompt v1.2 experimental y comparación de respuestas
# ---------------------------------------------------------------------------
def test_v1_2_es_experimental_y_no_puede_ser_vigente(engine_generacion, monkeypatch):  # noqa: F811
    from app.rag import generacion as gen
    from app.rag.parametros import ErrorParametro
    archivo = (gen.PROMPTS / gen.VERSIONES_PROMPT["v1.2"]).read_text(encoding="utf-8")
    assert archivo.startswith("<!--") and "EXPERIMENTAL, NO VIGENTE" in archivo
    assert cargar_prompt("v1.2").startswith("Eres un asistente") and "EXPERIMENTAL" not in cargar_prompt("v1.2")
    assert cargar_prompt("v1.1").startswith("Eres un asistente")
    assert "v1.2" in gen.VERSIONES_EXPERIMENTALES and "v1.1" not in gen.VERSIONES_EXPERIMENTALES
    original = gen.leer_parametros
    monkeypatch.setattr(gen, "leer_parametros", lambda s, claves: {**original(s, claves), "VERSION_PROMPT": "v1.2"})
    with engine_generacion.connect() as c, pytest.raises(ErrorParametro, match="experimental"):
        gen.configuracion_generacion(c)


def _respuesta(pasos, advertencias, citas=("F-01",)):
    return {"resumen": "Resumen.", "recomendacion": [{"tipo": t, "texto": x, "citas": list(c)} for t, x, c in pasos],
            "advertencias": list(advertencias), "factores_identificados": [],
            "citas": [{"etiqueta": e, "extracto": "texto", "extracto_traducido": None} for e in citas]}


def test_comparar_prompts_lista_las_diferencias_sin_api():
    from app.scripts.comparar_prompts import diferencias, frecuencias, informe
    v11 = _respuesta([("DERIVACION", "Referir de inmediato.", ("F-04",)),
                      ("TRATAMIENTO", "Hierro 3 mg/kg/día durante 6 meses.", ("F-03",)),
                      ("SEGUIMIENTO", "Incremento de 1 g/dL a los 30 días.", ("F-02",))],
                     ["La decisión final corresponde al profesional tratante."], ("F-02", "F-03", "F-04"))
    v12 = _respuesta([("TRATAMIENTO", "Hierro 3 mg/kg/día por 6 meses, unos 29.7 mg diarios.", ("F-03",)),
                      ("DERIVACION", "Referir de inmediato.", ("F-04",))], [], ("F-03", "F-04"))
    d = diferencias(v11, v12)
    assert d["dosis"] == ([], ["29.7 mg"])
    assert "30" in d["cifras"][0] and "29.7" in d["cifras"][1]
    assert d["frecuencias"][0] == ["a los 30 dias"] and "durante 6 meses" not in d["frecuencias"][1]
    assert [p["tipo"] for p in d["pasos_sin_equivalente"][0]] == ["SEGUIMIENTO"] and d["pasos"] == (3, 2)
    assert d["advertencias_sin_equivalente"] == (["La decisión final corresponde al profesional tratante."], [])
    assert d["citas"] == (["F-02"], [])
    assert frecuencias("por 6 meses, diaria") == {"durante 6 meses", "diario"}
    texto = informe({("v1.1", "d"): (v11, 900), ("v1.2", "d"): (v12, 700)}, ("v1.1", "v1.2"), ["d"], "Prueba.")
    assert "## Caso d" in texto and "#### v1.1 (900 tokens de salida)" in texto and "#### Diferencias" in texto
    assert "| d | 900 | 700 | 3 / 2 | 1 / 0 | ninguna | 29.7 mg |" in texto
