"""Parte E1a del Sprint 3 · API de solo lectura de los parámetros (M12, HU14).

- GET /api/parametros: grupos editables (puntos de corte, ajuste por altitud y vigencia del tamizaje)
  con su versión, valores, documento, referencia, motivo y verificado; grupos de solo lectura (riesgo
  por clasificación, recuperación, modelo e indexación); puede_editar y modo_evaluacion.
- GET /api/parametros/historial: versiones paginadas, de la más reciente a la más antigua.
- GET /api/parametros/huella: SHA-256 de la configuración vigente, con sus componentes.

Permiso VER_PARAMETROS (Coordinador CRED y Administrador); los roles clínicos reciben 403. Se lee con
la conexión clínica, que solo tiene SELECT sobre configuracion.

Edición (parte E1b), con CONFIGURAR_PARAMETROS (solo el Coordinador CRED) y la conexión de cdss_admin:
- PUT /api/parametros/puntos-corte, PUT /api/parametros/ajuste-altitud y
  PUT /api/parametros/vigencia-tamizaje, cada uno con la tabla completa del grupo, la versión del GET
  (409 si cambió), motivo_cambio, referencia, id_documento y confirmacion_escrita. 423 en modo de
  evaluación; 422 con el formato del proyecto, REQUIERE_CONFIRMACION o SIN_CAMBIOS.
Contrato en docs/contrato_parametros.md."""
from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from app.api.deps import UsuarioActual, requiere_permiso
from app.core.db import sesion_admin, sesion_clinica
from app.core.evaluacion import bloquear_en_evaluacion, modo_evaluacion_activo
from app.services import parametros as srv
from app.services import parametros_edicion as edicion

router = APIRouter(tags=["Parámetros"])
lector = requiere_permiso("VER_PARAMETROS")
PERMISO_EDICION = "CONFIGURAR_PARAMETROS"
editor = requiere_permiso(PERMISO_EDICION)
LIMITE_POR_OMISION, LIMITE_MAXIMO = 20, 100
Grupo = Literal["puntos_corte", "ajuste_altitud", "vigencia_tamizaje", "recuperacion", "modelo", "indexacion"]
_ERRORES = {401: {"description": "Sesión no válida"}, 403: {"description": "El rol no tiene VER_PARAMETROS"}}


class Documento(BaseModel):
    id_documento: str
    codigo: str | None
    titulo: str


class Comunes(BaseModel):
    documento: Documento | None = Field(description="Norma de la que procede el valor")
    referencia: str | None = Field(description="Tabla y página de la norma")
    motivo_cambio: str | None
    verificado: bool = Field(description="Contrastado con la norma; falso: pendiente de verificación")
    vigente_desde: datetime
    modificado_por: str = Field(description="Nombre del usuario que registró la versión")


class Categoria(Comunes):
    id_umbral: int
    categoria: str
    nivel_riesgo: str
    hb_min_g_dl: float | None
    hb_max_g_dl: float | None


class Tramo(BaseModel):
    edad_min_meses: int
    edad_max_meses: int
    categorias: list[Categoria]


class PuntosCorte(BaseModel):
    version: str
    tramos: list[Tramo]


class Rango(Comunes):
    id_ajuste: int
    altitud_min_msnm: int
    altitud_max_msnm: int
    ajuste_g_dl: float


class AjusteAltitud(BaseModel):
    version: str
    rangos: list[Rango]


class Parametro(Comunes):
    id_parametro: int
    clave: str
    valor: str
    tipo_dato: str
    valor_minimo: float | None
    valor_maximo: float | None
    descripcion: str


class VigenciaTamizaje(Parametro):
    version: str


class Riesgo(BaseModel):
    nombre: str
    nivel_riesgo: str
    requiere_derivacion: bool
    orden: int


class Parametros(BaseModel):
    puede_editar: bool = Field(description="El usuario tiene CONFIGURAR_PARAMETROS")
    modo_evaluacion: bool = Field(description="CDSS_MODO_EVALUACION: las ediciones responden 423")
    puntos_corte: PuntosCorte
    ajuste_altitud: AjusteAltitud
    vigencia_tamizaje: VigenciaTamizaje
    riesgo: list[Riesgo]
    recuperacion: list[Parametro]
    modelo: list[Parametro]
    indexacion: list[Parametro]


