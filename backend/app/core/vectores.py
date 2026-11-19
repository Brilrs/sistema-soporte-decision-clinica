"""Almacén de vectores: ChromaDB por HTTP (colección guias_clinicas, distancia
coseno) y una versión en memoria para las pruebas. El indexador escribe y la
recuperación (app.rag) consulta.

El respaldo (app.respaldo, Sprint 3 parte K) usa además la lectura por lotes (ids, obtener,
contar), los metadatos de la colección y los «servidores» (ServidorChroma y ServidorMemoria),
que listan, abren, crean y borran colecciones. Solo se borran colecciones de prueba: el nombre
debe empezar con PREFIJO_PRUEBA (exigir_coleccion_de_prueba)."""
import math
import struct
from dataclasses import dataclass, field
from typing import Protocol
from urllib.parse import urlparse

COLECCION = "guias_clinicas"
PREFIJO_PRUEBA = "guias_clinicas_prueba_"
# Metadato de la colección con la distancia del índice HNSW. ChromaDB usa l2 si no se indica;
# la recuperación del CDSS necesita coseno.
ESPACIO = "hnsw:space"
METADATOS_COLECCION = {ESPACIO: "cosine"}


class ErrorColeccion(Exception):
    """Operación sobre una colección que no se permite (nombre real, ya existe, no existe)."""


def exigir_coleccion_de_prueba(nombre: str) -> None:
    """Única barrera antes de borrar una colección: solo las de prueba, nunca guias_clinicas."""
    if nombre == COLECCION or not nombre.startswith(PREFIJO_PRUEBA) or len(nombre) <= len(PREFIJO_PRUEBA):
        raise ErrorColeccion(f"Solo se pueden descartar colecciones de prueba, cuyo nombre empieza con "
                             f"«{PREFIJO_PRUEBA}». La colección «{nombre}» no se borra.")


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

    def metadatos_de_documento(self, id_documento: str) -> dict[str, dict]: ...

    def actualizar_metadatos(self, ids: list[str], cambios: dict) -> None: ...

    def consultar(self, vector: list[float], n: int, filtro: dict | None = None) -> list[tuple[str, float]]: ...


def _cumple(metadatos: dict, filtro: dict | None) -> bool:
    return not filtro or all(metadatos.get(k) == v for k, v in filtro.items())


def _distancia_coseno(a: list[float], b: list[float]) -> float:
    producto = sum(x * y for x, y in zip(a, b))
    normas = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return 1.0 - (producto / normas if normas else 0.0)


def _distancia(espacio: str, a: list[float], b: list[float]) -> float:
    """Las tres distancias de ChromaDB: coseno, l2 (al cuadrado) e ip (1 menos el producto)."""
    if espacio == "cosine":
        return _distancia_coseno(a, b)
    if espacio == "ip":
        return 1.0 - sum(x * y for x, y in zip(a, b))
    return sum((x - y) ** 2 for x, y in zip(a, b))


def filtro_chroma(filtro: dict | None) -> dict | None:
    """Filtro de igualdad por metadatos con la sintaxis de ChromaDB ($and para varias condiciones)."""
    if not filtro:
        return None
    condiciones = [{k: {"$eq": v}} for k, v in filtro.items()]
    return condiciones[0] if len(condiciones) == 1 else {"$and": condiciones}


def _float32(x: float) -> float:
    return struct.unpack("f", struct.pack("f", x))[0]


def normalizar_float32(vector: list[float]) -> list[float]:
    """Lo que hace ChromaDB (hnswlib, normalize_vector) al guardar en una colección con distancia coseno:
    acumula la norma en float32, multiplica cada componente por 1 / (raíz de la norma + 1e-30) y guarda
    en float32. Sobre un vector ya unitario cambia el último dígito de algunos componentes (unos 3e-8),
    así que el vector que vuelve no es bit a bit el que se exportó."""
    v = [_float32(x) for x in vector]
    norma = 0.0
    for x in v:
        norma = _float32(norma + _float32(x * x))
    inverso = _float32(1.0 / (_float32(math.sqrt(norma)) + 1e-30))
    return [_float32(x * inverso) for x in v]


