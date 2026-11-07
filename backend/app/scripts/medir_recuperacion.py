"""Mediciones de la recuperación (parte B del Sprint 2). Se ejecuta dentro del
contenedor backend, con los modelos reales, ChromaDB y la base indexada, y escribe
JSON por la salida estándar (el avance va a la salida de errores):

    docker compose exec -T backend python -m app.scripts.medir_recuperacion calidad > calidad.json
    docker compose exec -T backend python -m app.scripts.medir_recuperacion latencia \\
        --entorno normal --configuraciones 20x1024,12x512,8x256 --consultas 10 > latencia.json
    docker compose exec -T backend python -m app.scripts.medir_recuperacion dominio > dominio.json

calidad: para cada consulta del grupo elegido busca una vez los
candidatos y puntúa con el reranker los 20 mejores de la fusión con cada longitud
máxima. Las configuraciones con 12 u 8 candidatos usan los primeros de esa misma
lista, de modo que la calidad de cada combinación se calcula sin repetir llamadas.
latencia: recuperación completa por configuración (candidatos x longitud), con
calentamiento previo y el tiempo de cada paso.
dominio: puntajes del filtro de dominio para calibrar UMBRAL_DOMINIO.
Con --grupo validacion (calidad) y --conjunto validacion (dominio) se miden las
consultas de consultas_validacion.yaml, que no se usan para ajustar nada.
El informe en Markdown se arma con app.scripts.informe_recuperacion."""
import argparse
import json
import os
import sys
import time
from dataclasses import replace

from sqlalchemy import create_engine

from app.core.config import get_settings
from app.core.modelos import ClienteModelos, EmbedderHttp, RerankerHttp
from app.core.vectores import AlmacenChroma
from app.rag.bm25 import CacheBM25
from app.rag.dominio import FiltroDominio
from app.rag.normalizacion import normalizar
from app.rag.parametros import parametros_recuperacion
from app.rag.recuperacion import Servicios, buscar_candidatos, seleccionar
from app.rag.referencias import (VALIDACION, cargar_consultas_latencia, cargar_consultas_referencia,
                                 cargar_validacion_dominio)

LONGITUDES = (1024, 512, 384, 256)


def _avance(mensaje: str) -> None:
    print(mensaje, file=sys.stderr, flush=True)


def _entorno(cliente: ClienteModelos, etiqueta: str) -> dict:
    salud = cliente.salud()
    try:
        cpus = len(os.sched_getaffinity(0))
    except AttributeError:
        cpus = os.cpu_count()
    return {"entorno": etiqueta, "fecha": time.strftime("%Y-%m-%d %H:%M:%S"), "cpus_backend": cpus,
            "hilos_modelos": salud.get("hilos"), "modelos": salud.get("modelos")}


def _servicios(cliente: ClienteModelos) -> Servicios:
    s = get_settings()
    return Servicios(EmbedderHttp(cliente), RerankerHttp(cliente), AlmacenChroma(s.chroma_url), CacheBM25())


def _fragmento(fila) -> dict:
    return {"id": fila.id_fragmento, "codigo_documento": fila.codigo_documento, "seccion": fila.seccion,
            "pagina_inicio": fila.pagina_inicio, "pagina_fin": fila.pagina_fin, "texto": fila.texto}


