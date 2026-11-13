"""Variantes de la primera etapa de la recuperación (Sprint 2 B2), evaluadas sin
volver a llamar a los modelos.

app.scripts.medir_recuperacion rankings guarda, para cada consulta, el ranking
completo de BM25 y de la búsqueda vectorial, los fragmentos que cumplen la sección
esperada y el puntaje del reranker (256 tokens) de todos los fragmentos que alguna
variante de la rejilla lleva al reranker, con y sin la expansión de BM25. Con eso, este módulo reproduce la fusión
y la selección de cada variante (candidatos por método, k y pesos de RRF, candidatos
al reranker) igual que app.rag.recuperacion, y arma el diagnóstico de los fallos y
la comparación de variantes. Se ejecuta en el anfitrión:

    python -m app.scripts.variantes_recuperacion --desarrollo data/mediciones/b2_rankings_desarrollo.json \\
        > data/mediciones/b2_variantes.md
    python -m app.scripts.variantes_recuperacion --desarrollo ... --prueba data/mediciones/b2_rankings_prueba.json \\
        --propuesta 20x60x1:1x8+e

El conjunto de desarrollo son las consultas de ajuste (R) y de validación (V); el de
prueba (P) se evalúa una sola vez, al final, con la variante actual y la propuesta.

Con --edad (parte C2) compara los pesos de la bonificación por edad en la fusión
(BONIFICACION_EDAD): el peso se elige con R y se informa V. La edad de cada consulta
sale de su texto (dominio.edad_mencionada_meses) y el signo de cada fragmento, de su
grupo etario, ambos guardados por medir_recuperacion rankings."""
import argparse
import itertools
import json
import math
from dataclasses import dataclass
from pathlib import Path

from app.rag.recuperacion import ajustar_por_edad, fusion_rrf
from app.rag.texto import terminos

FRAGMENTOS_ENVIADOS = 5


@dataclass(frozen=True)
class Variante:
    candidatos_busqueda: int = 20
    rrf_k: int = 60
    peso_bm25: float = 1.0
    peso_vectorial: float = 1.0
    candidatos_reranker: int = 8
    # BM25 con los sinónimos en español del diccionario desde la búsqueda inicial.
    expansion: bool = False
    # Peso de la edad del paciente en la fusión (BONIFICACION_EDAD).
    bono_edad: float = 0.0

    @property
    def nombre(self) -> str:
        return (f"{self.candidatos_busqueda}x{self.rrf_k}x{self.peso_bm25:g}:{self.peso_vectorial:g}"
                f"x{self.candidatos_reranker}" + ("+e" if self.expansion else "")
                + (f"+b{self.bono_edad:g}" if self.bono_edad else ""))

    @classmethod
    def desde_nombre(cls, nombre: str) -> "Variante":
        nombre, _, bono = nombre.partition("+b")
        expansion = nombre.endswith("+e")
        n, k, pesos, r = nombre.removesuffix("+e").split("x")
        pb, pv = pesos.split(":")
        return cls(int(n), int(k), float(pb), float(pv), int(r), expansion, float(bono) if bono else 0.0)


ACTUAL = Variante()


def rejilla(expansion: bool = True) -> list[Variante]:
    """Candidatos por método 20, 30 o 40; k de RRF 10, 30 o 60; pesos iguales o el
    doble para uno de los métodos; 8, 10 o 12 candidatos al reranker; BM25 con o sin
    la expansión del diccionario."""
    return [Variante(n, k, pb, pv, r, e) for n, k, (pb, pv), r, e in
            itertools.product((20, 30, 40), (10, 30, 60), ((1.0, 1.0), (1.0, 2.0), (2.0, 1.0)), (8, 10, 12),
                              (False, True) if expansion else (False,))]


BONOS_EDAD = (0.1, 0.2, 0.3, 0.5, 0.7)


def rejilla_edad() -> list[Variante]:
    """La configuración vigente con cada peso de la bonificación por edad."""
    return [Variante(bono_edad=b) for b in BONOS_EDAD]


