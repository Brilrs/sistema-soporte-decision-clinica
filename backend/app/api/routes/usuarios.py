"""HU11 · Gestionar usuarios (pantalla M10).

Solo para roles con el permiso ADMINISTRAR_USUARIOS; usa la conexión de administración
(cdss_admin). Las contraseñas las genera el sistema y se devuelven una sola vez, en la
respuesta de creación o de restablecimiento (sin caché). Nunca se guardan en la auditoría
ni se devuelve el hash."""
import re
from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import UsuarioActual, requiere_permiso
from app.core.auditoria import registrar_evento
from app.core.config import get_settings
from app.core.db import sesion_admin
from app.services import usuarios as srv

router = APIRouter(prefix="/api/usuarios", tags=["Usuarios"])

administrador = requiere_permiso(srv.PERMISO_ADMINISTRACION)

MENSAJE_NO_ENCONTRADO = "El usuario no existe"
DATOS_NO_VALIDOS = 422
_USUARIO = re.compile(r"^[a-z][a-z0-9]*(\.[a-z0-9]+)*$")
_CORREO = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# ---------------------------------------------------------------------------
# Modelos de entrada
# ---------------------------------------------------------------------------
class _Entrada(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    @field_validator("nombre_completo", check_fields=False)
    @classmethod
    def _nombre(cls, v: str | None) -> str | None:
        if v is not None:
            v = " ".join(v.split())
            if len(v) < 3:
                raise ValueError("El nombre completo debe tener al menos 3 caracteres")
        return v

    @field_validator("correo_institucional", check_fields=False)
    @classmethod
    def _correo(cls, v: str | None) -> str | None:
        if not v:
            return None
        v = v.lower()
        if not _CORREO.match(v):
            raise ValueError("El correo institucional no tiene un formato válido")
        return v


class UsuarioNuevo(_Entrada):
    nombre_completo: str = Field(min_length=3, max_length=150)
    nombre_usuario: str = Field(min_length=3, max_length=50)
    correo_institucional: str | None = Field(None, max_length=150)
    id_rol: int

    @field_validator("nombre_usuario")
    @classmethod
    def _usuario(cls, v: str) -> str:
        v = v.lower()
        if not _USUARIO.match(v):
            raise ValueError("El usuario solo admite letras minúsculas sin tildes, números y puntos "
                             "(p. ej., enf.rojas), y debe empezar con una letra")
        return v


class UsuarioCambios(_Entrada):
    """El nombre de usuario no se modifica después de creado (trazabilidad)."""
    nombre_completo: str | None = Field(None, min_length=3, max_length=150)
    correo_institucional: str | None = Field(None, max_length=150)
    id_rol: int | None = None

    @field_validator("nombre_completo", "id_rol")
    @classmethod
    def _obligatorio(cls, v):
        if v is None:
            raise ValueError("no puede quedar vacío")
        return v


# ---------------------------------------------------------------------------
# Modelos de salida (sin hash de contraseña)
# ---------------------------------------------------------------------------
class UsuarioSalida(BaseModel):
    id_usuario: str
    nombre_completo: str
    nombre_usuario: str
    correo_institucional: str | None
    id_rol: int
    rol: str
    activo: bool
    bloqueado: bool
    estado: Literal["ACTIVO", "INACTIVO", "BLOQUEADO"]
    ultimo_acceso: datetime | None
    fecha_creacion: datetime
    fecha_desactivacion: datetime | None


class Permiso(BaseModel):
    codigo: str
    descripcion: str


class Rol(BaseModel):
    id_rol: int
    nombre: str
    descripcion: str | None
    activo: bool
    permisos: list[str]


class RolesYPermisos(BaseModel):
    permisos: list[Permiso]
    roles: list[Rol]


class UsuarioConContrasena(BaseModel):
    """Respuesta de creación y de restablecimiento de contraseña."""
    usuario: UsuarioSalida
    contrasena_temporal: str = Field(description="Se muestra una sola vez; no se puede recuperar después")


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------
def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _max_intentos() -> int:
    return get_settings().max_intentos_fallidos


def _usuario_o_404(sesion: Session, id_usuario: UUID) -> dict:
    datos = srv.obtener(sesion, str(id_usuario), _max_intentos())
    if datos is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, MENSAJE_NO_ENCONTRADO)
    return datos


def _error_negocio(exc: Exception) -> HTTPException:
    if isinstance(exc, srv.ErrorConflicto):
        return HTTPException(status.HTTP_409_CONFLICT, str(exc))
    return HTTPException(DATOS_NO_VALIDOS, str(exc))


def _sin_cache(respuesta: Response) -> None:
    """Las respuestas con una contraseña no deben quedar en la caché del navegador ni de un proxy."""
    respuesta.headers["Cache-Control"] = "no-store"
    respuesta.headers["Pragma"] = "no-cache"


# ---------------------------------------------------------------------------
# Consulta
# ---------------------------------------------------------------------------
@router.get("", response_model=list[UsuarioSalida])
def listar(_: UsuarioActual = Depends(administrador), sesion: Session = Depends(sesion_admin)) -> list[dict]:
    return srv.listar(sesion, _max_intentos())


@router.get("/roles", response_model=RolesYPermisos)
def roles(_: UsuarioActual = Depends(administrador), sesion: Session = Depends(sesion_admin)) -> dict:
    """Catálogo de permisos y los permisos que otorga cada rol (casillas de M10)."""
    return srv.roles_y_permisos(sesion)


@router.get("/{id_usuario}", response_model=UsuarioSalida)
def ver(id_usuario: UUID, _: UsuarioActual = Depends(administrador), sesion: Session = Depends(sesion_admin)) -> dict:
    return _usuario_o_404(sesion, id_usuario)


