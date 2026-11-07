"""Informe en Markdown de las mediciones de la recuperación, a partir de los JSON de
app.scripts.medir_recuperacion (y de los experimentos de reranker alternativos con el
mismo formato de calidad). Se ejecuta en el anfitrión:

    python -m app.scripts.informe_recuperacion --calidad data/mediciones/b_calidad.json \\
        --latencia data/mediciones/b_latencia_normal.json data/mediciones/b_latencia_b2ms.json \\
        --dominio data/mediciones/b_dominio.json > data/mediciones/b_informe.md

Calidad: % de las 20 consultas de referencia con la sección esperada en el top 5 y %
de coincidencia del top 5 con la configuración completa (20 candidatos, 1024 tokens)
en las 50 consultas. Latencia: p50 y p90 por paso (percentil con interpolación lineal)."""
import argparse
import json
from pathlib import Path
from types import SimpleNamespace

from app.rag.dominio import es_manipulacion, es_poblacion_fuera_del_alcance, terminos_del_dominio
from app.rag.referencias import VALIDACION, cargar_consultas_referencia

PASOS = ("embedding", "bm25", "chromadb", "rrf", "postgresql", "reranker", "recomprobacion")
COMPLETA = (20, 1024)


def _referencias() -> dict:
    """Consultas de referencia (R) y del conjunto de validación (V), por id."""
    return {r.id: r for r in cargar_consultas_referencia() + cargar_consultas_referencia(VALIDACION)}


def percentil(valores: list[float], q: float) -> float:
    datos = sorted(valores)
    if not datos:
        return float("nan")
    posicion = (len(datos) - 1) * q
    i = int(posicion)
    resto = posicion - i
    return datos[i] + (datos[i + 1] - datos[i]) * resto if i + 1 < len(datos) else datos[i]


def _s(ms: float) -> str:
    return f"{ms / 1000:.2f}".replace(".", ",")


def _t(ms: float) -> str:
    """Segundos con dos decimales desde 1 s; por debajo, milisegundos."""
    return f"{_s(ms)} s" if ms >= 1000 else f"{ms:.0f} ms"


def _pct(x: float) -> str:
    return "-" if x != x else f"{100 * x:.0f} %"


def top5(consulta: dict, n: int, longitud: int | None) -> list[dict]:
    candidatos = consulta["candidatos"][:n]
    if longitud is None:
        return candidatos[:5]
    puntajes = consulta["puntajes"][str(longitud)][:n]
    orden = sorted(range(len(candidatos)), key=lambda j: (-puntajes[j], j))
    return [dict(candidatos[j], puntaje=puntajes[j]) for j in orden[:5]]


def _fragmento(c: dict) -> SimpleNamespace:
    return SimpleNamespace(codigo_documento=c["codigo_documento"], seccion=c["seccion"], texto=c["texto"],
                           pagina_inicio=c["pagina_inicio"], pagina_fin=c["pagina_fin"])


def calidad(datos: dict, configuraciones: list[tuple[int, int | None]]) -> list[dict]:
    referencias = _referencias()
    filas = []
    for n, longitud in configuraciones:
        aciertos, coincidencias = [], []
        for q in datos["consultas"]:
            if longitud is not None and str(longitud) not in q["puntajes"]:
                continue
            elegido = top5(q, n, longitud)
            if q["id"] in referencias:
                aciertos.append(any(referencias[q["id"]].acierta(_fragmento(c)) for c in elegido))
            if str(COMPLETA[1]) in q["puntajes"]:
                base = {c["id"] for c in top5(q, *COMPLETA)}
                coincidencias.append(len(base & {c["id"] for c in elegido}) / max(len(base), 1))
        filas.append({"candidatos": n, "longitud": longitud, "acierto": sum(aciertos) / len(aciertos),
                      "aciertos": sum(aciertos), "total": len(aciertos),
                      "coincidencia": sum(coincidencias) / len(coincidencias) if coincidencias else float("nan")})
    return filas