def cmd_calidad(args, motor, cliente) -> dict:
    servicios = _servicios(cliente)
    consultas = []
    if args.grupo in ("referencia", "todas"):
        consultas += [(r.id, r.consulta) for r in cargar_consultas_referencia()]
    if args.grupo == "validacion":
        consultas += [(r.id, r.consulta) for r in cargar_consultas_referencia(VALIDACION)]
    if args.grupo in ("latencia", "todas"):
        consultas += [(f"L{i:02d}", q) for i, q in enumerate(cargar_consultas_latencia(), start=1)]
    if args.grupo == "fuera":
        from app.rag.dominio import cargar_referencias, es_manipulacion
        fuera = [t for t in cargar_referencias().fuera if not es_manipulacion(t)]
        consultas += [(f"F{i:02d}", q) for i, q in enumerate(fuera, start=1)]
    with motor.connect() as c:
        p = replace(parametros_recuperacion(c), candidatos_busqueda=20, candidatos_reranker=20)
        resultados = []
        for k, (id_, texto) in enumerate(consultas, start=1):
            consulta = normalizar(texto)
            cand = buscar_candidatos(c, consulta, servicios, p)
            top = cand.fusionados[:20]
            textos = [cand.filas[i].texto for i, _, _ in top]
            puntajes, tiempos = {}, {}
            for longitud in args.longitudes:
                inicio = time.perf_counter()
                puntajes[str(longitud)] = servicios.reranker.puntuar(consulta.texto_normalizado, textos, longitud)
                tiempos[str(longitud)] = round((time.perf_counter() - inicio) * 1000, 1)
            resultados.append({
                "id": id_, "consulta": texto, "consulta_normalizada": consulta.texto_normalizado,
                "candidatos": [dict(_fragmento(cand.filas[i]), rrf=round(r, 6), posicion_rrf=pos,
                                    posicion_bm25=cand.posiciones_bm25.get(i),
                                    posicion_vectorial=cand.posiciones_vectoriales.get(i)) for i, r, pos in top],
                "puntajes": puntajes, "tiempos_reranker_ms": tiempos, "tiempos_busqueda_ms": cand.cronometro.tiempos,
            })
            _avance(f"[{k}/{len(consultas)}] {id_}: reranker {tiempos}")
    entorno = _entorno(cliente, args.entorno)
    formato = (entorno["modelos"] or {}).get("bge-reranker-v2-m3", {}).get("formato", "fp32")
    return {"tipo": "calidad", **entorno, "reranker": f"{formato} (servicio)", "grupo": args.grupo,
            "longitudes": args.longitudes, "consultas": resultados}


def _configuraciones(texto: str) -> list[tuple[int, int]]:
    return [tuple(int(x) for x in parte.split("x")) for parte in texto.split(",")]


def cmd_latencia(args, motor, cliente) -> dict:
    servicios = _servicios(cliente)
    consultas = cargar_consultas_latencia()[:args.consultas]
    calentamiento = cargar_consultas_latencia()[-args.calentamiento:] if args.calentamiento else []
    configuraciones = _configuraciones(args.configuraciones)
    salida = {"tipo": "latencia", **_entorno(cliente, args.entorno), "configuraciones": []}
    with motor.connect() as c:
        base = replace(parametros_recuperacion(c), umbral_relevancia=0.0)
        if args.frio:
            # Primera consulta con la primera configuración pedida
            frio = replace(base, candidatos_reranker=configuraciones[0][0], max_longitud_reranker=configuraciones[0][1])
            inicio = time.perf_counter()
            r = seleccionar(c, normalizar(consultas[0]), buscar_candidatos(c, normalizar(consultas[0]), servicios, frio),
                            servicios.reranker, frio)
            salida["primera_consulta_en_frio"] = {"total_ms": round((time.perf_counter() - inicio) * 1000, 1),
                                                  "pasos_ms": r.tiempos_ms,
                                                  "configuracion": [frio.candidatos_reranker, frio.max_longitud_reranker]}
            _avance(f"En frío: {salida['primera_consulta_en_frio']}")
        for q in calentamiento:
            cn = normalizar(q)
            seleccionar(c, cn, buscar_candidatos(c, cn, servicios, base), servicios.reranker,
                        replace(base, candidatos_reranker=4, max_longitud_reranker=256))
        for n, longitud in configuraciones:
            p = replace(base, candidatos_reranker=n, max_longitud_reranker=longitud)
            mediciones = []
            for k, q in enumerate(consultas, start=1):
                cn = normalizar(q)
                inicio = time.perf_counter()
                r = seleccionar(c, cn, buscar_candidatos(c, cn, servicios, p), servicios.reranker, p)
                total = round((time.perf_counter() - inicio) * 1000, 1)
                mediciones.append({"total_ms": total, "pasos_ms": r.tiempos_ms,
                                   "top5": [f.id_fragmento for f in r.fragmentos[:5]]})
                _avance(f"{n}x{longitud} [{k}/{len(consultas)}] total {total} ms, reranker {r.tiempos_ms.get('reranker')}")
            salida["configuraciones"].append({"candidatos": n, "longitud": longitud, "mediciones": mediciones})
    return salida


