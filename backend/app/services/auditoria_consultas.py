"""Auditoría de las consultas (M13, HU13; Sprint 3, parte D1).

Lee solo las vistas de auditoría con la sesión de cdss_auditor (rol_auditor), que no tiene
permisos sobre las tablas clínicas ni de escritura:
- asistencia.v_indicadores_operativos: indicadores de los últimos 30 días, sin consultas de prueba;
- asistencia.v_auditoria_lista: una fila por consulta, para la lista paginada;
- asistencia.v_auditoria_consulta: una fila por intento, para el detalle.

Ninguna de las tres trae la identidad del paciente, texto_consulta, las observaciones del tamizaje
ni la nota de la decisión; la solicitud enviada solo aparece si el control previo la aprobó
(migración 014). El orden de la lista es explícito y no depende de la colación: fecha y hora de
inicio descendente y, con la misma fecha y hora, el id (uuid se compara por bytes)."""
from datetime import date
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.orm import Session

ESTADOS = ("VERIFICADA", "EVIDENCIA_INSUFICIENTE", "ERROR", "SOLICITUD_BLOQUEADA", "FUERA_DE_DOMINIO",
           "DATOS_FALTANTES", "TAMIZAJE_NO_VIGENTE", "EN_PROCESO")
# Columna de v_indicadores_operativos con el conteo de cada estado.
_COLUMNA_ESTADO = {"VERIFICADA": "verificadas", "EVIDENCIA_INSUFICIENTE": "evidencia_insuficiente",
                   "ERROR": "errores", "SOLICITUD_BLOQUEADA": "solicitudes_bloqueadas",
                   "FUERA_DE_DOMINIO": "fuera_de_dominio", "DATOS_FALTANTES": "datos_faltantes",
                   "TAMIZAJE_NO_VIGENTE": "tamizaje_no_vigente", "EN_PROCESO": "en_proceso"}
DIAS_INDICADORES = 30


def _entero(valor) -> int | None:
    return None if valor is None else int(round(float(valor)))


def _decimal(valor) -> float | None:
    return None if valor is None else float(valor)


def indicadores(sesion: Session) -> dict:
    """Indicadores de los últimos 30 días, siempre sin consultas de prueba (los calcula la vista)."""
    f = sesion.execute(text("SELECT * FROM asistencia.v_indicadores_operativos")).mappings().one()
    return {
        "dias": DIAS_INDICADORES, "desde": f["desde"], "hasta": f["hasta"],
        "consultas": f["consultas"], "evaluadas": f["evaluadas"],
        "por_estado": {e: f[_COLUMNA_ESTADO[e]] for e in ESTADOS},
        "pct_verificadas": _decimal(f["pct_verificadas"]),
        "pct_evidencia_insuficiente": _decimal(f["pct_evidencia_insuficiente"]),
        "con_reintento": f["con_reintento"], "pct_con_reintento": _decimal(f["pct_con_reintento"]),
        "latencia_p50_ms": _entero(f["p50_ms"]), "latencia_p90_ms": _entero(f["p90_ms"]),
        "latencia_p90_flujo_normal_ms": _entero(f["p90_flujo_normal_ms"]),
        "solicitudes_bloqueadas": f["solicitudes_bloqueadas"], "errores": f["errores"],
        "tokens_entrada": int(f["tokens_entrada"]), "tokens_salida": int(f["tokens_salida"]),
        "costo_api_usd": _decimal(f["costo_api_usd"]),
    }


_LISTA = """
    SELECT id_consulta::text, fecha_hora_inicio, fecha_hora_fin, nombre_usuario, estado, numero_intentos,
           latencia_total_ms, modo_prueba, modelo_llm, version_prompt, tokens_entrada, tokens_salida, costo_usd
      FROM asistencia.v_auditoria_lista
     WHERE {filtro}
     ORDER BY fecha_hora_inicio DESC, id_consulta DESC
     LIMIT :limite OFFSET :desplazamiento
"""
_CONTEO = "SELECT count(*) FROM asistencia.v_auditoria_lista WHERE {filtro}"


def _filtro(estado: str | None, desde: date | None, hasta: date | None, incluir_pruebas: bool) -> tuple[str, dict]:
    """Las fechas son días calendario de Lima, inclusivos: desde las 00:00 del primero hasta antes de
    las 00:00 del día siguiente al último. Sin incluir_pruebas, las consultas de prueba no se listan."""
    condiciones, valores = ["true"], {}
    if not incluir_pruebas:
        condiciones.append("NOT modo_prueba")
    if estado is not None:
        condiciones.append("estado = :estado")
        valores["estado"] = estado
    if desde is not None:
        condiciones.append("fecha_hora_inicio >= CAST(:desde AS timestamp) AT TIME ZONE 'America/Lima'")
        valores["desde"] = desde
    if hasta is not None:
        condiciones.append("fecha_hora_inicio < (CAST(:hasta AS timestamp) + interval '1 day') AT TIME ZONE 'America/Lima'")
        valores["hasta"] = hasta
    return " AND ".join(condiciones), valores


def _suma_tokens(entrada, salida) -> int | None:
    if entrada is None and salida is None:
        return None
    return int(entrada or 0) + int(salida or 0)


