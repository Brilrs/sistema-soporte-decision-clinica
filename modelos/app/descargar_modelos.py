"""Descarga bge-m3 y bge-reranker-v2-m3 en la revisión fijada de revisiones.json.

Se ejecuta una sola vez:  docker compose run --rm descargar-modelos
Los archivos quedan en HF_HOME (./data/modelos/hf en el equipo), fuera de los
volúmenes de Docker, así que docker compose down -v no los borra. Si ya están
descargados, no se vuelven a bajar."""
import argparse
import sys

from app.catalogo import cargar_catalogo, ruta_local
from app.config import cargar_config


def _tamano_mb(ruta) -> float:
    return sum(f.stat().st_size for f in ruta.rglob("*") if f.is_file()) / 1024 / 1024


def main(argumentos: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Descarga los modelos locales del CDSS")
    parser.add_argument("--verificar", action="store_true", help="Solo comprueba que los modelos estén en la caché")
    args = parser.parse_args(argumentos)
    catalogo = cargar_catalogo(cargar_config().revisiones)

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
    return 1 if errores else 0


if __name__ == "__main__":
    sys.exit(main())
