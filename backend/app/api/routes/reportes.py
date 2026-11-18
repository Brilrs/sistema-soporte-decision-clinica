"""Sprint 3, parte C1 · API del reporte exportable (M09, HU10). Contrato: docs/contrato_reportes.md.

- GET /api/consultas/{id}/reportes/vista-previa?destino=...&secciones=...: contenido estructurado
  del reporte en JSON, sin número, sin hash y sin escribir en asistencia.reporte.
- POST /api/consultas/{id}/reportes: genera el PDF en memoria con ReportLab, registra el reporte
  (número EV-AAAA-NNNNN, destino, secciones, usuario, fecha y SHA-256 del PDF) y lo entrega como
  adjunto. Cada exportación es un reporte nuevo; los anteriores no se vuelven a entregar.
- GET /api/consultas/{id}/reportes: reportes emitidos de la consulta, sin el PDF.

Permiso EXPORTAR_REPORTE. Solo consultas propias, con la misma convención que las rutas de
consultas (404 para la de otro, con ACCESO_DENEGADO_CONSULTA). Solo consultas con resultado
(VERIFICADA o EVIDENCIA_INSUFICIENTE): en otro estado, 409. Los eventos de auditoría no llevan
datos del paciente. Nada de esta parte usa el modelo de lenguaje."""
from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api.deps import UsuarioActual, requiere_permiso
from app.api.routes.consultas import ENTIDAD, _ficha_propia, _ip
from app.core.auditoria import registrar_evento
from app.core.config import get_settings
from app.core.db import engines, sesion_clinica
from app.reportes import contenido as cont
from app.services import reportes as srv

router = APIRouter(tags=["Reportes"])
exporta_reporte = requiere_permiso("EXPORTAR_REPORTE")
Destino = Literal["EXPEDIENTE", "CUIDADOR"]
Seccion = Literal["PACIENTE", "CLASIFICACION", "RECOMENDACION", "EVIDENCIAS", "ADVERTENCIAS", "VERIFICACION",
                  "DECISION", "FIRMA"]
MENSAJE_SIN_RESULTADO = ("Solo se puede exportar el reporte de una consulta verificada o con evidencia insuficiente "
                         "(estado actual: {estado})")
SIN_CACHE = {"Cache-Control": "no-store"}


class ReporteEntrada(BaseModel):
    model_config = ConfigDict(extra="forbid")
    destino: Destino
    secciones: list[Seccion] = Field(default_factory=list, max_length=len(cont.TITULOS),
                                     description="Secciones opcionales elegidas; las obligatorias se agregan siempre")
    formato: Literal["PDF"] = "PDF"


class Campo(BaseModel):
    etiqueta: str
    valor: str


class Item(BaseModel):
    texto: str
    detalle: list[str]


class Bloque(BaseModel):
    seccion: str = Field(description="Sección del reporte (RECUERDE: indicaciones generales del reporte para el cuidador)")
    titulo: str
    campos: list[Campo]
    parrafos: list[str]
    items: list[Item]


class VistaPrevia(BaseModel):
    """Contenido del reporte tal como sale en el PDF, sin número ni fecha de emisión."""
    id_consulta: str
    destino: Destino
    secciones: list[Seccion] = Field(description="Secciones incluidas (obligatorias y elegidas), en el orden del reporte")
    modo_prueba: bool
    revision_pendiente: bool = Field(description="Reporte del cuidador con frases aún no aprobadas (revisado: false)")
    titulo: str
    introduccion: str | None = None
    establecimiento: str
    fecha_consulta: datetime
    avisos: list[str] = Field(description="Líneas que se repiten en cada página del PDF")
    bloques: list[Bloque]
    frase_final: str
    firma: bool
    generado_por: str


class ReporteListado(BaseModel):
    numero_reporte: str
    destino: Destino
    secciones: list[Seccion]
    formato: Literal["PDF", "IMPRESION"]
    fecha_generacion: datetime
    hash_documento: str | None = None


_ERRORES = {401: {"description": "Sesión no válida"}, 403: {"description": "El rol no tiene EXPORTAR_REPORTE"},
            404: {"description": "Consulta inexistente (o de otro profesional)"},
            409: {"description": "La consulta no tiene resultado (solo VERIFICADA o EVIDENCIA_INSUFICIENTE)"},
            422: {"description": "Destino, sección o formato no válidos"}}


def _invalida(ubicacion: str, campo: str, mensaje: str) -> RequestValidationError:
    return RequestValidationError([{"type": "value_error", "loc": (ubicacion, campo), "msg": "", "ctx": {"error": mensaje}}])