def listar(sesion: Session, *, estado: str | None = None, desde: date | None = None, hasta: date | None = None,
           incluir_pruebas: bool = False, limite: int = 20, desplazamiento: int = 0) -> tuple[list[dict], int]:
    filtro, valores = _filtro(estado, desde, hasta, incluir_pruebas)
    total = sesion.execute(text(_CONTEO.format(filtro=filtro)), valores).scalar_one()
    filas = sesion.execute(text(_LISTA.format(filtro=filtro)),
                           {**valores, "limite": limite, "desplazamiento": desplazamiento}).mappings().all()
    return [{
        "id_consulta": f["id_consulta"], "fecha_hora_inicio": f["fecha_hora_inicio"],
        "fecha_hora_fin": f["fecha_hora_fin"], "nombre_usuario": f["nombre_usuario"], "estado": f["estado"],
        "numero_intentos": f["numero_intentos"], "con_reintento": f["numero_intentos"] == 2,
        "latencia_total_ms": f["latencia_total_ms"], "modo_prueba": f["modo_prueba"],
        "modelo_llm": f["modelo_llm"], "version_prompt": f["version_prompt"],
        "tokens_entrada": None if f["tokens_entrada"] is None else int(f["tokens_entrada"]),
        "tokens_salida": None if f["tokens_salida"] is None else int(f["tokens_salida"]),
        "tokens_total": _suma_tokens(f["tokens_entrada"], f["tokens_salida"]),
        "costo_usd": _decimal(f["costo_usd"]),
    } for f in filas], total


_DETALLE = """
    SELECT id_consulta::text, fecha_hora_inicio, fecha_hora_fin, nombre_usuario, estado, numero_intentos,
           latencia_total_ms, confirma_tamizaje_no_vigente, modo_prueba, numero_intento, tipo_busqueda, resultado,
           modelo_llm, version_prompt, tokens_entrada, tokens_salida, tokens_razonamiento, costo_usd,
           latencia_llm_ms, candidatos_evaluados, relevancia_maxima, umbral_relevancia, valida_citas,
           valida_consistencia, valida_evidencia, control_identificadores, hash_solicitud, solicitud_enviada,
           fragmentos_enviados
      FROM asistencia.v_auditoria_consulta
     WHERE id_consulta = CAST(:c AS uuid)
     ORDER BY numero_intento NULLS FIRST
"""


def _fragmento(f: dict) -> dict:
    return {"etiqueta": f.get("etiqueta"), "puntaje_reranker": _decimal(f.get("puntaje")),
            "origen": f.get("origen"), "posicion_final": f.get("posicion_final"), "documento": f.get("documento"),
            "seccion": f.get("seccion"), "pagina_inicio": f.get("pagina_inicio"), "pagina_fin": f.get("pagina_fin")}


def _intento(f) -> dict:
    return {
        "numero_intento": f["numero_intento"], "tipo_busqueda": f["tipo_busqueda"], "resultado": f["resultado"],
        "modelo_llm": f["modelo_llm"], "version_prompt": f["version_prompt"],
        "tokens_entrada": f["tokens_entrada"], "tokens_salida": f["tokens_salida"],
        "tokens_razonamiento": f["tokens_razonamiento"], "costo_usd": _decimal(f["costo_usd"]),
        "latencia_llm_ms": f["latencia_llm_ms"], "candidatos_evaluados": f["candidatos_evaluados"],
        "verificacion": {"valida_citas": f["valida_citas"], "valida_consistencia": f["valida_consistencia"],
                         "valida_evidencia": f["valida_evidencia"],
                         "relevancia_maxima": _decimal(f["relevancia_maxima"]),
                         "umbral_relevancia": _decimal(f["umbral_relevancia"])},
        "control_identificadores": f["control_identificadores"], "hash_solicitud": f["hash_solicitud"],
        "solicitud_enviada": f["solicitud_enviada"],
        "fragmentos": [_fragmento(x) for x in (f["fragmentos_enviados"] or [])],
    }


def _suma(valores: list) -> float | int | None:
    presentes = [v for v in valores if v is not None]
    if not presentes:
        return None
    total = sum(Decimal(str(v)) for v in presentes)
    return float(total) if any(isinstance(v, (float, Decimal)) for v in presentes) else int(total)


def detalle(sesion: Session, id_consulta: str) -> dict | None:
    filas = sesion.execute(text(_DETALLE), {"c": id_consulta}).mappings().all()
    if not filas:
        return None
    q = filas[0]
    intentos = [_intento(f) for f in filas if f["numero_intento"] is not None]
    entrada = _suma([i["tokens_entrada"] for i in intentos])
    salida = _suma([i["tokens_salida"] for i in intentos])
    return {
        "id_consulta": q["id_consulta"], "fecha_hora_inicio": q["fecha_hora_inicio"],
        "fecha_hora_fin": q["fecha_hora_fin"], "nombre_usuario": q["nombre_usuario"], "estado": q["estado"],
        "numero_intentos": q["numero_intentos"], "latencia_total_ms": q["latencia_total_ms"],
        "confirma_tamizaje_no_vigente": q["confirma_tamizaje_no_vigente"], "modo_prueba": q["modo_prueba"],
        "tokens_entrada": entrada, "tokens_salida": salida, "tokens_total": _suma_tokens(entrada, salida),
        "costo_usd": _suma([i["costo_usd"] for i in intentos]),
        "intentos": intentos,
    }
