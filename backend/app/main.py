"""Punto de entrada del backend del CDSS (FastAPI)."""
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import auth, catalogos, consultas, pacientes, salud, usuarios
from app.core.config import get_settings
from app.core.errores import manejar_error_validacion

log = logging.getLogger("uvicorn.error")  # el logger que uvicorn muestra en INFO


REINTENTOS_CALENTAMIENTO = 60
PAUSA_CALENTAMIENTO_S = 5


async def calentar_con_reintentos(reintentos: int = REINTENTOS_CALENTAMIENTO,
                                  pausa_s: float = PAUSA_CALENTAMIENTO_S) -> dict | None:
    """Calienta los modelos, ChromaDB, el índice BM25, el esquema y el prompt
    (app.services.consultas.calentar). El servicio modelos puede tardar más que el
    backend en arrancar (en B2ms, más de un minuto), así que reintenta cada pausa_s."""
    from app.services.consultas import calentar
    for intento in range(1, reintentos + 1):
        try:
            tiempos = await asyncio.to_thread(calentar)
            log.info("Calentamiento (intento %d): %s", intento, tiempos)
            return tiempos
        except Exception as e:  # noqa: BLE001
            if intento == 1:
                log.warning("Calentamiento pendiente (%s); se reintenta cada %g s", type(e).__name__, pausa_s)
            await asyncio.sleep(pausa_s)
    log.warning("Calentamiento incompleto tras %d intentos; la primera consulta lo hará en frío", reintentos)
    return None


@asynccontextmanager
async def ciclo_de_vida(_: FastAPI):
    """El calentamiento corre en segundo plano: la API (pacientes, tamizajes) atiende
    mientras tanto. Nunca en pruebas."""
    tarea = None
    if get_settings().entorno != "pruebas":
        tarea = asyncio.create_task(calentar_con_reintentos())
    yield
    if tarea is not None and not tarea.done():
        tarea.cancel()


app = FastAPI(
    lifespan=ciclo_de_vida,
    title="CDSS Anemia Infantil · API",
    version="0.1.0",
    description="Sistema de soporte a la decisión clínica para la evaluación del riesgo de anemia infantil (CRED).",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origenes,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)

app.add_exception_handler(RequestValidationError, manejar_error_validacion)

app.include_router(salud.router)
app.include_router(auth.router)
app.include_router(catalogos.router)
app.include_router(pacientes.router)
app.include_router(usuarios.router)
app.include_router(consultas.router)


def openapi_con_eventos() -> dict:
    """OpenAPI con los esquemas de los eventos NDJSON de las consultas (EventoConsulta)."""
    if app.openapi_schema is None:
        from fastapi.openapi.utils import get_openapi
        esquema = get_openapi(title=app.title, version=app.version, description=app.description, routes=app.routes)
        esquema.setdefault("components", {}).setdefault("schemas", {}).update(consultas.esquemas_eventos())
        app.openapi_schema = esquema
    return app.openapi_schema


app.openapi = openapi_con_eventos
