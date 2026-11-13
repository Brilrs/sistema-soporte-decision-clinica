"""Resultado guardado de una consulta y datos faltantes (parte D2).

Cada función recibe la sesión que le corresponde:
- con cdss_clinica: la ficha de la consulta (dueño, estado, tamizaje, texto filtrado), los
  datos faltantes, la vigencia, la clasificación, la decisión y la completación de la
  hemoglobina del tamizaje;
- con cdss_generacion: la recomendación aprobada (respuesta del intento) y las citas con su
  etiqueta F-xx, que cdss_clinica no puede leer. Nada de esto lleva identidad.

texto_consulta solo lo lee leer_texto_original(), con cdss_clinica, para reanudar una
consulta en el servidor; nunca se devuelve en la API."""
from dataclasses import dataclass

from sqlalchemy import Connection, text
from sqlalchemy.orm import Session

from app.rag import grafo as g
from app.rag.generacion import interpretar
from app.rag.parametros import leer_parametros
from app.rag.validacion import DATOS_MINIMOS, TAMIZAJE_NO_VIGENTE, leer_clasificacion
from app.rag.verificacion import EVIDENCIA_INSUFICIENTE, ERROR, MENSAJE_EVIDENCIA_INSUFICIENTE, MENSAJE_NO_EVALUADA
from app.services.decisiones import leer_decision, opciones_decision

ETIQUETAS = {campo: etiqueta for campo, etiqueta, _ in DATOS_MINIMOS}
DATOS_FALTANTES = "DATOS_FALTANTES"
MENSAJE_ALTITUD = ("El distrito de residencia no tiene altitud registrada en el catálogo. El administrador debe "
                   "completarla antes de reanudar la consulta.")


class ErrorDatos(Exception):
    def __init__(self, mensaje: str, codigo: int):
        super().__init__(mensaje)
        self.codigo = codigo


@dataclass(frozen=True)
class FichaConsulta:
    id_consulta: str
    id_usuario: str
    id_tamizaje: str
    id_paciente: str
    id_consulta_previa: str | None
    estado: str
    confirma_tamizaje_no_vigente: bool


def ficha(sesion: Session | Connection, id_consulta: str) -> FichaConsulta | None:
    fila = sesion.execute(text(
        """SELECT q.id_consulta::text, q.id_usuario::text, q.id_tamizaje::text, t.id_paciente::text,
                  q.id_consulta_previa::text, q.estado, q.confirma_tamizaje_no_vigente
             FROM asistencia.consulta q JOIN clinico.tamizaje t ON t.id_tamizaje = q.id_tamizaje
            WHERE q.id_consulta = CAST(:c AS uuid)"""), {"c": id_consulta}).first()
    return None if fila is None else FichaConsulta(*fila)


def leer_texto_original(sesion: Session | Connection, id_consulta: str) -> str:
    """Solo con cdss_clinica y solo para reanudar la consulta en el servidor."""
    return sesion.execute(text("SELECT texto_consulta FROM asistencia.consulta WHERE id_consulta = CAST(:c AS uuid)"),
                          {"c": id_consulta}).scalar_one()


def _vigencia(sesion, id_consulta: str) -> dict:
    fila = sesion.execute(text(
        """SELECT (q.fecha_hora_inicio AT TIME ZONE 'America/Lima')::date - t.fecha_tamizaje AS dias,
                  q.confirma_tamizaje_no_vigente
             FROM asistencia.consulta q JOIN clinico.tamizaje t ON t.id_tamizaje = q.id_tamizaje
            WHERE q.id_consulta = CAST(:c AS uuid)"""), {"c": id_consulta}).one()
    vigencia = leer_parametros(sesion, ["DIAS_VIGENCIA_TAMIZAJE"])["DIAS_VIGENCIA_TAMIZAJE"]
    return {"dias_transcurridos": fila.dias, "dias_vigencia": vigencia,
            "continua_con_tamizaje_no_vigente": bool(fila.confirma_tamizaje_no_vigente and fila.dias > vigencia)}


def mensaje_de_estado(estado: str, faltantes: list[dict], vigencia: dict) -> str | None:
    if estado == DATOS_FALTANTES:
        return g.mensaje_datos_faltantes([f["etiqueta"] for f in faltantes if not f["completado"]] or
                                         [f["etiqueta"] for f in faltantes])
    if estado == TAMIZAJE_NO_VIGENTE:
        return g.mensaje_tamizaje_no_vigente(vigencia["dias_transcurridos"], vigencia["dias_vigencia"])
    return {EVIDENCIA_INSUFICIENTE: MENSAJE_EVIDENCIA_INSUFICIENTE, ERROR: MENSAJE_NO_EVALUADA,
            g.FUERA_DE_DOMINIO: g.MENSAJE_FUERA_DE_DOMINIO, g.SOLICITUD_BLOQUEADA: g.MENSAJE_BLOQUEADA}.get(estado)


