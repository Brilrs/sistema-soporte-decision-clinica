"""Parte D1 del Sprint 3: API de auditoría (M13, HU13) y migración 014.

Las consultas de estas pruebas se insertan directamente con la conexión de administración (datos
sintéticos de seed_demo, sin el grafo ni el modelo de lenguaje) y se borran al final. Las fechas
de la lista son de 2001, lejos de los datos de otras pruebas y fuera de la ventana de 30 días de
los indicadores; las de los indicadores son relativas a now() de la base, así que nada depende de
la hora del equipo. Ningún orden se compara con sorted() sobre textos: el desempate es por uuid,
que la base compara por bytes (igual que UUID.bytes en Python)."""
import json
import os
import re
import uuid
from pathlib import Path

import pytest
from psycopg import errors as pg
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from app.core.db import engines
from tests.test_generacion_bd import guia  # noqa: F401 (fixture)

RAIZ = Path(__file__).resolve().parents[2]
MIGRACIONES = RAIZ / "db" / "migraciones"
RUTAS = ("/api/auditoria/indicadores", "/api/auditoria/consultas",
         "/api/auditoria/consultas/00000000-0000-4000-8000-000000000000")
SIN_PERMISO = ("enf.rojas", "med.salazar", "nut.vilca")
CON_PERMISO = ("coord.ortiz", "admin.cdss")
MODELO_FALSO = "modelo-falso"
MODELO_REAL = "claude-sonnet-5-5"


# ---------------------------------------------------------------------------
# Datos de prueba
# ---------------------------------------------------------------------------
@pytest.fixture
def auditadas(super_engine):
    """Ids de las consultas insertadas; al final se borran con sus intentos, fragmentos y decisión."""
    ids: list[str] = []
    yield ids
    if not ids:
        return
    with super_engine.begin() as c:
        p = {"ids": ids}
        intentos = "(SELECT id_intento FROM asistencia.intento_generacion WHERE id_consulta::text = ANY(:ids))"
        c.execute(text("DELETE FROM asistencia.decision_clinica WHERE id_consulta::text = ANY(:ids)"), p)
        c.execute(text(f"DELETE FROM asistencia.fragmento_recuperado WHERE id_intento IN {intentos}"), p)
        c.execute(text("DELETE FROM asistencia.intento_generacion WHERE id_consulta::text = ANY(:ids)"), p)
        c.execute(text("DELETE FROM asistencia.consulta WHERE id_consulta::text = ANY(:ids)"), p)


@pytest.fixture(scope="module")
def paciente(super_engine):
    """Un paciente de seed_demo con tamizaje, con su identidad descifrada (solo para buscarla en las
    respuestas) y la fecha de nacimiento."""
    with super_engine.connect() as c:
        f = c.execute(text(
            """SELECT t.id_tamizaje::text, p.fecha_nacimiento,
                      pgp_sym_decrypt(i.nombres_apellidos_cifrado, :k) AS nombre,
                      pgp_sym_decrypt(i.dni_cifrado, :k) AS dni, pgp_sym_decrypt(i.numero_hc_cifrado, :k) AS hc
                 FROM clinico.tamizaje t
                 JOIN clinico.paciente p ON p.id_paciente = t.id_paciente
                 JOIN clinico.paciente_identidad i ON i.id_paciente = t.id_paciente
                ORDER BY t.fecha_registro, t.id_tamizaje LIMIT 1"""), {"k": os.environ["CDSS_CLAVE_PII"]}).mappings().one()
    return dict(f)


def _usuario(c, nombre: str) -> str:
    return c.execute(text("SELECT id_usuario::text FROM seguridad.usuario WHERE nombre_usuario = :n"),
                     {"n": nombre}).scalar_one()


