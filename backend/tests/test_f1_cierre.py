"""Parte F1 del Sprint 2, con modelos falsos y el cliente falso del modelo de lenguaje (nunca la
API real):

- P2: las consultas de prueba (modelo_llm = modelo-falso) quedan fuera de los indicadores de M02
  y de las vistas agregadas (migración 011), pero siguen en la lista del paciente con modo_prueba.
- P5: POST /api/consultas/{id}/continuar reanuda una consulta TAMIZAJE_NO_VIGENTE con la pregunta
  original guardada en el servidor.
- P6: el resultado indica si el tramo de edad de los puntos de corte cambió entre el tamizaje y
  la fecha de la consulta.
(P1, la nota de la decisión filtrada, está con las demás pruebas de la decisión en test_d2_api.py.)"""
import json
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import text

from app.rag.cliente_llm import APROBADA, EVIDENCIA_INSUFICIENTE, ClienteFalso
from app.core.fechas import hoy
from app.services import pacientes as srv_pacientes
from app.services import resultados as res
from app.services.clasificacion import tramo_de_edad
from tests.test_d1_grafo import _caso, _ids, entorno  # noqa: F401 (fixtures)
from tests.test_d2_api import (_auditoria, _caso_http, _consultar, _cuerpo, cliente_http, consultas_d2,  # noqa: F401
                               usar_entorno)
from tests.test_generacion_bd import engine_clinica, engine_generacion, guia  # noqa: F401 (fixtures)

MIGRACION_011 = Path(__file__).resolve().parents[2] / "db" / "migraciones" / "011_metricas_sin_prueba.sql"
MODELO_REAL = "claude-sonnet-5-5"  # el cliente falso con este nombre se comporta como uno real (modo_prueba false)


# ---------------------------------------------------------------------------
# Migración 011 (va primero: las pruebas de P2 usan las vistas redefinidas)
# ---------------------------------------------------------------------------
def test_migracion_011_es_idempotente_y_conserva_las_columnas(super_engine):
    sql = MIGRACION_011.read_text(encoding="utf-8")
    vistas = ("asistencia.v_consultas_sin_evidencia", "asistencia.v_indicadores_operativos",
              "conocimiento.v_uso_documento")
    with super_engine.begin() as c:
        antes = {v: [r[0] for r in c.execute(text(f"SELECT * FROM {v} LIMIT 0")).cursor.description] for v in vistas}
        c.exec_driver_sql(sql)
        c.exec_driver_sql(sql)
        despues = {v: [r[0] for r in c.execute(text(f"SELECT * FROM {v} LIMIT 0")).cursor.description] for v in vistas}
        for v in vistas:
            assert "modelo-falso" in c.execute(text("SELECT pg_get_viewdef(CAST(:v AS regclass))"), {"v": v}).scalar_one()
        permisos = c.execute(text(
            """SELECT count(*) FROM information_schema.role_table_grants
                WHERE grantee = 'rol_auditor' AND table_name = 'v_indicadores_operativos'""")).scalar_one()
    assert antes == despues and permisos >= 1


# ---------------------------------------------------------------------------
# P2: consultas de prueba fuera de las métricas
# ---------------------------------------------------------------------------
def _consulta(cliente_http, cabeceras, consultas_d2, super_engine, usar_entorno, id_caso, modos, modelo):  # noqa: F811
    usar_entorno(cliente=ClienteFalso(modos, modelo=modelo) if modelo else ClienteFalso(modos))
    caso = _caso(id_caso)
    id_paciente, id_tamizaje, _ = _ids(super_engine, caso)
    fin = _consultar(cliente_http, cabeceras, consultas_d2, id_paciente, _cuerpo(caso, id_tamizaje=id_tamizaje))[1][-1]
    return fin


