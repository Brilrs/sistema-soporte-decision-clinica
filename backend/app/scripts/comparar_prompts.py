"""Comparación textual de las respuestas de dos versiones del prompt, a partir de una corrida
de medir_consulta --versiones-prompt (parte D2). No llama a la API: lee de la base, con
cdss_generacion, la respuesta del intento aprobado (intento_generacion.respuesta_borrador)
de cada consulta de la corrida.

Por cada caso verificado en ambas versiones: resumen, pasos (tipo y texto), advertencias,
citas y tokens de salida de cada versión, una debajo de la otra, y una lista automática de
diferencias (solo datos):
- dosis, cifras y frecuencias o plazos presentes en una versión y no en la otra, tomados del
  texto redactado por el modelo (resumen, pasos, advertencias y factores), no de los
  extractos citados; las dosis usan la regla del control 6.2;
- pasos sin un paso de la otra versión del mismo tipo y con las mismas etiquetas citadas;
- advertencias que comparten menos del 50 % de sus palabras con cada advertencia de la otra
  versión;
- etiquetas citadas en una sola versión.

Uso (en el contenedor backend; ver docs/mediciones_sprint2.md):
    python -m app.scripts.comparar_prompts [--corrida d_consulta_real_prompts_v1_1_v1_2.json]
        [--versiones v1.1,v1.2] [--salida comparacion_prompts_v1_1_v1_2.md]"""
import argparse
import json
import os
import re
import sys
import unicodedata
from pathlib import Path

from sqlalchemy import text

from app.rag.verificacion import cifras, dosis

_FRECUENCIAS = re.compile(
    r"\b(?:diari[oa]s?|al d[ií]a|por d[ií]a|cada \d+(?:[.,]\d+)? ?(?:d[ií]as?|semanas?|meses|horas?)|"
    r"(?:durante|por) \d+(?:[.,]\d+)? ?(?:d[ií]as?|semanas?|meses)|a los? \d+(?:[.,]\d+)? ?(?:d[ií]as?|semanas?|meses)|"
    r"al mes|\d+ veces|una vez|mensual(?:es)?|semanal(?:es)?|trimestral(?:es)?|"
    r"daily|per day|weekly|once|twice|every \d+ ?(?:days?|weeks?|months?)|for \d+ ?(?:days?|weeks?|months?))",
    re.IGNORECASE)
_PALABRA = re.compile(r"[^\W\d_]{4,}")
UMBRAL_ADVERTENCIA = 0.5


def norm(t: str) -> str:
    t = unicodedata.normalize("NFD", t.lower())
    return " ".join("".join(c for c in t if unicodedata.category(c) != "Mn").split())


def redactado(r: dict) -> str:
    """Texto que escribe el modelo (sin los extractos citados)."""
    return "\n".join([r["resumen"], *[p["texto"] for p in r["recomendacion"]], *r["advertencias"],
                      *r.get("factores_identificados", [])])


def _canonica(f: str) -> str:
    """Una sola forma para variantes que dicen lo mismo: «por N» = «durante N», diaria(s) = diario."""
    f = re.sub(r"^por (?=\d)", "durante ", f)
    f = re.sub(r"^diari[oa]s?$", "diario", f)
    return re.sub(r"^mensual(es)?$", "mensual", f)


def frecuencias(t: str) -> set[str]:
    return {_canonica(norm(m.group())) for m in _FRECUENCIAS.finditer(t)}


def _palabras(t: str) -> set[str]:
    return set(_PALABRA.findall(norm(t)))


def solapamiento(a: str, b: str) -> float:
    """Parte de las palabras de a (4 letras o más, sin tildes) que también están en b."""
    pa = _palabras(a)
    return len(pa & _palabras(b)) / len(pa) if pa else 1.0


def _lista(items) -> str:
    items = list(items)
    return ", ".join(items) if items else "ninguna"


def _clave_paso(p: dict) -> tuple:
    return p["tipo"], tuple(sorted(p["citas"]))


