"""bge-reranker-v2-m3 en ONNX con pesos int8 (cuantización dinámica).

El modelo se exporta una vez desde la revisión fijada de revisiones.json con
app.exportar_onnx y queda en MODELOS_DIR_ONNX (./data/modelos/onnx en el equipo),
junto con el tokenizador y un manifiesto con la revisión de origen, las versiones
de las librerías usadas y el SHA-256 del archivo ONNX. El servicio comprueba el
manifiesto al cargar el modelo: si la revisión no coincide o el archivo cambió, no
arranca. Las importaciones de onnxruntime y transformers se hacen dentro de las
funciones para que el resto del servicio pueda probarse sin ellas."""
import hashlib
import json
import math
from pathlib import Path

from app.catalogo import ModeloFijado

CARPETA = "bge-reranker-v2-m3-int8"
ARCHIVO = "model_quantized.onnx"
MANIFIESTO = "manifiesto.json"
LIBRERIAS = ("torch", "transformers", "optimum", "onnx", "onnxruntime")


def carpeta(dir_onnx: Path) -> Path:
    return dir_onnx / CARPETA


def sha256(ruta: Path) -> str:
    h = hashlib.sha256()
    with ruta.open("rb") as f:
        for bloque in iter(lambda: f.read(1 << 20), b""):
            h.update(bloque)
    return h.hexdigest()


def leer_manifiesto(dir_onnx: Path) -> dict | None:
    ruta = carpeta(dir_onnx) / MANIFIESTO
    return json.loads(ruta.read_text(encoding="utf-8")) if ruta.exists() else None


def comprobar(dir_onnx: Path, modelo: ModeloFijado, verificar_hash: bool = True) -> dict:
    """Devuelve el manifiesto si la exportación corresponde a la revisión fijada."""
    manifiesto = leer_manifiesto(dir_onnx)
    if manifiesto is None or not (carpeta(dir_onnx) / ARCHIVO).exists():
        raise RuntimeError(f"No se encontró el reranker ONNX int8 en {carpeta(dir_onnx)}. "
                           "Expórtelo con: docker compose run --rm exportar-onnx")
    if manifiesto.get("repositorio") != modelo.repositorio or manifiesto.get("revision") != modelo.revision:
        raise RuntimeError(f"El reranker ONNX se exportó desde {manifiesto.get('repositorio')} "
                           f"{str(manifiesto.get('revision'))[:12]} y la revisión fijada es {modelo.revision[:12]}. "
                           "Vuelva a exportarlo con: docker compose run --rm exportar-onnx --forzar")
    if verificar_hash and sha256(carpeta(dir_onnx) / ARCHIVO) != manifiesto.get("sha256"):
        raise RuntimeError(f"{ARCHIVO} no coincide con el SHA-256 del manifiesto. "
                           "Vuelva a exportarlo con: docker compose run --rm exportar-onnx --forzar")
    return manifiesto


class RerankerOnnx:
    """Puntúa pares consulta y candidato con onnxruntime. Tokeniza igual que
    CrossEncoder de sentence-transformers (relleno al más largo del lote y
    truncamiento longest_first) y aplica la sigmoide al logit."""

    def __init__(self, dir_onnx: Path, modelo: ModeloFijado, hilos: int):
        import onnxruntime
        from transformers import AutoTokenizer

        self.manifiesto = comprobar(dir_onnx, modelo)
        self._tokenizador = AutoTokenizer.from_pretrained(str(carpeta(dir_onnx)))
        opciones = onnxruntime.SessionOptions()
        opciones.intra_op_num_threads = hilos
        opciones.inter_op_num_threads = 1
        self._sesion = onnxruntime.InferenceSession(str(carpeta(dir_onnx) / ARCHIVO), opciones,
                                                    providers=["CPUExecutionProvider"])
        self._entradas = {e.name for e in self._sesion.get_inputs()}

    def puntuar(self, consulta: str, candidatos: list[str], max_longitud: int, lote: int = 8) -> list[float]:
        import numpy as np

        puntajes = []
        for i in range(0, len(candidatos), lote):
            parte = candidatos[i:i + lote]
            tokens = self._tokenizador([consulta] * len(parte), parte, padding=True, truncation="longest_first",
                                       max_length=max_longitud, return_tensors="np")
            entrada = {k: v.astype(np.int64) for k, v in tokens.items() if k in self._entradas}
            logits = self._sesion.run(None, entrada)[0].reshape(-1)
            puntajes += [1 / (1 + math.exp(-float(x))) for x in logits]
        return puntajes
