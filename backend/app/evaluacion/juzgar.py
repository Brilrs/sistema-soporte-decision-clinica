"""Juicio de cada caso: lo determinista una vez y lo que depende del juez k veces.

Determinista: estado, clasificación, éxito de recuperación con los fragmentos enviados (y, como
diagnóstico, con todos los candidatos), cobertura de criterios y CUE por citas.
Con juez, por repetición: afirmaciones (CUE B y A, afirmaciones clave presentes o contradichas),
adherencia (rúbrica de prompts_juez.py, umbral 0,7) y las métricas de RAGAS.
Agregado de las k repeticiones: media de cada valor y su desviación (estabilidad del juez); la
respuesta cuenta como correcta si lo es en más de la mitad de las repeticiones, y el cuadrante se
calcula con la adherencia media."""
from __future__ import annotations

import statistics

from app.evaluacion import cue
from app.evaluacion import prompts_juez as pj
from app.evaluacion.dataset import Caso
from app.evaluacion.extraer import fragmentos_de
from app.evaluacion.juez import Juez


def _media(valores):
    v = [x for x in valores if x is not None]
    return statistics.fmean(v) if v else None


def _desviacion(valores):
    v = [x for x in valores if x is not None]
    return statistics.pstdev(v) if len(v) > 1 else (0.0 if v else None)


def determinista(caso: Caso, ext: dict) -> dict:
    enviados = fragmentos_de(ext, solo_enviados=True)
    candidatos = fragmentos_de(ext, solo_enviados=False)
    rec = cue.evaluar_criterios(caso.criterios, enviados)
    rec_cand = cue.evaluar_criterios(caso.criterios, candidatos)
    etiquetas = [f.etiqueta for f in enviados if f.etiqueta]
    return {
        "estado": ext["estado"], "estado_coincide": ext["estado"] == caso["estado_esperado"],
        "clasificacion": ext["clasificacion"],
        "enviados": len(etiquetas), "con_ingles": any(f.idioma != "es" for f in enviados),
        "exito_recuperacion": rec.exito, "sin_criterios": rec.sin_criterios,
        "cobertura_obligatorios": rec.cobertura, "obligatorios": rec.obligatorios,
        "obligatorios_cumplidos": rec.obligatorios_cumplidos, "opcionales": rec.opcionales,
        "opcionales_cumplidos": rec.opcionales_cumplidos, "criterios": rec.por_criterio,
        "depende_de_equivalencia_pendiente": rec.depende_de_equivalencia_pendiente,
        "exito_entre_candidatos": rec_cand.exito,
        "perdido_en_seleccion": rec_cand.exito and not rec.exito,
        "cue_citas": cue.cue_citas(ext["citados"], etiquetas),
    }


def una_repeticion(juez: Juez, caso: Caso, ext: dict, det: dict, repeticion: int, con_ragas: bool) -> dict:
    enviados = [f for f in ext["fragmentos"] if f["enviado"] and f["etiqueta"]]
    etiquetas = [f["etiqueta"] for f in enviados]
    respuesta = ext["respuesta_texto"]
    consulta = ext["texto_filtrado"] or ""
    hay_generacion = ext["estado"] in cue.CON_GENERACION and ext["tiene_respuesta"]
    juicio = adherencia = None
    if hay_generacion and respuesta and enviados:
        juicio = juez.llamar(caso.id, pj.AFIRMACIONES, pj.SISTEMA_AFIRMACIONES,
                             pj.contenido(consulta, respuesta, enviados, list(caso["afirmaciones_clave"])),
                             pj.ESQUEMA_AFIRMACIONES, repeticion)
        adh = juez.llamar(caso.id, pj.ADHERENCIA, pj.SISTEMA_ADHERENCIA, pj.contenido(consulta, respuesta, enviados),
                          pj.ESQUEMA_ADHERENCIA, repeticion)
        if adh is not None and isinstance(adh.get("puntaje"), (int, float)):
            adherencia = min(1.0, max(0.0, float(adh["puntaje"])))
    c = cue.cue_desde_juicio(juicio, etiquetas)
    observado = {"estado": ext["estado"], "clasificacion": ext["clasificacion"],
                 "tiene_respuesta": ext["tiene_respuesta"], "derivacion_en_respuesta": ext["derivacion_en_respuesta"],
                 "evidencia_suficiente": ext["evidencia_suficiente"]}
    corr = cue.correccion(caso.datos, observado, juicio)
    ragas = {"valores": {}, "errores": {}}
    if con_ragas and hay_generacion and enviados:
        from app.evaluacion import ragas_metricas
        ragas = ragas_metricas.calcular(juez, caso.id, repeticion, consulta, respuesta,
                                        [f["texto"] for f in enviados],
                                        caso["respuesta_referencia"] if caso.criterios else None)
    return {"repeticion": repeticion, "cue_b": c["cue_b"], "cue_a": c["cue_a"], "adherencia": adherencia,
            "correcta": corr.correcta, "campos": corr.campos, "claves_total": corr.claves_total,
            "claves_presentes": corr.claves_presentes, "claves_contradichas": corr.claves_contradichas,
            "fraccion_claves": corr.fraccion_claves,
            "cuadrante": cue.cuadrante(ext["estado"], det["exito_recuperacion"], corr.correcta, adherencia),
            "ragas": ragas["valores"], "errores_ragas": ragas["errores"],
            "juicio_afirmaciones": juicio}


def juzgar_caso(juez: Juez, caso: Caso, ext: dict, k: int, con_ragas: bool = True) -> dict:
    det = determinista(caso, ext)
    reps = [una_repeticion(juez, caso, ext, det, r, con_ragas) for r in range(1, k + 1)]
    correctas = [r["correcta"] for r in reps if r["correcta"] is not None]
    correcta = None if not correctas else sum(correctas) > len(correctas) / 2
    adherencia = _media(r["adherencia"] for r in reps)
    agregado = {
        "cue_b": _media(r["cue_b"] for r in reps), "cue_a": _media(r["cue_a"] for r in reps),
        "adherencia": adherencia, "correcta": correcta,
        "fraccion_claves": _media(r["fraccion_claves"] for r in reps),
        "cuadrante": cue.cuadrante(ext["estado"], det["exito_recuperacion"], correcta, adherencia),
        "ragas": {m: _media(r["ragas"].get(m) for r in reps) for m in
                  ("context_relevance", "faithfulness", "context_precision", "context_recall")},
        "desviacion": {"cue_b": _desviacion(r["cue_b"] for r in reps),
                       "adherencia": _desviacion(r["adherencia"] for r in reps),
                       **{m: _desviacion(r["ragas"].get(m) for r in reps)
                          for m in ("context_relevance", "faithfulness", "context_precision", "context_recall")}},
        "cuadrantes_por_repeticion": [r["cuadrante"] for r in reps],
    }
    return {"id_caso": caso.id, "tipos": list(caso["tipos"]), "origen": caso["origen"],
            "estado_esperado": caso["estado_esperado"], "modelo_juez": juez.modelo,
            "k": k, "determinista": det, "agregado": agregado, "repeticiones": reps}
