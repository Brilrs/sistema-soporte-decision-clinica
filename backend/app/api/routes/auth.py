"""HU01 · Iniciar sesión (pantalla M01)."""
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import UsuarioActual, cargar_usuario, usuario_actual
from app.core.auditoria import registrar_evento
from app.core.config import get_settings
from app.core.db import sesion_clinica
from app.core.seguridad import crear_token, verificar_contrasena

router = APIRouter(prefix="/api/auth", tags=["Autenticación"])

MENSAJE_GENERICO = "Usuario o contraseña incorrectos"


class SolicitudLogin(BaseModel):
    usuario: str = Field(min_length=1, max_length=50)
    contrasena: str = Field(min_length=1, max_length=200)


class UsuarioSalida(BaseModel):
    id_usuario: str
    nombre_usuario: str
    nombre_completo: str
    rol: str
    permisos: list[str]


class RespuestaLogin(BaseModel):
    token: str
    tipo: str = "bearer"
    expira_en_segundos: int
    usuario: UsuarioSalida


def _salida(u: UsuarioActual) -> UsuarioSalida:
    return UsuarioSalida(id_usuario=u.id_usuario, nombre_usuario=u.nombre_usuario,
                         nombre_completo=u.nombre_completo, rol=u.rol, permisos=sorted(u.permisos))


@router.post("/login", response_model=RespuestaLogin)
def login(datos: SolicitudLogin, request: Request, sesion: Session = Depends(sesion_clinica)) -> RespuestaLogin:
    ip = request.client.host if request.client else None
    max_intentos = get_settings().max_intentos_fallidos
    cuenta = sesion.execute(
        text("""SELECT id_usuario::text AS id, hash_contrasena, activo, intentos_fallidos
                  FROM seguridad.usuario WHERE nombre_usuario = :u"""),
        {"u": datos.usuario.strip().lower()},
    ).mappings().first()

    if cuenta is None:
        registrar_evento(sesion, "INICIO_SESION_FALLIDO", detalle={"motivo": "usuario_inexistente"}, direccion_ip=ip)
        sesion.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, MENSAJE_GENERICO)

    if not cuenta["activo"]:
        registrar_evento(sesion, "INICIO_SESION_FALLIDO", cuenta["id"], "usuario", cuenta["id"],
                         {"motivo": "cuenta_inactiva"}, ip)
        sesion.commit()
        raise HTTPException(status.HTTP_403_FORBIDDEN, "La cuenta está desactivada. Comuníquese con el administrador.")

    if cuenta["intentos_fallidos"] >= max_intentos:
        registrar_evento(sesion, "INICIO_SESION_FALLIDO", cuenta["id"], "usuario", cuenta["id"],
                         {"motivo": "cuenta_bloqueada"}, ip)
        sesion.commit()
        raise HTTPException(status.HTTP_423_LOCKED,
                            "La cuenta está bloqueada por intentos fallidos. Solicite el desbloqueo al administrador.")

    if not verificar_contrasena(cuenta["hash_contrasena"], datos.contrasena):
        intentos = cuenta["intentos_fallidos"] + 1
        sesion.execute(text("UPDATE seguridad.usuario SET intentos_fallidos = :n WHERE id_usuario = CAST(:id AS uuid)"),
                       {"n": intentos, "id": cuenta["id"]})
        registrar_evento(sesion, "INICIO_SESION_FALLIDO", cuenta["id"], "usuario", cuenta["id"],
                         {"motivo": "contrasena_incorrecta", "intento": intentos}, ip)
        sesion.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, MENSAJE_GENERICO)

    sesion.execute(
        text("UPDATE seguridad.usuario SET intentos_fallidos = 0, ultimo_acceso = now() WHERE id_usuario = CAST(:id AS uuid)"),
        {"id": cuenta["id"]},
    )
    usuario = cargar_usuario(sesion, cuenta["id"])
    registrar_evento(sesion, "INICIO_SESION", usuario.id_usuario, "usuario", usuario.id_usuario, None, ip)
    token, segundos = crear_token(usuario.id_usuario, usuario.rol)
    return RespuestaLogin(token=token, expira_en_segundos=segundos, usuario=_salida(usuario))


@router.get("/me", response_model=UsuarioSalida)
def me(usuario: UsuarioActual = Depends(usuario_actual)) -> UsuarioSalida:
    return _salida(usuario)
