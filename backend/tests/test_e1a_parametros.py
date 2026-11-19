"""Parte E1a del Sprint 3: base de M12 (HU14). Migración 015 (historial cerrado, Hb sin traslape entre
categorías y permisos VER_PARAMETROS y CONFIGURAR_PARAMETROS), rutas de solo lectura, huella de la
configuración, modo de evaluación (423 en M11) y un solo lector de DIAS_VIGENCIA_TAMIZAJE.

Las pruebas que tocan la base lo hacen dentro de una transacción que se deshace, o cambian un valor con
la conexión de administración (propietaria, sin la restricción del trigger) y lo restauran en finally.
Ningún orden depende de la colación: se compara con claves explícitas en Python."""
import json
import re
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, ProgrammingError

from app.core.config import get_settings
from app.core.db import engines
from app.rag.parametros import ErrorParametro, leer_parametros
from app.services import parametros as srv
from app.services.pacientes import dias_vigencia

RAIZ = Path(__file__).resolve().parents[2]
MIGRACION_015 = RAIZ / "db" / "migraciones" / "015_parametros.sql"
RUTAS = ("/api/parametros", "/api/parametros/historial", "/api/parametros/huella")
TABLAS = ("configuracion.umbral_hemoglobina", "configuracion.ajuste_altitud", "configuracion.parametro_sistema")


def _get(cliente, cabeceras, ruta, usuario="coord.ortiz"):
    return cliente.get(ruta, headers=cabeceras(usuario))


def _como(super_engine, rol: str, sql: str, valores: dict | None = None, preparar: str | None = None):
    """Ejecuta la sentencia con el rol indicado, en una transacción que siempre se deshace."""
    with super_engine.connect() as c:
        try:
            if preparar:
                c.exec_driver_sql(preparar)
            c.execute(text(f"SET LOCAL ROLE {rol}"))
            return c.execute(text(sql), valores or {}).rowcount
        finally:
            c.rollback()


def _id_vigente(super_engine, tabla: str, columna: str) -> int:
    with super_engine.connect() as c:
        return c.execute(text(f"SELECT min({columna}) FROM {tabla} WHERE vigente_hasta IS NULL")).scalar_one()


def _id_cerrado(super_engine) -> int:
    """Un parámetro ya cerrado (la carga inicial cierra TEMPERATURA_LLM y los valores anteriores)."""
    with super_engine.connect() as c:
        return c.execute(text("SELECT min(id_parametro) FROM configuracion.parametro_sistema "
                              "WHERE vigente_hasta IS NOT NULL")).scalar_one()


# ---------------------------------------------------------------------------
# Migración 015
# ---------------------------------------------------------------------------
def _estado(c) -> dict:
    return {
        "columnas": sorted(c.execute(text(
            """SELECT table_name || '.' || column_name || ':' || data_type FROM information_schema.columns
                WHERE table_schema = 'configuracion'""")).scalars()),
        "restricciones": sorted(c.execute(text(
            "SELECT conname FROM pg_constraint WHERE connamespace = 'configuracion'::regnamespace")).scalars()),
        "triggers": sorted(c.execute(text(
            """SELECT tgname FROM pg_trigger WHERE NOT tgisinternal
                AND tgrelid::regclass::text LIKE 'configuracion.%'""")).scalars()),
        "permisos": sorted(c.execute(text(
            """SELECT table_name || ':' || privilege_type FROM information_schema.role_table_grants
                WHERE grantee = 'rol_app_admin' AND table_schema = 'configuracion'""")).scalars()),
        "rbac": sorted(c.execute(text(
            """SELECT r.nombre || ':' || p.codigo FROM seguridad.rol_permiso rp
                 JOIN seguridad.rol r USING (id_rol) JOIN seguridad.permiso p USING (id_permiso)
                WHERE p.codigo LIKE '%PARAMETROS'""")).scalars()),
    }