def _secciones(destino: str, elegidas: list[str], ubicacion: str) -> list[str]:
    try:
        return cont.secciones_finales(destino, elegidas)
    except cont.SeccionInvalida as e:
        raise _invalida(ubicacion, "secciones", str(e))


def _contenido(sesion: Session, id_consulta: UUID, usuario: UsuarioActual, accion: str, request: Request,
               destino: str, secciones: list[str]) -> dict:
    f = _ficha_propia(sesion, id_consulta, usuario, accion, request)
    if f.estado not in cont.ESTADOS_CON_RESULTADO:
        raise HTTPException(status.HTTP_409_CONFLICT, MENSAJE_SIN_RESULTADO.format(estado=f.estado))
    with engines()["generacion"].connect() as c:
        datos = cont.leer_datos(sesion, c, f)
    return cont.armar(datos, destino, secciones, usuario.nombre_completo, get_settings().establecimiento, f.id_consulta)


@router.get("/api/consultas/{id_consulta}/reportes/vista-previa", response_model=VistaPrevia, responses=_ERRORES)
def vista_previa(id_consulta: UUID, request: Request, response: Response,
                 destino: Destino = Query(..., description="EXPEDIENTE o CUIDADOR"),
                 secciones: list[str] = Query([], description="Secciones opcionales, repetidas o separadas por comas"),
                 usuario: UsuarioActual = Depends(exporta_reporte),
                 sesion: Session = Depends(sesion_clinica)) -> dict:
    """Contenido del reporte para la vista previa de M09. No reserva número ni escribe en
    asistencia.reporte; deja el evento REPORTE_VISTA_PREVIA (sin datos del paciente)."""
    elegidas = [s.strip() for valor in secciones for s in valor.split(",") if s.strip()]
    finales = _secciones(destino, elegidas, "query")
    contenido = _contenido(sesion, id_consulta, usuario, "vista_previa_reporte", request, destino, finales)
    registrar_evento(sesion, "REPORTE_VISTA_PREVIA", usuario.id_usuario, ENTIDAD, contenido["id_consulta"],
                     {"destino": destino, "secciones": len(finales), "modo_prueba": contenido["modo_prueba"]}, _ip(request))
    sesion.commit()
    response.headers.update(SIN_CACHE)
    return contenido


@router.post("/api/consultas/{id_consulta}/reportes", status_code=status.HTTP_201_CREATED, response_class=Response,
             responses={**_ERRORES, 201: {"description": "PDF del reporte (adjunto)", "content": {"application/pdf": {}},
                                          "headers": {"X-Reporte-Numero": {"description": "EV-AAAA-NNNNN"},
                                                      "X-Reporte-Hash": {"description": "SHA-256 del cuerpo"}}}})
def exportar(id_consulta: UUID, datos: ReporteEntrada, request: Request,
             usuario: UsuarioActual = Depends(exporta_reporte),
             sesion: Session = Depends(sesion_clinica)) -> Response:
    """Genera el PDF en memoria, registra el reporte con el SHA-256 de los bytes entregados y lo
    devuelve como adjunto. El nombre del archivo es el número del reporte, sin datos del paciente."""
    finales = _secciones(datos.destino, list(datos.secciones), "body")
    contenido = _contenido(sesion, id_consulta, usuario, "exportar_reporte", request, datos.destino, finales)
    emitido = srv.emitir(sesion, contenido, contenido["id_consulta"], usuario.id_usuario)
    registrar_evento(sesion, "REPORTE_GENERADO", usuario.id_usuario, ENTIDAD, contenido["id_consulta"],
                     {"numero_reporte": emitido.numero, "destino": datos.destino, "secciones": len(finales),
                      "hash_prefijo": emitido.hash_documento[:12], "modo_prueba": contenido["modo_prueba"]}, _ip(request))
    sesion.commit()
    return Response(content=emitido.pdf, status_code=status.HTTP_201_CREATED, media_type="application/pdf", headers={
        **SIN_CACHE, "Content-Disposition": f'attachment; filename="{emitido.numero}.pdf"',
        "X-Reporte-Numero": emitido.numero, "X-Reporte-Hash": emitido.hash_documento})


@router.get("/api/consultas/{id_consulta}/reportes", response_model=list[ReporteListado], responses=_ERRORES)
def reportes_de_la_consulta(id_consulta: UUID, request: Request, usuario: UsuarioActual = Depends(exporta_reporte),
                            sesion: Session = Depends(sesion_clinica)) -> list[dict]:
    """Reportes emitidos de una consulta propia, del más reciente al más antiguo (sin el PDF)."""
    f = _ficha_propia(sesion, id_consulta, usuario, "listar_reportes", request)
    return srv.listar(sesion, f.id_consulta)