class AlmacenMemoria:
    def __init__(self, metadatos_coleccion: dict | None = None, normalizar_como_chroma: bool = False):
        self.registros: dict[str, RegistroVector] = {}
        # Por omisión, como la colección real (coseno). ServidorMemoria.crear pasa los metadatos
        # explícitos: sin ESPACIO, la distancia es l2, como en ChromaDB.
        self.metadatos_coleccion = dict(METADATOS_COLECCION if metadatos_coleccion is None else metadatos_coleccion)
        # Solo pruebas: con distancia coseno, normaliza en float32 al agregar, como ChromaDB.
        self.normalizar_como_chroma = normalizar_como_chroma

    def agregar(self, registros: list[RegistroVector]) -> None:
        normalizar = self.normalizar_como_chroma and self.metadatos_coleccion.get(ESPACIO) == "cosine"
        for r in registros:
            if normalizar:
                r = RegistroVector(r.id, normalizar_float32(r.vector), r.texto, dict(r.metadatos))
            self.registros[r.id] = r

    def eliminar(self, ids: list[str]) -> None:
        for i in ids:
            self.registros.pop(i, None)

    def ids_de_documento(self, id_documento: str) -> list[str]:
        return [r.id for r in self.registros.values() if r.metadatos.get("id_documento") == id_documento]

    def metadatos_de_documento(self, id_documento: str) -> dict[str, dict]:
        return {r.id: dict(r.metadatos) for r in self.registros.values() if r.metadatos.get("id_documento") == id_documento}

    def actualizar_metadatos(self, ids: list[str], cambios: dict) -> None:
        """Cambia solo los metadatos indicados; el vector y el texto no se tocan."""
        for i in ids:
            if i in self.registros:
                self.registros[i].metadatos = {**self.registros[i].metadatos, **cambios}

    def consultar(self, vector: list[float], n: int, filtro: dict | None = None) -> list[tuple[str, float]]:
        """Los n registros más cercanos que cumplen el filtro, con la distancia de la colección."""
        espacio = self.metadatos_coleccion.get(ESPACIO, "l2")
        distancias = [(r.id, _distancia(espacio, vector, r.vector))
                      for r in self.registros.values() if _cumple(r.metadatos, filtro)]
        return sorted(distancias, key=lambda d: (d[1], d[0]))[:n]

    # Lectura por lotes (respaldo) -----------------------------------------------
    def contar(self) -> int:
        return len(self.registros)

    def ids(self) -> list[str]:
        return sorted(self.registros)

    def obtener(self, ids: list[str]) -> list[RegistroVector]:
        """Copias de los registros pedidos (los que existen), en el orden de ids."""
        return [RegistroVector(r.id, list(r.vector), r.texto, dict(r.metadatos))
                for r in (self.registros.get(i) for i in ids) if r is not None]


class ServidorMemoria:
    """Varias colecciones en memoria, con la misma interfaz que ServidorChroma (pruebas). Con
    normalizar_como_chroma, las colecciones con distancia coseno normalizan en float32 al agregar."""

    def __init__(self, normalizar_como_chroma: bool = False):
        self.colecciones: dict[str, AlmacenMemoria] = {}
        self.normalizar_como_chroma = normalizar_como_chroma

    def version(self) -> str:
        return "memoria"

    def listar(self) -> list[str]:
        return sorted(self.colecciones)

    def abrir(self, nombre: str) -> AlmacenMemoria | None:
        return self.colecciones.get(nombre)

    def crear(self, nombre: str, metadatos: dict | None) -> AlmacenMemoria:
        if nombre in self.colecciones:
            raise ErrorColeccion(f"La colección «{nombre}» ya existe")
        self.colecciones[nombre] = AlmacenMemoria(dict(metadatos or {}), self.normalizar_como_chroma)
        return self.colecciones[nombre]

    def borrar(self, nombre: str) -> None:
        exigir_coleccion_de_prueba(nombre)
        if nombre not in self.colecciones:
            raise ErrorColeccion(f"La colección «{nombre}» no existe")
        del self.colecciones[nombre]


def _cliente_chroma(url: str):
    import chromadb
    from chromadb.config import Settings

    destino = urlparse(url)
    return chromadb.HttpClient(host=destino.hostname, port=destino.port or 8000,
                               settings=Settings(anonymized_telemetry=False))


