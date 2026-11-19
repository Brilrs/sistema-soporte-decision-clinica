"""Sprint 3, parte I: cambio obligatorio de contraseña y sesiones invalidadas (contador version_sesion).

Las pruebas usan solo cuentas sintéticas (prefijo prueba.i), creadas por la API o, para el seed, con
crear_usuarios y una lista propia. Las cuentas de la demostración no se tocan. Al terminar, las cuentas
sin eventos se eliminan y las que tienen eventos quedan desactivadas (la bitácora es inmutable)."""
import re
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
import pytest
from fastapi.routing import APIRoute
from sqlalchemy import create_engine, text
from sqlalchemy.exc import ProgrammingError

from app.core.config import get_settings
from app.main import app
from app.scripts import seed_demo

RAIZ = Path(__file__).resolve().parents[2]
MIGRACION_018 = RAIZ / "db" / "migraciones" / "018_cambio_contrasena.sql"
ADMIN = "admin.cdss"
DEMO = ["admin.cdss", "enf.rojas", "med.salazar", "nut.vilca", "coord.ortiz"]
NUEVA = "ClaveNueva2026x"
ID_FALSO = "00000000-0000-4000-8000-000000000000"

# Rutas que responden aunque la marca de cambio obligatorio esté activa
PERMITIDAS = {("GET", "/api/auth/me"), ("POST", "/api/auth/cambiar-contrasena"), ("POST", "/api/auth/login"),
              ("GET", "/api/salud")}


# ---------------------------------------------------------------------------
# Ayudantes
# ---------------------------------------------------------------------------
@pytest.fixture
def cuentas(super_engine):
    """Ids de las cuentas sintéticas que crea cada prueba; se limpian al final."""
    ids: list[str] = []
    yield ids
    with super_engine.begin() as c:
        for id_usuario in ids:
            con_eventos = c.execute(text("SELECT 1 FROM auditoria.evento_auditoria WHERE id_usuario = CAST(:id AS uuid)"
                                         " OR (entidad = 'usuario' AND id_entidad = :texto) LIMIT 1"),
                                    {"id": id_usuario, "texto": id_usuario}).first()
            if con_eventos:
                c.execute(text("""UPDATE seguridad.usuario SET activo = false, fecha_desactivacion = now()
                                   WHERE id_usuario = CAST(:id AS uuid)"""), {"id": id_usuario})
            else:
                c.execute(text("DELETE FROM seguridad.usuario WHERE id_usuario = CAST(:id AS uuid)"), {"id": id_usuario})


@pytest.fixture(scope="module")
def roles(super_engine) -> dict[str, int]:
    with super_engine.connect() as c:
        return dict(c.execute(text("SELECT nombre, id_rol FROM seguridad.rol")).all())


def _crear(cliente, cabeceras, cuentas, id_rol: int) -> tuple[dict, str]:
    nombre = f"prueba.i{secrets.token_hex(4)}"
    r = cliente.post("/api/usuarios", headers=cabeceras(ADMIN),
                     json={"nombre_completo": "Lic. Cuenta Sintética", "nombre_usuario": nombre, "id_rol": id_rol})
    assert r.status_code == 201, r.text
    cuerpo = r.json()
    cuentas.append(cuerpo["usuario"]["id_usuario"])
    return cuerpo["usuario"], cuerpo["contrasena_temporal"]


def _login(cliente, usuario: str, contrasena: str):
    return cliente.post("/api/auth/login", json={"usuario": usuario, "contrasena": contrasena})


