"""Prueba de punta a punta de las partes B y C, sin el grafo de LangGraph (llega en D).

Encadena en secuencia, con la sesión que corresponde a cada componente:
- cdss_clinica: identidad del paciente, filtro del texto libre y huellas, registro de
  la consulta con texto_filtrado e idioma_respuesta, validación, clasificación y
  filtro de dominio;
- cdss_generacion: recuperación, protección (solicitud mínima y control previo),
  generación, verificación y registro de cada intento, con un único reintento.

Los casos están en casos_e2e.yaml y usan solo pacientes ficticios de seed_demo: el
script rechaza un caso cuyo DNI no esté en seed_demo. Por defecto usa el cliente falso
del modelo de lenguaje; con --llm real llama a la API de Anthropic y exige
ANTHROPIC_API_KEY y --confirmo-datos-sinteticos.

Uso (en el contenedor backend, con la red de Docker; ver docs/mediciones_sprint2.md):
    python -m app.scripts.prueba_punta_a_punta [--llm falso|real] [--confirmo-datos-sinteticos]
        [--casos a,b,i] [--salida data/mediciones]

Guarda el informe en <salida>/c_punta_a_punta_<llm>.md y .json (con --casos, en
c_punta_a_punta_<llm>_<casos>). Por cada intento con llamada al modelo registra el
stop_reason, los tokens que informa la API (entrada, salida y razonamiento), los
fragmentos enviados (etiqueta, documento, sección y comienzo del texto), lo que respondió
el modelo y los tiempos por etapa. Todo es sintético; no guarda la clave ni cabeceras."""
import argparse
import json
import os
import sys
import time
from dataclasses import dataclass, field, replace
from datetime import date
from pathlib import Path

import yaml
from sqlalchemy import Engine, create_engine, text

from app.core.seguridad import hmac_identificador
from app.rag import generacion as gen
from app.rag import registro
from app.rag import verificacion as ver
from app.rag.cliente_llm import ClienteAnthropic, ClienteFalso, ClienteLLM
from app.rag.consulta_estructurada import consulta_de_recuperacion
from app.rag.dominio import FiltroDominio
from app.rag.filtro_texto import HuellasPaciente, filtrar_texto, generar_huellas, idioma_respuesta, leer_identidad
from app.rag.normalizacion import normalizar
from app.rag.parametros import ParametrosRecuperacion, leer_parametros, parametros_recuperacion
from app.rag.proteccion import construir_solicitud, controlar_identificadores, entidades_de_documentos, \
    leer_datos_clinicos
from app.rag.recuperacion import AMPLIADA, INICIAL, Servicios, comprobar_fragmentos, leer_texto_filtrado, recuperar
from app.rag.validacion import DATOS_FALTANTES, FUERA_DE_ALCANCE, TAMIZAJE_NO_VIGENTE, validar_tamizaje
from app.scripts.seed_demo import PACIENTES

CASOS = Path(__file__).with_name("casos_e2e.yaml")
USUARIO = "med.salazar"
FUERA_DE_DOMINIO = "FUERA_DE_DOMINIO"
EN_PROCESO = "EN_PROCESO"
DNIS_SEED = frozenset(p[1] for p in PACIENTES)


class ErrorCaso(Exception):
    """El caso no se puede ejecutar (paciente fuera de seed_demo o tamizaje inexistente)."""


@dataclass
class Entorno:
    clinica: Engine
    generacion: Engine
    servicios: Servicios
    dominio: FiltroDominio
    fecha_referencia: date
    parametros: ParametrosRecuperacion | None = None


@dataclass
class ResultadoCaso:
    id: str
    descripcion: str
    esperado: str
    estado: str
    id_consulta: str | None = None
    texto_filtrado: str | None = None
    idioma_respuesta: str | None = None
    mensaje: str | None = None
    intentos: list[dict] = field(default_factory=list)
    citas: list[dict] = field(default_factory=list)
    latencia_total_ms: int = 0

    @property
    def coincide(self) -> bool:
        return self.estado == self.esperado


def cargar_casos(ruta: Path = CASOS) -> tuple[date, list[dict]]:
    datos = yaml.safe_load(ruta.read_text(encoding="utf-8"))
    return datos["fecha_referencia"], datos["casos"]


