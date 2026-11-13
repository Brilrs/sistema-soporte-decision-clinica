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
rankings: ranking completo de BM25 y de la búsqueda vectorial, fragmentos esperados y
puntajes del reranker (256 tokens) de todo lo que alguna variante de
app.scripts.variantes_recuperacion lleva al reranker. --grupo desarrollo mide las
consultas de ajuste y de validación; --grupo prueba, el conjunto de prueba final.
Con --fragmentos (JSON de indexador comparar --fragmentos-json) y --coleccion mide
otra fragmentación sin tocar la de producción: BM25 en memoria y los vectores en una
colección aparte de ChromaDB, que se llena la primera vez.
Con --grupo validacion (calidad) y --conjunto validacion (dominio) se miden las
consultas de consultas_validacion.yaml, que no se usan para ajustar nada.
edad: recuperación real (recuperar, con el reranker y el umbral vigentes) de las
consultas de ajuste (R) y de validación (V) para cada peso de --pesos de la
bonificación por edad, en memoria y sin tocar la base; la edad sale del texto de la
consulta. Da los aciertos en el top 5 y la posición del primer fragmento esperado.
El informe en Markdown se arma con app.scripts.informe_recuperacion."""
import argparse
import json
import os
import sys
import time
from dataclasses import replace

from sqlalchemy import create_engine, text

from app.core.config import get_settings
from app.core.modelos import ClienteModelos, EmbedderHttp, RerankerHttp
from app.core.vectores import AlmacenChroma
from app.rag.bm25 import CONDICION_RECUPERABLE, CacheBM25, terminos_consulta
from app.rag.dominio import FiltroDominio, edad_mencionada_meses
from app.rag.normalizacion import normalizar
from app.rag.parametros import parametros_recuperacion
from app.rag.recuperacion import FILTRO_VECTORIAL, Servicios, buscar_candidatos, recuperar, seleccionar, signo_edad
from app.rag.referencias import (PRUEBA, VALIDACION, cargar_conjunto_prueba, cargar_consultas_latencia,
                                 cargar_consultas_referencia, cargar_validacion_dominio)
from app.scripts.variantes_recuperacion import ACTUAL, evaluados, rejilla, rejilla_edad

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


_RECUPERABLES = f"""
    SELECT f.id_fragmento::text AS id_fragmento, d.codigo_documento, d.idioma, f.seccion, f.pagina_inicio,
           f.pagina_fin, f.texto, f.edad_min_meses, f.edad_max_meses, f.poblacion, f.rango_dudoso
      FROM conocimiento.fragmento f JOIN conocimiento.documento_fuente d ON d.id_documento = f.id_documento
     WHERE {CONDICION_RECUPERABLE}
