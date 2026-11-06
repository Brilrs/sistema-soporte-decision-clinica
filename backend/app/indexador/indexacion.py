"""Flujo de indexación de un documento con consistencia entre PostgreSQL y
ChromaDB. Los fragmentos se escriben en una sola transacción de PostgreSQL;
los vectores se agregan a ChromaDB dentro de ella, antes del commit. Si ChromaDB
falla, la transacción se deshace y no queda nada; si falla el commit después de
escribir en ChromaDB, se compensa borrando esos vectores. En ambos casos el
documento queda en ERROR."""
import hashlib
import logging
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from app.indexador.chunker import Avisos, Fragmento, fragmentar
from app.indexador.config import FuenteDocumento
from app.indexador.errores import ErrorIndexacion
from app.indexador.extraccion import PaginaTexto, contar_sospechosos, extraer_pdf
from app.indexador.modificaciones import cargar_mapa
from app.indexador.repositorio import Documento, Repositorio
from app.indexador.segmentacion import ResultadoSegmentacion, TextoDocumento, segmentar
from app.indexador.servicios import Embedder, Tokenizador
from app.indexador.transcripciones import cargar_transcripciones
from app.indexador.vectores import AlmacenVectorial, RegistroVector

log = logging.getLogger("indexador")
ESPACIO_IDS = uuid.UUID("6f1c2b0e-5d1a-4c4e-9a57-2b8f0c3d7e21")


def sha256_archivo(ruta: Path) -> str:
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        for bloque in iter(lambda: f.read(1 << 20), b""):
            h.update(bloque)
    return h.hexdigest()


def id_fragmento(id_documento: str, version: int, orden: int) -> str:
    return str(uuid.uuid5(ESPACIO_IDS, f"{id_documento}:{version}:{orden}"))


@dataclass
class Opciones:
    permitir_no_verificadas: bool = False
    reindexar: bool = False


@dataclass
class Preparacion:
    """Resultado de extraer, segmentar y fragmentar, sin escribir nada."""
    paginas: list[PaginaTexto]
    segmentacion: ResultadoSegmentacion
    fragmentos: list[Fragmento]
    avisos: list[str]
    transcripciones: list
    sospechosos_por_pagina: dict[int, int]


@dataclass
class Resultado:
    id_documento: str
    estado: str
    version: int | None = None
    total: int = 0
    vigentes: int = 0
    no_verificadas: int = 0
    mensaje: str = ""
    avisos: list[str] = field(default_factory=list)
    segundos_total: float = 0.0
    segundos_embeddings: float = 0.0


def preparar(fuente: FuenteDocumento, paginas: list[PaginaTexto], tokenizador: Tokenizador,
             parametros: tuple[int, int, int] = (500, 800, 80)) -> Preparacion:
    if not paginas or not any(p.lineas for p in paginas):
        raise ErrorIndexacion("No se extrajo texto de las páginas del cuerpo")
    doc = TextoDocumento.desde_paginas(paginas)
    transcripciones = cargar_transcripciones(fuente.transcripciones)
    mapa = cargar_mapa(fuente.modificaciones) if fuente.modificaciones else None
    seg = segmentar(doc, transcripciones, mapa, fuente.rol)
    avisos = Avisos()
    objetivo, maximo, solapamiento = parametros
    fragmentos = fragmentar(seg.segmentos, doc, tokenizador, objetivo, maximo, solapamiento, avisos)
    if not fragmentos:
        raise ErrorIndexacion("El documento no produjo fragmentos")
    return Preparacion(paginas, seg, fragmentos, avisos.mensajes, transcripciones,
                       {p.numero: contar_sospechosos(p.texto) for p in paginas})


def _metadatos(documento: Documento, f: Fragmento, version: int) -> dict:
    return {
        "id_documento": documento.id_documento,
        "id_fragmento": "",
        "nivel": documento.nivel,
        "estado_documento": documento.estado,
        "vigente": f.vigente,
        "idioma": documento.idioma,
        "seccion": f.seccion or "",
        "paginas": f"{f.pagina_inicio}-{f.pagina_fin}",
        "pagina_inicio": f.pagina_inicio,
        "pagina_fin": f.pagina_fin,
        "tipo_contenido": f.tipo_contenido,
        "fuente_texto": f.fuente_texto,
        "verificado": f.verificado,
        "version_indexacion": version,
    }


