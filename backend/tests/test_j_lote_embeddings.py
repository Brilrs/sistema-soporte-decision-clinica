"""Sprint 3, parte J (P14): lote de embeddings del indexador configurable (INDEXADOR_LOTE_EMBEDDINGS).

El lote solo cambia cuántos textos van en cada petición a modelos: los vectores y los fragmentos son
los mismos con cualquier lote. Las pruebas usan un cliente de modelos simulado que responde con el
embedder falso y documentos sintéticos de la base de pruebas, que se borran al terminar."""
import uuid

import pytest
from sqlalchemy import text

from app.core.modelos import DIMENSION, EmbedderFalso, EmbedderHttp, TokenizadorFalso
from app.core.vectores import AlmacenMemoria
from app.indexador import __main__ as cli
from app.indexador.config import (LOTE_EMBEDDINGS_POR_OMISION, ConfigIndexador, FuenteDocumento, cargar_config,
                                  leer_lote_embeddings)
from app.indexador.indexacion import Indexador, Opciones
from app.indexador.repositorio import USUARIO_SISTEMA, Repositorio
from app.scripts import medir_interferencia
from app.indexador.extraccion import PaginaTexto
from tests.test_indexador_flujo import FRASE, engine_indexador  # noqa: F401 (fixture)

# Doce secciones de unas 40 frases, en seis páginas: bastantes fragmentos para que el lote 8 también se
# parta en varias peticiones (con PAGINAS de test_indexador_flujo salen solo 3 fragmentos).
TEMAS = ["preventiva", "terapéutica", "en gestantes", "en lactantes", "en prematuros", "de seguimiento",
         "comunitaria", "en el control", "con multimicronutrientes", "en la consejería", "domiciliaria", "final"]
PAGINAS_J = [PaginaTexto(n + 1, [f"5.{2 * n + k + 1}. Suplementación {TEMAS[2 * n + k]}" if j == 0
                                 else FRASE.replace("preventiva", TEMAS[2 * n + k])
                                 for k in range(2) for j in range(41)])
             for n in range(6)]


class ClienteSimulado:
    """Responde /embeddings con el embedder falso y anota cada petición."""

    def __init__(self):
        self.peticiones: list[list[str]] = []
        self._falso = EmbedderFalso()

    def post(self, ruta: str, cuerpo: dict) -> dict:
        assert ruta == "/embeddings"
        self.peticiones.append(list(cuerpo["textos"]))
        return {"dimension": DIMENSION, "vectores": self._falso.embeber(cuerpo["textos"])}


TEXTOS = [f"Texto número {i} sobre hierro y hemoglobina {'extra ' * (i % 3)}" for i in range(11)]


# ---------------------------------------------------------------------------
# Lote en el cliente y en las peticiones
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("lote, tamanos", [
    (1, [1] * 11), (2, [2, 2, 2, 2, 2, 1]), (4, [4, 4, 3]), (8, [8, 3]), (11, [11]), (64, [11]),
])
def test_el_lote_parte_las_peticiones_y_conserva_el_orden(lote, tamanos):
    cliente = ClienteSimulado()
    vectores = EmbedderHttp(cliente, lote=lote).embeber(TEXTOS)
    assert [len(p) for p in cliente.peticiones] == tamanos
    assert [t for p in cliente.peticiones for t in p] == TEXTOS          # nada se pierde ni se reordena
    assert vectores == EmbedderFalso().embeber(TEXTOS)                    # cada vector en su posición


@pytest.mark.parametrize("valor", [0, 65, -1])
def test_embedder_rechaza_un_lote_fuera_de_rango(valor):
    with pytest.raises(ValueError, match="de 1 a 64"):
        EmbedderHttp(ClienteSimulado(), lote=valor)


# ---------------------------------------------------------------------------
# Variable de entorno
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("valor, esperado", [
    (None, LOTE_EMBEDDINGS_POR_OMISION), ("", LOTE_EMBEDDINGS_POR_OMISION), ("1", 1), (" 4 ", 4), ("64", 64),
])
def test_valores_validos_de_la_variable(valor, esperado):
    assert leer_lote_embeddings(valor) == esperado


@pytest.mark.parametrize("valor", ["0", "65", "texto", "2.5", "-3"])
def test_valores_no_validos_dan_un_error_claro(valor, monkeypatch, capsys):
    with pytest.raises(ValueError, match=r"INDEXADOR_LOTE_EMBEDDINGS debe ser un entero de 1 a 64; se recibió"):
        leer_lote_embeddings(valor)
    monkeypatch.setenv("INDEXADOR_LOTE_EMBEDDINGS", valor)
    with pytest.raises(ValueError):
        cargar_config()
    assert cli.main(["trabajador", "--una-vez"]) == 2  # el trabajador no arranca con un valor no válido
    assert "INDEXADOR_LOTE_EMBEDDINGS debe ser un entero de 1 a 64" in capsys.readouterr().err