def fusionar(consulta: dict, v: Variante) -> list[str]:
    lexica = consulta["bm25_expandida"] if v.expansion else consulta["bm25"]
    listas = [lexica[:v.candidatos_busqueda], consulta["vectorial"][:v.candidatos_busqueda]]
    fusion = fusion_rrf(listas, v.rrf_k, [v.peso_bm25, v.peso_vectorial])
    return [i for i, _ in ajustar_por_edad(fusion, consulta.get("signos", {}), v.bono_edad)]


def evaluados(consulta: dict, v: Variante) -> list[str]:
    return fusionar(consulta, v)[:v.candidatos_reranker]


def orden_final(consulta: dict, v: Variante) -> list[str]:
    """Candidatos evaluados ordenados por el reranker; los empates conservan el orden
    de la fusión, como en app.rag.recuperacion.seleccionar."""
    candidatos = evaluados(consulta, v)
    puntajes = consulta["puntajes"]
    return [candidatos[j] for j in sorted(range(len(candidatos)), key=lambda j: (-puntajes[candidatos[j]], j))]


def top5(consulta: dict, v: Variante) -> list[str]:
    return orden_final(consulta, v)[:FRAGMENTOS_ENVIADOS]


def acierta(consulta: dict, v: Variante, original: bool = False) -> bool:
    esperados = set(consulta["esperados_originales" if original else "esperados"])
    return any(i in esperados for i in top5(consulta, v))


def posicion(lista: list[str], esperados: list[str]) -> int | None:
    """Mejor posición (desde 1) de un fragmento esperado en la lista."""
    posiciones = [lista.index(i) + 1 for i in esperados if i in lista]
    return min(posiciones) if posiciones else None


def wilson(aciertos: int, total: int, z: float = 1.96) -> tuple[float, float]:
    """Intervalo de confianza de Wilson al 95 % para una proporción."""
    if total == 0:
        return float("nan"), float("nan")
    p = aciertos / total
    centro = (p + z * z / (2 * total)) / (1 + z * z / total)
    margen = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / (1 + z * z / total)
    return max(0.0, centro - margen), min(1.0, centro + margen)


def conjunto(id_: str) -> str:
    return {"R": "ajuste", "V": "validación", "P": "prueba"}[id_[0]]


def tasa(consultas: list[dict], v: Variante, original: bool = False) -> tuple[int, int]:
    return sum(acierta(q, v, original) for q in consultas), len(consultas)


def _pct(aciertos: int, total: int) -> str:
    return f"{100 * aciertos / total:.0f} % ({aciertos}/{total})" if total else "-"


def _ic(aciertos: int, total: int) -> str:
    bajo, alto = wilson(aciertos, total)
    return f"{100 * bajo:.0f} a {100 * alto:.0f} %"


def _p(x: int | None) -> str:
    return "-" if x is None else str(x)


def solapamiento(consulta: dict, fragmento: dict) -> float:
    """Fracción de los términos de la consulta (raíces) presentes en el fragmento."""
    propios = set(consulta["terminos"])
    if not propios:
        return 0.0
    return len(propios & set(terminos(fragmento["texto"], fragmento["idioma"]))) / len(propios)


