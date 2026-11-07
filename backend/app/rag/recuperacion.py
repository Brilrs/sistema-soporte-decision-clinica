"""Capa 3 · Recuperación híbrida.

1. BM25 (CANDIDATOS_BUSQUEDA) y búsqueda vectorial en ChromaDB con el mismo número de
   candidatos, filtrando nivel 1, documento VIGENTE y fragmento vigente.
2. Fusión Reciprocal Rank Fusion: puntaje = suma de 1 / (RRF_K + posición), con la
   posición contada desde 1 en cada lista.
3. Comprobación contra PostgreSQL de los candidatos fusionados (vigente, documento
   VIGENTE, nivel 1 y última versión); de allí sale además el texto.
4. Reranker sobre los CANDIDATOS_RERANKER mejores de la fusión, con pares de hasta
   MAX_LONGITUD_RERANKER tokens.
5. Selección de los FRAGMENTOS_ENVIADOS mejores que alcanzan UMBRAL_RELEVANCIA. Si
   ninguno lo alcanza, búsqueda ampliada: CANDIDATOS_BUSQUEDA_AMPLIADA por método y
   la consulta con los sinónimos y equivalentes en inglés del diccionario.
6. Antes de devolver, los candidatos evaluados se vuelven a comprobar contra
   PostgreSQL y se descartan los que dejaron de ser recuperables mientras tanto.

La consulta que recibe esta capa es el texto filtrado (asistencia.consulta.texto_filtrado)
o una consulta construida con datos estructurados; nunca texto_consulta. La
persistencia en asistencia.fragmento_recuperado corresponde al orquestador."""
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from sqlalchemy import Connection, text
from sqlalchemy.orm import Session

from app.core.modelos import Embedder, Reranker
from app.core.vectores import AlmacenVectorial
from app.rag.bm25 import CONDICION_RECUPERABLE, CacheBM25, terminos_consulta
from app.rag.normalizacion import ConsultaNormalizada
from app.rag.parametros import ParametrosRecuperacion

INICIAL = "INICIAL"
AMPLIADA = "AMPLIADA"
FILTRO_VECTORIAL = {"nivel": 1, "estado_documento": "VIGENTE", "vigente": True}

_FRAGMENTOS = f"""
    SELECT f.id_fragmento::text AS id_fragmento, f.id_documento::text AS id_documento, d.titulo,
           d.codigo_documento, d.idioma, f.seccion, f.pagina_inicio, f.pagina_fin, f.texto, f.tipo_contenido
      FROM conocimiento.fragmento f
      JOIN conocimiento.documento_fuente d ON d.id_documento = f.id_documento
     WHERE f.id_fragmento = ANY(CAST(:ids AS uuid[])) AND {CONDICION_RECUPERABLE}
"""


@dataclass
class FragmentoRecuperado:
    id_fragmento: str
    posicion_bm25: int | None
    posicion_vectorial: int | None
    posicion_rrf: int
    puntaje_rrf: float
    puntaje_reranker: float | None
    posicion_final: int | None
    seleccionado: bool
    id_documento: str
    documento: str
    codigo_documento: str | None
    seccion: str | None
    pagina_inicio: int | None
    pagina_fin: int | None
    idioma: str
    tipo_contenido: str
    texto: str


@dataclass
class ResultadoRecuperacion:
    tipo_busqueda: str
    consulta: str
    terminos_normalizados: list[str]
    candidatos_por_metodo: int
    candidatos_evaluados: int
    umbral_relevancia: float
    relevancia_maxima: float | None
    suficiente: bool
    fragmentos: list[FragmentoRecuperado]
    descartados: list[str] = field(default_factory=list)
    tiempos_ms: dict[str, float] = field(default_factory=dict)

    @property
    def seleccionados(self) -> list[FragmentoRecuperado]:
        return [f for f in self.fragmentos if f.seleccionado]


@dataclass
class Servicios:
    embedder: Embedder
    reranker: Reranker | None
    almacen: AlmacenVectorial
    cache_bm25: CacheBM25


