"""Mide rerankers alternativos con los mismos candidatos que la medición de calidad
(data/mediciones/b_calidad.json), para compararlos con bge-reranker-v2-m3 en fp32.

    preparar onnx-int8   exporta bge-reranker-v2-m3 (revisión fijada) a ONNX y lo
                         cuantiza a int8 dinámico (AVX2), en /modelos/experimentos
    preparar mmarco      descarga cross-encoder/mmarco-mMiniLMv2-L12-H384-v1, un
                         reranker multilingüe de 118 M de parámetros
    medir <variante>     puntúa los 20 candidatos de cada consulta con una longitud
                         máxima y mide el tiempo con 20, 12 y 8 candidatos

Variantes: fp32 (PyTorch, como el servicio), onnx-int8, mmarco (PyTorch) y
mmarco-onnx-int8. La salida tiene el formato de calidad de
app.scripts.medir_recuperacion, con el nombre del reranker y las latencias."""
import argparse
import json
import math
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, "/srv")

EXPERIMENTOS = Path(os.environ.get("EXPERIMENTOS", "/modelos/experimentos"))
MMARCO = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"
VARIANTES = {
    "fp32": ("torch", None),
    "onnx-int8": ("onnx", EXPERIMENTOS / "bge-reranker-v2-m3-onnx-int8"),
    "mmarco": ("torch", EXPERIMENTOS / "mmarco-mMiniLMv2-L12-H384-v1"),
    "mmarco-onnx-int8": ("onnx", EXPERIMENTOS / "mmarco-mMiniLMv2-L12-H384-v1-onnx-int8"),
}


def _ruta_bge() -> Path:
    from app.catalogo import RERANKER, cargar_catalogo, ruta_local
    return ruta_local(cargar_catalogo(Path("/srv/revisiones.json"))[RERANKER])


def _cuantizar(origen: Path, destino: Path) -> None:
    """Exporta a ONNX fp32 con optimum y cuantiza los pesos a int8 dinámico con
    onnxruntime (el cuantizador de optimum no admite modelos de más de 2 GB, que se
    guardan con datos externos)."""
    import shutil

    from onnxruntime.quantization import QuantType, quantize_dynamic
    from optimum.onnxruntime import ORTModelForSequenceClassification
    from transformers import AutoTokenizer

    fp32 = destino.with_name(destino.name + "-fp32")
    ORTModelForSequenceClassification.from_pretrained(str(origen), export=True).save_pretrained(fp32)
    AutoTokenizer.from_pretrained(str(origen)).save_pretrained(fp32)
    destino.mkdir(parents=True, exist_ok=True)
    quantize_dynamic(str(fp32 / "model.onnx"), str(destino / "model_quantized.onnx"), weight_type=QuantType.QInt8,
                     per_channel=False)
    for archivo in fp32.iterdir():
        if archivo.suffix == ".json" or archivo.name.endswith(".model"):
            shutil.copy(archivo, destino / archivo.name)


def preparar(variante: str) -> None:
    EXPERIMENTOS.mkdir(parents=True, exist_ok=True)
    if variante == "onnx-int8":
        _cuantizar(_ruta_bge(), VARIANTES["onnx-int8"][1])
    elif variante == "mmarco":
        from huggingface_hub import snapshot_download
        ruta = Path(snapshot_download(MMARCO, local_dir=VARIANTES["mmarco"][1],
                                      allow_patterns=["*.json", "*.txt", "*.model", "*.safetensors", "*.bin"]))
        _cuantizar(ruta, VARIANTES["mmarco-onnx-int8"][1])
    else:
        raise SystemExit(f"Variante sin preparación: {variante}")
    print(f"Preparado: {variante}")


