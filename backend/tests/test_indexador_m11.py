"""Parte F2, paso 1: el indexador con documentos cargados desde M11 (fuera del manifiesto),
contra PostgreSQL con el usuario cdss_indexador, ChromaDB en memoria y modelos falsos.

- Un PDF mínimo, armado dentro de la prueba, se extrae completo (o solo las páginas del cuerpo).
- El trabajador procesa un documento fuera del manifiesto, conserva su ruta
  (local://guias_cargadas/...) y deja todos sus fragmentos GENERAL.
- Un documento de nivel 2 no es recuperable (ni en PostgreSQL ni con el filtro vectorial).
- Una excepción fuera de indexar() no termina el bucle del trabajador.
- Al arrancar, un trabajo EN_CURSO huérfano pasa a ERROR con un mensaje claro."""
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text

from app.core.modelos import EmbedderFalso, TokenizadorFalso
from app.core.vectores import AlmacenMemoria
from app.indexador.__main__ import MENSAJE_HUERFANO, _fuente, procesar_pendientes
from app.indexador.config import ConfigIndexador, Recorte
from app.indexador.extraccion import extraer_pdf
from app.indexador.grupos_etarios import GENERAL
from app.indexador.indexacion import Indexador
from app.indexador.repositorio import USUARIO_SISTEMA, Repositorio
from app.rag.bm25 import CONDICION_RECUPERABLE
from app.rag.recuperacion import FILTRO_VECTORIAL
from tests.test_indexador_flujo import engine_indexador  # noqa: F401 (fixture)

LINEAS = {
    1: ["Portada de la guia de prueba"],
    2: ["1. Suplementacion con hierro en ninos de 6 a 23 meses",
        "El establecimiento de salud entrega hierro en gotas a los ninos de 6 a 11 meses de edad."],
    3: ["2. Seguimiento", "El control de hemoglobina se realiza al tercer mes de iniciada la suplementacion."],
}


def pdf_minimo(paginas: dict[int, list[str]], cuadro: str = "0 0 612 792") -> bytes:
    """PDF 1.4 válido con una línea de texto por renglón (Helvetica), sin dependencias."""
    objetos: list[bytes] = []
    n = len(paginas)
    ids_paginas = [4 + 2 * i for i in range(n)]
    objetos.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objetos.append(f"<< /Type /Pages /Kids [{' '.join(f'{i} 0 R' for i in ids_paginas)}] /Count {n} >>".encode())
    objetos.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    for i, numero in enumerate(sorted(paginas)):
        contenido = "BT /F1 11 Tf 72 720 Td 14 TL " + " ".join(
            f"({linea}) Tj T*" for linea in paginas[numero]) + " ET"
        objetos.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [{cuadro}] /Resources << /Font << /F1 3 0 R >> >> "
                       f"/Contents {ids_paginas[i] + 1} 0 R >>".encode())
        objetos.append(f"<< /Length {len(contenido)} >>\nstream\n{contenido}\nendstream".encode())
    salida = bytearray(b"%PDF-1.4\n")
    desplazamientos = []
    for k, cuerpo in enumerate(objetos, 1):
        desplazamientos.append(len(salida))
        salida += f"{k} 0 obj\n".encode() + cuerpo + b"\nendobj\n"
    inicio_xref = len(salida)
    salida += f"xref\n0 {len(objetos) + 1}\n0000000000 65535 f \n".encode()
    salida += b"".join(f"{d:010d} 00000 n \n".encode() for d in desplazamientos)
    salida += f"trailer\n<< /Size {len(objetos) + 1} /Root 1 0 R >>\nstartxref\n{inicio_xref}\n%%EOF\n".encode()
    return bytes(salida)


@pytest.fixture
def carpetas(tmp_path: Path):
    guias, cargadas = tmp_path / "guias", tmp_path / "guias_cargadas"
    guias.mkdir()
    cargadas.mkdir()
    return ConfigIndexador(database_url=None, chroma_url="", modelos_url="", dir_guias=guias,
                           dir_mediciones=tmp_path, intervalo_trabajador_s=0), cargadas