def fusion_rrf(listas: list[list[str]], k: int) -> list[tuple[str, float]]:
    """Reciprocal Rank Fusion: suma de 1 / (k + posición) con posiciones desde 1. Los
    empates se ordenan por la mejor posición en cualquier lista y luego por id."""
    puntajes: dict[str, float] = {}
    mejor: dict[str, int] = {}
    for lista in listas:
        for posicion, id_ in enumerate(lista, start=1):
            puntajes[id_] = puntajes.get(id_, 0.0) + 1.0 / (k + posicion)
            mejor[id_] = min(mejor.get(id_, posicion), posicion)
    return sorted(puntajes.items(), key=lambda p: (-p[1], mejor[p[0]], p[0]))


def leer_texto_filtrado(sesion: Session | Connection, id_consulta: str) -> str | None:
    """Único texto de la consulta que usa la recuperación (columna permitida a cdss_generacion)."""
    return sesion.execute(text("SELECT texto_filtrado FROM asistencia.consulta WHERE id_consulta = CAST(:c AS uuid)"),
                          {"c": id_consulta}).scalar()


def comprobar_fragmentos(sesion: Session | Connection, ids: list[str]) -> dict:
    """Filas de los fragmentos que siguen siendo recuperables, por id."""
    if not ids:
        return {}
    return {f.id_fragmento: f for f in sesion.execute(text(_FRAGMENTOS), {"ids": ids}).all()}


class Cronometro:
    def __init__(self):
        self.tiempos: dict[str, float] = {}

    def medir(self, paso: str, funcion: Callable, *argumentos):
        inicio = time.perf_counter()
        resultado = funcion(*argumentos)
        self.tiempos[paso] = round((time.perf_counter() - inicio) * 1000, 1)
        return resultado


@dataclass
class Candidatos:
    """Resultado de la búsqueda y la fusión, antes del reranker."""
    tipo_busqueda: str
    texto_busqueda: str
    candidatos_por_metodo: int
    fusionados: list[tuple[str, float, int]]
    filas: dict
    posiciones_bm25: dict[str, int]
    posiciones_vectoriales: dict[str, int]
    descartados: list[str]
    cronometro: Cronometro


def buscar_candidatos(sesion: Session | Connection, consulta: ConsultaNormalizada, servicios: Servicios,
                      parametros: ParametrosRecuperacion, tipo_busqueda: str = INICIAL) -> Candidatos:
    """Pasos 1 a 3: BM25, búsqueda vectorial, fusión RRF y comprobación en PostgreSQL.
    fusionados guarda (id, puntaje RRF, posición RRF) de los candidatos recuperables."""
    ampliada = tipo_busqueda == AMPLIADA
    n = parametros.candidatos_busqueda_ampliada if ampliada else parametros.candidatos_busqueda
    texto_busqueda = consulta.texto_ampliado() if ampliada else consulta.texto_normalizado
    c = Cronometro()

    vector = c.medir("embedding", lambda: servicios.embedder.embeber([texto_busqueda])[0])
    indice = c.medir("bm25_indice", servicios.cache_bm25.obtener, sesion)
    lexicos = c.medir("bm25", indice.buscar, terminos_consulta(texto_busqueda, consulta.equivalentes_ingles), n)
    vectoriales = c.medir("chromadb", servicios.almacen.consultar, vector, n, FILTRO_VECTORIAL)
    fusion = c.medir("rrf", fusion_rrf, [[i for i, _ in lexicos], [i for i, _ in vectoriales]], parametros.rrf_k)
    filas = c.medir("postgresql", comprobar_fragmentos, sesion, [i for i, _ in fusion])
    return Candidatos(
        tipo_busqueda=tipo_busqueda, texto_busqueda=texto_busqueda, candidatos_por_metodo=n,
        fusionados=[(i, p, pos) for pos, (i, p) in enumerate(fusion, start=1) if i in filas], filas=filas,
        posiciones_bm25={id_: i for i, (id_, _) in enumerate(lexicos, start=1)},
        posiciones_vectoriales={id_: i for i, (id_, _) in enumerate(vectoriales, start=1)},
        descartados=[i for i, _ in fusion if i not in filas], cronometro=c,
    )


