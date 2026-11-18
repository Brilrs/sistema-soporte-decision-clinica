"""Reportes exportados de una consulta (M09, HU10; Sprint 3, parte C1).

Con la conexión de cdss_clinica: reserva el número correlativo (asistencia.siguiente_numero_reporte,
migración 013), registra cada reporte emitido en asistencia.reporte (número, destino, secciones,
usuario, fecha y SHA-256 del PDF entregado) y lista los de una consulta. El PDF nunca se guarda:
se genera en memoria, se entrega y solo queda su hash."""
import hashlib
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Connection, text
from sqlalchemy.orm import Session

from app.reportes.pdf import generar_pdf


@dataclass(frozen=True)
class ReporteEmitido:
    numero: str
    fecha_emision: datetime
    hash_documento: str
    pdf: bytes


def reservar_numero(sesion: Session | Connection) -> tuple[str, datetime]:
    """Número EV-AAAA-NNNNN y fecha de emisión de la base. nextval no se revierte: un reporte que
    falla deja un hueco en la numeración, nunca un número repetido."""
    fila = sesion.execute(text("SELECT numero_reporte, fecha_emision FROM asistencia.siguiente_numero_reporte()")).one()
    return fila.numero_reporte, fila.fecha_emision


def huella(pdf: bytes) -> str:
    return hashlib.sha256(pdf).hexdigest()


def emitir(sesion: Session | Connection, contenido: dict, id_consulta: str, id_usuario: str) -> ReporteEmitido:
    """Reserva el número, genera el PDF con ese número y registra el reporte con el hash de los
    bytes que se van a entregar. Quien llama hace el commit."""
    numero, fecha_emision = reservar_numero(sesion)
    pdf = generar_pdf(contenido, numero, fecha_emision)
    hash_documento = huella(pdf)
    sesion.execute(text(
        """INSERT INTO asistencia.reporte (numero_reporte, id_consulta, id_usuario, destino, secciones_incluidas, formato,
                                           hash_documento, fecha_generacion)
           VALUES (:n, CAST(:c AS uuid), CAST(:u AS uuid), :d, :s, 'PDF', :h, :f)"""),
        {"n": numero, "c": id_consulta, "u": id_usuario, "d": contenido["destino"], "s": contenido["secciones"],
         "h": hash_documento, "f": fecha_emision})
    return ReporteEmitido(numero, fecha_emision, hash_documento, pdf)


def _correlativo(numero: str) -> int:
    return int(numero.rsplit("-", 1)[1])


def listar(sesion: Session | Connection, id_consulta: str) -> list[dict]:
    """Reportes de la consulta, del más reciente al más antiguo. Se ordena en Python por el
    correlativo (la secuencia es global y creciente), no por el texto del número en la base."""
    filas = sesion.execute(text(
        """SELECT numero_reporte, destino, secciones_incluidas, formato, fecha_generacion, hash_documento
             FROM asistencia.reporte WHERE id_consulta = CAST(:c AS uuid)"""), {"c": id_consulta}).all()
    reportes = [{"numero_reporte": f.numero_reporte, "destino": f.destino, "secciones": list(f.secciones_incluidas),
                 "formato": f.formato, "fecha_generacion": f.fecha_generacion, "hash_documento": f.hash_documento}
                for f in filas]
    return sorted(reportes, key=lambda r: _correlativo(r["numero_reporte"]), reverse=True)