def test_migracion_015_se_aplica_dos_veces_sin_cambios(super_engine):
    sql = MIGRACION_015.read_text(encoding="utf-8")
    with super_engine.begin() as c:
        antes = _estado(c)
        cursor = c.connection.dbapi_connection.cursor()  # sin parámetros: los % de los RAISE quedan literales
        cursor.execute(sql)
        cursor.execute(sql)
        despues = _estado(c)
    assert antes == despues
    for tabla in ("umbral_hemoglobina", "ajuste_altitud", "parametro_sistema"):
        for col in ("motivo_cambio:character varying", "referencia:character varying", "verificado:boolean"):
            assert f"{tabla}.{col}" in despues["columnas"]
    assert "parametro_sistema.id_documento:uuid" in despues["columnas"]
    assert {"tg_umbral_solo_cierre", "tg_ajuste_solo_cierre", "tg_parametro_solo_cierre"} <= set(despues["triggers"])
    assert "ex_umbral_hb_sin_traslape" in despues["restricciones"]
    assert despues["rbac"] == ["Administrador:VER_PARAMETROS", "Coordinador CRED:CONFIGURAR_PARAMETROS",
                               "Coordinador CRED:VER_PARAMETROS"]


def test_las_filas_sembradas_quedan_pendientes_de_verificacion(super_engine):
    with super_engine.connect() as c:
        for tabla in ("configuracion.umbral_hemoglobina", "configuracion.ajuste_altitud"):
            assert c.execute(text(f"SELECT bool_or(verificado) FROM {tabla}")).scalar_one() is False, tabla


# ---------------------------------------------------------------------------
# Trigger: el historial solo se cierra
# ---------------------------------------------------------------------------
# Un rol que no es propietario pero sí tiene UPDATE en todas las columnas: prueba el trigger por sí
# solo, sin la barrera de los permisos (que se prueba aparte con cdss_admin).
PREPARAR_ROL = """
CREATE ROLE prueba_trigger_e1a NOLOGIN;
GRANT USAGE ON SCHEMA configuracion TO prueba_trigger_e1a;
GRANT SELECT, UPDATE ON configuracion.umbral_hemoglobina, configuracion.ajuste_altitud,
  configuracion.parametro_sistema TO prueba_trigger_e1a;
"""


@pytest.mark.parametrize("sql", [
    "UPDATE configuracion.umbral_hemoglobina SET hb_min_g_dl = hb_min_g_dl WHERE id_umbral = :vigente_u",
    "UPDATE configuracion.ajuste_altitud SET ajuste_g_dl = ajuste_g_dl + 0.1 WHERE id_ajuste = :vigente_a",
    "UPDATE configuracion.parametro_sistema SET valor = valor || '0' WHERE id_parametro = :vigente_p",
    "UPDATE configuracion.parametro_sistema SET verificado = true WHERE id_parametro = :vigente_p",
    "UPDATE configuracion.parametro_sistema SET vigente_hasta = now(), motivo_cambio = 'x' WHERE id_parametro = :vigente_p",
    "UPDATE configuracion.parametro_sistema SET vigente_hasta = now() WHERE id_parametro = :cerrado",
    "UPDATE configuracion.parametro_sistema SET vigente_hasta = NULL WHERE id_parametro = :cerrado",
    "UPDATE configuracion.parametro_sistema SET vigente_hasta = vigente_desde - interval '1 day' WHERE id_parametro = :vigente_p",
    "UPDATE configuracion.umbral_hemoglobina SET vigente_hasta = NULL WHERE id_umbral = :vigente_u",
])
def test_el_trigger_rechaza_editar_valores_y_reabrir_o_volver_a_cerrar(super_engine, sql):
    valores = {"vigente_u": _id_vigente(super_engine, TABLAS[0], "id_umbral"),
               "vigente_a": _id_vigente(super_engine, TABLAS[1], "id_ajuste"),
               "vigente_p": _id_vigente(super_engine, TABLAS[2], "id_parametro"), "cerrado": _id_cerrado(super_engine)}
    with pytest.raises(DBAPIError, match="historial de parámetros|solo se cierra"):
        _como(super_engine, "prueba_trigger_e1a", sql, valores, PREPARAR_ROL)


