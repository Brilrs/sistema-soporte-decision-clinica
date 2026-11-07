"""Recuperación con los modelos reales y la base indexada (marca lenta, fuera de CI).
Se ejecutan dentro de la red de Docker, donde están los servicios modelos y chromadb
(ver jobs/README.md):

    docker compose run --rm -e DATABASE_URL_GENERACION=... -v ./backend:/app jobs \\
        sh -c "pip install -q --user pytest && python -m pytest -q -m lenta tests/test_rag_lento.py"

Necesitan DATABASE_URL_GENERACION, MODELOS_URL y CHROMA_URL. Usan los parámetros
vigentes; para evaluar otra configuración del reranker sin cambiar la base se pueden
fijar PRUEBA_CANDIDATOS_RERANKER y PRUEBA_MAX_LONGITUD_RERANKER."""
import os
from dataclasses import replace

import httpx
import pytest
from sqlalchemy import create_engine

from app.core.modelos import ClienteModelos, EmbedderHttp, RerankerHttp
from app.core.vectores import AlmacenChroma
from app.rag.bm25 import CacheBM25
from app.rag.normalizacion import normalizar
from app.rag.parametros import parametros_recuperacion
from app.rag.recuperacion import Servicios, recuperar
from app.rag.referencias import cargar_consultas_referencia

pytestmark = pytest.mark.lenta
OBJETIVO_TOP5 = 0.8


@pytest.fixture(scope="module")
def entorno():
    faltan = [v for v in ("DATABASE_URL_GENERACION", "MODELOS_URL", "CHROMA_URL") if not os.environ.get(v)]
    if faltan:
        pytest.skip(f"Faltan {', '.join(faltan)}")
    cliente = ClienteModelos(os.environ["MODELOS_URL"], timeout_s=1800)
    try:
        cliente.salud()
    except httpx.HTTPError:
        pytest.skip("El servicio modelos no responde (estas pruebas corren dentro de la red de Docker)")
    servicios = Servicios(EmbedderHttp(cliente), RerankerHttp(cliente), AlmacenChroma(os.environ["CHROMA_URL"]),
                          CacheBM25())
    motor = create_engine(os.environ["DATABASE_URL_GENERACION"])
    with motor.connect() as c:
        parametros = parametros_recuperacion(c)
    if os.environ.get("PRUEBA_CANDIDATOS_RERANKER"):
        parametros = replace(parametros, candidatos_reranker=int(os.environ["PRUEBA_CANDIDATOS_RERANKER"]))
    if os.environ.get("PRUEBA_MAX_LONGITUD_RERANKER"):
        parametros = replace(parametros, max_longitud_reranker=int(os.environ["PRUEBA_MAX_LONGITUD_RERANKER"]))
    print(f"\nReranker: {parametros.candidatos_reranker} candidatos de hasta {parametros.max_longitud_reranker} tokens")
    return motor, servicios, parametros


@pytest.fixture(scope="module")
def resultados(entorno):
    motor, servicios, parametros = entorno
    salida = {}
    with motor.connect() as c:
        for ref in cargar_consultas_referencia():
            salida[ref.id] = (ref, recuperar(c, normalizar(ref.consulta), servicios, parametros))
    return salida


def test_tasa_de_acierto_en_el_top5_de_las_consultas_de_referencia(resultados):
    aciertos = {i: any(ref.acierta(f) for f in r.fragmentos[:5]) for i, (ref, r) in resultados.items()}
    tasa = sum(aciertos.values()) / len(aciertos)
    fallos = sorted(i for i, ok in aciertos.items() if not ok)
    print(f"\nAcierto en el top 5: {tasa:.2f} ({sum(aciertos.values())} de {len(aciertos)}); fallan: {fallos}")
    assert tasa >= OBJETIVO_TOP5, f"tasa {tasa:.2f} bajo el objetivo {OBJETIVO_TOP5}; fallan {fallos}"


def test_consulta_en_espanol_recupera_un_fragmento_en_ingles_de_la_oms(resultados):
    ref, r = resultados["R18"]
    ingles = [f for f in r.fragmentos[:5] if f.idioma == "en" and f.codigo_documento == "OMS 2024"]
    assert ingles, [f.codigo_documento for f in r.fragmentos[:5]]
    assert any(ref.acierta(f) for f in ingles)
