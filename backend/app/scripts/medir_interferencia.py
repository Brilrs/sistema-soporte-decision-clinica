"""Interferencia de la indexación con las consultas (Sprint 3, parte J, pendiente P14).

Mide la recuperación de las consultas de latencia (las 30 de app/rag/consultas_latencia.yaml, con el
mismo método que medir_recuperacion latencia y los parámetros vigentes) sin carga y mientras una
carga sintética imita al indexador: un hilo envía a modelos, uno tras otro, lotes de N textos reales
de fragmentos (POST /embeddings), como EmbedderHttp durante una indexación.

Solo lectura y sin efectos secundarios: lee conocimiento y configuracion con SELECT (usuario
cdss_indexador, transacciones de solo lectura), abre la colección de ChromaDB sin crearla ni escribir,
y no indexa, no carga ni retira nada. Se ejecuta con la imagen de jobs:

    docker compose run --rm jobs python -m app.scripts.medir_interferencia --lote 8 --consultas 15

Escribe un JSON en INDEXADOR_DIR_MEDICIONES (data/mediciones) y una tabla en pantalla."""
import argparse
import json
import os
import statistics
import sys
import threading
import time
from dataclasses import replace
from pathlib import Path

from sqlalchemy import create_engine, text

from app.core.modelos import ClienteModelos, EmbedderHttp, RerankerHttp
from app.core.vectores import COLECCION, ServidorChroma
from app.indexador.config import DIR_REPOSITORIO, leer_lote_embeddings
from app.rag.bm25 import CacheBM25
from app.rag.dominio import edad_mencionada_meses
from app.rag.normalizacion import normalizar
from app.rag.parametros import parametros_recuperacion
from app.rag.recuperacion import Servicios, buscar_candidatos, seleccionar
from app.rag.referencias import cargar_consultas_latencia

FRAGMENTOS_CARGA = 100


def _avance(mensaje: str) -> None:
    print(mensaje, file=sys.stderr, flush=True)


def percentil(valores: list[float], q: float) -> float | None:
    """Percentil con interpolación lineal (q entre 0 y 1)."""
    if not valores:
        return None
    ordenados = sorted(valores)
    posicion = (len(ordenados) - 1) * q
    abajo = int(posicion)
    arriba = min(abajo + 1, len(ordenados) - 1)
    return ordenados[abajo] + (ordenados[arriba] - ordenados[abajo]) * (posicion - abajo)


def resumen(mediciones: list[dict]) -> dict:
    totales = [m["total_ms"] for m in mediciones]
    return {
        "consultas": len(mediciones),
        "mediana_s": round(statistics.median(totales) / 1000, 2) if totales else None,
        "p90_s": round(percentil(totales, 0.9) / 1000, 2) if totales else None,
        "maximo_s": round(max(totales) / 1000, 2) if totales else None,
        "embedding_max_s": round(max((m["embedding_ms"] for m in mediciones), default=0) / 1000, 2),
        "reranker_max_s": round(max((m["reranker_ms"] for m in mediciones), default=0) / 1000, 2),
    }


def textos_de_fragmentos(motor) -> list[str]:
    """Textos de los fragmentos de la última versión de cada documento, en un orden fijo (solo lectura)."""
    with motor.connect() as c:
        c.execute(text("SET TRANSACTION READ ONLY"))
        return list(c.execute(text(
            """SELECT f.texto FROM conocimiento.fragmento f
                 JOIN (SELECT id_documento, max(version_indexacion) AS v
                         FROM conocimiento.fragmento GROUP BY id_documento) u
                   ON u.id_documento = f.id_documento AND u.v = f.version_indexacion
                ORDER BY f.id_documento, f.numero_orden""")).scalars())


class Carga(threading.Thread):
    """Envía lotes de embeddings uno tras otro hasta que se le pide parar, como el indexador."""

    def __init__(self, embedder: EmbedderHttp, textos: list[str], lote: int):
        super().__init__(daemon=True)
        self.embedder, self.textos, self.lote = embedder, textos, lote
        self.parar = threading.Event()
        self.lotes_ms: list[float] = []
        self.fragmentos = 0
        self.error: str | None = None

    def run(self) -> None:
        i = 0
        try:
            while not self.parar.is_set():
                parte = [self.textos[(i + k) % len(self.textos)] for k in range(self.lote)]
                inicio = time.perf_counter()
                self.embedder.embeber(parte)
                self.lotes_ms.append(round((time.perf_counter() - inicio) * 1000, 1))
                self.fragmentos += len(parte)
                i += self.lote
        except Exception as e:  # noqa: BLE001 (se informa en el JSON)
            self.error = f"{type(e).__name__}: {e}"