def tabla_calidad(datos: dict, titulo: str) -> list[str]:
    longitudes = [int(x) for x in datos["longitudes"]]
    configuraciones = [(n, L) for n in (20, 12, 8) for L in longitudes] + [(20, None)]
    lineas = [f"### {titulo}", "", "| Candidatos | Longitud | Acierto top 5 (20 ref.) | Coincidencia top 5 con 20 x 1024 |",
              "| --- | --- | --- | --- |"]
    for f in calidad(datos, configuraciones):
        longitud = "solo RRF" if f["longitud"] is None else str(f["longitud"])
        lineas.append(f"| {f['candidatos'] if f['longitud'] else '-'} | {longitud} | {_pct(f['acierto'])} "
                      f"({f['aciertos']}/{f['total']}) | {_pct(f['coincidencia'])} |")
    return lineas + [""]


def detalle_referencias(datos: dict, n: int, longitud: int) -> list[str]:
    referencias = _referencias()
    lineas = [f"| Consulta | Acierta ({n} x {longitud}) | Puntaje máx. esperado | Puntaje máx. otro | Top 1 |",
              "| --- | --- | --- | --- | --- |"]
    for q in datos["consultas"]:
        if q["id"] not in referencias:
            continue
        ref = referencias[q["id"]]
        pares = list(zip(q["candidatos"][:n], q["puntajes"][str(longitud)][:n]))
        esperados = [p for c, p in pares if ref.acierta(_fragmento(c))]
        otros = [p for c, p in pares if not ref.acierta(_fragmento(c))]
        elegido = top5(q, n, longitud)
        acierta = any(ref.acierta(_fragmento(c)) for c in elegido)
        max_esperado = f"{max(esperados):.3f}" if esperados else "sin candidato esperado"
        max_otro = f"{max(otros):.3f}" if otros else "-"
        primero = f"{elegido[0]['codigo_documento']} {(elegido[0]['seccion'] or '')[:50]}"
        lineas.append(f"| {q['id']} | {'sí' if acierta else 'no'} | {max_esperado} | {max_otro} | {primero} |")
    return lineas + [""]


def calibracion_umbral(datos: dict, longitud: int, n: int, negativos: dict | None) -> list[str]:
    referencias = _referencias()
    esperados, otros, maximos = [], [], []
    for q in datos["consultas"]:
        puntajes = q["puntajes"][str(longitud)][:n]
        maximos.append(max(puntajes))
        if q["id"] in referencias:
            for c, p in zip(q["candidatos"][:n], puntajes):
                (esperados if referencias[q["id"]].acierta(_fragmento(c)) else otros).append(p)
    negs = [max(q["puntajes"][str(longitud)][:n]) for q in negativos["consultas"]] if negativos else []
    lineas = [f"Puntajes del reranker con {n} candidatos y {longitud} tokens:", "",
              "| Grupo | n | p10 | p25 | mediana | p75 | p90 |", "| --- | --- | --- | --- | --- | --- | --- |"]
    for nombre, valores in (("Fragmentos esperados (20 ref.)", esperados), ("Otros candidatos (20 ref.)", otros),
                            (f"Máximo por consulta ({len(maximos)} consultas del dominio)", maximos),
                            ("Máximo por consulta fuera del dominio", negs)):
        if valores:
            lineas.append(f"| {nombre} | {len(valores)} | " + " | ".join(
                f"{percentil(valores, q):.3f}" for q in (0.10, 0.25, 0.5, 0.75, 0.9)) + " |")
    lineas += ["", "| Umbral | Consultas del dominio que alcanzan el umbral | Esperados sobre el umbral | "
               "Otros sobre el umbral | Fuera del dominio que alcanzan el umbral |", "| --- | --- | --- | --- | --- |"]
    for u in (0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.40, 0.50, 0.60):
        fila = (f"| {u:.2f} | {_pct(sum(m >= u for m in maximos) / len(maximos))} | "
                f"{_pct(sum(p >= u for p in esperados) / max(len(esperados), 1))} | "
                f"{_pct(sum(p >= u for p in otros) / max(len(otros), 1))} | ")
        fila += (_pct(sum(m >= u for m in negs) / len(negs)) if negs else "sin datos") + " |"
        lineas.append(fila)
    return lineas + [""]


