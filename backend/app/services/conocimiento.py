"""M11 · Base de conocimiento (HU12, parte F2b; HU17, Sprint 3 parte F): lectura de guías y trabajos,
subida de un PDF de nivel 2, reintento de una indexación fallida y retiro de guías. Todo con la
conexión de cdss_admin (rol_app_admin: lectura y escritura en conocimiento y lectura de
configuracion, sin acceso a datos clínicos); el indexador (cdss_indexador) procesa después los
trabajos PENDIENTE.

Ninguna función devuelve rutas del servidor: ruta_blob se guarda en la base para el indexador
(local://guias_cargadas/<id_documento>.pdf), pero no sale en las respuestas."""
import hashlib
import os
import unicodedata
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

import yaml
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.indexador.modificaciones import DIR_MODIFICACIONES, cargar_mapa
from app.rag.punteros import reglas_vigentes

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


class ErrorRetiro(Exception):
    """Rechazo del retiro con su código HTTP, un código para la pantalla y, en REFERENCIAS_VIGENTES, la
    lista de referencias que lo bloquean."""

    def __init__(self, estado: int, codigo: str, mensaje: str, referencias: list[dict] | None = None):
        super().__init__(mensaje)
        self.estado, self.codigo, self.referencias = estado, codigo, referencias

    def cuerpo(self) -> dict:
        cuerpo = {"detail": str(self), "codigo": self.codigo}
        if self.referencias is not None:
            cuerpo["referencias"] = self.referencias
        return cuerpo


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
           d.fecha_retiro, d.motivo_retiro, r.nombre_completo AS retirado_por,
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
      LEFT JOIN seguridad.usuario r ON r.id_usuario = d.retirado_por
      LEFT JOIN LATERAL (SELECT * FROM conocimiento.trabajo_indexacion x WHERE x.id_documento = d.id_documento
                          ORDER BY x.fecha_solicitud DESC, x.id_trabajo DESC LIMIT 1) t ON true
     {filtro}
