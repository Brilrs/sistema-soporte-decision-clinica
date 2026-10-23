"""HU01 · Iniciar sesión, bloqueo por intentos y control de acceso por rol."""
from fastapi import APIRouter, Depends
from sqlalchemy import text

from app.api.deps import requiere_permiso
from app.main import app
from tests.conftest import CONTRASENA, token_de

# Ruta solo para probar el control de permisos (RBAC)
_r = APIRouter()


@_r.get("/api/_prueba/parametros", dependencies=[Depends(requiere_permiso("CONFIGURAR_PARAMETROS"))])
def _ruta_protegida():
    return {"ok": True}


app.include_router(_r)


def test_login_correcto_devuelve_token_y_permisos(cliente, desbloquear):
    r = cliente.post("/api/auth/login", json={"usuario": "enf.rojas", "contrasena": CONTRASENA})
    assert r.status_code == 200
    datos = r.json()
    assert datos["usuario"]["rol"] == "Enfermera CRED"
    assert set(datos["usuario"]["permisos"]) == {"REGISTRAR_PACIENTE", "REALIZAR_CONSULTA", "EXPORTAR_REPORTE"}
    me = cliente.get("/api/auth/me", headers={"Authorization": f"Bearer {datos['token']}"})
    assert me.status_code == 200 and me.json()["nombre_usuario"] == "enf.rojas"


def test_usuario_inexistente_y_contrasena_incorrecta_dan_el_mismo_mensaje(cliente, desbloquear):
    a = cliente.post("/api/auth/login", json={"usuario": "no.existe", "contrasena": "x"})
    b = cliente.post("/api/auth/login", json={"usuario": "enf.rojas", "contrasena": "incorrecta"})
    assert a.status_code == b.status_code == 401
    assert a.json()["detail"] == b.json()["detail"]


def test_bloqueo_tras_cinco_intentos_fallidos(cliente, desbloquear):
    for _ in range(5):
        assert cliente.post("/api/auth/login", json={"usuario": "med.salazar", "contrasena": "mala"}).status_code == 401
    r = cliente.post("/api/auth/login", json={"usuario": "med.salazar", "contrasena": CONTRASENA})
    assert r.status_code == 423


def test_cuenta_inactiva_no_inicia_sesion(cliente):
    r = cliente.post("/api/auth/login", json={"usuario": "sistema", "contrasena": "!"})
    assert r.status_code == 403


def test_sin_token_o_token_alterado(cliente):
    assert cliente.get("/api/auth/me").status_code == 401
    assert cliente.get("/api/auth/me", headers={"Authorization": "Bearer abc.def.ghi"}).status_code == 401


def test_permisos_por_rol(cliente, desbloquear):
    enfermera = token_de(cliente, "enf.rojas")
    coordinadora = token_de(cliente, "coord.ortiz")
    assert cliente.get("/api/_prueba/parametros", headers={"Authorization": f"Bearer {enfermera}"}).status_code == 403
    assert cliente.get("/api/_prueba/parametros", headers={"Authorization": f"Bearer {coordinadora}"}).status_code == 200


def test_login_queda_en_la_auditoria(cliente, desbloquear, super_engine):
    with super_engine.connect() as c:
        antes = c.execute(text("SELECT count(*) FROM auditoria.evento_auditoria WHERE tipo_evento = 'INICIO_SESION'")).scalar()
    token_de(cliente, "nut.vilca")
    with super_engine.connect() as c:
        despues = c.execute(text("SELECT count(*) FROM auditoria.evento_auditoria WHERE tipo_evento = 'INICIO_SESION'")).scalar()
    assert despues == antes + 1
