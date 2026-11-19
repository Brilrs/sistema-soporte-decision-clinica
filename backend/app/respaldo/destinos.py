"""Destinos del respaldo: una carpeta local (por omisión ./data/respaldos) o un contenedor de Azure
Blob Storage. Cada respaldo es una carpeta respaldo_AAAAMMDD_HHMMSS con sus archivos; en Blob, los
mismos archivos bajo el prefijo respaldo_AAAAMMDD_HHMMSS/.

La retención (depurar) solo borra respaldos de este mismo destino cuyo nombre cumple el patrón;
nunca otra carpeta, archivo ni blob."""
import hashlib
import json
import os
import re
import shutil
import tempfile
from pathlib import Path, PurePosixPath
from typing import Protocol

PATRON_RESPALDO = re.compile(r"^respaldo_\d{8}_\d{6}$")
MANIFIESTO = "manifiesto.json"
HUELLA_MANIFIESTO = "manifiesto.json.sha256"


class ErrorRespaldo(Exception):
    """Error con un mensaje claro para la persona que ejecuta el comando (código de salida 1)."""


def sha256_bytes(datos: bytes) -> str:
    return hashlib.sha256(datos).hexdigest()


def sha256_archivo(ruta: Path) -> str:
    h = hashlib.sha256()
    with ruta.open("rb") as f:
        for bloque in iter(lambda: f.read(1 << 20), b""):
            h.update(bloque)
    return h.hexdigest()


def ruta_segura(base: Path, relativa: str) -> Path:
    """Ruta de un archivo del manifiesto dentro de base. Rechaza rutas absolutas o con «..»."""
    partes = PurePosixPath(relativa)
    if partes.is_absolute() or ".." in partes.parts or not relativa or "\\" in relativa:
        raise ErrorRespaldo(f"El manifiesto tiene una ruta no válida: {relativa!r}")
    return base.joinpath(*partes.parts)


class Destino(Protocol):
    tipo: str

    def carpeta_nueva(self, nombre: str) -> Path: ...

    def publicar(self, nombre: str, carpeta: Path) -> None: ...

    def descartar_incompleto(self, nombre: str, carpeta: Path) -> None: ...

    def listar(self) -> list[str]: ...

    def obtener(self, nombre: str) -> Path: ...

    def borrar(self, nombre: str) -> None: ...


# ---------------------------------------------------------------------------
# Carpeta local
# ---------------------------------------------------------------------------
class DestinoLocal:
    tipo = "local"

    def __init__(self, raiz: Path):
        self.raiz = Path(raiz)

    def carpeta_nueva(self, nombre: str) -> Path:
        self.raiz.mkdir(parents=True, exist_ok=True)
        carpeta = self.raiz / nombre
        try:
            carpeta.mkdir()
        except FileExistsError:
            raise ErrorRespaldo(f"Ya existe el respaldo {nombre}; espere un segundo y vuelva a intentarlo") from None
        return carpeta

    def publicar(self, nombre: str, carpeta: Path) -> None:
        """La carpeta de trabajo ya es el destino."""

    def descartar_incompleto(self, nombre: str, carpeta: Path) -> None:
        if carpeta.parent == self.raiz and PATRON_RESPALDO.match(carpeta.name):
            shutil.rmtree(carpeta, ignore_errors=True)

    def listar(self) -> list[str]:
        if not self.raiz.is_dir():
            return []
        return sorted(p.name for p in self.raiz.iterdir()
                      if p.is_dir() and not p.is_symlink() and PATRON_RESPALDO.match(p.name))

    def obtener(self, nombre: str) -> Path:
        """Acepta el nombre de un respaldo de este destino o la ruta de una carpeta."""
        ruta = Path(nombre)
        carpeta = ruta if ruta.is_dir() else self.raiz / nombre
        if not carpeta.is_dir():
            raise ErrorRespaldo(f"No existe el respaldo {nombre}")
        return carpeta

    def borrar(self, nombre: str) -> None:
        if not PATRON_RESPALDO.match(nombre):
            raise ErrorRespaldo(f"{nombre} no es el nombre de un respaldo; no se borra")
        carpeta = self.raiz / nombre
        if carpeta.is_dir() and not carpeta.is_symlink():
            shutil.rmtree(carpeta)


# ---------------------------------------------------------------------------
# Azure Blob Storage
# ---------------------------------------------------------------------------
class ClienteBlob(Protocol):
    """Lo mínimo de un contenedor de Blob. ClienteBlobAzure envuelve el SDK; las pruebas usan uno simulado."""

    def subir(self, nombre: str, datos: bytes) -> None: ...

    def bajar(self, nombre: str) -> bytes: ...

    def listar(self, prefijo: str) -> list[str]: ...

    def borrar(self, nombre: str) -> None: ...


class ClienteBlobAzure:
    def __init__(self, contenedor):
        self._contenedor = contenedor

    def subir(self, nombre: str, datos: bytes) -> None:
        self._contenedor.upload_blob(nombre, datos, overwrite=False)

    def bajar(self, nombre: str) -> bytes:
        return self._contenedor.download_blob(nombre).readall()

    def listar(self, prefijo: str) -> list[str]:
        return sorted(b.name for b in self._contenedor.list_blobs(name_starts_with=prefijo))

    def borrar(self, nombre: str) -> None:
        self._contenedor.delete_blob(nombre)


