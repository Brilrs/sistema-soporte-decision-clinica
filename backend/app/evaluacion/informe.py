"""Informe reproducible (docs/diseno_evaluacion_oe3.md, sección 7): tablas en Markdown, JSON con
todo el detalle, intervalos de Wilson para las proporciones y bootstrap por casos para las medias,
desglose por tipo de consulta, por origen, con o sin inglés y por cuadrante, costos y datos de
reproducibilidad."""
from __future__ import annotations

import math
import random
import statistics
import subprocess
import sys
from collections import Counter

from app.evaluacion import cue

Z95 = 1.959964
REMUESTREOS = 10_000
SEMILLA_BOOTSTRAP = 20261126
ROTULO_ENSAYO = "ENSAYO CON CLIENTE FALSO: los números no tienen valor"
METRICAS_MEDIA = ("cue_b", "cue_a", "cue_citas", "adherencia", "context_relevance", "faithfulness",
                  "context_precision", "context_recall", "cobertura_obligatorios")
NOMBRES = {
    "estado_coincide": "Estado igual al esperado", "exito_recuperacion": "Éxito de recuperación",
    "correcta": "Respuesta correcta", "cue_b": "CUE del OE2 (B, cifra principal)",
    "cue_a": "CUE variante A (todas las afirmaciones)", "cue_citas": "CUE sin juez (citados / enviados)",
    "adherencia": "Adherencia (juez, umbral 0,7)", "context_relevance": "Relevancia del contexto (RAGAS)",
    "faithfulness": "Faithfulness (RAGAS)", "context_precision": "Context Precision (RAGAS)",
    "context_recall": "Context Recall (RAGAS)", "cobertura_obligatorios": "Cobertura de criterios obligatorios",
}


def wilson(aciertos: int, n: int, z: float = Z95) -> tuple[float, float] | None:
    if n == 0:
        return None
    p = aciertos / n
    centro = (p + z * z / (2 * n)) / (1 + z * z / n)
    medio = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return max(0.0, centro - medio), min(1.0, centro + medio)


def bootstrap_media(valores: list[float], remuestreos: int = REMUESTREOS,
                    semilla: int = SEMILLA_BOOTSTRAP) -> tuple[float, float] | None:
    """Intervalo percentil al 95 % de la media, remuestreando casos con una semilla fija."""
    if not valores:
        return None
    if len(valores) == 1:
        return valores[0], valores[0]
    azar = random.Random(semilla)
    n = len(valores)
    medias = sorted(statistics.fmean(azar.choices(valores, k=n)) for _ in range(remuestreos))
    return medias[int(0.025 * remuestreos)], medias[min(remuestreos - 1, int(0.975 * remuestreos))]


def _valor(r: dict, clave: str):
    det, ag = r["determinista"], r["agregado"]
    if clave in det:
        return det[clave]
    if clave in ag:
        return ag[clave]
    return ag["ragas"].get(clave)


def proporcion(resultados: list[dict], clave: str, filtro=lambda r: True) -> dict:
    valores = [_valor(r, clave) for r in resultados if filtro(r)]
    valores = [v for v in valores if v is not None]
    k = sum(bool(v) for v in valores)
    ic = wilson(k, len(valores))
    return {"n": len(valores), "aciertos": k, "proporcion": k / len(valores) if valores else None,
            "ic95": ic, "metodo": "Wilson"}


def media(resultados: list[dict], clave: str) -> dict:
    valores = [float(v) for v in (_valor(r, clave) for r in resultados) if v is not None]
    return {"n": len(valores), "media": statistics.fmean(valores) if valores else None,
            "ic95": bootstrap_media(valores), "metodo": f"bootstrap percentil ({REMUESTREOS} remuestreos)"}


def _con_generacion(r: dict) -> bool:
    return r["determinista"]["estado"] in cue.CON_GENERACION


def _con_criterios(r: dict) -> bool:
    return not r["determinista"]["sin_criterios"]


