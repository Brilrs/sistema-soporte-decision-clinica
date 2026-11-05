"""Motores de inferencia del servicio de modelos.

MotorReal carga bge-m3 (embeddings de 1024 dimensiones) y bge-reranker-v2-m3
(puntaje de relevancia entre 0 y 1) desde la caché local, una sola vez. Las
importaciones de PyTorch y sentence-transformers se hacen dentro del constructor
para que el resto del servicio pueda probarse sin ellas (ver motor_falso.py)."""
from typing import Protocol

from app.catalogo import EMBEDDINGS, RERANKER, cargar_catalogo, ruta_local
from app.config import Config


class Motor(Protocol):
    def info(self) -> dict: ...

    def embeddings(self, textos: list[str]) -> list[list[float]]: ...

    def reranquear(self, consulta: str, candidatos: list[str]) -> list[float]: ...

    def contar_tokens(self, textos: list[str]) -> list[int]: ...


class MotorReal:
    def __init__(self, config: Config):
        import torch
        from sentence_transformers import CrossEncoder, SentenceTransformer

        if config.hilos:
            torch.set_num_threads(config.hilos)
        catalogo = cargar_catalogo(config.revisiones)
        self._fijados = {clave: catalogo[clave] for clave in (EMBEDDINGS, RERANKER)}
        self._embedder = SentenceTransformer(str(ruta_local(catalogo[EMBEDDINGS])), device="cpu")
        self._embedder.max_seq_length = config.max_longitud_embedding
        self._reranker = CrossEncoder(str(ruta_local(catalogo[RERANKER])), device="cpu",
                                      max_length=config.max_longitud_reranker)
        self._max_longitudes = {EMBEDDINGS: config.max_longitud_embedding, RERANKER: config.max_longitud_reranker}
        dimension = self._embedder.get_sentence_embedding_dimension()
        if dimension != catalogo[EMBEDDINGS].dimension:
            raise RuntimeError(f"{EMBEDDINGS} devolvió {dimension} dimensiones; se esperaban {catalogo[EMBEDDINGS].dimension}")

    def info(self) -> dict:
        return {
            "motor": "real",
            "modelos": {clave: {"repositorio": m.repositorio, "revision": m.revision, "dimension": m.dimension,
                                "max_longitud": self._max_longitudes[clave]}
                        for clave, m in self._fijados.items()},
        }

    def embeddings(self, textos: list[str]) -> list[list[float]]:
        vectores = self._embedder.encode(textos, batch_size=8, normalize_embeddings=True, convert_to_numpy=True)
        return vectores.tolist()

    def reranquear(self, consulta: str, candidatos: list[str]) -> list[float]:
        # Con una sola etiqueta, CrossEncoder aplica la función sigmoide: puntajes entre 0 y 1.
        puntajes = self._reranker.predict([(consulta, c) for c in candidatos], batch_size=8, convert_to_numpy=True)
        return [float(p) for p in puntajes]

    def contar_tokens(self, textos: list[str]) -> list[int]:
        ids = self._embedder.tokenizer(textos, add_special_tokens=False)["input_ids"]
        return [len(i) for i in ids]


def crear_motor(config: Config) -> Motor:
    if config.motor == "falso":
        from app.motor_falso import MotorFalso
        return MotorFalso()
    return MotorReal(config)