def _borrar(super_engine, ids: list[str]) -> None:
    with super_engine.begin() as c:
        for id_doc in ids:
            p = {"id": id_doc}
            c.execute(text("DELETE FROM conocimiento.fragmento WHERE id_documento = :id"), p)
            c.execute(text("DELETE FROM conocimiento.trabajo_indexacion WHERE id_documento = :id"), p)
            c.execute(text("DELETE FROM conocimiento.documento_fuente WHERE id_documento = :id"), p)


@pytest.fixture
def documentos_m11(super_engine):
    """Crea documentos como los dejará la subida de M11 (nivel 2, ruta en guias_cargadas, sin
    hash todavía); al final se borran con la conexión de administración."""
    creados: list[str] = []

    def crear(nivel: int = 2, pagina_inicio: int | None = None, pagina_fin: int | None = None) -> str:
        id_doc = str(uuid.uuid4())
        with super_engine.begin() as c:
            c.execute(text(
                """INSERT INTO conocimiento.documento_fuente
                     (id_documento, titulo, entidad_emisora, tipo_documento, nivel, anio_publicacion, idioma,
                      pagina_inicio_cuerpo, pagina_fin_cuerpo, ruta_blob, cargado_por)
                   VALUES (:id, 'Guía metodológica de prueba (M11)', 'OTRA', 'LITERATURA', :n, 2025, 'es', :pi, :pf,
                           :ruta, :u)"""),
                {"id": id_doc, "n": nivel, "pi": pagina_inicio, "pf": pagina_fin,
                 "ruta": f"local://guias_cargadas/{id_doc}.pdf", "u": USUARIO_SISTEMA})
        creados.append(id_doc)
        return id_doc

    yield crear
    _borrar(super_engine, creados)


def _indexador(engine, almacen=None, repo=None) -> Indexador:
    return Indexador(repo or Repositorio(engine), almacen if almacen is not None else AlmacenMemoria(),
                     EmbedderFalso(), TokenizadorFalso(), lote_progreso=4)


def _trabajo(super_engine, id_trabajo: str):
    with super_engine.connect() as c:
        return c.execute(text("SELECT estado, mensaje_error, fecha_fin FROM conocimiento.trabajo_indexacion "
                              "WHERE id_trabajo = :t"), {"t": id_trabajo}).one()


# ---------------------------------------------------------------------------
# Extracción de un PDF cualquiera
# ---------------------------------------------------------------------------
def test_un_pdf_minimo_se_extrae_completo_o_solo_el_cuerpo(tmp_path):
    ruta = tmp_path / "minimo.pdf"
    ruta.write_bytes(pdf_minimo(LINEAS))
    todas = extraer_pdf(ruta, None, None, Recorte())
    assert [p.numero for p in todas] == [1, 2, 3]
    assert "hierro en gotas" in todas[1].texto and "tercer mes" in todas[2].texto
    cuerpo = extraer_pdf(ruta, 2, 3, Recorte())
    assert [p.numero for p in cuerpo] == [2, 3]


def test_un_pdf_cuyo_cuadro_no_empieza_en_cero_se_extrae_sin_recorte(tmp_path):
    """Como la RM 251 (cuadro de 0 a -0.01): la caja de toda la página se salía del cuadro y
    pdfplumber la rechazaba; ahora se limita al cuadro real."""
    ruta = tmp_path / "desplazado.pdf"
    ruta.write_bytes(pdf_minimo(LINEAS, cuadro="0 -0.01 612 791.99"))
    paginas = extraer_pdf(ruta, None, None, Recorte())
    assert [p.numero for p in paginas] == [1, 2, 3] and "tercer mes" in paginas[2].texto