def resumen(resultados: list[dict]) -> dict:
    return {
        "casos": len(resultados),
        "proporciones": {
            "estado_coincide": proporcion(resultados, "estado_coincide"),
            "exito_recuperacion": proporcion(resultados, "exito_recuperacion",
                                             lambda r: _con_generacion(r) and _con_criterios(r)),
            "correcta": proporcion(resultados, "correcta", _con_generacion),
        },
        "medias": {m: media([r for r in resultados if _con_generacion(r)], m) for m in METRICAS_MEDIA},
        "cuadrantes": dict(Counter(r["agregado"]["cuadrante"] for r in resultados)),
        "estabilidad_juez": {m: _media_simple(r["agregado"]["desviacion"].get(m) for r in resultados)
                             for m in ("cue_b", "adherencia", "context_relevance", "faithfulness",
                                       "context_precision", "context_recall")},
        "sin_enviados": sum(1 for r in resultados if _con_generacion(r) and r["determinista"]["enviados"] == 0),
        "exito_con_equivalencia_pendiente": sum(1 for r in resultados
                                                if r["determinista"]["depende_de_equivalencia_pendiente"]),
        "perdidos_en_seleccion": sum(1 for r in resultados if r["determinista"]["perdido_en_seleccion"]),
    }


def _media_simple(valores):
    v = [x for x in valores if x is not None]
    return statistics.fmean(v) if v else None


def desgloses(resultados: list[dict]) -> dict:
    grupos: dict[str, dict[str, list[dict]]] = {"tipo": {}, "origen": {}, "ingles": {}, "cuadrante": {}}
    for r in resultados:
        for t in r["tipos"]:
            grupos["tipo"].setdefault(t, []).append(r)
        grupos["origen"].setdefault(r["origen"], []).append(r)
        grupos["ingles"].setdefault("con fragmento en inglés" if r["determinista"]["con_ingles"]
                                    else "sin fragmento en inglés", []).append(r)
        grupos["cuadrante"].setdefault(r["agregado"]["cuadrante"], []).append(r)
    salida = {}
    for eje, por_valor in grupos.items():
        salida[eje] = {}
        for valor, filas in sorted(por_valor.items()):
            salida[eje][valor] = {
                "n": len(filas),
                "estado_coincide": proporcion(filas, "estado_coincide"),
                "exito_recuperacion": proporcion(filas, "exito_recuperacion",
                                                 lambda r: _con_generacion(r) and _con_criterios(r)),
                "correcta": proporcion(filas, "correcta", _con_generacion),
                "cue_b": media([r for r in filas if _con_generacion(r)], "cue_b")["media"],
                "adherencia": media([r for r in filas if _con_generacion(r)], "adherencia")["media"],
            }
    return salida


def costos(extracciones: dict[str, dict], resumen_juez: dict) -> dict:
    intentos = [i for e in extracciones.values() for i in e["intentos"]]
    sistema = [i["costo_usd"] for i in intentos if i.get("costo_usd") is not None]
    # Con el cliente falso el sistema igual calcula costo_usd con los precios de los parámetros sobre
    # tokens inventados: es un costo simulado, no un gasto.
    simulado = any(i.get("modelo_llm") == "modelo-falso" for i in intentos)
    return {"sistema": {"intentos": len(intentos), "costo_usd": round(sum(sistema), 6), "simulado": simulado,
                        "tokens_entrada": sum(i.get("tokens_entrada") or 0 for i in intentos),
                        "tokens_salida": sum(i.get("tokens_salida") or 0 for i in intentos),
                        "modelos": sorted({i.get("modelo_llm") or "(sin llamada)" for i in intentos})},
            "juez": resumen_juez}


def pip_freeze() -> list[str]:
    try:
        r = subprocess.run([sys.executable, "-m", "pip", "freeze"], capture_output=True, text=True, timeout=120)
        return r.stdout.splitlines()
    except (OSError, subprocess.SubprocessError) as e:
        return [f"(no disponible: {type(e).__name__})"]


