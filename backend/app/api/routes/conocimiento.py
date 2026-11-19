"""HU12 · Base de conocimiento (pantalla M11, parte F2b).

Solo con el permiso ADMINISTRAR_GUIAS y la conexión cdss_admin (sin acceso a datos clínicos).
La subida es un solo multipart; las validaciones van en este orden: extensión .pdf (415), firma
%PDF- (415), tamaño máximo cortado mientras se copia (413), SHA-256 repetido (409), metadatos
(422) y nivel distinto de 2 (422). Los metadatos se validan en la ruta, no como parámetros de
FastAPI, para respetar ese orden. El archivo se guarda con el id del documento, nunca con el
nombre enviado, y ninguna respuesta lleva rutas del servidor. Contrato en docs/contrato_conocimiento.md.

Retiro (HU17, Sprint 3 parte F): GET .../referencias y POST .../retiro. La guía pasa a OBSOLETA y se
conserva; el trabajo RETIRO del indexador actualiza después los metadatos de ChromaDB."""
import logging
from datetime import date, datetime
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.datastructures import UploadFile

from app.api.deps import UsuarioActual, requiere_permiso
from app.core.auditoria import registrar_evento
from app.core.db import sesion_admin
from app.core.evaluacion import bloquear_en_evaluacion
from app.services import conocimiento as srv

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/conocimiento", tags=["Base de conocimiento"])
administrador = requiere_permiso(srv.PERMISO)
ENTIDAD = "documento_fuente"
CAMPOS = ("titulo", "codigo_documento", "entidad_emisora", "tipo_documento", "anio_publicacion", "idioma", "nivel",
          "pagina_inicio_cuerpo", "pagina_fin_cuerpo")
MENSAJE_NO_ENCONTRADO = "La guía no existe"