def _top5_ids(q: dict, n: int, longitud: int) -> set[str]:
    return {c["id"] for c in top5(q, n, longitud)}


def tabla_alternativas(base: dict, alternativas: list[dict], longitud: int) -> list[str]:
    """Rerankers alternativos frente a bge-reranker-v2-m3 fp32 con los mismos candidatos.
    base: consultas fp32 por id (referencia R, latencia L y fuera del dominio F)."""
    referencias = _referencias()
    lineas = ["| Reranker | Acierto top 5 (20 x L) | Acierto top 5 (8 x L) | Coincidencia top 5 con fp32, 30 consultas "
              "(20 x L / 8 x L) | Reranker p50 / p90 (20 / 12 / 8 candidatos) | Máx. dentro p10 | Máx. fuera p90 |",
              "| --- | --- | --- | --- | --- | --- | --- |"]
    for alt in [{"reranker": f"fp32 ({longitud} tokens, servicio)", "consultas": list(base.values())}] + alternativas:
        qs = {q["id"]: q for q in alt["consultas"] if str(longitud) in q["puntajes"]}
        def acierto(n):
            ok = [any(referencias[i].acierta(_fragmento(c)) for c in top5(q, n, longitud))
                  for i, q in qs.items() if i in referencias]
            return f"{_pct(sum(ok) / len(ok))} ({sum(ok)}/{len(ok)})" if ok else "-"
        def coincidencia(n):
            vals = [len(_top5_ids(q, n, longitud) & _top5_ids(base[i], n, longitud)) / 5
                    for i, q in qs.items() if i.startswith("L") and i in base]
            return _pct(sum(vals) / len(vals)) if vals else "-"
        lat = alt.get("latencias_ms", {})
        tiempos = " / ".join(f"{_t(percentil(lat[k], 0.5))} - {_t(percentil(lat[k], 0.9))}"
                             for k in (f"20x{longitud}", f"12x{longitud}", f"8x{longitud}") if lat.get(k)) or "ver latencia"
        dentro = [max(q["puntajes"][str(longitud)]) for i, q in qs.items() if not i.startswith("F")]
        fuera = [max(q["puntajes"][str(longitud)]) for i, q in qs.items() if i.startswith("F")]
        lineas.append(f"| {alt['reranker']} | {acierto(20)} | {acierto(8)} | {coincidencia(20)} / {coincidencia(8)} | "
                      f"{tiempos} | {percentil(dentro, 0.1):.3f} | "
                      + (f"{percentil(fuera, 0.9):.3f}" if fuera else "-") + " |")
    return lineas + [""]


def tabla_latencia(datos: dict) -> list[str]:
    lineas = [f"### Latencia, entorno {datos['entorno']} (hilos de PyTorch: {datos.get('hilos_modelos')}, "
              f"CPU visibles en backend: {datos.get('cpus_backend')})", ""]
    if "primera_consulta_en_frio" in datos:
        frio = datos["primera_consulta_en_frio"]
        lineas += [f"Primera consulta en frío ({frio['configuracion'][0]} x {frio['configuracion'][1]}): "
                   f"{_t(frio['total_ms'])} en total; " + ", ".join(
                       f"{k} {_t(v)}" for k, v in frio["pasos_ms"].items()), ""]
    encabezado = "| Configuración | n | " + " | ".join(f"{p} p50 / p90" for p in PASOS) + " | Total p50 / p90 |"
    lineas += [encabezado, "| " + " | ".join(["---"] * (len(PASOS) + 3)) + " |"]
    for conf in datos["configuraciones"]:
        med = conf["mediciones"]
        celdas = []
        for paso in PASOS:
            valores = [m["pasos_ms"].get(paso, 0.0) for m in med]
            celdas.append(f"{_t(percentil(valores, 0.5))} / {_t(percentil(valores, 0.9))}")
        totales = [m["total_ms"] for m in med]
        lineas.append(f"| {conf['candidatos']} x {conf['longitud']} | {len(med)} | " + " | ".join(celdas)
                      + f" | {_t(percentil(totales, 0.5))} / {_t(percentil(totales, 0.9))} |")
    return lineas + [""]