@pytest.mark.parametrize("tabla,columna", [(TABLAS[0], "id_umbral"), (TABLAS[1], "id_ajuste"), (TABLAS[2], "id_parametro")])
def test_el_trigger_permite_cerrar_una_version_vigente_con_fecha(super_engine, tabla, columna):
    ident = _id_vigente(super_engine, tabla, columna)
    filas = _como(super_engine, "prueba_trigger_e1a", f"UPDATE {tabla} SET vigente_hasta = now() WHERE {columna} = :i",
                  {"i": ident}, PREPARAR_ROL)
    assert filas == 1


def test_el_propietario_puede_corregir_el_historial(super_engine):
    """Migraciones, carga inicial y desmontaje de las pruebas: sin la restricción del trigger."""
    ident = _id_cerrado(super_engine)
    with super_engine.connect() as c:
        try:
            assert c.execute(text("UPDATE configuracion.parametro_sistema SET motivo_cambio = 'corrección', "
                                  "vigente_hasta = vigente_hasta + interval '1 second' WHERE id_parametro = :i"),
                             {"i": ident}).rowcount == 1
        finally:
            c.rollback()


# ---------------------------------------------------------------------------
# Permisos de rol_app_admin (cdss_admin)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("sql", [
    "UPDATE configuracion.parametro_sistema SET valor = valor WHERE false",
    "UPDATE configuracion.umbral_hemoglobina SET hb_min_g_dl = hb_min_g_dl WHERE false",
    "UPDATE configuracion.ajuste_altitud SET ajuste_g_dl = ajuste_g_dl WHERE false",
    "UPDATE configuracion.parametro_sistema SET motivo_cambio = 'x' WHERE false",
    "UPDATE configuracion.categoria_anemia SET nivel_riesgo = nivel_riesgo WHERE false",
    "INSERT INTO configuracion.categoria_anemia (nombre, nivel_riesgo, orden) VALUES ('X', 'BAJO', 99)",
    "DELETE FROM configuracion.parametro_sistema WHERE false",
])
def test_cdss_admin_no_edita_valores_ni_categorias(super_engine, sql):
    with pytest.raises(ProgrammingError, match="permission denied"):
        _como(super_engine, "cdss_admin", sql)


def test_cdss_admin_puede_cerrar_una_version_e_insertar_otra(super_engine):
    ident = _id_vigente(super_engine, TABLAS[2], "id_parametro")
    assert _como(super_engine, "cdss_admin", "UPDATE configuracion.parametro_sistema SET vigente_hasta = now() "
                 "WHERE id_parametro = :i", {"i": ident}) == 1
    assert _como(super_engine, "cdss_admin", """INSERT INTO configuracion.parametro_sistema
        (clave, valor, tipo_dato, descripcion, modificado_por, motivo_cambio)
        VALUES ('PRUEBA_E1A', '1', 'ENTERO', 'prueba', '00000000-0000-0000-0000-000000000001', 'prueba')""") == 1


# ---------------------------------------------------------------------------
# Hb sin traslape entre categorías
# ---------------------------------------------------------------------------
def _umbral(c, categoria: str, hb_min, hb_max, edad_min=0, edad_max=5):
    c.execute(text("""INSERT INTO configuracion.umbral_hemoglobina
                        (id_documento, id_categoria, edad_min_meses, edad_max_meses, hb_min_g_dl, hb_max_g_dl, modificado_por)
                      SELECT '10000000-0000-0000-0000-000000002024', id_categoria, :emin, :emax, :hmin, :hmax,
                             '00000000-0000-0000-0000-000000000001'
                        FROM configuracion.categoria_anemia WHERE nombre = :cat"""),
              {"cat": categoria, "hmin": hb_min, "hmax": hb_max, "emin": edad_min, "emax": edad_max})