class VersionHistorial(Comunes):
    grupo: Grupo
    tabla: Literal["umbral_hemoglobina", "ajuste_altitud", "parametro_sistema"]
    id: int
    elemento: str
    valores: dict
    vigente_hasta: datetime | None
    vigente: bool


class PaginaHistorial(BaseModel):
    total: int
    limite: int
    desplazamiento: int
    grupo: Grupo | None
    versiones: list[VersionHistorial]


class Componente(BaseModel):
    nombre: str
    huella: str
    elementos: int


class DocumentoIndexado(BaseModel):
    id_documento: str
    codigo: str | None
    version_indexacion: int


class Huella(BaseModel):
    huella: str = Field(description="SHA-256 de las huellas de los componentes")
    algoritmo: Literal["SHA-256"]
    calculada_en: datetime
    version_prompt: str | None
    componentes: list[Componente]
    indexacion: list[DocumentoIndexado]


@router.get("/api/parametros", response_model=Parametros, responses=_ERRORES)
def parametros(usuario: UsuarioActual = Depends(lector), sesion: Session = Depends(sesion_clinica)) -> dict:
    return srv.parametros(sesion, puede_editar=PERMISO_EDICION in usuario.permisos,
                          modo_evaluacion=modo_evaluacion_activo())


@router.get("/api/parametros/historial", response_model=PaginaHistorial,
            responses={**_ERRORES, 422: {"description": "Filtros no válidos"}})
def historial(grupo: Grupo | None = Query(None, description="Un grupo; sin él, todos"),
              limite: int = Query(LIMITE_POR_OMISION, ge=1, le=LIMITE_MAXIMO),
              desplazamiento: int = Query(0, ge=0),
              _: UsuarioActual = Depends(lector), sesion: Session = Depends(sesion_clinica)) -> dict:
    versiones, total = srv.historial(sesion, grupo, limite, desplazamiento)
    return {"total": total, "limite": limite, "desplazamiento": desplazamiento, "grupo": grupo, "versiones": versiones}


@router.get("/api/parametros/huella", response_model=Huella, responses=_ERRORES)
def huella(_: UsuarioActual = Depends(lector), sesion: Session = Depends(sesion_clinica)) -> dict:
    return srv.huella(sesion)


# ---------------------------------------------------------------------------
# Edición (parte E1b)
# ---------------------------------------------------------------------------
class EdicionComun(BaseModel):
    """Lo común a los tres PUT. Se ignoran los campos de más, para que el frontend reenvíe las filas
    tal como las leyó del GET (con id, documento, motivo y demás)."""
    model_config = ConfigDict(extra="ignore")
    version: str = Field(pattern=r"^[0-9a-f]{64}$", description="La versión del grupo leída en el GET")
    motivo_cambio: str = Field(description="De 10 a 500 caracteres; se guarda en cada versión nueva")
    referencia: str | None = Field(None, max_length=200,
                                   description="Norma, tabla y página; obligatoria si algún valor queda verificado")
    id_documento: UUID | None = Field(None, description="La norma; sin ella, se conserva la de cada versión anterior")
    confirmacion_escrita: str | None = Field(None, description="CONFIRMO, cuando el cambio tiene advertencias")

    @field_validator("motivo_cambio")
    @classmethod
    def _motivo(cls, v: str) -> str:
        v = v.strip()
        if not 10 <= len(v) <= 500:
            raise ValueError("debe tener entre 10 y 500 caracteres")
        return v

    @field_validator("referencia")
    @classmethod
    def _referencia(cls, v: str | None) -> str | None:
        return (v.strip() or None) if v is not None else None


class CategoriaEntrada(BaseModel):
    model_config = ConfigDict(extra="ignore")
    categoria: str
    hb_min_g_dl: Decimal | None
    hb_max_g_dl: Decimal | None
    verificado: bool = False


class TramoEntrada(BaseModel):
    model_config = ConfigDict(extra="ignore")
    edad_min_meses: int
    edad_max_meses: int
    categorias: list[CategoriaEntrada]


class PuntosCorteEntrada(EdicionComun):
    tramos: list[TramoEntrada]


class RangoEntrada(BaseModel):
    model_config = ConfigDict(extra="ignore")
    altitud_min_msnm: int
    altitud_max_msnm: int
    ajuste_g_dl: Decimal
    verificado: bool = False


