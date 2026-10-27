"""Las pruebas usan una base de datos real de PostgreSQL con el esquema, los
catálogos y los datos de demostración cargados (db/aplicar_bd.sh + seed_demo).
Variables: las del backend (.env.test) y TEST_DATABASE_URL_SUPER, una conexión
con privilegios de administración para preparar y limpiar los casos."""
import os
from pathlib import Path

import pytest

_env = Path(__file__).resolve().parents[1] / ".env.test"
if _env.exists():
    for linea in _env.read_text().splitlines():
        if linea.strip() and not linea.startswith("#") and "=" in linea:
            k, v = linea.split("=", 1)
            os.environ.setdefault(k, v)

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

from app.main import app  # noqa: E402

CONTRASENA = os.environ.get("SEED_CONTRASENA", "Cdss2026!")


@pytest.fixture(scope="session")
def super_engine():
    url = os.environ.get("TEST_DATABASE_URL_SUPER", "postgresql+psycopg://postgres@127.0.0.1:5433/cdss")
    return create_engine(url)


@pytest.fixture
def cliente():
    return TestClient(app)


@pytest.fixture
def desbloquear(super_engine):
    """Deja las cuentas de prueba sin intentos fallidos antes y después de cada caso."""
    def _reset():
        with super_engine.begin() as c:
            c.execute(text("UPDATE seguridad.usuario SET intentos_fallidos = 0 WHERE nombre_usuario <> 'sistema'"))
    _reset()
    yield
    _reset()


def token_de(cliente, usuario: str) -> str:
    r = cliente.post("/api/auth/login", json={"usuario": usuario, "contrasena": CONTRASENA})
    assert r.status_code == 200, r.text
    return r.json()["token"]


@pytest.fixture(scope="session")
def cabeceras(super_engine):
    """Cabeceras de autorización por usuario de prueba (un inicio de sesión por usuario)."""
    with super_engine.begin() as c:
        c.execute(text("UPDATE seguridad.usuario SET intentos_fallidos = 0 WHERE nombre_usuario <> 'sistema'"))
    cliente = TestClient(app)
    cache: dict[str, dict] = {}

    def _de(usuario: str) -> dict:
        if usuario not in cache:
            cache[usuario] = {"Authorization": f"Bearer {token_de(cliente, usuario)}"}
        return cache[usuario]

    return _de


@pytest.fixture
def pacientes_creados(super_engine):
    """Lista donde cada prueba anota los pacientes que crea; al final se eliminan con la
    conexión de administración (la aplicación no tiene permiso de DELETE). Los eventos
    de auditoría se conservan: la bitácora es inmutable."""
    ids: list[str] = []
    yield ids
    if not ids:
        return
    with super_engine.begin() as c:
        p = {"ids": ids}
        c.execute(text("""DELETE FROM clinico.tamizaje_sintoma WHERE id_tamizaje IN
                            (SELECT id_tamizaje FROM clinico.tamizaje WHERE id_paciente::text = ANY(:ids))"""), p)
        c.execute(text("""DELETE FROM clinico.resultado_clasificacion WHERE id_tamizaje IN
                            (SELECT id_tamizaje FROM clinico.tamizaje WHERE id_paciente::text = ANY(:ids))"""), p)
        c.execute(text("DELETE FROM clinico.tamizaje WHERE id_paciente::text = ANY(:ids)"), p)
        c.execute(text("DELETE FROM clinico.paciente_identidad WHERE id_paciente::text = ANY(:ids)"), p)
        c.execute(text("DELETE FROM clinico.paciente WHERE id_paciente::text = ANY(:ids)"), p)