def _consulta(super_engine, auditadas, paciente, *, inicio: str, estado: str = "VERIFICADA", intentos=(),
              usuario: str = "enf.rojas", latencia: int | None = 5000, id_consulta: str | None = None,
              texto_consulta: str = "¿Qué dosis le corresponde?") -> str:
    """inicio: expresión SQL de la fecha y hora de inicio (por ejemplo, now() - interval '1 hour').
    intentos: dicts con modelo, resultado y, si se quiere, solicitud, control, tokens y fecha."""
    id_consulta = id_consulta or str(uuid.uuid4())
    with super_engine.begin() as c:
        c.execute(text(
            f"""INSERT INTO asistencia.consulta (id_consulta, id_tamizaje, id_usuario, texto_consulta, texto_filtrado,
                                                 estado, numero_intentos, fecha_hora_inicio, fecha_hora_fin,
                                                 latencia_total_ms)
                VALUES (CAST(:id AS uuid), CAST(:t AS uuid), CAST(:u AS uuid), :txt, 'pregunta filtrada', :e, :n,
                        {inicio}, {inicio} + interval '5 seconds', :l)"""),
            {"id": id_consulta, "t": paciente["id_tamizaje"], "u": _usuario(c, usuario), "txt": texto_consulta,
             "e": estado, "n": len(intentos), "l": latencia})
        for n, i in enumerate(intentos, start=1):
            i.setdefault("id_intento", str(uuid.uuid4()))
            c.execute(text(
                f"""INSERT INTO asistencia.intento_generacion
                      (id_intento, id_consulta, numero_intento, tipo_busqueda, consulta_reformulada, candidatos_evaluados,
                       relevancia_maxima, umbral_relevancia, solicitud_enviada, hash_solicitud, control_identificadores,
                       modelo_llm, version_prompt, tokens_entrada, tokens_salida, tokens_razonamiento, costo_usd,
                       latencia_llm_ms, valida_citas, valida_consistencia, valida_evidencia, resultado, fecha_hora)
                    VALUES (CAST(:id AS uuid), CAST(:c AS uuid), :n, :tb, 'consulta reformulada', 8, 0.412, 0.15,
                            CAST(:sol AS jsonb), :h, :ci, :m, 'v1.1', :te, :ts, 12, :costo, 3000, :vc, true, :ve, :res,
                            {i.get('fecha', inicio)})"""),
                {"id": i["id_intento"], "c": id_consulta, "n": n, "tb": "INICIAL" if n == 1 else "AMPLIADA",
                 "sol": json.dumps(i["solicitud"]) if i.get("solicitud") is not None else None,
                 "h": "a" * 64, "ci": i.get("control", True), "m": i["modelo"], "te": i.get("tokens_entrada", 5000),
                 "ts": i.get("tokens_salida", 400), "costo": i.get("costo", 0.021), "vc": i.get("valida_citas", True),
                 "ve": i.get("valida_evidencia", True), "res": i["resultado"]})
    auditadas.append(id_consulta)
    return id_consulta


def _real(resultado="APROBADO", **extra):
    return {"modelo": MODELO_REAL, "resultado": resultado, **extra}


def _prueba(resultado="APROBADO", **extra):
    return {"modelo": MODELO_FALSO, "resultado": resultado, **extra}


def _contiene(texto: str, valor: str) -> bool:
    """El valor como palabra completa (una historia clínica de 5 cifras no debe coincidir por azar
    dentro de un uuid o de una fecha con microsegundos)."""
    return re.search(rf"(?<![0-9A-Za-z]){re.escape(valor)}(?![0-9A-Za-z])", texto) is not None


def _get(cliente, cabeceras, ruta, usuario="coord.ortiz"):
    return cliente.get(ruta, headers=cabeceras(usuario))


# ---------------------------------------------------------------------------
# Migración 014 y permisos de cdss_auditor
# ---------------------------------------------------------------------------
def _columnas(c, vista: str) -> list[str]:
    return [r[0] for r in c.execute(text(f"SELECT * FROM {vista} LIMIT 0")).cursor.description]


def test_migracion_014_es_idempotente_y_011_y_012_no_la_deshacen(super_engine):
    vistas = ("asistencia.v_auditoria_consulta", "asistencia.v_auditoria_lista", "asistencia.v_indicadores_operativos")
    with super_engine.begin() as c:
        antes = {v: _columnas(c, v) for v in vistas}
        for archivo in ("014_auditoria.sql", "014_auditoria.sql", "011_metricas_sin_prueba.sql",
                        "012_origen_fragmento.sql", "014_auditoria.sql"):
            c.exec_driver_sql((MIGRACIONES / archivo).read_text(encoding="utf-8"))
        despues = {v: _columnas(c, v) for v in vistas}
        permisos = set(c.execute(text(
            """SELECT table_name || ':' || privilege_type FROM information_schema.role_table_grants
                WHERE grantee = 'rol_auditor' AND table_schema = 'asistencia'""")).scalars())
    assert antes == despues
    assert {"modo_prueba", "version_prompt", "latencia_total_ms", "control_identificadores"} <= set(despues[vistas[0]])
    assert {"modo_prueba", "latencia_total_ms", "tokens_entrada", "costo_usd"} <= set(despues[vistas[1]])
    assert {"p50_ms", "p90_ms", "solicitudes_bloqueadas", "errores", "evaluadas"} <= set(despues[vistas[2]])
    assert permisos == {"v_auditoria_consulta:SELECT", "v_auditoria_lista:SELECT", "v_indicadores_operativos:SELECT"}


def test_las_vistas_del_auditor_no_tienen_columnas_de_identidad_ni_texto_original(super_engine):
    prohibidas = {"nombres_apellidos", "nombres_apellidos_cifrado", "dni", "dni_cifrado", "dni_hash", "numero_hc",
                  "numero_hc_cifrado", "numero_hc_hash", "direccion_cifrada", "fecha_nacimiento", "texto_consulta",
                  "observaciones", "descripcion", "id_paciente", "texto_filtrado", "respuesta_borrador"}
    with super_engine.connect() as c:
        for v in ("asistencia.v_auditoria_consulta", "asistencia.v_auditoria_lista", "asistencia.v_indicadores_operativos"):
            assert not prohibidas & set(_columnas(c, v)), v


