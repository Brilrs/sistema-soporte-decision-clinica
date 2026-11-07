"""Pruebas lentas del indexador (marca lenta, fuera de CI): usan los PDF reales de
data/guias y, para los valores críticos, los fragmentos ya indexados en la base
que indique DATABASE_URL_INDEXADOR. Se ejecutan con: pytest -m lenta"""
import os
import re

import pytest
from sqlalchemy import create_engine, text

from app.indexador.config import cargar_config, cargar_manifiesto
from app.indexador.extraccion import extraer_pdf
from app.indexador.indexacion import preparar
from app.indexador.informes import buscar_valor, cargar_valores, informe_extraccion, seccion_documento
from app.indexador.modificaciones import cargar_mapa
from app.core.modelos import TokenizadorFalso

pytestmark = pytest.mark.lenta

CONFIG = cargar_config()
FUENTES = cargar_manifiesto("fuentes_iniciales.yaml")
CUERPO = {"rm251": (4, 36), "rm429": (4, 11)}


def _pdf(fuente):
    ruta = CONFIG.dir_guias / fuente.archivo
    if not ruta.is_file():
        pytest.skip(f"Falta {ruta} (los PDF no se versionan)")
    return ruta


@pytest.fixture(scope="module")
def preparados():
    resultado = {}
    for f in FUENTES:
        inicio, fin = CUERPO.get(f.clave, (None, None))
        resultado[f.clave] = (f, preparar(f, extraer_pdf(_pdf(f), inicio, fin, f.recorte), TokenizadorFalso()))
    return resultado


def test_los_cuatro_pdf_se_extraen_y_fragmentan(preparados):
    for clave, (_, prep) in preparados.items():
        assert prep.fragmentos, clave
        assert all(f.texto.strip() for f in prep.fragmentos)


def test_pdf_real_cada_modificacion_deja_fragmentos_no_vigentes(preparados):
    _, prep = preparados["rm251"]
    mapa = cargar_mapa("rm429_2024.yaml")
    motivos = {f.motivo_exclusion for f in prep.fragmentos if not f.vigente}
    assert all(mapa.motivo(m.numero) in motivos for m in mapa.modificaciones)
    vigentes = [f.texto for f in prep.fragmentos if f.vigente]
    for m in mapa.modificaciones:
        for t in m.tramos:
            assert not any(re.search(t.inicio, x, re.MULTILINE | re.IGNORECASE) for x in vigentes)


def test_las_guias_oms_quedan_en_ingles_sin_transcripciones(preparados):
    for clave in ("oms2024", "oms2016"):
        _, prep = preparados[clave]
        assert not prep.transcripciones
        assert any("haemoglobin" in f.texto.lower() or "iron" in f.texto.lower() for f in prep.fragmentos)


def test_informe_de_comparacion(preparados, tmp_path):
    secciones = [seccion_documento(f, f.clave, prep, 800) for f, prep in preparados.values()]
    informe = informe_extraccion(secciones, "falso")
    for clave in preparados:
        assert f"(`{clave}`)" in informe
    assert "Anclas de las modificaciones" in informe and "Conflictos derivados" in informe
    (tmp_path / "a2_extraccion.md").write_text(informe, encoding="utf-8")


@pytest.fixture(scope="module")
def fragmentos_indexados():
    url = os.environ.get("DATABASE_URL_INDEXADOR")
    if not url:
        pytest.skip("Falta DATABASE_URL_INDEXADOR de la base con las guías indexadas")
    engine = create_engine(url)
    por_documento = {}
    with engine.connect() as c:
        for f in FUENTES:
            if f.clave not in CUERPO:
                continue
            estado = c.execute(text("SELECT estado_indexacion FROM conocimiento.documento_fuente WHERE id_documento = :id"),
                               {"id": f.id_documento}).scalar()
            if estado != "COMPLETADA":
                pytest.skip(f"{f.clave} no está indexado en esa base (estado {estado})")
            por_documento[f.transcripciones] = list(c.execute(text(
                """SELECT texto FROM conocimiento.fragmento
                    WHERE id_documento = :id AND vigente AND fuente_texto = 'TRANSCRIPCION'
                      AND version_indexacion = (SELECT max(version_indexacion) FROM conocimiento.fragmento
                                                 WHERE id_documento = :id)"""
            ), {"id": f.id_documento}).scalars())
    return por_documento


@pytest.mark.parametrize("valor", cargar_valores(), ids=lambda v: v.id)
def test_valor_critico_en_los_fragmentos_indexados(valor, fragmentos_indexados):
    textos = fragmentos_indexados[valor.transcripcion.split("/")[0]]
    assert any(buscar_valor(valor, t) for t in textos), f"{valor.id} no está en ningún fragmento vigente indexado"
