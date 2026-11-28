"""Job de evaluación del OE3. Fases (docs/diseno_evaluacion_oe3.md, sección 6):

    python -m app.evaluacion validar [--con-base]
    python -m app.evaluacion ejecutar --salida DIR [--llm falso|real] [--confirmo-datos-sinteticos]
    python -m app.evaluacion extraer --salida DIR
    python -m app.evaluacion juzgar --salida DIR [--juez falso|anthropic] [--modelo M] [--k 3]
                                    [--razonamiento T] [--esfuerzo E] [--confirmo-datos-sinteticos]
    python -m app.evaluacion informe --salida DIR [--modelo M] [--git ETIQUETA]
    python -m app.evaluacion comparar-jueces --salida DIR --modelos claude-sonnet-5-5,claude-haiku-5-5
    python -m app.evaluacion ensayo --salida DIR        (las cuatro fases con el cliente y el juez falsos)

Opciones comunes: --conjunto DIR (con esquema_caso.json; por omisión EVALUACION_DIR_CONJUNTO o
/datos/conjunto), --grupo evaluacion|piloto (evaluacion por omisión; el piloto nunca con
--llm real), --casos OE3-P01,OE3-P02.

Archivos en la carpeta de salida: manifiesto.json, ejecucion.jsonl, extraccion.jsonl,
juez/<modelo>/llamadas.jsonl y resultados.jsonl, cache_juez/, informe_<modelo>.md y .json.
Con el cliente o el juez falsos el informe lleva el rótulo de ensayo."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

from app.evaluacion import dataset, informe, juzgar
from app.evaluacion import prompts_juez as pj
from app.evaluacion.juez import MODELO_FALSO, ConfiguracionJuez, Juez, crear_cliente


def _jsonl(ruta: Path) -> list[dict]:
    if not ruta.exists():
        return []
    return [json.loads(l) for l in ruta.read_text(encoding="utf-8").splitlines() if l.strip()]


def _escribir_jsonl(ruta: Path, filas: list[dict]) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text("".join(json.dumps(f, ensure_ascii=False, default=str) + "\n" for f in filas), encoding="utf-8")


def _slug(modelo: str) -> str:
    return re.sub(r"[^a-z0-9.-]+", "_", modelo.lower())


def _conjunto(a) -> dataset.Conjunto:
    ids = set(a.casos.split(",")) if a.casos else None
    return dataset.cargar_conjunto(Path(a.conjunto), a.grupo, ids)


def _huella() -> str:
    from app.core.db import engines
    from app.services.parametros import huella
    with engines()["clinica"].connect() as c:
        return huella(c)["huella"]


# ---------------------------------------------------------------------------
def cmd_validar(a) -> int:
    conjunto = _conjunto(a)
    print(json.dumps(conjunto.manifiesto(), ensure_ascii=False, indent=2))
    if not a.con_base:
        return 0
    from sqlalchemy import text

    from app.core.db import engines
    from app.evaluacion.cue import Fragmento, cumple
    with engines()["generacion"].connect() as c:
        c.execute(text("SET TRANSACTION READ ONLY"))
        filas = c.execute(text(
            """SELECT f.id_fragmento::text, d.codigo_documento, f.pagina_inicio, f.pagina_fin, f.texto,
                      (f.vigente AND d.estado = 'VIGENTE' AND f.version_indexacion =
                         (SELECT max(v.version_indexacion) FROM conocimiento.fragmento v
                           WHERE v.id_documento = f.id_documento)) AS vigente
                 FROM conocimiento.fragmento f JOIN conocimiento.documento_fuente d USING (id_documento)""")).all()
    frags = [Fragmento(None, f[0], f[1], f[2], f[3], f[4], bool(f[5])) for f in filas]
    problemas = 0
    for caso in conjunto.casos:
        for cr in caso.criterios:
            for alt in cr.alternativas:
                n = sum(cumple(alt, f) for f in frags)
                if n != 1:
                    problemas += 1
                    print(f"{caso.id} {cr.id} {alt.documento} p{list(alt.paginas)}: {n} fragmentos vigentes")
    print(f"Anclajes con un solo fragmento vigente: {'todos' if not problemas else f'{problemas} problemas'}")
    return 0 if not problemas else 1


def cmd_ejecutar(a) -> int:
    from app.core.db import engines
    from app.evaluacion import ejecutar
    from app.rag.cliente_llm import ClienteFalso
    from app.services import consultas as srv
    conjunto = _conjunto(a)
    salida = Path(a.salida)
    if a.llm == "real" and conjunto.grupo == "piloto":
        print("El piloto se prueba solo con el cliente falso (opción A del diseño).", file=sys.stderr)
        return 2
    motores = engines()
    huella_inicio = _huella()
    creados = ejecutar.preparar_ficticios(motores["clinica"], conjunto.casos)
    _, servicios, dominio = srv._modelos_por_defecto()
    entorno = srv.EntornoConsulta(motores["clinica"], motores["generacion"], servicios, dominio, ClienteFalso(),
                                  srv.limites_por_defecto())
    srv.calentar(entorno, llamar_llm=False)
    filas = ejecutar.ejecutar(conjunto, entorno, salida, a.llm, a.falso_segun_esperado, a.confirmo_datos_sinteticos)
    manifiesto = {"conjunto": conjunto.manifiesto(), "llm": a.llm, "falso_segun_esperado": a.falso_segun_esperado,
                  "huella_configuracion_inicio": huella_inicio, "pacientes_ficticios_creados": creados,
                  "ejecutado": time.strftime("%Y-%m-%d %H:%M:%S"), "consultas": len(filas)}
    (salida / "manifiesto.json").write_text(json.dumps(manifiesto, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Ejecutados {len(filas)} casos; estados iguales al esperado: "
          f"{sum(f['estado'] == f['estado_esperado'] for f in filas)}")
    return 0


def cmd_extraer(a) -> int:
    from app.core.db import engines
    from app.evaluacion.extraer import extraer_consulta
    salida = Path(a.salida)
    ejecucion = _jsonl(salida / "ejecucion.jsonl")
    if not ejecucion:
        print("No hay ejecucion.jsonl en la carpeta de salida.", file=sys.stderr)
        return 2
    motor = engines()["generacion"]
    filas = []
    for e in ejecucion:
        ext = extraer_consulta(motor, e["id_consulta"]) if e["id_consulta"] else None
        filas.append({"id_caso": e["id_caso"], "extraccion": ext})
    _escribir_jsonl(salida / "extraccion.jsonl", filas)
    print(f"Extraídas {len(filas)} consultas")
    return 0


def _juzgar(a, salida: Path, conjunto: dataset.Conjunto, modelo: str) -> Path:
    config = ConfiguracionJuez(modelo=modelo, razonamiento=a.razonamiento, esfuerzo=a.esfuerzo,
                               max_tokens=a.max_tokens, k=a.k)
    cliente = crear_cliente(a.juez, modelo, a.confirmo_datos_sinteticos)
    carpeta = salida / "juez" / _slug(cliente.modelo)
    registro = carpeta / "llamadas.jsonl"
    if registro.exists():
        registro.unlink()
    juez = Juez(cliente, config, salida / "cache_juez", registro, {c.id for c in conjunto.casos})
    extracciones = {f["id_caso"]: f["extraccion"] for f in _jsonl(salida / "extraccion.jsonl")}
    resultados = []
    for caso in conjunto.casos:
        ext = extracciones.get(caso.id)
        if ext is None:
            print(f"{caso.id}: sin extracción, se omite", file=sys.stderr)
            continue
        resultados.append(juzgar.juzgar_caso(juez, caso, ext, config.k, con_ragas=not a.sin_ragas))
    _escribir_jsonl(carpeta / "resultados.jsonl", resultados)
    (carpeta / "configuracion.json").write_text(json.dumps(
        {"tipo": a.juez, "modelo": cliente.modelo, "razonamiento": config.razonamiento, "esfuerzo": config.esfuerzo,
         "max_tokens": config.max_tokens, "k": config.k, "temperatura": "sin fijar", "ragas": not a.sin_ragas},
        ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(juez.resumen(), ensure_ascii=False))
    return carpeta


def cmd_juzgar(a) -> int:
    _juzgar(a, Path(a.salida), _conjunto(a), a.modelo)
    return 0


def _resumen_llamadas(llamadas: list[dict], modelo: str) -> dict:
    nuevas = [x for x in llamadas if not x["cache"]]
    costos = [x["costo_usd"] for x in nuevas if x["costo_usd"] is not None]
    return {"modelo": modelo, "llamadas": len(llamadas), "desde_cache": len(llamadas) - len(nuevas),
            "fallidas": sum(not x["ok"] for x in llamadas),
            "tokens_entrada": sum(x["tokens_entrada"] for x in nuevas),
            "tokens_salida": sum(x["tokens_salida"] for x in nuevas),
            "costo_usd": round(sum(costos), 6) if len(costos) == len(nuevas) else None}


def construir_informe(salida: Path, modelo_slug: str, git: str, huella_fin: str, freeze: list[str],
                      ragas_version: str, ragas_sin_telemetria: bool | None) -> dict:
    manifiesto = json.loads((salida / "manifiesto.json").read_text(encoding="utf-8"))
    carpeta = salida / "juez" / modelo_slug
    config = json.loads((carpeta / "configuracion.json").read_text(encoding="utf-8"))
    resultados = _jsonl(carpeta / "resultados.jsonl")
    extracciones = {f["id_caso"]: f["extraccion"] for f in _jsonl(salida / "extraccion.jsonl") if f["extraccion"]}
    llamadas = _jsonl(carpeta / "llamadas.jsonl")
    ensayo = manifiesto["llm"] == "falso" or config["modelo"].startswith(MODELO_FALSO)
    reproducibilidad = {
        "grupo": manifiesto["conjunto"]["grupo"], "conjunto": manifiesto["conjunto"], "llm": manifiesto["llm"],
        "git": git, "huella_configuracion_inicio": manifiesto["huella_configuracion_inicio"],
        "huella_configuracion_fin": huella_fin, "juez": config,
        "prompts": {"version": pj.VERSION, "sha256": pj.huellas()}, "ragas": ragas_version,
        "ragas_sin_telemetria": ragas_sin_telemetria, "precios_usd_mtok": _precios(),
        "pip_freeze": freeze, "generado": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    return {"ensayo": ensayo, "rotulo": informe.ROTULO_ENSAYO if ensayo else None,
            "resumen": informe.resumen(resultados), "desgloses": informe.desgloses(resultados),
            "costos": informe.costos(extracciones, _resumen_llamadas(llamadas, config["modelo"])),
            "reproducibilidad": reproducibilidad, "casos": resultados}


def _precios() -> dict:
    from app.evaluacion.juez import PRECIOS_USD_MTOK
    return {k: list(v) for k, v in PRECIOS_USD_MTOK.items()}


def _ragas() -> tuple[str, bool | None]:
    try:
        from importlib.metadata import version
        v = version("ragas")
    except Exception:  # noqa: BLE001
        return "no instalado", None
    try:
        from app.evaluacion.ragas_metricas import telemetria_apagada
        return v, telemetria_apagada()
    except Exception:  # noqa: BLE001
        return v, None


def cmd_informe(a) -> int:
    salida = Path(a.salida)
    slug = _slug(a.modelo_informe) if a.modelo_informe else _slug(_unico_modelo(salida))
    ragas_version, sin_telemetria = _ragas()
    datos = construir_informe(salida, slug, a.git or os.environ.get("EVALUACION_GIT", "desconocido"), _huella(),
                              informe.pip_freeze(), ragas_version, sin_telemetria)
    (salida / f"informe_{slug}.json").write_text(json.dumps(datos, ensure_ascii=False, indent=2, default=str),
                                                 encoding="utf-8")
    (salida / f"informe_{slug}.md").write_text(informe.markdown(datos), encoding="utf-8")
    print(f"Informe: {salida / f'informe_{slug}.md'}")
    if datos["reproducibilidad"]["huella_configuracion_inicio"] != datos["reproducibilidad"]["huella_configuracion_fin"]:
        print("ATENCIÓN: la huella de la configuración cambió durante la evaluación", file=sys.stderr)
        return 1
    return 0


def _unico_modelo(salida: Path) -> str:
    modelos = [p.name for p in (salida / "juez").iterdir() if p.is_dir()] if (salida / "juez").exists() else []
    if len(modelos) != 1:
        raise SystemExit(f"Indique --modelo-informe; hay {len(modelos)} jueces en {salida / 'juez'}")
    return modelos[0]


def cmd_comparar(a) -> int:
    """Prepara la comparación de jueces sobre la misma extracción. Con --juez falso solo prueba el
    mecanismo; con la API la ejecuta el responsable."""
    salida, conjunto = Path(a.salida), _conjunto(a)
    tablas = {}
    for modelo in a.modelos.split(","):
        carpeta = _juzgar(a, salida, conjunto, modelo)
        filas = _jsonl(carpeta / "resultados.jsonl")
        tablas[carpeta.name] = {"resumen": informe.resumen(filas),
                                "cuadrantes": {f["id_caso"]: f["agregado"]["cuadrante"] for f in filas}}
    nombres = list(tablas)
    lineas = ["# Comparación de jueces" + (" (ENSAYO CON JUEZ FALSO: los números no tienen valor)"
                                          if a.juez == "falso" else ""), "",
              "| Métrica | " + " | ".join(nombres) + " |", "| --- |" + " --- |" * len(nombres)]
    for m in informe.METRICAS_MEDIA:
        lineas.append(f"| {informe.NOMBRES.get(m, m)} | " + " | ".join(
            informe._num(tablas[n]["resumen"]["medias"][m]["media"]) for n in nombres) + " |")
    if len(nombres) >= 2:
        a0, b0 = tablas[nombres[0]]["cuadrantes"], tablas[nombres[1]]["cuadrantes"]
        comunes = set(a0) & set(b0)
        iguales = sum(a0[c] == b0[c] for c in comunes)
        lineas += ["", f"Mismo cuadrante en {iguales} de {len(comunes)} casos."]
    (salida / "comparacion_jueces.md").write_text("\n".join(lineas) + "\n", encoding="utf-8")
    print(f"Comparación: {salida / 'comparacion_jueces.md'}")
    return 0


def cmd_ensayo(a) -> int:
    a.llm, a.juez, a.confirmo_datos_sinteticos = "falso", "falso", False
    for paso in (cmd_ejecutar, cmd_extraer, cmd_juzgar):
        codigo = paso(a)
        if codigo:
            return codigo
    a.modelo_informe = None
    return cmd_informe(a)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m app.evaluacion", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="orden", required=True)

    def comunes(sp, salida=True):
        sp.add_argument("--conjunto", default=str(dataset.DIR_CONJUNTO_DEFECTO))
        sp.add_argument("--grupo", default=dataset.GRUPO_DEFECTO, choices=dataset.GRUPOS)
        sp.add_argument("--casos", help="ids separados por comas")
        if salida:
            sp.add_argument("--salida", required=True)

    def juez(sp):
        sp.add_argument("--juez", default="falso", choices=["falso", "anthropic"])
        sp.add_argument("--modelo", default=MODELO_FALSO)
        sp.add_argument("--razonamiento", default=None, help="thinking.type del juez (por omisión no se envía)")
        sp.add_argument("--esfuerzo", default=None, help="output_config.effort (por omisión no se envía)")
        sp.add_argument("--max-tokens", type=int, default=4000)
        sp.add_argument("--k", type=int, default=3)
        sp.add_argument("--sin-ragas", action="store_true", help="solo los juicios propios (sin RAGAS instalado)")
        sp.add_argument("--confirmo-datos-sinteticos", action="store_true")

    v = sub.add_parser("validar")
    comunes(v, salida=False)
    v.add_argument("--con-base", action="store_true", help="comprueba los anclajes contra los fragmentos de la base")
    v.set_defaults(f=cmd_validar)

    e = sub.add_parser("ejecutar")
    comunes(e)
    e.add_argument("--llm", default="falso", choices=["falso", "real"])
    e.add_argument("--falso-segun-esperado", action="store_true",
                   help="solo ensayo: el cliente falso declara evidencia insuficiente donde el caso la espera")
    e.add_argument("--confirmo-datos-sinteticos", action="store_true")
    e.set_defaults(f=cmd_ejecutar)

    x = sub.add_parser("extraer")
    x.add_argument("--salida", required=True)
    x.set_defaults(f=cmd_extraer)

    j = sub.add_parser("juzgar")
    comunes(j)
    juez(j)
    j.set_defaults(f=cmd_juzgar)

    i = sub.add_parser("informe")
    i.add_argument("--salida", required=True)
    i.add_argument("--modelo-informe", help="carpeta del juez dentro de juez/ (si hay más de uno)")
    i.add_argument("--git", help="etiqueta o commit evaluado (o EVALUACION_GIT)")
    i.set_defaults(f=cmd_informe)

    c = sub.add_parser("comparar-jueces")
    comunes(c)
    juez(c)
    c.add_argument("--modelos", required=True, help="por ejemplo claude-sonnet-5-5,claude-haiku-5-5")
    c.set_defaults(f=cmd_comparar)

    s = sub.add_parser("ensayo")
    comunes(s)
    juez(s)
    s.add_argument("--git")
    s.add_argument("--falso-segun-esperado", action="store_true")
    s.set_defaults(f=cmd_ensayo)

    a = p.parse_args(argv)
    try:
        return a.f(a)
    except dataset.ErrorConjunto as err:
        print(str(err), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
