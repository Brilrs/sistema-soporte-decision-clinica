"""Registro en la bitácora de solo inserción (auditoria.evento_auditoria)."""
import ipaddress
import json

from sqlalchemy import text
from sqlalchemy.orm import Session


def registrar_evento(
    sesion: Session,
    tipo_evento: str,
    id_usuario: str | None = None,
    entidad: str | None = None,
    id_entidad: str | None = None,
    detalle: dict | None = None,
    direccion_ip: str | None = None,
) -> None:
    """El detalle nunca debe contener datos identificatorios en claro."""
    try:
        ip = str(ipaddress.ip_address(direccion_ip)) if direccion_ip else None
    except ValueError:  # p. ej., un proxy que no reenvía la IP real
        ip = None
    sesion.execute(
        text(
            """INSERT INTO auditoria.evento_auditoria
                 (id_usuario, tipo_evento, entidad, id_entidad, detalle, direccion_ip)
               VALUES (:u, :t, :e, :ie, CAST(:d AS jsonb), CAST(:ip AS inet))"""
        ),
        {
            "u": id_usuario,
            "t": tipo_evento,
            "e": entidad,
            "ie": id_entidad,
            "d": json.dumps(detalle, ensure_ascii=False) if detalle is not None else None,
            "ip": ip,
        },
    )