def test_rangos_de_hb_de_categorias_distintas_no_se_superponen(super_engine):
    with super_engine.connect() as c:
        try:
            _umbral(c, "SIN_ANEMIA", 10.0, None)
            _umbral(c, "ANEMIA_LEVE", 9.0, 9.9)  # contiguo: se admite
            with pytest.raises(DBAPIError, match="ex_umbral_hb_sin_traslape"):
                _umbral(c, "ANEMIA_MODERADA", 7.0, 9.0)  # 9.0 ya es leve
        finally:
            c.rollback()


def test_el_traslape_tambien_cuenta_con_edades_que_se_superponen(super_engine):
    with super_engine.connect() as c:
        try:
            _umbral(c, "ANEMIA_SEVERA", None, 6.9, 0, 5)
            with pytest.raises(DBAPIError, match="ex_umbral_hb_sin_traslape"):
                _umbral(c, "ANEMIA_MODERADA", 6.5, 8.0, 3, 5)  # se superpone en edad (3 a 5) y en Hb (6.5 a 6.9)
        finally:
            c.rollback()


# ---------------------------------------------------------------------------
# Rutas: permisos
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("ruta", RUTAS)
def test_sin_sesion_responde_401(cliente, ruta):
    assert cliente.get(ruta).status_code == 401


@pytest.mark.parametrize("usuario", ["enf.rojas", "med.salazar", "nut.vilca"])
@pytest.mark.parametrize("ruta", RUTAS)
def test_roles_clinicos_reciben_403(cliente, cabeceras, ruta, usuario):
    r = _get(cliente, cabeceras, ruta, usuario)
    assert r.status_code == 403 and r.json()["detail"] == "Su rol no tiene el permiso VER_PARAMETROS"


@pytest.mark.parametrize("usuario,puede", [("coord.ortiz", True), ("admin.cdss", False)])
def test_coordinador_y_administrador_leen_y_solo_el_coordinador_puede_editar(cliente, cabeceras, usuario, puede):
    for ruta in RUTAS:
        assert _get(cliente, cabeceras, ruta, usuario).status_code == 200, ruta
    datos = _get(cliente, cabeceras, RUTAS[0], usuario).json()
    assert datos["puede_editar"] is puede and datos["modo_evaluacion"] is False
    me = cliente.get("/api/auth/me", headers=cabeceras(usuario)).json()
    assert ("CONFIGURAR_PARAMETROS" in me["permisos"]) is puede and "VER_PARAMETROS" in me["permisos"]


# ---------------------------------------------------------------------------
# GET /api/parametros
# ---------------------------------------------------------------------------
def test_grupos_editables_con_version_valores_y_estado_de_verificacion(cliente, cabeceras, super_engine):
    d = _get(cliente, cabeceras, RUTAS[0]).json()
    tramos = d["puntos_corte"]["tramos"]
    assert [(t["edad_min_meses"], t["edad_max_meses"]) for t in tramos] == [(6, 23), (24, 59)]
    for t in tramos:
        assert [c["categoria"] for c in t["categorias"]] == ["SIN_ANEMIA", "ANEMIA_LEVE", "ANEMIA_MODERADA", "ANEMIA_SEVERA"]
        assert all(c["verificado"] is False and c["documento"]["codigo"] for c in t["categorias"])
    rangos = d["ajuste_altitud"]["rangos"]
    assert rangos[0]["altitud_min_msnm"] == 0 and [r["altitud_min_msnm"] for r in rangos] == sorted(r["altitud_min_msnm"] for r in rangos)
    assert d["vigencia_tamizaje"]["clave"] == "DIAS_VIGENCIA_TAMIZAJE"
    # La versión de cada grupo es la huella de sus ids vigentes.
    with super_engine.connect() as c:
        ids = list(c.execute(text("SELECT id_umbral FROM configuracion.umbral_hemoglobina WHERE vigente_hasta IS NULL")).scalars())
    assert d["puntos_corte"]["version"] == srv.version_de("puntos_corte", ids)
    assert re.fullmatch(r"[0-9a-f]{64}", d["ajuste_altitud"]["version"])