@pytest.fixture(scope="module")
def engine_auditor_directo():
    """cdss_auditor sin la opción de solo lectura de la aplicación: así lo que se prueba es el
    permiso del rol en la base."""
    return create_engine(os.environ["DATABASE_URL_AUDITOR"])


@pytest.mark.parametrize("sql", [
    "SELECT nombres_apellidos_cifrado FROM clinico.paciente_identidad LIMIT 1",
    "SELECT dni_hash FROM clinico.paciente_identidad LIMIT 1",
    "SELECT fecha_nacimiento FROM clinico.paciente LIMIT 1",
    "SELECT texto_consulta FROM asistencia.consulta LIMIT 1",
    "SELECT texto_filtrado FROM asistencia.consulta LIMIT 1",
    "SELECT observaciones FROM clinico.tamizaje LIMIT 1",
    "SELECT descripcion FROM asistencia.decision_clinica LIMIT 1",
    "SELECT solicitud_enviada FROM asistencia.intento_generacion LIMIT 1",
])
def test_cdss_auditor_no_lee_identidad_texto_original_ni_observaciones(engine_auditor_directo, sql):
    with engine_auditor_directo.connect() as c, pytest.raises(DBAPIError) as e:
        c.execute(text(sql))
    assert isinstance(e.value.orig, pg.InsufficientPrivilege)


@pytest.mark.parametrize("sql", [
    "INSERT INTO auditoria.evento_auditoria (tipo_evento) VALUES ('PRUEBA_AUDITOR')",
    "UPDATE auditoria.evento_auditoria SET tipo_evento = tipo_evento WHERE false",
    "DELETE FROM auditoria.evento_auditoria WHERE false",
    "UPDATE asistencia.consulta SET estado = estado WHERE false",
    "INSERT INTO asistencia.decision_clinica (id_consulta, id_usuario, tipo_decision) VALUES (gen_random_uuid(), gen_random_uuid(), 'ACEPTA_RECOMENDACION')",
])
def test_cdss_auditor_no_escribe(engine_auditor_directo, sql):
    with engine_auditor_directo.connect() as c, pytest.raises(DBAPIError) as e:
        c.execute(text(sql))
    assert isinstance(e.value.orig, pg.InsufficientPrivilege)


def test_cdss_auditor_solo_tiene_select_sobre_las_vistas_y_la_bitacora(super_engine):
    with super_engine.connect() as c:
        tablas = set(c.execute(text(
            """SELECT table_schema || '.' || table_name || ':' || privilege_type
                 FROM information_schema.role_table_grants WHERE grantee IN ('rol_auditor', 'cdss_auditor')""")).scalars())
        columnas = c.execute(text(
            """SELECT count(*) FROM information_schema.column_privileges
                WHERE grantee IN ('rol_auditor', 'cdss_auditor') AND table_schema IN ('clinico', 'asistencia', 'seguridad')
                  AND table_name NOT LIKE 'v\\_%'""")).scalar_one()
    assert {t.split(":")[1] for t in tablas} == {"SELECT"}
    assert {t.split(":")[0] for t in tablas if not t.startswith("auditoria.")} == {
        "asistencia.v_auditoria_consulta", "asistencia.v_auditoria_lista", "asistencia.v_indicadores_operativos"}
    assert columnas == 0


def test_la_conexion_del_auditor_de_la_aplicacion_es_de_solo_lectura():
    with engines()["auditor"].connect() as c:
        assert c.execute(text("SELECT current_user")).scalar_one() == "cdss_auditor"
        assert c.execute(text("SHOW default_transaction_read_only")).scalar_one() == "on"


# ---------------------------------------------------------------------------
# Permisos de las rutas
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("ruta", RUTAS)
def test_sin_sesion_responde_401(cliente, ruta):
    assert cliente.get(ruta).status_code == 401


@pytest.mark.parametrize("usuario", SIN_PERMISO)
@pytest.mark.parametrize("ruta", RUTAS)
def test_roles_clinicos_sin_ver_auditoria_reciben_403(cliente, cabeceras, usuario, ruta):
    r = _get(cliente, cabeceras, ruta, usuario)
    assert r.status_code == 403
    assert r.json()["detail"] == "Su rol no tiene el permiso VER_AUDITORIA"


@pytest.mark.parametrize("usuario", CON_PERMISO)
def test_coordinador_y_administrador_acceden(cliente, cabeceras, usuario):
    assert _get(cliente, cabeceras, RUTAS[0], usuario).status_code == 200
    assert _get(cliente, cabeceras, RUTAS[1], usuario).status_code == 200
    assert _get(cliente, cabeceras, RUTAS[2], usuario).status_code == 404


