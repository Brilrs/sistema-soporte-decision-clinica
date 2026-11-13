"""Parte C2 contra PostgreSQL, con modelos falsos y ChromaDB en memoria: la bonificación por
edad cambia qué fragmentos llegan al reranker, sin filtro duro; la migración 008 es
idempotente y el indexador guarda el grupo etario en PostgreSQL y en los metadatos."""
import os
import uuid
from dataclasses import replace
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from app.core.modelos import EmbedderFalso, RerankerFalso
from app.core.vectores import AlmacenMemoria, RegistroVector
from app.rag.bm25 import CacheBM25
from app.rag.normalizacion import normalizar
from app.rag.parametros import parametros_recuperacion
from app.rag.recuperacion import Servicios, buscar_candidatos, recuperar

SISTEMA = "00000000-0000-0000-0000-000000000001"
MIGRACION_008 = Path(__file__).resolve().parents[2] / "db" / "migraciones" / "008_grupo_etario.sql"
MIGRACION_009 = Path(__file__).resolve().parents[2] / "db" / "migraciones" / "009_bonificacion_edad.sql"
CONSULTA = "tratamiento con sulfato ferroso y control de hemoglobina en el niño con anemia"
# (clave, texto, edad mínima, edad máxima, población): los tres primeros comparten más
# términos con la consulta que el del rango del paciente.
FRAGMENTOS = [
    ("menor_6", "Tratamiento con sulfato ferroso y control de hemoglobina en el niño menor de 6 meses con anemia.",
     0, 5, "NINO"),
    ("gestante", "Tratamiento con sulfato ferroso y control de hemoglobina en la gestante con anemia.",
     None, None, "GESTANTE"),
    ("escolar", "Tratamiento con sulfato ferroso y control de hemoglobina en el niño de 5 a 11 años con anemia.",
     60, 143, "NINO"),
    ("seis_a_35", "Sulfato ferroso para el niño de 6 a 35 meses, durante seis meses.", 6, 35, "NINO"),
    ("general", "Control de hemoglobina en la anemia.", None, None, "GENERAL"),
]


@pytest.fixture(scope="module")
def engine_generacion():
    url = os.environ.get("DATABASE_URL_GENERACION")
    if not url:
        pytest.fail("Falta DATABASE_URL_GENERACION en .env.test")
    return create_engine(url)


@pytest.fixture
def guia_con_edades(super_engine):
    id_doc = str(uuid.uuid4())
    ids = {clave: str(uuid.uuid4()) for clave, *_ in FRAGMENTOS}
    almacen = AlmacenMemoria()
    with super_engine.begin() as c:
        c.execute(text(
            """INSERT INTO conocimiento.documento_fuente
                 (id_documento, titulo, codigo_documento, entidad_emisora, tipo_documento, nivel, anio_publicacion,
                  idioma, cargado_por, estado_indexacion, ruta_blob, hash_archivo, total_fragmentos)
               VALUES (:id, 'Guía de prueba C2', 'PRUEBA-C2', 'MINSA', 'NORMA_TECNICA', 1, 2024, 'es', :u,
                       'COMPLETADA', 'local://prueba/c2.pdf', :h, :n)"""),
            {"id": id_doc, "u": SISTEMA, "h": uuid.uuid4().hex * 2, "n": len(FRAGMENTOS)})
        for orden, (clave, texto, emin, emax, pob) in enumerate(FRAGMENTOS, start=1):
            c.execute(text(
                """INSERT INTO conocimiento.fragmento
                     (id_fragmento, id_documento, numero_orden, seccion, pagina_inicio, pagina_fin, texto, numero_tokens,
                      modelo_embedding, vigente, edad_min_meses, edad_max_meses, poblacion, origen_rango)
                   VALUES (:id, :doc, :o, :s, 1, 1, :t, 30, 'falso', true, :emin, :emax, :pob, 'TITULO')"""),
                {"id": ids[clave], "doc": id_doc, "o": orden, "s": clave, "t": texto, "emin": emin, "emax": emax,
                 "pob": pob})
            almacen.agregar([RegistroVector(ids[clave], EmbedderFalso().embeber([texto])[0], texto, {
                "id_documento": id_doc, "nivel": 1, "estado_documento": "VIGENTE", "vigente": True, "idioma": "es"})])
    yield {"ids": ids, "almacen": almacen}
    with super_engine.begin() as c:
        c.execute(text("DELETE FROM conocimiento.fragmento WHERE id_documento = :id"), {"id": id_doc})
        c.execute(text("DELETE FROM conocimiento.documento_fuente WHERE id_documento = :id"), {"id": id_doc})


def _evaluados(engine, guia, peso: float, edad: int | None) -> list[str]:
    servicios = Servicios(EmbedderFalso(), RerankerFalso(), guia["almacen"], CacheBM25())
    with engine.connect() as c:
        p = replace(parametros_recuperacion(c), candidatos_reranker=2, bonificacion_edad=peso, umbral_relevancia=0.0)
        cand = buscar_candidatos(c, normalizar(CONSULTA), servicios, p, edad_meses=edad)
    nombres = {v: k for k, v in guia["ids"].items()}
    return [nombres[i] for i, _, _ in cand.fusionados if i in nombres][:p.candidatos_reranker]


