"""Parte D1 del Sprint 3 · API de auditoría y trazabilidad (M13, HU13).

- GET /api/auditoria/indicadores: indicadores de los últimos 30 días, sin consultas de prueba.
- GET /api/auditoria/consultas: lista paginada de todas las consultas, con filtros de estado,
  fechas (días de Lima, inclusivos) e incluir_pruebas (por omisión, false: las de prueba se
  ocultan y, si se piden, van marcadas con modo_prueba).
- GET /api/auditoria/consultas/{id}: detalle con los intentos, el modelo, el prompt, los tokens,
  el costo, la verificación 6.1, 6.2 y 6.3, los fragmentos enviados con su puntaje y su origen, y
  la solicitud enviada al modelo tal como quedó registrada (ya pasó por la lista blanca).

Permiso VER_AUDITORIA (Coordinador CRED y Administrador; el resto, 403). Los datos se leen con la
conexión de solo lectura de cdss_auditor, que no puede leer la identidad del paciente, el texto
original de la consulta, las observaciones ni la nota de la decisión, ni escribir. Abrir la lista o
un detalle deja el evento AUDITORIA_CONSULTADA (con la conexión clínica, como los demás eventos),
con los filtros o el id de la consulta y sin datos personales. Contrato en docs/contrato_auditoria.md."""
from datetime import date, datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import UsuarioActual, requiere_permiso
from app.core.auditoria import registrar_evento
from app.core.db import sesion_auditor, sesion_clinica
from app.services import auditoria_consultas as srv

router = APIRouter(tags=["Auditoría"])
PERMISO = "VER_AUDITORIA"
auditor = requiere_permiso(PERMISO)
EVENTO = "AUDITORIA_CONSULTADA"
ENTIDAD = "asistencia.consulta"
MENSAJE_NO_ENCONTRADA = "La consulta no existe"
LIMITE_POR_OMISION, LIMITE_MAXIMO = 20, 100
Estado = Literal["EN_PROCESO", "VERIFICADA", "EVIDENCIA_INSUFICIENTE", "ERROR", "DATOS_FALTANTES",
                 "TAMIZAJE_NO_VIGENTE", "FUERA_DE_DOMINIO", "SOLICITUD_BLOQUEADA"]
_ERRORES = {401: {"description": "Sesión no válida"}, 403: {"description": "El rol no tiene VER_AUDITORIA"},
            422: {"description": "Filtros no válidos"}}


# ---------------------------------------------------------------------------
# Respuestas
# ---------------------------------------------------------------------------
class PorEstado(BaseModel):
    VERIFICADA: int
    EVIDENCIA_INSUFICIENTE: int
    ERROR: int
    SOLICITUD_BLOQUEADA: int
    FUERA_DE_DOMINIO: int
    DATOS_FALTANTES: int
    TAMIZAJE_NO_VIGENTE: int
    EN_PROCESO: int


class Indicadores(BaseModel):
    dias: int = Field(description="Ventana de los indicadores (30 días hasta ahora)")
    desde: datetime
    hasta: datetime
    consultas: int = Field(description="Consultas iniciadas en la ventana, sin las de prueba")
    evaluadas: int = Field(description="VERIFICADA más EVIDENCIA_INSUFICIENTE")
    por_estado: PorEstado
    pct_verificadas: float | None
    pct_evidencia_insuficiente: float | None
    con_reintento: int
    pct_con_reintento: float | None
    latencia_p50_ms: int | None
    latencia_p90_ms: int | None
    latencia_p90_flujo_normal_ms: int | None = Field(description="p90 de las consultas con un intento o sin llamada al modelo")
    solicitudes_bloqueadas: int
    errores: int
    tokens_entrada: int
    tokens_salida: int
    costo_api_usd: float


class ConsultaAuditada(BaseModel):
    id_consulta: str
    fecha_hora_inicio: datetime
    fecha_hora_fin: datetime | None
    nombre_usuario: str = Field(description="Usuario del sistema que hizo la consulta (no el paciente)")
    estado: Estado
    numero_intentos: int
    con_reintento: bool
    latencia_total_ms: int | None
    modo_prueba: bool
    modelo_llm: str | None
    version_prompt: str | None
    tokens_entrada: int | None
    tokens_salida: int | None
    tokens_total: int | None
    costo_usd: float | None


class PaginaAuditoria(BaseModel):
    total: int
    limite: int
    desplazamiento: int
    incluir_pruebas: bool
    consultas: list[ConsultaAuditada]


class VerificacionIntento(BaseModel):
    valida_citas: bool | None = Field(description="6.1 Citas textuales")
    valida_consistencia: bool | None = Field(description="6.2 Consistencia y dosis")
    valida_evidencia: bool | None = Field(description="6.3 Suficiencia de la evidencia")
    relevancia_maxima: float | None
    umbral_relevancia: float | None


