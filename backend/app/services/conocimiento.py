"""M11 · Base de conocimiento (HU12, parte F2b): lectura de guías y trabajos, subida de un PDF de
nivel 2 y reintento de una indexación fallida. Todo con la conexión de cdss_admin (rol_app_admin:
lectura y escritura en conocimiento, sin acceso a datos clínicos); el indexador (cdss_indexador)
procesa después los trabajos PENDIENTE.

Ninguna función devuelve rutas del servidor: ruta_blob se guarda en la base para el indexador
(local://guias_cargadas/<id_documento>.pdf), pero no sale en las respuestas."""
import hashlib
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings

PERMISO = "ADMINISTRAR_GUIAS"
NIVEL_API = 2  # M11 solo carga documentos de nivel 2 (decisión de la parte F2)
FIRMA_PDF = b"%PDF-"
BLOQUE = 1 << 20
ESQUEMA_RUTA = "local://guias_cargadas/"
MAX_TRABAJOS_ACTIVOS = 2  # pendiente P14: no saturar el servicio modelos
ACTIVOS = ("PENDIENTE", "EN_CURSO")

MENSAJE_EXTENSION = "El archivo debe tener la extensión .pdf"
MENSAJE_FIRMA = "El archivo no es un PDF válido (no empieza con %PDF-)"
MENSAJE_NIVEL_1 = ("Desde la pantalla solo se cargan guías de nivel 2 (metodológicas). Las guías de nivel 1 "
                   "(citables) se cargan por línea de comandos, con sus transcripciones verificadas.")
MENSAJE_ACTIVOS = (f"Ya hay {MAX_TRABAJOS_ACTIVOS} indexaciones pendientes o en curso. Espere a que terminen antes "
                   "de cargar otra guía: indexar varias a la vez satura el servicio de modelos.")


class ErrorGuia(Exception):
    """Rechazo con su código HTTP; motivo es el de la auditoría (GUIA_CARGA_RECHAZADA) o None."""

    def __init__(self, codigo: int, mensaje: str, motivo: str | None = None, detalle: dict | None = None):
        super().__init__(mensaje)
        self.codigo, self.motivo, self.detalle = codigo, motivo, detalle or {}


@dataclass(frozen=True)
class ParametrosSubida:
    directorio: Path
    max_bytes: int


def parametros_subida() -> ParametrosSubida:
    """Carpeta del volumen datos_guias_cargadas y tamaño máximo (las pruebas la reemplazan)."""
    s = get_settings()
    return ParametrosSubida(Path(s.dir_guias_cargadas), s.max_bytes_guia)


# ---------------------------------------------------------------------------
# Lectura
# ---------------------------------------------------------------------------
_DOCUMENTOS = """
    SELECT d.id_documento::text, d.titulo, d.codigo_documento, d.entidad_emisora, d.tipo_documento, d.nivel,
           d.version, d.anio_publicacion, d.idioma, d.estado, d.estado_indexacion, d.fecha_carga,
           (SELECT max(f.version_indexacion) FROM conocimiento.fragmento f
             WHERE f.id_documento = d.id_documento) AS version_indexacion,
           (SELECT count(*) FROM conocimiento.fragmento f
             WHERE f.id_documento = d.id_documento AND f.vigente) AS fragmentos_vigentes,
           coalesce(u.citas_30_dias, 0) AS citas_30_dias,
           t.id_trabajo::text AS t_id, t.tipo AS t_tipo, t.estado AS t_estado, t.etapa AS t_etapa,
           t.procesados AS t_procesados, t.total AS t_total, t.mensaje_error AS t_mensaje,
           t.fecha_solicitud AS t_solicitud, t.fecha_fin AS t_fin
      FROM conocimiento.documento_fuente d
      LEFT JOIN conocimiento.v_uso_documento u ON u.id_documento = d.id_documento
      LEFT JOIN LATERAL (SELECT * FROM conocimiento.trabajo_indexacion x WHERE x.id_documento = d.id_documento
                          ORDER BY x.fecha_solicitud DESC, x.id_trabajo DESC LIMIT 1) t ON true
     {filtro}
     ORDER BY d.nivel, d.estado DESC, d.anio_publicacion DESC, d.titulo, d.id_documento
"""


def _documento(fila) -> dict:
    m = dict(fila._mapping)
    trabajo = None if m["t_id"] is None else {
        "id_trabajo": m["t_id"], "tipo": m["t_tipo"], "estado": m["t_estado"], "etapa": m["t_etapa"],
        "procesados": m["t_procesados"], "total": m["t_total"], "mensaje_error": m["t_mensaje"],
        "fecha_solicitud": m["t_solicitud"], "fecha_fin": m["t_fin"]}
    base = {k: v for k, v in m.items() if not k.startswith("t_")}
    return {**base, "ultimo_trabajo": trabajo}