def _tamizaje(c, dni: str, fecha: date) -> str:
    if dni not in DNIS_SEED:
        raise ErrorCaso("El DNI no corresponde a un paciente ficticio de seed_demo")
    fila = c.execute(text(
        """SELECT t.id_tamizaje::text FROM clinico.tamizaje t
             JOIN clinico.paciente_identidad i ON i.id_paciente = t.id_paciente
            WHERE i.dni_hash = :h AND t.fecha_tamizaje = :f"""), {"h": hmac_identificador(dni), "f": fecha}).scalar()
    if fila is None:
        raise ErrorCaso("No existe el tamizaje del caso (ejecute seed_demo)")
    return fila


def _ms(inicio: float) -> int:
    return round((time.perf_counter() - inicio) * 1000)


LARGO_INICIO_FRAGMENTO = 200
LARGO_RESPUESTA_CRUDA = 3000


def fragmentos_enviados(solicitud) -> list[dict]:
    """Fragmentos de la solicitud para el informe (datos sintéticos de las guías)."""
    return [{"etiqueta": e, "documento": f.codigo_documento, "seccion": f.seccion,
             "puntaje_reranker": f.puntaje_reranker, "texto_inicio": f.texto[:LARGO_INICIO_FRAGMENTO]}
            for e, f in solicitud.etiquetas.items()]


def respuesta_modelo(g: gen.ResultadoGeneracion) -> dict | None:
    """Lo que respondió el modelo; si no se pudo interpretar (por ejemplo, cortada por
    max_tokens), el comienzo del texto tal como llegó."""
    if g.respuesta is not None:
        return {campo: g.respuesta[campo] for campo in
                ("evidencia_suficiente", "resumen", "advertencias", "recomendacion", "citas")}
    if g.texto:
        return {"texto_sin_interpretar": g.texto[:LARGO_RESPUESTA_CRUDA], "largo_caracteres": len(g.texto)}
    return None


def _estado_consulta(c, id_consulta: str, estado: str) -> None:
    c.execute(text("UPDATE asistencia.consulta SET estado = :e, fecha_hora_fin = now() WHERE id_consulta = CAST(:c AS uuid)"),
              {"e": estado, "c": id_consulta})


def etapa_clinica(entorno: Entorno, caso: dict) -> tuple[ResultadoCaso, str, HuellasPaciente]:
    """Con cdss_clinica: filtro, registro de la consulta, validación y dominio."""
    r = ResultadoCaso(caso["id"], caso["descripcion"], caso["esperado"], EN_PROCESO)
    with entorno.clinica.begin() as c:
        id_tamizaje = _tamizaje(c, caso["dni"], caso["fecha_tamizaje"])
        identidad = leer_identidad(c, id_tamizaje)
        filtro = filtrar_texto(caso["consulta"], identidad)
        huellas = generar_huellas(identidad) if identidad is not None else HuellasPaciente(frozenset())
        defecto = leer_parametros(c, ["IDIOMA_RESPUESTA_DEFECTO"])["IDIOMA_RESPUESTA_DEFECTO"]
        idioma = idioma_respuesta(filtro.texto_filtrado, defecto)
        confirma = bool(caso.get("confirma_tamizaje_no_vigente"))
        id_usuario = c.execute(text("SELECT id_usuario::text FROM seguridad.usuario WHERE nombre_usuario = :u"),
                               {"u": USUARIO}).scalar_one()
        r.id_consulta = c.execute(text(
            """INSERT INTO asistencia.consulta (id_tamizaje, id_usuario, texto_consulta, texto_filtrado,
                                                idioma_respuesta, confirma_tamizaje_no_vigente)
               VALUES (CAST(:t AS uuid), CAST(:u AS uuid), :tc, :tf, :i, :conf) RETURNING id_consulta::text"""),
            {"t": id_tamizaje, "u": id_usuario, "tc": caso["consulta"], "tf": filtro.texto_filtrado, "i": idioma,
             "conf": confirma}).scalar_one()
        r.texto_filtrado, r.idioma_respuesta = filtro.texto_filtrado, idioma

        validacion = validar_tamizaje(c, id_tamizaje, confirma, entorno.fecha_referencia)
        if validacion.estado == DATOS_FALTANTES:
            for f in validacion.faltantes:
                c.execute(text("INSERT INTO asistencia.dato_faltante (id_consulta, campo, mensaje) "
                               "VALUES (CAST(:c AS uuid), :campo, :m)"), {"c": r.id_consulta, "campo": f.campo,
                                                                          "m": f.mensaje})
            r.estado = DATOS_FALTANTES
        elif validacion.estado == FUERA_DE_ALCANCE:
            r.estado = FUERA_DE_DOMINIO
        elif validacion.estado == TAMIZAJE_NO_VIGENTE:
            r.estado = TAMIZAJE_NO_VIGENTE
        else:
            umbral = leer_parametros(c, ["UMBRAL_DOMINIO"])["UMBRAL_DOMINIO"]
            if not entorno.dominio.evaluar(filtro.texto_filtrado, umbral).dentro:
                r.estado = FUERA_DE_DOMINIO
        if r.estado in (DATOS_FALTANTES, FUERA_DE_DOMINIO):
            _estado_consulta(c, r.id_consulta, r.estado)
    return r, id_tamizaje, huellas