def test_una_fuente_fuera_del_manifiesto_no_tiene_reglas_propias():
    fuente = _fuente(str(uuid.uuid4()), "fuentes_iniciales.yaml")
    assert (fuente.en_manifiesto, fuente.archivo, fuente.transcripciones, fuente.modificaciones) == (False, "", None, None)
    assert _fuente("rm251", "fuentes_iniciales.yaml").en_manifiesto is True


# ---------------------------------------------------------------------------
# Trabajador con un documento de M11
# ---------------------------------------------------------------------------
def test_el_trabajador_indexa_un_documento_de_m11_conservando_su_ruta(engine_indexador, super_engine,  # noqa: F811
                                                                      documentos_m11, carpetas):
    config, cargadas = carpetas
    id_doc = documentos_m11(nivel=2)
    (cargadas / f"{id_doc}.pdf").write_bytes(pdf_minimo(LINEAS))
    repo = Repositorio(engine_indexador)
    id_trabajo = repo.crear_trabajo(id_doc, "INDEXACION")
    almacen = AlmacenMemoria()
    assert procesar_pendientes(_indexador(engine_indexador, almacen), config, una_vez=True) == 0

    assert _trabajo(super_engine, id_trabajo).estado == "COMPLETADO"
    with super_engine.connect() as c:
        doc = c.execute(text("SELECT ruta_blob, hash_archivo, estado_indexacion, total_fragmentos "
                             "FROM conocimiento.documento_fuente WHERE id_documento = :id"), {"id": id_doc}).one()
        grupos = c.execute(text("SELECT DISTINCT poblacion, edad_min_meses, edad_max_meses, origen_rango, rango_dudoso "
                                "FROM conocimiento.fragmento WHERE id_documento = :id"), {"id": id_doc}).all()
        paginas = c.execute(text("SELECT min(pagina_inicio), max(pagina_fin) FROM conocimiento.fragmento "
                                 "WHERE id_documento = :id"), {"id": id_doc}).one()
        recuperables = c.execute(text(
            f"""SELECT count(*) FROM conocimiento.fragmento f JOIN conocimiento.documento_fuente d
                   ON d.id_documento = f.id_documento WHERE f.id_documento = :id AND {CONDICION_RECUPERABLE}"""),
            {"id": id_doc}).scalar_one()
    # La ruta de M11 se conserva (antes se sobrescribía con local://guias/<archivo>).
    assert doc.ruta_blob == f"local://guias_cargadas/{id_doc}.pdf"
    assert doc.estado_indexacion == "COMPLETADA" and len(doc.hash_archivo) == 64 and doc.total_fragmentos >= 1
    # Sin páginas del cuerpo se leen todas.
    assert (paginas[0], paginas[1]) == (1, 3)
    # Sin reglas propias de grupo etario: todo GENERAL, aunque el texto nombra «6 a 23 meses».
    assert grupos == [(GENERAL, None, None, "MANUAL", False)]
    # Nivel 2: no es recuperable ni en PostgreSQL ni con el filtro vectorial de la recuperación.
    assert recuperables == 0
    propios = set(almacen.ids_de_documento(id_doc))
    vector = EmbedderFalso().embeber(["hierro en gotas"])[0]
    assert propios <= {i for i, _ in almacen.consultar(vector, 50)}  # sin filtro sí aparecen
    assert not propios & {i for i, _ in almacen.consultar(vector, 50, FILTRO_VECTORIAL)}  # con el de la recuperación, no


def test_el_trabajador_usa_las_paginas_del_cuerpo_si_vienen(engine_indexador, super_engine, documentos_m11,  # noqa: F811
                                                            carpetas):
    config, cargadas = carpetas
    id_doc = documentos_m11(nivel=2, pagina_inicio=2, pagina_fin=3)
    (cargadas / f"{id_doc}.pdf").write_bytes(pdf_minimo(LINEAS))
    Repositorio(engine_indexador).crear_trabajo(id_doc, "INDEXACION")
    procesar_pendientes(_indexador(engine_indexador), config, una_vez=True)
    with super_engine.connect() as c:
        textos = " ".join(c.execute(text("SELECT texto FROM conocimiento.fragmento WHERE id_documento = :id"),
                                    {"id": id_doc}).scalars())
    assert "Portada" not in textos and "hierro en gotas" in textos