# ---------------------------------------------------------------------------
# Indicadores
# ---------------------------------------------------------------------------
def test_indicadores_excluyen_las_consultas_de_prueba_y_coinciden_con_la_vista(cliente, cabeceras, super_engine,
                                                                               auditadas, paciente):
    antes = _get(cliente, cabeceras, RUTAS[0]).json()
    reciente = "now() - interval '1 hour'"
    _consulta(super_engine, auditadas, paciente, inicio=reciente, intentos=[_real(tokens_entrada=1000, tokens_salida=100,
                                                                                  costo=0.5)])
    _consulta(super_engine, auditadas, paciente, inicio=reciente, estado="EVIDENCIA_INSUFICIENTE", latencia=9000,
              intentos=[_real("REINTENTO", tokens_entrada=10, tokens_salida=1, costo=0.25),
                        _real("EVIDENCIA_INSUFICIENTE", tokens_entrada=10, tokens_salida=1, costo=0.25)])
    _consulta(super_engine, auditadas, paciente, inicio=reciente, estado="SOLICITUD_BLOQUEADA",
              intentos=[_real("ERROR", control=False, tokens_entrada=None, tokens_salida=None, costo=None)])
    # De prueba (cliente falso): no cuentan aunque sean recientes, ni sus tokens ni su costo.
    _consulta(super_engine, auditadas, paciente, inicio=reciente,
              intentos=[_prueba(tokens_entrada=777777, tokens_salida=7777, costo=7.0)])
    _consulta(super_engine, auditadas, paciente, inicio=reciente, estado="ERROR", intentos=[_prueba("ERROR")])
    # Fuera de la ventana de 30 días.
    hace_31 = "now() - interval '31 days'"
    _consulta(super_engine, auditadas, paciente, inicio=hace_31, intentos=[_real(fecha=hace_31, costo=3.0)])

    despues = _get(cliente, cabeceras, RUTAS[0]).json()
    assert despues["consultas"] == antes["consultas"] + 3
    assert despues["evaluadas"] == antes["evaluadas"] + 2
    assert despues["por_estado"]["VERIFICADA"] == antes["por_estado"]["VERIFICADA"] + 1
    assert despues["por_estado"]["EVIDENCIA_INSUFICIENTE"] == antes["por_estado"]["EVIDENCIA_INSUFICIENTE"] + 1
    assert despues["por_estado"]["ERROR"] == antes["por_estado"]["ERROR"]
    assert despues["solicitudes_bloqueadas"] == antes["solicitudes_bloqueadas"] + 1
    assert despues["errores"] == antes["errores"]
    assert despues["con_reintento"] == antes["con_reintento"] + 1
    assert despues["tokens_entrada"] == antes["tokens_entrada"] + 1020
    assert despues["tokens_salida"] == antes["tokens_salida"] + 102
    assert despues["costo_api_usd"] == pytest.approx(antes["costo_api_usd"] + 1.0)
    assert despues["dias"] == 30

    # Mismos valores que la vista (leída con la conexión de administración).
    with super_engine.connect() as c:
        v = c.execute(text("SELECT * FROM asistencia.v_indicadores_operativos")).mappings().one()
    assert despues["consultas"] == v["consultas"] and despues["errores"] == v["errores"]
    assert despues["latencia_p50_ms"] == round(v["p50_ms"]) and despues["latencia_p90_ms"] == round(v["p90_ms"])
    assert despues["latencia_p90_flujo_normal_ms"] == round(v["p90_flujo_normal_ms"])
    assert despues["pct_evidencia_insuficiente"] == float(v["pct_evidencia_insuficiente"])
    assert despues["pct_verificadas"] == float(v["pct_verificadas"])
    assert sum(despues["por_estado"].values()) == despues["consultas"]
    assert despues["pct_verificadas"] == pytest.approx(100 * despues["por_estado"]["VERIFICADA"] / despues["consultas"],
                                                       abs=0.051)


# ---------------------------------------------------------------------------
# Lista: filtros, pruebas ocultas, paginación y orden
# ---------------------------------------------------------------------------
@pytest.fixture
def lista_2001(super_engine, auditadas, paciente):
    """Consultas en marzo de 2001 (UTC; Lima es UTC-5):
    a: 10/03 00:00 Lima          b: 09/03 23:59:59 Lima (fuera del rango)
    c1 y c2: 11/03 10:00 Lima, la misma fecha y hora (desempate por id)
    e: 11/03 11:00 Lima, de prueba    f: 11/03 23:59:59 Lima    g: 12/03 00:00 Lima (fuera del rango)"""
    def ins(inicio, **kw):
        return _consulta(super_engine, auditadas, paciente, inicio=f"TIMESTAMPTZ '{inicio}'", **kw)
    ids = {
        "a": ins("2001-03-10 05:00:00+00", intentos=[_real()]),
        "b": ins("2001-03-10 04:59:59+00", estado="ERROR", intentos=[_real("ERROR")]),
        "c1": ins("2001-03-11 15:00:00+00", estado="EVIDENCIA_INSUFICIENTE", intentos=[_real("EVIDENCIA_INSUFICIENTE")]),
        "c2": ins("2001-03-11 15:00:00+00", intentos=[_real()]),
        "e": ins("2001-03-11 16:00:00+00", intentos=[_prueba()]),
        "f": ins("2001-03-12 04:59:59+00", estado="FUERA_DE_DOMINIO", intentos=[], latencia=300, usuario="med.salazar"),
        "g": ins("2001-03-12 05:00:00+00", intentos=[_real()]),
    }
    # Con la misma fecha y hora, primero el id mayor (la base compara uuid por bytes).
    ids["c_orden"] = sorted([ids["c1"], ids["c2"]], key=lambda x: uuid.UUID(x).bytes, reverse=True)
    return ids


