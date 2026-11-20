"""Configuración del indexador (variables de entorno del contenedor jobs) y
manifiesto de las fuentes que se cargan."""
import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from app.indexador.extraccion import Recorte

DIR_PAQUETE = Path(__file__).parent
DIR_REPOSITORIO = DIR_PAQUETE.parents[2]


# Textos por petición de embeddings al servicio modelos (INDEXADOR_LOTE_EMBEDDINGS). modelos atiende una
# petición a la vez y un lote no se interrumpe: cada paso de una consulta que llega durante una indexación
# espera, como mucho, a que termine el lote en curso. Valor elegido por la medición de la parte J del
# Sprint 3 (pendiente P14, jobs/README.md): con lote 1 la recuperación sigue en unos 4,7 s mientras se
# indexa (35 s con lote 8), e indexar es más rápido porque los lotes no se rellenan hasta el texto más
# largo. No cambia lote_progreso; los vectores difieren de los del lote 8 en 3e-7 como mucho (medido).
LOTE_EMBEDDINGS_POR_OMISION = 1
LOTE_EMBEDDINGS_MAXIMO = 64  # máximo de textos por petición que admite modelos


def leer_lote_embeddings(valor: str | None) -> int:
    """INDEXADOR_LOTE_EMBEDDINGS: vacío o ausente usa el valor por omisión; si no, un entero de 1 a 64."""
    if valor is None or not valor.strip():
        return LOTE_EMBEDDINGS_POR_OMISION
    try:
        lote = int(valor.strip())
    except ValueError:
        lote = 0
    if not 1 <= lote <= LOTE_EMBEDDINGS_MAXIMO:
        raise ValueError(f"INDEXADOR_LOTE_EMBEDDINGS debe ser un entero de 1 a {LOTE_EMBEDDINGS_MAXIMO}; "
                         f"se recibió {valor!r}")
    return lote


@dataclass(frozen=True)
class ConfigIndexador:
    database_url: str | None
    chroma_url: str
    modelos_url: str
    dir_guias: Path
    dir_mediciones: Path
    intervalo_trabajador_s: float = 5.0
    lote_progreso: int = 16
    lote_embeddings: int = LOTE_EMBEDDINGS_POR_OMISION


def cargar_config() -> ConfigIndexador:
    return ConfigIndexador(
        database_url=os.environ.get("DATABASE_URL_INDEXADOR"),
        chroma_url=os.environ.get("CHROMA_URL", "http://localhost:8001"),
        modelos_url=os.environ.get("MODELOS_URL", "http://localhost:8000"),
        dir_guias=Path(os.environ.get("INDEXADOR_DIR_GUIAS", DIR_REPOSITORIO / "data" / "guias")),
        dir_mediciones=Path(os.environ.get("INDEXADOR_DIR_MEDICIONES", DIR_REPOSITORIO / "data" / "mediciones")),
        lote_embeddings=leer_lote_embeddings(os.environ.get("INDEXADOR_LOTE_EMBEDDINGS")),
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
    # False para los documentos cargados desde M11 (fuera del manifiesto): sin reglas propias de
    # grupo etario, todos sus fragmentos quedan GENERAL (parte F2).
    en_manifiesto: bool = True


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
