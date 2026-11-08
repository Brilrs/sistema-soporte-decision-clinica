"""Registro de cada intento en la base de datos, con la sesión de cdss_generacion.

- intento_generacion: la consulta reformulada, los puntajes de la recuperación, la
  solicitud enviada, su SHA-256, el resultado del control previo, el modelo efectivo,
  la versión del prompt, los tokens (de entrada, de salida y de razonamiento), el costo,
  la latencia, la respuesta tal como llegó y el resultado de cada control.
- fragmento_recuperado: los candidatos evaluados por el reranker; los enviados al
  modelo llevan su etiqueta F-01 a F-05.
- recomendacion y cita_evidencia: solo para el intento aprobado. Los triggers de la
  base rechazan una recomendación de un intento no aprobado y una cita de un fragmento
  no enviado en ese intento.

Una solicitud bloqueada por el control previo deja el intento con
control_identificadores = false, su hash y sin la solicitud (no se guarda un texto
que contiene identificadores), y el evento SOLICITUD_BLOQUEADA en la auditoría."""
import json

from sqlalchemy import Connection, text
from sqlalchemy.orm import Session

from app.core.auditoria import registrar_evento
from app.rag.generacion import ResultadoGeneracion
from app.rag.proteccion import ResultadoControl, SolicitudProtegida
from app.rag.recuperacion import ResultadoRecuperacion
from app.rag.verificacion import ResultadoVerificacion

ENTIDAD = "asistencia.consulta"


def guardar_intento(sesion: Session | Connection, id_consulta: str, numero_intento: int,
                    recuperacion: ResultadoRecuperacion, resultado: str, version_prompt: str,
                    solicitud: SolicitudProtegida | None = None, control: ResultadoControl | None = None,
                    generacion: ResultadoGeneracion | None = None,
                    verificacion: ResultadoVerificacion | None = None,
                    valida_evidencia: bool | None = None) -> str:
    """valida_evidencia se indica cuando 6.3 falló antes de llamar al modelo."""
    enviada = solicitud is not None and control is not None and control.aprobado
    g = generacion
    return sesion.execute(text(
        """INSERT INTO asistencia.intento_generacion
             (id_consulta, numero_intento, tipo_busqueda, consulta_reformulada, terminos_normalizados,
              candidatos_evaluados, relevancia_maxima, umbral_relevancia, solicitud_enviada, hash_solicitud,
              control_identificadores, modelo_llm, version_prompt, tokens_entrada, tokens_salida,
              tokens_razonamiento, costo_usd, latencia_llm_ms, respuesta_borrador, valida_citas,
              valida_consistencia, valida_evidencia, resultado)
           VALUES (CAST(:c AS uuid), :n, :tb, :cr, :tn, :ce, :rm, :ur, CAST(:sol AS jsonb), :h, :ci, :m, :vp,
                   :te, :ts, :tr, :costo, :lat, :borrador, :vc, :vcons, :ve, :res)
           RETURNING id_intento::text"""
    ), {
        "c": id_consulta, "n": numero_intento, "tb": recuperacion.tipo_busqueda, "cr": recuperacion.consulta,
        "tn": recuperacion.terminos_normalizados, "ce": recuperacion.candidatos_evaluados,
        "rm": recuperacion.relevancia_maxima, "ur": recuperacion.umbral_relevancia,
        "sol": solicitud.serializada if enviada else None,
        "h": solicitud.hash_sha256 if solicitud is not None else None,
        "ci": None if control is None else control.aprobado,
        "m": g.modelo if g is not None else None, "vp": version_prompt if g is not None else None,
        "te": g.tokens_entrada if g else None, "ts": g.tokens_salida if g else None,
        "tr": g.tokens_razonamiento if g else None, "costo": g.costo_usd if g else None,
        "lat": g.latencia_ms if g else None, "borrador": g.texto if g else None,
        "vc": verificacion.valida_citas if verificacion else None,
        "vcons": verificacion.valida_consistencia if verificacion else None,
        "ve": verificacion.valida_evidencia if verificacion else valida_evidencia,
        "res": resultado,
    }).scalar_one()


