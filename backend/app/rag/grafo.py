"""Parte D1 · Grafo de la consulta (LangGraph), Tabla 11 de la guía.

Ocho nodos, cada uno con su propia sesión de base de datos y el rol que le corresponde:

| Nodo       | Rol             | Qué hace                                                               |
| validar    | cdss_clinica    | filtro del texto libre y huellas, registro de la consulta, datos       |
|            |                 | mínimos, vigencia, alcance de edad y filtro de dominio                 |
| clasificar | cdss_clinica    | clasificación guardada o calculada (2.3)                               |
| normalizar | cdss_generacion | consulta de recuperación (estructurada + texto filtrado) y datos       |
|            |                 | clínicos de la lista blanca                                            |
| recuperar  | cdss_generacion | recuperación híbrida con la edad estructurada y la bonificación vigente |
| proteger   | cdss_generacion | solicitud mínima y control previo con las huellas                      |
| generar    | cdss_generacion | llamada al modelo de lenguaje                                          |
| verificar  | cdss_generacion | controles 6.1 a 6.3, decisión de la Tabla 10 y registro del intento    |
| salida     | cdss_clinica    | cierre de la consulta con su estado, intentos y tiempos, y auditoría   |

Transiciones: validar termina en DATOS_FALTANTES, TAMIZAJE_NO_VIGENTE o FUERA_DE_DOMINIO;
recuperar sin fragmentos sobre el umbral pasa directo a verificar (6.3 sin llamar al
modelo); proteger termina en SOLICITUD_BLOQUEADA si el control previo encuentra
identificadores; verificar vuelve a proteger (regenerar) o a recuperar (búsqueda
ampliada) una sola vez, o termina en VERIFICADA, EVIDENCIA_INSUFICIENTE o ERROR.

Datos de identidad: el estado del grafo solo lleva identificadores internos (UUID), el
texto filtrado, datos clínicos sin identidad y resultados. El texto original de la
consulta y las huellas HMAC viven en el Contexto, en memoria y fuera del estado: el texto
original solo lo usa validar y se borra al terminar ese nodo; las huellas las calcula
validar (que ya tiene la identidad descifrada con cdss_clinica) y proteger recibe solo
los digests. Ni el texto original ni las huellas se guardan, se registran ni se emiten.

Concurrencia: las llamadas al servicio modelos (filtro de dominio y recuperación) y a la
API del modelo de lenguaje pasan por semáforos (Limites). Si no hay turno, se emite un
evento «en_cola» y la espera se suma a los tiempos."""
import time
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import date
from functools import lru_cache
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from sqlalchemy import Connection, Engine

from app.rag import generacion as gen
from app.rag import registro
from app.rag import verificacion as ver
from app.rag.cliente_llm import ClienteLLM
from app.rag.consulta_estructurada import consulta_de_recuperacion
from app.rag.dominio import FiltroDominio
from app.rag.filtro_texto import HuellasPaciente, filtrar_texto, generar_huellas, idioma_respuesta, leer_identidad
from app.rag.normalizacion import normalizar as normalizar_consulta
from app.rag.parametros import ParametrosRecuperacion, leer_parametros, parametros_recuperacion
from app.rag.proteccion import construir_solicitud, controlar_identificadores, entidades_de_documentos, \
    leer_datos_clinicos
from app.rag.recuperacion import AMPLIADA, INICIAL, Servicios, comprobar_fragmentos, recuperar as recuperar_fragmentos
from app.rag.validacion import DATOS_FALTANTES, FUERA_DE_ALCANCE, TAMIZAJE_NO_VIGENTE, obtener_clasificacion, \
    validar_tamizaje
from app.services.registro_consulta import registrar_consulta, registrar_datos_faltantes

CLINICA = "cdss_clinica"
GENERACION = "cdss_generacion"
NODOS = ("validar", "clasificar", "normalizar", "recuperar", "proteger", "generar", "verificar", "salida")
ROL_POR_NODO = {"validar": CLINICA, "clasificar": CLINICA, "salida": CLINICA, "normalizar": GENERACION,
                "recuperar": GENERACION, "proteger": GENERACION, "generar": GENERACION, "verificar": GENERACION}

