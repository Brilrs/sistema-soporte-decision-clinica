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
calendario: parte G (pendiente P4). Conjuntos de aceptación del calendario de control de
hemoglobina (--conjunto a: consultas_calendario.yaml; b: consultas_calendario_b.yaml; con sus
huellas SHA-256) y las 20 consultas de referencia (referencias), con la recuperación real como
en el grafo. Por consulta: fila correcta entre los enviados, Tabla N° 20 en las de tratamiento
(estricto: la tabla; aceptado: la tabla o el fragmento que la cita), puntero «según Tabla N° 4»
sin la tabla, tablas de otra edad, agregados por puntero, relevancia máxima y puntajes de los
evaluados por pasada, estado antes del modelo (PASA_AL_MODELO o EVIDENCIA_INSUFICIENTE, control
6.3) y latencia del reranker (p50 y p90).
El informe en Markdown se arma con app.scripts.informe_recuperacion."""
import argparse
import json
import os
import re
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
from app.rag.recuperacion import (FILTRO_VECTORIAL, Servicios, buscar_candidatos, recuperar, recuperar_con_ampliacion,
                                  seleccionar, signo_edad)
from app.rag.referencias import (CALENDARIO, CALENDARIO_B, NTS213, PRUEBA, RM429, VALIDACION,
                                 cargar_conjunto_calendario,
                                 cargar_conjunto_prueba, cargar_consultas_latencia, cargar_consultas_referencia,
                                 cargar_validacion_dominio, huella_archivo)
from app.rag.verificacion import control_evidencia
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


_PUNTERO_TABLA_4 = re.compile(r"según\s+Tabla\s+N\s*[°º]\s*4\b", re.IGNORECASE)
_TITULO_TABLA_4 = "Medición de hemoglobina por grupo de edad durante la suplementación"


def puntero_sin_tabla(enviados: list) -> bool:
    """Se envía el puntero «según Tabla N° 4» de la NTS 213 sin la Tabla N° 4 de la RM 429. Es una
    comprobación independiente de la regla de app/rag/punteros.yaml, para medir su efecto."""
    con_puntero = any(f.codigo_documento == NTS213 and _PUNTERO_TABLA_4.search(f.texto) for f in enviados)
    con_tabla = any(f.codigo_documento == RM429 and _TITULO_TABLA_4 in f.texto for f in enviados)
    return con_puntero and not con_tabla


def _percentil(valores: list[float], q: float) -> float | None:
    if not valores:
        return None
    orden = sorted(valores)
    k = (len(orden) - 1) * q
    i = int(k)
    return round(orden[i] + (orden[min(i + 1, len(orden) - 1)] - orden[i]) * (k - i), 1)


PASA_AL_MODELO = "PASA_AL_MODELO"
EVIDENCIA_INSUFICIENTE = "EVIDENCIA_INSUFICIENTE"
CONJUNTOS_CALENDARIO = ("a", "b", "referencias")


def conjuntos_calendario(texto: str) -> list[str]:
    """--conjunto: nombres separados por comas (a, b, referencias), sin repetir."""
    nombres = [x.strip().lower() for x in texto.split(",") if x.strip()]
    if not nombres or any(n not in CONJUNTOS_CALENDARIO for n in nombres) or len(set(nombres)) != len(nombres):
        raise argparse.ArgumentTypeError(f"conjuntos válidos: {', '.join(CONJUNTOS_CALENDARIO)} (separados por comas)")
    return nombres


def estado_previo(ultima) -> str:
    """Estado antes de llamar al modelo, como lo decide el grafo con la última pasada: el
    control 6.3 sin respuesta (puntaje máximo del reranker frente al umbral)."""
    if control_evidencia(None, ultima.relevancia_maxima, ultima.umbral_relevancia):
        return EVIDENCIA_INSUFICIENTE
    return PASA_AL_MODELO


def tablas_otra_edad(enviados: list, edad: int | None, dudosos: set[str]) -> list[str]:
    """Tablas enviadas cuyo grupo etario excluye la edad (signo -1 de la bonificación por edad)."""
    return [f.id_fragmento for f in enviados if f.tipo_contenido == "TABLA"
            and signo_edad(edad, f.edad_min_meses, f.edad_max_meses, f.poblacion, f.id_fragmento in dudosos) == -1]


def _pasada(r) -> dict:
    evaluados = sorted((f for f in r.fragmentos if f.puntaje_reranker is not None),
                       key=lambda f: (f.posicion_final or 0, f.id_fragmento))
    return {"tipo_busqueda": r.tipo_busqueda, "relevancia_maxima": r.relevancia_maxima,
            "reranker_ms": r.tiempos_ms.get("reranker"),
            "puntajes": [{"id": f.id_fragmento, "documento": f.codigo_documento, "seccion": (f.seccion or "")[:90],
                          "puntaje_reranker": f.puntaje_reranker, "seleccionado": f.seleccionado}
                         for f in evaluados]}


def fila_calendario(conjunto: str, ref, edad: int | None, pasadas: list, dudosos: set[str]) -> dict:
    """Resultado de una consulta (la última pasada es la que cuenta, como en el grafo).
    acierta: fila correcta en el calendario, Tabla N° 20 (estricto) en el tratamiento o acierto
    de la consulta de referencia."""
    enviados = pasadas[-1].seleccionados
    tipo = getattr(ref, "tipo", "REFERENCIA")
    fila = {"conjunto": conjunto, "tipo": tipo, "forma": getattr(ref, "forma", "libre"), "edad_meses": edad,
            "acierta": any(ref.acierta(f) for f in enviados),
            "t20_estricto": None, "t20_aceptado": None,
            "puntero_sin_tabla": puntero_sin_tabla(enviados),
            "tablas_otra_edad": tablas_otra_edad(enviados, edad, dudosos),
            "agregados_puntero": [f.id_fragmento for f in enviados if getattr(f, "origen", "RERANKER") == "PUNTERO"],
            "estado_previo": estado_previo(pasadas[-1]), "pasadas": len(pasadas),
            "detalle_pasadas": [_pasada(r) for r in pasadas],
            "enviados": [{"id": f.id_fragmento, "documento": f.codigo_documento, "seccion": (f.seccion or "")[:90],
                          "puntaje_reranker": f.puntaje_reranker, "origen": getattr(f, "origen", "RERANKER")}
                         for f in enviados],
            "reranker_ms": [r.tiempos_ms.get("reranker") for r in pasadas]}
    if tipo == "TRATAMIENTO":
        fila["t20_estricto"] = any(ref.acierta_estricto(f) for f in enviados)
        fila["t20_aceptado"] = any(ref.acierta_aceptado(f) for f in enviados)
    return fila


def resumen_calendario(consultas: dict[str, dict]) -> dict:
    """Por conjunto: calendario (fila correcta), tratamiento (estricto y aceptado), referencias
    (acierto), punteros sin tabla, tablas de otra edad, agregados por puntero, EVIDENCIA_INSUFICIENTE
    antes del modelo y latencia del reranker (p50 y p90 de todas las pasadas)."""
    resumen: dict = {}
    for conjunto in dict.fromkeys(v["conjunto"] for v in consultas.values()):
        filas = {k: v for k, v in consultas.items() if v["conjunto"] == conjunto}
        bloque: dict = {}
        for tipo in ("CALENDARIO", "TRATAMIENTO", "REFERENCIA"):
            del_tipo = {k: v for k, v in filas.items() if v["tipo"] == tipo}
            if not del_tipo:
                continue
            b = {"total": len(del_tipo), "aciertos": sum(v["acierta"] for v in del_tipo.values()),
                 "fallan": sorted(k for k, v in del_tipo.items() if not v["acierta"])}
            if tipo == "TRATAMIENTO":
                b["estricto"] = sum(v["t20_estricto"] for v in del_tipo.values())
                b["aceptado"] = sum(v["t20_aceptado"] for v in del_tipo.values())
                b["fallan_aceptado"] = sorted(k for k, v in del_tipo.items() if not v["t20_aceptado"])
            bloque[tipo] = b
        tiempos = [ms for v in filas.values() for ms in v["reranker_ms"] if ms is not None]
        bloque.update({
            "punteros_sin_tabla": sorted(k for k, v in filas.items() if v["puntero_sin_tabla"]),
            "tablas_otra_edad": sorted(k for k, v in filas.items() if v["tablas_otra_edad"]),
            "agregados_puntero": sorted(k for k, v in filas.items() if v["agregados_puntero"]),
            "evidencia_insuficiente": sorted(k for k, v in filas.items()
                                             if v["estado_previo"] == EVIDENCIA_INSUFICIENTE),
            "reranker_ms": {"p50": _percentil(tiempos, 0.5), "p90": _percentil(tiempos, 0.9), "n": len(tiempos)}})
        resumen[conjunto] = bloque
    tiempos = [ms for v in consultas.values() for ms in v["reranker_ms"] if ms is not None]
    resumen["reranker_ms"] = {"p50": _percentil(tiempos, 0.5), "p90": _percentil(tiempos, 0.9), "n": len(tiempos)}
    return resumen


def cmd_calendario(args, motor, cliente) -> dict:
    """Parte G: conjuntos de aceptación del calendario de control de hemoglobina (A y B) y las 20
    consultas de referencia, con la recuperación real (recuperar_con_ampliacion, como el grafo) y
    los parámetros vigentes. Cuenta los fragmentos enviados al modelo (seleccionados)."""
    servicios = _servicios(cliente)
    archivos = {"a": CALENDARIO, "b": CALENDARIO_B}
    salida = {"tipo": "calendario", **_entorno(cliente, args.entorno), "conjuntos": args.conjunto,
              "huellas": {n: huella_archivo(archivos[n]) for n in args.conjunto if n in archivos}, "consultas": {}}
    casos = []
    for nombre in args.conjunto:
        if nombre == "referencias":
            casos += [("REFERENCIA", r.id, r.consulta, edad_mencionada_meses(r.consulta), r)
                      for r in cargar_consultas_referencia()]
        else:
            casos += [(nombre.upper(), q.id, q.consulta, q.edad_meses, q)
                      for q in cargar_conjunto_calendario(archivos[nombre])]
    with motor.connect() as c:
        p = parametros_recuperacion(c)
        dudosos = set(c.execute(text("SELECT id_fragmento::text FROM conocimiento.fragmento WHERE rango_dudoso"))
                      .scalars())
        for texto in cargar_consultas_latencia()[:args.calentamiento]:
            recuperar(c, normalizar(texto), servicios, p)
        for conjunto, id_, texto, edad, ref in casos:
            pasadas = recuperar_con_ampliacion(c, normalizar(texto), servicios, p, edad)
            fila = fila_calendario(conjunto, ref, edad, pasadas, dudosos)
            salida["consultas"][id_] = fila
            _avance(f"{id_}: acierta {fila['acierta']}, aceptado {fila['t20_aceptado']}, "
                    f"puntero sin tabla {fila['puntero_sin_tabla']}, {fila['estado_previo']}")
    salida["resumen"] = resumen_calendario(salida["consultas"])
    _avance(json.dumps(salida["resumen"], ensure_ascii=False))
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
    p = sub.add_parser("calendario", help="conjuntos de aceptación del calendario de Hb y las 20 de referencia (parte G)")
    p.add_argument("--calentamiento", type=int, default=2)
    p.add_argument("--conjunto", type=conjuntos_calendario, default=["a", "referencias"],
                   help="a, b y referencias, separados por comas (por defecto a,referencias). B es el conjunto "
                        "de aceptación: se mide una vez por variante aprobada, nunca para elegir variantes")
    p = sub.add_parser("dominio")
    p.add_argument("--conjunto", choices=["ajuste", "validacion"], default="ajuste",
                   help="consultas usadas para calibrar o el conjunto de validación")
    for nombre in ("calidad", "latencia", "dominio", "rankings", "edad", "calendario"):
        sub.choices[nombre].add_argument("--entorno", default="normal")
    args = parser.parse_args(argv)

    s = get_settings()
    motor = create_engine(s.database_url_generacion)
    cliente = ClienteModelos(s.modelos_url, timeout_s=1800)
    comandos = {"calidad": cmd_calidad, "latencia": cmd_latencia, "dominio": cmd_dominio, "rankings": cmd_rankings,
                "edad": cmd_edad, "calendario": cmd_calendario}
    json.dump(comandos[args.comando](args, motor, cliente), sys.stdout, ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
