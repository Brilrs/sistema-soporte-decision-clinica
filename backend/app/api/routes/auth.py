"""HU01 · Iniciar sesión (pantalla M01) y cambio de la propia contraseña (Sprint 3, parte I).

Contrato en docs/contrato_autenticacion.md."""
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import CODIGO_SESION_REVOCADA, MENSAJE_SESION_NO_VALIDA, UsuarioActual, cargar_usuario, \
    usuario_actual_sin_bloqueo
from app.core.auditoria import registrar_evento
from app.core.config import get_settings
from app.core.db import sesion_clinica
from app.core.errores import ErrorConCodigo
from app.core.seguridad import crear_token, cumple_politica, hash_contrasena, texto_politica, verificar_contrasena

router = APIRouter(prefix="/api/auth", tags=["Autenticación"])

MENSAJE_GENERICO = "Usuario o contraseña incorrectos"
MENSAJE_BLOQUEADA = "La cuenta está bloqueada por intentos fallidos. Solicite el desbloqueo al administrador."
MENSAJE_ACTUAL_INCORRECTA = "La contraseña actual no es correcta."
MENSAJE_IGUAL = "La nueva contraseña debe ser distinta de la actual."


class SolicitudLogin(BaseModel):
    usuario: str = Field(min_length=1, max_length=50)
    contrasena: str = Field(min_length=1, max_length=200)


class SolicitudCambioContrasena(BaseModel):
    contrasena_actual: str = Field(min_length=1, max_length=200)
    contrasena_nueva: str = Field(min_length=1, max_length=200)


class UsuarioSalida(BaseModel):
    id_usuario: str
    nombre_usuario: str
    nombre_completo: str
    rol: str
    permisos: list[str]
    debe_cambiar_contrasena: bool
    # Política vigente (CONTRASENA_LONGITUD_MINIMA), para escribirla en la pantalla de cambio
    contrasena_longitud_minima: int


class RespuestaLogin(BaseModel):
    token: str
    tipo: str = "bearer"
    expira_en_segundos: int
    usuario: UsuarioSalida


def _salida(u: UsuarioActual) -> UsuarioSalida:
    return UsuarioSalida(id_usuario=u.id_usuario, nombre_usuario=u.nombre_usuario,
                         nombre_completo=u.nombre_completo, rol=u.rol, permisos=sorted(u.permisos),
                         debe_cambiar_contrasena=u.debe_cambiar_contrasena,
                         contrasena_longitud_minima=get_settings().contrasena_longitud_minima)


def _respuesta_con_token(u: UsuarioActual) -> RespuestaLogin:
    token, segundos = crear_token(u.id_usuario, u.rol, u.version_sesion)
    return RespuestaLogin(token=token, expira_en_segundos=segundos, usuario=_salida(u))


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.post("/login", response_model=RespuestaLogin)
def login(datos: SolicitudLogin, request: Request, sesion: Session = Depends(sesion_clinica)) -> RespuestaLogin:
    ip = _ip(request)
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
        raise HTTPException(status.HTTP_423_LOCKED, MENSAJE_BLOQUEADA)

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
    # Con la marca de cambio obligatorio el inicio de sesión funciona igual: la interfaz lleva a la
    # pantalla de cambio y el resto de las rutas responde 403 (deps.usuario_actual).
    return _respuesta_con_token(usuario)


@router.get("/me", response_model=UsuarioSalida)
def me(usuario: UsuarioActual = Depends(usuario_actual_sin_bloqueo)) -> UsuarioSalida:
    return _salida(usuario)


