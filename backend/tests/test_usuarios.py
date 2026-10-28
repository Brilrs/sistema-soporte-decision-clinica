"""HU11 · Gestionar usuarios (M10): permisos, reglas de las cuentas y auditoría.

Las pruebas crean sus propias cuentas (prefijo prueba.) y no modifican las del seed.
Al terminar se eliminan; si una cuenta ya tiene eventos de auditoría propios (por
ejemplo, un inicio de sesión), no se puede eliminar porque la bitácora es inmutable
y se deja desactivada."""
import secrets

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.seguridad import cumple_politica, generar_contrasena
from app.services import usuarios as srv

ROLES_SIN_PERMISO = ["enf.rojas", "med.salazar", "nut.vilca", "coord.ortiz"]
ADMIN = "admin.cdss"


@pytest.fixture
def usuarios_creados(super_engine):
    ids: list[str] = []
    yield ids
    for id_usuario in ids:
        with super_engine.begin() as c:
            tiene_eventos = c.execute(text("SELECT 1 FROM auditoria.evento_auditoria WHERE id_usuario = CAST(:id AS uuid)"),
                                      {"id": id_usuario}).first()
            if tiene_eventos:
                c.execute(text("""UPDATE seguridad.usuario SET activo = false, fecha_desactivacion = now()
                                   WHERE id_usuario = CAST(:id AS uuid)"""), {"id": id_usuario})
            else:
                c.execute(text("DELETE FROM seguridad.usuario WHERE id_usuario = CAST(:id AS uuid)"), {"id": id_usuario})


@pytest.fixture(scope="module")
def roles(super_engine) -> dict[str, int]:
    with super_engine.connect() as c:
        return dict(c.execute(text("SELECT nombre, id_rol FROM seguridad.rol")).all())


def _nombre_usuario() -> str:
    return f"prueba.{secrets.token_hex(4)}"


def _crear(cliente, cabeceras, usuarios_creados, id_rol: int, **cambios) -> dict:
    datos = {"nombre_completo": "Lic. Usuario de Prueba", "nombre_usuario": _nombre_usuario(), "id_rol": id_rol}
    datos.update(cambios)
    r = cliente.post("/api/usuarios", json=datos, headers=cabeceras(ADMIN))
    assert r.status_code == 201, r.text
    cuerpo = r.json()
    usuarios_creados.append(cuerpo["usuario"]["id_usuario"])
    return cuerpo


def _login(cliente, usuario: str, contrasena: str):
    return cliente.post("/api/auth/login", json={"usuario": usuario, "contrasena": contrasena})


def _id_de(super_engine, nombre_usuario: str) -> str:
    with super_engine.connect() as c:
        return c.execute(text("SELECT id_usuario::text FROM seguridad.usuario WHERE nombre_usuario = :u"),
                         {"u": nombre_usuario}).scalar_one()


def _eventos(super_engine, id_entidad: str) -> list[dict]:
    """Eventos de gestión de la cuenta (sin los inicios de sesión, que también usan la entidad usuario)."""
    with super_engine.connect() as c:
        return [dict(f) for f in c.execute(text(
            """SELECT tipo_evento, id_usuario::text AS id_usuario, detalle::text AS detalle
                 FROM auditoria.evento_auditoria
                WHERE entidad = 'usuario' AND id_entidad = :id AND tipo_evento NOT LIKE 'INICIO_SESION%'
                ORDER BY id_evento"""), {"id": id_entidad}).mappings()]


# ---------------------------------------------------------------------------
# Control de acceso
# ---------------------------------------------------------------------------
def test_sin_sesion_responde_401(cliente):
    assert cliente.get("/api/usuarios").status_code == 401
    assert cliente.post("/api/usuarios", json={}).status_code == 401


@pytest.mark.parametrize("usuario", ROLES_SIN_PERMISO)
def test_roles_sin_permiso_de_administracion_reciben_403(cliente, cabeceras, roles, usuario):
    h = cabeceras(usuario)
    id_admin = cliente.get("/api/auth/me", headers=cabeceras(ADMIN)).json()["id_usuario"]
    assert cliente.get("/api/usuarios", headers=h).status_code == 403
    assert cliente.get("/api/usuarios/roles", headers=h).status_code == 403
    nuevo = {"nombre_completo": "Intruso", "nombre_usuario": _nombre_usuario(), "id_rol": roles["Administrador"]}
    assert cliente.post("/api/usuarios", json=nuevo, headers=h).status_code == 403
    assert cliente.patch(f"/api/usuarios/{id_admin}", json={"nombre_completo": "Otro"}, headers=h).status_code == 403
    for accion in ("desactivar", "reactivar", "desbloquear", "restablecer-contrasena"):
        assert cliente.post(f"/api/usuarios/{id_admin}/{accion}", headers=h).status_code == 403