def diagnostico(datos: dict, v: Variante = ACTUAL) -> list[dict]:
    """Por consulta que falla con la variante v: posición del mejor fragmento esperado
    en BM25, en la búsqueda vectorial, en la fusión y en el orden del reranker, el
    puntaje que le daría el reranker y datos para la causa probable."""
    filas = []
    for q in datos["consultas"]:
        if acierta(q, v):
            continue
        esperados = q["esperados"]
        fusion = fusionar(q, v)
        final = orden_final(q, v)
        mejor = min(esperados, key=lambda i: -q["puntajes"].get(i, -1.0)) if esperados else None
        fragmento = datos["fragmentos"].get(mejor, {}) if mejor else {}
        # Posición que tendría el esperado si el reranker lo evaluara junto con los demás.
        hipotetica = None
        if mejor is not None and mejor in q["puntajes"]:
            hipotetica = 1 + sum(q["puntajes"][i] > q["puntajes"][mejor] for i in final if i != mejor)
        filas.append({
            "id": q["id"], "conjunto": conjunto(q["id"]), "consulta": q["consulta"],
            "bm25": posicion(q["bm25"], esperados), "vectorial": posicion(q["vectorial"], esperados),
            "rrf": posicion(fusion, esperados), "reranker": posicion(final, esperados),
            "puntaje_esperado": q["puntajes"].get(mejor) if mejor else None,
            "puntaje_maximo": max((q["puntajes"][i] for i in final), default=None),
            "posicion_si_se_evaluara": hipotetica,
            "seccion": fragmento.get("seccion"), "documento": fragmento.get("codigo_documento"),
            "longitud": len(fragmento.get("texto", "")), "idioma": fragmento.get("idioma"),
            "solapamiento": round(solapamiento(q, fragmento), 2) if fragmento else None,
        })
    return filas