@router.post("/cambiar-contrasena", response_model=RespuestaLogin, responses={
    401: {"description": "Contraseña actual incorrecta (CONTRASENA_ACTUAL_INCORRECTA) o sesión no válida"},
    422: {"description": "La nueva no cumple la política (POLITICA_CONTRASENA) o es igual a la actual "
                         "(CONTRASENA_IGUAL)"},
    423: {"description": "Cuenta bloqueada por intentos fallidos (CUENTA_BLOQUEADA)"},
})
def cambiar_contrasena(datos: SolicitudCambioContrasena, request: Request, respuesta: Response,
                       usuario: UsuarioActual = Depends(usuario_actual_sin_bloqueo),
                       sesion: Session = Depends(sesion_clinica)) -> RespuestaLogin:
    """Cambia la contraseña del propio usuario, con la marca de cambio obligatorio activa o no.
    La contraseña actual equivocada cuenta como intento fallido (el mismo contador y máximo del
    inicio de sesión). Si el cambio se hace, sube la versión de sesión: todas las sesiones anteriores
    del usuario dejan de valer, y la respuesta trae un token nuevo para que esta continúe."""
    ip = _ip(request)
    max_intentos = get_settings().max_intentos_fallidos
    # La fila queda bloqueada hasta el fin de la transacción: dos cambios simultáneos se ordenan.
    cuenta = sesion.execute(text(
        """SELECT hash_contrasena, intentos_fallidos, version_sesion, debe_cambiar_contrasena
             FROM seguridad.usuario WHERE id_usuario = CAST(:id AS uuid) FOR UPDATE"""),
        {"id": usuario.id_usuario}).mappings().one()
    if cuenta["version_sesion"] != usuario.version_sesion:
        # Otro cambio terminó mientras esta solicitud esperaba: este token ya no vale.
        raise ErrorConCodigo(status.HTTP_401_UNAUTHORIZED, MENSAJE_SESION_NO_VALIDA, CODIGO_SESION_REVOCADA,
                             headers={"WWW-Authenticate": "Bearer"})

    def fallido(motivo: str, **detalle) -> None:
        registrar_evento(sesion, "CAMBIO_CONTRASENA_FALLIDO", usuario.id_usuario, "usuario", usuario.id_usuario,
                         {"motivo": motivo, **detalle}, ip)
        sesion.commit()

    if cuenta["intentos_fallidos"] >= max_intentos:
        fallido("cuenta_bloqueada")
        raise ErrorConCodigo(status.HTTP_423_LOCKED, MENSAJE_BLOQUEADA, "CUENTA_BLOQUEADA")

    if not verificar_contrasena(cuenta["hash_contrasena"], datos.contrasena_actual):
        intentos = cuenta["intentos_fallidos"] + 1
        sesion.execute(text("UPDATE seguridad.usuario SET intentos_fallidos = :n WHERE id_usuario = CAST(:id AS uuid)"),
                       {"n": intentos, "id": usuario.id_usuario})
        fallido("contrasena_actual_incorrecta", intento=intentos)
        raise ErrorConCodigo(status.HTTP_401_UNAUTHORIZED, MENSAJE_ACTUAL_INCORRECTA, "CONTRASENA_ACTUAL_INCORRECTA",
                             campo="contrasena_actual")

    if not cumple_politica(datos.contrasena_nueva):
        sesion.rollback()
        raise ErrorConCodigo(422, f"La nueva contraseña no cumple la política: {texto_politica().lower()}.",
                             "POLITICA_CONTRASENA", campo="contrasena_nueva")
    if datos.contrasena_nueva == datos.contrasena_actual:
        sesion.rollback()
        raise ErrorConCodigo(422, MENSAJE_IGUAL, "CONTRASENA_IGUAL", campo="contrasena_nueva")

    sesion.execute(text(
        """UPDATE seguridad.usuario
              SET hash_contrasena = :h, debe_cambiar_contrasena = false, version_sesion = version_sesion + 1,
                  fecha_cambio_contrasena = now(), intentos_fallidos = 0
            WHERE id_usuario = CAST(:id AS uuid)"""),
        {"h": hash_contrasena(datos.contrasena_nueva), "id": usuario.id_usuario})
    # Sin contraseñas ni hash en la bitácora: solo si el cambio era obligatorio.
    registrar_evento(sesion, "CONTRASENA_CAMBIADA", usuario.id_usuario, "usuario", usuario.id_usuario,
                     {"obligatorio": cuenta["debe_cambiar_contrasena"]}, ip)
    actualizado = cargar_usuario(sesion, usuario.id_usuario)
    sesion.commit()
    respuesta.headers["Cache-Control"] = "no-store"
    return _respuesta_con_token(actualizado)