def test_solo_el_administrador_tiene_el_permiso(cliente, cabeceras):
    roles = cliente.get("/api/usuarios/roles", headers=cabeceras(ADMIN)).json()["roles"]
    con_permiso = {r["nombre"] for r in roles if srv.PERMISO_ADMINISTRACION in r["permisos"]}
    assert con_permiso == {"Administrador"}


# ---------------------------------------------------------------------------
# Consulta
# ---------------------------------------------------------------------------
def test_listado_sin_hash_ni_usuario_tecnico(cliente, cabeceras):
    r = cliente.get("/api/usuarios", headers=cabeceras(ADMIN))
    assert r.status_code == 200
    assert "hash" not in r.text and "$argon2" not in r.text
    nombres = {u["nombre_usuario"] for u in r.json()}
    assert {"enf.rojas", "med.salazar", "nut.vilca", "coord.ortiz", ADMIN} <= nombres
    assert "sistema" not in nombres
    fila = next(u for u in r.json() if u["nombre_usuario"] == "enf.rojas")
    assert fila["rol"] == "Enfermera CRED" and fila["estado"] == "ACTIVO" and "ultimo_acceso" in fila


def test_roles_muestran_todo_el_catalogo_de_permisos(cliente, cabeceras, super_engine):
    r = cliente.get("/api/usuarios/roles", headers=cabeceras(ADMIN))
    with super_engine.connect() as c:
        catalogo = set(c.execute(text("SELECT codigo FROM seguridad.permiso")).scalars())
    assert {p["codigo"] for p in r.json()["permisos"]} == catalogo
    enfermera = next(x for x in r.json()["roles"] if x["nombre"] == "Enfermera CRED")
    assert set(enfermera["permisos"]) == {"REGISTRAR_PACIENTE", "REALIZAR_CONSULTA", "EXPORTAR_REPORTE"}


def test_usuario_inexistente_o_tecnico_da_404(cliente, cabeceras):
    h = cabeceras(ADMIN)
    assert cliente.get("/api/usuarios/7d0c5a3e-0000-4000-8000-000000000000", headers=h).status_code == 404
    assert cliente.get(f"/api/usuarios/{srv.ID_USUARIO_SISTEMA}", headers=h).status_code == 404
    assert cliente.post(f"/api/usuarios/{srv.ID_USUARIO_SISTEMA}/reactivar", headers=h).status_code == 404


# ---------------------------------------------------------------------------
# Creación
# ---------------------------------------------------------------------------
def test_crear_genera_contrasena_que_permite_iniciar_sesion(cliente, cabeceras, roles, usuarios_creados, super_engine):
    nombre = _nombre_usuario()
    r = cliente.post("/api/usuarios", headers=cabeceras(ADMIN), json={
        "nombre_completo": "  Lic.   Prueba   Creación ", "nombre_usuario": nombre.upper(),
        "correo_institucional": f"{nombre}@SANLUIS.GOB.PE", "id_rol": roles["Nutricionista"]})
    assert r.status_code == 201, r.text
    assert r.headers["cache-control"] == "no-store"
    cuerpo = r.json()
    usuarios_creados.append(cuerpo["usuario"]["id_usuario"])
    contrasena = cuerpo["contrasena_temporal"]
    assert cumple_politica(contrasena)
    u = cuerpo["usuario"]
    assert u["nombre_usuario"] == nombre and u["nombre_completo"] == "Lic. Prueba Creación"
    assert u["correo_institucional"] == f"{nombre}@sanluis.gob.pe"
    assert u["rol"] == "Nutricionista" and u["estado"] == "ACTIVO" and u["ultimo_acceso"] is None
    assert "hash" not in r.text

    with super_engine.connect() as c:
        guardado = c.execute(text("SELECT hash_contrasena FROM seguridad.usuario WHERE nombre_usuario = :u"),
                             {"u": nombre}).scalar_one()
    assert guardado.startswith("$argon2id$") and contrasena not in guardado

    login = _login(cliente, nombre, contrasena)
    assert login.status_code == 200 and login.json()["usuario"]["rol"] == "Nutricionista"

    eventos = _eventos(super_engine, u["id_usuario"])
    assert [e["tipo_evento"] for e in eventos] == ["USUARIO_CREADO"]
    assert contrasena not in eventos[0]["detalle"] and "contrasena" not in eventos[0]["detalle"]


