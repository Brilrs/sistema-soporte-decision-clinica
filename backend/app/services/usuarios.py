"""Gestión de usuarios (IAdministración): cuentas del personal, roles y estado.

Trabaja solo con la conexión del componente de administración (cdss_admin). Las
consultas nunca leen ni devuelven el hash de la contraseña. Las cuentas no se
eliminan: se desactivan, para conservar la trazabilidad de la auditoría."""
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.seguridad import generar_contrasena, hash_contrasena

PERMISO_ADMINISTRACION = "ADMINISTRAR_USUARIOS"
# Usuario técnico de las cargas iniciales (02_catalogos.sql): no se lista ni se modifica
ID_USUARIO_SISTEMA = "00000000-0000-0000-0000-000000000001"


class ErrorDatos(Exception):
    """Datos que no cumplen una regla del negocio (se responde con 422)."""


class ErrorConflicto(Exception):
    """Usuario o correo ya registrados, o una acción que contradice el estado de las cuentas (409)."""


_COLUMNAS = """u.id_usuario::text, u.nombre_completo, u.nombre_usuario, u.correo_institucional,
               u.id_rol, r.nombre AS rol, u.activo, u.intentos_fallidos, u.ultimo_acceso,
               u.fecha_creacion, u.fecha_desactivacion"""


def _fila(f, max_intentos: int) -> dict:
    datos = dict(f)
    intentos = datos.pop("intentos_fallidos")
    datos["bloqueado"] = intentos >= max_intentos
    datos["estado"] = "INACTIVO" if not datos["activo"] else "BLOQUEADO" if datos["bloqueado"] else "ACTIVO"
    return datos


def listar(sesion: Session, max_intentos: int) -> list[dict]:
    filas = sesion.execute(text(f"""SELECT {_COLUMNAS}
                                       FROM seguridad.usuario u JOIN seguridad.rol r ON r.id_rol = u.id_rol
                                      WHERE u.id_usuario <> CAST(:sistema AS uuid)
                                      ORDER BY u.activo DESC, u.nombre_completo"""),
                           {"sistema": ID_USUARIO_SISTEMA}).mappings().all()
    return [_fila(f, max_intentos) for f in filas]


def obtener(sesion: Session, id_usuario: str, max_intentos: int) -> dict | None:
    if id_usuario == ID_USUARIO_SISTEMA:
        return None
    f = sesion.execute(text(f"""SELECT {_COLUMNAS}
                                  FROM seguridad.usuario u JOIN seguridad.rol r ON r.id_rol = u.id_rol
                                 WHERE u.id_usuario = CAST(:id AS uuid)"""), {"id": id_usuario}).mappings().first()
    return None if f is None else _fila(f, max_intentos)


def roles_y_permisos(sesion: Session) -> dict:
    """Catálogo completo de permisos y los permisos que otorga cada rol."""
    permisos = sesion.execute(text("SELECT codigo, descripcion FROM seguridad.permiso ORDER BY id_permiso")).mappings().all()
    roles = sesion.execute(text(
        """SELECT r.id_rol, r.nombre, r.descripcion, r.activo,
                  coalesce(array_agg(p.codigo ORDER BY p.id_permiso) FILTER (WHERE p.codigo IS NOT NULL), '{}') AS permisos
             FROM seguridad.rol r
             LEFT JOIN seguridad.rol_permiso rp ON rp.id_rol = r.id_rol
             LEFT JOIN seguridad.permiso p ON p.id_permiso = rp.id_permiso
            GROUP BY r.id_rol ORDER BY r.id_rol""")).mappings().all()
    return {"permisos": [dict(p) for p in permisos], "roles": [dict(r) for r in roles]}


def _rol_asignable(sesion: Session, id_rol: int) -> dict:
    rol = sesion.execute(text(
        """SELECT r.nombre, r.activo, EXISTS (
                  SELECT 1 FROM seguridad.rol_permiso rp JOIN seguridad.permiso p ON p.id_permiso = rp.id_permiso
                   WHERE rp.id_rol = r.id_rol AND p.codigo = :perm) AS administra
             FROM seguridad.rol r WHERE r.id_rol = :id"""), {"id": id_rol, "perm": PERMISO_ADMINISTRACION}).mappings().first()
    if rol is None:
        raise ErrorDatos("El rol no existe")
    if not rol["activo"]:
        raise ErrorDatos(f"El rol {rol['nombre']} no está habilitado para nuevas asignaciones")
    return dict(rol)


def _verificar_unicidad(sesion: Session, nombre_usuario: str | None, correo: str | None,
                        excluir: str | None = None) -> None:
    if nombre_usuario and sesion.execute(text("SELECT 1 FROM seguridad.usuario WHERE nombre_usuario = :u"),
                                         {"u": nombre_usuario}).first():
        raise ErrorConflicto(f"Ya existe una cuenta con el usuario {nombre_usuario}")
    if correo and sesion.execute(text("""SELECT 1 FROM seguridad.usuario
                                          WHERE lower(correo_institucional) = :c
                                            AND id_usuario IS DISTINCT FROM CAST(:excluir AS uuid)"""),
                                 {"c": correo, "excluir": excluir}).first():
        raise ErrorConflicto("Ya existe una cuenta con ese correo institucional")


