"""Fila 168: el inicio de sesión no revela si una cuenta existe o está inactiva sin la contraseña
correcta, y reactivar una cuenta reinicia sus intentos fallidos.

(a) cuenta inactiva con la clave equivocada: la misma respuesta que un usuario inexistente;
(b) cuenta inactiva con la clave correcta: 403 con el aviso de cuenta desactivada;
(c) cuenta activa: sin cambios, con el bloqueo (423) tras los intentos fallidos;
(d) reactivar una cuenta con intentos fallidos o bloqueada la deja en 0 y puede iniciar sesión;
(e) un usuario inexistente no cambia ningún contador y pasa por una verificación Argon2.
Las cuentas son sintéticas (prefijo prueba.) y las limpia la fixture usuarios_creados."""
import json

from sqlalchemy import text

from app.api.routes import auth
from app.core.config import get_settings
from tests.test_usuarios import ADMIN, _crear, _eventos, _login, roles, usuarios_creados  # noqa: F401 (fixtures)

INEXISTENTE = "prueba.no.existe.nunca"
EQUIVOCADA = "Clave-equivocada-1"


def _cuenta(cliente, cabeceras, usuarios_creados, roles, inactiva: bool = False) -> tuple[dict, str]:  # noqa: F811
    creado = _crear(cliente, cabeceras, usuarios_creados, roles["Enfermera CRED"])
    u = creado["usuario"]
    if inactiva:
        assert cliente.post(f"/api/usuarios/{u['id_usuario']}/desactivar", headers=cabeceras(ADMIN)).status_code == 200
    return u, creado["contrasena_temporal"]


def _intentos(super_engine, id_usuario: str) -> int:
    with super_engine.connect() as c:
        return c.execute(text("SELECT intentos_fallidos FROM seguridad.usuario WHERE id_usuario = CAST(:id AS uuid)"),
                         {"id": id_usuario}).scalar_one()


def _respuesta(r) -> tuple:
    """Lo que ve quien intenta iniciar sesión: código, cuerpo y cabeceras propias del error."""
    return r.status_code, r.json(), r.headers.get("x-codigo-error"), r.headers.get("www-authenticate")


def test_a_inactiva_con_clave_equivocada_igual_que_inexistente(cliente, cabeceras, usuarios_creados, roles,  # noqa: F811
                                                                super_engine):
    u, _ = _cuenta(cliente, cabeceras, usuarios_creados, roles, inactiva=True)
    inexistente = _respuesta(_login(cliente, INEXISTENTE, EQUIVOCADA))
    assert inexistente[:2] == (401, {"detail": auth.MENSAJE_GENERICO})
    # Igual también después del máximo de intentos: una cuenta inactiva no anuncia el bloqueo (423).
    maximo = get_settings().max_intentos_fallidos
    for _ in range(maximo + 2):
        assert _respuesta(_login(cliente, u["nombre_usuario"], EQUIVOCADA)) == inexistente
    assert _intentos(super_engine, u["id_usuario"]) == maximo + 2


def test_b_inactiva_con_clave_correcta_responde_403(cliente, cabeceras, usuarios_creados, roles, super_engine):  # noqa: F811
    u, clave = _cuenta(cliente, cabeceras, usuarios_creados, roles, inactiva=True)
    r = _login(cliente, u["nombre_usuario"], clave)
    assert r.status_code == 403 and r.json() == {"detail": auth.MENSAJE_INACTIVA}
    assert "token" not in r.text
    # Tras el máximo de intentos equivocados, la clave correcta ya no se confirma: 401 genérico.
    for _ in range(get_settings().max_intentos_fallidos):
        _login(cliente, u["nombre_usuario"], EQUIVOCADA)
    r = _login(cliente, u["nombre_usuario"], clave)
    assert r.status_code == 401 and r.json() == {"detail": auth.MENSAJE_GENERICO}
    with super_engine.connect() as c:
        motivos = [m for (m,) in c.execute(text(
            """SELECT detalle ->> 'motivo' FROM auditoria.evento_auditoria
                WHERE tipo_evento = 'INICIO_SESION_FALLIDO' AND id_entidad = :id ORDER BY id_evento"""),
            {"id": u["id_usuario"]})]
    assert motivos[0] == "cuenta_inactiva" and motivos[-1] == "cuenta_inactiva_bloqueada"
    assert set(motivos[1:-1]) == {"cuenta_inactiva_contrasena_incorrecta"}


