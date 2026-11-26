"""Extracción de solo lectura de lo que hizo el sistema en cada consulta evaluada.

Usa la conexión de generación (cdss_generacion) en transacciones READ ONLY: es la que puede leer
los intentos, la respuesta del modelo (respuesta_borrador), los fragmentos recuperados con su texto
y las citas, y no puede leer la identidad del paciente ni texto_consulta. La vista del auditor no
sirve aquí: no trae la respuesta del modelo ni los ids de los fragmentos.

Intento que cuenta (sección 3.2 del diseño): el de recomendacion.id_intento; si la consulta no
quedó verificada, el último. El texto de cada fragmento enviado es el de solicitud_enviada (lo que
recibió el modelo) y, si falta, el de conocimiento.fragmento."""
from __future__ import annotations

import json

from sqlalchemy import Engine, text

from app.evaluacion.cue import Fragmento

_CONSULTA = """
    SELECT q.id_consulta::text, q.id_tamizaje::text, q.texto_filtrado, q.estado, q.numero_intentos,
           q.idioma_respuesta, q.latencia_total_ms, c.nombre AS clasificacion, c.requiere_derivacion
      FROM asistencia.consulta q
      LEFT JOIN clinico.resultado_clasificacion r ON r.id_tamizaje = q.id_tamizaje
      LEFT JOIN configuracion.categoria_anemia c ON c.id_categoria = r.id_categoria
     WHERE q.id_consulta = CAST(:c AS uuid)
"""
_INTENTOS = """
    SELECT id_intento::text, numero_intento, tipo_busqueda, resultado, modelo_llm, version_prompt,
           tokens_entrada, tokens_salida, tokens_razonamiento, costo_usd, relevancia_maxima, umbral_relevancia,
           valida_citas, valida_consistencia, valida_evidencia, control_identificadores, solicitud_enviada,
           respuesta_borrador
      FROM asistencia.intento_generacion WHERE id_consulta = CAST(:c AS uuid) ORDER BY numero_intento
"""
_RECOMENDACION = """
    SELECT id_recomendacion::text, id_intento::text FROM asistencia.recomendacion WHERE id_consulta = CAST(:c AS uuid)
"""
_FRAGMENTOS = """
    SELECT r.id_fragmento::text, r.etiqueta_cita, r.enviado_al_llm, r.origen, r.posicion_rrf, r.posicion_final,
           r.puntaje_reranker, d.codigo_documento, d.idioma, f.pagina_inicio, f.pagina_fin, f.texto,
           (f.vigente AND d.estado = 'VIGENTE'
            AND f.version_indexacion = (SELECT max(v.version_indexacion) FROM conocimiento.fragmento v
                                         WHERE v.id_documento = f.id_documento)) AS vigente
      FROM asistencia.fragmento_recuperado r
      JOIN conocimiento.fragmento f ON f.id_fragmento = r.id_fragmento
      JOIN conocimiento.documento_fuente d ON d.id_documento = f.id_documento
     WHERE r.id_intento = CAST(:i AS uuid)
     ORDER BY r.enviado_al_llm DESC, r.etiqueta_cita, r.posicion_final NULLS LAST, r.posicion_rrf NULLS LAST
"""
_CITAS = """
    SELECT r.etiqueta_cita FROM asistencia.cita_evidencia c
      JOIN asistencia.fragmento_recuperado r ON r.id_intento = c.id_intento AND r.id_fragmento = c.id_fragmento
     WHERE c.id_recomendacion = CAST(:r AS uuid) ORDER BY c.orden
"""


def _num(v):
    return None if v is None else float(v)


def _json(v):
    if v is None or isinstance(v, (dict, list)):
        return v
    try:
        return json.loads(v)
    except (TypeError, ValueError):
        return None


def texto_respuesta(borrador: dict | None) -> str:
    """Resumen más el texto de cada paso de la recomendación, sin etiquetas de cita."""
    if not borrador:
        return ""
    partes = [borrador.get("resumen") or ""]
    partes += [p.get("texto") or "" for p in borrador.get("recomendacion") or []]
    return "\n".join(p.strip() for p in partes if p and p.strip())


