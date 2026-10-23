"""Dependencias comunes: usuario autenticado y control de acceso por permisos (RBAC)."""
from dataclasses import dataclass

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.db import sesion_clinica
from app.core.seguridad import leer_token

_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class UsuarioActual:
    id_usuario: str
    nombre_usuario: str
    nombre_completo: str
    rol: str
    permisos: frozenset[str]


def cargar_usuario(sesion: Session, id_usuario: str) -> UsuarioActual | None:
    fila = sesion.execute(
        text(
            """SELECT u.id_usuario::text, u.nombre_usuario, u.nombre_completo, r.nombre AS rol, u.activo,
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
                         fila["rol"], frozenset(fila["permisos"]))


def usuario_actual(
    credenciales: HTTPAuthorizationCredentials | None = Depends(_bearer),
    sesion: Session = Depends(sesion_clinica),
) -> UsuarioActual:
    no_autorizado = HTTPException(status.HTTP_401_UNAUTHORIZED, "Sesión no válida o expirada",
                                  headers={"WWW-Authenticate": "Bearer"})
    if credenciales is None:
        raise no_autorizado
    try:
        datos = leer_token(credenciales.credentials)
    except jwt.PyJWTError:
        raise no_autorizado
    usuario = cargar_usuario(sesion, datos.get("sub", ""))
    if usuario is None:
        raise no_autorizado
    return usuario


def requiere_permiso(codigo: str):
    """Uso: @router.get(..., dependencies=[Depends(requiere_permiso("REALIZAR_CONSULTA"))])"""

    def _verificar(usuario: UsuarioActual = Depends(usuario_actual)) -> UsuarioActual:
        if codigo not in usuario.permisos:
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Su rol no tiene el permiso {codigo}")
        return usuario

    return _verificar
