"""Índice léxico BM25 (3.1) sobre los fragmentos recuperables: vigentes, de la última
versión de indexación de documentos de nivel 1 en estado VIGENTE e indexación
COMPLETADA. Cada fragmento se procesa en el idioma de su documento (sin tildes, sin
palabras vacías y con raíces de snowballstemmer); la consulta en español se busca
con sus raíces en español más los equivalentes en inglés del diccionario.

El índice se reconstruye cuando cambia la huella de la base de conocimiento: número
de fragmentos recuperables y, por documento, su versión vigente, estado y nivel.
Indexar, reindexar, retirar una guía o marcar un fragmento como no vigente cambian
la huella."""
import threading
from dataclasses import dataclass

from rank_bm25 import BM25Okapi
from sqlalchemy import Connection, text
from sqlalchemy.orm import Session

from app.rag.texto import terminos

# Condición de un fragmento recuperable (alias f para fragmento y d para documento_fuente).
CONDICION_RECUPERABLE = """f.vigente AND d.nivel = 1 AND d.estado = 'VIGENTE' AND d.estado_indexacion = 'COMPLETADA'
       AND f.version_indexacion = (SELECT max(v.version_indexacion) FROM conocimiento.fragmento v
                                    WHERE v.id_documento = f.id_documento)"""

FRAGMENTOS_RECUPERABLES = f"""
    SELECT f.id_fragmento::text AS id_fragmento, f.id_documento::text AS id_documento, f.texto, d.idioma,
           f.version_indexacion
      FROM conocimiento.fragmento f
      JOIN conocimiento.documento_fuente d ON d.id_documento = f.id_documento
     WHERE {CONDICION_RECUPERABLE}
"""

HUELLA = f"""
    SELECT count(*) AS fragmentos,
           coalesce(md5(string_agg(DISTINCT r.id_documento || ':' || r.version_indexacion, ',')), '') AS documentos
      FROM ({FRAGMENTOS_RECUPERABLES}) r
"""


@dataclass(frozen=True)
class Huella:
    fragmentos: int
    documentos: str


def huella_conocimiento(sesion: Session | Connection) -> Huella:
    fila = sesion.execute(text(HUELLA)).one()
    return Huella(fila.fragmentos, fila.documentos)


class IndiceBM25:
    def __init__(self, filas: list, huella: Huella):
        self.huella = huella
        self.ids = [f.id_fragmento for f in filas]
        self.documentos = {f.id_fragmento: f.id_documento for f in filas}
        corpus = [terminos(f.texto, f.idioma) for f in filas]
        self._bm25 = BM25Okapi(corpus) if corpus else None

    def __len__(self) -> int:
        return len(self.ids)

    def buscar(self, terminos_consulta: list[str], n: int) -> list[tuple[str, float]]:
        """Los n fragmentos con mayor puntaje BM25 (solo puntajes positivos)."""
        if self._bm25 is None or not terminos_consulta:
            return []
        puntajes = self._bm25.get_scores(terminos_consulta)
        orden = sorted(range(len(self.ids)), key=lambda i: (-puntajes[i], self.ids[i]))
        return [(self.ids[i], float(puntajes[i])) for i in orden[:n] if puntajes[i] > 0]


def terminos_consulta(texto_es: str, equivalentes_ingles: list[str]) -> list[str]:
    return terminos(texto_es, "es") + [t for frase in equivalentes_ingles for t in terminos(frase, "en")]


def construir_indice(sesion: Session | Connection) -> IndiceBM25:
    huella = huella_conocimiento(sesion)
    return IndiceBM25(sesion.execute(text(FRAGMENTOS_RECUPERABLES)).all(), huella)


class CacheBM25:
    """Un índice por proceso del backend; se reconstruye solo si cambió la huella."""

    def __init__(self):
        self._indice: IndiceBM25 | None = None
        self._candado = threading.Lock()
        self.reconstrucciones = 0

    def obtener(self, sesion: Session | Connection) -> IndiceBM25:
        huella = huella_conocimiento(sesion)
        with self._candado:
            if self._indice is None or self._indice.huella != huella:
                self._indice = construir_indice(sesion)
                self.reconstrucciones += 1
            return self._indice