def guardar_fragmentos(sesion: Session | Connection, id_intento: str, recuperacion: ResultadoRecuperacion,
                       solicitud: SolicitudProtegida | None) -> None:
    etiquetas = {f.id_fragmento: e for e, f in solicitud.etiquetas.items()} if solicitud is not None else {}
    for f in recuperacion.fragmentos:
        sesion.execute(text(
            """INSERT INTO asistencia.fragmento_recuperado
                 (id_intento, id_fragmento, posicion_rrf, puntaje_rrf, puntaje_reranker, posicion_final,
                  enviado_al_llm, etiqueta_cita)
               VALUES (CAST(:i AS uuid), CAST(:f AS uuid), :prrf, :rrf, :rr, :pf, :env, :et)"""
        ), {"i": id_intento, "f": f.id_fragmento, "prrf": f.posicion_rrf, "rrf": round(f.puntaje_rrf, 5),
            "rr": round(f.puntaje_reranker or 0.0, 3), "pf": f.posicion_final,
            "env": f.id_fragmento in etiquetas, "et": etiquetas.get(f.id_fragmento)})


def texto_recomendacion(respuesta: dict) -> str:
    lineas = [respuesta["resumen"]]
    lineas += [f"{i}. {p['texto']} [{', '.join(p['citas'])}]" for i, p in enumerate(respuesta["recomendacion"], 1)]
    if respuesta["advertencias"]:
        lineas.append("Advertencias: " + " ".join(respuesta["advertencias"]))
    return "\n".join(lineas)


def guardar_recomendacion(sesion: Session | Connection, id_consulta: str, id_intento: str, respuesta: dict,
                          solicitud: SolicitudProtegida) -> str:
    id_recomendacion = sesion.execute(text(
        """INSERT INTO asistencia.recomendacion (id_consulta, id_intento, texto_recomendacion, factores_identificados)
           VALUES (CAST(:c AS uuid), CAST(:i AS uuid), :t, :f) RETURNING id_recomendacion::text"""
    ), {"c": id_consulta, "i": id_intento, "t": texto_recomendacion(respuesta),
        "f": respuesta["factores_identificados"]}).scalar_one()
    vistos: set[str] = set()
    for orden, cita in enumerate(respuesta["citas"], start=1):
        f = solicitud.etiquetas[cita["etiqueta"]]
        if f.id_fragmento in vistos:
            continue
        vistos.add(f.id_fragmento)
        sesion.execute(text(
            """INSERT INTO asistencia.cita_evidencia
                 (id_recomendacion, id_intento, id_fragmento, orden, texto_citado, extracto_traducido)
               VALUES (CAST(:r AS uuid), CAST(:i AS uuid), CAST(:f AS uuid), :o, :t, :tr)"""
        ), {"r": id_recomendacion, "i": id_intento, "f": f.id_fragmento, "o": orden, "t": cita["extracto"],
            "tr": cita["extracto_traducido"]})
    return id_recomendacion


def cerrar_consulta(sesion: Session | Connection, id_consulta: str, estado: str, numero_intentos: int,
                    latencia_total_ms: int) -> None:
    sesion.execute(text(
        """UPDATE asistencia.consulta
              SET estado = :e, numero_intentos = :n, fecha_hora_fin = now(), latencia_total_ms = :l
            WHERE id_consulta = CAST(:c AS uuid)"""), {"e": estado, "n": numero_intentos, "l": latencia_total_ms,
                                                       "c": id_consulta})


def registrar_bloqueo(sesion: Session | Connection, id_consulta: str, id_intento: str, control: ResultadoControl,
                      hash_sha256: str) -> None:
    """Evento SOLICITUD_BLOQUEADA: cuántas coincidencias y de qué tipo, nunca el valor."""
    registrar_evento(sesion, "SOLICITUD_BLOQUEADA", entidad=ENTIDAD, id_entidad=id_consulta, detalle={
        "id_intento": id_intento, "coincidencias": control.coincidencias, "tipos": list(control.tipos),
        "hash_solicitud": hash_sha256})


def registrar_cierre(sesion: Session | Connection, id_consulta: str, estado: str, intentos: list[dict]) -> None:
    registrar_evento(sesion, "CONSULTA_PROCESADA", entidad=ENTIDAD, id_entidad=id_consulta,
                     detalle={"estado": estado, "intentos": json.loads(json.dumps(intentos, default=str))})
