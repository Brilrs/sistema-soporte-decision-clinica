"""Conexiones a PostgreSQL. Cada componente usa su propio usuario de base de datos,
de modo que, por ejemplo, el componente de generación nunca puede leer
clinico.paciente_identidad aunque tuviera un error de programación."""
from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings


def _engine(url: str) -> Engine:
    return create_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=5)


@lru_cache
def engines() -> dict[str, Engine]:
    s = get_settings()
    return {
        "clinica": _engine(s.database_url_clinica),
        "generacion": _engine(s.database_url_generacion),
        "admin": _engine(s.database_url_admin),
    }


def _sesion(componente: str) -> Iterator[Session]:
    fabrica = sessionmaker(bind=engines()[componente], expire_on_commit=False)
    with fabrica() as sesion:
        try:
            yield sesion
            sesion.commit()
        except Exception:
            sesion.rollback()
            raise


def sesion_clinica() -> Iterator[Session]:
    yield from _sesion("clinica")


def sesion_generacion() -> Iterator[Session]:
    yield from _sesion("generacion")


def sesion_admin() -> Iterator[Session]:
    yield from _sesion("admin")