def test_indicadores_de_m02_cuentan_solo_las_consultas_reales(cliente_http, cabeceras, consultas_d2, super_engine,
                                                              usar_entorno, engine_generacion):  # noqa: F811
    with engine_generacion.connect() as c:
        base, _ = srv_pacientes.metricas_consultas(c, hoy())
    base = base or 0
    # Una consulta de prueba (cliente falso) y una real (mismo cliente con el nombre del modelo real), el mismo día.
    prueba = _consulta(cliente_http, cabeceras, consultas_d2, super_engine, usar_entorno, "b", [APROBADA], None)
    real = _consulta(cliente_http, cabeceras, consultas_d2, super_engine, usar_entorno, "b", [APROBADA], MODELO_REAL)
    assert (prueba["estado"], prueba["modo_prueba"]) == ("VERIFICADA", True)
    assert (real["estado"], real["modo_prueba"]) == ("VERIFICADA", False)
    with engine_generacion.connect() as c:
        evaluaciones, tiempo = srv_pacientes.metricas_consultas(c, hoy())
        latencia = c.execute(text("SELECT latencia_total_ms FROM asistencia.consulta WHERE id_consulta = CAST(:c AS uuid)"),
                             {"c": real["id_consulta"]}).scalar_one()
    assert evaluaciones == base + 1
    if base == 0:
        assert tiempo == round(latencia / 1000, 1)
    datos = cliente_http.get("/api/pacientes/indicadores", headers=cabeceras("enf.rojas")).json()
    assert datos["evaluaciones_hoy"] == base + 1 and datos["tiempo_medio_respuesta_s"] is not None
    # El historial del paciente sigue mostrando la consulta de prueba, con su marca.
    id_paciente, _, _ = _ids(super_engine, _caso("b"))
    lista = cliente_http.get(f"/api/pacientes/{id_paciente}/consultas", headers=cabeceras("med.salazar")).json()
    marcas = {c["id_consulta"]: c["modo_prueba"] for c in lista}
    assert marcas[prueba["id_consulta"]] is True and marcas[real["id_consulta"]] is False


def test_sin_consultas_reales_los_indicadores_quedan_sin_datos(cliente_http, cabeceras, consultas_d2, super_engine,
                                                              usar_entorno, engine_generacion):  # noqa: F811
    with engine_generacion.connect() as c:
        antes = srv_pacientes.metricas_consultas(c, hoy())
        # Un día sin consultas: «Sin datos» (nulos), no cero.
        assert srv_pacientes.metricas_consultas(c, date(2000, 1, 1)) == (None, None)
    # Solo consultas de prueba (también en EVIDENCIA_INSUFICIENTE): los indicadores no cambian.
    _consulta(cliente_http, cabeceras, consultas_d2, super_engine, usar_entorno, "b", [APROBADA], None)
    _consulta(cliente_http, cabeceras, consultas_d2, super_engine, usar_entorno, "j", [EVIDENCIA_INSUFICIENTE], None)
    with engine_generacion.connect() as c:
        assert srv_pacientes.metricas_consultas(c, hoy()) == antes


def test_error_y_estados_sin_evaluacion_no_cuentan_y_evidencia_insuficiente_si(
        cliente_http, cabeceras, consultas_d2, super_engine, usar_entorno, engine_generacion):  # noqa: F811
    from app.rag.cliente_llm import RECHAZO
    with engine_generacion.connect() as c:
        base = srv_pacientes.metricas_consultas(c, hoy())[0] or 0
    error = _consulta(cliente_http, cabeceras, consultas_d2, super_engine, usar_entorno, "b", [RECHAZO], MODELO_REAL)
    fuera = _consulta(cliente_http, cabeceras, consultas_d2, super_engine, usar_entorno, "h", [APROBADA], MODELO_REAL)
    assert (error["estado"], fuera["estado"]) == ("ERROR", "FUERA_DE_DOMINIO")
    with engine_generacion.connect() as c:
        assert (srv_pacientes.metricas_consultas(c, hoy())[0] or 0) == base
    insuficiente = _consulta(cliente_http, cabeceras, consultas_d2, super_engine, usar_entorno, "j",
                             [EVIDENCIA_INSUFICIENTE], MODELO_REAL)
    assert insuficiente["estado"] == "EVIDENCIA_INSUFICIENTE"
    with engine_generacion.connect() as c:
        assert srv_pacientes.metricas_consultas(c, hoy())[0] == base + 1


