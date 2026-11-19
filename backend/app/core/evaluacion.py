"""Modo de evaluación del OE3 (Sprint 3, parte E1a).

Con CDSS_MODO_EVALUACION=true (solo en el entorno; ninguna ruta lo cambia), las escrituras que
cambian lo que el sistema responde quedan bloqueadas: la carga y el reintento de guías (M11) y,
desde la parte E1b, la edición de parámetros (M12). Cada intento responde 423 con un mensaje claro y
deja el evento PARAMETRO_CAMBIO_BLOQUEADO, sin datos personales."""
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.auditoria import registrar_evento
from app.core.config import get_settings

EVENTO_BLOQUEO = "PARAMETRO_CAMBIO_BLOQUEADO"
MENSAJE_BLOQUEO = ("El sistema está en modo de evaluación: los cambios de parámetros y de la base de conocimiento "
                   "están bloqueados hasta que termine la evaluación.")


def modo_evaluacion_activo() -> bool:
    return get_settings().modo_evaluacion


def bloquear_en_evaluacion(sesion: Session, id_usuario: str, accion: str, entidad: str | None = None,
                           id_entidad: str | None = None, direccion_ip: str | None = None) -> None:
    """Si el modo de evaluación está activo, registra el evento (y lo confirma) y responde 423.
    Llamarla antes de cualquier escritura; la sesión debe poder insertar en la bitácora."""
    if not modo_evaluacion_activo():
        return
    registrar_evento(sesion, EVENTO_BLOQUEO, id_usuario, entidad, id_entidad, {"accion": accion}, direccion_ip)
    sesion.commit()
    raise HTTPException(status.HTTP_423_LOCKED, MENSAJE_BLOQUEO)