RANGO = "fecha_desde=2001-03-10&fecha_hasta=2001-03-11"


def _ids(r) -> list[str]:
    return [c["id_consulta"] for c in r.json()["consultas"]]


def test_lista_oculta_las_de_prueba_por_omision_y_respeta_el_borde_del_dia_de_lima(cliente, cabeceras, lista_2001):
    r = _get(cliente, cabeceras, f"/api/auditoria/consultas?{RANGO}")
    assert r.status_code == 200
    d = lista_2001
    assert _ids(r) == [d["f"], *d["c_orden"], d["a"]]
    assert r.json()["total"] == 4 and r.json()["incluir_pruebas"] is False
    assert all(c["modo_prueba"] is False for c in r.json()["consultas"])
    # Un solo día: 11/03 en Lima va de 05:00 UTC del 11 a 04:59:59 UTC del 12.
    r = _get(cliente, cabeceras, "/api/auditoria/consultas?fecha_desde=2001-03-11&fecha_hasta=2001-03-11")
    assert _ids(r) == [d["f"], *d["c_orden"]]
    r = _get(cliente, cabeceras, "/api/auditoria/consultas?fecha_desde=2001-03-09&fecha_hasta=2001-03-09")
    assert _ids(r) == [d["b"]]


def test_con_incluir_pruebas_las_muestra_marcadas(cliente, cabeceras, lista_2001):
    r = _get(cliente, cabeceras, f"/api/auditoria/consultas?{RANGO}&incluir_pruebas=true")
    d = lista_2001
    assert _ids(r) == [d["f"], d["e"], *d["c_orden"], d["a"]]
    assert r.json()["total"] == 5 and r.json()["incluir_pruebas"] is True
    marcas = {c["id_consulta"]: c["modo_prueba"] for c in r.json()["consultas"]}
    assert marcas[d["e"]] is True and sum(marcas.values()) == 1


def test_paginacion_total_y_orden_estable_con_fechas_iguales(cliente, cabeceras, lista_2001):
    d = lista_2001
    paginas = [_get(cliente, cabeceras, f"/api/auditoria/consultas?{RANGO}&limite=2&desplazamiento={n}") for n in (0, 2, 4)]
    assert [p.json()["total"] for p in paginas] == [4, 4, 4]
    assert [_ids(p) for p in paginas] == [[d["f"], d["c_orden"][0]], [d["c_orden"][1], d["a"]], []]
    # Repetir la misma página da el mismo resultado.
    assert _ids(_get(cliente, cabeceras, f"/api/auditoria/consultas?{RANGO}&limite=2&desplazamiento=0")) == _ids(paginas[0])


def test_filtro_de_estado_y_campos_de_cada_fila(cliente, cabeceras, lista_2001):
    d = lista_2001
    r = _get(cliente, cabeceras, f"/api/auditoria/consultas?{RANGO}&estado=EVIDENCIA_INSUFICIENTE")
    assert _ids(r) == [d["c1"]] and r.json()["total"] == 1
    fila = r.json()["consultas"][0]
    assert fila["nombre_usuario"] == "enf.rojas" and fila["modelo_llm"] == MODELO_REAL
    assert (fila["tokens_entrada"], fila["tokens_salida"], fila["tokens_total"]) == (5000, 400, 5400)
    assert fila["latencia_total_ms"] == 5000 and fila["con_reintento"] is False and fila["version_prompt"] == "v1.1"
    sin_llm = next(c for c in _get(cliente, cabeceras, f"/api/auditoria/consultas?{RANGO}").json()["consultas"]
                   if c["id_consulta"] == d["f"])
    assert sin_llm["modelo_llm"] is None and sin_llm["tokens_total"] is None and sin_llm["nombre_usuario"] == "med.salazar"


@pytest.mark.parametrize("consulta,campo", [
    ("limite=101", "limite"), ("limite=0", "limite"), ("desplazamiento=-1", "desplazamiento"),
    ("estado=CUALQUIERA", "estado"), ("fecha_desde=2001-02-30", "fecha_desde"),
    ("fecha_desde=2001-03-12&fecha_hasta=2001-03-11", "fecha_hasta"), ("incluir_pruebas=quizas", "incluir_pruebas"),
])
def test_filtros_invalidos_responden_422_con_el_formato_del_proyecto(cliente, cabeceras, consulta, campo):
    r = _get(cliente, cabeceras, f"/api/auditoria/consultas?{consulta}")
    assert r.status_code == 422
    assert r.json()["detail"].startswith("Revise los datos ingresados.")
    assert [e["campo"] for e in r.json()["errores"]] == [campo]