class AlmacenChroma:
    def __init__(self, url: str, coleccion: str = COLECCION, lote: int = 64, *, _coleccion=None):
        """Sin _coleccion, abre la colección o la crea con distancia coseno (indexador y recuperación).
        ServidorChroma pasa una colección ya abierta o creada con sus metadatos."""
        if _coleccion is None:
            _coleccion = _cliente_chroma(url).get_or_create_collection(coleccion, metadata=dict(METADATOS_COLECCION))
        self._coleccion = _coleccion
        self._lote = lote

    @property
    def metadatos_coleccion(self) -> dict:
        return dict(self._coleccion.metadata or {})

    def contar(self) -> int:
        return self._coleccion.count()

    def ids(self) -> list[str]:
        """Todos los ids, leídos por páginas y ordenados."""
        ids: list[str] = []
        pagina = max(self._lote, 500)
        while True:
            parte = self._coleccion.get(include=[], limit=pagina, offset=len(ids))["ids"]
            ids.extend(parte)
            if len(parte) < pagina:
                return sorted(ids)

    def obtener(self, ids: list[str]) -> list[RegistroVector]:
        """Vector, texto y metadatos de cada id tal como los devuelve ChromaDB, por lotes, en el orden de
        ids. Los floats de ChromaDB (float32) pasan a float de Python sin pérdida. Con coseno, ChromaDB
        guarda el vector normalizado en float32 (normalizar_float32)."""
        registros: dict[str, RegistroVector] = {}
        for i in range(0, len(ids), self._lote):
            r = self._coleccion.get(ids=ids[i:i + self._lote], include=["embeddings", "documents", "metadatas"])
            for id_, vector, texto, meta in zip(r["ids"], r["embeddings"], r["documents"], r["metadatas"]):
                registros[id_] = RegistroVector(id_, [float(x) for x in vector], texto or "", dict(meta or {}))
        return [registros[i] for i in ids if i in registros]

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

    def metadatos_de_documento(self, id_documento: str) -> dict[str, dict]:
        r = self._coleccion.get(where={"id_documento": id_documento}, include=["metadatas"])
        return {i: dict(m or {}) for i, m in zip(r["ids"], r["metadatas"])}

    def actualizar_metadatos(self, ids: list[str], cambios: dict) -> None:
        """Actualiza los metadatos por lotes con update (sin borrar ni volver a calcular vectores). Se
        envía el metadato completo, ya combinado, para no depender de cómo combina la versión de ChromaDB."""
        for i in range(0, len(ids), self._lote):
            actuales = self._coleccion.get(ids=ids[i:i + self._lote], include=["metadatas"])
            self._coleccion.update(ids=actuales["ids"],
                                   metadatas=[{**(m or {}), **cambios} for m in actuales["metadatas"]])

    def consultar(self, vector: list[float], n: int, filtro: dict | None = None) -> list[tuple[str, float]]:
        r = self._coleccion.query(query_embeddings=[vector], n_results=n, where=filtro_chroma(filtro),
                                  include=["distances"])
        return list(zip(r["ids"][0], r["distances"][0]))


class ServidorChroma:
    """Colecciones de un servidor ChromaDB (respaldo). Nunca borra la colección real."""

    def __init__(self, url: str, lote: int = 64):
        self._url = url
        self._cliente = _cliente_chroma(url)
        self._lote = lote

    def version(self) -> str:
        return str(self._cliente.get_version())

    def listar(self) -> list[str]:
        # En ChromaDB 0.6 list_collections devuelve nombres; en versiones anteriores, objetos.
        return sorted(c if isinstance(c, str) else c.name for c in self._cliente.list_collections())

    def abrir(self, nombre: str) -> AlmacenChroma | None:
        if nombre not in self.listar():
            return None
        return AlmacenChroma(self._url, nombre, self._lote, _coleccion=self._cliente.get_collection(nombre))

    def crear(self, nombre: str, metadatos: dict | None) -> AlmacenChroma:
        if nombre in self.listar():
            raise ErrorColeccion(f"La colección «{nombre}» ya existe")
        coleccion = self._cliente.create_collection(nombre, metadata=dict(metadatos) if metadatos else None)
        return AlmacenChroma(self._url, nombre, self._lote, _coleccion=coleccion)

    def borrar(self, nombre: str) -> None:
        exigir_coleccion_de_prueba(nombre)
        if nombre not in self.listar():
            raise ErrorColeccion(f"La colección «{nombre}» no existe")
        self._cliente.delete_collection(nombre)