"""
LONGITUD_RANKINGS = 256
LOTE_RERANKER = 32


def _fragmentos_experimento(ruta: str, servicios: Servicios, coleccion: str):
    """Fragmentos vigentes de un JSON exportado, su índice BM25 en memoria y la
    colección de ChromaDB del experimento (se llena si está vacía)."""
    import uuid
    from types import SimpleNamespace

    from app.core.vectores import AlmacenChroma, RegistroVector
    from app.rag.bm25 import Huella, IndiceBM25
    datos = json.loads(open(ruta, encoding="utf-8").read())
    filas = [SimpleNamespace(id_fragmento=str(uuid.uuid5(uuid.NAMESPACE_URL, f"{coleccion}:{f['id_documento']}:{f['orden']}")),
                             **{k: f[k] for k in ("id_documento", "codigo_documento", "idioma", "seccion",
                                                  "pagina_inicio", "pagina_fin", "texto")})
             for f in datos["fragmentos"] if f["vigente"]]
    almacen = AlmacenChroma(get_settings().chroma_url, coleccion)
    if len(almacen._coleccion.get(include=[])["ids"]) != len(filas):
        for i in range(0, len(filas), 16):
            lote = filas[i:i + 16]
            vectores = servicios.embedder.embeber([f.texto for f in lote])
            almacen.agregar([RegistroVector(f.id_fragmento, v, f.texto, {
                "id_documento": f.id_documento, "nivel": 1, "estado_documento": "VIGENTE", "vigente": True})
                for f, v in zip(lote, vectores)])
            _avance(f"Colección {coleccion}: {i + len(lote)} de {len(filas)} vectores")
    return {f.id_fragmento: f for f in filas}, IndiceBM25(filas, Huella(len(filas), coleccion)), almacen, datos


def cmd_rankings(args, motor, cliente) -> dict:
    servicios = _servicios(cliente)
    if args.grupo == "prueba":
        import yaml
        tipos = {c["id"]: tipo for tipo, clave in (("caso", "casos"), ("libre", "libres"))
                 for c in yaml.safe_load(PRUEBA.read_text(encoding="utf-8"))[clave]}
        referencias = cargar_conjunto_prueba()
    else:
        tipos = {}
        referencias = cargar_consultas_referencia() + cargar_consultas_referencia(VALIDACION)
    variantes = rejilla() + rejilla_edad()
    salida = {"tipo": "rankings", **_entorno(cliente, args.entorno), "grupo": args.grupo,
              "longitud": LONGITUD_RANKINGS, "consultas": []}
    with motor.connect() as c:
        if args.fragmentos:
            fragmentos, indice, almacen, datos = _fragmentos_experimento(args.fragmentos, servicios, args.coleccion)
            servicios = replace(servicios, almacen=almacen)
            salida["fragmentacion"] = {"archivo": args.fragmentos, "coleccion": args.coleccion,
                                       "parametros": datos.get("parametros")}
        else:
            fragmentos = {f.id_fragmento: f for f in c.execute(text(_RECUPERABLES)).all()}
            indice = servicios.cache_bm25.obtener(c)
        for k, ref in enumerate(referencias, start=1):
            cn = normalizar(ref.consulta)
            vector = servicios.embedder.embeber([cn.texto_normalizado])[0]
            terminos = terminos_consulta(cn.texto_normalizado, cn.equivalentes_ingles)
            q = {"id": ref.id, "tipo": tipos.get(ref.id), "consulta": ref.consulta,
                 "consulta_normalizada": cn.texto_normalizado, "terminos": terminos,
                 "conceptos": [t.clave for t in cn.terminos],
                 "bm25": [i for i, _ in indice.buscar(terminos, len(fragmentos))],
                 "bm25_expandida": [i for i, _ in indice.buscar(
                     terminos_consulta(" ".join([cn.texto_normalizado, *cn.expansion]), cn.equivalentes_ingles),
                     len(fragmentos))],
                 "vectorial": [i for i, _ in servicios.almacen.consultar(vector, len(fragmentos), FILTRO_VECTORIAL)],
                 "esperados": [i for i, f in fragmentos.items() if ref.acierta(f)],
                 "esperados_originales": [i for i, f in fragmentos.items() if ref.acierta(f, original=True)],
                 "edad_meses": edad_mencionada_meses(ref.consulta)}
            # Signo de la bonificación por edad de cada fragmento (+1 incluye, -1 excluye).
            q["signos"] = {i: s for i, f in fragmentos.items()
                           if (s := signo_edad(q["edad_meses"], getattr(f, "edad_min_meses", None),
                                               getattr(f, "edad_max_meses", None), getattr(f, "poblacion", None),
                                               getattr(f, "rango_dudoso", False)))}
            a_puntuar = set(q["esperados"])
            for v in [ACTUAL, *variantes]:
                a_puntuar.update(evaluados(q, v))
            ids = sorted(a_puntuar)
            inicio = time.perf_counter()
            puntajes = []
            for i in range(0, len(ids), LOTE_RERANKER):
                puntajes += servicios.reranker.puntuar(cn.texto_normalizado,
                                                       [fragmentos[j].texto for j in ids[i:i + LOTE_RERANKER]],
                                                       LONGITUD_RANKINGS)
            q["puntajes"] = dict(zip(ids, puntajes))
            # Tiempo del reranker con los candidatos de la configuración vigente (8 x 256).
            actuales = evaluados(q, ACTUAL)
            inicio = time.perf_counter()
            servicios.reranker.puntuar(cn.texto_normalizado, [fragmentos[j].texto for j in actuales], LONGITUD_RANKINGS)
            q["reranker_actual_ms"] = round((time.perf_counter() - inicio) * 1000, 1)
            salida["consultas"].append(q)
            _avance(f"[{k}/{len(referencias)}] {ref.id}: {len(ids)} pares en "
                    f"{time.perf_counter() - inicio:.1f} s")
    salida["fragmentos"] = {i: {"codigo_documento": f.codigo_documento, "idioma": f.idioma, "seccion": f.seccion,
                                "pagina_inicio": f.pagina_inicio, "texto": f.texto} for i, f in fragmentos.items()}
    return salida


def _configuraciones(texto: str) -> list[tuple[int, int]]:
    return [tuple(int(x) for x in parte.split("x")) for parte in texto.split(",")]


def cmd_latencia(args, motor, cliente) -> dict:
    servicios = _servicios(cliente)
    consultas = cargar_consultas_latencia()[:args.consultas]
    calentamiento = cargar_consultas_latencia()[-args.calentamiento:] if args.calentamiento else []
    configuraciones = _configuraciones(args.configuraciones)
    salida = {"tipo": "latencia", **_entorno(cliente, args.entorno), "candidatos_busqueda": args.candidatos_busqueda,
              "rrf_k": args.rrf_k, "bonificacion_edad": args.bonificacion_edad, "configuraciones": []}
    with motor.connect() as c:
        base = replace(parametros_recuperacion(c), umbral_relevancia=0.0)
        if args.candidatos_busqueda:
            base = replace(base, candidatos_busqueda=args.candidatos_busqueda)
        if args.rrf_k:
            base = replace(base, rrf_k=args.rrf_k)
        if args.bonificacion_edad is not None:
            base = replace(base, bonificacion_edad=args.bonificacion_edad)
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
                r = seleccionar(c, cn, buscar_candidatos(c, cn, servicios, p, edad_meses=edad_mencionada_meses(q)),
                                servicios.reranker, p)
                total = round((time.perf_counter() - inicio) * 1000, 1)
                mediciones.append({"total_ms": total, "pasos_ms": r.tiempos_ms,
                                   "top5": [f.id_fragmento for f in r.fragmentos[:5]]})
                _avance(f"{n}x{longitud} [{k}/{len(consultas)}] total {total} ms, reranker {r.tiempos_ms.get('reranker')}")
            salida["configuraciones"].append({"candidatos": n, "longitud": longitud, "mediciones": mediciones})
    return salida


def resumen_edad(consultas: dict[str, dict]) -> dict:
    """Aciertos en el top 5 por conjunto (R ajuste, V validación) y las consultas que fallan."""
    resumen = {}
    for conjunto in ("R", "V"):
        filas = {k: v for k, v in consultas.items() if k.startswith(conjunto)}
        resumen[conjunto] = {"aciertos": sum(v["acierta"] for v in filas.values()), "total": len(filas),
                             "fallan": sorted(k for k, v in filas.items() if not v["acierta"])}
    return resumen


def cmd_edad(args, motor, cliente) -> dict:
    servicios = _servicios(cliente)
    referencias = cargar_consultas_referencia() + cargar_consultas_referencia(VALIDACION)
    salida = {"tipo": "edad", **_entorno(cliente, args.entorno), "pesos": {}}
    with motor.connect() as c:
        base = parametros_recuperacion(c)
        salida["bonificacion_vigente"] = base.bonificacion_edad
        for peso in args.pesos:
            p = replace(base, bonificacion_edad=peso)
            consultas = {}
            for ref in referencias:
                edad = edad_mencionada_meses(ref.consulta)
                r = recuperar(c, normalizar(ref.consulta), servicios, p, edad_meses=edad)
                posiciones = [k for k, f in enumerate(r.fragmentos, start=1) if ref.acierta(f)]
                consultas[ref.id] = {"edad_meses": edad, "acierta": bool(posiciones and posiciones[0] <= 5),
                                     "posicion": posiciones[0] if posiciones else None,
                                     "top5": [f.id_fragmento for f in r.fragmentos[:5]]}
                _avance(f"peso {peso:g} {ref.id}: {consultas[ref.id]['posicion']}")
            salida["pesos"][f"{peso:g}"] = {"resumen": resumen_edad(consultas), "consultas": consultas}
            _avance(f"peso {peso:g}: {salida['pesos'][f'{peso:g}']['resumen']}")
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
    p.add_argument("--candidatos-busqueda", type=int, help="candidatos por método (por defecto, el vigente)")
    p.add_argument("--rrf-k", type=int, help="k de RRF (por defecto, el vigente)")
    p.add_argument("--bonificacion-edad", type=float,
                   help="peso de la edad en la fusión, en memoria (por defecto, el vigente); la edad sale del texto")
    p = sub.add_parser("rankings")
    p.add_argument("--grupo", choices=["desarrollo", "prueba"], default="desarrollo",
                   help="consultas de ajuste y de validación, o el conjunto de prueba final")
    p.add_argument("--fragmentos", help="JSON de fragmentos de un experimento (indexador comparar --fragmentos-json)")
    p.add_argument("--coleccion", default="experimento_fragmentos", help="colección de ChromaDB del experimento")
    p = sub.add_parser("edad")
    p.add_argument("--pesos", type=lambda t: [float(x) for x in t.split(",")], default=[0.0, 0.1, 0.3, 0.5, 0.7],
                   help="pesos de la bonificación por edad, separados por comas (de 0 a 1)")
    p = sub.add_parser("dominio")
    p.add_argument("--conjunto", choices=["ajuste", "validacion"], default="ajuste",
                   help="consultas usadas para calibrar o el conjunto de validación")
    for nombre in ("calidad", "latencia", "dominio", "rankings", "edad"):
        sub.choices[nombre].add_argument("--entorno", default="normal")
    args = parser.parse_args(argv)

    s = get_settings()
    motor = create_engine(s.database_url_generacion)
    cliente = ClienteModelos(s.modelos_url, timeout_s=1800)
    comandos = {"calidad": cmd_calidad, "latencia": cmd_latencia, "dominio": cmd_dominio, "rankings": cmd_rankings,
                "edad": cmd_edad}
    json.dump(comandos[args.comando](args, motor, cliente), sys.stdout, ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
