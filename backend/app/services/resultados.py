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
from app.rag.cliente_llm import MODELO_FALSO
from app.rag.generacion import interpretar
from app.rag.parametros import leer_parametros
from app.rag.validacion import DATOS_MINIMOS, TAMIZAJE_NO_VIGENTE, leer_clasificacion
from app.rag.verificacion import EVIDENCIA_INSUFICIENTE, ERROR, MENSAJE_EVIDENCIA_INSUFICIENTE, MENSAJE_NO_EVALUADA
from app.services.consultas import intento_publico, verificacion_de
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


_INTENTOS = """
    SELECT id_intento::text, numero_intento AS numero, tipo_busqueda, candidatos_evaluados, relevancia_maxima,
           umbral_relevancia, resultado, valida_citas, valida_consistencia, valida_evidencia, modelo_llm,
           respuesta_borrador
      FROM asistencia.intento_generacion
     WHERE id_consulta = CAST(:c AS uuid)
     ORDER BY numero_intento
"""
_CITAS = """
    SELECT r.etiqueta_cita, ce.texto_citado, ce.extracto_traducido, d.codigo_documento, d.titulo, d.idioma,
           f.seccion, f.pagina_inicio, f.pagina_fin, r.puntaje_reranker
      FROM asistencia.cita_evidencia ce
      JOIN asistencia.fragmento_recuperado r ON r.id_intento = ce.id_intento AND r.id_fragmento = ce.id_fragmento
      JOIN conocimiento.fragmento f ON f.id_fragmento = ce.id_fragmento
      JOIN conocimiento.documento_fuente d ON d.id_documento = f.id_documento
     WHERE ce.id_intento = CAST(:i AS uuid)
     ORDER BY ce.orden
"""


def _numero(valor) -> float | None:
    return None if valor is None else float(valor)


def parte_generacion(sesion: Session | Connection, id_consulta: str) -> dict:
    """Con cdss_generacion: intentos (búsqueda y controles), verificación, modo de prueba y la
    recomendación aprobada con sus citas (vacías si no hay)."""
    filas = sesion.execute(text(_INTENTOS), {"c": id_consulta}).all()
    intentos = [{"numero": f.numero, "tipo_busqueda": f.tipo_busqueda, "candidatos_evaluados": f.candidatos_evaluados,
                 "relevancia_maxima": _numero(f.relevancia_maxima), "umbral_relevancia": _numero(f.umbral_relevancia),
                 "resultado": f.resultado, "valida_citas": f.valida_citas,
                 "valida_consistencia": f.valida_consistencia, "valida_evidencia": f.valida_evidencia}
                for f in filas]
    base = {"intentos": [intento_publico(i) for i in intentos], "verificacion": verificacion_de(intentos),
            "modo_prueba": any(f.modelo_llm == MODELO_FALSO for f in filas), "recomendacion": None, "citas": []}
    fila = next((f for f in filas if f.resultado == "APROBADO"), None)
    if fila is None:
        return base
    respuesta, _ = interpretar(fila.respuesta_borrador or "")
    citas = [{"etiqueta": c.etiqueta_cita, "extracto": c.texto_citado, "extracto_traducido": c.extracto_traducido,
              "etiqueta_traduccion": g.ETIQUETA_TRADUCCION if c.extracto_traducido else None,
              "fuente": c.codigo_documento, "documento": c.titulo, "seccion": c.seccion,
              "pagina_inicio": c.pagina_inicio, "pagina_fin": c.pagina_fin, "idioma": c.idioma,
              "puntaje_reranker": _numero(c.puntaje_reranker)}
             for c in sesion.execute(text(_CITAS), {"i": fila.id_intento})]
    recomendacion = None if respuesta is None else {
        campo: respuesta.get(campo) for campo in ("resumen", "recomendacion", "advertencias", "factores_identificados")}
    return {**base, "recomendacion": recomendacion, "citas": citas}


_LISTA = """
    SELECT q.id_consulta::text, q.id_tamizaje::text, t.fecha_tamizaje, q.id_consulta_previa::text, q.estado,
           q.texto_filtrado, q.idioma_respuesta AS idioma, q.fecha_hora_inicio, q.fecha_hora_fin, q.numero_intentos,
           q.latencia_total_ms, q.confirma_tamizaje_no_vigente, c.nombre AS categoria, dc.tipo_decision
      FROM asistencia.consulta q
      JOIN clinico.tamizaje t ON t.id_tamizaje = q.id_tamizaje
      LEFT JOIN clinico.resultado_clasificacion r ON r.id_tamizaje = q.id_tamizaje
      LEFT JOIN configuracion.categoria_anemia c ON c.id_categoria = r.id_categoria
      LEFT JOIN asistencia.decision_clinica dc ON dc.id_consulta = q.id_consulta
     WHERE t.id_paciente = CAST(:p AS uuid) AND q.id_usuario = CAST(:u AS uuid)
     ORDER BY q.fecha_hora_inicio DESC
"""
_MODO_PRUEBA = """
    SELECT id_consulta::text FROM asistencia.intento_generacion
     WHERE id_consulta = ANY(CAST(:ids AS uuid[])) AND modelo_llm = :m
"""


def consultas_del_paciente(clinica: Session | Connection, generacion: Session | Connection, id_paciente: str,
                           id_usuario: str) -> list[dict]:
    """Consultas del paciente hechas por el usuario (las de otros profesionales no se listan),
    de la más reciente a la más antigua. La marca de prueba se lee con cdss_generacion."""
    filas = [dict(f._mapping) for f in clinica.execute(text(_LISTA), {"p": id_paciente, "u": id_usuario})]
    if not filas:
        return []
    de_prueba = set(generacion.execute(text(_MODO_PRUEBA), {"ids": [f["id_consulta"] for f in filas],
                                                            "m": MODELO_FALSO}).scalars())
    return [{**f, "modo_prueba": f["id_consulta"] in de_prueba} for f in filas]


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