def test_crear_rechaza_duplicados_y_datos_invalidos(cliente, cabeceras, roles, usuarios_creados):
    h = cabeceras(ADMIN)
    rol = roles["Médico"]
    existente = _crear(cliente, cabeceras, usuarios_creados, rol, correo_institucional=f"{_nombre_usuario()}@sanluis.gob.pe")
    u = existente["usuario"]

    r = cliente.post("/api/usuarios", headers=h, json={"nombre_completo": "Otro", "nombre_usuario": "enf.rojas", "id_rol": rol})
    assert r.status_code == 409 and "enf.rojas" in r.json()["detail"]
    r = cliente.post("/api/usuarios", headers=h, json={"nombre_completo": "Otro", "nombre_usuario": _nombre_usuario(),
                                                        "correo_institucional": u["correo_institucional"].upper(), "id_rol": rol})
    assert r.status_code == 409 and "correo" in r.json()["detail"]

    for usuario in ("enf rojas", "1enf", "enf..rojas", "enf.", "énf.rojas"):
        r = cliente.post("/api/usuarios", headers=h, json={"nombre_completo": "Otro", "nombre_usuario": usuario, "id_rol": rol})
        assert r.status_code == 422 and "letras minúsculas" in r.json()["detail"], usuario
    r = cliente.post("/api/usuarios", headers=h, json={"nombre_completo": "Otro", "nombre_usuario": _nombre_usuario(),
                                                        "correo_institucional": "sin-arroba", "id_rol": rol})
    assert r.status_code == 422 and "correo" in r.json()["detail"]
    r = cliente.post("/api/usuarios", headers=h, json={"nombre_completo": "Otro", "nombre_usuario": _nombre_usuario(), "id_rol": 999})
    assert r.status_code == 422 and r.json()["detail"] == "El rol no existe"
    # El administrador no escribe contraseñas: el campo no se admite
    r = cliente.post("/api/usuarios", headers=h, json={"nombre_completo": "Otro", "nombre_usuario": _nombre_usuario(),
                                                        "id_rol": rol, "contrasena": "Elegida123"})
    assert r.status_code == 422 and "no es un campo permitido" in r.json()["detail"]


# ---------------------------------------------------------------------------
# Edición
# ---------------------------------------------------------------------------
def test_editar_nombre_correo_y_rol_queda_auditado(cliente, cabeceras, roles, usuarios_creados, super_engine):
    u = _crear(cliente, cabeceras, usuarios_creados, roles["Enfermera CRED"])["usuario"]
    r = cliente.patch(f"/api/usuarios/{u['id_usuario']}", headers=cabeceras(ADMIN), json={
        "nombre_completo": "Dra. Prueba Editada", "id_rol": roles["Coordinador CRED"],
        "correo_institucional": "editada@sanluis.gob.pe"})
    assert r.status_code == 200, r.text
    assert r.json()["rol"] == "Coordinador CRED" and r.json()["nombre_completo"] == "Dra. Prueba Editada"

    evento = _eventos(super_engine, u["id_usuario"])[-1]
    assert evento["tipo_evento"] == "USUARIO_MODIFICADO"
    assert '"rol_anterior": "Enfermera CRED"' in evento["detalle"] and '"rol_nuevo": "Coordinador CRED"' in evento["detalle"]

    # Vaciar el correo opcional
    r = cliente.patch(f"/api/usuarios/{u['id_usuario']}", headers=cabeceras(ADMIN), json={"correo_institucional": ""})
    assert r.status_code == 200 and r.json()["correo_institucional"] is None


def test_el_nombre_de_usuario_no_se_modifica(cliente, cabeceras, roles, usuarios_creados):
    u = _crear(cliente, cabeceras, usuarios_creados, roles["Médico"])["usuario"]
    r = cliente.patch(f"/api/usuarios/{u['id_usuario']}", headers=cabeceras(ADMIN), json={"nombre_usuario": "otro.nombre"})
    assert r.status_code == 422 and "no es un campo permitido" in r.json()["detail"]
    r = cliente.patch(f"/api/usuarios/{u['id_usuario']}", headers=cabeceras(ADMIN), json={"nombre_completo": None})
    assert r.status_code == 422 and "no puede quedar vacío" in r.json()["detail"]
    r = cliente.patch(f"/api/usuarios/{u['id_usuario']}", headers=cabeceras(ADMIN), json={})
    assert r.status_code == 422


