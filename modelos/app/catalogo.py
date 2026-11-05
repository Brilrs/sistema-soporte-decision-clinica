"""Modelos fijados a una revisión exacta de Hugging Face (revisiones.json)."""
import json
import re
from dataclasses import dataclass
from pathlib import Path

EMBEDDINGS = "bge-m3"
RERANKER = "bge-reranker-v2-m3"
_HASH = re.compile(r"[0-9a-f]{40}")


@dataclass(frozen=True)
class ModeloFijado:
    clave: str
    repositorio: str
    revision: str
    archivos: tuple[str, ...]
    dimension: int | None
    tamano_aproximado_mb: int


def cargar_catalogo(ruta: Path) -> dict[str, ModeloFijado]:
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    catalogo = {}
    for clave, d in datos.items():
        if not _HASH.fullmatch(d.get("revision") or ""):
            raise ValueError(f"La revisión de {clave} debe ser el hash completo de un commit (40 caracteres hexadecimales)")
        if not d.get("archivos"):
            raise ValueError(f"Falta la lista de archivos de {clave}")
        catalogo[clave] = ModeloFijado(clave, d["repositorio"], d["revision"], tuple(d["archivos"]),
                                       d.get("dimension"), d["tamano_aproximado_mb"])
    for requerido in (EMBEDDINGS, RERANKER):
        if requerido not in catalogo:
            raise ValueError(f"Falta {requerido} en {ruta}")
    return catalogo


def ruta_local(modelo: ModeloFijado) -> Path:
    """Carpeta local de la revisión fijada. No descarga nada: falla si el modelo no está en la caché."""
    from huggingface_hub import snapshot_download

    try:
        ruta = Path(snapshot_download(modelo.repositorio, revision=modelo.revision,
                                      allow_patterns=list(modelo.archivos), local_files_only=True))
    except Exception as e:
        raise RuntimeError(f"No se encontró {modelo.repositorio} en la revisión {modelo.revision[:12]}. "
                           "Descárguelo con: docker compose run --rm descargar-modelos") from e
    faltantes = [a for a in modelo.archivos if not (ruta / a).exists()]
    if faltantes:
        raise RuntimeError(f"Faltan archivos de {modelo.repositorio}: {', '.join(faltantes)}. "
                           "Vuelva a ejecutar: docker compose run --rm descargar-modelos")
    return ruta
