"""Descarga bge-m3 y bge-reranker-v2-m3 en la revisión fijada de revisiones.json.

Se ejecuta una sola vez:  docker compose run --rm descargar-modelos
Los archivos quedan en HF_HOME (./data/modelos/hf en el equipo), fuera de los
volúmenes de Docker, así que docker compose down -v no los borra. Si ya están
descargados, no se vuelven a bajar. El reranker en ONNX int8 se exporta después, una
vez, con app.exportar_onnx (docker compose run --rm exportar-onnx); aquí solo se
informa si esa exportación está lista."""
import argparse
import sys

from app.catalogo import RERANKER, cargar_catalogo, ruta_local
from app.config import cargar_config
from app.onnx_int8 import comprobar


def _tamano_mb(ruta) -> float:
    return sum(f.stat().st_size for f in ruta.rglob("*") if f.is_file()) / 1024 / 1024


def main(argumentos: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Descarga los modelos locales del CDSS")
    parser.add_argument("--verificar", action="store_true", help="Solo comprueba que los modelos estén en la caché")
    args = parser.parse_args(argumentos)
    config = cargar_config()
    catalogo = cargar_catalogo(config.revisiones)

    errores = 0
    for modelo in catalogo.values():
        if not args.verificar:
            from huggingface_hub import snapshot_download

            print(f"Descargando {modelo.repositorio} ({modelo.revision[:12]}, unos {modelo.tamano_aproximado_mb} MB)...",
                  flush=True)
            snapshot_download(modelo.repositorio, revision=modelo.revision, allow_patterns=list(modelo.archivos))
        try:
            ruta = ruta_local(modelo)
            print(f"  {modelo.clave}: listo, {_tamano_mb(ruta):,.0f} MB en {ruta}")
        except RuntimeError as e:
            errores += 1
            print(f"  {modelo.clave}: {e}", file=sys.stderr)
    try:
        comprobar(config.dir_onnx, catalogo[RERANKER], verificar_hash=False)
        print(f"  {RERANKER} ONNX int8: listo en {config.dir_onnx}")
    except RuntimeError as e:
        print(f"  {RERANKER} ONNX int8: {e}", file=sys.stderr)
        errores += args.verificar and config.reranker == "onnx-int8"
    return 1 if errores else 0


if __name__ == "__main__":
    sys.exit(main())