def _bloquear_administradores(sesion: Session) -> list[str]:
    """Cuentas activas con permiso de administración de usuarios. Las filas quedan bloqueadas
    (FOR UPDATE) hasta el fin de la transacción: dos cambios simultáneos no pueden dejar
    el sistema sin administrador."""
    return list(sesion.execute(text(
        """SELECT u.id_usuario::text
             FROM seguridad.usuario u
            WHERE u.activo AND EXISTS (
                  SELECT 1 FROM seguridad.rol_permiso rp JOIN seguridad.permiso p ON p.id_permiso = rp.id_permiso
                   WHERE rp.id_rol = u.id_rol AND p.codigo = :perm)
            ORDER BY u.id_usuario
              FOR UPDATE OF u"""), {"perm": PERMISO_ADMINISTRACION}).scalars())


def _asegurar_otro_administrador(sesion: Session, id_usuario: str) -> None:
    administradores = _bloquear_administradores(sesion)
    if id_usuario in administradores and len(administradores) <= 1:
        raise ErrorConflicto("No se puede dejar el sistema sin ningún administrador activo")


def crear(sesion: Session, *, nombre_completo: str, nombre_usuario: str, correo: str | None,
          id_rol: int) -> tuple[str, str, str]:
    """Devuelve (id_usuario, nombre del rol, contraseña generada). La contraseña solo vive en
    la respuesta: en la base de datos queda únicamente su hash Argon2id."""
    rol = _rol_asignable(sesion, id_rol)
    _verificar_unicidad(sesion, nombre_usuario, correo)
    contrasena = generar_contrasena()
    id_usuario = sesion.execute(text(
        """INSERT INTO seguridad.usuario (id_rol, nombre_completo, nombre_usuario, correo_institucional, hash_contrasena)
           VALUES (:r, :n, :u, :c, :h) RETURNING id_usuario::text"""),
        {"r": id_rol, "n": nombre_completo, "u": nombre_usuario, "c": correo, "h": hash_contrasena(contrasena)}).scalar_one()
    return id_usuario, rol["nombre"], contrasena


def actualizar(sesion: Session, id_actor: str, actual: dict, cambios: dict) -> dict:
    """Edita nombre, correo y rol (el nombre de usuario no cambia). Devuelve el detalle para la
    auditoría: los campos modificados y, si cambió, el rol anterior y el nuevo."""
    efectivos = {c: v for c, v in cambios.items() if v != actual[c]}
    if "correo_institucional" in efectivos:
        _verificar_unicidad(sesion, None, efectivos["correo_institucional"], excluir=actual["id_usuario"])
    detalle: dict = {"campos": sorted(efectivos)}
    if "id_rol" in efectivos:
        nuevo = _rol_asignable(sesion, efectivos["id_rol"])
        if not nuevo["administra"]:
            if actual["id_usuario"] == id_actor:
                raise ErrorConflicto("No puede quitarse a sí mismo el rol de administración")
            _asegurar_otro_administrador(sesion, actual["id_usuario"])
        detalle.update(rol_anterior=actual["rol"], rol_nuevo=nuevo["nombre"])
    if efectivos:
        asignaciones = ", ".join(f"{c} = :{c}" for c in efectivos)
        sesion.execute(text(f"UPDATE seguridad.usuario SET {asignaciones} WHERE id_usuario = CAST(:id AS uuid)"),
                       {**efectivos, "id": actual["id_usuario"]})
    return detalle


def desactivar(sesion: Session, id_actor: str, actual: dict) -> None:
    if actual["id_usuario"] == id_actor:
        raise ErrorConflicto("No puede desactivar su propia cuenta")
    if not actual["activo"]:
        raise ErrorConflicto("La cuenta ya está desactivada")
    _asegurar_otro_administrador(sesion, actual["id_usuario"])
    sesion.execute(text("""UPDATE seguridad.usuario SET activo = false, fecha_desactivacion = now()
                            WHERE id_usuario = CAST(:id AS uuid)"""), {"id": actual["id_usuario"]})


def reactivar(sesion: Session, actual: dict) -> None:
    if actual["activo"]:
        raise ErrorConflicto("La cuenta ya está activa")
    sesion.execute(text("""UPDATE seguridad.usuario SET activo = true, fecha_desactivacion = NULL
                            WHERE id_usuario = CAST(:id AS uuid)"""), {"id": actual["id_usuario"]})


def desbloquear(sesion: Session, actual: dict) -> None:
    if not actual["bloqueado"]:
        raise ErrorConflicto("La cuenta no está bloqueada")
    sesion.execute(text("UPDATE seguridad.usuario SET intentos_fallidos = 0 WHERE id_usuario = CAST(:id AS uuid)"),
                   {"id": actual["id_usuario"]})


def restablecer_contrasena(sesion: Session, actual: dict) -> str:
    """Genera una contraseña nueva y desbloquea la cuenta. Devuelve la contraseña para mostrarla una vez."""
    contrasena = generar_contrasena()
    sesion.execute(text("""UPDATE seguridad.usuario SET hash_contrasena = :h, intentos_fallidos = 0
                            WHERE id_usuario = CAST(:id AS uuid)"""),
                   {"h": hash_contrasena(contrasena), "id": actual["id_usuario"]})
    return contrasena