# ---------------------------------------------------------------------------
# Markdown
# ---------------------------------------------------------------------------
def _pct(v) -> str:
    return "" if v is None else f"{100 * v:.1f} %"


def _num(v) -> str:
    return "" if v is None else f"{v:.3f}"


def _ic(ic, pct: bool) -> str:
    if ic is None:
        return ""
    f = _pct if pct else _num
    return f"{f(ic[0])} a {f(ic[1])}"


def markdown(datos: dict) -> str:
    r, meta = datos["resumen"], datos["reproducibilidad"]
    lineas = []
    if datos["ensayo"]:
        lineas += [f"# {ROTULO_ENSAYO}", "", f"> **{ROTULO_ENSAYO}.** Este informe prueba el job de punta a "
                   "punta con el cliente falso del modelo de lenguaje y el juez falso. No es una medición del "
                   "sistema y no se cita en la tesis.", ""]
    lineas += [f"# Informe de la evaluación del OE3 ({meta['grupo']})", "",
               f"Casos: {r['casos']}. Juez: `{meta['juez']['modelo']}`, k = {meta['juez']['k']}. "
               f"Huella del conjunto: `{meta['conjunto']['huella_conjunto_sha256']}`.", "",
               "## Resultados principales", "",
               "| Indicador | n | Valor | IC 95 % | Método |", "| --- | --- | --- | --- | --- |"]
    for clave, p in r["proporciones"].items():
        lineas.append(f"| {NOMBRES[clave]} | {p['n']} | {_pct(p['proporcion'])} | {_ic(p['ic95'], True)} | Wilson |")
    for clave, m in r["medias"].items():
        lineas.append(f"| {NOMBRES[clave]} | {m['n']} | {_num(m['media'])} | {_ic(m['ic95'], False)} | bootstrap |")
    lineas += ["", "Las proporciones de recuperación y corrección cuentan solo los casos con generación "
               "(VERIFICADA o EVIDENCIA_INSUFICIENTE); el éxito de recuperación, además, solo los casos con "
               "criterios. Consultas con generación y sin fragmentos enviados (sin CUE): "
               f"{r['sin_enviados']}. Éxitos que dependen de una equivalencia pendiente de la ficha del CRED: "
               f"{r['exito_con_equivalencia_pendiente']}. Casos con el criterio entre los candidatos pero no "
               f"entre los enviados: {r['perdidos_en_seleccion']}.", "",
               "## Cuadrantes (RAG-X) y categoría propia", "", "| Categoría | Casos |", "| --- | --- |"]
    for c in cue.CATEGORIAS:
        lineas.append(f"| {c} | {r['cuadrantes'].get(c, 0)} |")
    lineas += ["", "Los cuatro primeros son los cuadrantes del artículo RAG-X. "
               f"`{cue.FUERA_CUADRANTES}` es una categoría propia del proyecto (recuperación fallida, respuesta "
               "incorrecta y adherencia de 0,7 o más), que el artículo no define. `no_aplica`: sin generación.", "",
               "## Estabilidad del juez (desviación media entre repeticiones)", "",
               "| Métrica | Desviación media |", "| --- | --- |"]
    for m, v in r["estabilidad_juez"].items():
        lineas.append(f"| {NOMBRES.get(m, m)} | {_num(v)} |")
    for eje, titulo in (("tipo", "tipo de consulta"), ("origen", "origen"), ("ingles", "idioma de los fragmentos"),
                        ("cuadrante", "cuadrante")):
        lineas += ["", f"## Desglose por {titulo}", "",
                   "| Grupo | n | Estado igual | Éxito de recuperación | Correcta | CUE B | Adherencia |",
                   "| --- | --- | --- | --- | --- | --- | --- |"]
        for valor, d in datos["desgloses"][eje].items():
            lineas.append(f"| {valor} | {d['n']} | {_pct(d['estado_coincide']['proporcion'])} | "
                          f"{_pct(d['exito_recuperacion']['proporcion'])} | {_pct(d['correcta']['proporcion'])} | "
                          f"{_num(d['cue_b'])} | {_num(d['adherencia'])} |")
    lineas += ["", "## Por caso", "",
               "| Caso | Estado | Esperado | Clasificación | Enviados | Recuperación | Cobertura | CUE B | CUE citas "
               "| Adherencia | Correcta | Cuadrante |",
               "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for x in datos["casos"]:
        d, a = x["determinista"], x["agregado"]
        lineas.append(f"| {x['id_caso']} | {d['estado']} | {x['estado_esperado']} | {d['clasificacion'] or ''} | "
                      f"{d['enviados']} | {'sí' if d['exito_recuperacion'] else 'no'} | "
                      f"{_pct(d['cobertura_obligatorios'])} | {_num(a['cue_b'])} | {_num(d['cue_citas'])} | "
                      f"{_num(a['adherencia'])} | {'' if a['correcta'] is None else ('sí' if a['correcta'] else 'no')} "
                      f"| {a['cuadrante']} |")
    c = datos["costos"]
    lineas += ["", "## Costos", "", "| Componente | Llamadas o intentos | Tokens de entrada | Tokens de salida | "
               "Costo (USD) |", "| --- | --- | --- | --- | --- |",
               f"| Sistema ({', '.join(c['sistema']['modelos'])}) | {c['sistema']['intentos']} | "
               f"{c['sistema']['tokens_entrada']} | {c['sistema']['tokens_salida']} | {c['sistema']['costo_usd']}"
               f"{' (simulado: cliente falso)' if c['sistema'].get('simulado') else ''} |",
               f"| Juez ({c['juez']['modelo']}; {c['juez']['desde_cache']} desde caché, {c['juez']['fallidas']} "
               f"fallidas) | {c['juez']['llamadas']} | {c['juez']['tokens_entrada']} | {c['juez']['tokens_salida']} | "
               f"{c['juez']['costo_usd']} |", "",
               "## Reproducibilidad", "",
               f"- Etiqueta o commit de git: `{meta['git']}`",
               f"- Huella de la configuración al ejecutar: `{meta['huella_configuracion_inicio']}`",
               f"- Huella de la configuración al informar: `{meta['huella_configuracion_fin']}` "
               f"({'igual' if meta['huella_configuracion_inicio'] == meta['huella_configuracion_fin'] else 'DISTINTA'})",
               f"- Conjunto: `{meta['conjunto']['grupo']}`, {meta['conjunto']['casos']} casos, SHA-256 "
               f"`{meta['conjunto']['huella_conjunto_sha256']}`; esquema `{meta['conjunto']['huella_esquema_sha256']}`",
               f"- Cliente del modelo de lenguaje: `{meta['llm']}`",
               f"- Juez: `{meta['juez']['modelo']}`, razonamiento `{meta['juez']['razonamiento']}`, esfuerzo "
               f"`{meta['juez']['esfuerzo']}`, máximo {meta['juez']['max_tokens']} tokens, sin temperatura, k = "
               f"{meta['juez']['k']}",
               f"- Prompts propios (versión {meta['prompts']['version']}): "
               + ", ".join(f"{k} `{v[:12]}`" for k, v in meta["prompts"]["sha256"].items()),
               f"- RAGAS: {meta['ragas']}; telemetría apagada: {meta['ragas_sin_telemetria']}",
               f"- Paquetes: {len(meta['pip_freeze'])} en `pip freeze` (lista completa en el JSON)",
               f"- Bootstrap: {REMUESTREOS} remuestreos, semilla {SEMILLA_BOOTSTRAP}",
               f"- Generado: {meta['generado']}"]
    return "\n".join(lineas) + "\n"