def test_limite_maximo_es_100(cliente, cabeceras):
    r = _get(cliente, cabeceras, "/api/auditoria/consultas?limite=100&fecha_desde=2001-01-01&fecha_hasta=2001-01-01")
    assert r.status_code == 200 and r.json()["limite"] == 100


# ---------------------------------------------------------------------------
# Detalle
# ---------------------------------------------------------------------------
def _fragmentos(super_engine, id_intento: str, ids_fragmentos: list[str]) -> None:
    with super_engine.begin() as c:
        for n, id_f in enumerate(ids_fragmentos, start=1):
            puntero = n == len(ids_fragmentos)
            c.execute(text(
                """INSERT INTO asistencia.fragmento_recuperado
                     (id_intento, id_fragmento, posicion_rrf, puntaje_rrf, puntaje_reranker, posicion_final,
                      enviado_al_llm, etiqueta_cita, origen)
                   VALUES (CAST(:i AS uuid), CAST(:f AS uuid), :p, :rrf, :rr, :pf, true, :et, :o)"""),
                {"i": id_intento, "f": id_f, "p": None if puntero else n, "rrf": None if puntero else 0.01,
                 "rr": None if puntero else round(0.9 - n / 10, 3), "pf": None if puntero else n,
                 "et": f"F-0{n}", "o": "PUNTERO" if puntero else "RERANKER"})


def test_detalle_sin_identificadores_del_paciente_y_con_la_solicitud_aprobada(cliente, cabeceras, super_engine, guia,  # noqa: F811
                                                                               auditadas, paciente):
    # guia va antes que auditadas: las consultas (y sus fragmentos recuperados) se borran primero.
    nombre, dni, hc = paciente["nombre"], paciente["dni"], paciente["hc"]
    nacimiento = paciente["fecha_nacimiento"].isoformat()
    identificadores = [nombre, dni, hc, nacimiento, *nombre.split()]
    solicitud = {"consulta": "tratamiento de anemia leve en [PACIENTE]", "paciente": {"edad_meses": 14, "sexo": "M"},
                 "evidencia": [{"etiqueta": "F-01", "texto": "Suplementación con hierro"}]}
    # Un intento bloqueado con la solicitud guardada por error (con identificadores): la vista no la muestra.
    bloqueada = {"consulta": f"tratamiento para {nombre}, DNI {dni}, HC {hc}, nacido el {nacimiento}"}
    id_consulta = _consulta(
        super_engine, auditadas, paciente, inicio="now() - interval '2 hours'", estado="VERIFICADA",
        texto_consulta=f"{nombre} con DNI {dni} e historia {hc}: ¿qué dosis?",
        intentos=[_real("REINTENTO", control=False, solicitud=bloqueada, valida_evidencia=False),
                  _real("APROBADO", solicitud=solicitud)])
    with super_engine.begin() as c:
        id_intento = c.execute(text("SELECT id_intento::text FROM asistencia.intento_generacion WHERE id_consulta = "
                                    "CAST(:c AS uuid) AND numero_intento = 2"), {"c": id_consulta}).scalar_one()
        c.execute(text("""INSERT INTO asistencia.decision_clinica (id_consulta, id_usuario, tipo_decision, descripcion)
                          VALUES (CAST(:c AS uuid), (SELECT id_usuario FROM seguridad.usuario WHERE nombre_usuario = 'enf.rojas'),
                                  'MODIFICA_RECOMENDACION', :d)"""), {"c": id_consulta, "d": f"Nota sobre {nombre}"})
    _fragmentos(super_engine, id_intento, guia["docs"][0]["ids"][:3])

    r = _get(cliente, cabeceras, f"/api/auditoria/consultas/{id_consulta}")
    assert r.status_code == 200
    completo = r.text
    assert _contiene(f"x {hc} y", hc)  # la búsqueda sí encuentra el valor cuando está
    for valor in identificadores:
        assert not _contiene(completo, valor), "el detalle contiene un identificador del paciente"
    d = r.json()
    assert (d["estado"], d["numero_intentos"], d["nombre_usuario"], d["modo_prueba"]) == ("VERIFICADA", 2, "enf.rojas", False)
    assert (d["tokens_entrada"], d["tokens_salida"], d["tokens_total"]) == (10000, 800, 10800)
    assert d["costo_usd"] == pytest.approx(0.042)
    primero, segundo = d["intentos"]
    assert (primero["numero_intento"], primero["control_identificadores"], primero["solicitud_enviada"]) == (1, False, None)
    assert primero["verificacion"]["valida_evidencia"] is False
    assert segundo["solicitud_enviada"] == solicitud
    assert (segundo["modelo_llm"], segundo["version_prompt"], segundo["tipo_busqueda"]) == (MODELO_REAL, "v1.1", "AMPLIADA")
    assert segundo["verificacion"] == {"valida_citas": True, "valida_consistencia": True, "valida_evidencia": True,
                                       "relevancia_maxima": 0.412, "umbral_relevancia": 0.15}
    assert [(f["etiqueta"], f["origen"], f["puntaje_reranker"]) for f in segundo["fragmentos"]] == [
        ("F-01", "RERANKER", 0.8), ("F-02", "RERANKER", 0.7), ("F-03", "PUNTERO", None)]
    assert segundo["fragmentos"][0]["documento"] == "PRUEBA-C-MINSA" and segundo["fragmentos"][0]["seccion"] == "Sección 1"