def test_vistas_agregadas_excluyen_las_consultas_de_prueba(cliente_http, cabeceras, consultas_d2, super_engine,
                                                           usar_entorno):  # noqa: F811
    def leer():
        with super_engine.connect() as c:
            sin_evidencia = set(c.execute(text("SELECT id_consulta::text FROM asistencia.v_consultas_sin_evidencia")).scalars())
            operativos = c.execute(text("SELECT consultas FROM asistencia.v_indicadores_operativos")).scalar_one()
            citas = c.execute(text("SELECT coalesce(sum(citas_30_dias), 0) FROM conocimiento.v_uso_documento")).scalar_one()
        return sin_evidencia, operativos, citas

    _, operativos_antes, citas_antes = leer()
    ei_prueba = _consulta(cliente_http, cabeceras, consultas_d2, super_engine, usar_entorno, "j",
                          [EVIDENCIA_INSUFICIENTE], None)
    verificada_prueba = _consulta(cliente_http, cabeceras, consultas_d2, super_engine, usar_entorno, "b", [APROBADA], None)
    sin_evidencia, operativos, citas = leer()
    assert ei_prueba["id_consulta"] not in sin_evidencia
    assert (operativos, citas) == (operativos_antes, citas_antes)
    assert verificada_prueba["citas"]  # la de prueba sí tiene citas, pero no se cuentan
    ei_real = _consulta(cliente_http, cabeceras, consultas_d2, super_engine, usar_entorno, "j",
                        [EVIDENCIA_INSUFICIENTE], MODELO_REAL)
    verificada_real = _consulta(cliente_http, cabeceras, consultas_d2, super_engine, usar_entorno, "b", [APROBADA],
                                MODELO_REAL)
    sin_evidencia, operativos, citas = leer()
    assert ei_real["id_consulta"] in sin_evidencia
    assert operativos == operativos_antes + 2
    assert citas == citas_antes + len(verificada_real["citas"])


# ---------------------------------------------------------------------------
# P5: continuar una consulta TAMIZAJE_NO_VIGENTE con la pregunta guardada
# ---------------------------------------------------------------------------
def _texto_original(super_engine, id_consulta: str) -> str:
    with super_engine.connect() as c:
        return c.execute(text("SELECT texto_consulta FROM asistencia.consulta WHERE id_consulta = CAST(:c AS uuid)"),
                         {"c": id_consulta}).scalar_one()


def test_continuar_reanuda_con_la_pregunta_guardada(cliente_http, cabeceras, consultas_d2, super_engine,
                                                    usar_entorno):
    # La pregunta nombra a la paciente: el texto filtrado ([PACIENTE]) y el original difieren, y la
    # consulta reanudada debe guardar el original, no el filtrado que antes reenviaba la interfaz.
    pregunta = "¿Qué dosis de hierro le corresponde a Luana Paucar por su anemia?"
    previa = _caso_http(cliente_http, cabeceras, consultas_d2, super_engine, usar_entorno, "f",
                        confirma_tamizaje_no_vigente=False, texto_consulta=pregunta)[1][-1]
    assert previa["estado"] == "TAMIZAJE_NO_VIGENTE"
    ruta = f"/api/consultas/{previa['id_consulta']}/continuar"
    # Otro profesional: 404 y queda auditado, sin reanudar.
    assert cliente_http.post(ruta, headers=cabeceras("enf.rojas")).status_code == 404
    assert [d["accion"] for d in _auditoria(super_engine, "ACCESO_DENEGADO_CONSULTA", previa["id_consulta"])] == [
        "continuar"]
    # El dueño: sin cuerpo, NDJSON y consulta nueva enlazada, con la pregunta original (no la filtrada).
    r, eventos = _consultar(cliente_http, cabeceras, consultas_d2, None, None, ruta=ruta)
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/x-ndjson")
    fin = eventos[-1]
    assert fin["tipo"] == "fin" and fin["estado"] == "VERIFICADA"
    assert fin["id_consulta_previa"] == previa["id_consulta"] and fin["id_consulta"] != previa["id_consulta"]
    assert fin["vigencia"]["continua_con_tamizaje_no_vigente"] is True
    assert _texto_original(super_engine, fin["id_consulta"]) == _texto_original(super_engine, previa["id_consulta"]) == pregunta
    filtrado = cliente_http.get(f"/api/consultas/{fin['id_consulta']}", headers=cabeceras("med.salazar")).json()["texto_filtrado"]
    assert "[PACIENTE]" in filtrado and "Luana" not in filtrado
    with super_engine.connect() as c:
        confirma, tamizaje_nueva, tamizaje_previa = c.execute(text(
            """SELECT n.confirma_tamizaje_no_vigente, n.id_tamizaje::text, p.id_tamizaje::text
                 FROM asistencia.consulta n JOIN asistencia.consulta p ON p.id_consulta = n.id_consulta_previa
                WHERE n.id_consulta = CAST(:c AS uuid)"""), {"c": fin["id_consulta"]}).one()
    assert confirma is True and tamizaje_nueva == tamizaje_previa
    # Auditoría sin texto clínico.
    id_paciente, _, _ = _ids(super_engine, _caso("f"))
    # _auditoria no ordena: se busca el evento de esta reanudación por su consulta previa.
    detalles = [d for d in _auditoria(super_engine, "CONSULTA_INICIADA", id_paciente)
                if d.get("id_consulta_previa") == previa["id_consulta"]]
    assert detalles == [{"id_tamizaje": tamizaje_previa, "id_consulta_previa": previa["id_consulta"],
                         "confirma_tamizaje_no_vigente": True}]
    # Segunda vez: ya se reanudó.
    r = cliente_http.post(ruta, headers=cabeceras("med.salazar"))
    assert r.status_code == 409 and "ya se reanudó" in r.json()["detail"]


