"""Acceso a PostgreSQL con el usuario cdss_indexador: lee la base de conocimiento
y los parámetros, escribe fragmentos y trabajos, actualiza solo ruta, hash,
estado de indexación y total de fragmentos de los documentos, e inserta en la
auditoría. No tiene permiso de eliminación."""
import json
from dataclasses import dataclass

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine

from app.indexador.chunker import Fragmento

USUARIO_SISTEMA = "00000000-0000-0000-0000-000000000001"


@dataclass
class Documento:
    id_documento: str
    titulo: str
    codigo_documento: str | None
    nivel: int
    idioma: str
    estado: str
    estado_indexacion: str
    hash_archivo: str | None
    ruta_blob: str | None
    pagina_inicio_cuerpo: int | None
    pagina_fin_cuerpo: int | None
    total_fragmentos: int


@dataclass
class Trabajo:
    id_trabajo: str
    id_documento: str
    tipo: str


class Repositorio:
    def __init__(self, engine: Engine):
        self.engine = engine

    @classmethod
    def desde_url(cls, url: str) -> "Repositorio":
        return cls(create_engine(url, pool_pre_ping=True, pool_size=2, max_overflow=2))

    # Parámetros ---------------------------------------------------------------
    def parametros_fragmentacion(self) -> tuple[int, int, int]:
        with self.engine.connect() as c:
            filas = dict(c.execute(text(
                """SELECT clave, valor FROM configuracion.parametro_sistema
                    WHERE vigente_hasta IS NULL
                      AND clave IN ('TAMANO_FRAGMENTO_TOKENS','TAMANO_MAX_FRAGMENTO_TOKENS','SOLAPAMIENTO_TOKENS')"""
            )).all())
        return (int(filas.get("TAMANO_FRAGMENTO_TOKENS", 500)), int(filas.get("TAMANO_MAX_FRAGMENTO_TOKENS", 800)),
                int(filas.get("SOLAPAMIENTO_TOKENS", 80)))

    # Documentos ---------------------------------------------------------------
    def documento(self, id_documento: str) -> Documento:
        with self.engine.connect() as c:
            fila = c.execute(text(
                """SELECT id_documento::text, titulo, codigo_documento, nivel, idioma, estado, estado_indexacion,
                          hash_archivo, ruta_blob, pagina_inicio_cuerpo, pagina_fin_cuerpo, total_fragmentos
                     FROM conocimiento.documento_fuente WHERE id_documento = :id"""
            ), {"id": id_documento}).mappings().first()
        if fila is None:
            raise LookupError(f"No existe el documento {id_documento} en conocimiento.documento_fuente")
        return Documento(**fila)

    def documento_con_hash(self, hash_archivo: str) -> str | None:
        with self.engine.connect() as c:
            return c.execute(text("SELECT id_documento::text FROM conocimiento.documento_fuente WHERE hash_archivo = :h"),
                             {"h": hash_archivo}).scalar()

    def registrar_archivo(self, id_documento: str, ruta: str, hash_archivo: str) -> None:
        with self.engine.begin() as c:
            c.execute(text(
                """UPDATE conocimiento.documento_fuente
                      SET ruta_blob = :r, hash_archivo = :h, estado_indexacion = 'EN_PROCESO'
                    WHERE id_documento = :id"""
            ), {"r": ruta, "h": hash_archivo, "id": id_documento})

    def marcar_error(self, id_documento: str) -> None:
        with self.engine.begin() as c:
            c.execute(text("UPDATE conocimiento.documento_fuente SET estado_indexacion = 'ERROR' WHERE id_documento = :id"),
                      {"id": id_documento})

    def version_actual(self, id_documento: str) -> int:
        with self.engine.connect() as c:
            return c.execute(text(
                "SELECT coalesce(max(version_indexacion), 0) FROM conocimiento.fragmento WHERE id_documento = :id"
            ), {"id": id_documento}).scalar()

    def contar_fragmentos(self, id_documento: str, version: int | None = None) -> int:
        with self.engine.connect() as c:
            return c.execute(text(
                """SELECT count(*) FROM conocimiento.fragmento
                    WHERE id_documento = :id AND version_indexacion = coalesce(:v, version_indexacion)"""
            ), {"id": id_documento, "v": version}).scalar()

    def fragmentos(self, id_documento: str, version: int) -> list[dict]:
        with self.engine.connect() as c:
            return [dict(f) for f in c.execute(text(
                """SELECT id_fragmento::text, numero_orden, seccion, pagina_inicio, pagina_fin, texto, numero_tokens,
                          vigente, motivo_exclusion, tipo_contenido, fuente_texto, verificado
                     FROM conocimiento.fragmento WHERE id_documento = :id AND version_indexacion = :v
                    ORDER BY numero_orden"""
            ), {"id": id_documento, "v": version}).mappings()]

    # Escritura de una versión (dentro de la transacción del llamador) ---------
    @staticmethod
    def retirar_versiones_anteriores(c: Connection, id_documento: str, version: int) -> int:
        return c.execute(text(
            """UPDATE conocimiento.fragmento
                  SET vigente = false,
                      motivo_exclusion = coalesce(motivo_exclusion, 'REINDEXADO: reemplazado por la versión ' || :v)
                WHERE id_documento = :id AND version_indexacion < :v AND vigente"""
        ), {"id": id_documento, "v": version}).rowcount

    @staticmethod
    def insertar_fragmentos(c: Connection, id_documento: str, version: int, modelo: str,
                            fragmentos: list[Fragmento], ids: list[str]) -> None:
        c.execute(text(
            """INSERT INTO conocimiento.fragmento
                 (id_fragmento, id_documento, numero_orden, seccion, pagina_inicio, pagina_fin, texto, numero_tokens,
                  terminos_mesh, conceptos_umls, modelo_embedding, vigente, id_documento_modificatorio, motivo_exclusion,
                  tipo_contenido, fuente_texto, verificado, fecha_verificacion, version_indexacion,
                  edad_min_meses, edad_max_meses, poblacion, origen_rango, rango_dudoso)
               VALUES (:id, :doc, :orden, :seccion, :pi, :pf, :texto, :tokens, '{}', '{}', :modelo, :vigente, :mod,
                       :motivo, :tipo, :fuente, :verificado, :fecha, :version, :emin, :emax, :pob, :origen,
                       :dudoso)"""
        ), [
            {"id": i, "doc": id_documento, "orden": f.orden, "seccion": f.seccion, "pi": f.pagina_inicio,
             "pf": f.pagina_fin, "texto": f.texto, "tokens": f.numero_tokens, "modelo": modelo, "vigente": f.vigente,
             "mod": f.id_documento_modificatorio, "motivo": f.motivo_exclusion, "tipo": f.tipo_contenido,
             "fuente": f.fuente_texto, "verificado": f.verificado,
             "fecha": f.fecha_verificacion if f.verificado else None, "version": version,
             "emin": f.edad_min_meses, "emax": f.edad_max_meses, "pob": f.poblacion, "origen": f.origen_rango,
             "dudoso": f.rango_dudoso}
            for f, i in zip(fragmentos, ids)
        ])

    @staticmethod
    def completar_documento(c: Connection, id_documento: str, total: int) -> None:
        c.execute(text(
            """UPDATE conocimiento.documento_fuente SET estado_indexacion = 'COMPLETADA', total_fragmentos = :t
                WHERE id_documento = :id"""
        ), {"t": total, "id": id_documento})

    @staticmethod
    def auditar(c: Connection, tipo_evento: str, id_documento: str, detalle: dict,
                id_usuario: str = USUARIO_SISTEMA) -> None:
        c.execute(text(
            """INSERT INTO auditoria.evento_auditoria (id_usuario, tipo_evento, entidad, id_entidad, detalle)
               VALUES (:u, :t, 'documento_fuente', :id, CAST(:d AS jsonb))"""
        ), {"u": id_usuario, "t": tipo_evento, "id": id_documento, "d": json.dumps(detalle, ensure_ascii=False)})

    def auditar_aparte(self, tipo_evento: str, id_documento: str, detalle: dict, id_usuario: str = USUARIO_SISTEMA) -> None:
        with self.engine.begin() as c:
            self.auditar(c, tipo_evento, id_documento, detalle, id_usuario)

    # Trabajos -----------------------------------------------------------------
    def crear_trabajo(self, id_documento: str, tipo: str, solicitado_por: str = USUARIO_SISTEMA,
                      estado: str = "PENDIENTE") -> str:
        with self.engine.begin() as c:
            return c.execute(text(
                """INSERT INTO conocimiento.trabajo_indexacion (id_documento, tipo, estado, solicitado_por, fecha_inicio)
                   VALUES (:d, :t, :e, :u, CASE WHEN :en_curso THEN now() END) RETURNING id_trabajo::text"""
            ), {"d": id_documento, "t": tipo, "e": estado, "u": solicitado_por, "en_curso": estado == "EN_CURSO"}).scalar()

    def tomar_trabajo(self) -> Trabajo | None:
        with self.engine.begin() as c:
            fila = c.execute(text(
                """SELECT id_trabajo::text, id_documento::text, tipo FROM conocimiento.trabajo_indexacion
                    WHERE estado = 'PENDIENTE' ORDER BY fecha_solicitud
                    LIMIT 1 FOR UPDATE SKIP LOCKED"""
            )).mappings().first()
            if fila is None:
                return None
            c.execute(text(
                "UPDATE conocimiento.trabajo_indexacion SET estado = 'EN_CURSO', fecha_inicio = now() WHERE id_trabajo = :t"
            ), {"t": fila["id_trabajo"]})
            return Trabajo(**fila)

    def avance(self, id_trabajo: str | None, etapa: str, procesados: int = 0, total: int | None = None) -> None:
        """Transacción corta y separada: la pantalla M11 lee el avance real."""
        if id_trabajo is None:
            return
        with self.engine.begin() as c:
            c.execute(text(
                """UPDATE conocimiento.trabajo_indexacion SET etapa = :e, procesados = :p, total = :t
                    WHERE id_trabajo = :id"""
            ), {"e": etapa, "p": procesados, "t": total, "id": id_trabajo})

    def finalizar_trabajo(self, id_trabajo: str | None, error: str | None = None) -> None:
        if id_trabajo is None:
            return
        with self.engine.begin() as c:
            c.execute(text(
                """UPDATE conocimiento.trabajo_indexacion
                      SET estado = :e, mensaje_error = :m, fecha_fin = now()
                    WHERE id_trabajo = :id"""
            ), {"e": "ERROR" if error else "COMPLETADO", "m": error[:500] if error else None, "id": id_trabajo})
