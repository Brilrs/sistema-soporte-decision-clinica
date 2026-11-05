"""generar_env.sh crea el .env y, si ya existe, solo agrega las variables que faltan."""
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "generar_env.sh"
VARIABLES = ["POSTGRES_PASSWORD", "CDSS_DB_PWD_CLINICA", "CDSS_DB_PWD_GENERACION", "CDSS_DB_PWD_ADMIN",
             "CDSS_DB_PWD_AUDITOR", "CDSS_DB_PWD_INDEXADOR", "JWT_SECRETO", "CDSS_CLAVE_PII",
             "CDSS_CLAVE_HMAC", "SEED_CONTRASENA", "ANTHROPIC_API_KEY", "OPENROUTER_API_KEY"]


def _bash() -> str | None:
    """En Windows se usa el bash de Git (el de System32 es el de WSL y no ve las rutas de Windows)."""
    if os.name == "nt":
        git = shutil.which("git")
        candidatos = [Path(git).resolve().parents[1] / "bin" / "bash.exe"] if git else []
        candidatos.append(Path(r"C:\Program Files\Git\bin\bash.exe"))
        return next((str(c) for c in candidatos if c.exists()), None)
    return shutil.which("bash")


BASH = _bash()
pytestmark = pytest.mark.skipif(BASH is None, reason="Requiere bash (en Windows, el de Git)")


def _ejecutar(archivo: Path) -> str:
    entorno = {**os.environ, "CDSS_ENV_ARCHIVO": archivo.as_posix()}
    r = subprocess.run([BASH, SCRIPT.as_posix()], env=entorno, capture_output=True, text=True,
                       encoding="utf-8", timeout=60)
    assert r.returncode == 0, r.stderr
    return r.stdout


def _variables(archivo: Path) -> dict[str, str]:
    return dict(linea.split("=", 1) for linea in archivo.read_text(encoding="utf-8").splitlines()
                if "=" in linea and not linea.startswith("#"))


def test_crea_el_env_completo_si_no_existe(tmp_path):
    archivo = tmp_path / ".env"
    salida = _ejecutar(archivo)
    assert "creado" in salida
    valores = _variables(archivo)
    assert list(valores) == VARIABLES
    assert re.fullmatch(r"[0-9a-f]{32}", valores["CDSS_DB_PWD_INDEXADOR"])
    assert re.fullmatch(r"[0-9a-f]{64}", valores["CDSS_CLAVE_PII"])
    assert valores["ANTHROPIC_API_KEY"] == ""


def test_agrega_solo_las_variables_que_faltan_sin_tocar_las_existentes(tmp_path):
    archivo = tmp_path / ".env"
    previo = ("# .env de un entorno anterior\n"
              "POSTGRES_PASSWORD=existente-pg\n"
              "CDSS_DB_PWD_CLINICA=existente-clinica\n"
              "CDSS_CLAVE_PII=clave-que-no-debe-cambiar\n"
              "ANTHROPIC_API_KEY=sk-ant-de-ejemplo\n"
              "OTRA_VARIABLE=se-conserva")
    archivo.write_text(previo, encoding="utf-8")
    salida = _ejecutar(archivo)
    contenido = archivo.read_text(encoding="utf-8")
    assert contenido.startswith(previo + "\n")
    valores = _variables(archivo)
    assert valores["CDSS_CLAVE_PII"] == "clave-que-no-debe-cambiar"
    assert valores["ANTHROPIC_API_KEY"] == "sk-ant-de-ejemplo"
    assert valores["OTRA_VARIABLE"] == "se-conserva"
    assert set(VARIABLES) <= set(valores)
    assert "CDSS_DB_PWD_INDEXADOR" in salida and "POSTGRES_PASSWORD" not in salida.split("agregaron:")[1]
    assert all(contenido.count(f"\n{v}=") + contenido.startswith(f"{v}=") == 1 for v in VARIABLES)


def test_no_modifica_un_env_completo(tmp_path):
    archivo = tmp_path / ".env"
    _ejecutar(archivo)
    antes = archivo.read_bytes()
    salida = _ejecutar(archivo)
    assert archivo.read_bytes() == antes
    assert "no se modificó" in salida