class Reranker:
    def __init__(self, variante: str, hilos: int):
        tipo, ruta = VARIANTES[variante]
        ruta = ruta or _ruta_bge()
        from transformers import AutoTokenizer
        self.tokenizador = AutoTokenizer.from_pretrained(str(ruta))
        self.tipo = tipo
        if tipo == "torch":
            import torch
            from transformers import AutoModelForSequenceClassification
            torch.set_num_threads(hilos)
            self.modelo = AutoModelForSequenceClassification.from_pretrained(str(ruta)).eval()
        else:
            import onnxruntime
            from optimum.onnxruntime import ORTModelForSequenceClassification
            opciones = onnxruntime.SessionOptions()
            opciones.intra_op_num_threads = hilos
            archivo = next(ruta.glob("*quantized*.onnx"), None) or next(ruta.glob("*.onnx"))
            self.modelo = ORTModelForSequenceClassification.from_pretrained(str(ruta), file_name=archivo.name,
                                                                            session_options=opciones)

    def puntuar(self, consulta: str, candidatos: list[str], longitud: int, lote: int = 8) -> list[float]:
        puntajes = []
        for i in range(0, len(candidatos), lote):
            parte = candidatos[i:i + lote]
            entrada = self.tokenizador([consulta] * len(parte), parte, padding=True, truncation="longest_first",
                                       max_length=longitud, return_tensors="pt")
            if self.tipo == "torch":
                import torch
                with torch.no_grad():
                    logits = self.modelo(**entrada).logits
            else:
                logits = self.modelo(**entrada).logits
            puntajes += [1 / (1 + math.exp(-float(x))) for x in logits.reshape(-1)]
        return puntajes


def medir(args) -> None:
    calidad = {"consultas": [q for ruta in args.calidad
                             for q in json.loads(Path(ruta).read_text(encoding="utf-8"))["consultas"]]}
    reranker = Reranker(args.variante, args.hilos)
    for q in calidad["consultas"][:2]:
        reranker.puntuar(q["consulta_normalizada"], [c["texto"] for c in q["candidatos"][:4]], args.longitud)
    consultas, latencias = [], {f"{n}x{args.longitud}": [] for n in (20, 12, 8)}
    for k, q in enumerate(calidad["consultas"], start=1):
        textos = [c["texto"] for c in q["candidatos"][:20]]
        inicio = time.perf_counter()
        puntajes = reranker.puntuar(q["consulta_normalizada"], textos, args.longitud)
        latencias[f"20x{args.longitud}"].append(round((time.perf_counter() - inicio) * 1000, 1))
        if k <= args.consultas_latencia:
            for n in (12, 8):
                inicio = time.perf_counter()
                reranker.puntuar(q["consulta_normalizada"], textos[:n], args.longitud)
                latencias[f"{n}x{args.longitud}"].append(round((time.perf_counter() - inicio) * 1000, 1))
        consultas.append({k2: q[k2] for k2 in ("id", "consulta", "consulta_normalizada", "candidatos")}
                         | {"puntajes": {str(args.longitud): puntajes}})
        print(f"[{k}/{len(calidad['consultas'])}] {q['id']} {latencias[f'20x{args.longitud}'][-1]} ms",
              file=sys.stderr, flush=True)
    try:
        cpus = len(os.sched_getaffinity(0))
    except AttributeError:
        cpus = os.cpu_count()
    salida = {"tipo": "calidad", "reranker": f"{args.variante} ({args.longitud} tokens, {args.hilos} hilos, "
                                             f"{cpus} CPU)", "longitudes": [args.longitud],
              "hilos": args.hilos, "cpus": cpus, "latencias_ms": latencias, "consultas": consultas}
    json.dump(salida, sys.stdout, ensure_ascii=False, indent=1)


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="comando", required=True)
    p = sub.add_parser("preparar")
    p.add_argument("variante", choices=["onnx-int8", "mmarco"])
    p = sub.add_parser("medir")
    p.add_argument("variante", choices=list(VARIANTES))
    p.add_argument("--calidad", nargs="+", default=["/datos/b_calidad.json", "/datos/b_calidad_latencia.json",
                                                    "/datos/b_calidad_fuera.json"])
    p.add_argument("--longitud", type=int, default=512)
    p.add_argument("--hilos", type=int, default=2)
    p.add_argument("--consultas-latencia", type=int, default=10)
    args = parser.parse_args()
    preparar(args.variante) if args.comando == "preparar" else medir(args)


if __name__ == "__main__":
    main()
