"""Servicio de consultas clínicas (parte D1): ejecuta el grafo de app/rag/grafo.py y
emite un evento por etapa, para que la parte D2 los transmita por NDJSON.

ejecutar_consulta(solicitud) es un generador asíncrono:
- antes del primer evento, con cdss_clinica, comprueba que el tamizaje sea del paciente
  (por defecto toma el más reciente) y que la consulta previa, si se indica, sea del
  mismo tamizaje y haya terminado en TAMIZAJE_NO_VIGENTE; si no, lanza ErrorSolicitud;
- el grafo corre en un hilo aparte y cada nodo emite su evento («etapa», «en_cola»);
- termina con un evento «fin» (estado, mensaje, recomendación, citas y tiempos) o
  «error» (la consulta se cierra en ERROR con cdss_clinica).

Los eventos no llevan el texto original de la consulta, la identidad del paciente ni
las huellas. Los errores se registran solo con su tipo, sin mensajes que puedan llevar
datos (por ejemplo, los parámetros de una sentencia SQL).

Límites de concurrencia (config.py): MAX_CONCURRENCIA_RERANKER para el servicio modelos
(vacío: núcleos visibles divididos por los hilos que informa modelos, mínimo 1) y
MAX_CONCURRENCIA_LLM para la API. calentar() prepara los modelos, ChromaDB, el índice
BM25, el esquema y el prompt; llama a la API solo con CALENTAR_LLM=true y nunca en
pruebas."""
import asyncio
import logging
import os
import threading
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache

from sqlalchemy import Connection, Engine, text

from app.core.config import get_settings
from app.rag import generacion as gen
from app.rag.cliente_llm import ENTORNO_PRUEBAS, ClienteLLM, entorno_actual
from app.rag.dominio import FiltroDominio
from app.rag.grafo import Contexto, Limites, ejecutar_grafo, grafo, resumen_tiempos
from app.rag.parametros import ParametrosRecuperacion, parametros_recuperacion
from app.rag.proteccion import serializar
from app.rag.recuperacion import FILTRO_VECTORIAL, Servicios
from app.rag.registro import cerrar_consulta_con_tiempos
from app.rag.validacion import TAMIZAJE_NO_VIGENTE
from app.rag.verificacion import ERROR, MENSAJE_NO_EVALUADA

log = logging.getLogger(__name__)
_FIN = object()


class ErrorSolicitud(Exception):
    """La consulta no se puede iniciar (tamizaje de otro paciente, sin tamizaje, consulta previa inválida)."""


@dataclass(frozen=True)
class SolicitudConsulta:
    id_paciente: str
    id_usuario: str
    texto_consulta: str = field(repr=False)
    id_tamizaje: str | None = None
    confirma_tamizaje_no_vigente: bool = False
    id_consulta_previa: str | None = None


@dataclass
class EntornoConsulta:
    clinica: Engine
    generacion: Engine
    servicios: Servicios
    dominio: FiltroDominio
    cliente: ClienteLLM
    limites: Limites
    parametros: ParametrosRecuperacion | None = None
    fecha_referencia: date | None = None


# ---------------------------------------------------------------------------
# Límites de concurrencia y entorno por defecto
# ---------------------------------------------------------------------------
def nucleos_visibles() -> int:
    try:
        return len(os.sched_getaffinity(0))
    except AttributeError:
        return os.cpu_count() or 1