def test_continuar_rechaza_otros_estados_y_roles(cliente_http, cabeceras, consultas_d2, super_engine, usar_entorno):
    verificada = _caso_http(cliente_http, cabeceras, consultas_d2, super_engine, usar_entorno, "b")[1][-1]
    r = cliente_http.post(f"/api/consultas/{verificada['id_consulta']}/continuar", headers=cabeceras("med.salazar"))
    assert r.status_code == 409 and "no está pendiente" in r.json()["detail"]
    assert cliente_http.post(f"/api/consultas/{verificada['id_consulta']}/continuar",
                             headers=cabeceras("admin.cdss")).status_code == 403
    assert cliente_http.post("/api/consultas/00000000-0000-4000-8000-00000000abcd/continuar",
                             headers=cabeceras("med.salazar")).status_code == 404
    assert cliente_http.post(f"/api/consultas/{verificada['id_consulta']}/continuar").status_code == 401


# ---------------------------------------------------------------------------
# P6: cambio de tramo de edad entre el tamizaje y la consulta
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("nacimiento, edad_tamizaje, fecha_consulta, antes, ahora, cambio", [
    # De 5 a 6 meses: sin punto de corte (menor de 6 meses) a 6 a 23 meses.
    (date(2026, 5, 10), 5, date(2026, 11, 10), None, (6, 23), True),
    # De 23 a 24 meses.
    (date(2024, 11, 10), 23, date(2026, 11, 10), (6, 23), (24, 59), True),
    # Sin cambio: de 10 a 11 meses, el mismo tramo.
    (date(2025, 12, 1), 10, date(2026, 11, 1), (6, 23), (6, 23), False),
    # El día antes de cumplir 6 meses sigue fuera de los puntos de corte.
    (date(2026, 5, 10), 5, date(2026, 11, 9), None, None, False),
    # De 59 a 60 meses: deja de estar cubierto.
    (date(2021, 11, 10), 59, date(2026, 11, 10), (24, 59), None, True),
])
def test_comparar_tramos_en_los_limites(engine_clinica, nacimiento, edad_tamizaje, fecha_consulta, antes, ahora,  # noqa: F811
                                        cambio):
    with engine_clinica.connect() as c:
        r = res.comparar_tramos(c, edad_tamizaje, nacimiento, fecha_consulta)
        assert tramo_de_edad(c, edad_tamizaje) == antes
    tramo = (lambda t: None if t is None else {"edad_min_meses": t[0], "edad_max_meses": t[1]})
    assert r == {"edad_meses_tamizaje": edad_tamizaje, "edad_meses_consulta": r["edad_meses_consulta"],
                 "tramo_tamizaje": tramo(antes), "tramo_consulta": tramo(ahora), "cambio": cambio}


def test_el_resultado_trae_el_tramo_de_edad(cliente_http, cabeceras, consultas_d2, super_engine, usar_entorno):
    fin = _caso_http(cliente_http, cabeceras, consultas_d2, super_engine, usar_entorno, "b")[1][-1]
    resultado = cliente_http.get(f"/api/consultas/{fin['id_consulta']}", headers=cabeceras("med.salazar")).json()
    tramo = resultado["tramo_edad"]
    with super_engine.connect() as c:
        fila = c.execute(text(
            """SELECT t.edad_meses, p.fecha_nacimiento, (q.fecha_hora_inicio AT TIME ZONE 'America/Lima')::date
                 FROM asistencia.consulta q JOIN clinico.tamizaje t ON t.id_tamizaje = q.id_tamizaje
                 JOIN clinico.paciente p ON p.id_paciente = t.id_paciente
                WHERE q.id_consulta = CAST(:c AS uuid)"""), {"c": fin["id_consulta"]}).one()
        esperado = res.comparar_tramos(c, *fila)
    assert tramo == json.loads(json.dumps(esperado))
    assert set(tramo) == {"edad_meses_tamizaje", "edad_meses_consulta", "tramo_tamizaje", "tramo_consulta", "cambio"}