def test_sin_bonificacion_el_rango_del_paciente_no_llega_al_reranker(engine_generacion, guia_con_edades):
    assert "seis_a_35" not in _evaluados(engine_generacion, guia_con_edades, 0.0, 20)


def test_con_bonificacion_sube_el_rango_del_paciente_y_bajan_gestante_y_otros_rangos(engine_generacion,
                                                                                       guia_con_edades):
    sin = _evaluados(engine_generacion, guia_con_edades, 0.0, 20)
    con = _evaluados(engine_generacion, guia_con_edades, 0.7, 20)
    assert "gestante" in sin and "general" not in sin
    assert con == ["seis_a_35", "general"]


def test_sin_edad_la_bonificacion_no_cambia_nada(engine_generacion, guia_con_edades):
    assert _evaluados(engine_generacion, guia_con_edades, 0.7, None) == \
        _evaluados(engine_generacion, guia_con_edades, 0.0, None)


def test_la_recuperacion_devuelve_el_grupo_etario(engine_generacion, guia_con_edades):
    servicios = Servicios(EmbedderFalso(), RerankerFalso(), guia_con_edades["almacen"], CacheBM25())
    with engine_generacion.connect() as c:
        p = replace(parametros_recuperacion(c), umbral_relevancia=0.0)
        r = recuperar(c, normalizar(CONSULTA), servicios, p, edad_meses=20)
    grupos = {f.id_fragmento: (f.edad_min_meses, f.edad_max_meses, f.poblacion) for f in r.fragmentos}
    assert grupos[guia_con_edades["ids"]["seis_a_35"]] == (6, 35, "NINO")
    assert grupos[guia_con_edades["ids"]["gestante"]] == (None, None, "GESTANTE")


def test_parametro_bonificacion_edad_vigente(engine_generacion):
    with engine_generacion.connect() as c:
        assert 0.0 <= parametros_recuperacion(c).bonificacion_edad <= 1.0


def test_migracion_008_es_idempotente(super_engine):
    sql = MIGRACION_008.read_text(encoding="utf-8")
    consulta = text("SELECT count(*) FROM configuracion.parametro_sistema "
                    "WHERE clave = 'BONIFICACION_EDAD' AND vigente_hasta IS NULL")
    with super_engine.begin() as c:
        antes = c.execute(consulta).scalar_one()
        c.exec_driver_sql(sql)
        c.exec_driver_sql(sql)
        assert c.execute(consulta).scalar_one() == antes == 1
        columnas = set(c.execute(text(
            """SELECT column_name FROM information_schema.columns
                WHERE table_schema = 'conocimiento' AND table_name = 'fragmento'""")).scalars())
    assert {"edad_min_meses", "edad_max_meses", "poblacion", "origen_rango", "rango_dudoso"} <= columnas


def test_migracion_009_deja_bonificacion_edad_en_0_7_con_historial(super_engine):
    sql = MIGRACION_009.read_text(encoding="utf-8")
    with super_engine.begin() as c:
        c.exec_driver_sql(sql)
        c.exec_driver_sql(sql)
        filas = c.execute(text(
            """SELECT valor, vigente_hasta IS NULL AS vigente FROM configuracion.parametro_sistema
                WHERE clave = 'BONIFICACION_EDAD' ORDER BY vigente_desde, id_parametro""")).all()
    assert [(f.valor, f.vigente) for f in filas] == [("0", False), ("0.7", True)]


def test_la_base_rechaza_un_rango_invertido_o_una_poblacion_desconocida(super_engine, guia_con_edades):
    from sqlalchemy.exc import IntegrityError
    for cambio in ("edad_min_meses = 40, edad_max_meses = 10", "poblacion = 'ADULTO'"):
        with pytest.raises(IntegrityError), super_engine.begin() as c:
            c.execute(text(f"UPDATE conocimiento.fragmento SET {cambio} WHERE id_fragmento = :i"),
                      {"i": guia_con_edades["ids"]["seis_a_35"]})


def test_metadatos_de_chromadb_con_el_grupo_etario():
    from app.indexador.chunker import Fragmento
    from app.indexador.indexacion import _metadatos
    from app.indexador.repositorio import Documento
    import inspect
    campos = {n: None for n in inspect.signature(Documento).parameters}
    documento = Documento(**{**campos, "id_documento": "d", "nivel": 1, "estado": "VIGENTE", "idioma": "es"})
    f = Fragmento("texto", "sección", 1, 1, "TEXTO", "CAPA_TEXTO", True, None, None, False, None,
                  edad_min_meses=24, edad_max_meses=59, poblacion="NINO")
    sin = Fragmento("texto", None, 1, 1, "TEXTO", "CAPA_TEXTO", True, None, None, False, None)
    assert {k: _metadatos(documento, f, 5)[k] for k in ("edad_min_meses", "edad_max_meses", "poblacion")} == \
        {"edad_min_meses": 24, "edad_max_meses": 59, "poblacion": "NINO"}
    assert (_metadatos(documento, sin, 5)["edad_min_meses"], _metadatos(documento, sin, 5)["poblacion"]) == (-1, "GENERAL")
