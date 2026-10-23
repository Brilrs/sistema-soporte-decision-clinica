"""Verificación de estado de los servicios (útil para Docker y Azure)."""
import httpx
from fastapi import APIRouter
from sqlalchemy import text

from app.core.config import get_settings
from app.core.db import engines

router = APIRouter(prefix="/api", tags=["Salud"])


@router.get("/salud")
def salud() -> dict:
    estado: dict[str, str] = {}
    for componente, engine in engines().items():
        try:
            with engine.connect() as c:
                c.execute(text("SELECT 1"))
            estado[f"bd_{componente}"] = "ok"
        except Exception:
            estado[f"bd_{componente}"] = "sin conexión"
    try:
        r = httpx.get(f"{get_settings().chroma_url}/api/v2/heartbeat", timeout=2)
        if r.status_code == 404:  # versiones anteriores de Chroma
            r = httpx.get(f"{get_settings().chroma_url}/api/v1/heartbeat", timeout=2)
        estado["chromadb"] = "ok" if r.status_code == 200 else f"error {r.status_code}"
    except Exception:
        estado["chromadb"] = "sin conexión"
    estado["estado"] = "ok" if all(v == "ok" for v in estado.values()) else "degradado"
    return estado
