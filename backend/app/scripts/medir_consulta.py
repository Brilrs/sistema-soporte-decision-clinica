"""Medición de punta a punta del grafo de la consulta (parte D1), con el servicio de
app/services/consultas.py: los mismos 12 casos de casos_e2e.yaml que la prueba de la
parte C, ahora por el grafo, con los eventos, el tiempo hasta el primer evento, los
tiempos por nodo, la espera en cola y el total.

Solo usa pacientes ficticios de seed_demo (rechaza un caso cuyo DNI no esté en
seed_demo). Por defecto usa el cliente falso del modelo de lenguaje; con --llm real llama
a la API de Anthropic y exige ANTHROPIC_API_KEY y --confirmo-datos-sinteticos (lo ejecuta
el responsable). El perfil (normal o B2ms) lo fija docker compose; --entorno solo lo anota.

Uso (en el contenedor backend, con la red de Docker; ver docs/mediciones_sprint2.md):
    python -m app.scripts.medir_consulta [--llm falso|real] [--confirmo-datos-sinteticos]
        [--casos a,b] [--repeticiones 3] [--concurrentes 2] [--entorno normal] [--etiqueta v5]
        [--sin-calentar] [--versiones-prompt v1.1,v1.2]

Guarda <salida>/d_consulta_<llm>[_<etiqueta>].md y .json. Por cada consulta registra el
estado, los eventos (sin texto de la consulta), los tiempos y, leídos con cdss_generacion,
los intentos (tokens, costo, resultado, tiempos) y los fragmentos enviados.

Con --versiones-prompt (por ejemplo v1.1,v1.2) corre los casos una vez por versión del
prompt, cambiándola solo en memoria (VERSION_PROMPT de la base no cambia), y agrega la
comparación de estados, tokens de salida, tiempo de generar y total por versión."""
import argparse
import asyncio
import json
import math
import os
import sys
import time
from dataclasses import replace
from pathlib import Path

from sqlalchemy import text

from app.core.seguridad import hmac_identificador
from app.scripts.prueba_punta_a_punta import DNIS_SEED, USUARIO, cargar_casos, cliente_para
from app.services import consultas as srv


def percentil(valores: list[float], p: float) -> float | None:
    """Percentil por rango más cercano (p entre 0 y 100)."""
    if not valores:
        return None
    ordenados = sorted(valores)
    k = max(0, min(len(ordenados) - 1, math.ceil(p / 100 * len(ordenados)) - 1))
    return ordenados[k]


def _ids(c, caso: dict) -> tuple[str, str]:
    fila = c.execute(text(
        """SELECT t.id_paciente::text, t.id_tamizaje::text FROM clinico.tamizaje t
             JOIN clinico.paciente_identidad i ON i.id_paciente = t.id_paciente
            WHERE i.dni_hash = :h AND t.fecha_tamizaje = :f"""),
        {"h": hmac_identificador(caso["dni"]), "f": caso["fecha_tamizaje"]}).first()
    if fila is None:
        raise SystemExit(f"No existe el tamizaje del caso {caso['id']} (ejecute seed_demo)")
    return fila[0], fila[1]


_INTENTOS = """
    SELECT numero_intento, tipo_busqueda, resultado, modelo_llm, version_prompt, tokens_entrada, tokens_salida, tokens_razonamiento,
           costo_usd, latencia_llm_ms, relevancia_maxima, valida_citas, valida_consistencia, valida_evidencia,
           tiempos_ms, id_intento::text
      FROM asistencia.intento_generacion WHERE id_consulta = CAST(:c AS uuid) ORDER BY numero_intento
"""
_ENVIADOS = """
    SELECT r.etiqueta_cita, d.codigo_documento, f.seccion, r.puntaje_reranker
      FROM asistencia.fragmento_recuperado r
      JOIN conocimiento.fragmento f ON f.id_fragmento = r.id_fragmento
      JOIN conocimiento.documento_fuente d ON d.id_documento = f.id_documento
     WHERE r.id_intento = CAST(:i AS uuid) AND r.enviado_al_llm ORDER BY r.etiqueta_cita
"""


