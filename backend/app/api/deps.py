"""Dependencias comunes: usuario autenticado y control de acceso por permisos (RBAC).

usuario_actual es la dependencia de todas las rutas autenticadas: además de validar el token,
responde 403 con el código CAMBIO_CONTRASENA_OBLIGATORIO mientras la cuenta tenga la marca
debe_cambiar_contrasena. Solo GET /api/auth/me y POST /api/auth/cambiar-contrasena usan
usuario_actual_sin_bloqueo; así, una ruta nueva queda protegida por omisión."""
from dataclasses import dataclass

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.db import sesion_clinica
from app.core.errores import ErrorConCodigo
from app.core.seguridad import leer_token

_bearer = HTTPBearer(auto_error=False)

MENSAJE_SESION_NO_VALIDA = "Sesión no válida o expirada"
CODIGO_SESION_NO_VALIDA = "SESION_NO_VALIDA"
# Token bien firmado y vigente, pero de una versión de sesión anterior (contraseña cambiada o
# restablecida, o cuenta reactivada). La interfaz lo distingue para explicar el cierre de sesión.
CODIGO_SESION_REVOCADA = "SESION_REVOCADA"
CODIGO_CAMBIO_OBLIGATORIO = "CAMBIO_CONTRASENA_OBLIGATORIO"
MENSAJE_CAMBIO_OBLIGATORIO = "Debe cambiar su contraseña antes de continuar."


@dataclass(frozen=True)
class UsuarioActual:
    id_usuario: str
    nombre_usuario: str
    nombre_completo: str
    rol: str
    permisos: frozenset[str]
    debe_cambiar_contrasena: bool = False
    version_sesion: int = 0


def cargar_usuario(sesion: Session, id_usuario: str) -> UsuarioActual | None:
    fila = sesion.execute(
        text(
            """SELECT u.id_usuario::text, u.nombre_usuario, u.nombre_completo, r.nombre AS rol, u.activo,
                      u.debe_cambiar_contrasena, u.version_sesion,
                      coalesce(array_agg(p.codigo) FILTER (WHERE p.codigo IS NOT NULL), '{}') AS permisos
                 FROM seguridad.usuario u
                 JOIN seguridad.rol r ON r.id_rol = u.id_rol
                 LEFT JOIN seguridad.rol_permiso rp ON rp.id_rol = u.id_rol
                 LEFT JOIN seguridad.permiso p ON p.id_permiso = rp.id_permiso
                WHERE u.id_usuario = CAST(:id AS uuid)
                GROUP BY u.id_usuario, r.nombre"""
        ),
        {"id": id_usuario},
    ).mappings().first()
    if fila is None or not fila["activo"]:
        return None
    return UsuarioActual(fila["id_usuario"], fila["nombre_usuario"], fila["nombre_completo"],
                         fila["rol"], frozenset(fila["permisos"]), fila["debe_cambiar_contrasena"],
                         fila["version_sesion"])


def _no_autorizado(codigo: str = CODIGO_SESION_NO_VALIDA) -> ErrorConCodigo:
    return ErrorConCodigo(status.HTTP_401_UNAUTHORIZED, MENSAJE_SESION_NO_VALIDA, codigo,
                          headers={"WWW-Authenticate": "Bearer"})


def usuario_actual_sin_bloqueo(
    credenciales: HTTPAuthorizationCredentials | None = Depends(_bearer),
    sesion: Session = Depends(sesion_clinica),
) -> UsuarioActual:
    """Valida el token y la versión de sesión, sin mirar la marca de cambio obligatorio.
    Solo para /api/auth/me y /api/auth/cambiar-contrasena."""
    if credenciales is None:
        raise _no_autorizado()
    try:
        datos = leer_token(credenciales.credentials)
    except jwt.PyJWTError:
        raise _no_autorizado()
    usuario = cargar_usuario(sesion, str(datos.get("sub", "")))
    if usuario is None:
        raise _no_autorizado()
    # Un token emitido antes de la migración 018 no tiene sv: cuenta como 0.
    version = datos.get("sv", 0)
    if type(version) is not int or version != usuario.version_sesion:
        raise _no_autorizado(CODIGO_SESION_REVOCADA)
    return usuario


def usuario_actual(usuario: UsuarioActual = Depends(usuario_actual_sin_bloqueo)) -> UsuarioActual:
    if usuario.debe_cambiar_contrasena:
        raise ErrorConCodigo(status.HTTP_403_FORBIDDEN, MENSAJE_CAMBIO_OBLIGATORIO, CODIGO_CAMBIO_OBLIGATORIO)
    return usuario


def requiere_permiso(codigo: str):
    """Uso: @router.get(..., dependencies=[Depends(requiere_permiso("REALIZAR_CONSULTA"))])"""

    def _verificar(usuario: UsuarioActual = Depends(usuario_actual)) -> UsuarioActual:
        if codigo not in usuario.permisos:
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Su rol no tiene el permiso {codigo}")
        return usuario

    return _verificar


def requiere_algun_permiso(*codigos: str):
    """Permite el acceso si el rol tiene al menos uno de los permisos indicados.
    Se usa en las rutas de lectura de pacientes (registro o consulta clínica)."""

    def _verificar(usuario: UsuarioActual = Depends(usuario_actual)) -> UsuarioActual:
        if usuario.permisos.isdisjoint(codigos):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Su rol no tiene acceso a esta información")
        return usuario

    return _verificar