def etapa_generacion(entorno: Entorno, r: ResultadoCaso, id_tamizaje: str, huellas: HuellasPaciente,
                     cliente: ClienteLLM) -> ResultadoCaso:
    """Con cdss_generacion: recuperación, protección, generación y verificación."""
    inicio = time.perf_counter()
    with entorno.generacion.begin() as c:
        parametros = entorno.parametros or parametros_recuperacion(c)
        config = gen.configuracion_generacion(c)
        # La recuperación usa la consulta estructurada más el texto filtrado; al modelo se le
        # envía como consulta solo la pregunta filtrada del profesional.
        consulta = normalizar(consulta_de_recuperacion(c, r.id_consulta, id_tamizaje))
        texto = leer_texto_filtrado(c, r.id_consulta) or consulta.texto
        datos = leer_datos_clinicos(c, id_tamizaje)
        idioma = c.execute(text("SELECT idioma_respuesta FROM asistencia.consulta WHERE id_consulta = CAST(:c AS uuid)"),
                           {"c": r.id_consulta}).scalar_one()
        rec, siguiente, decision, numero = None, None, None, 0
        for numero in (1, 2):
            tiempos: dict[str, int | None] = {"recuperacion": None, "proteccion": None, "llamada_modelo": None,
                                              "verificacion": None}
            if rec is None or siguiente == ver.AMPLIADA:
                t0 = time.perf_counter()
                rec = recuperar(c, consulta, entorno.servicios, parametros, AMPLIADA if numero == 2 else INICIAL,
                                datos.edad_meses)
                tiempos["recuperacion"] = _ms(t0)
            intento = {"numero": numero, "tipo_busqueda": rec.tipo_busqueda, "relevancia_maxima": rec.relevancia_maxima,
                       "tiempos_ms": tiempos}
            if not rec.suficiente:
                decision = ver.decidir(numero, None, None)
                id_intento = registro.guardar_intento(c, r.id_consulta, numero, rec, decision.resultado_intento,
                                                      config.version_prompt, valida_evidencia=False)
                registro.guardar_fragmentos(c, id_intento, rec, None)
                r.intentos.append({**intento, "resultado": decision.resultado_intento,
                                   "motivos": ["6.3: ningún fragmento alcanza el umbral (sin llamar al modelo)"]})
            else:
                t0 = time.perf_counter()
                entidades = entidades_de_documentos(c, sorted({f.id_documento for f in rec.seleccionados}))
                solicitud = construir_solicitud(datos, texto, idioma, rec.seleccionados, entidades)
                control = controlar_identificadores(solicitud.serializada, huellas)
                tiempos["proteccion"] = _ms(t0)
                if not control.aprobado:
                    decision = ver.decidir(numero, None, None, bloqueada=True)
                    id_intento = registro.guardar_intento(c, r.id_consulta, numero, rec, decision.resultado_intento,
                                                          config.version_prompt, solicitud, control)
                    registro.guardar_fragmentos(c, id_intento, rec, solicitud)
                    registro.registrar_bloqueo(c, r.id_consulta, id_intento, control, solicitud.hash_sha256)
                    r.intentos.append({**intento, "resultado": decision.resultado_intento, "control_identificadores":
                                       False, "motivos": [f"Solicitud bloqueada: {control.coincidencias} coincidencias"]})
                else:
                    t0 = time.perf_counter()
                    g = gen.generar(cliente, solicitud, config)
                    tiempos["llamada_modelo"] = _ms(t0)
                    v = None
                    if g.estado == gen.RESPUESTA:
                        t0 = time.perf_counter()
                        vigentes = set(comprobar_fragmentos(c, [f.id_fragmento for f in solicitud.etiquetas.values()]))
                        v = ver.verificar(g.respuesta, solicitud, datos, rec.relevancia_maxima, rec.umbral_relevancia,
                                          vigentes)
                        tiempos["verificacion"] = _ms(t0)
                    decision = ver.decidir(numero, g.estado, v)
                    id_intento = registro.guardar_intento(c, r.id_consulta, numero, rec, decision.resultado_intento,
                                                          config.version_prompt, solicitud, control, g, v)
                    registro.guardar_fragmentos(c, id_intento, rec, solicitud)
                    r.intentos.append({
                        **intento, "resultado": decision.resultado_intento, "control_identificadores": True,
                        "hash_solicitud": solicitud.hash_sha256, "generacion": g.estado, "stop_reason": g.fin,
                        "modelo": g.modelo, "version_prompt": config.version_prompt,
                        "max_tokens": config.llm.max_tokens, "tokens_entrada": g.tokens_entrada,
                        "tokens_salida": g.tokens_salida, "tokens_razonamiento": g.tokens_razonamiento,
                        "costo_usd": g.costo_usd, "latencia_llm_ms": g.latencia_ms,
                        "motivos": ([g.motivo] if g.motivo else []) + (v.motivos if v else []),
                        "fragmentos_enviados": fragmentos_enviados(solicitud), "respuesta_modelo": respuesta_modelo(g),
                    })
                    if decision.estado_final == ver.VERIFICADA:
                        registro.guardar_recomendacion(c, r.id_consulta, id_intento, g.respuesta, solicitud)
                        r.citas = [{**cita, "fuente": solicitud.etiquetas[cita["etiqueta"]].codigo_documento,
                                    "idioma": solicitud.etiquetas[cita["etiqueta"]].idioma}
                                   for cita in g.respuesta["citas"]]
            siguiente = decision.siguiente
            if decision.estado_final is not None:
                break
        r.estado, r.mensaje = decision.estado_final, decision.mensaje
        r.latencia_total_ms = round((time.perf_counter() - inicio) * 1000)
        registro.cerrar_consulta(c, r.id_consulta, r.estado, numero, r.latencia_total_ms)
        registro.registrar_cierre(c, r.id_consulta, r.estado, r.intentos)
    return r