def detalle_intentos(motor, id_consulta: str) -> list[dict]:
    """Con cdss_generacion, que puede leer los intentos y los fragmentos (no la identidad)."""
    with motor.connect() as c:
        salida = []
        for i in c.execute(text(_INTENTOS), {"c": id_consulta}).mappings():
            fila = {k: (float(v) if k in ("costo_usd", "relevancia_maxima") and v is not None else v)
                    for k, v in i.items() if k != "id_intento"}
            fila["enviados"] = [{"etiqueta": e.etiqueta_cita, "documento": e.codigo_documento, "seccion": e.seccion,
                                 "puntaje_reranker": None if e.puntaje_reranker is None else float(e.puntaje_reranker)}
                                for e in c.execute(text(_ENVIADOS), {"i": i["id_intento"]})]
            salida.append(fila)
    return salida


async def _una(caso: dict, solicitud: srv.SolicitudConsulta, entorno: srv.EntornoConsulta, llm: str,
               repeticion: int) -> dict:
    inicio = time.perf_counter()
    eventos = await srv.eventos_de(solicitud, replace(entorno, cliente=cliente_para(caso, llm)))
    total_cliente = round((time.perf_counter() - inicio) * 1000)
    fin = eventos[-1]
    return {"caso": caso["id"], "repeticion": repeticion, "descripcion": caso["descripcion"],
            "esperado": caso["esperado"], "estado": fin.get("estado"), "coincide": fin.get("estado") == caso["esperado"],
            "id_consulta": fin.get("id_consulta"), "total_cliente_ms": total_cliente,
            "primer_evento_ms": eventos[0]["transcurrido_ms"], "tiempos_ms": fin.get("tiempos_ms"),
            "eventos": [{k: v for k, v in e.items() if k not in ("recomendacion", "citas", "clasificacion")}
                        for e in eventos],
            "citas": fin.get("citas", []), "mensaje": fin.get("mensaje")}


def resumen(filas: list[dict]) -> dict:
    def serie(clave, filtro=lambda f: True):
        return [f[clave] for f in filas if filtro(f) and f.get(clave) is not None]
    totales = serie("total_cliente_ms")
    verificadas = serie("total_cliente_ms", lambda f: f["estado"] == "VERIFICADA")
    primeros = serie("primer_evento_ms")
    nodos: dict[str, list[int]] = {}
    for f in filas:
        for nodo, ms in ((f.get("tiempos_ms") or {}).get("por_nodo") or {}).items():
            nodos.setdefault(nodo, []).append(ms)
    intentos = [i for f in filas for i in f.get("intentos", [])]
    enviados = [i for i in intentos if i.get("modelo_llm")]
    costo = sum(i["costo_usd"] or 0 for i in enviados)
    return {
        "consultas": len(filas), "coinciden": sum(f["coincide"] for f in filas),
        "total_ms": {"p50": percentil(totales, 50), "p90": percentil(totales, 90), "max": max(totales, default=None)},
        "total_verificadas_ms": {"p50": percentil(verificadas, 50), "p90": percentil(verificadas, 90)},
        "primer_evento_ms": {"p50": percentil(primeros, 50), "p90": percentil(primeros, 90)},
        "por_nodo_p50_ms": {n: percentil(v, 50) for n, v in nodos.items()},
        "espera_cola_ms_max": max([max((f.get("tiempos_ms") or {}).get("espera_ms", {}).values(), default=0)
                                   for f in filas], default=0),
        "intentos_enviados": len(enviados), "costo_usd": round(costo, 5),
        "tokens_entrada": sum(i["tokens_entrada"] or 0 for i in enviados),
        "tokens_salida": sum(i["tokens_salida"] or 0 for i in enviados),
    }


