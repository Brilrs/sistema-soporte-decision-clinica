"""Almacén de vectores: ChromaDB por HTTP (colección guias_clinicas, distancia
coseno) y una versión en memoria para las pruebas."""
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