def diferencias(r1: dict, r2: dict) -> dict:
    t1, t2 = redactado(r1), redactado(r2)
    d1, d2 = dosis(t1), dosis(t2)
    c1, c2 = set(cifras(t1)), set(cifras(t2))
    f1, f2 = frecuencias(t1), frecuencias(t2)
    k1, k2 = {_clave_paso(p) for p in r1["recomendacion"]}, {_clave_paso(p) for p in r2["recomendacion"]}

    def sin_equivalente(advs, otras):
        return [a for a in advs if all(solapamiento(a, b) < UMBRAL_ADVERTENCIA for b in otras)]
    citas1, citas2 = {c["etiqueta"] for c in r1["citas"]}, {c["etiqueta"] for c in r2["citas"]}
    return {
        "dosis": (sorted(f"{n} {u}" for n, u in d1 - d2), sorted(f"{n} {u}" for n, u in d2 - d1)),
        "cifras": (sorted(c1 - c2, key=float), sorted(c2 - c1, key=float)),
        "frecuencias": (sorted(f1 - f2), sorted(f2 - f1)),
        "pasos": (len(r1["recomendacion"]), len(r2["recomendacion"])),
        "pasos_sin_equivalente": ([p for p in r1["recomendacion"] if _clave_paso(p) not in k2],
                                  [p for p in r2["recomendacion"] if _clave_paso(p) not in k1]),
        "advertencias": (len(r1["advertencias"]), len(r2["advertencias"])),
        "advertencias_sin_equivalente": (sin_equivalente(r1["advertencias"], r2["advertencias"]),
                                         sin_equivalente(r2["advertencias"], r1["advertencias"])),
        "citas": (sorted(citas1 - citas2), sorted(citas2 - citas1)),
    }


def _paso(p: dict) -> str:
    return f"[{p['tipo']}] {p['texto']} (citas {', '.join(p['citas'])})"


def seccion_version(version: str, r: dict, tokens: int | None) -> list[str]:
    lineas = [f"#### {version} ({tokens} tokens de salida)", "", f"**Resumen:** {r['resumen']}", "", "**Pasos:**", ""]
    lineas += [f"{i}. {_paso(p)}" for i, p in enumerate(r["recomendacion"], 1)] or ["Ninguno."]
    lineas += ["", "**Advertencias:**", ""] + ([f"- {a}" for a in r["advertencias"]] or ["Ninguna."])
    lineas += ["", "**Citas:**", ""]
    for c in r["citas"]:
        lineas.append(f"- {c['etiqueta']}: «{' '.join(c['extracto'].split())}»"
                      + (f" (traducción de apoyo: «{' '.join(c['extracto_traducido'].split())}»)"
                         if c.get("extracto_traducido") else ""))
    return lineas + [""]


def seccion_diferencias(v1: str, v2: str, d: dict) -> list[str]:
    def sublista(items, formato=str):
        return "".join(f"\n  - {formato(x)}" for x in items)
    return ["#### Diferencias", "",
            f"- Dosis solo en {v1}: {_lista(d['dosis'][0])}. Solo en {v2}: {_lista(d['dosis'][1])}.",
            f"- Cifras solo en {v1}: {_lista(d['cifras'][0])}. Solo en {v2}: {_lista(d['cifras'][1])}.",
            f"- Frecuencias y plazos solo en {v1}: {_lista(d['frecuencias'][0])}. Solo en {v2}: "
            f"{_lista(d['frecuencias'][1])}.",
            f"- Pasos: {d['pasos'][0]} en {v1} y {d['pasos'][1]} en {v2}.",
            f"- Pasos de {v1} sin un paso de {v2} del mismo tipo y con las mismas citas: "
            f"{len(d['pasos_sin_equivalente'][0])}" + sublista(d["pasos_sin_equivalente"][0], _paso),
            f"- Pasos de {v2} sin un paso de {v1} del mismo tipo y con las mismas citas: "
            f"{len(d['pasos_sin_equivalente'][1])}" + sublista(d["pasos_sin_equivalente"][1], _paso),
            f"- Advertencias: {d['advertencias'][0]} en {v1} y {d['advertencias'][1]} en {v2}.",
            f"- Advertencias de {v1} sin equivalente en {v2}: {len(d['advertencias_sin_equivalente'][0])}"
            + sublista(d["advertencias_sin_equivalente"][0]),
            f"- Advertencias de {v2} sin equivalente en {v1}: {len(d['advertencias_sin_equivalente'][1])}"
            + sublista(d["advertencias_sin_equivalente"][1]),
            f"- Etiquetas citadas solo en {v1}: {_lista(d['citas'][0])}. Solo en {v2}: {_lista(d['citas'][1])}.", ""]


