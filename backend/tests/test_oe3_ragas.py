"""OE3: métricas de RAGAS 0.4.4 a través del juez (con el juez falso, sin red). Solo corre donde
RAGAS está instalado (imagen de evaluación); en el resto se salta."""
import json
import os

import pytest

ragas = pytest.importorskip("ragas")

from app.evaluacion import ragas_metricas  # noqa: E402
from app.evaluacion.juez import (CLAVES_ADMITIDAS_API, ConfiguracionJuez, Juez, JuezAnthropic,  # noqa: E402
                                 JuezFalso, esquema_para_api, problemas_esquema_api)

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


MODELOS_RAGAS = {"ragas:StatementGeneratorOutput", "ragas:NLIStatementOutput", "ragas:ContextPrecisionOutput",
                 "ragas:ContextRecallOutput", "ragas:ContextRelevanceOutput"}


def _objetos(s):
    if isinstance(s, dict):
        if s.get("type") == "object" or "properties" in s:
            yield s
        for k, v in s.items():
            if k not in ("enum", "required", "const"):
                yield from _objetos(v)
    elif isinstance(s, list):
        for v in s:
            yield from _objetos(v)


def _claves(s):
    if not isinstance(s, dict):
        return set()
    hijos = list((s.get("properties") or {}).values()) + list((s.get("$defs") or {}).values())
    hijos += [s["items"]] if isinstance(s.get("items"), dict) else []
    hijos += [v for k in ("anyOf", "allOf", "oneOf") for v in s.get(k) or []]
    return set(s).union(*(_claves(h) for h in hijos))


class _JuezQueAnota(JuezFalso):
    def generar(self, tarea, sistema, contenido, esquema, config):
        self.esquemas = getattr(self, "esquemas", {})
        self.esquemas.setdefault(tarea, esquema)
        return super().generar(tarea, sistema, contenido, esquema, config)


def _esquemas_reales(tmp_path) -> dict:
    """Los esquemas que RAGAS pide de verdad (response_model.model_json_schema()) en las cuatro métricas."""
    cliente = _JuezQueAnota()
    ragas_metricas.calcular(Juez(cliente, ConfiguracionJuez(k=1), tmp_path), "OE3-P02", 1, "¿Qué dosis?",
                            "Dar 3 mg/kg/día durante 6 meses continuos.", CONTEXTOS, "3 mg/kg/día durante 6 meses.")
    return cliente.esquemas


def test_los_cinco_esquemas_de_ragas_quedan_admitidos_por_la_api(tmp_path):
    esquemas = _esquemas_reales(tmp_path)
    assert set(esquemas) == MODELOS_RAGAS
    for tarea, original in esquemas.items():
        # Sin normalizar, la API los rechaza (el 400 de la prueba real)
        assert any("additionalProperties" in p for p in problemas_esquema_api(original)), tarea
        normalizado = esquema_para_api(original)
        objetos = list(_objetos(normalizado))
        assert objetos and all(o.get("additionalProperties") is False for o in objetos), tarea
        assert _claves(normalizado) <= CLAVES_ADMITIDAS_API, (tarea, _claves(normalizado) - CLAVES_ADMITIDAS_API)
        assert problemas_esquema_api(normalizado) == [], tarea
        # Los mismos campos y obligatorios en cada objeto
        assert [sorted(o.get("properties", {})) for o in _objetos(original)] ==             [sorted(o.get("properties", {})) for o in objetos], tarea


class _AnthropicSimulado:
    """anthropic.Anthropic sin red: valida el esquema recibido y responde con una instancia mínima."""
    llamadas: list = []

    def __init__(self, api_key, max_retries):
        self.messages = self

    def create(self, **kw):
        import random
        from types import SimpleNamespace
        from app.evaluacion.juez import _llenar
        esquema = kw["output_config"]["format"]["schema"]
        assert problemas_esquema_api(esquema) == []
        _AnthropicSimulado.llamadas.append(kw)
        texto = json.dumps(_llenar(esquema, esquema, random.Random(len(_AnthropicSimulado.llamadas))))
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=texto)], model=kw["model"],
                               usage=SimpleNamespace(input_tokens=10, output_tokens=5))


def test_ragas_por_el_cliente_real_simulado_envia_solo_esquemas_normalizados(tmp_path, monkeypatch):
    import anthropic
    monkeypatch.setattr(anthropic, "Anthropic", _AnthropicSimulado)
    monkeypatch.setenv("CDSS_ENTORNO", "desarrollo")
    _AnthropicSimulado.llamadas = []
    cliente = JuezAnthropic("claude-sonnet-5-5", confirmo_datos_sinteticos=True, api_key="clave-falsa")
    juez = Juez(cliente, ConfiguracionJuez(modelo="claude-sonnet-5-5", k=1), tmp_path / "cache")
    esquemas_de_la_clave = {}
    clave_original = juez.clave

    def clave_que_anota(tarea, sistema, contenido, esquema, repeticion):
        esquemas_de_la_clave.setdefault(tarea, esquema)
        return clave_original(tarea, sistema, contenido, esquema, repeticion)

    monkeypatch.setattr(juez, "clave", clave_que_anota)
    r = ragas_metricas.calcular(juez, "OE3-P02", 1, "¿Qué dosis?", "Dar 3 mg/kg/día durante 6 meses continuos.",
                                CONTEXTOS, "3 mg/kg/día durante 6 meses.")
    assert r["errores"] == {}, r["errores"]
    assert {x.tarea for x in juez.llamadas} == MODELOS_RAGAS and all(x.ok for x in juez.llamadas)
    assert len(_AnthropicSimulado.llamadas) == len(juez.llamadas)
    # La clave de caché usa el esquema original de RAGAS (el mismo que recibe el juez falso), no el
    # normalizado que va a la API
    assert esquemas_de_la_clave == _esquemas_reales(tmp_path / "falso")
    assert all("additionalProperties" not in e for e in esquemas_de_la_clave.values())
    enviados = [kw["output_config"]["format"]["schema"] for kw in _AnthropicSimulado.llamadas]
    assert all(e["additionalProperties"] is False for e in enviados)
    assert {json.dumps(esquema_para_api(e), sort_keys=True) for e in esquemas_de_la_clave.values()} ==         {json.dumps(e, sort_keys=True) for e in enviados}

