"""PostgreSQL con el usuario cdss_indexador: solo lee el esquema conocimiento (fragmentos,
documentos y trabajos) e inserta en la bitácora. No hace falta ninguna migración: el rol ya tiene
SELECT en conocimiento e INSERT en auditoria.evento_auditoria."""
import json
from dataclasses import dataclass

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from app.indexador.repositorio import USUARIO_SISTEMA


@dataclass(frozen=True)
class FragmentoEsperado:
    id_documento: str
    vigente: bool
    estado_documento: str
    nivel: int


class FuentePostgres:
    def __init__(self, engine: Engine):
        self.engine = engine

    @classmethod
    def desde_url(cls, url: str) -> "FuentePostgres":
        return cls(create_engine(url, pool_pre_ping=True, pool_size=1, max_overflow=1))

    def trabajos_activos(self) -> int:
        with self.engine.connect() as c:
            return c.execute(text("SELECT count(*) FROM conocimiento.trabajo_indexacion "
                                  "WHERE estado IN ('PENDIENTE', 'EN_CURSO')")).scalar_one()

    def modelos_embedding(self) -> list[str]:
        """Modelos de los fragmentos de la última versión de cada documento (los que están en ChromaDB)."""
        with self.engine.connect() as c:
            return sorted(c.execute(text(
                """SELECT DISTINCT f.modelo_embedding
                     FROM conocimiento.fragmento f
                     JOIN (SELECT id_documento, max(version_indexacion) AS v
                             FROM conocimiento.fragmento GROUP BY id_documento) u
                       ON u.id_documento = f.id_documento AND u.v = f.version_indexacion""")).scalars())

    def fragmentos_esperados(self) -> dict[str, FragmentoEsperado]:
        """Lo que debe haber en la colección: los fragmentos de la última versión de cada documento,
        con su vigencia y el estado y el nivel de su documento."""
        with self.engine.connect() as c:
            filas = c.execute(text(
                """SELECT f.id_fragmento::text, f.id_documento::text, f.vigente, d.estado, d.nivel
                     FROM conocimiento.fragmento f
                     JOIN (SELECT id_documento, max(version_indexacion) AS v
                             FROM conocimiento.fragmento GROUP BY id_documento) u
                       ON u.id_documento = f.id_documento AND u.v = f.version_indexacion
                     JOIN conocimiento.documento_fuente d ON d.id_documento = f.id_documento""")).all()
        return {f[0]: FragmentoEsperado(f[1], f[2], f[3], f[4]) for f in filas}

    def auditar(self, tipo_evento: str, nombre_respaldo: str, detalle: dict) -> None:
        """Evento sin datos personales ni rutas del servidor: solo el nombre del respaldo y conteos."""
        with self.engine.begin() as c:
            c.execute(text(
                """INSERT INTO auditoria.evento_auditoria (id_usuario, tipo_evento, entidad, id_entidad, detalle)
                   VALUES (:u, :t, 'respaldo', :id, CAST(:d AS jsonb))"""),
                {"u": USUARIO_SISTEMA, "t": tipo_evento, "id": nombre_respaldo,
                 "d": json.dumps(detalle, ensure_ascii=False)})