def _h(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _cambiar(cliente, token: str, actual: str, nueva: str):
    return cliente.post("/api/auth/cambiar-contrasena", headers=_h(token),
                        json={"contrasena_actual": actual, "contrasena_nueva": nueva})


def _cuenta(super_engine, id_usuario: str) -> dict:
    with super_engine.connect() as c:
        return dict(c.execute(text(
            """SELECT debe_cambiar_contrasena, version_sesion, fecha_cambio_contrasena, intentos_fallidos, hash_contrasena
                 FROM seguridad.usuario WHERE id_usuario = CAST(:id AS uuid)"""), {"id": id_usuario}).mappings().one())


def _eventos(super_engine, id_usuario: str) -> list[dict]:
    with super_engine.connect() as c:
        return [dict(f) for f in c.execute(text(
            """SELECT tipo_evento, detalle::text AS detalle FROM auditoria.evento_auditoria
                WHERE entidad = 'usuario' AND id_entidad = :id ORDER BY id_evento"""), {"id": id_usuario}).mappings()]


def _con_sesion_cambiada(cliente, cabeceras, cuentas, roles) -> tuple[dict, str, str]:
    """Cuenta nueva que ya cambió la contraseña temporal: devuelve (usuario, contraseña, token)."""
    u, temporal = _crear(cliente, cabeceras, cuentas, roles["Enfermera CRED"])
    token = _login(cliente, u["nombre_usuario"], temporal).json()["token"]
    r = _cambiar(cliente, token, temporal, NUEVA)
    assert r.status_code == 200, r.text
    return u, NUEVA, r.json()["token"]


def _assert_revocado(r) -> None:
    assert r.status_code == 401, r.text
    assert r.json() == {"detail": "Sesión no válida o expirada", "codigo": "SESION_REVOCADA"}
    assert r.headers["x-codigo-error"] == "SESION_REVOCADA"


# ---------------------------------------------------------------------------
# Inicio de sesión y /me
# ---------------------------------------------------------------------------
def test_login_y_me_informan_la_marca_y_la_politica(cliente, cabeceras, cuentas, roles):
    minimo = get_settings().contrasena_longitud_minima
    me = cliente.get("/api/auth/me", headers=cabeceras("enf.rojas")).json()
    assert me["debe_cambiar_contrasena"] is False and me["contrasena_longitud_minima"] == minimo

    u, temporal = _crear(cliente, cabeceras, cuentas, roles["Médico"])
    r = _login(cliente, u["nombre_usuario"], temporal)
    assert r.status_code == 200
    datos = r.json()
    assert datos["usuario"]["debe_cambiar_contrasena"] is True
    assert datos["usuario"]["contrasena_longitud_minima"] == minimo
    me = cliente.get("/api/auth/me", headers=_h(datos["token"]))
    assert me.status_code == 200 and me.json()["debe_cambiar_contrasena"] is True


def test_las_cuentas_de_la_demostracion_no_tienen_la_marca(super_engine):
    with super_engine.connect() as c:
        marcas = dict(c.execute(text("SELECT nombre_usuario, debe_cambiar_contrasena FROM seguridad.usuario"
                                     " WHERE nombre_usuario = ANY(:u)"), {"u": DEMO}).all())
    assert marcas == {u: False for u in DEMO}


# ---------------------------------------------------------------------------
# Cambio de contraseña
# ---------------------------------------------------------------------------
def test_cambio_correcto(cliente, cabeceras, cuentas, roles, super_engine):
    u, temporal = _crear(cliente, cabeceras, cuentas, roles["Nutricionista"])
    token_a = _login(cliente, u["nombre_usuario"], temporal).json()["token"]
    token_b = _login(cliente, u["nombre_usuario"], temporal).json()["token"]  # otro dispositivo
    antes = _cuenta(super_engine, u["id_usuario"])
    assert antes["debe_cambiar_contrasena"] and antes["fecha_cambio_contrasena"] is None

    r = _cambiar(cliente, token_a, temporal, NUEVA)
    assert r.status_code == 200, r.text
    assert r.headers["cache-control"] == "no-store"
    datos = r.json()
    assert datos["usuario"]["debe_cambiar_contrasena"] is False and datos["usuario"]["nombre_usuario"] == u["nombre_usuario"]
    assert "contrasena_actual" not in r.text and NUEVA not in r.text

    despues = _cuenta(super_engine, u["id_usuario"])
    assert despues["version_sesion"] == antes["version_sesion"] + 1
    assert not despues["debe_cambiar_contrasena"] and despues["intentos_fallidos"] == 0
    assert despues["fecha_cambio_contrasena"] is not None
    assert despues["hash_contrasena"].startswith("$argon2id$") and despues["hash_contrasena"] != antes["hash_contrasena"]
    assert jwt.decode(datos["token"], options={"verify_signature": False})["sv"] == despues["version_sesion"]

    # Las dos sesiones anteriores quedan inválidas; el token nuevo sirve, también fuera de /api/auth
    _assert_revocado(cliente.get("/api/auth/me", headers=_h(token_a)))
    _assert_revocado(cliente.get("/api/consultas", headers=_h(token_b)))
    assert cliente.get("/api/auth/me", headers=_h(datos["token"])).status_code == 200
    assert cliente.get("/api/consultas", headers=_h(datos["token"])).status_code == 200

    assert _login(cliente, u["nombre_usuario"], temporal).status_code == 401
    assert _login(cliente, u["nombre_usuario"], NUEVA).status_code == 200


def test_cambio_voluntario_sin_marca(cliente, cabeceras, cuentas, roles, super_engine):
    u, actual, token = _con_sesion_cambiada(cliente, cabeceras, cuentas, roles)
    version = _cuenta(super_engine, u["id_usuario"])["version_sesion"]
    r = _cambiar(cliente, token, actual, "OtraClave2027y")
    assert r.status_code == 200, r.text
    assert _cuenta(super_engine, u["id_usuario"])["version_sesion"] == version + 1
    _assert_revocado(cliente.get("/api/auth/me", headers=_h(token)))
    eventos = [e for e in _eventos(super_engine, u["id_usuario"]) if e["tipo_evento"] == "CONTRASENA_CAMBIADA"]
    assert ['"obligatorio": true' in e["detalle"] for e in eventos] == [True, False]


def test_contrasena_actual_equivocada_cuenta_el_intento_y_bloquea(cliente, cabeceras, cuentas, roles, super_engine):
    u, temporal = _crear(cliente, cabeceras, cuentas, roles["Médico"])
    token = _login(cliente, u["nombre_usuario"], temporal).json()["token"]
    maximo = get_settings().max_intentos_fallidos
    version = _cuenta(super_engine, u["id_usuario"])["version_sesion"]

    for intento in range(1, maximo + 1):
        r = _cambiar(cliente, token, "Equivocada123", NUEVA)
        assert r.status_code == 401, r.text
        assert r.json() == {"detail": "La contraseña actual no es correcta.", "codigo": "CONTRASENA_ACTUAL_INCORRECTA",
                            "campo": "contrasena_actual"}
        assert _cuenta(super_engine, u["id_usuario"])["intentos_fallidos"] == intento

    # A partir del máximo: 423 en el cambio (aun con la contraseña correcta) y en el inicio de sesión
    r = _cambiar(cliente, token, temporal, NUEVA)
    assert r.status_code == 423 and r.json()["codigo"] == "CUENTA_BLOQUEADA"
    assert _login(cliente, u["nombre_usuario"], temporal).status_code == 423
    cuenta = _cuenta(super_engine, u["id_usuario"])
    assert cuenta["version_sesion"] == version and cuenta["debe_cambiar_contrasena"]

    fallidos = [e for e in _eventos(super_engine, u["id_usuario"]) if e["tipo_evento"] == "CAMBIO_CONTRASENA_FALLIDO"]
    assert len(fallidos) == maximo + 1
    assert all("Equivocada123" not in e["detalle"] and NUEVA not in e["detalle"] for e in fallidos)

    # Restablecer sigue desbloqueando la cuenta
    r = cliente.post(f"/api/usuarios/{u['id_usuario']}/restablecer-contrasena", headers=cabeceras(ADMIN))
    assert r.status_code == 200 and r.json()["usuario"]["estado"] == "ACTIVO"
    assert _login(cliente, u["nombre_usuario"], r.json()["contrasena_temporal"]).status_code == 200


@pytest.mark.parametrize("nueva, codigo", [
    ("Corta12", "POLITICA_CONTRASENA"),
    ("sinnumerosaqui", "POLITICA_CONTRASENA"),
    ("12345678901", "POLITICA_CONTRASENA"),
    (None, "CONTRASENA_IGUAL"),
])
def test_politica_e_igual_a_la_actual(cliente, cabeceras, cuentas, roles, super_engine, nueva, codigo):
    u, temporal = _crear(cliente, cabeceras, cuentas, roles["Enfermera CRED"])
    token = _login(cliente, u["nombre_usuario"], temporal).json()["token"]
    antes = _cuenta(super_engine, u["id_usuario"])
    r = _cambiar(cliente, token, temporal, temporal if nueva is None else nueva)
    assert r.status_code == 422, r.text
    assert r.json()["codigo"] == codigo and r.json()["campo"] == "contrasena_nueva"
    if codigo == "POLITICA_CONTRASENA":
        assert f"mínimo {get_settings().contrasena_longitud_minima} caracteres" in r.json()["detail"]
    else:
        assert r.json()["detail"] == "La nueva contraseña debe ser distinta de la actual."
    assert _cuenta(super_engine, u["id_usuario"]) == antes  # nada cambió (ni los intentos)
    assert cliente.get("/api/auth/me", headers=_h(token)).status_code == 200


def test_longitudes_maximas_y_campos_obligatorios(cliente, cabeceras, cuentas, roles):
    u, temporal = _crear(cliente, cabeceras, cuentas, roles["Enfermera CRED"])
    token = _login(cliente, u["nombre_usuario"], temporal).json()["token"]
    assert _cambiar(cliente, token, temporal, "A1" * 100 + "x").status_code == 422
    assert _cambiar(cliente, token, "x" * 201, NUEVA).status_code == 422
    r = cliente.post("/api/auth/cambiar-contrasena", headers=_h(token), json={"contrasena_nueva": NUEVA})
    assert r.status_code == 422
    assert cliente.post("/api/auth/cambiar-contrasena",
                        json={"contrasena_actual": temporal, "contrasena_nueva": NUEVA}).status_code == 401


def test_evento_sin_contrasenas(cliente, cabeceras, cuentas, roles, super_engine):
    u, temporal = _crear(cliente, cabeceras, cuentas, roles["Enfermera CRED"])
    token = _login(cliente, u["nombre_usuario"], temporal).json()["token"]
    hash_anterior = _cuenta(super_engine, u["id_usuario"])["hash_contrasena"]
    assert _cambiar(cliente, token, temporal, NUEVA).status_code == 200
    hash_nuevo = _cuenta(super_engine, u["id_usuario"])["hash_contrasena"]
    eventos = _eventos(super_engine, u["id_usuario"])
    cambio = [e for e in eventos if e["tipo_evento"] == "CONTRASENA_CAMBIADA"]
    assert len(cambio) == 1 and cambio[0]["detalle"] == '{"obligatorio": true}'
    for e in eventos:
        for secreto in (temporal, NUEVA, hash_anterior, hash_nuevo):
            assert secreto not in (e["detalle"] or "")


# ---------------------------------------------------------------------------
# Versión de sesión: restablecer, reactivar y tokens sin sv
# ---------------------------------------------------------------------------
def test_restablecer_invalida_las_sesiones_y_vuelve_a_poner_la_marca(cliente, cabeceras, cuentas, roles, super_engine):
    u, actual, token_a = _con_sesion_cambiada(cliente, cabeceras, cuentas, roles)
    token_b = _login(cliente, u["nombre_usuario"], actual).json()["token"]
    version = _cuenta(super_engine, u["id_usuario"])["version_sesion"]

    r = cliente.post(f"/api/usuarios/{u['id_usuario']}/restablecer-contrasena", headers=cabeceras(ADMIN))
    assert r.status_code == 200
    assert r.json()["usuario"]["debe_cambiar_contrasena"] is True
    cuenta = _cuenta(super_engine, u["id_usuario"])
    assert cuenta["version_sesion"] == version + 1 and cuenta["debe_cambiar_contrasena"]
    for token in (token_a, token_b):
        _assert_revocado(cliente.get("/api/auth/me", headers=_h(token)))

    nuevo = _login(cliente, u["nombre_usuario"], r.json()["contrasena_temporal"]).json()
    assert nuevo["usuario"]["debe_cambiar_contrasena"] is True
    assert cliente.get("/api/consultas", headers=_h(nuevo["token"])).json()["codigo"] == "CAMBIO_CONTRASENA_OBLIGATORIO"


def test_reactivar_invalida_los_tokens_anteriores(cliente, cabeceras, cuentas, roles, super_engine):
    u, actual, token = _con_sesion_cambiada(cliente, cabeceras, cuentas, roles)
    h = cabeceras(ADMIN)
    version = _cuenta(super_engine, u["id_usuario"])["version_sesion"]
    assert cliente.post(f"/api/usuarios/{u['id_usuario']}/desactivar", headers=h).status_code == 200
    assert cliente.get("/api/auth/me", headers=_h(token)).status_code == 401
    assert cliente.post(f"/api/usuarios/{u['id_usuario']}/reactivar", headers=h).status_code == 200
    assert _cuenta(super_engine, u["id_usuario"])["version_sesion"] == version + 1
    _assert_revocado(cliente.get("/api/auth/me", headers=_h(token)))
    nuevo = _login(cliente, u["nombre_usuario"], actual)
    assert nuevo.status_code == 200 and nuevo.json()["usuario"]["debe_cambiar_contrasena"] is False
    assert cliente.get("/api/auth/me", headers=_h(nuevo.json()["token"])).status_code == 200


def _token_manual(id_usuario: str, rol: str, **extra) -> str:
    ahora = datetime.now(timezone.utc)
    datos = {"sub": id_usuario, "rol": rol, "iat": ahora, "exp": ahora + timedelta(minutes=5), **extra}
    return jwt.encode(datos, get_settings().jwt_secreto, algorithm="HS256")


def test_token_sin_sv_vale_como_version_cero(cliente, cabeceras, cuentas, roles, super_engine):
    u, temporal = _crear(cliente, cabeceras, cuentas, roles["Enfermera CRED"])
    with super_engine.begin() as c:  # cuenta como las existentes antes de la migración 018
        c.execute(text("UPDATE seguridad.usuario SET debe_cambiar_contrasena = false WHERE id_usuario = CAST(:id AS uuid)"),
                  {"id": u["id_usuario"]})
    assert _cuenta(super_engine, u["id_usuario"])["version_sesion"] == 0
    sin_sv = _token_manual(u["id_usuario"], u["rol"])
    assert cliente.get("/api/auth/me", headers=_h(sin_sv)).status_code == 200
    assert cliente.get("/api/consultas", headers=_h(sin_sv)).status_code == 200
    # Valores que no son la versión exacta no valen
    for sv in (1, "0", None, 0.0, True):
        _assert_revocado(cliente.get("/api/auth/me", headers=_h(_token_manual(u["id_usuario"], u["rol"], sv=sv))))

    with super_engine.begin() as c:
        c.execute(text("UPDATE seguridad.usuario SET version_sesion = 1 WHERE id_usuario = CAST(:id AS uuid)"),
                  {"id": u["id_usuario"]})
    _assert_revocado(cliente.get("/api/auth/me", headers=_h(sin_sv)))
    assert cliente.get("/api/auth/me", headers=_h(_token_manual(u["id_usuario"], u["rol"], sv=1))).status_code == 200


def test_crear_y_restablecer_dejan_la_marca_en_la_lista(cliente, cabeceras, cuentas, roles):
    u, _ = _crear(cliente, cabeceras, cuentas, roles["Médico"])
    assert u["debe_cambiar_contrasena"] is True
    lista = {x["id_usuario"]: x for x in cliente.get("/api/usuarios", headers=cabeceras(ADMIN)).json()}
    assert lista[u["id_usuario"]]["debe_cambiar_contrasena"] is True
    assert all(x["debe_cambiar_contrasena"] is False for x in lista.values() if x["nombre_usuario"] in DEMO)
    assert all(not ({"hash_contrasena", "version_sesion"} & set(x)) for x in lista.values())


# ---------------------------------------------------------------------------
# Marca activa: todas las rutas responden 403 salvo las permitidas
# ---------------------------------------------------------------------------
def _rutas_api(rutas) -> list[APIRoute]:
    """APIRoute de la aplicación, también dentro de los routers incluidos (FastAPI reciente los agrupa)."""
    salida: list[APIRoute] = []
    for r in rutas:
        if isinstance(r, APIRoute):
            salida.append(r)
        elif hasattr(r, "original_router"):
            salida.extend(_rutas_api(r.original_router.routes))
        elif hasattr(r, "routes"):
            salida.extend(_rutas_api(r.routes))
    return salida


def test_con_la_marca_todas_las_rutas_responden_403_salvo_las_permitidas(cliente, cabeceras, cuentas, roles):
    u, temporal = _crear(cliente, cabeceras, cuentas, roles["Administrador"])
    token = _login(cliente, u["nombre_usuario"], temporal).json()["token"]

    rutas = _rutas_api(app.routes)
    pares = {(m, r.path) for r in rutas for m in r.methods if m != "HEAD"}
    # El recorrido encontró todas las rutas publicadas en el OpenAPI
    publicadas = {(m.upper(), p) for p, ops in app.openapi()["paths"].items() for m in ops}
    assert publicadas <= pares and len(pares) > 40
    assert PERMITIDAS <= pares

    sin_bloqueo = set()
    for metodo, ruta in sorted(pares):
        url = re.sub(r"\{[^}]+\}", ID_FALSO, ruta)
        r = cliente.request(metodo, url, headers=_h(token))
        if r.status_code == 403 and r.json().get("codigo") == "CAMBIO_CONTRASENA_OBLIGATORIO":
            assert r.json()["detail"] == "Debe cambiar su contraseña antes de continuar."
            continue
        sin_bloqueo.add((metodo, ruta))
    assert sin_bloqueo == PERMITIDAS, "Rutas sin el bloqueo de la marca: " + str(sorted(sin_bloqueo - PERMITIDAS))


# ---------------------------------------------------------------------------
# Seed
# ---------------------------------------------------------------------------
def _marcas(super_engine, nombres: list[str]) -> dict[str, bool]:
    with super_engine.connect() as c:
        return dict(c.execute(text("SELECT nombre_usuario, debe_cambiar_contrasena FROM seguridad.usuario"
                                   " WHERE nombre_usuario = ANY(:u)"), {"u": nombres}).all())


def test_seed_con_y_sin_la_opcion(super_engine, cuentas, monkeypatch):
    sufijo = secrets.token_hex(3)
    sin = [(f"prueba.iseed{sufijo}a", "Cuenta Seed A", "Médico", None)]
    con = [(f"prueba.iseed{sufijo}b", "Cuenta Seed B", "Médico", None)]
    nombres = [sin[0][0], con[0][0]]

    cuentas.extend(seed_demo.crear_usuarios("Cdss2026!", False, sin).values())
    cuentas.extend(seed_demo.crear_usuarios("Cdss2026!", True, con).values())
    assert _marcas(super_engine, nombres) == {nombres[0]: False, nombres[1]: True}

    # Idempotente: sin la opción no quita una marca puesta; con la opción la pone a una cuenta existente
    seed_demo.crear_usuarios("Cdss2026!", False, sin + con)
    assert _marcas(super_engine, nombres) == {nombres[0]: False, nombres[1]: True}
    seed_demo.crear_usuarios("Cdss2026!", True, sin)
    assert _marcas(super_engine, nombres) == {nombres[0]: True, nombres[1]: True}

    monkeypatch.delenv("CDSS_SEED_EXIGIR_CAMBIO", raising=False)
    assert seed_demo.exigir_cambio_desde_entorno() is False
    for valor, esperado in (("false", False), ("", False), ("0", False), ("true", True), ("TRUE", True), ("1", True)):
        monkeypatch.setenv("CDSS_SEED_EXIGIR_CAMBIO", valor)
        assert seed_demo.exigir_cambio_desde_entorno() is esperado


def test_compose_pasa_la_opcion_apagada_por_omision():
    compose = (RAIZ / "docker-compose.yml").read_text(encoding="utf-8")
    assert "CDSS_SEED_EXIGIR_CAMBIO: ${CDSS_SEED_EXIGIR_CAMBIO:-false}" in compose


# ---------------------------------------------------------------------------
# Permisos de columna y migración
# ---------------------------------------------------------------------------
def _privilegios(c, rol: str) -> dict[str, set[str]]:
    filas = c.execute(text(
        """SELECT privilege_type, column_name FROM information_schema.column_privileges
            WHERE table_schema = 'seguridad' AND table_name = 'usuario' AND grantee = :r"""), {"r": rol}).all()
    salida: dict[str, set[str]] = {}
    for tipo, columna in filas:
        salida.setdefault(tipo, set()).add(columna)
    return salida


NUEVAS = {"debe_cambiar_contrasena", "version_sesion", "fecha_cambio_contrasena"}
UPDATE_CLINICA = {"intentos_fallidos", "ultimo_acceso", "hash_contrasena"} | NUEVAS


def test_permisos_de_columna(super_engine):
    with super_engine.connect() as c:
        clinica = _privilegios(c, "rol_app_clinica")
        assert clinica["UPDATE"] == UPDATE_CLINICA
        assert set(clinica) == {"SELECT", "UPDATE"} and NUEVAS <= clinica["SELECT"]
        assert NUEVAS <= _privilegios(c, "rol_app_admin")["UPDATE"]
        for rol in ("rol_auditor", "rol_app_generacion", "rol_app_indexador"):
            assert _privilegios(c, rol) == {}, rol
        for rol in ("rol_auditor", "rol_app_generacion", "rol_app_indexador", "PUBLIC"):
            assert not c.execute(text("""SELECT 1 FROM information_schema.table_privileges
                                          WHERE table_schema = 'seguridad' AND table_name = 'usuario'
                                            AND grantee = :r"""), {"r": rol}).first(), rol


def _rechaza(url: str, sql: str) -> None:
    motor = create_engine(url)
    try:
        with motor.connect() as c:
            with pytest.raises(ProgrammingError, match="permission denied"):
                c.execute(text(sql))
            c.rollback()
    finally:
        motor.dispose()


def test_conexiones_reales_respetan_los_permisos():
    s = get_settings()
    # cdss_clinica no puede cambiar otros datos de la cuenta
    for columna in ("nombre_completo", "activo", "id_rol", "correo_institucional"):
        _rechaza(s.database_url_clinica, f"UPDATE seguridad.usuario SET {columna} = {columna} WHERE false")
    # El auditor no ve el hash, la marca ni la versión de sesión
    for columna in ("hash_contrasena", "debe_cambiar_contrasena", "version_sesion", "fecha_cambio_contrasena"):
        _rechaza(s.database_url_auditor, f"SELECT {columna} FROM seguridad.usuario LIMIT 1")
    _rechaza(s.database_url_generacion, "SELECT version_sesion FROM seguridad.usuario LIMIT 1")
    # Las columnas permitidas sí se actualizan (sin filas afectadas)
    motor = create_engine(s.database_url_clinica)
    try:
        with motor.connect() as c:
            c.execute(text("""UPDATE seguridad.usuario SET hash_contrasena = hash_contrasena,
                                     debe_cambiar_contrasena = debe_cambiar_contrasena, version_sesion = version_sesion,
                                     fecha_cambio_contrasena = fecha_cambio_contrasena WHERE false"""))
            c.rollback()
    finally:
        motor.dispose()


def _estado_018(c) -> dict:
    return {
        "columnas": sorted(c.execute(text(
            """SELECT column_name || ':' || data_type || ':' || is_nullable || ':' || coalesce(column_default, '')
                 FROM information_schema.columns
                WHERE table_schema = 'seguridad' AND table_name = 'usuario'""")).scalars()),
        "restricciones": sorted(c.execute(text(
            "SELECT conname FROM pg_constraint WHERE conrelid = 'seguridad.usuario'::regclass")).scalars()),
        "clinica": {k: sorted(v) for k, v in _privilegios(c, "rol_app_clinica").items()},
        "auditor": _privilegios(c, "rol_auditor"),
    }


def test_migracion_018_se_aplica_dos_veces_sin_cambios(super_engine):
    sql = MIGRACION_018.read_text(encoding="utf-8")
    with super_engine.begin() as c:
        antes = _estado_018(c)
        cursor = c.connection.dbapi_connection.cursor()
        cursor.execute(sql)
        cursor.execute(sql)
        despues = _estado_018(c)
    assert antes == despues
    assert {"debe_cambiar_contrasena:boolean:NO:false", "version_sesion:integer:NO:0",
            "fecha_cambio_contrasena:timestamp with time zone:YES:"} <= set(despues["columnas"])
    assert "ck_usuario_version_sesion" in despues["restricciones"]
    assert set(despues["clinica"]["UPDATE"]) == UPDATE_CLINICA and despues["auditor"] == {}