def ejecutar_caso(entorno: Entorno, caso: dict, cliente: ClienteLLM) -> ResultadoCaso:
    r, id_tamizaje, huellas = etapa_clinica(entorno, caso)
    if r.estado != EN_PROCESO:
        return r
    return etapa_generacion(entorno, r, id_tamizaje, huellas, cliente)


def cliente_para(caso: dict, llm: str) -> ClienteLLM:
    if llm == "real":
        return ClienteAnthropic()
    falso = caso.get("falso") or {}
    return ClienteFalso(modos=list(falso.get("modos", ["aprobada"])), preferir_ingles=bool(falso.get("preferir_ingles")))


def resumen(resultados: list[ResultadoCaso]) -> dict:
    intentos = [i for r in resultados for i in r.intentos]
    enviados = [i for i in intentos if i.get("generacion")]
    tokens_e = sum(i["tokens_entrada"] or 0 for i in enviados)
    tokens_s = sum(i["tokens_salida"] or 0 for i in enviados)
    costo = sum(float(i["costo_usd"] or 0) for i in enviados)
    return {
        "casos": len(resultados), "coinciden": sum(r.coincide for r in resultados),
        "intentos_enviados": len(enviados),
        "todos_con_control_identificadores": all(i.get("control_identificadores") for i in enviados),
        "tokens_entrada": tokens_e, "tokens_salida": tokens_s,
        "tokens_razonamiento": sum(i["tokens_razonamiento"] or 0 for i in enviados),
        "costo_usd": round(costo, 5), "costo_medio_por_consulta_usd":
            round(costo / max(1, len({r.id for r in resultados if any(i.get("generacion") for i in r.intentos)})), 5),
    }