def test_el_rol_inactivo_no_se_asigna(cliente, cabeceras, roles, usuarios_creados, super_engine):
    u = _crear(cliente, cabeceras, usuarios_creados, roles["Médico"])["usuario"]
    with super_engine.begin() as c:
        c.execute(text("UPDATE seguridad.rol SET activo = false WHERE nombre = 'Nutricionista'"))
    try:
        r = cliente.patch(f"/api/usuarios/{u['id_usuario']}", headers=cabeceras(ADMIN),
                          json={"id_rol": roles["Nutricionista"]})
        assert r.status_code == 422 and "no está habilitado" in r.json()["detail"]
    finally:
        with super_engine.begin() as c:
            c.execute(text("UPDATE seguridad.rol SET activo = true WHERE nombre = 'Nutricionista'"))


# ---------------------------------------------------------------------------
# Reglas sobre la propia cuenta y el último administrador
# ---------------------------------------------------------------------------
def test_el_administrador_no_puede_desactivarse_ni_quitarse_el_rol(cliente, cabeceras, roles):
    h = cabeceras(ADMIN)
    yo = cliente.get("/api/auth/me", headers=h).json()["id_usuario"]
    r = cliente.post(f"/api/usuarios/{yo}/desactivar", headers=h)
    assert r.status_code == 409 and r.json()["detail"] == "No puede desactivar su propia cuenta"
    r = cliente.patch(f"/api/usuarios/{yo}", headers=h, json={"id_rol": roles["Médico"]})
    assert r.status_code == 409 and "a sí mismo" in r.json()["detail"]
    assert cliente.get(f"/api/usuarios/{yo}", headers=h).json()["estado"] == "ACTIVO"


def test_otro_administrador_puede_ser_desactivado(cliente, cabeceras, roles, usuarios_creados):
    u = _crear(cliente, cabeceras, usuarios_creados, roles["Administrador"])["usuario"]
    r = cliente.post(f"/api/usuarios/{u['id_usuario']}/desactivar", headers=cabeceras(ADMIN))
    assert r.status_code == 200 and r.json()["estado"] == "INACTIVO"


def test_no_se_puede_dejar_el_sistema_sin_administrador_activo(super_engine, roles):
    """La regla se prueba en el servicio: por la API, quien actúa siempre es un administrador
    activo distinto de la cuenta afectada. Todo ocurre en una transacción que se revierte."""
    id_admin = _id_de(super_engine, ADMIN)
    id_otro = _id_de(super_engine, "enf.rojas")
    with Session(super_engine) as s:
        s.execute(text("""UPDATE seguridad.usuario SET activo = false
                           WHERE id_usuario <> CAST(:id AS uuid) AND id_rol = :rol"""),
                  {"id": id_admin, "rol": roles["Administrador"]})
        actual = srv.obtener(s, id_admin, get_settings().max_intentos_fallidos)
        with pytest.raises(srv.ErrorConflicto, match="sin ningún administrador activo"):
            srv.desactivar(s, id_otro, actual)
        with pytest.raises(srv.ErrorConflicto, match="sin ningún administrador activo"):
            srv.actualizar(s, id_otro, actual, {"id_rol": roles["Médico"]})
        # Con un segundo administrador activo sí se permite
        s.execute(text("""UPDATE seguridad.usuario SET activo = true, id_rol = :rol
                           WHERE id_usuario = CAST(:id AS uuid)"""), {"id": id_otro, "rol": roles["Administrador"]})
        srv.desactivar(s, id_otro, actual)
        s.rollback()