def cliente_azure_desde_entorno() -> ClienteBlobAzure:
    """RESPALDO_CONTENEDOR_BLOB y, para autenticarse, AZURE_STORAGE_CONNECTION_STRING o la identidad
    administrada de la máquina (AZURE_STORAGE_ACCOUNT_URL y, si hay varias, AZURE_CLIENT_ID).
    La prueba real contra Azure se hace en la parte L."""
    contenedor = os.environ.get("RESPALDO_CONTENEDOR_BLOB", "").strip()
    if not contenedor:
        raise ErrorRespaldo("Falta RESPALDO_CONTENEDOR_BLOB (nombre del contenedor de Blob)")
    try:
        from azure.storage.blob import BlobServiceClient
    except ImportError:
        raise ErrorRespaldo("El destino blob necesita azure-storage-blob (imagen de jobs)") from None
    cadena = os.environ.get("AZURE_STORAGE_CONNECTION_STRING", "").strip()
    if cadena:
        servicio = BlobServiceClient.from_connection_string(cadena)
    else:
        cuenta = os.environ.get("AZURE_STORAGE_ACCOUNT_URL", "").strip()
        if not cuenta:
            raise ErrorRespaldo("Defina AZURE_STORAGE_CONNECTION_STRING o AZURE_STORAGE_ACCOUNT_URL "
                                "(identidad administrada)")
        from azure.identity import ManagedIdentityCredential
        credencial = ManagedIdentityCredential(client_id=os.environ.get("AZURE_CLIENT_ID") or None)
        servicio = BlobServiceClient(cuenta, credential=credencial)
    return ClienteBlobAzure(servicio.get_container_client(contenedor))


class DestinoBlob:
    """Sube y baja los mismos archivos que el destino local. Al subir, vuelve a bajar cada archivo y
    compara su SHA-256; al bajar, comprueba cada archivo contra el manifiesto antes de seguir."""
    tipo = "blob"

    def __init__(self, cliente: ClienteBlob, temporal: Path | None = None):
        self.cliente = cliente
        self._temporal = Path(temporal) if temporal else None
        self._carpetas: list[Path] = []

    def _carpeta_temporal(self) -> Path:
        carpeta = Path(tempfile.mkdtemp(prefix="cdss_respaldo_", dir=self._temporal))
        self._carpetas.append(carpeta)
        return carpeta

    def limpiar(self) -> None:
        for carpeta in self._carpetas:
            shutil.rmtree(carpeta, ignore_errors=True)
        self._carpetas.clear()

    def carpeta_nueva(self, nombre: str) -> Path:
        if nombre in self.listar():
            raise ErrorRespaldo(f"Ya existe el respaldo {nombre} en Blob; espere un segundo y vuelva a intentarlo")
        carpeta = self._carpeta_temporal() / nombre
        carpeta.mkdir()
        return carpeta

    def publicar(self, nombre: str, carpeta: Path) -> None:
        archivos = sorted(p for p in carpeta.rglob("*") if p.is_file())
        for ruta in archivos:
            self.cliente.subir(f"{nombre}/{ruta.relative_to(carpeta).as_posix()}", ruta.read_bytes())
        for ruta in archivos:
            blob = f"{nombre}/{ruta.relative_to(carpeta).as_posix()}"
            if sha256_bytes(self.cliente.bajar(blob)) != sha256_archivo(ruta):
                raise ErrorRespaldo(f"El archivo {blob} no quedó igual en Blob (SHA-256 distinto)")

    def descartar_incompleto(self, nombre: str, carpeta: Path) -> None:
        if PATRON_RESPALDO.match(nombre):
            for blob in self.cliente.listar(f"{nombre}/"):
                self.cliente.borrar(blob)

    def listar(self) -> list[str]:
        nombres = {b.split("/", 1)[0] for b in self.cliente.listar("respaldo_") if "/" in b}
        return sorted(n for n in nombres if PATRON_RESPALDO.match(n))

    def obtener(self, nombre: str) -> Path:
        if not PATRON_RESPALDO.match(nombre) or nombre not in self.listar():
            raise ErrorRespaldo(f"No existe el respaldo {nombre} en Blob")
        carpeta = self._carpeta_temporal() / nombre
        carpeta.mkdir()
        try:
            manifiesto = self.cliente.bajar(f"{nombre}/{MANIFIESTO}")
            huella = self.cliente.bajar(f"{nombre}/{HUELLA_MANIFIESTO}")
        except Exception as e:  # noqa: BLE001 (el SDK lanza varios tipos)
            raise ErrorRespaldo(f"Falta el manifiesto del respaldo {nombre} en Blob ({type(e).__name__})") from e
        if huella.decode("utf-8", "replace").split()[0:1] != [sha256_bytes(manifiesto)]:
            raise ErrorRespaldo("El manifiesto bajado de Blob no coincide con su SHA-256")
        (carpeta / MANIFIESTO).write_bytes(manifiesto)
        (carpeta / HUELLA_MANIFIESTO).write_bytes(huella)
        for archivo in json.loads(manifiesto)["archivos"]:
            destino = ruta_segura(carpeta, archivo["ruta"])
            try:
                datos = self.cliente.bajar(f"{nombre}/{archivo['ruta']}")
            except Exception as e:  # noqa: BLE001
                raise ErrorRespaldo(f"Falta el archivo {archivo['ruta']} en Blob ({type(e).__name__})") from e
            if sha256_bytes(datos) != archivo["sha256"]:
                raise ErrorRespaldo(f"El archivo {archivo['ruta']} bajado de Blob no coincide con el manifiesto")
            destino.parent.mkdir(parents=True, exist_ok=True)
            destino.write_bytes(datos)
        return carpeta

    def borrar(self, nombre: str) -> None:
        if not PATRON_RESPALDO.match(nombre):
            raise ErrorRespaldo(f"{nombre} no es el nombre de un respaldo; no se borra")
        for blob in self.cliente.listar(f"{nombre}/"):
            self.cliente.borrar(blob)