def test_detalle_de_una_consulta_sin_intentos(cliente, cabeceras, super_engine, auditadas, paciente):
    id_consulta = _consulta(super_engine, auditadas, paciente, inicio="now() - interval '3 hours'",
                            estado="FUERA_DE_DOMINIO", intentos=[], latencia=250)
    d = _get(cliente, cabeceras, f"/api/auditoria/consultas/{id_consulta}").json()
    assert (d["estado"], d["intentos"], d["tokens_total"], d["costo_usd"], d["latencia_total_ms"]) == (
        "FUERA_DE_DOMINIO", [], None, None, 250)


def test_detalle_de_una_consulta_de_prueba_va_marcado(cliente, cabeceras, super_engine, auditadas, paciente):
    id_consulta = _consulta(super_engine, auditadas, paciente, inicio="now() - interval '3 hours'",
                            intentos=[_prueba(solicitud={"consulta": "x"})])
    d = _get(cliente, cabeceras, f"/api/auditoria/consultas/{id_consulta}").json()
    assert d["modo_prueba"] is True and d["intentos"][0]["modelo_llm"] == MODELO_FALSO


def test_detalle_inexistente_404_e_id_invalido_422(cliente, cabeceras):
    r = _get(cliente, cabeceras, f"/api/auditoria/consultas/{uuid.uuid4()}")
    assert r.status_code == 404 and r.json()["detail"] == "La consulta no existe"
    r = _get(cliente, cabeceras, "/api/auditoria/consultas/no-es-un-id")
    assert r.status_code == 422 and r.json()["errores"][0]["campo"] == "id_consulta"


# ---------------------------------------------------------------------------
# Auditoría de la auditoría
# ---------------------------------------------------------------------------
def test_evento_auditoria_consultada_sin_datos_personales(cliente, cabeceras, super_engine, auditadas, paciente):
    with super_engine.connect() as c:
        ultimo = c.execute(text("SELECT coalesce(max(id_evento), 0) FROM auditoria.evento_auditoria")).scalar_one()
        coord = _usuario(c, "coord.ortiz")
    id_consulta = _consulta(super_engine, auditadas, paciente, inicio="now() - interval '4 hours'",
                            texto_consulta=f"{paciente['nombre']} ¿qué dosis?", intentos=[_real()])
    _get(cliente, cabeceras, f"/api/auditoria/consultas?{RANGO}&estado=VERIFICADA&incluir_pruebas=true&limite=5")
    _get(cliente, cabeceras, f"/api/auditoria/consultas/{id_consulta}")
    _get(cliente, cabeceras, f"/api/auditoria/consultas/{uuid.uuid4()}")
    _get(cliente, cabeceras, "/api/auditoria/indicadores")
    with super_engine.connect() as c:
        eventos = c.execute(text(
            """SELECT id_usuario::text, entidad, id_entidad, detalle FROM auditoria.evento_auditoria
                WHERE id_evento > :u AND tipo_evento = 'AUDITORIA_CONSULTADA' ORDER BY id_evento"""),
            {"u": ultimo}).mappings().all()
    assert len(eventos) == 3 and all(e["id_usuario"] == coord for e in eventos)
    lista, detalle, inexistente = eventos
    assert lista["id_entidad"] is None and lista["detalle"] == {
        "vista": "lista", "estado": "VERIFICADA", "fecha_desde": "2001-03-10", "fecha_hasta": "2001-03-11",
        "incluir_pruebas": True, "limite": 5, "desplazamiento": 0, "total": 0, "consultas": 0}
    assert detalle["id_entidad"] == id_consulta and detalle["detalle"] == {"vista": "detalle", "encontrada": True}
    assert inexistente["detalle"] == {"vista": "detalle", "encontrada": False}
    texto_eventos = json.dumps([dict(e) for e in eventos], ensure_ascii=False)
    for valor in (paciente["nombre"], paciente["dni"], paciente["hc"]):
        assert not _contiene(texto_eventos, valor)


# ---------------------------------------------------------------------------
# Fixtures del frontend (parte D2): las tres respuestas, generadas con datos sintéticos
# ---------------------------------------------------------------------------
DIR_FIXTURES = RAIZ / "frontend" / "src" / "__fixtures__"
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def _normalizar(datos) -> object:
    """UUID en orden de aparición, fechas de marzo de 2001 pasadas a octubre de 2026 y la ventana de
    los indicadores fija, para que el diff muestre solo cambios del contrato."""
    texto = json.dumps(datos, ensure_ascii=False)
    ids: dict[str, str] = {}
    for u in _UUID.findall(texto):
        ids.setdefault(u, f"00000000-0000-4000-8000-{len(ids) + 1:012d}")
    texto = _UUID.sub(lambda m: ids[m.group()], texto)
    texto = re.sub(r"2001-03-(\d{2})T", r"2026-10-\1T", texto)
    datos = json.loads(texto)
    if isinstance(datos, dict) and "desde" in datos and "hasta" in datos:
        datos["desde"], datos["hasta"] = "2026-09-20T15:00:00Z", "2026-10-20T15:00:00Z"
    return datos