def cmd_dominio(args, motor, cliente) -> dict:
    from app.rag.dominio import es_manipulacion
    filtro = FiltroDominio(EmbedderHttp(cliente))
    refs = filtro.referencias
    if args.conjunto == "validacion":
        dentro, fuera = cargar_validacion_dominio()
        casos = [(t, "dentro", "validacion") for t in dentro] + [(t, "fuera", "validacion") for t in fuera]
        casos += [(r.consulta, "dentro", "validacion") for r in cargar_consultas_referencia(VALIDACION)]
    else:
        casos = [(t, "dentro", "referencia") for t in refs.dentro] + [(t, "fuera", "referencia") for t in refs.fuera]
        casos += [(r.consulta, "dentro", "consulta_referencia") for r in cargar_consultas_referencia()]
        casos += [(q, "dentro", "consulta_latencia") for q in cargar_consultas_latencia()]
    vectores = EmbedderHttp(cliente).embeber([t for t, _, _ in casos])
    filas = []
    for (texto, esperado, origen), vector in zip(casos, vectores):
        # Las referencias se evalúan dejándolas fuera de la comparación (validación cruzada).
        excluir = texto if origen == "referencia" else None
        r = filtro.evaluar(texto, 0.0, vector=vector, excluir_referencia=excluir)
        filas.append({"texto": texto, "esperado": esperado, "origen": origen, "manipulacion": es_manipulacion(texto),
                      "similitud_dentro": r.similitud_dentro, "similitud_fuera": r.similitud_fuera,
                      "terminos_dominio": list(r.terminos_dominio), "estado_con_umbral_0": r.estado})
    return {"tipo": "dominio", **_entorno(cliente, args.entorno), "casos": filas}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.scripts.medir_recuperacion")
    sub = parser.add_subparsers(dest="comando", required=True)
    p = sub.add_parser("calidad")
    p.add_argument("--longitudes", type=lambda t: [int(x) for x in t.split(",")], default=list(LONGITUDES))
    p.add_argument("--grupo", choices=["referencia", "latencia", "fuera", "todas", "validacion"], default="referencia",
                   help="consultas de referencia, de latencia, fuera del dominio (sin las de manipulación), "
                        "todas o las del conjunto de validación")
    p = sub.add_parser("latencia")
    p.add_argument("--configuraciones", default="20x1024,20x512,20x384,20x256,12x1024,12x512,12x384,12x256,"
                                                "8x1024,8x512,8x384,8x256")
    p.add_argument("--consultas", type=int, default=30)
    p.add_argument("--calentamiento", type=int, default=2)
    p.add_argument("--frio", action="store_true", help="mide primero una consulta sin calentamiento")
    p = sub.add_parser("dominio")
    p.add_argument("--conjunto", choices=["ajuste", "validacion"], default="ajuste",
                   help="consultas usadas para calibrar o el conjunto de validación")
    for nombre in ("calidad", "latencia", "dominio"):
        sub.choices[nombre].add_argument("--entorno", default="normal")
    args = parser.parse_args(argv)

    s = get_settings()
    motor = create_engine(s.database_url_generacion)
    cliente = ClienteModelos(s.modelos_url, timeout_s=1800)
    comandos = {"calidad": cmd_calidad, "latencia": cmd_latencia, "dominio": cmd_dominio}
    json.dump(comandos[args.comando](args, motor, cliente), sys.stdout, ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