# ---------------------------------------------------------------------------
# Desactivación, reactivación, desbloqueo y restablecimiento
# ---------------------------------------------------------------------------
def test_desactivar_impide_el_acceso_y_reactivar_lo_devuelve(cliente, cabeceras, roles, usuarios_creados, super_engine):
    creado = _crear(cliente, cabeceras, usuarios_creados, roles["Enfermera CRED"])
    u, contrasena = creado["usuario"], creado["contrasena_temporal"]
    token = _login(cliente, u["nombre_usuario"], contrasena).json()["token"]
    h = cabeceras(ADMIN)

    r = cliente.post(f"/api/usuarios/{u['id_usuario']}/desactivar", headers=h)
    assert r.status_code == 200 and r.json()["estado"] == "INACTIVO" and r.json()["fecha_desactivacion"]
    assert _login(cliente, u["nombre_usuario"], contrasena).status_code == 403
    # La sesión abierta deja de valer de inmediato
    assert cliente.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401
    assert cliente.post(f"/api/usuarios/{u['id_usuario']}/desactivar", headers=h).status_code == 409

    r = cliente.post(f"/api/usuarios/{u['id_usuario']}/reactivar", headers=h)
    assert r.status_code == 200 and r.json()["estado"] == "ACTIVO" and r.json()["fecha_desactivacion"] is None
    assert _login(cliente, u["nombre_usuario"], contrasena).status_code == 200
    assert cliente.post(f"/api/usuarios/{u['id_usuario']}/reactivar", headers=h).status_code == 409

    # La cuenta sigue en la base de datos: nunca se elimina
    tipos = [e["tipo_evento"] for e in _eventos(super_engine, u["id_usuario"])]
    assert tipos == ["USUARIO_CREADO", "USUARIO_DESACTIVADO", "USUARIO_REACTIVADO"]


def test_desbloquear_cuenta_bloqueada(cliente, cabeceras, roles, usuarios_creados):
    creado = _crear(cliente, cabeceras, usuarios_creados, roles["Médico"])
    u, contrasena = creado["usuario"], creado["contrasena_temporal"]
    h = cabeceras(ADMIN)
    assert cliente.post(f"/api/usuarios/{u['id_usuario']}/desbloquear", headers=h).status_code == 409

    for _ in range(get_settings().max_intentos_fallidos):
        assert _login(cliente, u["nombre_usuario"], "Incorrecta123").status_code == 401
    assert _login(cliente, u["nombre_usuario"], contrasena).status_code == 423
    fila = cliente.get(f"/api/usuarios/{u['id_usuario']}", headers=h).json()
    assert fila["estado"] == "BLOQUEADO" and fila["bloqueado"]

    r = cliente.post(f"/api/usuarios/{u['id_usuario']}/desbloquear", headers=h)
    assert r.status_code == 200 and r.json()["estado"] == "ACTIVO"
    assert _login(cliente, u["nombre_usuario"], contrasena).status_code == 200


def test_restablecer_contrasena(cliente, cabeceras, roles, usuarios_creados, super_engine):
    creado = _crear(cliente, cabeceras, usuarios_creados, roles["Nutricionista"])
    u, anterior = creado["usuario"], creado["contrasena_temporal"]
    for _ in range(get_settings().max_intentos_fallidos):
        _login(cliente, u["nombre_usuario"], "Incorrecta123")

    r = cliente.post(f"/api/usuarios/{u['id_usuario']}/restablecer-contrasena", headers=cabeceras(ADMIN))
    assert r.status_code == 200, r.text
    assert r.headers["cache-control"] == "no-store"
    nueva = r.json()["contrasena_temporal"]
    assert nueva != anterior and cumple_politica(nueva)
    assert r.json()["usuario"]["estado"] == "ACTIVO"  # también desbloquea
    assert "hash" not in r.text

    assert _login(cliente, u["nombre_usuario"], anterior).status_code == 401
    assert _login(cliente, u["nombre_usuario"], nueva).status_code == 200

    evento = [e for e in _eventos(super_engine, u["id_usuario"]) if e["tipo_evento"] == "CONTRASENA_RESTABLECIDA"][0]
    assert '"estaba_bloqueada": true' in evento["detalle"]
    with super_engine.connect() as c:
        detalles = c.execute(text("SELECT detalle::text FROM auditoria.evento_auditoria WHERE detalle IS NOT NULL")).scalars().all()
    assert not any(anterior in d or nueva in d for d in detalles)


# ---------------------------------------------------------------------------
# Política de contraseñas
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("contrasena, valida", [
    ("Abcdefgh12", True),
    ("Abcdefg12", False),       # 9 caracteres
    ("abcdefghijk", False),     # sin número
    ("1234567890", False),      # sin letra
    ("ñandú12345", True),
])
def test_politica_de_contrasenas(contrasena, valida):
    assert cumple_politica(contrasena) is valida


def test_contrasenas_generadas_cumplen_la_politica_y_no_se_repiten():
    generadas = {generar_contrasena() for _ in range(200)}
    assert len(generadas) == 200
    assert all(cumple_politica(c) and len(c) >= get_settings().contrasena_longitud_minima for c in generadas)
    assert not any(set("0O1lI") & set(c) for c in generadas)