# ---------------------------------------------------------------------------
# Modelos
# ---------------------------------------------------------------------------
class MetadatosGuia(BaseModel):
    """Valores que admite conocimiento.documento_fuente. nivel acepta 1 o 2 aquí; que sea 2 se
    comprueba después, con su propio mensaje."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    titulo: str = Field(min_length=3, max_length=255)
    codigo_documento: str | None = Field(None, max_length=80)
    entidad_emisora: Literal["MINSA", "OMS", "OTRA"]
    tipo_documento: Literal["NORMA_TECNICA", "GUIA", "DIRECTIVA", "RESOLUCION", "LITERATURA"]
    anio_publicacion: int = Field(ge=1948)
    idioma: Literal["es", "en"]
    nivel: int = Field(ge=1, le=2)
    pagina_inicio_cuerpo: int | None = Field(None, ge=1, le=32767)
    pagina_fin_cuerpo: int | None = Field(None, ge=1, le=32767)

    @field_validator("codigo_documento", "pagina_inicio_cuerpo", "pagina_fin_cuerpo", mode="before")
    @classmethod
    def _vacio_es_nulo(cls, v):
        return None if isinstance(v, str) and not v.strip() else v

    @field_validator("anio_publicacion")
    @classmethod
    def _anio(cls, v: int) -> int:
        if v > date.today().year:
            raise ValueError("el año de publicación no puede ser posterior al actual")
        return v

    @model_validator(mode="after")
    def _paginas(self):
        inicio, fin = self.pagina_inicio_cuerpo, self.pagina_fin_cuerpo
        if (inicio is None) != (fin is None):
            raise ValueError("indique la página de inicio y la de fin del cuerpo, o ninguna")
        if inicio is not None and inicio > fin:
            raise ValueError("la página de inicio del cuerpo no puede ser mayor que la de fin")
        return self


class TrabajoResumen(BaseModel):
    id_trabajo: str
    tipo: str
    estado: str
    etapa: str | None
    procesados: int
    total: int | None
    mensaje_error: str | None
    fecha_solicitud: datetime
    fecha_fin: datetime | None


class DocumentoSalida(BaseModel):
    id_documento: str
    titulo: str
    codigo_documento: str | None
    entidad_emisora: str
    tipo_documento: str
    nivel: int
    version: str | None
    version_indexacion: int | None
    anio_publicacion: int
    idioma: str
    estado: str
    estado_indexacion: str
    fecha_carga: datetime
    fragmentos_vigentes: int
    citas_30_dias: int
    retirado_por: str | None
    fecha_retiro: datetime | None
    motivo_retiro: str | None
    ultimo_trabajo: TrabajoResumen | None


class TrabajoSalida(BaseModel):
    id_trabajo: str
    id_documento: str
    titulo: str
    tipo: str
    estado: str
    etapa: str | None
    procesados: int
    total: int | None
    mensaje_error: str | None
    fecha_solicitud: datetime
    fecha_inicio: datetime | None
    fecha_fin: datetime | None
    solicitado_por: str


class VersionIndexacion(BaseModel):
    version_indexacion: int
    fragmentos: int
    vigentes: int
    modelo_embedding: str | None


class DetalleDocumento(DocumentoSalida):
    fecha_publicacion: date | None
    pagina_inicio_cuerpo: int | None
    pagina_fin_cuerpo: int | None
    hash_archivo: str | None
    total_fragmentos: int
    cargado_por: str
    versiones: list[VersionIndexacion]
    trabajos: list[TrabajoSalida]


class DocumentoCreado(BaseModel):
    documento: DocumentoSalida
    trabajo: TrabajoSalida


class ReintentoSalida(BaseModel):
    trabajo: TrabajoSalida


class Referencia(BaseModel):
    tipo: Literal["UMBRAL_HEMOGLOBINA", "AJUSTE_ALTITUD", "PARAMETRO_SISTEMA", "MODIFICACION", "MAPA_MODIFICACIONES",
                  "PUNTERO"]
    descripcion: str


class ReferenciasSalida(BaseModel):
    id_documento: str
    nivel: int
    estado: str
    codigo_confirmacion: str | None
    referencias: list[Referencia]
    puede_retirarse: bool


class RetiroEntrada(BaseModel):
    """El largo del motivo se comprueba en la ruta, después del modo de evaluación."""
    model_config = ConfigDict(extra="forbid")

    motivo: str = Field(max_length=2000)
    confirmacion: str | None = Field(None, max_length=255)


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------
def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _rechazar(sesion: Session, actor: UsuarioActual, request: Request, e: srv.ErrorGuia,
              id_entidad: str | None = None) -> HTTPException:
    """Deshace lo pendiente, deja la auditoría del rechazo (si tiene motivo) en su propia
    transacción y devuelve la excepción HTTP: la dependencia de la sesión haría rollback."""
    sesion.rollback()
    if e.motivo:
        registrar_evento(sesion, "GUIA_CARGA_RECHAZADA", actor.id_usuario, ENTIDAD, id_entidad,
                         {"motivo": e.motivo, **e.detalle}, _ip(request))
        sesion.commit()
    return HTTPException(e.codigo, str(e))


def _mensaje_validacion(error: ValidationError) -> str:
    partes = []
    for err in error.errors():
        campo = ".".join(str(x) for x in err["loc"]) or "datos"
        partes.append(f"{campo}: {err['msg'].removeprefix('Value error, ')}")
    return "Metadatos no válidos. " + "; ".join(partes)


def _trabajo(sesion: Session, id_trabajo: str) -> dict:
    return srv.trabajo(sesion, id_trabajo)


# ---------------------------------------------------------------------------
# Lectura
# ---------------------------------------------------------------------------
@router.get("/documentos", response_model=list[DocumentoSalida])
def listar(_: UsuarioActual = Depends(administrador), sesion: Session = Depends(sesion_admin)) -> list[dict]:
    """Guías de nivel 1 primero; dentro de cada nivel, vigentes antes que obsoletas, año
    descendente, título e id (orden estable)."""
    return srv.listar_documentos(sesion)


@router.get("/trabajos", response_model=list[TrabajoSalida])
def trabajos(activos: bool = Query(False, description="true: solo PENDIENTE y EN_CURSO"),
             _: UsuarioActual = Depends(administrador), sesion: Session = Depends(sesion_admin)) -> list[dict]:
    return srv.listar_trabajos(sesion, activos)


@router.get("/documentos/{id_documento}", response_model=DetalleDocumento)
def ver(id_documento: UUID, _: UsuarioActual = Depends(administrador),
        sesion: Session = Depends(sesion_admin)) -> dict:
    d = srv.detalle(sesion, str(id_documento))
    if d is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, MENSAJE_NO_ENCONTRADO)
    return d


# ---------------------------------------------------------------------------
# Subida
# ---------------------------------------------------------------------------
@router.post("/documentos", response_model=DocumentoCreado, status_code=status.HTTP_201_CREATED)
async def cargar(request: Request, actor: UsuarioActual = Depends(administrador),
                 sesion: Session = Depends(sesion_admin)) -> dict:
    """Multipart con el campo archivo y los metadatos como campos de texto. La copia del archivo
    y el trabajo con la base van en el grupo de hilos, fuera del bucle de eventos."""
    # Modo de evaluación (OE3): 423 antes de leer el archivo.
    await run_in_threadpool(bloquear_en_evaluacion, sesion, actor.id_usuario, "CARGAR_GUIA", ENTIDAD, None, _ip(request))
    p = srv.parametros_subida()
    await run_in_threadpool(_capacidad, sesion, actor, request)
    async with request.form(max_files=1, max_fields=len(CAMPOS) + 1) as formulario:
        archivo = formulario.get("archivo")
        if not isinstance(archivo, UploadFile):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Falta el archivo PDF (campo archivo)")
        campos = {k: v for k, v in formulario.items() if k != "archivo"}
        return await run_in_threadpool(_cargar, sesion, actor, request, p, archivo.filename, archivo.file, campos)


def _capacidad(sesion: Session, actor: UsuarioActual, request: Request) -> None:
    """Antes de leer el archivo, para no recibir 20 MB que se van a rechazar."""
    try:
        srv.comprobar_capacidad(sesion)
    except srv.ErrorGuia as e:
        raise _rechazar(sesion, actor, request, e)


def _cargar(sesion: Session, actor: UsuarioActual, request: Request, p: srv.ParametrosSubida,
            nombre: str | None, origen, campos: dict) -> dict:
    try:
        recibido = srv.recibir_pdf(nombre, origen, p)
    except srv.ErrorGuia as e:
        raise _rechazar(sesion, actor, request, e)
    destino = None
    try:
        existente = srv.documento_con_hash(sesion, recibido.sha256)
        if existente:
            raise srv.ErrorGuia(409, f"Este archivo ya está cargado como «{existente['titulo']}»", "duplicado",
                                {"id_documento_existente": existente["id_documento"]})
        try:
            datos = MetadatosGuia.model_validate(campos)
        except ValidationError as e:
            raise srv.ErrorGuia(422, _mensaje_validacion(e))
        if datos.nivel != srv.NIVEL_API:
            raise srv.ErrorGuia(422, srv.MENSAJE_NIVEL_1, "nivel", {"nivel": datos.nivel})

        id_documento = str(uuid4())
        srv.bloquear_cola(sesion)  # dos subidas a la vez no pasan juntas el límite de trabajos activos
        srv.comprobar_capacidad(sesion)
        id_trabajo = srv.insertar_documento(sesion, id_documento, datos.model_dump(include=set(CAMPOS)), recibido,
                                            actor.id_usuario)
        registrar_evento(sesion, "GUIA_CARGADA", actor.id_usuario, ENTIDAD, id_documento,
                         {"id_documento": id_documento, "nivel": datos.nivel, "tipo_documento": datos.tipo_documento,
                          "entidad_emisora": datos.entidad_emisora, "anio_publicacion": datos.anio_publicacion,
                          "idioma": datos.idioma, "tamano_bytes": recibido.tamano, "sha256": recibido.sha256},
                         _ip(request))
        sesion.flush()
        destino = srv.destino_final(p, id_documento)
        srv.mover(recibido.temporal, destino)  # antes del commit: si el commit falla, se borra abajo
        sesion.commit()
    except srv.ErrorGuia as e:
        _borrar(recibido.temporal, destino)
        raise _rechazar(sesion, actor, request, e)
    except IntegrityError:
        # Otra subida del mismo archivo ganó la carrera entre la comprobación y el INSERT.
        _borrar(recibido.temporal, destino)
        sesion.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Este archivo ya está cargado")
    except BaseException:
        _borrar(recibido.temporal, destino)
        sesion.rollback()
        raise
    return {"documento": srv.documento(sesion, id_documento), "trabajo": _trabajo(sesion, id_trabajo)}


def _borrar(*rutas) -> None:
    for r in rutas:
        if r is not None:
            try:
                r.unlink(missing_ok=True)
            except OSError:
                log.exception("No se pudo borrar un archivo de una subida fallida")


# ---------------------------------------------------------------------------
# Reintento
# ---------------------------------------------------------------------------
@router.post("/documentos/{id_documento}/reintentar", response_model=ReintentoSalida,
             status_code=status.HTTP_201_CREATED)
def reintentar(id_documento: UUID, request: Request, actor: UsuarioActual = Depends(administrador),
               sesion: Session = Depends(sesion_admin)) -> dict:
    bloquear_en_evaluacion(sesion, actor.id_usuario, "REINTENTAR_INDEXACION", ENTIDAD, str(id_documento), _ip(request))
    try:
        srv.bloquear_cola(sesion)
        id_trabajo, tipo = srv.reintentar(sesion, str(id_documento), actor.id_usuario)
    except srv.ErrorGuia as e:
        sesion.rollback()
        raise HTTPException(e.codigo, str(e))
    evento = "GUIA_RETIRO_REINTENTADO" if tipo == "RETIRO" else "GUIA_REINDEXACION_SOLICITADA"
    registrar_evento(sesion, evento, actor.id_usuario, ENTIDAD, str(id_documento),
                     {"id_trabajo": id_trabajo, "tipo": tipo}, _ip(request))
    sesion.flush()
    return {"trabajo": _trabajo(sesion, id_trabajo)}


# ---------------------------------------------------------------------------
# Retiro (HU17)
# ---------------------------------------------------------------------------
@router.get("/documentos/{id_documento}/referencias", response_model=ReferenciasSalida)
def referencias(id_documento: UUID, _: UsuarioActual = Depends(administrador),
                sesion: Session = Depends(sesion_admin)) -> dict:
    """Referencias vigentes que bloquean el retiro de una guía de nivel 1; lista vacía en el nivel 2."""
    r = srv.referencias_de(sesion, str(id_documento))
    if r is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, MENSAJE_NO_ENCONTRADO)
    return r


@router.post("/documentos/{id_documento}/retiro", response_model=DocumentoCreado,
             status_code=status.HTTP_201_CREATED,
             responses={409: {"description": "YA_OBSOLETA, TRABAJO_ACTIVO o REFERENCIAS_VIGENTES (con la lista)"},
                        422: {"description": "MOTIVO_INVALIDO o CONFIRMACION_INCORRECTA"},
                        423: {"description": "Modo de evaluación"}})
def retirar(id_documento: UUID, entrada: RetiroEntrada, request: Request, actor: UsuarioActual = Depends(administrador),
            sesion: Session = Depends(sesion_admin)):
    """Orden: permiso, modo de evaluación (423), motivo (422), candado de la cola, guía existente (404),
    ya obsoleta (409), trabajo activo (409), referencias del nivel 1 (409 con la lista), confirmación
    del nivel 1 (422) y, en una transacción, OBSOLETA, el trabajo RETIRO y el evento GUIA_RETIRADA."""
    id_doc = str(id_documento)
    bloquear_en_evaluacion(sesion, actor.id_usuario, "RETIRAR_GUIA", ENTIDAD, id_doc, _ip(request))
    try:
        motivo = srv.validar_motivo(entrada.motivo)
        srv.bloquear_cola(sesion)
        datos, id_trabajo = srv.retirar(sesion, id_doc, motivo, entrada.confirmacion, actor.id_usuario)
    except srv.ErrorRetiro as e:
        sesion.rollback()
        return JSONResponse(status_code=e.estado, content=e.cuerpo())
    # Sin datos personales: ni el nombre de quien retira (va en id_usuario del evento) ni el título.
    registrar_evento(sesion, "GUIA_RETIRADA", actor.id_usuario, ENTIDAD, id_doc, datos, _ip(request))
    sesion.flush()
    return {"documento": srv.documento(sesion, id_doc), "trabajo": _trabajo(sesion, id_trabajo)}
