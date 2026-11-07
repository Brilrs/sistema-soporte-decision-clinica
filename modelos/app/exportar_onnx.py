"""Exporta bge-reranker-v2-m3 a ONNX y cuantiza sus pesos a int8.

Se ejecuta una vez, después de descargar los modelos:
    docker compose run --rm exportar-onnx
Parte de la revisión fijada en revisiones.json (debe estar en la caché local; no
descarga nada), exporta con optimum (fp32, con datos externos porque el modelo
supera los 2 GB), cuantiza los pesos a int8 dinámico con onnxruntime, copia el
tokenizador y escribe manifiesto.json con la revisión, las versiones de las
librerías y el SHA-256 del resultado. La exportación fp32 intermedia se borra al
terminar. Si ya existe una exportación válida de la misma revisión, no hace nada
(--forzar la repite). Las versiones de las librerías están fijadas en
requirements-ml.txt."""
import argparse
import importlib.metadata
import json
import shutil
import sys
import time
from pathlib import Path

from app.catalogo import RERANKER, cargar_catalogo, ruta_local
from app.config import cargar_config
from app.onnx_int8 import ARCHIVO, LIBRERIAS, MANIFIESTO, carpeta, comprobar, sha256


def _versiones() -> dict:
    return {nombre: importlib.metadata.version(nombre) for nombre in LIBRERIAS}


def exportar(origen: Path, destino: Path) -> None:
    from onnxruntime.quantization import QuantType, quantize_dynamic
    from optimum.exporters.onnx import main_export
    from transformers import AutoTokenizer

    intermedia = destino.with_name(destino.name + ".fp32-tmp")
    shutil.rmtree(intermedia, ignore_errors=True)
    shutil.rmtree(destino, ignore_errors=True)
    try:
        main_export(str(origen), output=intermedia, task="text-classification", do_validation=False, device="cpu")
        destino.mkdir(parents=True)
        quantize_dynamic(str(intermedia / "model.onnx"), str(destino / ARCHIVO), weight_type=QuantType.QInt8,
                         per_channel=False)
        AutoTokenizer.from_pretrained(str(origen)).save_pretrained(destino)
        shutil.copy(origen / "config.json", destino / "config.json")
    finally:
        shutil.rmtree(intermedia, ignore_errors=True)


def main(argumentos: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Exporta el reranker a ONNX int8")
    parser.add_argument("--forzar", action="store_true", help="Repite la exportación aunque ya exista")
    args = parser.parse_args(argumentos)
    config = cargar_config()
    modelo = cargar_catalogo(config.revisiones)[RERANKER]
    destino = carpeta(config.dir_onnx)
    if not args.forzar:
        try:
            comprobar(config.dir_onnx, modelo)
            print(f"El reranker ONNX int8 ya está exportado en {destino}")
            return 0
        except RuntimeError:
            pass
    try:
        origen = ruta_local(modelo)
    except RuntimeError as e:
        print(e, file=sys.stderr)
        return 1
    print(f"Exportando {modelo.repositorio} ({modelo.revision[:12]}) a {destino}...", flush=True)
    inicio = time.perf_counter()
    exportar(origen, destino)
    manifiesto = {"repositorio": modelo.repositorio, "revision": modelo.revision, "formato": "onnx-int8",
                  "cuantizacion": "dinámica, pesos QInt8 por tensor", "archivo": ARCHIVO,
                  "sha256": sha256(destino / ARCHIVO), "versiones": _versiones(),
                  "fecha": time.strftime("%Y-%m-%d %H:%M:%S")}
    (destino / MANIFIESTO).write_text(json.dumps(manifiesto, ensure_ascii=False, indent=2), encoding="utf-8")
    tamano = (destino / ARCHIVO).stat().st_size / 1024 / 1024
    print(f"Listo en {time.perf_counter() - inicio:.0f} s: {ARCHIVO} de {tamano:,.0f} MB, SHA-256 "
          f"{manifiesto['sha256'][:12]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
