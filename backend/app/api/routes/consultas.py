"""Parte D2 · API de consultas clínicas (HU06 a HU09 y M05, M06, M07 y M15).

- POST /api/pacientes/{id}/consultas: ejecuta el grafo de D1 y responde por etapas en
  NDJSON (application/x-ndjson): un objeto JSON por línea, el mismo orden de
  ejecutar_consulta(), y al final un evento «fin» o «error».
- GET /api/consultas/{id}: resultado guardado con sus citas.
- POST /api/consultas/{id}/datos-faltantes: completa la hemoglobina y reanuda como consulta
  nueva enlazada a la previa, con el mismo flujo de eventos.
- POST /api/consultas/{id}/decision: decisión del profesional (M07 mínimo).

Permiso REALIZAR_CONSULTA (el Administrador no lo tiene: 403). Cada profesional ve y
decide solo sus consultas: la de otro responde 404, sin revelar que existe, y queda el
evento ACCESO_DENEGADO_CONSULTA. Ningún evento ni respuesta lleva identidad, huellas ni
el texto original; la auditoría guarda solo ids, estados y tipos. El contrato completo
está en docs/contrato_consultas.md."""
import asyncio
import json
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, Literal, Union
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter
from sqlalchemy.orm import Session

from app.api.deps import UsuarioActual, requiere_permiso
from app.core.auditoria import registrar_evento
from app.core.db import engines, sesion_clinica
from app.services import consultas as srv
from app.services import decisiones as dec
from app.services import resultados as res
from app.services.pacientes import datos_permanentes

router = APIRouter(tags=["Consultas"])
realiza_consulta = requiere_permiso("REALIZAR_CONSULTA")
NDJSON = "application/x-ndjson"
ENTIDAD = "asistencia.consulta"
MENSAJE_NO_ENCONTRADA = "La consulta no existe"
Estado = Literal["VERIFICADA", "EVIDENCIA_INSUFICIENTE", "ERROR", "DATOS_FALTANTES", "TAMIZAJE_NO_VIGENTE",
                 "FUERA_DE_DOMINIO", "SOLICITUD_BLOQUEADA"]
TipoDecision = Literal["ACEPTA_RECOMENDACION", "MODIFICA_RECOMENDACION", "CRITERIO_CLINICO_PROPIO"]
Nodo = Literal["validar", "clasificar", "normalizar", "recuperar", "proteger", "generar", "verificar", "salida"]