class Indexador:
    def __init__(self, repo: Repositorio, almacen: AlmacenVectorial, embedder: Embedder, tokenizador: Tokenizador,
                 lote_progreso: int = 16):
        self.repo = repo
        self.almacen = almacen
        self.embedder = embedder
        self.tokenizador = tokenizador
        self.lote_progreso = lote_progreso

    def indexar(self, fuente: FuenteDocumento, ruta_pdf: Path | None, opciones: Opciones = Opciones(),
                id_trabajo: str | None = None, extraer: Callable[[Documento], list[PaginaTexto]] | None = None,
                hash_archivo: str | None = None, ruta_blob: str | None = None) -> Resultado:
        documento = self.repo.documento(fuente.id_documento)
        inicio = time.perf_counter()
        try:
            if hash_archivo is None:
                if ruta_pdf is None or not ruta_pdf.is_file():
                    raise ErrorIndexacion(f"No se encontró el archivo {ruta_pdf}")
                hash_archivo = sha256_archivo(ruta_pdf)
            ruta_blob = ruta_blob or f"local://guias/{ruta_pdf.name if ruta_pdf else fuente.archivo}"

            if (documento.hash_archivo == hash_archivo and documento.estado_indexacion == "COMPLETADA"
                    and not opciones.reindexar):
                self.repo.finalizar_trabajo(id_trabajo)
                return Resultado(documento.id_documento, "OMITIDO", self.repo.version_actual(documento.id_documento),
                                 documento.total_fragmentos,
                                 mensaje="Mismo archivo (SHA-256) ya indexado; no se duplica nada")
            otro = self.repo.documento_con_hash(hash_archivo)
            if otro and otro != documento.id_documento:
                raise ErrorIndexacion(f"El archivo ya está cargado como el documento {otro}")

            self.repo.registrar_archivo(documento.id_documento, ruta_blob, hash_archivo)
            resultado = self._indexar(fuente, documento, ruta_pdf, opciones, id_trabajo, extraer, hash_archivo)
            resultado.segundos_total = time.perf_counter() - inicio
            return resultado
        except Exception as e:
            mensaje = str(e) if isinstance(e, ErrorIndexacion) else f"{type(e).__name__}: {e}"
            log.error("Documento %s en ERROR: %s", fuente.clave, mensaje)
            self.repo.marcar_error(documento.id_documento)
            self.repo.finalizar_trabajo(id_trabajo, mensaje)
            self.repo.auditar_aparte("GUIA_INDEXACION_ERROR", documento.id_documento,
                                     {"clave": fuente.clave, "hash": hash_archivo, "error": mensaje[:500]})
            return Resultado(documento.id_documento, "ERROR", mensaje=mensaje,
                             segundos_total=time.perf_counter() - inicio)

    def _indexar(self, fuente, documento, ruta_pdf, opciones, id_trabajo, extraer, hash_archivo) -> Resultado:
        self.repo.avance(id_trabajo, "EXTRACCION")
        if extraer is not None:
            paginas = extraer(documento)
        else:
            paginas = extraer_pdf(ruta_pdf, documento.pagina_inicio_cuerpo, documento.pagina_fin_cuerpo, fuente.recorte)

        self.repo.avance(id_trabajo, "FRAGMENTACION")
        prep = preparar(fuente, paginas, self.tokenizador, self.repo.parametros_fragmentacion())
        fragmentos = prep.fragmentos

        sin_verificar = sorted({t.clave for t in prep.transcripciones if not t.verificada})
        if documento.nivel == 1 and sin_verificar and not opciones.permitir_no_verificadas:
            raise ErrorIndexacion(
                f"El documento es de nivel 1 y tiene {len(sin_verificar)} transcripciones sin verificar "
                f"({', '.join(sin_verificar)}). Complete verificado_por y fecha_verificacion en cada una, o use "
                "--permitir-no-verificadas solo en desarrollo"
            )

        self.repo.avance(id_trabajo, "NORMALIZACION", 0, len(fragmentos))
        total = len(fragmentos)
        vectores: list[list[float]] = []
        self.repo.avance(id_trabajo, "EMBEDDINGS", 0, total)
        inicio_embeddings = time.perf_counter()
        for i in range(0, total, self.lote_progreso):
            vectores.extend(self.embedder.embeber([f.texto for f in fragmentos[i:i + self.lote_progreso]]))
            self.repo.avance(id_trabajo, "EMBEDDINGS", min(i + self.lote_progreso, total), total)
        segundos_embeddings = time.perf_counter() - inicio_embeddings

        version = self.repo.version_actual(documento.id_documento) + 1
        ids = [id_fragmento(documento.id_documento, version, f.orden) for f in fragmentos]
        registros = []
        for f, i, v in zip(fragmentos, ids, vectores):
            meta = _metadatos(documento, f, version)
            meta["id_fragmento"] = i
            registros.append(RegistroVector(i, v, f.texto, meta))
        previos = [i for i in self.almacen.ids_de_documento(documento.id_documento) if i not in set(ids)]

        self.repo.avance(id_trabajo, "INDEXACION", 0, total)
        vigentes = sum(f.vigente for f in fragmentos)
        no_verificadas = sum(1 for f in fragmentos if f.fuente_texto == "TRANSCRIPCION" and not f.verificado)
        en_chroma = False
        try:
            with self.repo.engine.begin() as c:
                retirados = self.repo.retirar_versiones_anteriores(c, documento.id_documento, version)
                self.repo.insertar_fragmentos(c, documento.id_documento, version, self.embedder.nombre, fragmentos, ids)
                self.repo.completar_documento(c, documento.id_documento, total)
                self.repo.auditar(c, "GUIA_INDEXADA", documento.id_documento, {
                    "clave": fuente.clave, "hash": hash_archivo, "version": version, "fragmentos": total,
                    "vigentes": vigentes, "transcripciones_no_verificadas": no_verificadas,
                    "permitir_no_verificadas": opciones.permitir_no_verificadas, "fragmentos_retirados": retirados,
                })
                for k in range(0, total, self.lote_progreso):
                    en_chroma = True
                    self.almacen.agregar(registros[k:k + self.lote_progreso])
                    self.repo.avance(id_trabajo, "INDEXACION", min(k + self.lote_progreso, total), total)
        except Exception:
            if en_chroma:
                log.warning("Compensación: se borran de ChromaDB los %d vectores de la versión %d", total, version)
                self.almacen.eliminar(ids)
            raise

        if previos:
            try:
                self.almacen.eliminar(previos)
            except Exception as e:  # la siguiente indexación vuelve a intentarlo
                log.warning("No se pudieron quitar de ChromaDB %d vectores de versiones anteriores: %s", len(previos), e)
        self.repo.finalizar_trabajo(id_trabajo)
        return Resultado(documento.id_documento, "COMPLETADA", version, total, vigentes, no_verificadas,
                         avisos=prep.avisos, segundos_embeddings=segundos_embeddings)