def test_grupos_de_solo_lectura_sin_los_parametros_sin_uso(cliente, cabeceras):
    d = _get(cliente, cabeceras, RUTAS[0]).json()
    assert [r["nombre"] for r in d["riesgo"]] == ["SIN_ANEMIA", "ANEMIA_LEVE", "ANEMIA_MODERADA", "ANEMIA_SEVERA"]
    assert d["riesgo"][3]["requiere_derivacion"] is True
    claves = {p["clave"] for g in ("recuperacion", "modelo", "indexacion") for p in d[g]}
    assert not claves & srv.CLAVES_SIN_USO
    assert {p["clave"]: p["valor"] for p in d["recuperacion"]}["UMBRAL_RELEVANCIA"] == "0.15"
    assert "DIAS_VIGENCIA_TAMIZAJE" not in claves
    assert "REINTENTOS_MAXIMOS" not in json.dumps(d)


# ---------------------------------------------------------------------------
# Historial
# ---------------------------------------------------------------------------
def test_historial_pagina_con_orden_estable(cliente, cabeceras):
    completo = _get(cliente, cabeceras, "/api/parametros/historial?limite=100").json()
    total = completo["total"]
    paginas = [_get(cliente, cabeceras, f"/api/parametros/historial?limite=7&desplazamiento={n}").json()
               for n in range(0, total, 7)]
    assert all(p["total"] == total for p in paginas)
    por_paginas = [(v["tabla"], v["id"]) for p in paginas for v in p["versiones"]]
    assert len(por_paginas) == total and len(set(por_paginas)) == total
    repetido = [(v["tabla"], v["id"]) for p in paginas for v in p["versiones"]]
    assert por_paginas == repetido
    versiones = [v for p in paginas for v in p["versiones"]]
    from datetime import datetime
    clave = [(-datetime.fromisoformat(v["vigente_desde"]).timestamp(), srv.GRUPOS_HISTORIAL.index(v["grupo"]), -v["id"])
             for v in versiones]
    assert clave == sorted(clave)


def test_historial_de_un_grupo_trae_vigentes_y_cerradas(cliente, cabeceras, super_engine):
    d = _get(cliente, cabeceras, "/api/parametros/historial?grupo=recuperacion&limite=100").json()
    with super_engine.connect() as c:
        esperado = c.execute(text("SELECT count(*) FROM configuracion.parametro_sistema WHERE clave = ANY(:c)"),
                             {"c": srv.CLAVES_SOLO_LECTURA["recuperacion"]}).scalar_one()
    assert d["total"] == esperado and d["grupo"] == "recuperacion"
    umbrales = [v for v in d["versiones"] if v["elemento"] == "UMBRAL_RELEVANCIA"]
    assert {(v["valores"]["valor"], v["vigente"]) for v in umbrales} == {("0.60", False), ("0.15", True)}
    assert all(v["modificado_por"] for v in d["versiones"])


@pytest.mark.parametrize("consulta,campo", [("limite=101", "limite"), ("limite=0", "limite"),
                                            ("desplazamiento=-1", "desplazamiento"), ("grupo=riesgo", "grupo")])
def test_historial_rechaza_filtros_invalidos(cliente, cabeceras, consulta, campo):
    r = _get(cliente, cabeceras, f"/api/parametros/historial?{consulta}")
    assert r.status_code == 422 and [e["campo"] for e in r.json()["errores"]] == [campo]