FUERA_DE_DOMINIO = "FUERA_DE_DOMINIO"
SOLICITUD_BLOQUEADA = "SOLICITUD_BLOQUEADA"
ESTADOS_FINALES = (ver.VERIFICADA, ver.EVIDENCIA_INSUFICIENTE, ver.ERROR, DATOS_FALTANTES, TAMIZAJE_NO_VIGENTE,
                   FUERA_DE_DOMINIO, SOLICITUD_BLOQUEADA)
MENSAJE_FUERA_DE_DOMINIO = ("La consulta está fuera del alcance del sistema: evaluación y manejo de la anemia en "
                            "niños de 0 a 59 meses.")
MENSAJE_BLOQUEADA = ("La solicitud no se envió porque contenía datos que identifican al paciente. Reformule la "
                     "consulta sin nombres, documentos ni números de contacto.")
MODELOS = "modelos"
LLM = "llm"
LARGO_INICIO_FRAGMENTO = 200


def mensaje_datos_faltantes(etiquetas: list[str]) -> str:
    return f"Faltan datos obligatorios del tamizaje: {', '.join(etiquetas)}. Complete el registro para continuar."


def mensaje_tamizaje_no_vigente(dias: int, vigencia: int) -> str:
    return (f"El tamizaje tiene {dias} días y supera el plazo de vigencia de {vigencia} días. Registre un tamizaje "
            "nuevo o confirme que desea continuar con el disponible.")


def _ms(inicio: float) -> int:
    return round((time.perf_counter() - inicio) * 1000)


class Limites:
    """Semáforos de las llamadas al servicio modelos y a la API del modelo de lenguaje."""

    def __init__(self, reranker: int, llm: int):
        self.reranker, self.llm = reranker, llm
        self._semaforos = {MODELOS: threading.BoundedSemaphore(reranker), LLM: threading.BoundedSemaphore(llm)}

    def semaforo(self, recurso: str) -> threading.BoundedSemaphore:
        return self._semaforos[recurso]

    def __repr__(self) -> str:
        return f"Limites(reranker={self.reranker}, llm={self.llm})"


@dataclass(eq=False)
class Contexto:
    """Lo que el grafo necesita y no forma parte de su estado: conexiones, servicios y,
    solo en memoria, el texto original de la consulta y las huellas del paciente."""
    clinica: Engine
    generacion: Engine
    servicios: Servicios
    dominio: FiltroDominio
    cliente: ClienteLLM
    limites: Limites
    emitir: Callable[[dict], None]
    inicio: float
    parametros: ParametrosRecuperacion | None = None
    fecha_referencia: date | None = None
    # Versión del prompt solo para las mediciones (medir_consulta --versiones-prompt); None usa VERSION_PROMPT.
    version_prompt: str | None = None
    texto_consulta: str | None = field(default=None, repr=False)
    huellas: HuellasPaciente | None = field(default=None, repr=False)
    id_consulta: str | None = None
    intentos_registrados: int = 0
    etapas: list[dict] = field(default_factory=list)
    esperas_ms: dict[str, int] = field(default_factory=lambda: {MODELOS: 0, LLM: 0})
    primer_evento_ms: int | None = None
    sesiones: list[tuple[str | None, str]] = field(default_factory=list)
    nodo_actual: str | None = None

    def __repr__(self) -> str:
        return f"Contexto(id_consulta={self.id_consulta}, <datos en memoria>)"

    def evento(self, evento: dict) -> None:
        transcurrido = _ms(self.inicio)
        if self.primer_evento_ms is None:
            self.primer_evento_ms = transcurrido
        self.emitir({**evento, "transcurrido_ms": transcurrido})