"""


def _documento(fila) -> dict:
    m = dict(fila._mapping)
    trabajo = None if m["t_id"] is None else {
        "id_trabajo": m["t_id"], "tipo": m["t_tipo"], "estado": m["t_estado"], "etapa": m["t_etapa"],
        "procesados": m["t_procesados"], "total": m["t_total"], "mensaje_error": m["t_mensaje"],
        "fecha_solicitud": m["t_solicitud"], "fecha_fin": m["t_fin"]}
    base = {k: v for k, v in m.items() if not k.startswith("t_")}
    return {**base, "ultimo_trabajo": trabajo}


def _titulo_para_ordenar(titulo: str) -> str:
    """Título sin tildes y sin distinguir mayúsculas («Norma técnica» antes de «NTS 213»)."""
    return "".join(c for c in unicodedata.normalize("NFKD", titulo) if not unicodedata.combining(c)).casefold()


def clave_orden(d: dict) -> tuple:
    """Orden de la lista de M11: nivel, vigentes primero, año más reciente y título; desempatan el
    título exacto y el id. Se ordena aquí y no con ORDER BY titulo porque ese orden depende de la
    colación de la base (glibc ignora mayúsculas; C y la imagen alpine, con musl, ordenan por bytes)."""
    return (d["nivel"], d["estado"] != "VIGENTE", -d["anio_publicacion"], _titulo_para_ordenar(d["titulo"]),
            d["titulo"], d["id_documento"])


def listar_documentos(sesion: Session) -> list[dict]:
    filas = sesion.execute(text(_DOCUMENTOS.format(filtro="")))
    return sorted((_documento(f) for f in filas), key=clave_orden)


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
MENSAJE_OBSOLETA = ("La guía está retirada: no se vuelve a indexar. Solo se puede reintentar un retiro que "
                    "terminó en error.")


def reintentar(sesion: Session, id_documento: str, id_usuario: str) -> tuple[str, str]:
    """Solo con el documento en ERROR y sin trabajo activo propio (409 en otro caso). REINDEXACION si
    ya tiene fragmentos de una versión anterior; INDEXACION si nunca se indexó. Con la guía retirada
    (OBSOLETA) solo se reintenta un RETIRO que terminó en error, con otro trabajo RETIRO; indexarla de
    nuevo es 409. Devuelve (trabajo, tipo)."""
    fila = sesion.execute(text(
        """SELECT d.estado, d.estado_indexacion,
                  EXISTS (SELECT 1 FROM conocimiento.trabajo_indexacion t
                           WHERE t.id_documento = d.id_documento AND t.estado = ANY(:a)) AS activo,
                  EXISTS (SELECT 1 FROM conocimiento.fragmento f WHERE f.id_documento = d.id_documento) AS indexado,
                  (SELECT t.tipo || ':' || t.estado FROM conocimiento.trabajo_indexacion t
                    WHERE t.id_documento = d.id_documento
                    ORDER BY t.fecha_solicitud DESC, t.id_trabajo DESC LIMIT 1) AS ultimo
             FROM conocimiento.documento_fuente d WHERE d.id_documento = CAST(:id AS uuid) FOR UPDATE OF d"""),
        {"id": id_documento, "a": list(ACTIVOS)}).first()
    if fila is None:
        raise ErrorGuia(404, "La guía no existe")
    if fila.activo:
        raise ErrorGuia(409, "La guía ya tiene una indexación pendiente o en curso")
    if fila.estado == "OBSOLETA":
        if fila.ultimo != "RETIRO:ERROR":
            raise ErrorGuia(409, MENSAJE_OBSOLETA)
        return crear_trabajo(sesion, id_documento, "RETIRO", id_usuario), "RETIRO"
    if fila.estado_indexacion != "ERROR":
        raise ErrorGuia(409, "Solo se puede reintentar una guía cuya indexación terminó en error")
    comprobar_capacidad(sesion)
    tipo = "REINDEXACION" if fila.indexado else "INDEXACION"
    id_trabajo = crear_trabajo(sesion, id_documento, tipo, id_usuario)
    sesion.execute(text("UPDATE conocimiento.documento_fuente SET estado_indexacion = 'PENDIENTE' "
                        "WHERE id_documento = CAST(:id AS uuid)"), {"id": id_documento})
    return id_trabajo, tipo


# ---------------------------------------------------------------------------
# Retiro (HU17, Sprint 3 parte F; decisión 6 del plan)
# ---------------------------------------------------------------------------
MOTIVO_MIN, MOTIVO_MAX = 10, 250  # motivo_retiro es VARCHAR(250)
MANIFIESTO = Path(__file__).resolve().parents[1] / "indexador" / "fuentes_iniciales.yaml"
MENSAJE_YA_OBSOLETA = "La guía ya está retirada"
MENSAJE_RETIRO_ACTIVO = "La guía tiene una indexación pendiente o en curso: espere a que termine antes de retirarla"
MENSAJE_REFERENCIAS = ("No se puede retirar: la guía es de nivel 1 y otros elementos vigentes la usan. Cambie o "
                       "retire primero esas referencias.")
MENSAJE_CONFIRMACION = "Para retirar una guía de nivel 1, escriba su código exactamente como aparece"
MENSAJE_MOTIVO = f"El motivo del retiro debe tener entre {MOTIVO_MIN} y {MOTIVO_MAX} caracteres"


def _plural(n: int, singular: str, plural: str) -> str:
    return f"{n} {singular if n == 1 else plural}"


def _ids_del_manifiesto() -> dict[str, str]:
    """clave del manifiesto del indexador (rm251, rm429...) -> id_documento."""
    datos = yaml.safe_load(MANIFIESTO.read_text(encoding="utf-8")) or {}
    return {d["clave"]: str(d["id_documento"]) for d in datos.get("documentos") or []}


def _mapas() -> list[tuple[str, object]]:
    return [(p.name, cargar_mapa(p.name)) for p in sorted(DIR_MODIFICACIONES.glob("*.yaml"))]


def _nombre(sesion: Session, id_documento: str | None) -> str:
    if id_documento is None:
        return "otra guía"
    fila = sesion.execute(text("SELECT coalesce(codigo_documento, titulo) FROM conocimiento.documento_fuente "
                               "WHERE id_documento = CAST(:id AS uuid)"), {"id": id_documento}).scalar()
    return fila or id_documento


def referencias(sesion: Session, id_documento: str, nivel: int, codigo: str | None) -> list[dict]:
    """Referencias vigentes que impiden retirar una guía de nivel 1 (decisión 6). Para el nivel 2, lista
    vacía: sin restricción. Cada una con tipo y descripción en español claro, en un orden fijo."""
    if nivel != 1:
        return []
    p = {"id": id_documento}
    refs: list[dict] = []
    n = sesion.execute(text("SELECT count(*) FROM configuracion.umbral_hemoglobina "
                            "WHERE id_documento = CAST(:id AS uuid) AND vigente_hasta IS NULL"), p).scalar_one()
    if n:
        refs.append({"tipo": "UMBRAL_HEMOGLOBINA", "descripcion":
                     f"{_plural(n, 'punto de corte de hemoglobina vigente la cita', 'puntos de corte de hemoglobina vigentes la citan')}"
                     " como norma (Parámetros clínicos, «Puntos de corte de hemoglobina»)"})
    n = sesion.execute(text("SELECT count(*) FROM configuracion.ajuste_altitud "
                            "WHERE id_documento = CAST(:id AS uuid) AND vigente_hasta IS NULL"), p).scalar_one()
    if n:
        refs.append({"tipo": "AJUSTE_ALTITUD", "descripcion":
                     f"{_plural(n, 'ajuste por altitud vigente la cita', 'ajustes por altitud vigentes la citan')}"
                     " como norma (Parámetros clínicos, «Ajuste por altitud»)"})
    for f in sesion.execute(text(
            """SELECT clave, descripcion FROM configuracion.parametro_sistema
                WHERE id_documento = CAST(:id AS uuid) AND vigente_hasta IS NULL"""), p).all():
        refs.append({"tipo": "PARAMETRO_SISTEMA",
                     "descripcion": f"El parámetro vigente «{f.descripcion or f.clave}» ({f.clave}) la cita como norma"})
    # Es una norma que modifica a otra: fragmentos de la última versión de otras guías vigentes
    # sustituidos por su texto (fragmento.id_documento_modificatorio).
    filas = sesion.execute(text(
        """SELECT coalesce(d.codigo_documento, d.titulo) AS nombre, count(*) AS n
             FROM conocimiento.fragmento f JOIN conocimiento.documento_fuente d ON d.id_documento = f.id_documento
            WHERE f.id_documento_modificatorio = CAST(:id AS uuid) AND f.id_documento <> CAST(:id AS uuid)
              AND d.estado = 'VIGENTE'
              AND f.version_indexacion = (SELECT max(v.version_indexacion) FROM conocimiento.fragmento v
                                           WHERE v.id_documento = f.id_documento)
            GROUP BY 1"""), p).all()
    for f in sorted(filas, key=lambda x: x.nombre):
        refs.append({"tipo": "MODIFICACION", "descripcion":
                     f"Modifica a «{f.nombre}»: {_plural(f.n, 'fragmento de esa guía quedó sustituido', 'fragmentos de esa guía quedaron sustituidos')}"
                     " por su texto"})
    ids = _ids_del_manifiesto()
    for archivo, mapa in _mapas():
        base = ids.get(mapa.documento_modificado)
        if mapa.id_documento_modificatorio == id_documento:
            refs.append({"tipo": "MAPA_MODIFICACIONES", "descripcion":
                         f"Es la norma modificatoria del mapa de modificaciones del indexador ({archivo}): modifica a "
                         f"«{_nombre(sesion, base)}»"})
        if base == id_documento:
            refs.append({"tipo": "MAPA_MODIFICACIONES", "descripcion":
                         f"Es la guía base del mapa de modificaciones del indexador ({archivo}): «{mapa.codigo}» "
                         "modifica su texto"})
    if codigo:
        for r in reglas_vigentes():
            if r.documento_origen == codigo:
                refs.append({"tipo": "PUNTERO", "descripcion":
                             f"La regla de punteros «{r.id}» (punteros.yaml) la usa como documento de origen"})
            if r.documento_destino == codigo:
                refs.append({"tipo": "PUNTERO", "descripcion":
                             f"La regla de punteros «{r.id}» (punteros.yaml) la usa como documento de destino"})
    return refs


def referencias_de(sesion: Session, id_documento: str) -> dict | None:
    """Respuesta de GET .../referencias, o None si la guía no existe."""
    d = sesion.execute(text("SELECT nivel, codigo_documento, titulo, estado FROM conocimiento.documento_fuente "
                            "WHERE id_documento = CAST(:id AS uuid)"), {"id": id_documento}).first()
    if d is None:
        return None
    refs = referencias(sesion, id_documento, d.nivel, d.codigo_documento)
    return {"id_documento": id_documento, "nivel": d.nivel, "estado": d.estado,
            "codigo_confirmacion": codigo_confirmacion(d.codigo_documento, d.titulo) if d.nivel == 1 else None,
            "referencias": refs, "puede_retirarse": d.estado == "VIGENTE" and not refs}


def codigo_confirmacion(codigo: str | None, titulo: str) -> str:
    """Texto que confirma el retiro de una guía de nivel 1: su código (o el título si no tiene)."""
    return codigo or titulo


def validar_motivo(motivo: str) -> str:
    limpio = (motivo or "").strip()
    if not MOTIVO_MIN <= len(limpio) <= MOTIVO_MAX:
        raise ErrorRetiro(422, "MOTIVO_INVALIDO", MENSAJE_MOTIVO)
    return limpio


def retirar(sesion: Session, id_documento: str, motivo: str, confirmacion: str | None, id_usuario: str) -> tuple[dict, str]:
    """Guardas en orden (documento, ya obsoleta, trabajo activo, referencias y confirmación del nivel 1)
    y, en la transacción del llamador, el retiro: estado OBSOLETA con quién, cuándo y por qué, y un
    trabajo RETIRO en la cola. El documento nunca se borra. Devuelve (datos para la auditoría, trabajo)."""
    d = sesion.execute(text(
        """SELECT d.nivel, d.estado, d.codigo_documento, d.titulo,
                  EXISTS (SELECT 1 FROM conocimiento.trabajo_indexacion t
                           WHERE t.id_documento = d.id_documento AND t.estado = ANY(:a)) AS activo
             FROM conocimiento.documento_fuente d WHERE d.id_documento = CAST(:id AS uuid) FOR UPDATE OF d"""),
        {"id": id_documento, "a": list(ACTIVOS)}).first()
    if d is None:
        raise ErrorRetiro(404, "NO_ENCONTRADA", "La guía no existe")
    if d.estado == "OBSOLETA":
        raise ErrorRetiro(409, "YA_OBSOLETA", MENSAJE_YA_OBSOLETA)
    if d.activo:
        raise ErrorRetiro(409, "TRABAJO_ACTIVO", MENSAJE_RETIRO_ACTIVO)
    if d.nivel == 1:
        refs = referencias(sesion, id_documento, d.nivel, d.codigo_documento)
        if refs:
            raise ErrorRetiro(409, "REFERENCIAS_VIGENTES", MENSAJE_REFERENCIAS, refs)
        if confirmacion != codigo_confirmacion(d.codigo_documento, d.titulo):
            raise ErrorRetiro(422, "CONFIRMACION_INCORRECTA", MENSAJE_CONFIRMACION)
    sesion.execute(text(
        """UPDATE conocimiento.documento_fuente
              SET estado = 'OBSOLETA', retirado_por = CAST(:u AS uuid), fecha_retiro = now(), motivo_retiro = :m
            WHERE id_documento = CAST(:id AS uuid)"""), {"id": id_documento, "u": id_usuario, "m": motivo})
    id_trabajo = crear_trabajo(sesion, id_documento, "RETIRO", id_usuario)
    return {"id_documento": id_documento, "codigo_documento": d.codigo_documento, "nivel": d.nivel,
            "motivo": motivo, "id_trabajo": id_trabajo}, id_trabajo