def tabla_diagnostico(datos: dict, v: Variante = ACTUAL) -> list[str]:
    lineas = [f"**Fallos con la variante {v.nombre}** (posición del mejor fragmento esperado; «-» = no aparece)", "",
              "| Consulta | Conjunto | BM25 | Vectorial | RRF | Reranker | Puntaje esperado / máximo | "
              "Posición si se evaluara | Fragmento esperado | Caracteres | Términos de la consulta en el fragmento |",
              "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for f in diagnostico(datos, v):
        puntajes = "-" if f["puntaje_esperado"] is None else f"{f['puntaje_esperado']:.3f} / {f['puntaje_maximo']:.3f}"
        seccion = (f["seccion"] or "(sin sección)")[-70:]
        lineas.append(f"| {f['id']} | {f['conjunto']} | {_p(f['bm25'])} | {_p(f['vectorial'])} | {_p(f['rrf'])} | "
                      f"{_p(f['reranker'])} | {puntajes} | {_p(f['posicion_si_se_evaluara'])} | "
                      f"{f['documento']}: {seccion} | {f['longitud']} | {100 * (f['solapamiento'] or 0):.0f} % |")
    return lineas


def tabla_variantes(datos: dict, variantes: list[Variante], mejores: int = 15) -> list[str]:
    consultas = datos["consultas"]
    ajuste = [q for q in consultas if q["id"].startswith("R")]
    validacion = [q for q in consultas if q["id"].startswith("V")]
    filas = []
    for v in variantes:
        a, n = tasa(consultas, v)
        filas.append((a, -v.candidatos_reranker, -v.candidatos_busqueda, v))
    filas.sort(key=lambda f: (-f[0], -f[1], -f[2], f[3].nombre))
    elegidas = [f[3] for f in filas[:mejores]]
    if ACTUAL not in elegidas:
        elegidas.append(ACTUAL)
    lineas = ["| Variante (n x k x pesos BM25:vectorial x reranker) | Desarrollo | IC 95 % | Ajuste (R) | "
              "Validación (V) |", "| --- | --- | --- | --- | --- |"]
    for v in elegidas:
        a, n = tasa(consultas, v)
        marca = " (actual)" if v == ACTUAL else ""
        lineas.append(f"| {v.nombre}{marca} | {_pct(a, n)} | {_ic(a, n)} | {_pct(*tasa(ajuste, v))} | "
                      f"{_pct(*tasa(validacion, v))} |")
    return lineas


def tabla_prueba(datos: dict, variantes: list[Variante]) -> list[str]:
    consultas = datos["consultas"]
    casos = [q for q in consultas if q.get("tipo") == "caso"]
    libres = [q for q in consultas if q.get("tipo") == "libre"]
    lineas = ["| Variante | Prueba (20) | IC 95 % | Casos clínicos (10) | Preguntas libres (10) |",
              "| --- | --- | --- | --- | --- |"]
    for v in variantes:
        a, n = tasa(consultas, v)
        lineas.append(f"| {v.nombre} | {_pct(a, n)} | {_ic(a, n)} | {_pct(*tasa(casos, v))} | {_pct(*tasa(libres, v))} |")
    return lineas


def detalle(datos: dict, variantes: list[Variante]) -> list[str]:
    cabecera = " | ".join(v.nombre for v in variantes)
    lineas = [f"| Consulta | {cabecera} |", "| --- |" + " --- |" * len(variantes)]
    for q in datos["consultas"]:
        marcas = " | ".join("sí" if acierta(q, v) else "no" for v in variantes)
        lineas.append(f"| {q['id']} | {marcas} |")
    return lineas


def tabla_edad(datos: dict) -> list[str]:
    """Aciertos en el top 5 por peso de la bonificación: R (calibración), V (validación)
    y las consultas con edad en el texto; y las consultas que cambian frente a 0."""
    consultas = datos["consultas"]
    r = [q for q in consultas if q["id"].startswith("R")]
    v = [q for q in consultas if q["id"].startswith("V")]
    con_edad = [q for q in consultas if q.get("edad_meses") is not None]
    filas = ["| Peso | R (calibración) | V (validación) | Con edad en el texto (R y V) | Cambian frente a 0 |",
             "| --- | --- | --- | --- | --- |"]
    for variante in [ACTUAL, *rejilla_edad()]:
        cambios = [f"{q['id']} {'+' if acierta(q, variante) else '-'}" for q in consultas
                   if acierta(q, variante) != acierta(q, ACTUAL)]
        filas.append(f"| {variante.bono_edad:g} | {_pct(*tasa(r, variante))} | {_pct(*tasa(v, variante))} | "
                     f"{_pct(*tasa(con_edad, variante))} | {', '.join(cambios) or 'ninguna'} |")
    return [f"Consultas con edad en el texto: {len(con_edad)} ({', '.join(q['id'] for q in con_edad)}).", "", *filas]


def cargar(ruta: str) -> dict:
    return json.loads(Path(ruta).read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.scripts.variantes_recuperacion")
    parser.add_argument("--desarrollo", required=True, help="JSON de rankings del conjunto de desarrollo")
    parser.add_argument("--prueba", help="JSON de rankings del conjunto de prueba (medición final)")
    parser.add_argument("--propuesta", help="variante propuesta, por ejemplo 30x60x1:1x8")
    parser.add_argument("--edad", action="store_true", help="compara los pesos de la bonificación por edad")
    args = parser.parse_args(argv)
    desarrollo = cargar(args.desarrollo)
    if args.edad:
        print("\n".join(["## Bonificación por edad en la fusión", "", *tabla_edad(desarrollo), ""]))
        return 0
    salida = ["## Conjunto de desarrollo", "", *tabla_diagnostico(desarrollo), "",
              "**Variantes de la primera etapa** (las 15 mejores y la actual)", "",
              *tabla_variantes(desarrollo, rejilla("bm25_expandida" in desarrollo["consultas"][0])), ""]
    original = [q for q in desarrollo["consultas"] if q["id"].startswith("V")]
    a_orig, n_orig = tasa(original, ACTUAL, original=True)
    a_corr, n_corr = tasa(original, ACTUAL)
    salida += [f"Validación con la variante actual: {a_orig} de {n_orig} con las secciones esperadas originales y "
               f"{a_corr} de {n_corr} con la corrección de V11.", ""]
    if args.propuesta:
        propuesta = Variante.desde_nombre(args.propuesta)
        salida += [*tabla_diagnostico(desarrollo, propuesta), ""]
        if args.prueba:
            prueba = cargar(args.prueba)
            salida += ["## Conjunto de prueba", "", *tabla_prueba(prueba, [ACTUAL, propuesta]), "",
                       *detalle(prueba, [ACTUAL, propuesta]), "", *tabla_diagnostico(prueba, propuesta), ""]
    print("\n".join(salida))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