class Estado(TypedDict, total=False):
    id_consulta: str
    id_consulta_previa: str | None
    id_tamizaje: str
    id_paciente: str
    id_usuario: str
    confirma_tamizaje_no_vigente: bool
    texto_filtrado: str
    idioma: str
    validacion: dict
    clasificacion: dict | None
    parametros: ParametrosRecuperacion
    consulta: Any
    datos: Any
    numero_intento: int
    siguiente: str | None
    recuperacion: Any
    solicitud: Any
    control: Any
    config_generacion: Any
    generacion: Any
    tiempos_intento: dict
    intentos: list[dict]
    estado_final: str | None
    mensaje: str | None
    respuesta: dict | None
    citas: list[dict]
    tiempos_ms: dict


@contextmanager
def _sesion(ctx: Contexto, rol: str) -> Iterator[Connection]:
    ctx.sesiones.append((ctx.nodo_actual, rol))
    motor = ctx.clinica if rol == CLINICA else ctx.generacion
    with motor.begin() as c:
        yield c


@contextmanager
def _turno(ctx: Contexto, recurso: str) -> Iterator[dict]:
    """Turno en el semáforo del recurso; espera["ms"] es lo que esperó en cola."""
    semaforo, espera = ctx.limites.semaforo(recurso), {"ms": 0}
    if not semaforo.acquire(blocking=False):
        ctx.evento({"tipo": "en_cola", "etapa": ctx.nodo_actual, "recurso": recurso})
        inicio = time.perf_counter()
        semaforo.acquire()
        espera["ms"] = _ms(inicio)
        ctx.esperas_ms[recurso] += espera["ms"]
    try:
        yield espera
    finally:
        semaforo.release()


def _nodo(nombre: str, funcion: Callable[[Estado, Contexto], dict]) -> Callable:
    def envoltura(estado: Estado, runtime: Runtime[Contexto]) -> dict:
        ctx = runtime.context
        ctx.nodo_actual = nombre
        inicio = time.perf_counter()
        cambios = funcion(estado, ctx)
        resumen = cambios.pop("_evento", {})
        ms = _ms(inicio)
        intento = cambios.get("numero_intento", estado.get("numero_intento"))
        ctx.etapas.append({"nodo": nombre, "intento": intento, "ms": ms})
        ctx.evento({"tipo": "etapa", "etapa": nombre, "intento": intento, "ms": ms,
                    "id_consulta": ctx.id_consulta, **resumen})
        return cambios
    envoltura.__name__ = nombre
    return envoltura


def _tiempos_nuevos() -> dict:
    return {"recuperacion": None, "proteccion": None, "llamada_modelo": None, "verificacion": None,
            "espera_modelos": 0, "espera_llm": 0}