def comparar_versiones(filas: list[dict]) -> dict:
    """Por versión del prompt: estados, tokens de salida por intento enviado, generar y total."""
    comparacion = {}
    for version in dict.fromkeys(f["version_prompt"] for f in filas):
        propias = [f for f in filas if f["version_prompt"] == version]
        enviados = [i for f in propias for i in f.get("intentos", []) if i.get("modelo_llm")]
        salida = [i["tokens_salida"] for i in enviados if i.get("tokens_salida") is not None]
        generar = [ms for f in propias for e in (f.get("tiempos_ms") or {}).get("etapas", [])
                   if e["nodo"] == "generar" for ms in [e["ms"]]]
        r = resumen(propias)
        comparacion[version] = {
            "coinciden": r["coinciden"], "consultas": r["consultas"], "intentos_enviados": r["intentos_enviados"],
            "tokens_salida_total": r["tokens_salida"], "tokens_salida_p50": percentil(salida, 50),
            "tokens_salida_max": max(salida, default=None),
            "tokens_salida_media": round(sum(salida) / len(salida)) if salida else None,
            "generar_ms_p50": percentil(generar, 50), "generar_ms_p90": percentil(generar, 90),
            "total_ms": r["total_ms"], "total_verificadas_ms": r["total_verificadas_ms"], "costo_usd": r["costo_usd"],
            "estados": {f"{f['caso']}#{f['repeticion']}": f["estado"] for f in propias},
        }
    return comparacion