# ---------------------------------------------------------------------------
# Huella
# ---------------------------------------------------------------------------
def test_la_huella_es_estable_entre_dos_llamadas(cliente, cabeceras):
    a = _get(cliente, cabeceras, RUTAS[2]).json()
    b = _get(cliente, cabeceras, RUTAS[2], "admin.cdss").json()
    assert a["huella"] == b["huella"] and re.fullmatch(r"[0-9a-f]{64}", a["huella"])
    assert [c["nombre"] for c in a["componentes"]] == ["puntos_corte", "ajuste_altitud", "categorias",
                                                      "parametros_sistema", "indexacion", "version_prompt"]
    assert a["version_prompt"] == "v1.1"


@pytest.mark.parametrize("tabla,columna,id_col,cambio,componente", [
    ("configuracion.umbral_hemoglobina", "hb_min_g_dl", "id_umbral", "hb_min_g_dl + 0.1", "puntos_corte"),
    ("configuracion.ajuste_altitud", "ajuste_g_dl", "id_ajuste", "ajuste_g_dl + 0.1", "ajuste_altitud"),
    ("configuracion.parametro_sistema", "valor", "id_parametro", "valor || '1'", "parametros_sistema"),
])
def test_la_huella_cambia_al_cambiar_un_valor_y_vuelve_al_restaurarlo(cliente, cabeceras, super_engine, tabla, columna,
                                                                     id_col, cambio, componente):
    antes = _get(cliente, cabeceras, RUTAS[2]).json()
    with super_engine.connect() as c:
        ident, original = c.execute(text(
            f"""SELECT {id_col}, {columna} FROM {tabla} WHERE vigente_hasta IS NULL AND {columna} IS NOT NULL
                 ORDER BY {id_col} DESC LIMIT 1""")).one()
    try:
        with super_engine.begin() as c:  # propietario: cambia el valor en el lugar solo para la prueba
            c.execute(text(f"UPDATE {tabla} SET {columna} = {cambio} WHERE {id_col} = :i"), {"i": ident})
        durante = _get(cliente, cabeceras, RUTAS[2]).json()
    finally:
        with super_engine.begin() as c:
            c.execute(text(f"UPDATE {tabla} SET {columna} = :v WHERE {id_col} = :i"), {"v": original, "i": ident})
    despues = _get(cliente, cabeceras, RUTAS[2]).json()
    assert durante["huella"] != antes["huella"]
    cambiados = [a["nombre"] for a, d in zip(antes["componentes"], durante["componentes"]) if a["huella"] != d["huella"]]
    assert cambiados == [componente]
    assert despues["huella"] == antes["huella"]


def test_el_script_imprime_la_misma_huella(cliente, cabeceras, capsys, monkeypatch):
    from app.scripts import huella_configuracion
    monkeypatch.setattr("sys.argv", ["huella_configuracion"])
    huella_configuracion.main()
    salida = capsys.readouterr().out
    assert _get(cliente, cabeceras, RUTAS[2]).json()["huella"] in salida


# ---------------------------------------------------------------------------
# Modo de evaluación
# ---------------------------------------------------------------------------
@pytest.fixture
def modo_evaluacion(monkeypatch):
    monkeypatch.setattr(get_settings(), "modo_evaluacion", True)


def _eventos_desde(super_engine, desde: int) -> list:
    with super_engine.connect() as c:
        return c.execute(text("""SELECT tipo_evento, id_entidad, detalle, id_usuario::text FROM auditoria.evento_auditoria
                                  WHERE id_evento > :d AND tipo_evento = 'PARAMETRO_CAMBIO_BLOQUEADO'
                                  ORDER BY id_evento"""), {"d": desde}).mappings().all()


def _ultimo_evento(super_engine) -> int:
    with super_engine.connect() as c:
        return c.execute(text("SELECT coalesce(max(id_evento), 0) FROM auditoria.evento_auditoria")).scalar_one()


