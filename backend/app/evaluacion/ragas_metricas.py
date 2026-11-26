"""Métricas de RAGAS 0.4.4 (docs/diseno_evaluacion_oe3.md, sección 2): ContextRelevance,
Faithfulness, ContextPrecisionWithReference y ContextRecall. Sin Answer Relevancy (necesita
embeddings y no está en la Tabla 2 del OE2).

Cada llamada de RAGAS al modelo pasa por AdaptadorRagas, que la entrega al Juez de juez.py: así
usa la misma caché, el mismo registro de tokens y costo, el mismo cliente (falso en el ensayo) y
ninguna llamada sale por otro camino. La telemetría de RAGAS queda apagada antes de importarla.

Solo se importa en la imagen de evaluación (requirements-evaluacion.txt); el resto del job no
depende de RAGAS."""
from __future__ import annotations

import asyncio
import math
import os

os.environ["RAGAS_DO_NOT_TRACK"] = "true"

from ragas.llms.base import InstructorBaseRagasLLM  # noqa: E402
from ragas.metrics.collections import (  # noqa: E402
    ContextPrecisionWithReference,
    ContextRecall,
    ContextRelevance,
    Faithfulness,
)

from app.evaluacion import prompts_juez as pj  # noqa: E402
from app.evaluacion.juez import Juez  # noqa: E402

METRICAS = ("context_relevance", "faithfulness", "context_precision", "context_recall")


class SinRespuestaJuez(RuntimeError):
    """El juez no devolvió un JSON válido para RAGAS."""


class AdaptadorRagas(InstructorBaseRagasLLM):
    def __init__(self, juez: Juez, id_caso: str, repeticion: int):
        self.juez, self.id_caso, self.repeticion = juez, id_caso, repeticion

    async def agenerate(self, prompt, response_model):
        return self.generate(prompt, response_model)

    def generate(self, prompt, response_model):
        datos = self.juez.llamar(self.id_caso, f"ragas:{response_model.__name__}", pj.SISTEMA_RAGAS, prompt,
                                 response_model.model_json_schema(), self.repeticion)
        if datos is None:
            raise SinRespuestaJuez(response_model.__name__)
        return response_model.model_validate(datos)


def telemetria_apagada() -> bool:
    from ragas._analytics import do_not_track
    return do_not_track()


def calcular(juez: Juez, id_caso: str, repeticion: int, consulta: str, respuesta: str, contextos: list[str],
             referencia: str | None) -> dict:
    """Valor de cada métrica (None si no aplica) y los errores. Context Precision y Context Recall
    solo con referencia; ninguna sin contextos; Faithfulness solo con respuesta."""
    if not telemetria_apagada():
        raise RuntimeError("La telemetría de RAGAS debe estar apagada (RAGAS_DO_NOT_TRACK=true)")
    llm = AdaptadorRagas(juez, id_caso, repeticion)
    valores: dict[str, float | None] = {m: None for m in METRICAS}
    errores: dict[str, str] = {}
    if not contextos:
        return {"valores": valores, "errores": {"todas": "sin fragmentos enviados"}}

    async def una(nombre, corrutina):
        # ContextRelevance atrapa los errores del juez y promedia lo que le queda (o da NaN): si el
        # juez falló en cualquier llamada de la métrica, la métrica queda sin valor.
        fallidas_antes = sum(not x.ok for x in juez.llamadas)
        try:
            r = await corrutina
            valor = None if r.value is None else float(r.value)
        except Exception as e:  # noqa: BLE001 (queda registrado; la métrica no tiene valor)
            errores[nombre] = f"{type(e).__name__}: {e}"[:300]
            return
        if sum(not x.ok for x in juez.llamadas) > fallidas_antes:
            errores[nombre] = "el juez no devolvió un JSON válido en alguna llamada"
        elif valor is None or math.isnan(valor):
            errores[nombre] = "RAGAS no devolvió un valor (NaN)"
        else:
            valores[nombre] = valor

    async def todas():
        # max_retries=1: el juez ya reintenta una vez; con el valor por omisión (5) RAGAS repetiría
        # cada llamada fallida hasta 5 veces.
        await una("context_relevance", ContextRelevance(llm=llm, max_retries=1).ascore(
            user_input=consulta, retrieved_contexts=contextos))
        if respuesta:
            await una("faithfulness", Faithfulness(llm=llm).ascore(user_input=consulta, response=respuesta,
                                                                    retrieved_contexts=contextos))
        if referencia:
            await una("context_precision", ContextPrecisionWithReference(llm=llm).ascore(
                user_input=consulta, reference=referencia, retrieved_contexts=contextos))
            await una("context_recall", ContextRecall(llm=llm).ascore(
                user_input=consulta, retrieved_contexts=contextos, reference=referencia))

    asyncio.run(todas())
    return {"valores": valores, "errores": errores}