class RepositorioQueFallaUnaVez(Repositorio):
    """documento() falla la primera vez (como una base caída a mitad del trabajo)."""
    fallos = 0

    def documento(self, id_documento):
        if RepositorioQueFallaUnaVez.fallos == 0:
            RepositorioQueFallaUnaVez.fallos += 1
            raise ConnectionError("La base de datos no responde")
        return super().documento(id_documento)


def test_una_excepcion_fuera_de_indexar_no_detiene_el_bucle(engine_indexador, super_engine, documentos_m11,  # noqa: F811
                                                            carpetas):
    config, cargadas = carpetas
    primero, segundo = documentos_m11(), documentos_m11()
    for id_doc in (primero, segundo):
        (cargadas / f"{id_doc}.pdf").write_bytes(pdf_minimo(LINEAS))
    repo = RepositorioQueFallaUnaVez(engine_indexador)
    t1 = repo.crear_trabajo(primero, "INDEXACION")
    t2 = repo.crear_trabajo(segundo, "INDEXACION")
    pausas: list[float] = []
    resultado = procesar_pendientes(_indexador(engine_indexador, repo=repo), config, una_vez=True,
                                    dormir=pausas.append)
    assert resultado == 0 and pausas == [0]  # una pausa tras el fallo, y siguió
    fallido = _trabajo(super_engine, t1)
    assert fallido.estado == "ERROR" and "ConnectionError: La base de datos no responde" in fallido.mensaje_error
    assert _trabajo(super_engine, t2).estado == "COMPLETADO"


def test_si_tomar_un_trabajo_falla_el_bucle_espera_y_sigue(engine_indexador, carpetas):  # noqa: F811
    config, _ = carpetas
    llamadas = {"n": 0}

    class RepositorioCaido(Repositorio):
        def marcar_trabajos_huerfanos(self, mensaje):
            raise ConnectionError("sin base")

        def tomar_trabajo(self):
            llamadas["n"] += 1
            if llamadas["n"] == 1:
                raise ConnectionError("sin base")
            return None

    pausas: list[float] = []
    assert procesar_pendientes(_indexador(engine_indexador, repo=RepositorioCaido(engine_indexador)), config,
                               una_vez=True, dormir=pausas.append) == 0
    assert llamadas["n"] == 2 and pausas == [0]


def test_al_arrancar_un_trabajo_huerfano_queda_en_error(engine_indexador, super_engine, documentos_m11,  # noqa: F811
                                                        carpetas):
    config, _ = carpetas
    id_doc = documentos_m11()
    repo = Repositorio(engine_indexador)
    id_trabajo = repo.crear_trabajo(id_doc, "INDEXACION", estado="EN_CURSO")
    repo.registrar_archivo(id_doc, f"local://guias_cargadas/{id_doc}.pdf", uuid.uuid4().hex * 2)  # EN_PROCESO
    procesar_pendientes(_indexador(engine_indexador), config, una_vez=True)
    huerfano = _trabajo(super_engine, id_trabajo)
    assert huerfano.estado == "ERROR" and huerfano.mensaje_error == MENSAJE_HUERFANO and huerfano.fecha_fin
    assert "Reintentar" in MENSAJE_HUERFANO
    with super_engine.connect() as c:
        estado = c.execute(text("SELECT estado_indexacion FROM conocimiento.documento_fuente WHERE id_documento = :id"),
                           {"id": id_doc}).scalar_one()
        auditoria = c.execute(text(
            """SELECT detalle FROM auditoria.evento_auditoria
                WHERE tipo_evento = 'GUIA_INDEXACION_ERROR' AND id_entidad = :id"""), {"id": id_doc}).scalars().all()
    assert estado == "ERROR"
    assert {"id_trabajo": id_trabajo, "error": MENSAJE_HUERFANO} in auditoria
