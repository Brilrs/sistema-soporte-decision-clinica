"""Parte E1a del Sprint 3 · API de solo lectura de los parámetros (M12, HU14).

- GET /api/parametros: grupos editables (puntos de corte, ajuste por altitud y vigencia del tamizaje)
  con su versión, valores, documento, referencia, motivo y verificado; grupos de solo lectura (riesgo
  por clasificación, recuperación, modelo e indexación); puede_editar y modo_evaluacion.
- GET /api/parametros/historial: versiones paginadas, de la más reciente a la más antigua.
- GET /api/parametros/huella: SHA-256 de la configuración vigente, con sus componentes.

Permiso VER_PARAMETROS (Coordinador CRED y Administrador); los roles clínicos reciben 403. La edición
(PUT por grupo, con CONFIGURAR_PARAMETROS, solo el Coordinador) es la parte E1b. Se lee con la
conexión clínica, que solo tiene SELECT sobre configuracion. Contrato en docs/contrato_parametros.md."""
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import UsuarioActual, requiere_permiso
from app.core.db import sesion_clinica
from app.core.evaluacion import modo_evaluacion_activo
from app.services import parametros as srv

router = APIRouter(tags=["Parámetros"])
lector = requiere_permiso("VER_PARAMETROS")
PERMISO_EDICION = "CONFIGURAR_PARAMETROS"
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