def listar_documentos(sesion: Session) -> list[dict]:
    return [_documento(f) for f in sesion.execute(text(_DOCUMENTOS.format(filtro="")))]


def documento(sesion: Session, id_documento: str) -> dict | None:
    fila = sesion.execute(text(_DOCUMENTOS.format(filtro="WHERE d.id_documento = CAST(:id AS uuid)")),
                          {"id": id_documento}).first()
    return None if fila is None else _documento(fila)


_TRABAJOS = """
    SELECT t.id_trabajo::text, t.id_documento::text, d.titulo, t.tipo, t.estado, t.etapa, t.procesados, t.total,
           t.mensaje_error, t.fecha_solicitud, t.fecha_inicio, t.fecha_fin, u.nombre_completo AS solicitado_por
      FROM conocimiento.trabajo_indexacion t
      JOIN conocimiento.documento_fuente d ON d.id_documento = t.id_documento
      JOIN seguridad.usuario u ON u.id_usuario = t.solicitado_por
     {filtro}
     ORDER BY t.fecha_solicitud DESC, t.id_trabajo DESC
     {limite}
"""


def trabajo(sesion: Session, id_trabajo: str) -> dict:
    sql = _TRABAJOS.format(filtro="WHERE t.id_trabajo = CAST(:id AS uuid)", limite="")
    return dict(sesion.execute(text(sql), {"id": id_trabajo}).one()._mapping)


def listar_trabajos(sesion: Session, activos: bool) -> list[dict]:
    """Con activos, los PENDIENTE y EN_CURSO; si no, los 50 más recientes."""
    sql = _TRABAJOS.format(filtro="WHERE t.estado = ANY(:activos)" if activos else "",
                           limite="" if activos else "LIMIT 50")
    return [dict(f._mapping) for f in sesion.execute(text(sql), {"activos": list(ACTIVOS)})]


def detalle(sesion: Session, id_documento: str) -> dict | None:
    base = documento(sesion, id_documento)
    if base is None:
        return None
    extra = sesion.execute(text(
        """SELECT d.fecha_publicacion, d.pagina_inicio_cuerpo, d.pagina_fin_cuerpo, d.hash_archivo, d.total_fragmentos,
                  u.nombre_completo AS cargado_por
             FROM conocimiento.documento_fuente d JOIN seguridad.usuario u ON u.id_usuario = d.cargado_por
            WHERE d.id_documento = CAST(:id AS uuid)"""), {"id": id_documento}).one()
    versiones = [dict(f._mapping) for f in sesion.execute(text(
        """SELECT version_indexacion, count(*) AS fragmentos, count(*) FILTER (WHERE vigente) AS vigentes,
                  string_agg(DISTINCT modelo_embedding, ', ') AS modelo_embedding
             FROM conocimiento.fragmento WHERE id_documento = CAST(:id AS uuid)
            GROUP BY version_indexacion ORDER BY version_indexacion DESC"""), {"id": id_documento})]
    trabajos = [dict(f._mapping) for f in sesion.execute(text(
        _TRABAJOS.format(filtro="WHERE t.id_documento = CAST(:id AS uuid)", limite="")), {"id": id_documento})]
    return {**base, **dict(extra._mapping), "versiones": versiones, "trabajos": trabajos}


# ---------------------------------------------------------------------------
# Subida
# ---------------------------------------------------------------------------
def trabajos_activos(sesion: Session) -> int:
    return sesion.execute(text("SELECT count(*) FROM conocimiento.trabajo_indexacion WHERE estado = ANY(:a)"),
                          {"a": list(ACTIVOS)}).scalar_one()


def bloquear_cola(sesion: Session) -> None:
    """Candado de la transacción para crear trabajos: dos subidas o reintentos simultáneos no
    pasan juntos el límite de trabajos activos. Se libera con el commit o el rollback."""
    sesion.execute(text("SELECT pg_advisory_xact_lock(hashtext('cdss.cola_indexacion'))"))


def comprobar_capacidad(sesion: Session) -> None:
    if trabajos_activos(sesion) >= MAX_TRABAJOS_ACTIVOS:
        raise ErrorGuia(409, MENSAJE_ACTIVOS)


@dataclass
class ArchivoRecibido:
    temporal: Path
    sha256: str
    tamano: int