def _acepta(c: dict, umbral: float) -> bool:
    if es_manipulacion(c["texto"]) or es_poblacion_fuera_del_alcance(c["texto"]):
        return False
    if terminos_del_dominio(c["texto"]):
        return True
    return c["similitud_dentro"] >= c["similitud_fuera"] and c["similitud_dentro"] >= umbral


def tabla_validacion_dominio(datos: dict, umbral: float) -> list[str]:
    """Filtro de dominio completo (reglas y similitud) sobre el conjunto de validación."""
    dentro = [c for c in datos["casos"] if c["esperado"] == "dentro"]
    fuera = [c for c in datos["casos"] if c["esperado"] == "fuera"]
    ok_dentro = sum(_acepta(c, umbral) for c in dentro)
    ok_fuera = sum(not _acepta(c, umbral) for c in fuera)
    lineas = [f"Con UMBRAL_DOMINIO = {umbral:.2f}: dentro aceptadas {ok_dentro}/{len(dentro)}, fuera rechazadas "
              f"{ok_fuera}/{len(fuera)}, exactitud {_pct((ok_dentro + ok_fuera) / len(datos['casos']))}.", "",
              "| Consulta | Esperado | Resultado | Decide | Similitud dentro / fuera |", "| --- | --- | --- | --- | --- |"]
    for c in datos["casos"]:
        acepta = _acepta(c, umbral)
        if es_manipulacion(c["texto"]):
            decide = "manipulación"
        elif es_poblacion_fuera_del_alcance(c["texto"]):
            decide = "población"
        elif terminos_del_dominio(c["texto"]):
            decide = "términos"
        else:
            decide = "similitud"
        error = "" if acepta == (c["esperado"] == "dentro") else " (error)"
        lineas.append(f"| {c['texto'][:80]} | {c['esperado']} | {'dentro' if acepta else 'fuera'}{error} | {decide} | "
                      f"{c['similitud_dentro']:.3f} / {c['similitud_fuera']:.3f} |")
    return lineas + [""]