# ---------------------------------------------------------------------------
# Nodos
# ---------------------------------------------------------------------------
def validar(estado: Estado, ctx: Contexto) -> dict:
    id_tamizaje = estado["id_tamizaje"]
    confirma = bool(estado.get("confirma_tamizaje_no_vigente"))
    with _sesion(ctx, CLINICA) as c:
        identidad = leer_identidad(c, id_tamizaje)
        filtro = filtrar_texto(ctx.texto_consulta or "", identidad)
        ctx.huellas = generar_huellas(identidad) if identidad is not None else HuellasPaciente(frozenset())
        del identidad
        defecto = leer_parametros(c, ["IDIOMA_RESPUESTA_DEFECTO", "UMBRAL_DOMINIO"])
        idioma = idioma_respuesta(filtro.texto_filtrado, defecto["IDIOMA_RESPUESTA_DEFECTO"])
        ctx.id_consulta = registrar_consulta(c, id_tamizaje, estado["id_usuario"], ctx.texto_consulta or "",
                                             filtro.texto_filtrado, idioma, confirma, estado.get("id_consulta_previa"))
        ctx.texto_consulta = None
        v = validar_tamizaje(c, id_tamizaje, confirma, ctx.fecha_referencia, con_clasificacion=False)
        registrar_datos_faltantes(c, ctx.id_consulta, v.faltantes)
    validacion = {"estado": v.estado, "faltantes": [{"campo": f.campo, "etiqueta": f.etiqueta, "mensaje": f.mensaje}
                                                    for f in v.faltantes],
                  "dias_transcurridos": v.dias_transcurridos, "dias_vigencia": v.dias_vigencia,
                  "continua_con_tamizaje_no_vigente": v.continua_con_tamizaje_no_vigente}
    estado_final, mensaje = None, None
    if v.estado == DATOS_FALTANTES:
        estado_final, mensaje = DATOS_FALTANTES, mensaje_datos_faltantes([f.etiqueta for f in v.faltantes])
    elif v.estado == FUERA_DE_ALCANCE:
        estado_final, mensaje = FUERA_DE_DOMINIO, MENSAJE_FUERA_DE_DOMINIO
    elif v.estado == TAMIZAJE_NO_VIGENTE:
        estado_final, mensaje = TAMIZAJE_NO_VIGENTE, mensaje_tamizaje_no_vigente(v.dias_transcurridos,
                                                                                  v.dias_vigencia)
    else:
        # Fuera de la transacción: el filtro de dominio puede esperar turno en el servicio modelos.
        with _turno(ctx, MODELOS):
            dominio = ctx.dominio.evaluar(filtro.texto_filtrado, defecto["UMBRAL_DOMINIO"])
        if not dominio.dentro:
            estado_final, mensaje = FUERA_DE_DOMINIO, MENSAJE_FUERA_DE_DOMINIO
    return {"id_consulta": ctx.id_consulta, "texto_filtrado": filtro.texto_filtrado, "idioma": idioma,
            "validacion": validacion, "estado_final": estado_final, "mensaje": mensaje, "intentos": [],
            "_evento": {"resultado": estado_final or v.estado}}


def clasificar(estado: Estado, ctx: Contexto) -> dict:
    with _sesion(ctx, CLINICA) as c:
        r, motivo = obtener_clasificacion(c, estado["id_tamizaje"])
    clasificacion = None if r is None else {
        "categoria": r.categoria, "nivel_riesgo": r.nivel_riesgo, "hb_ajustada_g_dl": float(r.hb_ajustada_g_dl),
        "ajuste_hb_g_dl": float(r.ajuste_hb_g_dl), "altitud_msnm": r.altitud_msnm,
        "requiere_derivacion": r.requiere_derivacion, "calculada_ahora": r.calculada_ahora}
    return {"clasificacion": clasificacion,
            "_evento": {"resultado": r.categoria if r else "SIN_CLASIFICACION", "motivo": motivo}}


def normalizar(estado: Estado, ctx: Contexto) -> dict:
    with _sesion(ctx, GENERACION) as c:
        parametros = ctx.parametros or parametros_recuperacion(c)
        consulta = normalizar_consulta(consulta_de_recuperacion(c, estado["id_consulta"], estado["id_tamizaje"]))
        datos = leer_datos_clinicos(c, estado["id_tamizaje"])
    return {"parametros": parametros, "consulta": consulta, "datos": datos, "numero_intento": 1, "siguiente": None,
            "tiempos_intento": _tiempos_nuevos(),
            "_evento": {"terminos": len(consulta.terminos), "edad_meses": datos.edad_meses}}


def recuperar(estado: Estado, ctx: Contexto) -> dict:
    tipo = AMPLIADA if estado.get("siguiente") == ver.AMPLIADA else INICIAL
    tiempos = dict(estado["tiempos_intento"])
    inicio = time.perf_counter()
    with _turno(ctx, MODELOS) as espera, _sesion(ctx, GENERACION) as c:
        rec = recuperar_fragmentos(c, estado["consulta"], ctx.servicios, estado["parametros"], tipo,
                                   estado["datos"].edad_meses)
    tiempos["recuperacion"] = _ms(inicio) - espera["ms"]
    tiempos["espera_modelos"] += espera["ms"]
    return {"recuperacion": rec, "solicitud": None, "control": None, "generacion": None, "tiempos_intento": tiempos,
            "_evento": {"tipo_busqueda": rec.tipo_busqueda, "relevancia_maxima": _tres(rec.relevancia_maxima),
                        "suficiente": rec.suficiente, "seleccionados": len(rec.seleccionados)}}