def recuperar(sesion: Session | Connection, consulta: ConsultaNormalizada, servicios: Servicios,
              parametros: ParametrosRecuperacion, tipo_busqueda: str = INICIAL) -> ResultadoRecuperacion:
    """Una pasada de la recuperación híbrida. Con servicios.reranker = None (solo para
    las mediciones) se seleccionan los mejores de la fusión RRF sin umbral."""
    cand = buscar_candidatos(sesion, consulta, servicios, parametros, tipo_busqueda)
    return seleccionar(sesion, consulta, cand, servicios.reranker, parametros)


def seleccionar(sesion: Session | Connection, consulta: ConsultaNormalizada, cand: Candidatos,
                reranker: Reranker | None, parametros: ParametrosRecuperacion) -> ResultadoRecuperacion:
    """Pasos 4 a 6: reranker sobre los mejores de la fusión, selección con umbral y
    recomprobación en PostgreSQL."""
    c, filas, descartados = cand.cronometro, cand.filas, list(cand.descartados)
    pos_bm25, pos_vector = cand.posiciones_bm25, cand.posiciones_vectoriales
    evaluados = cand.fusionados[:parametros.candidatos_reranker]

    if reranker is not None and evaluados:
        puntajes = c.medir("reranker", reranker.puntuar, consulta.texto_normalizado,
                           [filas[i].texto for i, _, _ in evaluados], parametros.max_longitud_reranker)
    else:
        puntajes = [None] * len(evaluados)
    orden = sorted(range(len(evaluados)), key=lambda j: (-(puntajes[j] if puntajes[j] is not None else 0.0), j))

    vigentes = c.medir("recomprobacion", comprobar_fragmentos, sesion, [i for i, _, _ in evaluados])
    fragmentos: list[FragmentoRecuperado] = []
    for j in orden:
        id_, rrf, posicion_rrf = evaluados[j]
        if id_ not in vigentes:
            descartados.append(id_)
            continue
        fila, puntaje = vigentes[id_], puntajes[j]
        alcanza = puntaje is None or puntaje >= parametros.umbral_relevancia
        enviados = sum(f.seleccionado for f in fragmentos)
        fragmentos.append(FragmentoRecuperado(
            id_fragmento=id_, posicion_bm25=pos_bm25.get(id_), posicion_vectorial=pos_vector.get(id_),
            posicion_rrf=posicion_rrf, puntaje_rrf=round(rrf, 6),
            puntaje_reranker=None if puntaje is None else round(float(puntaje), 4), posicion_final=len(fragmentos) + 1,
            seleccionado=alcanza and enviados < parametros.fragmentos_enviados, id_documento=fila.id_documento,
            documento=fila.titulo, codigo_documento=fila.codigo_documento, seccion=fila.seccion,
            pagina_inicio=fila.pagina_inicio, pagina_fin=fila.pagina_fin, idioma=fila.idioma,
            tipo_contenido=fila.tipo_contenido, texto=fila.texto,
        ))

    reales = [f.puntaje_reranker for f in fragmentos if f.puntaje_reranker is not None]
    maxima = max(reales) if reales else None
    return ResultadoRecuperacion(
        tipo_busqueda=cand.tipo_busqueda, consulta=cand.texto_busqueda,
        terminos_normalizados=[t.preferido for t in consulta.terminos],
        candidatos_por_metodo=cand.candidatos_por_metodo,
        candidatos_evaluados=len(evaluados), umbral_relevancia=parametros.umbral_relevancia,
        relevancia_maxima=maxima, suficiente=any(f.seleccionado for f in fragmentos),
        fragmentos=fragmentos, descartados=descartados, tiempos_ms=c.tiempos,
    )


def recuperar_con_ampliacion(sesion: Session | Connection, consulta: ConsultaNormalizada, servicios: Servicios,
                             parametros: ParametrosRecuperacion) -> list[ResultadoRecuperacion]:
    """Búsqueda inicial y, si ningún fragmento alcanza el umbral, la ampliada. Devuelve
    las pasadas ejecutadas en orden; la última es la que cuenta."""
    inicial = recuperar(sesion, consulta, servicios, parametros, INICIAL)
    if inicial.suficiente:
        return [inicial]
    return [inicial, recuperar(sesion, consulta, servicios, parametros, AMPLIADA)]