def test_en_modo_de_evaluacion_las_escrituras_de_m11_responden_423(cliente, cabeceras, super_engine, modo_evaluacion):
    desde = _ultimo_evento(super_engine)
    with super_engine.connect() as c:
        documentos_antes = c.execute(text("SELECT count(*) FROM conocimiento.documento_fuente")).scalar_one()
    h = cabeceras("admin.cdss")
    carga = cliente.post("/api/conocimiento/documentos", headers=h,
                         files={"archivo": ("guia.pdf", b"%PDF-1.4 prueba", "application/pdf")},
                         data={"titulo": "Guía de prueba"})
    id_doc = str(uuid.uuid4())
    reintento = cliente.post(f"/api/conocimiento/documentos/{id_doc}/reintentar", headers=h)
    for r in (carga, reintento):
        assert r.status_code == 423
        assert r.json()["detail"].startswith("El sistema está en modo de evaluación")
    with super_engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM conocimiento.documento_fuente")).scalar_one() == documentos_antes
        admin = c.execute(text("SELECT id_usuario::text FROM seguridad.usuario WHERE nombre_usuario = 'admin.cdss'")).scalar_one()
    eventos = _eventos_desde(super_engine, desde)
    assert [(e["detalle"], e["id_entidad"], e["id_usuario"]) for e in eventos] == [
        ({"accion": "CARGAR_GUIA"}, None, admin), ({"accion": "REINTENTAR_INDEXACION"}, id_doc, admin)]
    assert _get(cliente, cabeceras, RUTAS[0]).json()["modo_evaluacion"] is True


def test_sin_modo_de_evaluacion_m11_no_responde_423(cliente, cabeceras):
    r = cliente.post(f"/api/conocimiento/documentos/{uuid.uuid4()}/reintentar", headers=cabeceras("admin.cdss"))
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Un solo lector de DIAS_VIGENCIA_TAMIZAJE
# ---------------------------------------------------------------------------
def test_los_dos_lectores_de_la_vigencia_dan_lo_mismo_y_fallan_igual(super_engine):
    with engines()["clinica"].connect() as c:
        assert dias_vigencia(c) == leer_parametros(c, ["DIAS_VIGENCIA_TAMIZAJE"])["DIAS_VIGENCIA_TAMIZAJE"]
    with super_engine.connect() as c:
        try:
            c.execute(text("UPDATE configuracion.parametro_sistema SET vigente_hasta = now() "
                           "WHERE clave = 'DIAS_VIGENCIA_TAMIZAJE' AND vigente_hasta IS NULL"))
            with pytest.raises(ErrorParametro, match="DIAS_VIGENCIA_TAMIZAJE"):
                dias_vigencia(c)
            with pytest.raises(ErrorParametro, match="DIAS_VIGENCIA_TAMIZAJE"):
                leer_parametros(c, ["DIAS_VIGENCIA_TAMIZAJE"])
        finally:
            c.rollback()


# ---------------------------------------------------------------------------
# Fixtures del frontend (parte E2)
# ---------------------------------------------------------------------------
DIR_FIXTURES = RAIZ / "frontend" / "src" / "__fixtures__"
_FECHA = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})")


def _normalizar(datos) -> object:
    """Fechas fijas para que el diff muestre solo cambios del contrato."""
    return json.loads(_FECHA.sub("2026-10-20T15:00:00Z", json.dumps(datos, ensure_ascii=False)))


def test_genera_los_fixtures_de_parametros_para_el_frontend(cliente, cabeceras):
    salidas = {
        "parametros.json": _get(cliente, cabeceras, RUTAS[0]).json(),
        "parametros_solo_lectura.json": _get(cliente, cabeceras, RUTAS[0], "admin.cdss").json(),
        "parametros_historial.json": _get(cliente, cabeceras, "/api/parametros/historial?grupo=recuperacion&limite=5").json(),
        "parametros_huella.json": _get(cliente, cabeceras, RUTAS[2]).json(),
    }
    for archivo, datos in salidas.items():
        (DIR_FIXTURES / archivo).write_text(json.dumps(_normalizar(datos), ensure_ascii=False, indent=2) + "\n",
                                            encoding="utf-8", newline="\n")