def recibir_pdf(nombre: str | None, origen: BinaryIO, p: ParametrosSubida) -> ArchivoRecibido:
    """Comprueba la extensión y la firma, y copia por partes a un temporal del volumen calculando el
    SHA-256; corta al pasar el máximo. El nombre enviado por el usuario solo se usa para la extensión."""
    if Path(nombre or "").suffix.lower() != ".pdf":
        raise ErrorGuia(415, MENSAJE_EXTENSION, "no_es_pdf")
    inicio = origen.read(len(FIRMA_PDF))
    if inicio != FIRMA_PDF:
        raise ErrorGuia(415, MENSAJE_FIRMA, "no_es_pdf")
    p.directorio.mkdir(parents=True, exist_ok=True)
    temporal = p.directorio / f".subida-{uuid.uuid4().hex}.tmp"
    h, tamano = hashlib.sha256(inicio), len(inicio)
    try:
        with open(temporal, "xb") as destino:
            destino.write(inicio)
            while bloque := origen.read(BLOQUE):
                tamano += len(bloque)
                if tamano > p.max_bytes:
                    raise ErrorGuia(413, f"El archivo supera el máximo de {p.max_bytes / (1 << 20):g} MB",
                                    "tamano", {"max_bytes": p.max_bytes})
                h.update(bloque)
                destino.write(bloque)
    except BaseException:
        temporal.unlink(missing_ok=True)
        raise
    return ArchivoRecibido(temporal, h.hexdigest(), tamano)


def documento_con_hash(sesion: Session, sha256: str) -> dict | None:
    fila = sesion.execute(text("SELECT id_documento::text, titulo FROM conocimiento.documento_fuente WHERE hash_archivo = :h"),
                          {"h": sha256}).first()
    return None if fila is None else dict(fila._mapping)


def insertar_documento(sesion: Session, id_documento: str, datos: dict, archivo: ArchivoRecibido,
                       id_usuario: str) -> str:
    """Documento PENDIENTE y su trabajo INDEXACION, en la transacción del llamador. Devuelve el trabajo."""
    sesion.execute(text(
        """INSERT INTO conocimiento.documento_fuente
             (id_documento, titulo, codigo_documento, entidad_emisora, tipo_documento, nivel, anio_publicacion,
              idioma, pagina_inicio_cuerpo, pagina_fin_cuerpo, ruta_blob, hash_archivo, cargado_por)
           VALUES (CAST(:id AS uuid), :titulo, :codigo_documento, :entidad_emisora, :tipo_documento, :nivel,
                   :anio_publicacion, :idioma, :pagina_inicio_cuerpo, :pagina_fin_cuerpo, :ruta, :hash,
                   CAST(:usuario AS uuid))"""),
        {**datos, "id": id_documento, "ruta": f"{ESQUEMA_RUTA}{id_documento}.pdf", "hash": archivo.sha256,
         "usuario": id_usuario})
    return crear_trabajo(sesion, id_documento, "INDEXACION", id_usuario)


def crear_trabajo(sesion: Session, id_documento: str, tipo: str, id_usuario: str) -> str:
    return sesion.execute(text(
        """INSERT INTO conocimiento.trabajo_indexacion (id_documento, tipo, estado, solicitado_por)
           VALUES (CAST(:d AS uuid), :t, 'PENDIENTE', CAST(:u AS uuid)) RETURNING id_trabajo::text"""),
        {"d": id_documento, "t": tipo, "u": id_usuario}).scalar_one()


def destino_final(p: ParametrosSubida, id_documento: str) -> Path:
    return p.directorio / f"{id_documento}.pdf"


def mover(temporal: Path, destino: Path) -> None:
    os.replace(temporal, destino)


# ---------------------------------------------------------------------------
# Reintento
# ---------------------------------------------------------------------------
def reintentar(sesion: Session, id_documento: str, id_usuario: str) -> tuple[str, str]:
    """Solo con el documento en ERROR y sin trabajo activo propio (409 en otro caso). REINDEXACION si
    ya tiene fragmentos de una versión anterior; INDEXACION si nunca se indexó. Devuelve (trabajo, tipo)."""
    fila = sesion.execute(text(
        """SELECT d.estado_indexacion,
                  EXISTS (SELECT 1 FROM conocimiento.trabajo_indexacion t
                           WHERE t.id_documento = d.id_documento AND t.estado = ANY(:a)) AS activo,
                  EXISTS (SELECT 1 FROM conocimiento.fragmento f WHERE f.id_documento = d.id_documento) AS indexado
             FROM conocimiento.documento_fuente d WHERE d.id_documento = CAST(:id AS uuid) FOR UPDATE OF d"""),
        {"id": id_documento, "a": list(ACTIVOS)}).first()
    if fila is None:
        raise ErrorGuia(404, "La guía no existe")
    if fila.activo:
        raise ErrorGuia(409, "La guía ya tiene una indexación pendiente o en curso")
    if fila.estado_indexacion != "ERROR":
        raise ErrorGuia(409, "Solo se puede reintentar una guía cuya indexación terminó en error")
    comprobar_capacidad(sesion)
    tipo = "REINDEXACION" if fila.indexado else "INDEXACION"
    id_trabajo = crear_trabajo(sesion, id_documento, tipo, id_usuario)
    sesion.execute(text("UPDATE conocimiento.documento_fuente SET estado_indexacion = 'PENDIENTE' "
                        "WHERE id_documento = CAST(:id AS uuid)"), {"id": id_documento})
    return id_trabajo, tipo