def test_genera_los_fixtures_de_auditoria_para_el_frontend(cliente, cabeceras, super_engine, guia,  # noqa: F811
                                                           auditadas, paciente):
    from app.api.routes import auditoria as rutas
    with super_engine.connect() as c:
        recientes = c.execute(text("SELECT count(*) FROM asistencia.consulta "
                                   "WHERE fecha_hora_inicio >= now() - interval '30 days'")).scalar_one()
    if recientes:
        pytest.skip("Hay otras consultas en los últimos 30 días: los indicadores no serían reproducibles")
    solicitud = {"consulta": "tratamiento de anemia leve en niño de [EDAD] meses",
                 "paciente": {"edad_meses": 14, "sexo": "M", "hb": 9.8, "clasificacion": "anemia leve",
                              "suplementacion": False},
                 "evidencia": [{"etiqueta": "F-01", "texto": "Suplementación con hierro"},
                               {"etiqueta": "F-02", "texto": "Control de hemoglobina"},
                               {"etiqueta": "F-03", "texto": "Tabla de dosis"}]}
    # Indicadores: consultas recientes reales en varios estados y una de prueba (que no cuenta).
    hora = "now() - interval '1 hour'"
    for estado, intentos, latencia in (
            ("VERIFICADA", [_real(tokens_entrada=5020, tokens_salida=392, costo=0.021)], 7200),
            ("VERIFICADA", [_real(tokens_entrada=4600, tokens_salida=380, costo=0.019)], 6100),
            ("EVIDENCIA_INSUFICIENTE", [_real("REINTENTO", costo=0.02), _real("EVIDENCIA_INSUFICIENTE", costo=0.02)], 16300),
            ("SOLICITUD_BLOQUEADA", [_real("ERROR", control=False, tokens_entrada=None, tokens_salida=None, costo=None)], 2100),
            ("ERROR", [_real("ERROR", tokens_entrada=None, tokens_salida=None, costo=None)], 30000),
            ("FUERA_DE_DOMINIO", [], 400)):
        _consulta(super_engine, auditadas, paciente, inicio=hora, estado=estado, intentos=intentos, latencia=latencia)
    _consulta(super_engine, auditadas, paciente, inicio=hora, intentos=[_prueba()], latencia=900)
    # Lista y detalle: marzo de 2001 (fechas fijas), una real con reintento y fragmentos y una de prueba.
    inicio = "TIMESTAMPTZ '2001-03-20 15:42:00+00'"
    id_real = _consulta(super_engine, auditadas, paciente, inicio=inicio, latencia=14800,
                        intentos=[_real("REINTENTO", valida_evidencia=False, solicitud=solicitud),
                                  _real("APROBADO", solicitud=solicitud, tokens_entrada=5020, tokens_salida=392,
                                        costo=0.021)])
    with super_engine.connect() as c:
        id_intento = c.execute(text("SELECT id_intento::text FROM asistencia.intento_generacion WHERE id_consulta = "
                                    "CAST(:c AS uuid) AND numero_intento = 2"), {"c": id_real}).scalar_one()
    _fragmentos(super_engine, id_intento, guia["docs"][0]["ids"][:3])
    _consulta(super_engine, auditadas, paciente, inicio="TIMESTAMPTZ '2001-03-20 15:15:00+00'", usuario="med.salazar",
              intentos=[_prueba()], latencia=6100)
    _consulta(super_engine, auditadas, paciente, inicio="TIMESTAMPTZ '2001-03-20 14:58:00+00'", usuario="nut.vilca",
              estado="FUERA_DE_DOMINIO", latencia=350)

    indicadores = _get(cliente, cabeceras, "/api/auditoria/indicadores").json()
    lista = _get(cliente, cabeceras, "/api/auditoria/consultas?fecha_desde=2001-03-20&fecha_hasta=2001-03-20"
                                     "&incluir_pruebas=true").json()
    detalle = _get(cliente, cabeceras, f"/api/auditoria/consultas/{id_real}").json()
    assert indicadores["consultas"] == 6 and lista["total"] == 3
    rutas.Indicadores.model_validate(indicadores)
    rutas.PaginaAuditoria.model_validate(lista)
    rutas.DetalleAuditoria.model_validate(detalle)
    for archivo, datos in (("auditoria_indicadores.json", indicadores), ("auditoria_consultas.json", lista),
                           ("auditoria_detalle.json", detalle)):
        texto = json.dumps(_normalizar(datos), ensure_ascii=False, indent=2) + "\n"
        for valor in (paciente["nombre"], paciente["dni"], paciente["hc"]):
            assert not _contiene(texto, valor), (archivo, valor)
        (DIR_FIXTURES / archivo).write_text(texto, encoding="utf-8", newline="\n")