def proteger(estado: Estado, ctx: Contexto) -> dict:
    if ctx.huellas is None:
        raise RuntimeError("Faltan las huellas del paciente para el control previo")
    rec, numero, tiempos = estado["recuperacion"], estado["numero_intento"], dict(estado["tiempos_intento"])
    inicio = time.perf_counter()
    with _sesion(ctx, GENERACION) as c:
        entidades = entidades_de_documentos(c, sorted({f.id_documento for f in rec.seleccionados}))
        texto = estado.get("texto_filtrado") or estado["consulta"].texto
        solicitud = construir_solicitud(estado["datos"], texto, estado["idioma"], rec.seleccionados, entidades)
        control = controlar_identificadores(solicitud.serializada, ctx.huellas)
        tiempos["proteccion"] = _ms(inicio)
        if control.aprobado:
            return {"solicitud": solicitud, "control": control, "tiempos_intento": tiempos,
                    "_evento": {"control_identificadores": True, "fragmentos": len(solicitud.etiquetas)}}
        decision = ver.decidir(numero, None, None, bloqueada=True)
        id_intento = registro.guardar_intento(c, estado["id_consulta"], numero, rec, decision.resultado_intento, None,
                                              solicitud, control, tiempos_ms=tiempos)
        registro.guardar_fragmentos(c, id_intento, rec, solicitud)
        registro.registrar_bloqueo(c, estado["id_consulta"], id_intento, control, solicitud.hash_sha256)
    ctx.intentos_registrados += 1
    intento = {**_busqueda(numero, rec, decision.resultado_intento), "control_identificadores": False,
               "tiempos_ms": tiempos, "motivos": [f"Solicitud bloqueada: {control.coincidencias} coincidencias"]}
    return {"solicitud": solicitud, "control": control, "tiempos_intento": tiempos,
            "intentos": [*estado.get("intentos", []), intento], "estado_final": SOLICITUD_BLOQUEADA,
            "mensaje": MENSAJE_BLOQUEADA, "_evento": {"control_identificadores": False}}


def generar(estado: Estado, ctx: Contexto) -> dict:
    with _sesion(ctx, GENERACION) as c:
        config = gen.configuracion_generacion(c)
    if ctx.version_prompt:
        if ctx.version_prompt not in gen.VERSIONES_PROMPT:
            raise ValueError(f"No hay prompt para la versión {ctx.version_prompt}")
        config = replace(config, version_prompt=ctx.version_prompt)
    tiempos = dict(estado["tiempos_intento"])
    inicio = time.perf_counter()
    with _turno(ctx, LLM) as espera:
        g = gen.generar(ctx.cliente, estado["solicitud"], config)
    tiempos["llamada_modelo"] = _ms(inicio) - espera["ms"]
    tiempos["espera_llm"] += espera["ms"]
    return {"config_generacion": config, "generacion": g, "tiempos_intento": tiempos,
            "_evento": {"generacion": g.estado, "stop_reason": g.fin}}


def _tres(valor: float | None) -> float | None:
    """Con 3 decimales, como se guarda en la base (NUMERIC(4,3)): el evento fin y el GET coinciden."""
    return None if valor is None else round(float(valor), 3)


def _busqueda(numero: int, rec, resultado: str) -> dict:
    """Datos de la búsqueda de un intento (M07: detalle de la búsqueda)."""
    return {"numero": numero, "tipo_busqueda": rec.tipo_busqueda, "candidatos_evaluados": rec.candidatos_evaluados,
            "relevancia_maxima": _tres(rec.relevancia_maxima), "umbral_relevancia": _tres(rec.umbral_relevancia),
            "resultado": resultado, "valida_citas": None, "valida_consistencia": None, "valida_evidencia": None}