def _una_linea(texto: str) -> str:
    return " ".join(str(texto).split())


def _detalle_intento(i: dict) -> list[str]:
    """Detalle de un intento con llamada al modelo para el informe Markdown."""
    t = i.get("tiempos_ms") or {}
    lineas = [f"  - Tiempos (ms): recuperación {t.get('recuperacion')}, protección {t.get('proteccion')}, "
              f"llamada al modelo {t.get('llamada_modelo')}, verificación {t.get('verificacion')}"]
    if not i.get("generacion"):
        return lineas
    lineas.append(f"  - stop_reason {i['stop_reason']}; tokens: entrada {i['tokens_entrada']}, salida "
                  f"{i['tokens_salida']} (máximo {i['max_tokens']}), razonamiento {i['tokens_razonamiento']}; "
                  f"prompt {i['version_prompt']}")
    for f in i["fragmentos_enviados"]:
        lineas.append(f"  - {f['etiqueta']} ({f['documento']}, reranker {f['puntaje_reranker']}) "
                      f"{_una_linea(f['seccion'] or 'sin sección')}: «{_una_linea(f['texto_inicio'])}»")
    m = i.get("respuesta_modelo")
    if m is None:
        lineas.append("  - Respuesta del modelo: ninguna")
    elif "texto_sin_interpretar" in m:
        lineas.append(f"  - Respuesta sin interpretar ({m['largo_caracteres']} caracteres): "
                      f"«{_una_linea(m['texto_sin_interpretar'])}»")
    else:
        lineas.append(f"  - evidencia_suficiente: {m['evidencia_suficiente']}; resumen: «{_una_linea(m['resumen'])}»")
        for a in m["advertencias"]:
            lineas.append(f"  - Advertencia: «{_una_linea(a)}»")
        for p in m["recomendacion"]:
            lineas.append(f"  - Paso {p['tipo']} [{', '.join(p['citas'])}]: «{_una_linea(p['texto'])}»")
    return lineas


def informe_markdown(resultados: list[ResultadoCaso], llm: str, total: dict) -> str:
    lineas = [f"# Prueba de punta a punta (cliente {llm})", "",
              f"Casos que coinciden con lo esperado: {total['coinciden']} de {total['casos']}. "
              f"Intentos enviados al modelo: {total['intentos_enviados']}, todos con control_identificadores = "
              f"{'true' if total['todos_con_control_identificadores'] else 'false (revisar)'}.",
              f"Tokens: {total['tokens_entrada']} de entrada, {total['tokens_salida']} de salida "
              f"({total['tokens_razonamiento']} de razonamiento). Costo total {total['costo_usd']} USD, "
              f"{total['costo_medio_por_consulta_usd']} USD por consulta enviada."
              + (" Con el cliente falso los tokens y el costo son simulados." if llm == "falso" else ""), "",
              "| Caso | Descripción | Esperado | Obtenido | Intentos | Latencia (ms) |",
              "| --- | --- | --- | --- | --- | --- |"]
    for r in resultados:
        intentos = "; ".join(f"{i['numero']} {i['tipo_busqueda']} {i['resultado']}" for i in r.intentos) or "sin intentos"
        marca = r.estado if r.coincide else f"**{r.estado}**"
        lineas.append(f"| {r.id} | {r.descripcion} | {r.esperado} | {marca} | {intentos} | {r.latencia_total_ms} |")
    lineas += ["", "## Detalle", ""]
    for r in resultados:
        lineas.append(f"### Caso {r.id}: {r.descripcion}")
        lineas.append(f"- Texto filtrado: {r.texto_filtrado}")
        lineas.append(f"- Idioma de la respuesta: {r.idioma_respuesta}")
        if r.mensaje:
            lineas.append(f"- Mensaje al profesional: {r.mensaje}")
        for i in r.intentos:
            motivos = "; ".join(i.get("motivos") or []) or "ninguno"
            lineas.append(f"- Intento {i['numero']} ({i['tipo_busqueda']}, relevancia máxima "
                          f"{i['relevancia_maxima']}): {i['resultado']}; motivos: {motivos}")
            lineas += _detalle_intento(i)
        for cita in r.citas:
            lineas.append(f"- Cita {cita['etiqueta']} ({cita['fuente']}, {cita['idioma']}): «{cita['extracto']}»"
                          + (f"; traducción de apoyo, no oficial: «{cita['extracto_traducido']}»"
                             if cita.get("extracto_traducido") else ""))
        lineas.append("")
    return "\n".join(lineas)


