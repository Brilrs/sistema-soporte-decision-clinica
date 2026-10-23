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