def _fragmentos_enviados(solicitud) -> list[dict]:
    return [{"etiqueta": e, "documento": f.codigo_documento, "seccion": f.seccion,
             "puntaje_reranker": f.puntaje_reranker, "texto_inicio": f.texto[:LARGO_INICIO_FRAGMENTO]}
            for e, f in solicitud.etiquetas.items()]


def verificar(estado: Estado, ctx: Contexto) -> dict:
    rec, numero, tiempos = estado["recuperacion"], estado["numero_intento"], dict(estado["tiempos_intento"])
    g, solicitud, control = estado.get("generacion"), estado.get("solicitud"), estado.get("control")
    config = estado.get("config_generacion")
    cambios: dict = {}
    with _sesion(ctx, GENERACION) as c:
        if g is None:
            # 6.3 antes de llamar al modelo: ningún fragmento alcanza el umbral.
            decision = ver.decidir(numero, None, None)
            id_intento = registro.guardar_intento(c, estado["id_consulta"], numero, rec, decision.resultado_intento,
                                                  None, valida_evidencia=False, tiempos_ms=tiempos)
            registro.guardar_fragmentos(c, id_intento, rec, None)
            intento = {**_busqueda(numero, rec, decision.resultado_intento), "valida_evidencia": False,
                       "tiempos_ms": tiempos, "motivos": ["6.3: ningún fragmento alcanza el umbral (sin llamar al modelo)"]}
        else:
            inicio, v = time.perf_counter(), None
            if g.estado == gen.RESPUESTA:
                vigentes = set(comprobar_fragmentos(c, [f.id_fragmento for f in solicitud.etiquetas.values()]))
                v = ver.verificar(g.respuesta, solicitud, estado["datos"], rec.relevancia_maxima,
                                  rec.umbral_relevancia, vigentes)
            tiempos["verificacion"] = _ms(inicio)
            decision = ver.decidir(numero, g.estado, v)
            id_intento = registro.guardar_intento(c, estado["id_consulta"], numero, rec, decision.resultado_intento,
                                                  config.version_prompt, solicitud, control, g, v, tiempos_ms=tiempos)
            registro.guardar_fragmentos(c, id_intento, rec, solicitud)
            intento = {
                **_busqueda(numero, rec, decision.resultado_intento), "control_identificadores": True,
                "valida_citas": v.valida_citas if v else None, "valida_consistencia": v.valida_consistencia if v else None,
                "valida_evidencia": v.valida_evidencia if v else None,
                "hash_solicitud": solicitud.hash_sha256, "generacion": g.estado, "stop_reason": g.fin,
                "modelo": g.modelo, "version_prompt": config.version_prompt, "tokens_entrada": g.tokens_entrada,
                "tokens_salida": g.tokens_salida, "tokens_razonamiento": g.tokens_razonamiento,
                "costo_usd": None if g.costo_usd is None else float(g.costo_usd), "latencia_llm_ms": g.latencia_ms,
                "tiempos_ms": tiempos, "motivos": ([g.motivo] if g.motivo else []) + (v.motivos if v else []),
                "fragmentos_enviados": _fragmentos_enviados(solicitud)}
            if decision.estado_final == ver.VERIFICADA:
                registro.guardar_recomendacion(c, estado["id_consulta"], id_intento, g.respuesta, solicitud)
                cambios["respuesta"] = g.respuesta
                cambios["citas"] = [_cita(cita, solicitud) for cita in g.respuesta["citas"]]
    ctx.intentos_registrados += 1
    cambios["intentos"] = [*estado.get("intentos", []), intento]
    if decision.estado_final is not None:
        cambios.update(estado_final=decision.estado_final, mensaje=decision.mensaje)
    else:
        cambios.update(numero_intento=numero + 1, siguiente=decision.siguiente, tiempos_intento=_tiempos_nuevos())
    cambios["_evento"] = {"resultado": decision.resultado_intento, "siguiente": decision.siguiente,
                          "estado_final": decision.estado_final}
    return cambios


