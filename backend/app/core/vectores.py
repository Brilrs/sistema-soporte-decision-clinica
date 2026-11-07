"""Almacén de vectores: ChromaDB por HTTP (colección guias_clinicas, distancia
coseno) y una versión en memoria para las pruebas. El indexador escribe y la
recuperación (app.rag) consulta."""
import math
from dataclasses import dataclass, field
from typing import Protocol
from urllib.parse import urlparse

COLECCION = "guias_clinicas"


@dataclass
class RegistroVector:
    id: str
    vector: list[float]
    texto: str
    metadatos: dict = field(default_factory=dict)


class AlmacenVectorial(Protocol):
    def agregar(self, registros: list[RegistroVector]) -> None: ...

    def eliminar(self, ids: list[str]) -> None: ...

    def ids_de_documento(self, id_documento: str) -> list[str]: ...

    def consultar(self, vector: list[float], n: int, filtro: dict | None = None) -> list[tuple[str, float]]: ...


def _cumple(metadatos: dict, filtro: dict | None) -> bool:
    return not filtro or all(metadatos.get(k) == v for k, v in filtro.items())


def _distancia_coseno(a: list[float], b: list[float]) -> float:
    producto = sum(x * y for x, y in zip(a, b))
    normas = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return 1.0 - (producto / normas if normas else 0.0)


def filtro_chroma(filtro: dict | None) -> dict | None:
    """Filtro de igualdad por metadatos con la sintaxis de ChromaDB ($and para varias condiciones)."""
    if not filtro:
        return None
    condiciones = [{k: {"$eq": v}} for k, v in filtro.items()]
    return condiciones[0] if len(condiciones) == 1 else {"$and": condiciones}


class AlmacenMemoria:
    def __init__(self):
        self.registros: dict[str, RegistroVector] = {}

    def agregar(self, registros: list[RegistroVector]) -> None:
        for r in registros:
            self.registros[r.id] = r

    def eliminar(self, ids: list[str]) -> None:
        for i in ids:
            self.registros.pop(i, None)

    def ids_de_documento(self, id_documento: str) -> list[str]:
        return [r.id for r in self.registros.values() if r.metadatos.get("id_documento") == id_documento]

    def consultar(self, vector: list[float], n: int, filtro: dict | None = None) -> list[tuple[str, float]]:
        """Los n registros más cercanos que cumplen el filtro, con su distancia coseno."""
        distancias = [(r.id, _distancia_coseno(vector, r.vector))
                      for r in self.registros.values() if _cumple(r.metadatos, filtro)]
        return sorted(distancias, key=lambda d: (d[1], d[0]))[:n]


class AlmacenChroma:
    def __init__(self, url: str, coleccion: str = COLECCION, lote: int = 64):
        import chromadb
        from chromadb.config import Settings

        destino = urlparse(url)
        cliente = chromadb.HttpClient(
            host=destino.hostname, port=destino.port or 8000, settings=Settings(anonymized_telemetry=False)
        )
        self._coleccion = cliente.get_or_create_collection(coleccion, metadata={"hnsw:space": "cosine"})
        self._lote = lote

    def agregar(self, registros: list[RegistroVector]) -> None:
        for i in range(0, len(registros), self._lote):
            parte = registros[i:i + self._lote]
            self._coleccion.upsert(
                ids=[r.id for r in parte],
                embeddings=[r.vector for r in parte],
                documents=[r.texto for r in parte],
                metadatas=[r.metadatos for r in parte],
            )

    def eliminar(self, ids: list[str]) -> None:
        for i in range(0, len(ids), self._lote):
            self._coleccion.delete(ids=ids[i:i + self._lote])

    def ids_de_documento(self, id_documento: str) -> list[str]:
        return self._coleccion.get(where={"id_documento": id_documento}, include=[])["ids"]

    def consultar(self, vector: list[float], n: int, filtro: dict | None = None) -> list[tuple[str, float]]:
        r = self._coleccion.query(query_embeddings=[vector], n_results=n, where=filtro_chroma(filtro),
                                  include=["distances"])
        return list(zip(r["ids"][0], r["distances"][0]))