# ---------------------------------------------------------------------------
# Entradas
# ---------------------------------------------------------------------------
class _Entrada(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")


class ConsultaEntrada(_Entrada):
    texto_consulta: str = Field(min_length=1, max_length=2000, description="Pregunta del profesional (texto libre)")
    id_tamizaje: UUID | None = Field(None, description="Por defecto, el tamizaje más reciente del paciente")
    confirma_tamizaje_no_vigente: bool = Field(False, description="Continuar con un tamizaje que superó la vigencia")
    id_consulta_previa: UUID | None = Field(
        None, description="Consulta que terminó en TAMIZAJE_NO_VIGENTE y que esta reanuda tras la confirmación")


class DatosFaltantesEntrada(_Entrada):
    hemoglobina_g_dl: Decimal = Field(ge=Decimal("3.0"), le=Decimal("20.0"), decimal_places=1)
    metodo_medicion: Literal["HEMOGLOBINOMETRO", "LABORATORIO"] | None = None


class DecisionEntrada(_Entrada):
    tipo_decision: TipoDecision
    nota: str | None = Field(None, max_length=dec.LARGO_MAXIMO_NOTA,
                             description="Obligatoria si opciones_decision indica nota_obligatoria para el tipo")


# ---------------------------------------------------------------------------
# Contrato de salida (también documenta el NDJSON en OpenAPI)
# ---------------------------------------------------------------------------
class Paso(BaseModel):
    tipo: str
    texto: str
    citas: list[str]


class Recomendacion(BaseModel):
    resumen: str
    recomendacion: list[Paso]
    advertencias: list[str]
    factores_identificados: list[str]


class Cita(BaseModel):
    etiqueta: str = Field(description="F-01 a F-05")
    extracto: str = Field(description="Extracto literal del fragmento, en su idioma original")
    extracto_traducido: str | None = None
    etiqueta_traduccion: str | None = Field(None, description="«Traducción de apoyo, no oficial» si hay traducción")
    fuente: str | None = Field(None, description="Código del documento")
    documento: str
    seccion: str | None = None
    pagina_inicio: int | None = None
    pagina_fin: int | None = None
    idioma: str


class Vigencia(BaseModel):
    dias_transcurridos: int | None = None
    dias_vigencia: int | None = None
    continua_con_tamizaje_no_vigente: bool | None = None


class Clasificacion(BaseModel):
    categoria: str
    nivel_riesgo: str
    hb_ajustada_g_dl: float
    ajuste_hb_g_dl: float
    altitud_msnm: int | None = None
    requiere_derivacion: bool


class OpcionDecision(BaseModel):
    tipo: TipoDecision
    nota_obligatoria: bool


class EventoEtapa(BaseModel):
    """Un nodo terminó. Los campos opcionales dependen del nodo."""
    model_config = ConfigDict(extra="allow")
    tipo: Literal["etapa"]
    etapa: Nodo
    intento: int | None = None
    ms: int
    transcurrido_ms: int
    id_consulta: str | None = None
    resultado: str | None = Field(None, description="validar, clasificar y verificar")
    tipo_busqueda: str | None = Field(None, description="recuperar: INICIAL o AMPLIADA")
    relevancia_maxima: float | None = Field(None, description="recuperar")
    suficiente: bool | None = Field(None, description="recuperar")
    control_identificadores: bool | None = Field(None, description="proteger")
    generacion: str | None = Field(None, description="generar")
    siguiente: str | None = Field(None, description="verificar: REGENERAR o AMPLIADA")
    estado_final: str | None = Field(None, description="verificar y salida")


class EventoEnCola(BaseModel):
    tipo: Literal["en_cola"]
    etapa: Nodo
    recurso: Literal["modelos", "llm"]
    transcurrido_ms: int


class EventoFin(BaseModel):
    tipo: Literal["fin"]
    id_consulta: str
    id_paciente: str
    id_consulta_previa: str | None = None
    estado: Estado
    mensaje: str | None = None
    idioma: str | None = None
    datos_faltantes: list[str]
    vigencia: Vigencia
    clasificacion: Clasificacion | None = None
    recomendacion: Recomendacion | None = None
    citas: list[Cita]
    intentos: int
    opciones_decision: list[OpcionDecision]
    tiempos_ms: dict[str, Any] | None = None
    transcurrido_ms: int


class EventoError(BaseModel):
    tipo: Literal["error"]
    id_consulta: str | None = None
    id_paciente: str
    estado: Literal["ERROR"]
    mensaje: str
    opciones_decision: list[OpcionDecision]
    transcurrido_ms: int


EventoConsulta = Annotated[Union[EventoEtapa, EventoEnCola, EventoFin, EventoError], Field(discriminator="tipo")]


class DatoFaltante(BaseModel):
    campo: str
    etiqueta: str
    mensaje: str
    completado: bool


class Decision(BaseModel):
    id_decision: str
    id_usuario: str
    tipo_decision: TipoDecision
    nota: str | None = None
    fecha_registro: datetime


class ResultadoConsulta(BaseModel):
    id_consulta: str
    id_paciente: str
    id_tamizaje: str
    id_consulta_previa: str | None = None
    estado: Estado | Literal["EN_PROCESO"]
    mensaje: str | None = None
    idioma: str
    texto_filtrado: str | None = Field(None, description="Pregunta tras el filtro de identificadores")
    numero_intentos: int
    fecha_hora_inicio: datetime
    fecha_hora_fin: datetime | None = None
    latencia_total_ms: int | None = None
    datos_faltantes: list[DatoFaltante]
    vigencia: Vigencia
    clasificacion: Clasificacion | None = None
    recomendacion: Recomendacion | None = None
    citas: list[Cita]
    decision: Decision | None = None
    opciones_decision: list[OpcionDecision] = Field(
        description="Tipos de decisión admitidos y si cada uno exige nota; vacía si ya hay decisión o no se admite")


def esquemas_eventos() -> dict:
    """Esquemas del NDJSON para components.schemas de OpenAPI (los agrega app.main)."""
    esquema = TypeAdapter(EventoConsulta).json_schema(ref_template="#/components/schemas/{model}")
    definiciones = esquema.pop("$defs", {})
    return {**definiciones, "EventoConsulta": esquema}


_ERRORES = {401: {"description": "Sesión no válida"}, 403: {"description": "El rol no tiene REALIZAR_CONSULTA"},
            404: {"description": "Paciente o consulta inexistente (o de otro profesional)"},
            409: {"description": "La consulta ya se reanudó o el estado no lo admite"},
            422: {"description": "Datos no válidos"}}
_STREAM = {"responses": {"200": {"description": "Un evento JSON por línea (ver EventoConsulta)", "content": {
    NDJSON: {"schema": {"$ref": "#/components/schemas/EventoConsulta"}}}}}}


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------
def entorno_consultas() -> srv.EntornoConsulta:
    """Dependencia que las pruebas reemplazan por un entorno con modelos y cliente falsos."""
    return srv.entorno_por_defecto()


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _linea(evento: dict) -> str:
    return json.dumps(jsonable_encoder(evento), ensure_ascii=False) + "\n"


def _stream(solicitud: srv.SolicitudConsulta, entorno: srv.EntornoConsulta, id_tamizaje: str) -> StreamingResponse:
    async def lineas():
        async for evento in srv.ejecutar_consulta(solicitud, entorno, id_tamizaje):
            yield _linea(evento)
    return StreamingResponse(lineas(), media_type=NDJSON,
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


async def _preparar(solicitud: srv.SolicitudConsulta, entorno: srv.EntornoConsulta) -> str:
    try:
        return await asyncio.to_thread(srv.preparar, solicitud, entorno)
    except srv.ErrorSolicitud as e:
        raise HTTPException(e.codigo, str(e))


def _ficha_propia(sesion: Session, id_consulta: UUID, usuario: UsuarioActual, accion: str,
                  request: Request) -> res.FichaConsulta:
    f = res.ficha(sesion, str(id_consulta))
    if f is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, MENSAJE_NO_ENCONTRADA)
    if f.id_usuario != usuario.id_usuario:
        registrar_evento(sesion, "ACCESO_DENEGADO_CONSULTA", usuario.id_usuario, ENTIDAD, f.id_consulta,
                         {"accion": accion}, _ip(request))
        sesion.commit()
        raise HTTPException(status.HTTP_404_NOT_FOUND, MENSAJE_NO_ENCONTRADA)
    return f


# ---------------------------------------------------------------------------
# Rutas
# ---------------------------------------------------------------------------
@router.post("/api/pacientes/{id_paciente}/consultas", response_class=StreamingResponse, responses=_ERRORES,
             openapi_extra=_STREAM)
async def iniciar_consulta(id_paciente: UUID, datos: ConsultaEntrada, request: Request,
                           usuario: UsuarioActual = Depends(realiza_consulta),
                           sesion: Session = Depends(sesion_clinica),
                           entorno: srv.EntornoConsulta = Depends(entorno_consultas)) -> StreamingResponse:
    """Consulta clínica sobre el tamizaje del paciente, respondida por etapas en NDJSON."""
    if datos_permanentes(sesion, str(id_paciente)) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "El paciente no existe")
    solicitud = srv.SolicitudConsulta(
        str(id_paciente), usuario.id_usuario, datos.texto_consulta,
        str(datos.id_tamizaje) if datos.id_tamizaje else None, datos.confirma_tamizaje_no_vigente,
        str(datos.id_consulta_previa) if datos.id_consulta_previa else None)
    id_tamizaje = await _preparar(solicitud, entorno)
    registrar_evento(sesion, "CONSULTA_INICIADA", usuario.id_usuario, "paciente", str(id_paciente),
                     {"id_tamizaje": id_tamizaje, "id_consulta_previa": solicitud.id_consulta_previa,
                      "confirma_tamizaje_no_vigente": solicitud.confirma_tamizaje_no_vigente}, _ip(request))
    sesion.commit()
    return _stream(solicitud, entorno, id_tamizaje)