ETIQUETA_TRADUCCION = "Traducción de apoyo, no oficial"


def _cita(cita: dict, solicitud) -> dict:
    f = solicitud.etiquetas[cita["etiqueta"]]
    return {"etiqueta": cita["etiqueta"], "extracto": cita["extracto"], "extracto_traducido": cita["extracto_traducido"],
            "etiqueta_traduccion": ETIQUETA_TRADUCCION if cita["extracto_traducido"] else None,
            "puntaje_reranker": _tres(f.puntaje_reranker),
            "fuente": f.codigo_documento, "documento": f.documento, "seccion": f.seccion,
            "pagina_inicio": f.pagina_inicio, "pagina_fin": f.pagina_fin, "idioma": f.idioma}


def resumen_tiempos(ctx: Contexto, total_ms: int) -> dict:
    por_nodo: dict[str, int] = {}
    for e in ctx.etapas:
        por_nodo[e["nodo"]] = por_nodo.get(e["nodo"], 0) + e["ms"]
    return {"total_ms": total_ms, "primer_evento_ms": ctx.primer_evento_ms, "por_nodo": por_nodo,
            "etapas": list(ctx.etapas), "espera_ms": dict(ctx.esperas_ms)}


def salida(estado: Estado, ctx: Contexto) -> dict:
    estado_final = estado.get("estado_final") or ver.ERROR
    intentos = estado.get("intentos", [])
    with _sesion(ctx, CLINICA) as c:
        tiempos = resumen_tiempos(ctx, _ms(ctx.inicio))
        registro.cerrar_consulta_con_tiempos(c, estado["id_consulta"], estado_final, len(intentos),
                                             tiempos["total_ms"], tiempos)
        registro.registrar_cierre(c, estado["id_consulta"], estado_final, intentos)
    return {"estado_final": estado_final, "tiempos_ms": tiempos, "_evento": {"estado_final": estado_final}}


# ---------------------------------------------------------------------------
# Aristas
# ---------------------------------------------------------------------------
def _tras_validar(estado: Estado) -> str:
    return "salida" if estado.get("estado_final") else "clasificar"


def _tras_recuperar(estado: Estado) -> str:
    return "proteger" if estado["recuperacion"].suficiente else "verificar"


def _tras_proteger(estado: Estado) -> str:
    return "salida" if estado.get("estado_final") else "generar"


def _tras_verificar(estado: Estado) -> str:
    if estado.get("estado_final"):
        return "salida"
    return "recuperar" if estado.get("siguiente") == ver.AMPLIADA else "proteger"


@lru_cache
def grafo():
    g = StateGraph(Estado, context_schema=Contexto)
    for nombre, funcion in (("validar", validar), ("clasificar", clasificar), ("normalizar", normalizar),
                            ("recuperar", recuperar), ("proteger", proteger), ("generar", generar),
                            ("verificar", verificar), ("salida", salida)):
        g.add_node(nombre, _nodo(nombre, funcion))
    g.add_edge(START, "validar")
    g.add_conditional_edges("validar", _tras_validar, {"salida": "salida", "clasificar": "clasificar"})
    g.add_edge("clasificar", "normalizar")
    g.add_edge("normalizar", "recuperar")
    g.add_conditional_edges("recuperar", _tras_recuperar, {"proteger": "proteger", "verificar": "verificar"})
    g.add_conditional_edges("proteger", _tras_proteger, {"salida": "salida", "generar": "generar"})
    g.add_edge("generar", "verificar")
    g.add_conditional_edges("verificar", _tras_verificar,
                            {"salida": "salida", "recuperar": "recuperar", "proteger": "proteger"})
    g.add_edge("salida", END)
    return g.compile()


def ejecutar_grafo(entrada: Estado, ctx: Contexto) -> Estado:
    """Ejecuta el grafo de forma síncrona (el servicio lo llama en un hilo aparte)."""
    return grafo().invoke(entrada, context=ctx)