def informe_comparacion(comparacion: dict) -> list[str]:
    versiones = list(comparacion)
    lineas = ["## Comparación de versiones del prompt", "",
              "| Versión | Coinciden | Intentos enviados | Tokens de salida p50 / media / máx. | Generar p50 / p90 (ms) "
              "| Total p50 / p90 (ms) | Verificadas p50 / p90 (ms) | Costo (USD) |",
              "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for v, c in comparacion.items():
        lineas.append(f"| {v} | {c['coinciden']}/{c['consultas']} | {c['intentos_enviados']} | "
                      f"{c['tokens_salida_p50']} / {c['tokens_salida_media']} / {c['tokens_salida_max']} | "
                      f"{c['generar_ms_p50']} / {c['generar_ms_p90']} | {c['total_ms']['p50']} / {c['total_ms']['p90']} | "
                      f"{c['total_verificadas_ms']['p50']} / {c['total_verificadas_ms']['p90']} | {c['costo_usd']} |")
    lineas += ["", "| Caso | " + " | ".join(versiones) + " |", "| --- |" + " --- |" * len(versiones)]
    for clave in comparacion[versiones[0]]["estados"]:
        lineas.append(f"| {clave} | " + " | ".join(comparacion[v]["estados"].get(clave, "") for v in versiones) + " |")
    return lineas + [""]


def informe_markdown(filas: list[dict], total: dict, meta: dict, comparacion: dict | None = None) -> str:
    lineas = [f"# Consulta de punta a punta por el grafo (cliente {meta['llm']}, entorno {meta['entorno']})", "",
              f"Fecha {meta['fecha']}; {meta['repeticiones']} repetición(es), {meta['concurrentes']} consulta(s) a la "
              f"vez; límites {meta['limites']}; calentamiento {meta['calentamiento']}.", "",
              f"Coinciden con lo esperado: {total['coinciden']} de {total['consultas']}. Total p50 / p90: "
              f"{total['total_ms']['p50']} / {total['total_ms']['p90']} ms (verificadas: "
              f"{total['total_verificadas_ms']['p50']} / {total['total_verificadas_ms']['p90']} ms). Primer evento "
              f"p50 / p90: {total['primer_evento_ms']['p50']} / {total['primer_evento_ms']['p90']} ms. Espera máxima "
              f"en cola: {total['espera_cola_ms_max']} ms. Intentos enviados {total['intentos_enviados']}, costo "
              f"{total['costo_usd']} USD." + (" Con el cliente falso los tokens y el costo son simulados."
                                             if meta["llm"] == "falso" else ""), "",
              "Mediana por nodo (ms): " + ", ".join(f"{n} {v}" for n, v in total["por_nodo_p50_ms"].items()), ""]
    if comparacion:
        lineas += informe_comparacion(comparacion)
    lineas += ["| Prompt | Caso | Rep. | Esperado | Obtenido | Intentos | Primer evento (ms) | Total (ms) | Nodos (ms) |",
               "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for f in filas:
        nodos = ", ".join(f"{e['nodo']} {e['ms']}" for e in (f.get("tiempos_ms") or {}).get("etapas", []))
        intentos = "; ".join(f"{i['numero_intento']} {i['tipo_busqueda']} {i['resultado']}" for i in f["intentos"]) \
            or "sin intentos"
        marca = f["estado"] if f["coincide"] else f"**{f['estado']}**"
        lineas.append(f"| {f['version_prompt']} | {f['caso']} | {f['repeticion']} | {f['esperado']} | {marca} | {intentos} | "
                      f"{f['primer_evento_ms']} | {f['total_cliente_ms']} | {nodos} |")
    lineas += ["", "## Fragmentos enviados y citas (primera repetición)", ""]
    for f in [f for f in filas if f["repeticion"] == 1]:
        lineas.append(f"### Caso {f['caso']} (prompt {f['version_prompt']}): {f['descripcion']}")
        if f.get("mensaje"):
            lineas.append(f"- Mensaje: {f['mensaje']}")
        for i in f["intentos"]:
            lineas.append(f"- Intento {i['numero_intento']} ({i['tipo_busqueda']}, relevancia máxima "
                          f"{i['relevancia_maxima']}): {i['resultado']}; tokens {i['tokens_entrada']} / "
                          f"{i['tokens_salida']}; tiempos {json.dumps(i['tiempos_ms'], ensure_ascii=False)}")
            for e in i["enviados"]:
                lineas.append(f"  - {e['etiqueta']} {e['documento']} (reranker {e['puntaje_reranker']}): "
                              f"{' '.join((e['seccion'] or 'sin sección').split())[:140]}")
        for c in f.get("citas", []):
            lineas.append(f"- Cita {c['etiqueta']} ({c['fuente']}): «{' '.join(c['extracto'].split())}»")
        lineas.append("")
    return "\n".join(lineas)


async def _correr(casos, solicitudes, entorno, llm, repeticiones, concurrentes) -> list[dict]:
    trabajos = [(caso, solicitudes[caso["id"]], r) for r in range(1, repeticiones + 1) for caso in casos]
    filas = []
    for i in range(0, len(trabajos), concurrentes):
        lote = trabajos[i:i + concurrentes]
        filas += await asyncio.gather(*(_una(caso, s, entorno, llm, r) for caso, s, r in lote))
        for f in filas[-len(lote):]:
            print(f"[{f['caso']} #{f['repeticion']}] esperado {f['esperado']}, obtenido {f['estado']}, "
                  f"{f['total_cliente_ms']} ms", flush=True)
    return filas


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--llm", choices=["falso", "real"], default="falso")
    p.add_argument("--confirmo-datos-sinteticos", action="store_true",
                   help="Obligatoria con --llm real: confirma que los casos usan solo pacientes ficticios")
    p.add_argument("--casos", help="Ids de los casos separados por comas (por defecto, todos)")
    p.add_argument("--repeticiones", type=int, default=1)
    p.add_argument("--concurrentes", type=int, default=1, help="consultas a la vez (prueba los límites)")
    p.add_argument("--entorno", default="normal", help="etiqueta del perfil (normal, b2ms)")
    p.add_argument("--etiqueta", help="sufijo del informe")
    p.add_argument("--sin-calentar", action="store_true", help="la primera consulta se mide en frío")
    p.add_argument("--versiones-prompt", help="versiones del prompt a comparar, separadas por comas (p. ej. v1.1,v1.2); "
                                             "por defecto, la vigente")
    p.add_argument("--salida", type=Path, default=Path(os.environ.get("CDSS_DIR_MEDICIONES", "data/mediciones")))
    a = p.parse_args(argv)
    if a.repeticiones < 1 or a.concurrentes < 1:
        p.error("--repeticiones y --concurrentes deben ser 1 o más")
    if a.llm == "real":
        if not a.confirmo_datos_sinteticos:
            p.error("--llm real exige --confirmo-datos-sinteticos")
        if not os.environ.get("ANTHROPIC_API_KEY"):
            p.error("--llm real exige ANTHROPIC_API_KEY")
    from app.rag.generacion import VERSIONES_PROMPT
    versiones = a.versiones_prompt.split(",") if a.versiones_prompt else [None]
    desconocidas = [v for v in versiones if v is not None and v not in VERSIONES_PROMPT]
    if desconocidas:
        p.error(f"Versiones del prompt sin archivo: {', '.join(desconocidas)}")
    fecha_referencia, casos = cargar_casos()
    if a.casos:
        elegidos = set(a.casos.split(","))
        casos = [c for c in casos if c["id"] in elegidos]
    fuera_de_seed = [c["id"] for c in casos if c["dni"] not in DNIS_SEED]
    if fuera_de_seed:
        p.error(f"Casos con pacientes que no son de seed_demo: {', '.join(fuera_de_seed)}")

    from app.core.db import engines
    from app.rag.cliente_llm import ClienteFalso
    motores = engines()
    _, servicios, dominio = srv._modelos_por_defecto()
    entorno = srv.EntornoConsulta(motores["clinica"], motores["generacion"], servicios, dominio, ClienteFalso(),
                                  srv.limites_por_defecto(), fecha_referencia=fecha_referencia)
    calentamiento = "no" if a.sin_calentar else srv.calentar(entorno, llamar_llm=False)
    with motores["clinica"].connect() as c:
        usuario = c.execute(text("SELECT id_usuario::text FROM seguridad.usuario WHERE nombre_usuario = :u"),
                            {"u": USUARIO}).scalar_one()
        solicitudes = {}
        for caso in casos:
            id_paciente, id_tamizaje = _ids(c, caso)
            solicitudes[caso["id"]] = srv.SolicitudConsulta(
                id_paciente, usuario, caso["consulta"], id_tamizaje, bool(caso.get("confirma_tamizaje_no_vigente")))
    filas = []
    for version in versiones:
        propias = asyncio.run(_correr(casos, solicitudes, replace(entorno, version_prompt=version), a.llm,
                                      a.repeticiones, a.concurrentes))
        for f in propias:
            f["version_prompt"] = version or "vigente"
        filas += propias
    for f in filas:
        f["intentos"] = detalle_intentos(motores["generacion"], f["id_consulta"]) if f["id_consulta"] else []
    total = resumen(filas)
    comparacion = comparar_versiones(filas) if len(versiones) > 1 else None
    meta = {"llm": a.llm, "entorno": a.entorno, "fecha": time.strftime("%Y-%m-%d %H:%M:%S"),
            "repeticiones": a.repeticiones, "concurrentes": a.concurrentes, "nucleos": srv.nucleos_visibles(),
            "limites": repr(entorno.limites), "calentamiento": calentamiento,
            "versiones_prompt": [v or "vigente" for v in versiones]}
    a.salida.mkdir(parents=True, exist_ok=True)
    nombre = f"d_consulta_{a.llm}" + (f"_{a.etiqueta}" if a.etiqueta else "")
    (a.salida / f"{nombre}.md").write_text(informe_markdown(filas, total, meta, comparacion) + "\n", encoding="utf-8")
    (a.salida / f"{nombre}.json").write_text(json.dumps({"meta": meta, "resumen": total, "comparacion": comparacion,
                                                         "consultas": filas},
                                                        ensure_ascii=False, indent=2, default=str) + "\n",
                                             encoding="utf-8")
    print(json.dumps(comparacion or total, ensure_ascii=False, default=str))
    print(f"Informe: {a.salida / nombre}.md")
    return 0 if total["coinciden"] == total["consultas"] else 1


if __name__ == "__main__":
    sys.exit(main())
