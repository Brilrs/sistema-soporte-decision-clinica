"""Huella de la configuración vigente (parte E1a del Sprint 3), para el OE3.

Imprime el SHA-256 de los puntos de corte, el ajuste por altitud, las categorías de anemia, los
parámetros del sistema vigentes, la versión de indexación de cada guía vigente y VERSION_PROMPT, con
la huella de cada componente. Guardarla junto a la etiqueta de git en cada medición: dos mediciones
con la misma huella usaron la misma configuración. Solo lee (conexión clínica).

    docker compose exec backend python -m app.scripts.huella_configuracion
    docker compose exec backend python -m app.scripts.huella_configuracion --json
"""
import argparse
import json

from app.core.db import engines
from app.services.parametros import huella


def main() -> None:
    parser = argparse.ArgumentParser(description="Huella SHA-256 de la configuración vigente")
    parser.add_argument("--json", action="store_true", help="Salida en JSON")
    args = parser.parse_args()
    with engines()["clinica"].connect() as c:
        h = huella(c)
    if args.json:
        print(json.dumps(h, ensure_ascii=False, indent=2, default=str))
        return
    print(f"Huella de la configuración ({h['algoritmo']}): {h['huella']}")
    print(f"Calculada en: {h['calculada_en'].isoformat()}")
    print(f"VERSION_PROMPT: {h['version_prompt']}")
    for c in h["componentes"]:
        print(f"  {c['nombre']}: {c['huella']} ({c['elementos']} elementos)")
    for d in h["indexacion"]:
        print(f"  guía {d['codigo'] or d['id_documento']}: versión de indexación {d['version_indexacion']}")


if __name__ == "__main__":
    main()
