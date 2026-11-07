"""Configuración del servicio de modelos, leída de variables de entorno."""
import os
from dataclasses import dataclass
from pathlib import Path

# onnx-int8: bge-reranker-v2-m3 exportado a ONNX y cuantizado a int8 (app.exportar_onnx).
# fp32: el modelo original con PyTorch, como alternativa.
RERANKERS = ("onnx-int8", "fp32")


@dataclass(frozen=True)
class Config:
    motor: str
    concurrencia: int
    max_longitud_embedding: int
    max_longitud_reranker: int
    hilos: int | None
    revisiones: Path
    reranker: str = "onnx-int8"
    dir_onnx: Path = Path("/modelos/onnx")
    longitud_calentamiento: int = 256


def _entero(nombre: str, defecto: int) -> int:
    valor = int(os.environ.get(nombre, defecto))
    if valor < 1:
        raise ValueError(f"{nombre} debe ser un entero mayor que cero")
    return valor


def cargar_config() -> Config:
    motor = os.environ.get("MODELOS_MOTOR", "real")
    if motor not in ("real", "falso"):
        raise ValueError("MODELOS_MOTOR debe ser 'real' o 'falso'")
    reranker = os.environ.get("MODELOS_RERANKER", "onnx-int8")
    if reranker not in RERANKERS:
        raise ValueError(f"MODELOS_RERANKER debe ser uno de: {', '.join(RERANKERS)}")
    hilos = os.environ.get("MODELOS_HILOS")
    return Config(
        motor=motor,
        concurrencia=_entero("MODELOS_CONCURRENCIA", 1),
        max_longitud_embedding=_entero("MODELOS_MAX_LONGITUD_EMBEDDING", 1024),
        max_longitud_reranker=_entero("MODELOS_MAX_LONGITUD_RERANKER", 1024),
        hilos=int(hilos) if hilos else None,
        revisiones=Path(os.environ.get("MODELOS_REVISIONES", Path(__file__).resolve().parents[1] / "revisiones.json")),
        reranker=reranker,
        dir_onnx=Path(os.environ.get("MODELOS_DIR_ONNX", "/modelos/onnx")),
        longitud_calentamiento=_entero("MODELOS_LONGITUD_CALENTAMIENTO", 256),
    )
