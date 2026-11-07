"""Motores de inferencia del servicio de modelos.

MotorReal carga bge-m3 (embeddings de 1024 dimensiones) y bge-reranker-v2-m3
(puntaje de relevancia entre 0 y 1) desde la caché local, una sola vez. El reranker
corre por defecto en ONNX con pesos int8 (MODELOS_RERANKER=onnx-int8, ver
onnx_int8.py); con MODELOS_RERANKER=fp32 usa el modelo original con PyTorch. Las
importaciones de PyTorch y sentence-transformers se hacen dentro del constructor
para que el resto del servicio pueda probarse sin ellas (ver motor_falso.py)."""
import threading
from typing import Protocol

from app.catalogo import EMBEDDINGS, RERANKER, cargar_catalogo, ruta_local
from app.config import Config


class Motor(Protocol):
    def info(self) -> dict: ...

    def embeddings(self, textos: list[str]) -> list[list[float]]: ...

    def reranquear(self, consulta: str, candidatos: list[str], max_longitud: int | None = None) -> list[float]: ...

    def contar_tokens(self, textos: list[str]) -> list[int]: ...


class MotorReal:
    def __init__(self, config: Config):
        import torch
        from sentence_transformers import CrossEncoder, SentenceTransformer

        if config.hilos:
            torch.set_num_threads(config.hilos)
        self._hilos = torch.get_num_threads()
        catalogo = cargar_catalogo(config.revisiones)
        self._fijados = {clave: catalogo[clave] for clave in (EMBEDDINGS, RERANKER)}
        self._embedder = SentenceTransformer(str(ruta_local(catalogo[EMBEDDINGS])), device="cpu")
        self._embedder.max_seq_length = config.max_longitud_embedding
        self._formato_reranker = config.reranker
        self._manifiesto_onnx = None
        if config.reranker == "onnx-int8":
            from app.onnx_int8 import RerankerOnnx
            self._reranker = RerankerOnnx(config.dir_onnx, catalogo[RERANKER], self._hilos)
            self._manifiesto_onnx = self._reranker.manifiesto
        else:
            self._reranker = CrossEncoder(str(ruta_local(catalogo[RERANKER])), device="cpu",
                                          max_length=config.max_longitud_reranker)
        self._max_longitudes = {EMBEDDINGS: config.max_longitud_embedding, RERANKER: config.max_longitud_reranker}
        self._candado_reranker = threading.Lock()
        dimension = self._embedder.get_sentence_embedding_dimension()
        if dimension != catalogo[EMBEDDINGS].dimension:
            raise RuntimeError(f"{EMBEDDINGS} devolvió {dimension} dimensiones; se esperaban {catalogo[EMBEDDINGS].dimension}")

    def info(self) -> dict:
        modelos = {clave: {"repositorio": m.repositorio, "revision": m.revision, "dimension": m.dimension,
                           "max_longitud": self._max_longitudes[clave]}
                   for clave, m in self._fijados.items()}
        modelos[RERANKER]["formato"] = self._formato_reranker
        if self._manifiesto_onnx:
            modelos[RERANKER]["sha256_onnx"] = self._manifiesto_onnx["sha256"]
        return {"motor": "real", "hilos": self._hilos, "modelos": modelos}

    def embeddings(self, textos: list[str]) -> list[list[float]]:
        vectores = self._embedder.encode(textos, batch_size=8, normalize_embeddings=True, convert_to_numpy=True)
        return vectores.tolist()

    def reranquear(self, consulta: str, candidatos: list[str], max_longitud: int | None = None) -> list[float]:
        # Con una sola etiqueta, CrossEncoder aplica la función sigmoide: puntajes entre 0 y 1.
        # max_longitud acorta el par consulta y candidato en esta petición, sin superar el
        # máximo configurado; el candado evita que otra inferencia vea la longitud cambiada.
        maximo = self._max_longitudes[RERANKER]
        longitud = min(max_longitud, maximo) if max_longitud else maximo
        if self._formato_reranker == "onnx-int8":
            return self._reranker.puntuar(consulta, candidatos, longitud)
        with self._candado_reranker:
            self._reranker.max_length = longitud
            try:
                puntajes = self._reranker.predict([(consulta, c) for c in candidatos], batch_size=8,
                                                  convert_to_numpy=True)
            finally:
                self._reranker.max_length = maximo
        return [float(p) for p in puntajes]

    def contar_tokens(self, textos: list[str]) -> list[int]:
        ids = self._embedder.tokenizer(textos, add_special_tokens=False)["input_ids"]
        return [len(i) for i in ids]


def crear_motor(config: Config) -> Motor:
    if config.motor == "falso":
        from app.motor_falso import MotorFalso
        return MotorFalso()
    return MotorReal(config)
