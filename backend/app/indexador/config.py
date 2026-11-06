"""Configuración del indexador (variables de entorno del contenedor jobs) y
manifiesto de las fuentes que se cargan."""
import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from app.indexador.extraccion import Recorte

DIR_PAQUETE = Path(__file__).parent
DIR_REPOSITORIO = DIR_PAQUETE.parents[2]


@dataclass(frozen=True)
class ConfigIndexador:
    database_url: str | None
    chroma_url: str
    modelos_url: str
    dir_guias: Path
    dir_mediciones: Path
    intervalo_trabajador_s: float = 5.0
    lote_progreso: int = 16


def cargar_config() -> ConfigIndexador:
    return ConfigIndexador(
        database_url=os.environ.get("DATABASE_URL_INDEXADOR"),
        chroma_url=os.environ.get("CHROMA_URL", "http://localhost:8001"),
        modelos_url=os.environ.get("MODELOS_URL", "http://localhost:8000"),
        dir_guias=Path(os.environ.get("INDEXADOR_DIR_GUIAS", DIR_REPOSITORIO / "data" / "guias")),
        dir_mediciones=Path(os.environ.get("INDEXADOR_DIR_MEDICIONES", DIR_REPOSITORIO / "data" / "mediciones")),
    )


@dataclass(frozen=True)
class FuenteDocumento:
    clave: str
    id_documento: str
    archivo: str
    recorte: Recorte = field(default_factory=Recorte)
    transcripciones: str | None = None
    modificaciones: str | None = None
    rol: str = "normal"
    prefijo_imagen: str | None = None


def cargar_manifiesto(ruta: str | Path) -> list[FuenteDocumento]:
    ruta = Path(ruta)
    if not ruta.is_file() and (DIR_PAQUETE / ruta).is_file():
        ruta = DIR_PAQUETE / ruta
    datos = yaml.safe_load(ruta.read_text(encoding="utf-8"))
    fuentes = []
    for d in datos["documentos"]:
        rol = d.get("rol", "normal")
        if rol not in ("normal", "modificado", "modificatorio"):
            raise ValueError(f"{d['clave']}: rol '{rol}' no válido")
        fuentes.append(FuenteDocumento(
            clave=d["clave"],
            id_documento=d["id_documento"],
            archivo=d["archivo"],
            recorte=Recorte(**(d.get("recorte") or {})),
            transcripciones=d.get("transcripciones"),
            modificaciones=d.get("modificaciones"),
            rol=rol,
            prefijo_imagen=d.get("prefijo_imagen"),
        ))
    return fuentes
