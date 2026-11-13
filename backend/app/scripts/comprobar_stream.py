"""Comprueba que la respuesta NDJSON de una consulta llega por etapas a través de Nginx
(parte D2): registra el momento en que el cliente recibe cada línea, medido desde el
envío de la solicitud. Si Nginx guardara la respuesta en un búfer, todas las líneas
llegarían juntas al final.

Usa la API como la interfaz: inicia sesión con un usuario de seed_demo, busca al paciente
ficticio por su DNI (en el cuerpo, como M02) y envía la consulta. El backend usa el modelo
de lenguaje configurado, así que una consulta que llega a generar hace una llamada real a
la API (unos 0,02 USD); por eso exige --confirmo-llamada-real. Solo admite DNI de
pacientes ficticios de seed_demo.

Uso (dentro de la red de Docker, contra el servicio nginx):
    python -m app.scripts.comprobar_stream --confirmo-llamada-real [--url http://nginx]
        [--usuario med.salazar] [--dni 81345678] [--confirma-tamizaje-no-vigente]

Imprime una línea por evento (ms, tipo, etapa) y el veredicto, y guarda el detalle en
<salida>/d2_stream_nginx.json."""
import argparse
import json
import os
import sys
import time
from pathlib import Path

import httpx

from app.scripts.seed_demo import PACIENTES

DNIS_SEED = frozenset(p[1] for p in PACIENTES)
CONSULTA = "¿Qué suplementación preventiva con hierro le corresponde y cuándo se vuelve a medir la hemoglobina?"
SEPARACION_MINIMA_MS = 1000


def veredicto(llegadas: list[dict]) -> dict:
    """Por etapas: al menos tres momentos de llegada distintos y el primero llega al menos un
    segundo antes que el último."""
    momentos = sorted({e["llegada_ms"] for e in llegadas})
    separacion = (momentos[-1] - momentos[0]) if momentos else 0
    return {"lineas": len(llegadas), "momentos_distintos": len(momentos), "primera_ms": momentos[0] if momentos else None,
            "ultima_ms": momentos[-1] if momentos else None, "separacion_ms": separacion,
            "por_etapas": len(momentos) >= 3 and separacion >= SEPARACION_MINIMA_MS}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--url", default="http://nginx")
    p.add_argument("--usuario", default="med.salazar")
    p.add_argument("--dni", default="81345678", help="DNI ficticio de seed_demo (por defecto, Valentina)")
    p.add_argument("--consulta", default=CONSULTA)
    p.add_argument("--confirma-tamizaje-no-vigente", action="store_true")
    p.add_argument("--confirmo-llamada-real", action="store_true",
                   help="obligatoria: la consulta puede llamar a la API real del modelo de lenguaje")
    p.add_argument("--salida", type=Path, default=Path(os.environ.get("CDSS_DIR_MEDICIONES", "data/mediciones")))
    a = p.parse_args(argv)
    if not a.confirmo_llamada_real:
        p.error("exige --confirmo-llamada-real")
    if a.dni not in DNIS_SEED:
        p.error("El DNI no corresponde a un paciente ficticio de seed_demo")
    contrasena = os.environ.get("SEED_CONTRASENA")
    if not contrasena:
        p.error("Falta SEED_CONTRASENA")

    with httpx.Client(base_url=a.url, timeout=httpx.Timeout(10.0, read=150.0)) as http:
        r = http.post("/api/auth/login", json={"usuario": a.usuario, "contrasena": contrasena})
        r.raise_for_status()
        cabeceras = {"Authorization": f"Bearer {r.json()['token']}"}
        r = http.post("/api/pacientes/buscar", json={"texto": a.dni}, headers=cabeceras)
        r.raise_for_status()
        (paciente,) = r.json()
        cuerpo = {"texto_consulta": a.consulta, "confirma_tamizaje_no_vigente": a.confirma_tamizaje_no_vigente}
        llegadas = []
        inicio = time.perf_counter()
        with http.stream("POST", f"/api/pacientes/{paciente['id_paciente']}/consultas", json=cuerpo,
                         headers=cabeceras) as respuesta:
            if respuesta.status_code != 200:
                print(f"HTTP {respuesta.status_code}: {respuesta.read().decode('utf-8')}")
                return 1
            tipo_contenido = respuesta.headers.get("content-type")
            for linea in respuesta.iter_lines():
                if not linea:
                    continue
                llegada = round((time.perf_counter() - inicio) * 1000)
                evento = json.loads(linea)
                llegadas.append({"llegada_ms": llegada, "tipo": evento["tipo"], "etapa": evento.get("etapa"),
                                 "transcurrido_servidor_ms": evento.get("transcurrido_ms"),
                                 "estado": evento.get("estado")})
                print(f"{llegada:>7} ms  {evento['tipo']:<8} {evento.get('etapa') or evento.get('estado') or ''}",
                      flush=True)
    resultado = {"url": a.url, "content_type": tipo_contenido, **veredicto(llegadas), "llegadas": llegadas}
    a.salida.mkdir(parents=True, exist_ok=True)
    (a.salida / "d2_stream_nginx.json").write_text(json.dumps(resultado, ensure_ascii=False, indent=2) + "\n",
                                                   encoding="utf-8")
    print(f"Content-Type {tipo_contenido}; {resultado['lineas']} líneas en {resultado['momentos_distintos']} momentos "
          f"distintos, del {resultado['primera_ms']} al {resultado['ultima_ms']} ms. Por etapas: "
          f"{'sí' if resultado['por_etapas'] else 'no'}")
    return 0 if resultado["por_etapas"] else 1


if __name__ == "__main__":
    sys.exit(main())