def test_la_variable_llega_al_embedder_del_indexador(monkeypatch):
    monkeypatch.setenv("INDEXADOR_LOTE_EMBEDDINGS", "2")
    config = cargar_config()
    assert config.lote_embeddings == 2
    embedder, _ = cli._servicios(config, falsos=False)
    assert isinstance(embedder, EmbedderHttp) and embedder.lote == 2
    monkeypatch.delenv("INDEXADOR_LOTE_EMBEDDINGS")
    embedder, _ = cli._servicios(cargar_config(), falsos=False)
    assert embedder.lote == LOTE_EMBEDDINGS_POR_OMISION


def test_el_script_de_medicion_usa_la_misma_regla():
    assert medir_interferencia.lote_valido("3") == 3
    for valor in ("0", "65", "x"):
        with pytest.raises(Exception, match="de 1 a 64"):
            medir_interferencia.lote_valido(valor)


def test_compose_pasa_la_variable_al_indexador_y_a_jobs():
    from pathlib import Path
    compose = (Path(__file__).resolve().parents[2] / "docker-compose.yml").read_text(encoding="utf-8")
    linea = f"INDEXADOR_LOTE_EMBEDDINGS: ${{INDEXADOR_LOTE_EMBEDDINGS:-{LOTE_EMBEDDINGS_POR_OMISION}}}"
    assert compose.count(linea) == 2


def test_la_medicion_resume_percentiles():
    assert medir_interferencia.percentil([1, 2, 3, 4], 0.5) == 2.5
    r = medir_interferencia.resumen([{"total_ms": 1000, "embedding_ms": 100, "reranker_ms": 800},
                                     {"total_ms": 3000, "embedding_ms": 500, "reranker_ms": 2400}])
    assert (r["mediana_s"], r["maximo_s"], r["embedding_max_s"], r["reranker_max_s"]) == (2.0, 3.0, 0.5, 2.4)


# ---------------------------------------------------------------------------
# El indexador produce lo mismo con cualquier lote
# ---------------------------------------------------------------------------
@pytest.fixture
def documentos(super_engine):
    ids: list[str] = []

    def crear() -> str:
        id_doc = str(uuid.uuid4())
        with super_engine.begin() as c:
            c.execute(text(
                """INSERT INTO conocimiento.documento_fuente
                     (id_documento, titulo, codigo_documento, entidad_emisora, tipo_documento, nivel,
                      anio_publicacion, idioma, cargado_por)
                   VALUES (:id, 'Documento sintético de la parte J', 'PRUEBA-J', 'MINSA', 'NORMA_TECNICA', 1, 2024,
                           'es', :u)"""), {"id": id_doc, "u": USUARIO_SISTEMA})
        ids.append(id_doc)
        return id_doc

    yield crear
    with super_engine.begin() as c:
        for id_doc in ids:
            for tabla in ("fragmento", "trabajo_indexacion", "documento_fuente"):
                c.execute(text(f"DELETE FROM conocimiento.{tabla} WHERE id_documento = :id"), {"id": id_doc})


def _indexar(engine, id_doc: str, lote: int) -> tuple[AlmacenMemoria, ClienteSimulado]:
    cliente = ClienteSimulado()
    almacen = AlmacenMemoria()
    indexador = Indexador(Repositorio(engine), almacen, EmbedderHttp(cliente, lote=lote), TokenizadorFalso(),
                          lote_progreso=16)
    resultado = indexador.indexar(FuenteDocumento(clave="prueba-j", id_documento=id_doc, archivo="j.pdf"), None,
                                  Opciones(), extraer=lambda _doc: PAGINAS_J, hash_archivo=uuid.uuid4().hex * 2,
                                  ruta_blob="local://prueba/j.pdf")
    assert resultado.estado == "COMPLETADA", resultado.mensaje
    return almacen, cliente


def _por_orden(almacen: AlmacenMemoria) -> list[tuple]:
    """(página, sección, texto, vector) en el orden de los fragmentos, sin los ids, que dependen del documento."""
    registros = sorted(almacen.registros.values(), key=lambda r: (r.metadatos["pagina_inicio"], r.id))
    return sorted((r.metadatos["pagina_inicio"], r.metadatos["seccion"], r.texto, tuple(r.vector)) for r in registros)


@pytest.mark.parametrize("lote", [1, 2, 3])
def test_el_indexador_produce_los_mismos_fragmentos_y_vectores_que_con_lote_8(engine_indexador, documentos, lote):
    con_8, cliente_8 = _indexar(engine_indexador, documentos(), 8)
    con_lote, cliente_lote = _indexar(engine_indexador, documentos(), lote)
    assert len(con_8.registros) == len(con_lote.registros) > 8  # el lote 8 también se parte
    assert _por_orden(con_lote) == _por_orden(con_8)
    # Mismos textos enviados, en el mismo orden, partidos en lotes del tamaño pedido
    assert [t for p in cliente_lote.peticiones for t in p] == [t for p in cliente_8.peticiones for t in p]
    assert max(len(p) for p in cliente_lote.peticiones) == lote and max(len(p) for p in cliente_8.peticiones) <= 8
    assert len(cliente_8.peticiones) > 1 and len(cliente_lote.peticiones) > len(cliente_8.peticiones)
    # Cada vector corresponde a su propio texto
    for r in con_lote.registros.values():
        assert r.vector == EmbedderFalso().embeber([r.texto])[0]
