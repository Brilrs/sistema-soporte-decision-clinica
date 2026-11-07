"""Servicio interno de modelos locales (sin puerto publicado).

Expone bge-m3 y bge-reranker-v2-m3 al backend y al indexador por HTTP. Los modelos
se cargan una sola vez al iniciar y después se ejecuta una inferencia de
calentamiento de cada uno; el servicio no atiende peticiones (y /salud no responde,
de modo que Docker no lo marca healthy) hasta que ambas terminan. Un semáforo limita
las inferencias simultáneas para no exceder la memoria y los núcleos asignados al
contenedor; el conteo de tokens solo usa el tokenizador y no pasa por el semáforo."""
import asyncio
import logging
import time
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
MIN_LONGITUD_RERANKER = 64
CANDIDATOS_CALENTAMIENTO = 8
_TEXTO_CALENTAMIENTO = ("Lactante de 9 meses con hemoglobina de 10,1 g/dL que vive a 3400 metros sobre el nivel del "
                        "mar; recibe sulfato ferroso en gotas desde los 6 meses y la madre refiere estreñimiento. ")
log = logging.getLogger("uvicorn.error")


def calentar(motor: Motor, longitud: int) -> dict:
    """Primera inferencia de cada modelo, con un texto sintético de varios cientos de
    tokens y la longitud del reranker usada en producción. Devuelve los tiempos en ms."""
    inicio = time.perf_counter()
    motor.embeddings([_TEXTO_CALENTAMIENTO * 4])
    embedding = time.perf_counter()
    motor.reranquear(_TEXTO_CALENTAMIENTO, [_TEXTO_CALENTAMIENTO * 8] * CANDIDATOS_CALENTAMIENTO, longitud)
    fin = time.perf_counter()
    return {"embedding_ms": round((embedding - inicio) * 1000, 1), "reranker_ms": round((fin - embedding) * 1000, 1)}


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
    max_longitud: int | None = Field(None, ge=MIN_LONGITUD_RERANKER,
                                     description="Tokens por par consulta y candidato; no supera el máximo configurado")


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
        config = cargar_config()
        inicio = time.perf_counter()
        if getattr(app.state, "motor", None) is None:
            app.state.motor = await run_in_threadpool(crear_motor, config)
            app.state.semaforo = asyncio.Semaphore(config.concurrencia)
        carga = time.perf_counter()
        tiempos = await run_in_threadpool(calentar, app.state.motor, config.longitud_calentamiento)
        app.state.arranque = {"carga_ms": round((carga - inicio) * 1000, 1), "calentamiento_ms": tiempos,
                              "total_ms": round((time.perf_counter() - inicio) * 1000, 1)}
        log.info("Modelos listos: %s", app.state.arranque)
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
        return {"estado": "ok", **request.app.state.motor.info(), "arranque": getattr(request.app.state, "arranque", None)}

    @app.post("/embeddings", response_model=RespuestaEmbeddings)
    async def embeddings(solicitud: SolicitudTextos, request: Request) -> RespuestaEmbeddings:
        vectores = await _inferir(request, request.app.state.motor.embeddings, solicitud.textos)
        return RespuestaEmbeddings(dimension=len(vectores[0]), vectores=vectores)

    @app.post("/reranquear", response_model=RespuestaReranking)
    async def reranquear(solicitud: SolicitudReranking, request: Request) -> RespuestaReranking:
        puntajes = await _inferir(request, request.app.state.motor.reranquear,
                                  solicitud.consulta, solicitud.candidatos, solicitud.max_longitud)
        return RespuestaReranking(puntajes=puntajes)

    @app.post("/tokens", response_model=RespuestaTokens)
    async def tokens(solicitud: SolicitudTextos, request: Request) -> RespuestaTokens:
        return RespuestaTokens(tokens=await run_in_threadpool(request.app.state.motor.contar_tokens, solicitud.textos))

    return app


app = crear_app()