def concurrencia_reranker(configurada: int | None, hilos_modelos: int | None, nucleos: int | None = None) -> int:
    """La configurada o, si está vacía, núcleos visibles / hilos del servicio modelos (mínimo 1)."""
    if configurada:
        return configurada
    nucleos = nucleos or nucleos_visibles()
    return max(1, nucleos // max(1, hilos_modelos or nucleos))


@lru_cache
def _modelos_por_defecto():
    from app.core.modelos import ClienteModelos, EmbedderHttp, RerankerHttp
    from app.core.vectores import AlmacenChroma
    from app.rag.bm25 import CacheBM25
    s = get_settings()
    cliente = ClienteModelos(s.modelos_url, timeout_s=s.modelos_timeout_s)
    embedder = EmbedderHttp(cliente)
    return cliente, Servicios(embedder, RerankerHttp(cliente), AlmacenChroma(s.chroma_url), CacheBM25()), \
        FiltroDominio(embedder)


_limites: Limites | None = None
_limites_definitivos = False
_candado_limites = threading.Lock()


def limites_por_defecto() -> Limites:
    """Una sola instancia (los semáforos se comparten entre consultas). Con
    MAX_CONCURRENCIA_RERANKER vacío y el servicio modelos todavía sin responder (por
    ejemplo, al arrancar), usa 1 de forma provisional y lo recalcula en la siguiente
    llamada hasta que modelos informe sus hilos."""
    global _limites, _limites_definitivos
    with _candado_limites:
        if _limites is not None and _limites_definitivos:
            return _limites
        s = get_settings()
        if s.max_concurrencia_reranker is not None:
            _limites, _limites_definitivos = Limites(s.max_concurrencia_reranker, s.max_concurrencia_llm), True
            return _limites
        try:
            hilos = _modelos_por_defecto()[0].salud().get("hilos")
            _limites = Limites(concurrencia_reranker(None, hilos), s.max_concurrencia_llm)
            _limites_definitivos = True
        except Exception as e:  # noqa: BLE001 (sin el servicio, el mínimo provisional)
            if _limites is None:
                log.warning("El servicio modelos no informa sus hilos (%s); concurrencia 1 provisional",
                            type(e).__name__)
                _limites = Limites(1, s.max_concurrencia_llm)
        return _limites


class ClienteNoDisponible:
    """Sin ANTHROPIC_API_KEY (o en pruebas) el stack arranca igual: cada generación
    termina como error de la API y la consulta, en ERROR."""

    def __init__(self, motivo: str):
        self.motivo = motivo

    def generar(self, sistema, contenido, esquema, config):
        from app.rag.cliente_llm import ErrorAPI
        raise ErrorAPI(self.motivo)


@lru_cache
def _cliente_llm_por_defecto() -> ClienteLLM:
    from app.rag.cliente_llm import ClienteAnthropic, ErrorAPI, ErrorEntornoPruebas
    try:
        return ClienteAnthropic()
    except (ErrorAPI, ErrorEntornoPruebas) as e:
        log.warning("Cliente del modelo de lenguaje no disponible (%s)", type(e).__name__)
        return ClienteNoDisponible(str(e))


def entorno_por_defecto() -> EntornoConsulta:
    from app.core.db import engines
    _, servicios, dominio = _modelos_por_defecto()
    motores = engines()
    return EntornoConsulta(motores["clinica"], motores["generacion"], servicios, dominio, _cliente_llm_por_defecto(),
                           limites_por_defecto())


# ---------------------------------------------------------------------------
# Comprobación previa (cdss_clinica)
# ---------------------------------------------------------------------------
def resolver_tamizaje(c: Connection, solicitud: SolicitudConsulta) -> str:
    if solicitud.id_tamizaje:
        dueno = c.execute(text("SELECT id_paciente::text FROM clinico.tamizaje WHERE id_tamizaje = CAST(:t AS uuid)"),
                          {"t": solicitud.id_tamizaje}).scalar()
        if dueno is None or dueno != solicitud.id_paciente:
            raise ErrorSolicitud("El tamizaje no pertenece al paciente")
        return solicitud.id_tamizaje
    reciente = c.execute(text(
        """SELECT id_tamizaje::text FROM clinico.tamizaje WHERE id_paciente = CAST(:p AS uuid)
            ORDER BY fecha_tamizaje DESC, fecha_registro DESC LIMIT 1"""), {"p": solicitud.id_paciente}).scalar()
    if reciente is None:
        raise ErrorSolicitud("El paciente no tiene tamizajes registrados")
    return reciente


def comprobar_consulta_previa(c: Connection, id_consulta_previa: str, id_tamizaje: str) -> None:
    previa = c.execute(text("SELECT id_tamizaje::text, estado FROM asistencia.consulta "
                            "WHERE id_consulta = CAST(:c AS uuid)"), {"c": id_consulta_previa}).first()
    if previa is None or previa.id_tamizaje != id_tamizaje or previa.estado != TAMIZAJE_NO_VIGENTE:
        raise ErrorSolicitud("La consulta previa no corresponde a un tamizaje no vigente de este paciente")


def preparar(solicitud: SolicitudConsulta, entorno: EntornoConsulta) -> str:
    if not solicitud.texto_consulta or not solicitud.texto_consulta.strip():
        raise ErrorSolicitud("La consulta está vacía")
    with entorno.clinica.begin() as c:
        id_tamizaje = resolver_tamizaje(c, solicitud)
        if solicitud.id_consulta_previa:
            comprobar_consulta_previa(c, solicitud.id_consulta_previa, id_tamizaje)
    return id_tamizaje


# ---------------------------------------------------------------------------
# Ejecución
# ---------------------------------------------------------------------------
def _evento_fin(final: dict) -> dict:
    validacion = final.get("validacion") or {}
    respuesta = final.get("respuesta")
    return {
        "tipo": "fin", "id_consulta": final["id_consulta"], "id_paciente": final["id_paciente"],
        "estado": final["estado_final"], "mensaje": final.get("mensaje"),
        "datos_faltantes": [f["etiqueta"] for f in validacion.get("faltantes", [])],
        "vigencia": {"dias_transcurridos": validacion.get("dias_transcurridos"),
                     "dias_vigencia": validacion.get("dias_vigencia"),
                     "continua_con_tamizaje_no_vigente": validacion.get("continua_con_tamizaje_no_vigente")},
        "clasificacion": final.get("clasificacion"),
        "recomendacion": None if respuesta is None else {
            campo: respuesta.get(campo) for campo in ("resumen", "recomendacion", "advertencias",
                                                      "factores_identificados")},
        "citas": final.get("citas", []), "intentos": len(final.get("intentos", [])),
        "tiempos_ms": final.get("tiempos_ms"),
    }


def _cerrar_con_error(ctx: Contexto) -> None:
    try:
        with ctx.clinica.begin() as c:
            tiempos = resumen_tiempos(ctx, round((time.perf_counter() - ctx.inicio) * 1000))
            cerrar_consulta_con_tiempos(c, ctx.id_consulta, ERROR, ctx.intentos_registrados, tiempos["total_ms"],
                                        tiempos)
    except Exception as e:  # noqa: BLE001
        log.error("No se pudo cerrar en ERROR la consulta %s (%s)", ctx.id_consulta, type(e).__name__)


def ejecutar_en_hilo(solicitud: SolicitudConsulta, id_tamizaje: str, entorno: EntornoConsulta,
                     emitir: Callable[[dict], None], inicio: float) -> Contexto:
    """Ejecución síncrona del grafo; emite los eventos por emitir. Devuelve el contexto
    (para las pruebas y las mediciones), ya sin el texto original ni las huellas."""
    ctx = Contexto(entorno.clinica, entorno.generacion, entorno.servicios, entorno.dominio, entorno.cliente,
                   entorno.limites, emitir, inicio, parametros=entorno.parametros,
                   fecha_referencia=entorno.fecha_referencia, texto_consulta=solicitud.texto_consulta)
    entrada = {"id_tamizaje": id_tamizaje, "id_paciente": solicitud.id_paciente, "id_usuario": solicitud.id_usuario,
               "confirma_tamizaje_no_vigente": solicitud.confirma_tamizaje_no_vigente,
               "id_consulta_previa": solicitud.id_consulta_previa}
    try:
        ctx.evento(_evento_fin(ejecutar_grafo(entrada, ctx)))
    except Exception as e:  # noqa: BLE001 (cualquier falla cierra la consulta en ERROR)
        log.error("La consulta %s terminó en ERROR (%s)", ctx.id_consulta, type(e).__name__)
        if ctx.id_consulta:
            _cerrar_con_error(ctx)
        ctx.evento({"tipo": "error", "id_consulta": ctx.id_consulta, "id_paciente": solicitud.id_paciente,
                    "estado": ERROR, "mensaje": MENSAJE_NO_EVALUADA})
    finally:
        ctx.texto_consulta = None
        ctx.huellas = None
    return ctx


async def ejecutar_consulta(solicitud: SolicitudConsulta,
                            entorno: EntornoConsulta | None = None) -> AsyncIterator[dict]:
    """Generador asíncrono de eventos de una consulta. ErrorSolicitud sale antes del primer evento."""
    inicio = time.perf_counter()
    entorno = entorno or entorno_por_defecto()
    id_tamizaje = await asyncio.to_thread(preparar, solicitud, entorno)
    loop = asyncio.get_running_loop()
    cola: asyncio.Queue = asyncio.Queue()

    def emitir(evento: dict) -> None:
        loop.call_soon_threadsafe(cola.put_nowait, evento)

    def trabajo() -> None:
        try:
            ejecutar_en_hilo(solicitud, id_tamizaje, entorno, emitir, inicio)
        finally:
            loop.call_soon_threadsafe(cola.put_nowait, _FIN)

    tarea = loop.run_in_executor(None, trabajo)
    while (evento := await cola.get()) is not _FIN:
        yield evento
    await tarea


async def eventos_de(solicitud: SolicitudConsulta, entorno: EntornoConsulta | None = None) -> list[dict]:
    """Todos los eventos de una consulta (pruebas y mediciones)."""
    return [e async for e in ejecutar_consulta(solicitud, entorno)]


# ---------------------------------------------------------------------------
# Calentamiento
# ---------------------------------------------------------------------------
SOLICITUD_SINTETICA = {
    "version_solicitud": "1", "idioma_respuesta": "es",
    "consulta": "Solicitud sintética de calentamiento: indique evidencia insuficiente.",
    "paciente": {"edad_meses": 12, "sexo": "F", "altitud_msnm": 150, "hb_observada_g_dl": 11.5,
                 "hb_ajustada_g_dl": 11.5, "clasificacion": "SIN_ANEMIA", "nivel_riesgo": "BAJO",
                 "requiere_derivacion": False, "peso_kg": 9.5, "suplementacion_hierro": None,
                 "lactancia_materna_actual": None, "parasitosis_reciente": None, "bajo_peso_nacer": None,
                 "edad_gestacional": "NO_REGISTRADA", "sintomas": []},
    "tamizaje_anterior": None, "evidencia": [],
}


def calentar(entorno: EntornoConsulta | None = None, llamar_llm: bool | None = None) -> dict:
    """Prepara todo lo que la primera consulta haría en frío. Devuelve los tiempos (ms)."""
    tiempos: dict[str, int] = {}

    def medir(nombre: str, funcion: Callable):
        inicio = time.perf_counter()
        resultado = funcion()
        tiempos[nombre] = round((time.perf_counter() - inicio) * 1000)
        return resultado

    entorno = entorno or entorno_por_defecto()
    s = entorno.servicios
    vector = medir("embedding", lambda: s.embedder.embeber(["anemia por deficiencia de hierro"])[0])
    medir("reranker", lambda: s.reranker.puntuar("anemia", ["suplementación con hierro"], 256))
    medir("chromadb", lambda: s.almacen.consultar(vector, 1, FILTRO_VECTORIAL))
    medir("dominio", lambda: entorno.dominio.evaluar("anemia en niños", 0.0))
    with entorno.generacion.connect() as c:
        medir("bm25", lambda: s.cache_bm25.obtener(c))
        parametros_recuperacion(c)
        config = gen.configuracion_generacion(c)
    medir("esquema_y_prompt", lambda: (gen.cargar_esquema(), gen.cargar_prompt(config.version_prompt)))
    medir("grafo", grafo)
    llamar = get_settings().calentar_llm if llamar_llm is None else llamar_llm
    if llamar and entorno_actual() != ENTORNO_PRUEBAS:
        medir("llm", lambda: entorno.cliente.generar(gen.cargar_prompt(config.version_prompt),
                                                     serializar(SOLICITUD_SINTETICA), gen.cargar_esquema(),
                                                     config.llm))
    tiempos["limites"] = {"reranker": entorno.limites.reranker, "llm": entorno.limites.llm}
    return tiempos