def medir_consultas(motor, servicios: Servicios, consultas: list[str], fin: float | None = None) -> list[dict]:
    """Recuperación completa de cada consulta con los parámetros vigentes (como medir_recuperacion latencia)."""
    mediciones = []
    with motor.connect() as c:
        c.execute(text("SET TRANSACTION READ ONLY"))
        p = replace(parametros_recuperacion(c), umbral_relevancia=0.0)
        for k, q in enumerate(consultas, start=1):
            if fin is not None and time.perf_counter() > fin:
                _avance(f"  se alcanzó --duracion tras {k - 1} consultas")
                break
            cn = normalizar(q)
            inicio = time.perf_counter()
            cand = buscar_candidatos(c, cn, servicios, p, edad_meses=edad_mencionada_meses(q))
            r = seleccionar(c, cn, cand, servicios.reranker, p)
            total = round((time.perf_counter() - inicio) * 1000, 1)
            mediciones.append({"total_ms": total, "embedding_ms": r.tiempos_ms.get("embedding", 0.0),
                               "reranker_ms": r.tiempos_ms.get("reranker", 0.0), "pasos_ms": r.tiempos_ms})
            _avance(f"  [{k}/{len(consultas)}] {total / 1000:.1f} s (embedding {r.tiempos_ms.get('embedding')} ms, "
                    f"reranker {r.tiempos_ms.get('reranker')} ms)")
    return mediciones


def medir(motor, servicios: Servicios, embedder_carga: EmbedderHttp, textos: list[str], args) -> dict:
    consultas = cargar_consultas_latencia()
    salida: dict = {"tipo": "interferencia", "lote": args.lote, "consultas_pedidas": args.consultas,
                    "fecha": time.strftime("%Y-%m-%d %H:%M:%S"), "etiqueta": args.etiqueta,
                    "candidatos_reranker": None, "fragmentos_disponibles": len(textos)}
    with motor.connect() as c:
        p = parametros_recuperacion(c)
        salida["candidatos_reranker"] = p.candidatos_reranker
        salida["max_longitud_reranker"] = p.max_longitud_reranker
    _avance("Calentamiento (2 consultas)")
    medir_consultas(motor, servicios, consultas[-2:])

    if not args.sin_base:
        _avance(f"Sin carga ({args.consultas} consultas)")
        salida["sin_carga"] = medir_consultas(motor, servicios, consultas[:args.consultas])

    n = args.fragmentos_carga
    _avance(f"Carga equivalente a {n} fragmentos, sola, con lote {args.lote}")
    inicio = time.perf_counter()
    for i in range(0, n, args.lote):
        embedder_carga.embeber([textos[k % len(textos)] for k in range(i, min(i + args.lote, n))])
    salida["fragmentos_carga"] = n
    salida["carga_100_fragmentos_s"] = round(time.perf_counter() - inicio, 1)
    _avance(f"  {salida['carga_100_fragmentos_s']} s")

    _avance(f"Con carga, lote {args.lote} ({args.consultas} consultas, como mucho {args.duracion} s)")
    carga = Carga(embedder_carga, textos, args.lote)
    carga.start()
    time.sleep(1.0)  # la carga ya envió su primer lote
    inicio = time.perf_counter()
    salida["con_carga"] = medir_consultas(motor, servicios, consultas[:args.consultas], inicio + args.duracion)
    carga.parar.set()
    carga.join(timeout=600)
    salida["carga"] = {"lotes": len(carga.lotes_ms), "fragmentos": carga.fragmentos,
                       "lote_mediana_s": round(statistics.median(carga.lotes_ms) / 1000, 2) if carga.lotes_ms else None,
                       "lote_max_s": round(max(carga.lotes_ms) / 1000, 2) if carga.lotes_ms else None,
                       "error": carga.error}
    salida["resumen"] = {"sin_carga": resumen(salida.get("sin_carga", [])), "con_carga": resumen(salida["con_carga"])}
    return salida


