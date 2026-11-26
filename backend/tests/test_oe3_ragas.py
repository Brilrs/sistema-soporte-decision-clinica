"""OE3: métricas de RAGAS 0.4.4 a través del juez (con el juez falso, sin red). Solo corre donde
RAGAS está instalado (imagen de evaluación); en el resto se salta."""
import json
import os

import pytest

ragas = pytest.importorskip("ragas")

from app.evaluacion import ragas_metricas  # noqa: E402
from app.evaluacion.juez import ConfiguracionJuez, Juez, JuezFalso  # noqa: E402

CONTEXTOS = ["Se indica suplemento de hierro a una dosis de 3mg/kg/día, durante 6 meses continuos (Tabla N°17).",
             "| 6 meses a 35 meses | Al mes de iniciado tratamiento. Al segundo, tercer y sexto mes |"]


def test_version_y_telemetria_apagada():
    from importlib.metadata import version
    assert version("ragas") == "0.4.4"
    assert os.environ["RAGAS_DO_NOT_TRACK"] == "true" and ragas_metricas.telemetria_apagada()


def test_las_cuatro_metricas_pasan_por_el_juez(tmp_path):
    juez = Juez(JuezFalso(), ConfiguracionJuez(k=1), tmp_path / "cache", tmp_path / "llamadas.jsonl", {"OE3-P02"})
    r = ragas_metricas.calcular(juez, "OE3-P02", 1, "¿Qué dosis le corresponde?",
                                "Dar 3 mg/kg/día durante 6 meses continuos.", CONTEXTOS,
                                "El tratamiento es con 3 mg/kg/día durante 6 meses continuos.")
    assert r["errores"] == {}, r["errores"]
    assert set(r["valores"]) == {"context_relevance", "faithfulness", "context_precision", "context_recall"}
    assert all(v is not None and 0.0 <= v <= 1.0 for v in r["valores"].values()), r["valores"]
    tareas = {json.loads(x)["tarea"] for x in (tmp_path / "llamadas.jsonl").read_text(encoding="utf-8").splitlines()}
    assert {t.split(":")[0] for t in tareas} == {"ragas"}
    assert not any("AnswerRelevance" in t or "answer_relevancy" in t for t in tareas)
    # Context Precision: una llamada por fragmento; Faithfulness: dos; Relevancia: dos; Recall: una
    nuevas = [json.loads(x) for x in (tmp_path / "llamadas.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(nuevas) == 2 + 2 + len(CONTEXTOS) + 1
    # La segunda vez todo sale de la caché y da lo mismo
    otra = ragas_metricas.calcular(juez, "OE3-P02", 1, "¿Qué dosis le corresponde?",
                                   "Dar 3 mg/kg/día durante 6 meses continuos.", CONTEXTOS,
                                   "El tratamiento es con 3 mg/kg/día durante 6 meses continuos.")
    assert otra["valores"] == r["valores"]
    assert juez.resumen()["desde_cache"] == len(nuevas)


def test_sin_referencia_o_sin_contextos(tmp_path):
    juez = Juez(JuezFalso(), ConfiguracionJuez(k=1), tmp_path)
    r = ragas_metricas.calcular(juez, "OE3-P07", 1, "¿?", "Evidencia insuficiente.", CONTEXTOS, None)
    assert r["valores"]["context_precision"] is None and r["valores"]["context_recall"] is None
    assert r["valores"]["context_relevance"] is not None
    r = ragas_metricas.calcular(juez, "OE3-P07", 1, "¿?", "x", [], "ref")
    assert all(v is None for v in r["valores"].values()) and "todas" in r["errores"]


def test_un_juez_que_no_responde_deja_la_metrica_sin_valor(tmp_path):
    juez = Juez(JuezFalso(invalidas=100), ConfiguracionJuez(k=1), tmp_path)
    r = ragas_metricas.calcular(juez, "OE3-P02", 1, "¿?", "Dar hierro.", CONTEXTOS, "ref")
    assert all(v is None for v in r["valores"].values())
    assert set(r["errores"]) == {"context_relevance", "faithfulness", "context_precision", "context_recall"}
    # ContextRelevance no repite por su cuenta: 2 juicios, cada uno con su único reintento del juez
    relevancia = [x for x in juez.llamadas if x.tarea == "ragas:ContextRelevanceOutput"]
    assert len(relevancia) == 2 and all(x.intentos == 2 for x in relevancia)


def test_un_fallo_parcial_del_juez_no_deja_un_promedio_a_medias(tmp_path):
    """ContextRelevance promedia los juicios que le quedan; si uno falló, la métrica queda sin valor."""
    juez = Juez(JuezFalso(invalidas=2), ConfiguracionJuez(k=1), tmp_path)
    r = ragas_metricas.calcular(juez, "OE3-P02", 1, "¿?", "Dar hierro.", CONTEXTOS, None)
    assert r["valores"]["context_relevance"] is None
    assert "no devolvió un JSON válido" in r["errores"]["context_relevance"]
    assert r["valores"]["faithfulness"] is not None
