"""Sprint 3, parte L: despliegue en Azure (primera mitad: código, scripts y documentación).

- Nginx: reglas comunes a desarrollo y producción, HTTPS con TLS 1.2 o superior y el 80 solo para el
  desafío de Let's Encrypt y la redirección; desarrollo sigue solo en el 80.
- docker-compose.prod.yml: solo Nginx publica puertos, reinicio automático, entorno de producción y
  presupuesto de memoria de la VM de 8 GiB.
- db/aplicar_bd.sh y db/init/03_usuarios_bd.sh: contraseñas con \\getenv, nunca en la línea de comandos.
- deploy/: secretos de Key Vault, respaldos a Blob con retención, restauración probada, certificado y
  temporizadores de systemd. Los scripts se ejecutan con bash y un curl y un docker simulados
  (tests/despliegue_falsos), que anotan cada llamada: así se comprueba también que el token y los
  secretos nunca van en los argumentos de un proceso.

Sin Azure: la prueba real (Key Vault, Blob, Let's Encrypt y la VM) está en docs/despliegue_azure.md."""
import json
import os
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

RAIZ = Path(__file__).resolve().parents[2]
DEPLOY = RAIZ / "deploy"
FALSOS = Path(__file__).with_name("despliegue_falsos")
DOMINIO = "cdss-ejemplo.chilecentral.cloudapp.azure.com"
GIB = 1024 ** 3
MIB = 1024 ** 2