def extraer_consulta(motor: Engine, id_consulta: str) -> dict:
    with motor.connect() as c:
        c.execute(text("SET TRANSACTION READ ONLY"))
        q = c.execute(text(_CONSULTA), {"c": id_consulta}).mappings().first()
        if q is None:
            raise LookupError(f"No existe la consulta {id_consulta}")
        intentos = [dict(i) for i in c.execute(text(_INTENTOS), {"c": id_consulta}).mappings()]
        rec = c.execute(text(_RECOMENDACION), {"c": id_consulta}).mappings().first()
        cuenta = None
        if rec is not None:
            cuenta = next((i for i in intentos if i["id_intento"] == rec["id_intento"]), None)
        elif intentos:
            cuenta = intentos[-1]
        fragmentos, citados = [], []
        if cuenta is not None:
            fragmentos = [dict(f) for f in c.execute(text(_FRAGMENTOS), {"i": cuenta["id_intento"]}).mappings()]
        if rec is not None:
            citados = [e for (e,) in c.execute(text(_CITAS), {"r": rec["id_recomendacion"]})]
        c.rollback()

    solicitud = _json(cuenta["solicitud_enviada"]) if cuenta else None
    enviado_texto = {e["etiqueta"]: e["texto"] for e in (solicitud or {}).get("evidencia", [])}
    borrador = _json(cuenta["respuesta_borrador"]) if cuenta else None
    salida_fragmentos = []
    for f in fragmentos:
        salida_fragmentos.append({
            "id_fragmento": f["id_fragmento"], "etiqueta": f["etiqueta_cita"], "enviado": f["enviado_al_llm"],
            "origen": f["origen"], "posicion_rrf": f["posicion_rrf"], "posicion_final": f["posicion_final"],
            "puntaje_reranker": _num(f["puntaje_reranker"]), "documento": f["codigo_documento"],
            "idioma": f["idioma"], "pagina_inicio": f["pagina_inicio"], "pagina_fin": f["pagina_fin"],
            "vigente": bool(f["vigente"]),
            "texto": enviado_texto.get(f["etiqueta_cita"]) or f["texto"],
            "texto_de_la_solicitud": f["etiqueta_cita"] in enviado_texto,
        })
    pasos = (borrador or {}).get("recomendacion") or []
    return {
        "id_consulta": q["id_consulta"], "estado": q["estado"], "texto_filtrado": q["texto_filtrado"],
        "idioma_respuesta": q["idioma_respuesta"], "numero_intentos": q["numero_intentos"],
        "latencia_total_ms": q["latencia_total_ms"],
        "clasificacion": q["clasificacion"], "requiere_derivacion_sistema": q["requiere_derivacion"],
        "intento_que_cuenta": cuenta["numero_intento"] if cuenta else None,
        "intentos": [{k: (_num(v) if k in ("costo_usd", "relevancia_maxima", "umbral_relevancia") else v)
                      for k, v in i.items() if k not in ("solicitud_enviada", "respuesta_borrador", "id_intento")}
                     for i in intentos],
        "respuesta_borrador": borrador,
        "respuesta_texto": texto_respuesta(borrador),
        "tiene_respuesta": borrador is not None,
        "evidencia_suficiente": (borrador or {}).get("evidencia_suficiente"),
        "clasificacion_confirmada": (borrador or {}).get("clasificacion_confirmada"),
        "derivacion_en_respuesta": any(p.get("tipo") == "DERIVACION" for p in pasos) if borrador else None,
        "fragmentos": salida_fragmentos,
        "citados": citados,
        "modo_prueba": any(i["modelo_llm"] == "modelo-falso" for i in intentos),
    }


def fragmentos_de(extraccion: dict, solo_enviados: bool = True) -> list[Fragmento]:
    return [Fragmento(f["etiqueta"], f["id_fragmento"], f["documento"], f["pagina_inicio"], f["pagina_fin"],
                      f["texto"], f["vigente"], f["enviado"], f["idioma"] or "es", f["origen"])
            for f in extraccion["fragmentos"] if f["enviado"] or not solo_enviados]