def informe(respuestas: dict, versiones: tuple[str, str], casos: list[str], titulo: str) -> str:
    """respuestas[(version, caso)] = (respuesta, tokens_salida)."""
    v1, v2 = versiones
    cabecera = [
        f"# Comparación de respuestas: prompt {v1} frente a {v2}", "", titulo, "",
        "Criterios de las diferencias (automáticos):", "",
        "- Dosis, cifras y frecuencias o plazos se extraen del texto redactado por el modelo (resumen, pasos, "
        "advertencias y factores), no de los extractos citados. Dosis: número con unidad mg, mg/kg, ml, gotas, mcg o "
        "UI (la misma regla del control 6.2). Cifras: todos los números. Frecuencias y plazos: expresiones como "
        "«diario», «cada N meses», «durante N meses», «por N meses», «a los N meses», «al mes», «una vez». «Por N "
        "meses» se cuenta como «durante N meses» y «diaria» como «diario».",
        "- Un paso no tiene equivalente si en la otra versión no hay un paso del mismo tipo con las mismas etiquetas "
        "citadas.",
        f"- Una advertencia no tiene equivalente si comparte menos del {int(UMBRAL_ADVERTENCIA * 100)} % de sus "
        "palabras de 4 letras o más (sin tildes) con cada advertencia de la otra versión.", "",
        "## Resumen por caso", "",
        f"| Caso | Tokens {v1} | Tokens {v2} | Pasos {v1} / {v2} | Advertencias {v1} / {v2} | Dosis solo en {v1} | "
        f"Dosis solo en {v2} |", "| --- | --- | --- | --- | --- | --- | --- |"]
    cuerpo = []
    for caso in casos:
        (r1, t1), (r2, t2) = respuestas[(v1, caso)], respuestas[(v2, caso)]
        d = diferencias(r1, r2)
        cabecera.append(f"| {caso} | {t1} | {t2} | {d['pasos'][0]} / {d['pasos'][1]} | {d['advertencias'][0]} / "
                        f"{d['advertencias'][1]} | {_lista(d['dosis'][0])} | {_lista(d['dosis'][1])} |")
        cuerpo += [f"## Caso {caso}", ""] + seccion_version(v1, r1, t1) + seccion_version(v2, r2, t2) \
            + seccion_diferencias(v1, v2, d)
    return "\n".join(cabecera + [""] + cuerpo) + "\n"


_APROBADA = """
    SELECT respuesta_borrador, tokens_salida FROM asistencia.intento_generacion
     WHERE id_consulta = CAST(:c AS uuid) AND resultado = 'APROBADO'
"""


def leer_respuestas(conexion, corrida: dict, versiones: tuple[str, str]) -> tuple[dict, list[str]]:
    """Respuestas aprobadas de la primera repetición; casos verificados en ambas versiones."""
    ids = {(f["version_prompt"], f["caso"]): f["id_consulta"] for f in corrida["consultas"] if f["repeticion"] == 1}
    respuestas = {}
    for (version, caso), id_consulta in ids.items():
        if version not in versiones or id_consulta is None:
            continue
        fila = conexion.execute(text(_APROBADA), {"c": id_consulta}).first()
        if fila is not None:
            respuestas[(version, caso)] = (json.loads(fila.respuesta_borrador), fila.tokens_salida)
    casos = sorted({c for v, c in respuestas if all((x, c) in respuestas for x in versiones)})
    return respuestas, casos


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--corrida", default="d_consulta_real_prompts_v1_1_v1_2.json",
                   help="JSON de medir_consulta --versiones-prompt, dentro de --dir")
    p.add_argument("--versiones", default="v1.1,v1.2")
    p.add_argument("--salida", default="comparacion_prompts_v1_1_v1_2.md")
    p.add_argument("--dir", type=Path, default=Path(os.environ.get("CDSS_DIR_MEDICIONES", "data/mediciones")))
    a = p.parse_args(argv)
    versiones = tuple(a.versiones.split(","))
    if len(versiones) != 2:
        p.error("--versiones debe indicar exactamente dos versiones")
    corrida = json.loads((a.dir / a.corrida).read_text(encoding="utf-8"))

    from app.core.db import engines
    with engines()["generacion"].connect() as c:
        respuestas, casos = leer_respuestas(c, corrida, versiones)
    titulo = (f"Corrida `{a.corrida}` del {corrida['meta']['fecha']} (cliente {corrida['meta']['llm']}, entorno "
              f"{corrida['meta']['entorno']}). Casos verificados en ambas versiones: {', '.join(casos)}. Respuestas "
              "leídas de `asistencia.intento_generacion.respuesta_borrador` (intento APROBADO), sin llamar a la API.")
    (a.dir / a.salida).write_text(informe(respuestas, versiones, casos, titulo), encoding="utf-8")
    print(f"Informe: {a.dir / a.salida} ({len(casos)} casos)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