@router.get("/api/consultas/{id_consulta}", response_model=ResultadoConsulta, responses=_ERRORES)
def ver_consulta(id_consulta: UUID, request: Request, usuario: UsuarioActual = Depends(realiza_consulta),
                 sesion: Session = Depends(sesion_clinica)) -> dict:
    """Resultado guardado de una consulta propia, con sus citas."""
    f = _ficha_propia(sesion, id_consulta, usuario, "ver", request)
    resultado = res.parte_clinica(sesion, f)
    with engines()["generacion"].connect() as c:
        resultado.update(res.parte_generacion(c, f.id_consulta))
    registrar_evento(sesion, "CONSULTA_VISTA", usuario.id_usuario, ENTIDAD, f.id_consulta, {"estado": f.estado},
                     _ip(request))
    sesion.commit()
    return resultado


@router.post("/api/consultas/{id_consulta}/datos-faltantes", response_class=StreamingResponse, responses=_ERRORES,
             openapi_extra=_STREAM)
async def completar_datos_faltantes(id_consulta: UUID, datos: DatosFaltantesEntrada, request: Request,
                                    usuario: UsuarioActual = Depends(realiza_consulta),
                                    sesion: Session = Depends(sesion_clinica),
                                    entorno: srv.EntornoConsulta = Depends(entorno_consultas)) -> StreamingResponse:
    """M06: completa la hemoglobina del tamizaje y reanuda como consulta nueva enlazada a la previa."""
    f = _ficha_propia(sesion, id_consulta, usuario, "completar_datos", request)
    try:
        campos = res.completar_datos(sesion, f, datos.hemoglobina_g_dl, datos.metodo_medicion)
    except res.ErrorDatos as e:
        sesion.rollback()
        raise HTTPException(e.codigo, str(e))
    registrar_evento(sesion, "TAMIZAJE_COMPLETADO", usuario.id_usuario, "tamizaje", f.id_tamizaje,
                     {"id_consulta": f.id_consulta, "campos": campos}, _ip(request))
    texto = res.leer_texto_original(sesion, f.id_consulta)
    sesion.commit()
    solicitud = srv.SolicitudConsulta(f.id_paciente, usuario.id_usuario, texto, f.id_tamizaje,
                                      f.confirma_tamizaje_no_vigente, f.id_consulta)
    id_tamizaje = await _preparar(solicitud, entorno)
    registrar_evento(sesion, "CONSULTA_INICIADA", usuario.id_usuario, "paciente", f.id_paciente,
                     {"id_tamizaje": id_tamizaje, "id_consulta_previa": f.id_consulta,
                      "confirma_tamizaje_no_vigente": f.confirma_tamizaje_no_vigente}, _ip(request))
    sesion.commit()
    return _stream(solicitud, entorno, id_tamizaje)


@router.post("/api/consultas/{id_consulta}/decision", response_model=Decision, status_code=status.HTTP_201_CREATED,
             responses=_ERRORES)
def registrar_decision(id_consulta: UUID, datos: DecisionEntrada, request: Request,
                       usuario: UsuarioActual = Depends(realiza_consulta),
                       sesion: Session = Depends(sesion_clinica)) -> dict:
    """M07 mínimo: «Registrar decisión clínica». Solo el profesional de la consulta."""
    f = _ficha_propia(sesion, id_consulta, usuario, "decidir", request)
    try:
        decision = dec.registrar_decision(sesion, f.id_consulta, f.estado, usuario.id_usuario, datos.tipo_decision,
                                          datos.nota)
    except dec.ErrorDecision as e:
        sesion.rollback()
        raise HTTPException(e.codigo, str(e))
    registrar_evento(sesion, "DECISION_REGISTRADA", usuario.id_usuario, ENTIDAD, f.id_consulta,
                     {"tipo_decision": datos.tipo_decision, "con_nota": decision["nota"] is not None}, _ip(request))
    sesion.commit()
    return decision
