"""curl simulado para las pruebas de deploy/ (parte L). Atiende el servicio de metadatos (token de la
identidad administrada), Key Vault y Blob con archivos locales, y anota cada llamada (argumentos y si el
token llegó por la entrada estándar) en FAKE_LOG."""
import json
import os
import re
import shutil
import sys
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

TOKEN = "token-falso-de-la-identidad"


def ruta(p: str) -> Path:
    """En Git Bash (Windows) los scripts pasan rutas /tmp/...: se convierten con cygpath."""
    if os.name == "nt" and p.startswith("/"):
        import subprocess
        return Path(subprocess.run(["cygpath", "-w", p], capture_output=True, text=True).stdout.strip())
    return Path(p)


def main(args: list[str]) -> int:
    opciones: dict[str, str] = {}
    cabeceras: list[str] = []
    url = None
    falla = False
    i = 0
    while i < len(args):
        a = args[i]
        if a in ("-K", "-o", "-w", "-X", "--data-binary", "--max-time"):
            opciones[a] = args[i + 1]
            i += 2
            continue
        if a == "-H":
            cabeceras.append(args[i + 1])
            i += 2
            continue
        if a == "--fail":
            falla = True
        elif a.startswith("http"):
            url = a
        i += 1
    entrada = sys.stdin.read() if opciones.get("-K") == "-" else ""
    cabeceras += re.findall(r'header = "([^"]*)"', entrada)
    with open(os.environ["FAKE_LOG"], "a", encoding="utf-8") as log:
        log.write(json.dumps({"programa": "curl", "argv": args, "url": url}) + "\n")

    def responder(codigo: int, cuerpo: bytes = b"") -> int:
        if "-o" in opciones:
            ruta(opciones["-o"]).write_bytes(cuerpo)
        else:
            sys.stdout.buffer.write(cuerpo)
        if "-w" in opciones:
            sys.stdout.write(opciones["-w"].replace("%{http_code}", str(codigo)))
        return 22 if falla and codigo >= 400 else 0

    autorizado = f"Authorization: Bearer {TOKEN}" in cabeceras
    u = urlparse(url)
    if "/metadata/identity/oauth2/token" in u.path:
        if "Metadata: true" not in cabeceras or os.environ.get("FAKE_IMDS_FALLA"):
            return responder(400, b"{}")
        return responder(200, json.dumps({"access_token": TOKEN}).encode())
    if u.hostname.endswith(".vault.azure.net"):
        if not autorizado:
            return responder(401, b"{}")
        nombre = u.path.rsplit("/", 1)[1]
        secretos = json.loads(Path(os.environ["FAKE_SECRETOS"]).read_text(encoding="utf-8"))
        if nombre not in secretos:
            return responder(404, b'{"error": {"code": "SecretNotFound"}}')
        return responder(200, json.dumps({"value": secretos[nombre], "id": nombre}).encode())
    if u.hostname.endswith(".blob.core.windows.net"):
        if not autorizado:
            return responder(403, b"")
        raiz = Path(os.environ["FAKE_BLOB_DIR"])
        partes = u.path.lstrip("/").split("/", 1)
        consulta = parse_qs(u.query)
        if consulta.get("comp") == ["list"]:
            prefijo = consulta.get("prefix", [""])[0]
            nombres = sorted(p.relative_to(raiz).as_posix() for p in raiz.rglob("*") if p.is_file())
            xml = "".join(f"<Blob><Name>{n}</Name></Blob>" for n in nombres if n.startswith(prefijo))
            return responder(200, f"<EnumerationResults><Blobs>{xml}</Blobs><NextMarker/></EnumerationResults>".encode())
        destino = raiz / unquote(partes[1])
        metodo = opciones.get("-X", "GET")
        if metodo == "PUT":
            destino.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ruta(opciones["--data-binary"].lstrip("@")), destino)
            return responder(201)
        if metodo == "DELETE":
            if not destino.exists():
                return responder(404)
            destino.unlink()
            return responder(202)
        if not destino.exists():
            return responder(404)
        datos = destino.read_bytes()
        if os.environ.get("FAKE_BLOB_CORROMPER"):
            datos += b"x"
        return responder(200, datos)
    return responder(599)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