class FragmentoAuditado(BaseModel):
    etiqueta: str | None
    puntaje_reranker: float | None
    origen: Literal["RERANKER", "PUNTERO"] | None
    posicion_final: int | None
    documento: str | None
    seccion: str | None
    pagina_inicio: int | None
    pagina_fin: int | None


class IntentoAuditado(BaseModel):
    numero_intento: int
    tipo_busqueda: Literal["INICIAL", "AMPLIADA"] | None
    resultado: str | None
    modelo_llm: str | None
    version_prompt: str | None
    tokens_entrada: int | None
    tokens_salida: int | None
    tokens_razonamiento: int | None
    costo_usd: float | None
    latencia_llm_ms: int | None
    candidatos_evaluados: int | None
    verificacion: VerificacionIntento
    control_identificadores: bool | None = Field(description="Resultado del control previo; false = solicitud bloqueada")
    hash_solicitud: str | None
    solicitud_enviada: dict | None = Field(description="La solicitud registrada; null si no se envió o se bloqueó")
    fragmentos: list[FragmentoAuditado]


class DetalleAuditoria(BaseModel):
    id_consulta: str
    fecha_hora_inicio: datetime
    fecha_hora_fin: datetime | None
    nombre_usuario: str
    estado: Estado
    numero_intentos: int
    latencia_total_ms: int | None
    confirma_tamizaje_no_vigente: bool
    modo_prueba: bool
    tokens_entrada: int | None
    tokens_salida: int | None
    tokens_total: int | None
    costo_usd: float | None
    intentos: list[IntentoAuditado]


# ---------------------------------------------------------------------------
# Rutas
# ---------------------------------------------------------------------------
def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.get("/api/auditoria/indicadores", response_model=Indicadores, responses=_ERRORES)
def indicadores(_: UsuarioActual = Depends(auditor), lectura: Session = Depends(sesion_auditor)) -> dict:
    """Indicadores de los últimos 30 días, siempre sin consultas de prueba."""
    return srv.indicadores(lectura)


@router.get("/api/auditoria/consultas", response_model=PaginaAuditoria, responses=_ERRORES)
def consultas(request: Request,
              estado: Estado | None = Query(None, description="Solo las consultas en este estado"),
              fecha_desde: date | None = Query(None, description="Día de inicio (America/Lima), inclusive"),
              fecha_hasta: date | None = Query(None, description="Último día (America/Lima), inclusive"),
              incluir_pruebas: bool = Query(False, description="Incluir las consultas de prueba (marcadas)"),
              limite: int = Query(LIMITE_POR_OMISION, ge=1, le=LIMITE_MAXIMO),
              desplazamiento: int = Query(0, ge=0),
              usuario: UsuarioActual = Depends(auditor),
              lectura: Session = Depends(sesion_auditor),
              sesion: Session = Depends(sesion_clinica)) -> dict:
    """Todas las consultas, de la más reciente a la más antigua (con la misma fecha y hora, por id)."""
    if fecha_desde and fecha_hasta and fecha_desde > fecha_hasta:
        raise RequestValidationError([{"type": "value_error", "loc": ("query", "fecha_hasta"), "msg": "",
                                       "ctx": {"error": "no puede ser anterior a fecha_desde"}}])
    lista, total = srv.listar(lectura, estado=estado, desde=fecha_desde, hasta=fecha_hasta,
                              incluir_pruebas=incluir_pruebas, limite=limite, desplazamiento=desplazamiento)
    registrar_evento(sesion, EVENTO, usuario.id_usuario, ENTIDAD, None, {
        "vista": "lista", "estado": estado, "fecha_desde": fecha_desde and fecha_desde.isoformat(),
        "fecha_hasta": fecha_hasta and fecha_hasta.isoformat(), "incluir_pruebas": incluir_pruebas,
        "limite": limite, "desplazamiento": desplazamiento, "total": total, "consultas": len(lista)}, _ip(request))
    sesion.commit()
    return {"total": total, "limite": limite, "desplazamiento": desplazamiento, "incluir_pruebas": incluir_pruebas,
            "consultas": lista}


@router.get("/api/auditoria/consultas/{id_consulta}", response_model=DetalleAuditoria,
            responses={**_ERRORES, 404: {"description": "La consulta no existe"}})
def consulta(id_consulta: UUID, request: Request, usuario: UsuarioActual = Depends(auditor),
             lectura: Session = Depends(sesion_auditor), sesion: Session = Depends(sesion_clinica)) -> dict:
    """Detalle de una consulta, sin ningún dato que identifique al paciente."""
    datos = srv.detalle(lectura, str(id_consulta))
    registrar_evento(sesion, EVENTO, usuario.id_usuario, ENTIDAD, str(id_consulta),
                     {"vista": "detalle", "encontrada": datos is not None}, _ip(request))
    sesion.commit()
    if datos is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, MENSAJE_NO_ENCONTRADA)
    return datos