# ---------------------------------------------------------------------------
# Creación y edición
# ---------------------------------------------------------------------------
@router.post("", response_model=UsuarioConContrasena, status_code=status.HTTP_201_CREATED)
def crear(datos: UsuarioNuevo, request: Request, respuesta: Response, actor: UsuarioActual = Depends(administrador),
          sesion: Session = Depends(sesion_admin)) -> dict:
    try:
        id_usuario, rol, contrasena = srv.crear(
            sesion, nombre_completo=datos.nombre_completo, nombre_usuario=datos.nombre_usuario,
            correo=datos.correo_institucional, id_rol=datos.id_rol)
    except (srv.ErrorDatos, srv.ErrorConflicto) as exc:
        sesion.rollback()
        raise _error_negocio(exc)
    except IntegrityError:
        # Otra cuenta con el mismo usuario o correo se guardó al mismo tiempo
        sesion.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Ya existe una cuenta con ese usuario o correo institucional")
    registrar_evento(sesion, "USUARIO_CREADO", actor.id_usuario, "usuario", id_usuario,
                     {"nombre_usuario": datos.nombre_usuario, "rol": rol}, _ip(request))
    sesion.commit()
    _sin_cache(respuesta)
    return {"usuario": srv.obtener(sesion, id_usuario, _max_intentos()), "contrasena_temporal": contrasena}


@router.patch("/{id_usuario}", response_model=UsuarioSalida)
def actualizar(id_usuario: UUID, cambios: UsuarioCambios, request: Request,
               actor: UsuarioActual = Depends(administrador), sesion: Session = Depends(sesion_admin)) -> dict:
    actual = _usuario_o_404(sesion, id_usuario)
    enviados = cambios.model_dump(include=cambios.model_fields_set)
    if not enviados:
        raise HTTPException(DATOS_NO_VALIDOS, "No se envió ningún dato para actualizar")
    try:
        detalle = srv.actualizar(sesion, actor.id_usuario, actual, enviados)
    except (srv.ErrorDatos, srv.ErrorConflicto) as exc:
        sesion.rollback()
        raise _error_negocio(exc)
    except IntegrityError:
        sesion.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Ya existe una cuenta con ese correo institucional")
    if detalle["campos"]:
        registrar_evento(sesion, "USUARIO_MODIFICADO", actor.id_usuario, "usuario", str(id_usuario), detalle, _ip(request))
    sesion.commit()
    return srv.obtener(sesion, str(id_usuario), _max_intentos())


# ---------------------------------------------------------------------------
# Estado de la cuenta
# ---------------------------------------------------------------------------
def _cambiar_estado(id_usuario: UUID, request: Request, actor: UsuarioActual, sesion: Session,
                    accion, tipo_evento: str) -> dict:
    actual = _usuario_o_404(sesion, id_usuario)
    try:
        accion(actual)
    except srv.ErrorConflicto as exc:
        sesion.rollback()
        raise _error_negocio(exc)
    registrar_evento(sesion, tipo_evento, actor.id_usuario, "usuario", str(id_usuario),
                     {"nombre_usuario": actual["nombre_usuario"]}, _ip(request))
    sesion.commit()
    return srv.obtener(sesion, str(id_usuario), _max_intentos())


@router.post("/{id_usuario}/desactivar", response_model=UsuarioSalida)
def desactivar(id_usuario: UUID, request: Request, actor: UsuarioActual = Depends(administrador),
               sesion: Session = Depends(sesion_admin)) -> dict:
    """La cuenta no se elimina: deja de poder iniciar sesión y conserva su trazabilidad."""
    return _cambiar_estado(id_usuario, request, actor, sesion,
                           lambda u: srv.desactivar(sesion, actor.id_usuario, u), "USUARIO_DESACTIVADO")


@router.post("/{id_usuario}/reactivar", response_model=UsuarioSalida)
def reactivar(id_usuario: UUID, request: Request, actor: UsuarioActual = Depends(administrador),
              sesion: Session = Depends(sesion_admin)) -> dict:
    return _cambiar_estado(id_usuario, request, actor, sesion,
                           lambda u: srv.reactivar(sesion, u), "USUARIO_REACTIVADO")


@router.post("/{id_usuario}/desbloquear", response_model=UsuarioSalida)
def desbloquear(id_usuario: UUID, request: Request, actor: UsuarioActual = Depends(administrador),
                sesion: Session = Depends(sesion_admin)) -> dict:
    """Reinicia los intentos fallidos de una cuenta bloqueada."""
    return _cambiar_estado(id_usuario, request, actor, sesion,
                           lambda u: srv.desbloquear(sesion, u), "USUARIO_DESBLOQUEADO")


@router.post("/{id_usuario}/restablecer-contrasena", response_model=UsuarioConContrasena)
def restablecer_contrasena(id_usuario: UUID, request: Request, respuesta: Response,
                           actor: UsuarioActual = Depends(administrador),
                           sesion: Session = Depends(sesion_admin)) -> dict:
    """Genera una contraseña nueva (también desbloquea la cuenta). Las sesiones abiertas con la
    contraseña anterior siguen vigentes hasta que vence su token (ver docs/mejoras_despliegue.md)."""
    actual = _usuario_o_404(sesion, id_usuario)
    contrasena = srv.restablecer_contrasena(sesion, actual)
    registrar_evento(sesion, "CONTRASENA_RESTABLECIDA", actor.id_usuario, "usuario", str(id_usuario),
                     {"nombre_usuario": actual["nombre_usuario"], "estaba_bloqueada": actual["bloqueado"]},
                     _ip(request))
    sesion.commit()
    _sin_cache(respuesta)
    return {"usuario": srv.obtener(sesion, str(id_usuario), _max_intentos()), "contrasena_temporal": contrasena}