def parte_clinica(sesion: Session | Connection, f: FichaConsulta) -> dict:
    """Con cdss_clinica: todo lo que no es la recomendación ni las citas."""
    q = sesion.execute(text(
        """SELECT texto_filtrado, idioma_respuesta, numero_intentos, fecha_hora_inicio, fecha_hora_fin,
                  latencia_total_ms
             FROM asistencia.consulta WHERE id_consulta = CAST(:c AS uuid)"""), {"c": f.id_consulta}).one()
    faltantes = [{"campo": d.campo, "etiqueta": ETIQUETAS.get(d.campo, d.campo), "mensaje": d.mensaje,
                  "completado": d.completado}
                 for d in sesion.execute(text(
                     """SELECT campo, mensaje, completado FROM asistencia.dato_faltante
                         WHERE id_consulta = CAST(:c AS uuid) ORDER BY id_dato_faltante"""), {"c": f.id_consulta})]
    vigencia = _vigencia(sesion, f.id_consulta)
    c = leer_clasificacion(sesion, f.id_tamizaje)
    decision = leer_decision(sesion, f.id_consulta)
    return {
        "id_consulta": f.id_consulta, "id_paciente": f.id_paciente, "id_tamizaje": f.id_tamizaje,
        "id_consulta_previa": f.id_consulta_previa, "estado": f.estado,
        "mensaje": mensaje_de_estado(f.estado, faltantes, vigencia), "idioma": q.idioma_respuesta,
        "texto_filtrado": q.texto_filtrado, "numero_intentos": q.numero_intentos,
        "fecha_hora_inicio": q.fecha_hora_inicio, "fecha_hora_fin": q.fecha_hora_fin,
        "latencia_total_ms": q.latencia_total_ms, "datos_faltantes": faltantes, "vigencia": vigencia,
        "clasificacion": None if c is None else {
            "categoria": c.categoria, "nivel_riesgo": c.nivel_riesgo, "hb_ajustada_g_dl": float(c.hb_ajustada_g_dl),
            "ajuste_hb_g_dl": float(c.ajuste_hb_g_dl), "altitud_msnm": c.altitud_msnm,
            "requiere_derivacion": c.requiere_derivacion},
        "decision": decision,
        "opciones_decision": [] if decision else opciones_decision(f.estado),
    }


_RESPUESTA = """
    SELECT i.id_intento::text, i.respuesta_borrador
      FROM asistencia.intento_generacion i
     WHERE i.id_consulta = CAST(:c AS uuid) AND i.resultado = 'APROBADO'
"""
_CITAS = """
    SELECT r.etiqueta_cita, ce.texto_citado, ce.extracto_traducido, d.codigo_documento, d.titulo, d.idioma,
           f.seccion, f.pagina_inicio, f.pagina_fin
      FROM asistencia.cita_evidencia ce
      JOIN asistencia.fragmento_recuperado r ON r.id_intento = ce.id_intento AND r.id_fragmento = ce.id_fragmento
      JOIN conocimiento.fragmento f ON f.id_fragmento = ce.id_fragmento
      JOIN conocimiento.documento_fuente d ON d.id_documento = f.id_documento
     WHERE ce.id_intento = CAST(:i AS uuid)
     ORDER BY ce.orden
"""


def parte_generacion(sesion: Session | Connection, id_consulta: str) -> dict:
    """Con cdss_generacion: la recomendación aprobada y sus citas (vacías si no hay)."""
    fila = sesion.execute(text(_RESPUESTA), {"c": id_consulta}).first()
    if fila is None:
        return {"recomendacion": None, "citas": []}
    respuesta, _ = interpretar(fila.respuesta_borrador or "")
    citas = [{"etiqueta": c.etiqueta_cita, "extracto": c.texto_citado, "extracto_traducido": c.extracto_traducido,
              "etiqueta_traduccion": g.ETIQUETA_TRADUCCION if c.extracto_traducido else None,
              "fuente": c.codigo_documento, "documento": c.titulo, "seccion": c.seccion,
              "pagina_inicio": c.pagina_inicio, "pagina_fin": c.pagina_fin, "idioma": c.idioma}
             for c in sesion.execute(text(_CITAS), {"i": fila.id_intento})]
    recomendacion = None if respuesta is None else {
        campo: respuesta.get(campo) for campo in ("resumen", "recomendacion", "advertencias", "factores_identificados")}
    return {"recomendacion": recomendacion, "citas": citas}


def completar_datos(sesion: Session | Connection, f: FichaConsulta, hemoglobina_g_dl, metodo_medicion: str | None
                    ) -> list[str]:
    """Con cdss_clinica: completa la hemoglobina del mismo tamizaje solo si está vacía (nunca
    sobrescribe) y marca los datos faltantes como completados. Devuelve los campos."""
    if f.estado != DATOS_FALTANTES:
        raise ErrorDatos("La consulta no está pendiente de datos faltantes", 409)
    pendientes = [r.campo for r in sesion.execute(text(
        "SELECT campo FROM asistencia.dato_faltante WHERE id_consulta = CAST(:c AS uuid) AND NOT completado"),
        {"c": f.id_consulta})]
    if not pendientes:
        raise ErrorDatos("Los datos faltantes de esta consulta ya se completaron", 409)
    if "altitud_msnm" in pendientes:
        raise ErrorDatos(MENSAJE_ALTITUD, 422)
    otros = [c for c in pendientes if c != "hemoglobina_g_dl"]
    if otros:
        raise ErrorDatos(f"No se pueden completar desde la consulta: {', '.join(ETIQUETAS.get(c, c) for c in otros)}",
                         422)
    if hemoglobina_g_dl is None:
        raise ErrorDatos("Falta la hemoglobina", 422)
    sesion.execute(text(
        """UPDATE clinico.tamizaje
              SET hemoglobina_g_dl = :hb, metodo_medicion = coalesce(metodo_medicion, :m)
            WHERE id_tamizaje = CAST(:t AS uuid) AND hemoglobina_g_dl IS NULL"""),
        {"hb": hemoglobina_g_dl, "m": metodo_medicion, "t": f.id_tamizaje})
    sesion.execute(text(
        """UPDATE asistencia.dato_faltante SET completado = true, fecha_completado = now()
            WHERE id_consulta = CAST(:c AS uuid) AND NOT completado"""), {"c": f.id_consulta})
    return pendientes
