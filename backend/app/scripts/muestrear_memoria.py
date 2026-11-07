"""Muestrea docker stats mientras corren las mediciones y guarda el pico de memoria y
de CPU de cada contenedor. Se ejecuta en el equipo anfitrión (solo usa la biblioteca
estándar y el comando docker), en otra terminal:

    python backend/app/scripts/muestrear_memoria.py --salida data/mediciones/b_memoria_normal.json

Termina con Ctrl+C, al cumplirse --duracion (segundos) o cuando aparece el archivo
indicado en --detener-si-existe. El JSON se reescribe en cada muestra, así que un
corte abrupto no pierde lo medido."""
import argparse
import json
import re
import subprocess
import time
from pathlib import Path

_UNIDADES = {"B": 1 / 2**20, "KiB": 1 / 1024, "MiB": 1.0, "GiB": 1024.0, "kB": 1000 / 2**20, "MB": 10**6 / 2**20,
             "GB": 10**9 / 2**20}
_CANTIDAD = re.compile(r"([\d.]+)\s*([A-Za-z]+)")


def mib(texto: str) -> float:
    m = _CANTIDAD.match(texto.strip())
    if not m:
        return 0.0
    return float(m.group(1)) * _UNIDADES.get(m.group(2), 1.0)


def muestra() -> list[dict]:
    salida = subprocess.run(["docker", "stats", "--no-stream", "--format", "{{json .}}"],
                            capture_output=True, text=True, check=True).stdout
    filas = []
    for linea in salida.splitlines():
        if linea.strip():
            d = json.loads(linea)
            uso, _, limite = d["MemUsage"].partition("/")
            filas.append({"contenedor": d["Name"], "mem_mib": round(mib(uso), 1), "limite_mib": round(mib(limite), 1),
                          "cpu_pct": float(d["CPUPerc"].rstrip("%") or 0)})
    return filas


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--salida", required=True)
    parser.add_argument("--duracion", type=float, default=0, help="segundos; 0 = hasta Ctrl+C")
    parser.add_argument("--detener-si-existe", help="archivo que, al aparecer, detiene el muestreo")
    args = parser.parse_args()
    salida = Path(args.salida)
    salida.parent.mkdir(parents=True, exist_ok=True)
    picos: dict[str, dict] = {}
    inicio = time.time()
    muestras = 0
    try:
        while True:
            for f in muestra():
                p = picos.setdefault(f["contenedor"], {"mem_pico_mib": 0.0, "limite_mib": f["limite_mib"],
                                                      "cpu_pico_pct": 0.0, "hora_pico": ""})
                if f["mem_mib"] > p["mem_pico_mib"]:
                    p.update(mem_pico_mib=f["mem_mib"], hora_pico=time.strftime("%H:%M:%S"))
                p["cpu_pico_pct"] = max(p["cpu_pico_pct"], f["cpu_pct"])
            muestras += 1
            salida.write_text(json.dumps({"inicio": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(inicio)),
                                          "segundos": round(time.time() - inicio), "muestras": muestras,
                                          "picos": picos}, indent=1), encoding="utf-8")
            if args.duracion and time.time() - inicio >= args.duracion:
                break
            if args.detener_si_existe and Path(args.detener_si_existe).exists():
                break
    except KeyboardInterrupt:
        pass
    print(f"{muestras} muestras en {round(time.time() - inicio)} s: {salida}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