def test_c_cuenta_activa_sin_cambios_y_con_bloqueo(cliente, cabeceras, usuarios_creados, roles, super_engine):  # noqa: F811
    u, clave = _cuenta(cliente, cabeceras, usuarios_creados, roles)
    maximo = get_settings().max_intentos_fallidos
    for i in range(1, maximo + 1):
        r = _login(cliente, u["nombre_usuario"], EQUIVOCADA)
        assert r.status_code == 401 and r.json() == {"detail": auth.MENSAJE_GENERICO}
        assert _intentos(super_engine, u["id_usuario"]) == i
    for contrasena in (clave, EQUIVOCADA):
        r = _login(cliente, u["nombre_usuario"], contrasena)
        assert r.status_code == 423 and r.json() == {"detail": auth.MENSAJE_BLOQUEADA}
    assert _intentos(super_engine, u["id_usuario"]) == maximo
    # Desbloqueada, la clave correcta entra y reinicia el contador.
    assert cliente.post(f"/api/usuarios/{u['id_usuario']}/desbloquear", headers=cabeceras(ADMIN)).status_code == 200
    _login(cliente, u["nombre_usuario"], EQUIVOCADA)
    assert _login(cliente, u["nombre_usuario"], clave).status_code == 200
    assert _intentos(super_engine, u["id_usuario"]) == 0


def test_d_reactivar_reinicia_los_intentos_y_permite_entrar(cliente, cabeceras, usuarios_creados, roles,  # noqa: F811
                                                            super_engine):
    h = cabeceras(ADMIN)
    maximo = get_settings().max_intentos_fallidos
    for fallidos in (2, maximo + 1):
        u, clave = _cuenta(cliente, cabeceras, usuarios_creados, roles, inactiva=True)
        for _ in range(fallidos):
            _login(cliente, u["nombre_usuario"], EQUIVOCADA)
        assert _intentos(super_engine, u["id_usuario"]) == fallidos
        r = cliente.post(f"/api/usuarios/{u['id_usuario']}/reactivar", headers=h)
        assert r.status_code == 200 and r.json()["estado"] == "ACTIVO" and r.json()["bloqueado"] is False
        assert _intentos(super_engine, u["id_usuario"]) == 0
        assert _login(cliente, u["nombre_usuario"], clave).status_code == 200
        evento = _eventos(super_engine, u["id_usuario"])[-1]
        assert evento["tipo_evento"] == "USUARIO_REACTIVADO"
        assert json.loads(evento["detalle"]) == {"nombre_usuario": u["nombre_usuario"], "desbloqueada": fallidos >= maximo}
        assert clave not in evento["detalle"] and "contrasena" not in evento["detalle"]


def test_e_usuario_inexistente_no_cambia_contadores_y_verifica_un_hash(cliente, super_engine, monkeypatch):
    llamadas = []
    original = auth.verificar_contrasena_ficticia
    monkeypatch.setattr(auth, "verificar_contrasena_ficticia", lambda c: llamadas.append(1) or original(c))
    consulta = ("SELECT md5(string_agg(id_usuario::text || ':' || intentos_fallidos, ',' ORDER BY id_usuario)) "
                "FROM seguridad.usuario")
    with super_engine.connect() as c:
        antes = c.execute(text(consulta)).scalar_one()
    for _ in range(3):
        assert _login(cliente, INEXISTENTE, EQUIVOCADA).status_code == 401
    with super_engine.connect() as c:
        assert c.execute(text(consulta)).scalar_one() == antes
    assert len(llamadas) == 3
    assert original("cualquiera") is False