class AjusteAltitudEntrada(EdicionComun):
    rangos: list[RangoEntrada]


class VigenciaEntrada(EdicionComun):
    valor: int = Field(description="Días; el GET lo da como texto y se acepta igual")
    verificado: bool = False


class Cambio(BaseModel):
    elemento: str
    antes: dict | None
    despues: dict | None


class Resumen(BaseModel):
    grupo: Literal["puntos_corte", "ajuste_altitud", "vigencia_tamizaje"]
    cerrados: list[int]
    creados: list[int]
    cambios: list[Cambio]
    advertencias_confirmadas: list[str]


class EdicionPuntosCorte(BaseModel):
    grupo: PuntosCorte
    resumen: Resumen


class EdicionAjusteAltitud(BaseModel):
    grupo: AjusteAltitud
    resumen: Resumen


class EdicionVigencia(BaseModel):
    grupo: VigenciaTamizaje
    resumen: Resumen


_ERRORES_EDICION = {
    401: {"description": "Sesión no válida"},
    403: {"description": "El rol no tiene CONFIGURAR_PARAMETROS"},
    409: {"description": "VERSION_DESACTUALIZADA: los parámetros cambiaron desde el GET (incluye version_actual)"},
    422: {"description": "Errores de validación, REQUIERE_CONFIRMACION (con advertencias) o SIN_CAMBIOS"},
    423: {"description": "Modo de evaluación (CDSS_MODO_EVALUACION)"},
}


def _datos(entrada: EdicionComun, usuario: UsuarioActual) -> edicion.Edicion:
    return edicion.Edicion(version=entrada.version, motivo_cambio=entrada.motivo_cambio, referencia=entrada.referencia,
                           id_documento=str(entrada.id_documento) if entrada.id_documento else None,
                           confirmacion_escrita=entrada.confirmacion_escrita, id_usuario=usuario.id_usuario)


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _guardar(sesion: Session, funcion, *argumentos):
    """Ejecuta la edición; un ErrorEdicion se responde con su código y cuerpo, sin escribir nada."""
    try:
        return funcion(sesion, *argumentos)
    except edicion.ErrorEdicion as e:
        sesion.rollback()
        return JSONResponse(status_code=e.estado, content=e.cuerpo())


@router.put("/api/parametros/puntos-corte", response_model=EdicionPuntosCorte, responses=_ERRORES_EDICION)
def editar_puntos_corte(entrada: PuntosCorteEntrada, request: Request, usuario: UsuarioActual = Depends(editor),
                        sesion: Session = Depends(sesion_admin)):
    bloquear_en_evaluacion(sesion, usuario.id_usuario, "EDITAR_PUNTOS_CORTE", "configuracion.umbral_hemoglobina",
                           None, _ip(request))
    return _guardar(sesion, edicion.editar_puntos_corte, _datos(entrada, usuario),
                    [t.model_dump() for t in entrada.tramos])


@router.put("/api/parametros/ajuste-altitud", response_model=EdicionAjusteAltitud, responses=_ERRORES_EDICION)
def editar_ajuste_altitud(entrada: AjusteAltitudEntrada, request: Request, usuario: UsuarioActual = Depends(editor),
                          sesion: Session = Depends(sesion_admin)):
    bloquear_en_evaluacion(sesion, usuario.id_usuario, "EDITAR_AJUSTE_ALTITUD", "configuracion.ajuste_altitud",
                           None, _ip(request))
    return _guardar(sesion, edicion.editar_ajuste_altitud, _datos(entrada, usuario),
                    [r.model_dump() for r in entrada.rangos])


@router.put("/api/parametros/vigencia-tamizaje", response_model=EdicionVigencia, responses=_ERRORES_EDICION)
def editar_vigencia(entrada: VigenciaEntrada, request: Request, usuario: UsuarioActual = Depends(editor),
                    sesion: Session = Depends(sesion_admin)):
    bloquear_en_evaluacion(sesion, usuario.id_usuario, "EDITAR_VIGENCIA_TAMIZAJE", "configuracion.parametro_sistema",
                           None, _ip(request))
    return _guardar(sesion, edicion.editar_vigencia, _datos(entrada, usuario), entrada.valor, entrada.verificado)
