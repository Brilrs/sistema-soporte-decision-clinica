"""Configuración del servicio de modelos, leída de variables de entorno."""
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Config:
    motor: str
    concurrencia: int
    max_longitud_embedding: int
    max_longitud_reranker: int
    hilos: int | None
    revisiones: Path


def _entero(nombre: str, defecto: int) -> int:
    valor = int(os.environ.get(nombre, defecto))
    if valor < 1:
        raise ValueError(f"{nombre} debe ser un entero mayor que cero")
    return valor


def cargar_config() -> Config:
    motor = os.environ.get("MODELOS_MOTOR", "real")
    if motor not in ("real", "falso"):
        raise ValueError("MODELOS_MOTOR debe ser 'real' o 'falso'")
    hilos = os.environ.get("MODELOS_HILOS")
    return Config(
        motor=motor,
        concurrencia=_entero("MODELOS_CONCURRENCIA", 1),
        max_longitud_embedding=_entero("MODELOS_MAX_LONGITUD_EMBEDDING", 1024),
        max_longitud_reranker=_entero("MODELOS_MAX_LONGITUD_RERANKER", 1024),
        hilos=int(hilos) if hilos else None,
        revisiones=Path(os.environ.get("MODELOS_REVISIONES", Path(__file__).resolve().parents[1] / "revisiones.json")),
    )
