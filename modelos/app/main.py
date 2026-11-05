"""Servicio interno de modelos locales (sin puerto publicado).

Expone bge-m3 y bge-reranker-v2-m3 al backend y al indexador por HTTP. Los modelos
se cargan una sola vez al iniciar. Un semáforo limita las inferencias simultáneas
para no exceder la memoria y los núcleos asignados al contenedor; el conteo de
tokens solo usa el tokenizador y no pasa por el semáforo."""
import asyncio
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import AfterValidator, BaseModel, Field

from app.config import cargar_config
from app.motor import Motor, crear_motor

MAX_TEXTOS = 64
MAX_CANDIDATOS = 100
MAX_CARACTERES = 20000


def _con_contenido(texto: str) -> str:
    if not texto.strip():
        raise ValueError("El texto no puede estar vacío")
    return texto


Texto = Annotated[str, Field(min_length=1, max_length=MAX_CARACTERES), AfterValidator(_con_contenido)]


class SolicitudTextos(BaseModel):
    textos: list[Texto] = Field(min_length=1, max_length=MAX_TEXTOS)


class SolicitudReranking(BaseModel):
    consulta: Texto
    candidatos: list[Texto] = Field(min_length=1, max_length=MAX_CANDIDATOS)


class RespuestaEmbeddings(BaseModel):
    dimension: int
    vectores: list[list[float]]


class RespuestaReranking(BaseModel):
    puntajes: list[float]


class RespuestaTokens(BaseModel):
    tokens: list[int]


def crear_app(motor: Motor | None = None, concurrencia: int | None = None) -> FastAPI:
    """Con motor=None se carga el motor indicado por MODELOS_MOTOR al iniciar el servicio."""

    @asynccontextmanager
    async def ciclo_de_vida(app: FastAPI):
        if getattr(app.state, "motor", None) is None:
            config = cargar_config()
            app.state.motor = await run_in_threadpool(crear_motor, config)
            app.state.semaforo = asyncio.Semaphore(config.concurrencia)
        yield

    app = FastAPI(title="CDSS Anemia Infantil · Modelos locales", version="0.1.0", lifespan=ciclo_de_vida)
    if motor is not None:
        app.state.motor = motor
        app.state.semaforo = asyncio.Semaphore(concurrencia or 1)

    async def _inferir(request: Request, funcion, *argumentos):
        async with request.app.state.semaforo:
            return await run_in_threadpool(funcion, *argumentos)

    @app.get("/salud")
    def salud(request: Request) -> dict:
        return {"estado": "ok", **request.app.state.motor.info()}

    @app.post("/embeddings", response_model=RespuestaEmbeddings)
    async def embeddings(solicitud: SolicitudTextos, request: Request) -> RespuestaEmbeddings:
        vectores = await _inferir(request, request.app.state.motor.embeddings, solicitud.textos)
        return RespuestaEmbeddings(dimension=len(vectores[0]), vectores=vectores)

    @app.post("/reranquear", response_model=RespuestaReranking)
    async def reranquear(solicitud: SolicitudReranking, request: Request) -> RespuestaReranking:
        puntajes = await _inferir(request, request.app.state.motor.reranquear,
                                  solicitud.consulta, solicitud.candidatos)
        return RespuestaReranking(puntajes=puntajes)

    @app.post("/tokens", response_model=RespuestaTokens)
    async def tokens(solicitud: SolicitudTextos, request: Request) -> RespuestaTokens:
        return RespuestaTokens(tokens=await run_in_threadpool(request.app.state.motor.contar_tokens, solicitud.textos))

    return app


app = crear_app()