def tabla_dominio(datos: dict) -> list[str]:
    casos = [c for c in datos["casos"] if not c["manipulacion"]]
    dentro = [c for c in casos if c["esperado"] == "dentro"]
    fuera = [c for c in casos if c["esperado"] == "fuera"]
    lineas = ["| Umbral | Dentro aceptadas | Fuera rechazadas | Exactitud |", "| --- | --- | --- | --- |"]
    for u in [x / 100 for x in range(30, 81, 5)]:
        def acepta(c):
            if es_poblacion_fuera_del_alcance(c["texto"]):
                return False
            if terminos_del_dominio(c["texto"]):
                return True
            return c["similitud_dentro"] >= c["similitud_fuera"] and c["similitud_dentro"] >= u
        ok_dentro = sum(acepta(c) for c in dentro)
        ok_fuera = sum(not acepta(c) for c in fuera)
        lineas.append(f"| {u:.2f} | {ok_dentro}/{len(dentro)} | {ok_fuera}/{len(fuera)} | "
                      f"{_pct((ok_dentro + ok_fuera) / len(casos))} |")
    lineas += ["", "Consultas que decide la similitud (sin términos del dominio ni población fuera del alcance):", "",
               "| Consulta | Esperado | Similitud dentro | Similitud fuera |", "| --- | --- | --- | --- |"]
    por_similitud = [c for c in casos if not terminos_del_dominio(c["texto"])
                     and not es_poblacion_fuera_del_alcance(c["texto"])]
    for c in sorted(por_similitud, key=lambda c: (c["esperado"], -c["similitud_dentro"])):
        lineas.append(f"| {c['texto'][:70]} | {c['esperado']} | {c['similitud_dentro']:.3f} | "
                      f"{c['similitud_fuera']:.3f} |")
    return lineas + [""]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--calidad", type=Path)
    parser.add_argument("--calidad-alternativas", type=Path, nargs="*", default=[])
    parser.add_argument("--base-fp32", type=Path, nargs="*", default=[],
                        help="archivos de calidad del servicio (referencia, latencia y fuera) para comparar")
    parser.add_argument("--longitud-alternativas", type=int, default=384)
    parser.add_argument("--negativos", type=Path)
    parser.add_argument("--latencia", type=Path, nargs="*", default=[])
    parser.add_argument("--dominio", type=Path)
    parser.add_argument("--umbral-longitud", type=int, default=1024)
    parser.add_argument("--umbral-candidatos", type=int, default=20)
    parser.add_argument("--validacion-calidad", type=Path, help="calidad del conjunto de validación")
    parser.add_argument("--validacion-dominio", type=Path, help="dominio del conjunto de validación")
    parser.add_argument("--umbral-dominio", type=float, default=0.65)
    args = parser.parse_args()
    leer = lambda ruta: json.loads(ruta.read_text(encoding="utf-8"))  # noqa: E731
    lineas = ["# Mediciones de la recuperación (parte B)", ""]
    if args.calidad:
        datos = leer(args.calidad)
        lineas += ["## Calidad frente a velocidad", ""] + tabla_calidad(datos, f"bge-reranker-v2-m3, {datos.get('reranker', 'fp32 (servicio)')}")
        if args.calidad_alternativas and args.base_fp32:
            base = {q["id"]: q for ruta in args.base_fp32 for q in leer(ruta)["consultas"]}
            lineas += [f"### Rerankers alternativos ({args.longitud_alternativas} tokens, mismos candidatos)", ""]
            lineas += tabla_alternativas(base, [leer(r) for r in args.calidad_alternativas],
                                         args.longitud_alternativas)
        lineas += ["## Detalle por consulta de referencia", ""]
        lineas += detalle_referencias(datos, args.umbral_candidatos, args.umbral_longitud)
        lineas += ["## Calibración de UMBRAL_RELEVANCIA", ""]
        lineas += calibracion_umbral(datos, args.umbral_longitud, args.umbral_candidatos,
                                     leer(args.negativos) if args.negativos else None)
    if args.latencia:
        lineas += ["## Latencia por paso", ""]
        for ruta in args.latencia:
            lineas += tabla_latencia(leer(ruta))
    if args.dominio:
        lineas += ["## Calibración de UMBRAL_DOMINIO", ""] + tabla_dominio(leer(args.dominio))
    if args.validacion_calidad:
        datos = leer(args.validacion_calidad)
        n, longitud = args.umbral_candidatos, args.umbral_longitud
        filas = calidad(datos, [(n, longitud), (20, None)])
        lineas += ["## Conjunto de validación: recuperación", "",
                   f"Acierto en el top 5 con {n} x {longitud}: {_pct(filas[0]['acierto'])} "
                   f"({filas[0]['aciertos']}/{filas[0]['total']}); solo RRF: {_pct(filas[1]['acierto'])} "
                   f"({filas[1]['aciertos']}/{filas[1]['total']}).", ""]
        lineas += detalle_referencias(datos, n, longitud)
        maximos = [max(q["puntajes"][str(longitud)][:n]) for q in datos["consultas"]]
        lineas += [f"Puntaje máximo por consulta: mínimo {min(maximos):.3f}, mediana {percentil(maximos, 0.5):.3f}.", ""]
    if args.validacion_dominio:
        lineas += ["## Conjunto de validación: filtro de dominio", ""]
        lineas += tabla_validacion_dominio(leer(args.validacion_dominio), args.umbral_dominio)
    print("\n".join(lineas))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