def _git_bash() -> str | None:
    """bash.exe de Git para Windows (Git\\bin), deducido de la ubicación de git o en su carpeta habitual.
    Nunca el de system32 ni el de WindowsApps: es el lanzador de WSL, que no ve las rutas de Windows."""
    candidatos = []
    git = shutil.which("git")
    if git:
        candidatos += [carpeta / "bin" / "bash.exe" for carpeta in Path(git).resolve().parents]
    for variable in ("ProgramW6432", "ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
        if os.environ.get(variable):
            base = Path(os.environ[variable])
            candidatos.append(base / ("Programs" if variable == "LOCALAPPDATA" else "") / "Git" / "bin" / "bash.exe")
    candidatos.append(Path(r"C:\Program Files\Git\bin\bash.exe"))
    for candidato in candidatos:
        partes = {p.lower() for p in candidato.parts}
        if candidato.is_file() and not partes & {"system32", "windowsapps"}:
            return str(candidato)
    return None


if os.name == "nt":
    BASH = _git_bash()
    requiere_bash = pytest.mark.skipif(BASH is None, reason="necesita Git Bash en Windows")
else:
    BASH = shutil.which("bash")
    requiere_bash = pytest.mark.skipif(BASH is None, reason="necesita bash")

# Ejecuta un script con una carpeta de programas falsos al principio del PATH. Se antepone dentro de bash
# porque Git\bin\bash.exe agrega /mingw64/bin y /usr/bin al arrancar: con el PATH puesto desde Python, el
# curl real ganaría al falso. $0 es la carpeta, $1 el script y el resto, sus argumentos.
PRIMERO_EN_PATH = 'export PATH="$0:$PATH"; exec bash "$@"'


# ---------------------------------------------------------------------------
# Ayudantes
# ---------------------------------------------------------------------------
class _Cargador(yaml.SafeLoader):
    """YAML de Compose con las etiquetas !reset y !override."""


for _etiqueta in ("!reset", "!override"):
    _Cargador.add_constructor(_etiqueta, lambda cargador, nodo, e=_etiqueta: (
        e, cargador.construct_sequence(nodo) if isinstance(nodo, yaml.SequenceNode)
        else cargador.construct_mapping(nodo) if isinstance(nodo, yaml.MappingNode) else None))


def _compose(nombre: str) -> dict:
    return yaml.load((RAIZ / nombre).read_text(encoding="utf-8"), Loader=_Cargador)


def _memoria(valor: str) -> int:
    numero, unidad = re.fullmatch(r"(\d+)([mg])", valor).groups()
    return int(numero) * (MIB if unidad == "m" else GIB)


def _ruta(p: Path) -> str:
    """Ruta con letra de unidad y barras normales: la entienden bash (Git Bash) y Python en Windows."""
    return p.as_posix()


def _ruta_bash(p: Path) -> str:
    """Ruta como la ve bash dentro de PATH (/c/... en Git Bash, sin cambios en Linux)."""
    if os.name != "nt":
        return str(p)
    r = subprocess.run([BASH, "-c", 'cygpath -u "$0"', _ruta(p)], capture_output=True, text=True, check=True)
    return r.stdout.strip()


@pytest.fixture
def falsos(tmp_path):
    """bin con curl y docker simulados, carpeta de Blob, Key Vault simulado y bitácora de llamadas."""
    binario = tmp_path / "bin"
    binario.mkdir()
    python = _ruta(Path(sys.executable))
    for programa in ("curl", "docker"):
        envoltorio = binario / programa
        envoltorio.write_text(f'#!/bin/bash\nexec "{python}" "{_ruta(FALSOS / f"fake_{programa}.py")}" "$@"\n',
                              encoding="utf-8", newline="\n")
        envoltorio.chmod(envoltorio.stat().st_mode | stat.S_IEXEC)
    blob = tmp_path / "blob"
    blob.mkdir()
    temporal = tmp_path / "tmp"
    temporal.mkdir()
    conf = tmp_path / "despliegue.conf"
    conf.write_text(f"KEY_VAULT=kv-prueba\nCDSS_DOMINIO={DOMINIO}\nCUENTA_ALMACENAMIENTO=stprueba\n"
                    "CONTENEDOR_RESPALDOS=respaldos\nCONSERVAR_RESPALDOS_CHROMA=3\nCONSERVAR_RESPALDOS_PG=3\n",
                    encoding="utf-8", newline="\n")
    secretos = tmp_path / "secretos.json"
    log = tmp_path / "llamadas.jsonl"
    log.touch()
    entorno = {
        **os.environ,
        "FAKE_LOG": _ruta(log), "FAKE_BLOB_DIR": _ruta(blob), "FAKE_SECRETOS": _ruta(secretos),
        "TMPDIR": _ruta(temporal), "CDSS_CONF_DESPLIEGUE": _ruta(conf), "CDSS_PYTHON": python,
        "CDSS_ENV_ARCHIVO": _ruta(tmp_path / ".env"), "MSYS_NO_PATHCONV": "1",
    }
    bin_bash = _ruta_bash(binario)

    class Falsos:
        def __init__(self):
            self.entorno, self.blob, self.secretos, self.log, self.tmp = entorno, blob, secretos, log, tmp_path
            self.temporal, self.env = temporal, tmp_path / ".env"

        def correr(self, script: str, *args: str, **extra) -> subprocess.CompletedProcess:
            return subprocess.run([BASH, "-c", PRIMERO_EN_PATH, bin_bash, _ruta(DEPLOY / script), *args],
                                  capture_output=True, text=True,
                                  encoding="utf-8", env={**self.entorno, **extra}, timeout=120)

        def llamadas(self, programa: str | None = None) -> list[dict]:
            filas = [json.loads(linea) for linea in self.log.read_text(encoding="utf-8").splitlines() if linea]
            return [f for f in filas if programa is None or f["programa"] == programa]

        def argumentos(self) -> str:
            return "\n".join(" ".join(f["argv"]) for f in self.llamadas())

        def blobs(self) -> list[str]:
            return sorted(p.relative_to(self.blob).as_posix() for p in self.blob.rglob("*") if p.is_file())

    return Falsos()


# Secretos válidos (valores de prueba, no reales) y con qué variable se escriben
SECRETOS = {
    "postgres-password": ("POSTGRES_PASSWORD", "a1b2c3d4e5f60718293a4b5c6d7e8f90"),
    "db-pwd-clinica": ("CDSS_DB_PWD_CLINICA", "clinica0123456789abcdef0123456789"),
    "db-pwd-generacion": ("CDSS_DB_PWD_GENERACION", "generacion0123456789abcdef012345"),
    "db-pwd-admin": ("CDSS_DB_PWD_ADMIN", "admin0123456789abcdef0123456789ab"),
    "db-pwd-auditor": ("CDSS_DB_PWD_AUDITOR", "auditor0123456789abcdef012345678"),
    "db-pwd-indexador": ("CDSS_DB_PWD_INDEXADOR", "indexador0123456789abcdef0123456"),
    "jwt-secreto": ("JWT_SECRETO", "jwt-secreto-de-prueba-con-mas-de-32-caracteres"),
    "clave-pii": ("CDSS_CLAVE_PII", "clave-pii-de-prueba-con-mas-de-32-caracteres"),
    "clave-hmac": ("CDSS_CLAVE_HMAC", "clave-hmac-de-prueba-con-mas-de-32-caracteres"),
    "anthropic-api-key": ("ANTHROPIC_API_KEY", "sk-ant-prueba-no-es-una-clave-real"),
}
OPCIONALES = {"seed-contrasena": ("SEED_CONTRASENA", "Semilla-de-prueba-2026"),
              "blob-cadena-conexion": ("AZURE_STORAGE_CONNECTION_STRING", "DefaultEndpointsProtocol=https;x=y")}


def _guardar_secretos(f, cambios: dict | None = None, quitar: tuple = (), opcionales: bool = False):
    datos = {n: v for n, (_, v) in SECRETOS.items()}
    if opcionales:
        datos.update({n: v for n, (_, v) in OPCIONALES.items()})
    datos.update(cambios or {})
    for n in quitar:
        datos.pop(n, None)
    f.secretos.write_text(json.dumps(datos), encoding="utf-8")
    return datos


def _leer_env(archivo: Path) -> dict:
    valores = {}
    for linea in archivo.read_text(encoding="utf-8").splitlines():
        m = re.fullmatch(r"([A-Z_]+)='(.*)'", linea)
        if m:
            valores[m.group(1)] = m.group(2)
    return valores


# ---------------------------------------------------------------------------
# Nginx
# ---------------------------------------------------------------------------
RUTAS = RAIZ / "frontend" / "nginx" / "cdss_rutas.conf"
NGINX_DEV = RAIZ / "frontend" / "nginx.conf"
NGINX_PROD = RAIZ / "frontend" / "nginx.prod.conf.template"
INCLUDE = "include /etc/nginx/cdss/rutas.conf;"


def _bloques_server(conf: str) -> list[str]:
    """Cuerpo de cada bloque server de primer nivel (cuenta llaves)."""
    bloques, i = [], 0
    while (inicio := conf.find("server {", i)) != -1:
        nivel, j = 0, inicio + len("server ")
        while True:
            if conf[j] == "{":
                nivel += 1
            elif conf[j] == "}":
                nivel -= 1
                if nivel == 0:
                    break
            j += 1
        bloques.append(conf[inicio:j + 1])
        i = j + 1
    return bloques


def _sin_comentarios(texto: str) -> str:
    return "\n".join(linea.split("#", 1)[0] for linea in texto.splitlines())


def test_desarrollo_y_produccion_incluyen_las_mismas_reglas_de_la_aplicacion():
    dev, prod = NGINX_DEV.read_text(encoding="utf-8"), NGINX_PROD.read_text(encoding="utf-8")
    assert _sin_comentarios(dev).count(INCLUDE) == 1 and _sin_comentarios(prod).count(INCLUDE) == 1
    # Ninguna regla de /api fuera del archivo común
    assert "location" not in _sin_comentarios(dev) and "/api" not in _sin_comentarios(prod)
    dockerfile = (RAIZ / "frontend" / "Dockerfile").read_text(encoding="utf-8")
    assert "COPY nginx/cdss_rutas.conf /etc/nginx/cdss/rutas.conf" in dockerfile
    assert "COPY nginx.prod.conf.template /etc/nginx/cdss/plantillas/default.conf.template" in dockerfile
    assert "COPY nginx.conf /etc/nginx/conf.d/default.conf" in dockerfile


def test_desarrollo_sigue_solo_en_el_puerto_80():
    dev = _sin_comentarios(NGINX_DEV.read_text(encoding="utf-8"))
    assert re.findall(r"listen\s+([^;]+);", dev) == ["80"]
    assert "ssl" not in dev and "443" not in dev
    assert _compose("docker-compose.yml")["services"]["nginx"]["ports"] == ["8080:80"]


def test_produccion_80_solo_desafio_y_redireccion():
    prod = _sin_comentarios(NGINX_PROD.read_text(encoding="utf-8"))
    del_80 = [b for b in _bloques_server(prod) if re.search(r"listen 80[ ;]", b)]
    assert len(del_80) == 2
    for bloque in del_80:
        assert "proxy_pass" not in bloque and INCLUDE not in bloque and "root /usr/share" not in bloque
    nombrado = next(b for b in del_80 if "server_name ${CDSS_DOMINIO};" in b)
    desafio = re.search(r"location \^~ /\.well-known/acme-challenge/ \{(.*?)\}", nombrado, re.S).group(1)
    assert "root /var/www/certbot;" in desafio
    assert "return 301 https://$host$request_uri;" in nombrado
    por_defecto = next(b for b in del_80 if "default_server" in b)
    assert "return 444;" in por_defecto


def test_produccion_443_con_tls_12_o_superior():
    prod = _sin_comentarios(NGINX_PROD.read_text(encoding="utf-8"))
    del_443 = [b for b in _bloques_server(prod) if "listen 443" in b]
    app = next(b for b in del_443 if INCLUDE in b)
    assert re.search(r"ssl_protocols\s+TLSv1\.2 TLSv1\.3;", app)
    assert "TLSv1 " not in prod and "TLSv1.1" not in prod and "SSLv" not in prod
    assert "http2 on;" in app and "server_name ${CDSS_DOMINIO};" in app
    assert "ssl_certificate /etc/letsencrypt/live/${CDSS_DOMINIO}/fullchain.pem;" in app
    assert "ssl_certificate_key /etc/letsencrypt/live/${CDSS_DOMINIO}/privkey.pem;" in app
    assert 'add_header Strict-Transport-Security "max-age=31536000" always;' in app
    otro = next(b for b in del_443 if INCLUDE not in b)
    assert "default_server" in otro and "ssl_reject_handshake on;" in otro


def test_la_plantilla_solo_usa_variables_cdss():
    """envsubst de la imagen solo reemplaza las CDSS_ (NGINX_ENVSUBST_FILTER): $host y $request_uri quedan."""
    prod = NGINX_PROD.read_text(encoding="utf-8")
    assert set(re.findall(r"\$\{([A-Z_]+)\}", prod)) == {"CDSS_DOMINIO"}
    servicio = _compose("docker-compose.prod.yml")["services"]["nginx"]
    assert servicio["environment"]["NGINX_ENVSUBST_FILTER"] == "CDSS_"
    assert servicio["environment"]["NGINX_ENVSUBST_TEMPLATE_DIR"] == "/etc/nginx/cdss/plantillas"
    assert "certbot_certificados:/etc/letsencrypt:ro" in servicio["volumes"]
    assert "certbot_webroot:/var/www/certbot:ro" in servicio["volumes"]


# ---------------------------------------------------------------------------
# docker-compose.prod.yml
# ---------------------------------------------------------------------------
PERMANENTES = ["db", "chromadb", "backend", "nginx", "modelos", "indexador"]
BAJO_DEMANDA = ["jobs", "respaldo", "respaldo-guias", "certbot"]


def _fusion() -> dict:
    """Fusión simple de los dos archivos (lo que hacen las etiquetas !reset y !override)."""
    base, prod = _compose("docker-compose.yml"), _compose("docker-compose.prod.yml")
    servicios = {n: dict(s) for n, s in base["services"].items()}
    for nombre, cambios in prod["services"].items():
        destino = servicios.setdefault(nombre, {})
        for clave, valor in cambios.items():
            if isinstance(valor, tuple):
                destino[clave] = valor[1]
            elif isinstance(valor, dict) and isinstance(destino.get(clave), dict):
                destino[clave] = {**destino[clave], **valor}
            else:
                destino[clave] = valor
    return servicios


def test_solo_nginx_publica_puertos_y_solo_80_y_443():
    servicios = _fusion()
    con_puertos = {n: s["ports"] for n, s in servicios.items() if s.get("ports")}
    publicados = {n: p for n, p in con_puertos.items() if n not in ("descargar-modelos", "exportar-onnx")}
    assert publicados == {"nginx": ["80:80", "443:443"]}
    prod = _compose("docker-compose.prod.yml")["services"]
    assert prod["db"]["ports"] == ("!reset", []) and prod["chromadb"]["ports"] == ("!reset", [])
    assert prod["nginx"]["ports"][0] == "!override"


def test_servicios_permanentes_se_reinician_solos():
    servicios = _fusion()
    for nombre in PERMANENTES:
        assert servicios[nombre].get("restart") == "unless-stopped", nombre


def test_entorno_de_produccion_fijo():
    servicios = _fusion()
    for nombre in ["backend", "indexador", "jobs", "respaldo", "respaldo-guias"]:
        assert servicios[nombre]["environment"]["CDSS_ENTORNO"] == "produccion", nombre
    backend = servicios["backend"]["environment"]
    assert backend["CDSS_LLM"] == "real" and backend["CDSS_LLM_FALSO_MODO"] == "normal"
    assert backend["CORS_ORIGENES"].startswith('["https://${CDSS_DOMINIO')
    assert servicios["certbot"]["image"] == "certbot/certbot:v2.11.0"  # versión fija, no latest


def test_presupuesto_de_memoria_en_8_gib():
    servicios = _fusion()
    permanentes = sum(_memoria(servicios[n]["mem_limit"]) for n in PERMANENTES)
    mayor_bajo_demanda = max(_memoria(servicios[n]["mem_limit"]) for n in BAJO_DEMANDA)
    assert permanentes == 5184 * MIB
    # Con un trabajo bajo demanda quedan al menos 1,75 GiB de los 8 GiB para el sistema y Docker.
    assert permanentes + mayor_bajo_demanda <= 8 * GIB - int(1.75 * GIB)
    # modelos: pico medido de unos 2,3 GiB al indexar (docs/mediciones_sprint2.md)
    assert _memoria(servicios["modelos"]["mem_limit"]) >= 3 * GIB


def _referencias_obligatorias() -> set[str]:
    """Variables ${X} de los dos archivos de Compose sin valor por omisión (:-) en los servicios que
    corren en la VM."""
    texto = "".join((RAIZ / n).read_text(encoding="utf-8") for n in ("docker-compose.yml", "docker-compose.prod.yml"))
    nombres = set()
    for m in re.finditer(r"\$\{([A-Z_]+)(:-|-|:\?|\?)?[^}]*\}", texto):
        if m.group(2) not in (":-", "-"):
            nombres.add(m.group(1))
    return nombres


def test_el_env_de_la_vm_trae_todas_las_variables_que_exigen_compose_y_el_backend():
    """«No omitas ninguna»: lo que escribe cargar_secretos.sh cubre las variables sin valor por omisión
    de Compose, y la configuración del backend (campos obligatorios) sale de esas variables."""
    script = (DEPLOY / "cargar_secretos.sh").read_text(encoding="utf-8")
    escritas = set(re.findall(r'"[a-z0-9-]+:([A-Z_]+):(?:url|clave|texto)"', script))
    escritas |= set(re.findall(r"linea ([A-Z_]+) ", script))
    assert _referencias_obligatorias() <= escritas, _referencias_obligatorias() - escritas
    from app.core.config import Settings
    obligatorias = {campo.alias for campo in Settings.model_fields.values() if campo.is_required()}
    backend = _fusion()["backend"]["environment"]
    assert obligatorias <= set(backend), obligatorias - set(backend)


@pytest.mark.skipif(shutil.which("docker") is None, reason="necesita docker compose")
def test_docker_compose_config_valida_la_fusion(tmp_path):
    entorno = tmp_path / "env"
    entorno.write_text("\n".join(f"{v}=valor-de-prueba" for v in sorted(_referencias_obligatorias()))
                       + f"\nCDSS_DOMINIO={DOMINIO}\n", encoding="utf-8")
    r = subprocess.run(["docker", "compose", "--env-file", str(entorno), "-f", str(RAIZ / "docker-compose.yml"),
                        "-f", str(RAIZ / "docker-compose.prod.yml"), "--profile", "jobs", "--profile", "respaldo",
                        "--profile", "certbot", "config", "--format", "json"],
                       capture_output=True, text=True, cwd=RAIZ, timeout=120)
    assert r.returncode == 0, r.stderr
    servicios = json.loads(r.stdout)["services"]
    publicados = {n: sorted(p["published"] for p in s["ports"]) for n, s in servicios.items() if s.get("ports")}
    assert publicados == {"nginx": ["443", "80"]}
    assert servicios["nginx"]["environment"]["CDSS_DOMINIO"] == DOMINIO
    assert servicios["backend"]["environment"]["CORS_ORIGENES"] == f'["https://{DOMINIO}"]'


# ---------------------------------------------------------------------------
# db/aplicar_bd.sh y db/init/03_usuarios_bd.sh: \getenv
# ---------------------------------------------------------------------------
PWD_DB = {f"CDSS_DB_PWD_{n}": f"valor-secreto-{n.lower()}-123" for n in
          ("CLINICA", "GENERACION", "ADMIN", "AUDITOR", "INDEXADOR")}


@pytest.fixture
def psql_falso(tmp_path):
    """psql que anota sus argumentos y su entrada estándar."""
    binario = tmp_path / "binpsql"
    binario.mkdir()
    log = tmp_path / "psql.log"
    psql = binario / "psql"
    psql.write_text('#!/bin/bash\n{ printf "ARGS:%s\\n" "$*"; cat; printf "\\nFIN\\n"; } >> "$PSQL_LOG"\n',
                    encoding="utf-8", newline="\n")
    psql.chmod(psql.stat().st_mode | stat.S_IEXEC)
    return _ruta_bash(binario), log


@requiere_bash
@pytest.mark.parametrize("script, args", [("db/aplicar_bd.sh", []), ("db/aplicar_bd.sh", ["--solo-migraciones"]),
                                          ("db/init/03_usuarios_bd.sh", [])])
def test_las_contrasenas_de_la_base_se_leen_con_getenv(psql_falso, script, args):
    ruta_bin, log = psql_falso
    entorno = {**os.environ, **PWD_DB, "PSQL_LOG": _ruta(log), "POSTGRES_USER": "postgres", "POSTGRES_DB": "cdss",
               "MSYS_NO_PATHCONV": "1"}
    r = subprocess.run([BASH, "-c", f'export PATH="{ruta_bin}:$PATH"; bash "{_ruta(RAIZ / script)}" {" ".join(args)}'],
                       capture_output=True, text=True, encoding="utf-8", env=entorno, timeout=60)
    assert r.returncode == 0, r.stderr
    registro = log.read_text(encoding="utf-8")
    argumentos = "\n".join(linea for linea in registro.splitlines() if linea.startswith("ARGS:"))
    for valor in PWD_DB.values():
        assert valor not in argumentos and valor not in registro and valor not in r.stdout + r.stderr
    for nombre in PWD_DB:
        psql_var = "pwd_" + nombre.removeprefix("CDSS_DB_PWD_").lower()
        assert f"\\getenv {psql_var} {nombre}" in registro
    assert "-v pwd_" not in (RAIZ / script).read_text(encoding="utf-8")


@requiere_bash
@pytest.mark.parametrize("script", ["db/aplicar_bd.sh", "db/init/03_usuarios_bd.sh"])
def test_falta_una_contrasena_de_la_base_y_se_detiene(psql_falso, script):
    ruta_bin, log = psql_falso
    entorno = {**os.environ, **PWD_DB, "PSQL_LOG": _ruta(log), "POSTGRES_USER": "postgres", "POSTGRES_DB": "cdss"}
    del entorno["CDSS_DB_PWD_AUDITOR"]
    r = subprocess.run([BASH, "-c", f'export PATH="{ruta_bin}:$PATH"; bash "{_ruta(RAIZ / script)}" --solo-migraciones'
                        if script.endswith("aplicar_bd.sh") else
                        f'export PATH="{ruta_bin}:$PATH"; bash "{_ruta(RAIZ / script)}"'],
                       capture_output=True, text=True, encoding="utf-8", env=entorno, timeout=60)
    assert r.returncode == 1 and "Falta la variable de entorno CDSS_DB_PWD_AUDITOR" in r.stderr
    assert "getenv" not in (log.read_text(encoding="utf-8") if log.exists() else "")


def test_aplicar_bd_vm_pasa_las_contrasenas_por_nombre():
    script = (DEPLOY / "aplicar_bd_vm.sh").read_text(encoding="utf-8")
    llamada = script[script.index("docker run"):]
    for nombre in [*PWD_DB, "PGPASSWORD"]:
        assert f"-e {nombre} " in llamada or f"-e {nombre}\n" in llamada or f"-e {nombre} \\" in llamada
    assert "=$" not in llamada  # ningún -e NOMBRE=$valor
    assert "postgres:16-alpine" in script and "/cdss-db/aplicar_bd.sh" in llamada


# ---------------------------------------------------------------------------
# deploy/cargar_secretos.sh
# ---------------------------------------------------------------------------
@requiere_bash
def test_cargar_secretos_escribe_el_env_completo_sin_mostrar_valores(falsos):
    _guardar_secretos(falsos, opcionales=True)
    r = falsos.correr("cargar_secretos.sh")
    assert r.returncode == 0, r.stderr
    valores = _leer_env(falsos.env)
    for nombre, (variable, valor) in {**SECRETOS, **OPCIONALES}.items():
        assert valores[variable] == valor, variable
        assert valor not in r.stdout + r.stderr  # nunca se muestra un valor
    assert valores["COMPOSE_FILE"] == "docker-compose.yml:docker-compose.prod.yml"
    assert valores["CDSS_DOMINIO"] == DOMINIO
    assert valores["RESPALDO_CONTENEDOR_BLOB"] == "respaldos"
    assert valores["AZURE_STORAGE_ACCOUNT_URL"] == "https://stprueba.blob.core.windows.net"
    assert valores["CDSS_SEED_EXIGIR_CAMBIO"] == "true"
    # Ni el token ni los secretos van en los argumentos de un proceso
    argumentos = falsos.argumentos()
    assert "token-falso-de-la-identidad" not in argumentos
    for _, valor in SECRETOS.values():
        assert valor not in argumentos
    # Sin temporales sueltos; permisos 600 (en Windows no se pueden comprobar)
    assert [p.name for p in falsos.tmp.glob(".env.*")] == []
    if os.name != "nt":
        assert stat.S_IMODE(falsos.env.stat().st_mode) == 0o600


@requiere_bash
def test_el_env_se_puede_cargar_con_source(falsos):
    _guardar_secretos(falsos)
    assert falsos.correr("cargar_secretos.sh").returncode == 0
    r = subprocess.run([BASH, "-c", f'set -a; source "{_ruta(falsos.env)}"; echo "$JWT_SECRETO|$COMPOSE_FILE"'],
                       capture_output=True, text=True, encoding="utf-8")
    assert r.stdout.strip() == f"{SECRETOS['jwt-secreto'][1]}|docker-compose.yml:docker-compose.prod.yml"


@requiere_bash
def test_los_opcionales_se_omiten_si_no_existen(falsos):
    _guardar_secretos(falsos)
    r = falsos.correr("cargar_secretos.sh")
    assert r.returncode == 0, r.stderr
    valores = _leer_env(falsos.env)
    assert "SEED_CONTRASENA" not in valores and "AZURE_STORAGE_CONNECTION_STRING" not in valores
    assert "seed-contrasena: no existe" in r.stderr


@requiere_bash
@pytest.mark.parametrize("cambios, quitar, mensaje", [
    ({}, ("clave-hmac",), "Falta el secreto obligatorio clave-hmac (CDSS_CLAVE_HMAC)"),
    ({"db-pwd-admin": "con@arroba:y/barra-0123456789"}, (), "El secreto db-pwd-admin debe tener al menos 16"),
    ({"db-pwd-clinica": "corta"}, (), "El secreto db-pwd-clinica debe tener al menos 16"),
    ({"jwt-secreto": "menos-de-32"}, (), "El secreto jwt-secreto debe tener al menos 32"),
    ({"anthropic-api-key": "con'comilla"}, (), "El secreto anthropic-api-key está vacío o tiene comillas"),
])
def test_un_secreto_faltante_o_no_valido_no_cambia_el_env(falsos, cambios, quitar, mensaje):
    _guardar_secretos(falsos)
    assert falsos.correr("cargar_secretos.sh").returncode == 0
    antes = falsos.env.read_bytes()
    datos = _guardar_secretos(falsos, cambios, quitar)
    r = falsos.correr("cargar_secretos.sh")
    assert r.returncode == 1 and mensaje in r.stderr and "No se escribió" in r.stderr
    assert falsos.env.read_bytes() == antes
    for valor in cambios.values():
        assert valor not in r.stdout + r.stderr
    assert [p.name for p in falsos.tmp.glob(".env.*")] == []
    assert datos  # los valores de prueba se usaron


@requiere_bash
def test_no_reemplaza_un_env_que_no_escribio(falsos):
    _guardar_secretos(falsos)
    falsos.env.write_text("JWT_SECRETO=el-de-desarrollo\n", encoding="utf-8")
    r = falsos.correr("cargar_secretos.sh")
    assert r.returncode == 1 and "no lo escribió este script" in r.stderr
    assert falsos.env.read_text(encoding="utf-8") == "JWT_SECRETO=el-de-desarrollo\n"


@requiere_bash
def test_sin_identidad_administrada_no_escribe_nada(falsos):
    _guardar_secretos(falsos)
    r = falsos.correr("cargar_secretos.sh", FAKE_IMDS_FALLA="1")
    assert r.returncode != 0 and "identidad administrada" in r.stderr
    assert not falsos.env.exists()


@requiere_bash
def test_sin_configuracion_explica_que_falta(falsos):
    r = falsos.correr("cargar_secretos.sh", CDSS_CONF_DESPLIEGUE=_ruta(falsos.tmp / "no_existe.conf"))
    assert r.returncode == 1 and "despliegue.conf.ejemplo" in r.stderr


# ---------------------------------------------------------------------------
# deploy/respaldo_pg.sh y deploy/restaurar_pg.sh
# ---------------------------------------------------------------------------
def _previos_pg(falsos, cantidad: int):
    carpeta = falsos.blob / "pg"
    carpeta.mkdir(exist_ok=True)
    for i in range(cantidad):
        (carpeta / f"cdss_202601{i + 1:02d}_030000.dump").write_bytes(b"viejo")
    # Ajenos al patrón: la retención nunca los toca
    (carpeta / "otro.dump").write_bytes(b"x")
    (carpeta / "cdss_2026.dump").write_bytes(b"x")
    (falsos.blob / "respaldo_20260101_030000").mkdir()
    (falsos.blob / "respaldo_20260101_030000" / "manifiesto.json").write_bytes(b"{}")


@requiere_bash
def test_respaldo_pg_sube_comprueba_y_aplica_la_retencion(falsos):
    _previos_pg(falsos, 5)
    r = falsos.correr("respaldo_pg.sh")
    assert r.returncode == 0, r.stderr
    dumps = [b for b in falsos.blobs() if re.fullmatch(r"pg/cdss_\d{8}_\d{6}\.dump", b)]
    assert len(dumps) == 3  # CONSERVAR_RESPALDOS_PG=3: el nuevo y los 2 previos más recientes
    nuevo = dumps[-1]
    assert (falsos.blob / nuevo).read_bytes().startswith(b"PGDMP-falso-")
    assert dumps[:2] == ["pg/cdss_20260104_030000.dump", "pg/cdss_20260105_030000.dump"]
    assert {"pg/otro.dump", "pg/cdss_2026.dump", "respaldo_20260101_030000/manifiesto.json"} <= set(falsos.blobs())
    assert "Subido y comprobado" in r.stdout
    assert "token-falso-de-la-identidad" not in falsos.argumentos()
    # pg_restore --list leyó el archivo antes de subirlo
    assert any("pg_restore" in " ".join(f["argv"]) and f["bytes_entrada"] > 0 for f in falsos.llamadas("docker"))


@requiere_bash
@pytest.mark.parametrize("falla, mensaje", [("FAKE_PGDUMP_VACIO", "pg_dump no produjo datos"),
                                            ("FAKE_PGRESTORE_FALLA", "no se puede leer con pg_restore")])
def test_respaldo_pg_no_sube_un_volcado_invalido(falsos, falla, mensaje):
    _previos_pg(falsos, 5)
    antes = falsos.blobs()
    r = falsos.correr("respaldo_pg.sh", **{falla: "1"})
    assert r.returncode != 0 and mensaje in r.stderr
    assert falsos.blobs() == antes  # ni sube ni borra


@requiere_bash
def test_respaldo_pg_corrupto_en_blob_no_aplica_la_retencion(falsos):
    _previos_pg(falsos, 5)
    r = falsos.correr("respaldo_pg.sh", FAKE_BLOB_CORROMPER="1")
    assert r.returncode != 0 and "no coincide con el archivo subido" in r.stderr
    previos = [b for b in falsos.blobs() if b.startswith("pg/cdss_202601")]
    assert len(previos) == 5  # no se borró ninguno


@requiere_bash
def test_restaurar_pg_prueba_en_base_aparte_y_la_borra(falsos):
    _previos_pg(falsos, 2)
    r = falsos.correr("restaurar_pg.sh")
    assert r.returncode == 0, r.stderr
    assert "pg/cdss_20260102_030000.dump" in r.stdout  # el más nuevo
    llamadas = [" ".join(f["argv"]) for f in falsos.llamadas("docker")]
    assert any("createdb" in c and "cdss_prueba_restauracion" in c for c in llamadas)
    assert any("pg_restore" in c and "cdss_prueba_restauracion" in c for c in llamadas)
    assert "dropdb" in llamadas[-1]  # la base de prueba se borra al final
    assert not any("--clean" in c for c in llamadas)  # la base real no se toca
    assert not any(c.startswith("compose stop") for c in llamadas)
    assert "Restauración probada" in r.stdout


@requiere_bash
def test_restaurar_pg_detecta_una_restauracion_incompleta_y_borra_la_base_de_prueba(falsos):
    _previos_pg(falsos, 1)
    r = falsos.correr("restaurar_pg.sh", FAKE_TABLAS_PRUEBA="12")
    assert r.returncode == 1 and "no tiene las mismas tablas" in r.stderr
    assert "dropdb" in " ".join(falsos.llamadas("docker")[-1]["argv"])


@requiere_bash
@pytest.mark.parametrize("args, mensaje", [
    (["pg/cdss_20260101_030000.dump", "--sobre-cdss"], "agregue --confirmo"),
    (["--sobre-cdss", "--confirmo"], "exige el nombre del respaldo"),
    (["pg/otro.dump"], "Nombre de respaldo no válido"),
])
def test_restaurar_pg_exige_confirmacion_y_nombres_validos(falsos, args, mensaje):
    _previos_pg(falsos, 1)
    r = falsos.correr("restaurar_pg.sh", *args)
    assert r.returncode == 2 and mensaje in r.stderr
    assert not any("pg_restore" in " ".join(f["argv"]) for f in falsos.llamadas("docker"))


@requiere_bash
def test_restaurar_pg_sobre_cdss_detiene_y_levanta_el_backend(falsos):
    _previos_pg(falsos, 1)
    r = falsos.correr("restaurar_pg.sh", "pg/cdss_20260101_030000.dump", "--sobre-cdss", "--confirmo")
    assert r.returncode == 0, r.stderr
    llamadas = [" ".join(f["argv"]) for f in falsos.llamadas("docker")]
    parada = next(i for i, c in enumerate(llamadas) if c == "compose stop backend indexador")
    restauracion = next(i for i, c in enumerate(llamadas) if "--clean --if-exists" in c)
    arranque = next(i for i, c in enumerate(llamadas) if c == "compose start backend indexador")
    assert parada < restauracion < arranque


# ---------------------------------------------------------------------------
# deploy/respaldo_chroma.sh y deploy/probar_restauracion_chroma.sh
# ---------------------------------------------------------------------------
@requiere_bash
def test_respaldo_chroma_crea_en_blob_con_retencion_y_verifica(falsos):
    r = falsos.correr("respaldo_chroma.sh")
    assert r.returncode == 0, r.stderr
    corridas = [f["argv"] for f in falsos.llamadas("docker") if "run" in f["argv"]]
    assert corridas[0][-6:] == ["app.respaldo", "crear", "--destino", "blob", "--conservar", "3"]
    assert corridas[1][-2:] == ["app.respaldo", "verificar"]


@requiere_bash
def test_respaldo_chroma_falla_si_crear_falla(falsos):
    r = falsos.correr("respaldo_chroma.sh", FAKE_CREAR_FALLA="1")
    assert r.returncode != 0
    assert not any("verificar" in f["argv"] for f in falsos.llamadas("docker"))


@requiere_bash
@pytest.mark.parametrize("comparar_falla", [False, True])
def test_probar_restauracion_chroma_usa_una_coleccion_aparte_y_la_descarta(falsos, comparar_falla):
    for nombre in ("respaldo_20260101_030000", "respaldo_20260103_030000", "respaldo_20260102_030000"):
        (falsos.blob / nombre).mkdir()
        (falsos.blob / nombre / "manifiesto.json").write_bytes(b"{}")
    extra = {"FAKE_COMPARAR_FALLA": "1"} if comparar_falla else {}
    r = falsos.correr("probar_restauracion_chroma.sh", **extra)
    assert (r.returncode != 0) == comparar_falla, r.stderr
    corridas = [f["argv"] for f in falsos.llamadas("docker") if "run" in f["argv"]]
    restaurar = next(c for c in corridas if "restaurar" in c)
    assert restaurar[-5:] == ["respaldo_20260103_030000", "--destino", "blob", "--coleccion",
                              "guias_clinicas_prueba_restauracion"]
    assert corridas[-1][-2:] == ["descartar-coleccion", "guias_clinicas_prueba_restauracion"]
    assert not any(c[-1] == "guias_clinicas" and "descartar-coleccion" in c for c in corridas)


# ---------------------------------------------------------------------------
# Certificado y systemd
# ---------------------------------------------------------------------------
@requiere_bash
def test_emitir_certificado_con_nginx_detenido(falsos):
    r = falsos.correr("renovar_certificado.sh", "emitir")
    assert r.returncode == 0, r.stderr
    llamadas = [" ".join(f["argv"]) for f in falsos.llamadas("docker")]
    assert llamadas[0] == "compose stop nginx"
    assert ("compose run --rm -p 80:80 certbot certonly --standalone --non-interactive --agree-tos "
            f"--register-unsafely-without-email --key-type ecdsa -d {DOMINIO}") == llamadas[1]
    assert llamadas[2] == "compose up -d nginx"


@requiere_bash
def test_renovar_certificado_por_webroot_y_recarga_nginx(falsos):
    r = falsos.correr("renovar_certificado.sh")
    assert r.returncode == 0, r.stderr
    llamadas = [" ".join(f["argv"]) for f in falsos.llamadas("docker")]
    renovar = next(i for i, c in enumerate(llamadas) if "certbot renew --webroot -w /var/www/certbot" in c)
    recarga = next(i for i, c in enumerate(llamadas) if c == "compose exec -T nginx nginx -s reload")
    assert renovar < recarga


def test_temporizadores_de_systemd():
    carpeta = DEPLOY / "systemd"
    temporizadores = sorted(carpeta.glob("*.timer"))
    assert [t.stem for t in temporizadores] == ["cdss-certificado", "cdss-respaldo-chroma", "cdss-respaldo-pg"]
    for temporizador in temporizadores:
        texto = temporizador.read_text(encoding="utf-8")
        assert re.search(r"^Persistent=true$", texto, re.M)  # la VM pasa apagada: lo atrasado corre al encenderla
        assert re.search(r"^OnCalendar=\*-\*-\* [\d,]+:\d\d:\d\d America/Lima$", texto, re.M)
        servicio = (carpeta / f"{temporizador.stem}.service").read_text(encoding="utf-8")
        script = re.search(r"^ExecStart=/bin/bash /opt/cdss-anemia/(deploy/\S+)", servicio, re.M).group(1)
        assert (RAIZ / script).is_file()
        assert "Type=oneshot" in servicio and "After=docker.service" in servicio


def test_scripts_de_despliegue_estrictos_y_en_lf():
    for script in sorted(DEPLOY.glob("*.sh")):
        datos = script.read_bytes()
        assert b"\r\n" not in datos, script.name
        if script.name != "comun.sh":
            assert b"set -euo pipefail" in datos, script.name
    for archivo in [*DEPLOY.glob("systemd/*"), DEPLOY / "despliegue.conf.ejemplo", NGINX_PROD, RUTAS,
                    RAIZ / "docker-compose.prod.yml"]:
        assert b"\r\n" not in archivo.read_bytes(), archivo.name


def test_la_guia_lista_todos_los_secretos_sin_valores():
    guia = (RAIZ / "docs" / "despliegue_azure.md").read_text(encoding="utf-8")
    for nombre, (variable, valor) in {**SECRETOS, **OPCIONALES}.items():
        assert f"`{nombre}`" in guia and f"`{variable}`" in guia, nombre
    ejemplo = (DEPLOY / "despliegue.conf.ejemplo").read_text(encoding="utf-8")
    assert "cambiar" in ejemplo and not re.search(r"(?i)(password|secreto|clave)\s*=", ejemplo)