def _entorno_real(fecha_referencia: date) -> Entorno:
    from app.core.config import get_settings
    from app.core.modelos import ClienteModelos, EmbedderHttp, RerankerHttp
    from app.core.vectores import AlmacenChroma
    from app.rag.bm25 import CacheBM25

    s = get_settings()
    modelos = ClienteModelos(s.modelos_url, timeout_s=s.modelos_timeout_s)
    embedder = EmbedderHttp(modelos)
    servicios = Servicios(embedder, RerankerHttp(modelos), AlmacenChroma(s.chroma_url), CacheBM25())
    return Entorno(create_engine(s.database_url_clinica), create_engine(s.database_url_generacion), servicios,
                   FiltroDominio(embedder), fecha_referencia)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--llm", choices=["falso", "real"], default="falso")
    p.add_argument("--confirmo-datos-sinteticos", action="store_true",
                   help="Obligatoria con --llm real: confirma que los casos usan solo pacientes ficticios")
    p.add_argument("--casos", help="Ids de los casos separados por comas (por defecto, todos)")
    p.add_argument("--salida", type=Path, default=Path(os.environ.get("CDSS_DIR_MEDICIONES", "data/mediciones")))
    p.add_argument("--bonificacion-edad", type=float,
                   help="Peso de la edad en la fusión solo para esta corrida (en memoria; no cambia parametro_sistema)")
    p.add_argument("--etiqueta", help="Sufijo del informe, para no reemplazar el de otra corrida (por ejemplo v5_b0.3)")
    a = p.parse_args(argv)
    if a.bonificacion_edad is not None and not 0 <= a.bonificacion_edad <= 1:
        p.error("--bonificacion-edad debe estar entre 0 y 1")
    if a.llm == "real":
        if not a.confirmo_datos_sinteticos:
            p.error("--llm real exige --confirmo-datos-sinteticos")
        if not os.environ.get("ANTHROPIC_API_KEY"):
            p.error("--llm real exige ANTHROPIC_API_KEY")
    fecha_referencia, casos = cargar_casos()
    if a.casos:
        elegidos = set(a.casos.split(","))
        casos = [c for c in casos if c["id"] in elegidos]
    fuera_de_seed = [c["id"] for c in casos if c["dni"] not in DNIS_SEED]
    if fuera_de_seed:
        p.error(f"Casos con pacientes que no son de seed_demo: {', '.join(fuera_de_seed)}")

    entorno = _entorno_real(fecha_referencia)
    if a.bonificacion_edad is not None:
        with entorno.generacion.connect() as c:
            entorno.parametros = replace(parametros_recuperacion(c), bonificacion_edad=a.bonificacion_edad)
    resultados = []
    for caso in casos:
        r = ejecutar_caso(entorno, caso, cliente_para(caso, a.llm))
        print(f"[{r.id}] esperado {r.esperado}, obtenido {r.estado}", flush=True)
        resultados.append(r)
    total = resumen(resultados)
    a.salida.mkdir(parents=True, exist_ok=True)
    # Con --casos, un informe aparte para no reemplazar el de la corrida completa.
    sufijo = "_" + "-".join(c["id"] for c in casos) if a.casos else ""
    sufijo += f"_{a.etiqueta}" if a.etiqueta else ""
    # Sin with_suffix: una etiqueta como «v5_b0.7» tiene un punto que no es una extensión.
    nombre = f"c_punta_a_punta_{a.llm}{sufijo}"
    informe_md, informe_json = a.salida / f"{nombre}.md", a.salida / f"{nombre}.json"
    informe_md.write_text(informe_markdown(resultados, a.llm, total) + "\n", encoding="utf-8")
    informe_json.write_text(json.dumps({"resumen": total, "casos": [r.__dict__ for r in resultados]},
                                       ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps(total, ensure_ascii=False))
    print(f"Informe: {informe_md}")
    return 0 if total["coinciden"] == total["casos"] else 1


if __name__ == "__main__":
    sys.exit(main())