def tabla(salida: dict) -> str:
    filas = ["| Fase | Consultas | Mediana | p90 | Máximo | Embedding más lento | Reranker más lento |",
             "| --- | --- | --- | --- | --- | --- | --- |"]
    for fase, nombre in (("sin_carga", "Sin carga"), ("con_carga", f"Con carga, lote {salida['lote']}")):
        r = salida["resumen"][fase]
        if r["consultas"]:
            filas.append(f"| {nombre} | {r['consultas']} | {r['mediana_s']} s | {r['p90_s']} s | {r['maximo_s']} s | "
                         f"{r['embedding_max_s']} s | {r['reranker_max_s']} s |")
    c = salida["carga"]
    filas.append("")
    filas.append(f"Carga equivalente a {salida['fragmentos_carga']} fragmentos con lote {salida['lote']}, sola: "
                 f"{salida['carga_100_fragmentos_s']} s. Durante la medición: {c['lotes']} lotes, mediana "
                 f"{c['lote_mediana_s']} s y máximo {c['lote_max_s']} s por lote.")
    return "\n".join(filas)


def lote_valido(texto: str) -> int:
    """La misma regla que INDEXADOR_LOTE_EMBEDDINGS (entero de 1 a 64)."""
    try:
        return leer_lote_embeddings(texto)
    except ValueError as e:
        raise argparse.ArgumentTypeError(str(e)) from None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.scripts.medir_interferencia", description=__doc__.splitlines()[0])
    parser.add_argument("--lote", type=lote_valido, default=8, help="textos por petición de la carga (1 a 64)")
    parser.add_argument("--consultas", type=int, default=15, help="consultas por fase (de 1 a 30)")
    parser.add_argument("--duracion", type=float, default=1200, help="segundos como máximo para la fase con carga")
    parser.add_argument("--fragmentos-carga", type=int, default=FRAGMENTOS_CARGA,
                        help="fragmentos de la carga sola que se cronometra (100)")
    parser.add_argument("--sin-base", action="store_true", help="no mide la fase sin carga")
    parser.add_argument("--etiqueta", default="normal", help="se agrega al nombre del archivo (perfil, repetición)")
    parser.add_argument("--salida", help="carpeta del JSON (por omisión INDEXADOR_DIR_MEDICIONES o data/mediciones)")
    args = parser.parse_args(argv)
    if not 1 <= args.consultas <= 30:
        parser.error("--consultas debe estar entre 1 y 30")

    url_bd = os.environ.get("DATABASE_URL_INDEXADOR")
    if not url_bd:
        parser.error("Falta DATABASE_URL_INDEXADOR (usuario cdss_indexador, solo lectura)")
    motor = create_engine(url_bd, pool_size=2)
    cliente = ClienteModelos(os.environ.get("MODELOS_URL", "http://localhost:8000"), timeout_s=1800)
    almacen = ServidorChroma(os.environ.get("CHROMA_URL", "http://localhost:8001")).abrir(COLECCION)
    if almacen is None:
        parser.error(f"La colección {COLECCION} no existe; no se crea")
    servicios = Servicios(EmbedderHttp(cliente), RerankerHttp(cliente), almacen, CacheBM25())
    # La carga usa su propio cliente HTTP, como el indexador (otro proceso).
    embedder_carga = EmbedderHttp(ClienteModelos(os.environ.get("MODELOS_URL", "http://localhost:8000"),
                                                 timeout_s=1800), lote=args.lote)
    textos = textos_de_fragmentos(motor)
    if not textos:
        parser.error("No hay fragmentos indexados para armar la carga")

    salida = medir(motor, servicios, embedder_carga, textos, args)
    carpeta = Path(args.salida or os.environ.get("INDEXADOR_DIR_MEDICIONES", DIR_REPOSITORIO / "data" / "mediciones"))
    carpeta.mkdir(parents=True, exist_ok=True)
    archivo = carpeta / f"j_interferencia_lote{args.lote}_{args.etiqueta}.json"
    archivo.write_text(json.dumps(salida, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(tabla(salida))
    print(f"\nJSON: {archivo.name} en {carpeta.name}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
