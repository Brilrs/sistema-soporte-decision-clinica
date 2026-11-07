"""Recuperación con los modelos reales y la base indexada (marca lenta, fuera de CI).
Se ejecutan dentro de la red de Docker, donde están los servicios modelos y chromadb
(ver jobs/README.md):

    docker compose run --rm -e DATABASE_URL_GENERACION=... -v ./backend:/app jobs \\
        sh -c "pip install -q --user pytest && python -m pytest -q -m lenta tests/test_rag_lento.py"

Necesitan DATABASE_URL_GENERACION, MODELOS_URL y CHROMA_URL. Miden las consultas de
ajuste (con su objetivo), el conjunto de validación y el conjunto de prueba final
(B2), que solo informan su tasa de acierto, y comprueban que cada sección esperada
exista en las guías indexadas. Usan los parámetros vigentes; para evaluar otra configuración del reranker sin cambiar la base se pueden
fijar PRUEBA_CANDIDATOS_RERANKER y PRUEBA_MAX_LONGITUD_RERANKER."""
import os
from dataclasses import replace

import httpx
import pytest
from sqlalchemy import create_engine, text

from app.core.modelos import ClienteModelos, EmbedderHttp, RerankerHttp
from app.core.vectores import AlmacenChroma
from app.rag.bm25 import CONDICION_RECUPERABLE, CacheBM25
from app.rag.normalizacion import normalizar
from app.rag.parametros import parametros_recuperacion
from app.rag.recuperacion import Servicios, recuperar
from app.rag.referencias import VALIDACION, cargar_conjunto_prueba, cargar_consultas_referencia

pytestmark = pytest.mark.lenta
OBJETIVO_TOP5 = 0.8
# Piso de control para los conjuntos que no se usan para ajustar: detecta una
# recuperación rota, no es un objetivo de calidad.
PISO_SIN_AJUSTE = 0.3


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


def _tasa(motor, servicios, parametros, referencias):
    with motor.connect() as c:
        aciertos = {ref.id: any(ref.acierta(f) for f in recuperar(c, normalizar(ref.consulta), servicios,
                                                                    parametros).fragmentos[:5])
                    for ref in referencias}
    return sum(aciertos.values()) / len(aciertos), sorted(i for i, ok in aciertos.items() if not ok)


@pytest.mark.parametrize("nombre", ["validacion", "prueba"])
def test_tasa_de_acierto_de_los_conjuntos_sin_ajuste(entorno, nombre):
    motor, servicios, parametros = entorno
    referencias = cargar_consultas_referencia(VALIDACION) if nombre == "validacion" else cargar_conjunto_prueba()
    tasa, fallos = _tasa(motor, servicios, parametros, referencias)
    print(f"\n{nombre}: acierto en el top 5 {tasa:.2f} ({len(referencias) - len(fallos)} de {len(referencias)}); "
          f"fallan: {fallos}")
    assert tasa >= PISO_SIN_AJUSTE, fallos


# Secciones esperadas de la NTS cuyo texto sustituyó la RM 429 (no vigente): con las
# etiquetas desplazadas de la versión 3 coincidían con otro contenido. Las consultas
# tienen además la sección de la RM 429, que sí existe.
SUSTITUIDAS_POR_LA_RM429 = {("V06", "5.4.2. Cuando la adherencia al sulfato ferroso"), ("V09", "5.4.5. Excepcionalmente"),
                            ("V11", "E. Realizar sesiones educativas y demostrativas")}


def test_cada_seccion_esperada_existe_en_las_guias_indexadas(entorno):
    motor, _, _ = entorno
    with motor.connect() as c:
        filas = c.execute(text(
            f"""SELECT d.codigo_documento, f.seccion, f.texto, f.pagina_inicio, f.pagina_fin
                  FROM conocimiento.fragmento f JOIN conocimiento.documento_fuente d ON d.id_documento = f.id_documento
                 WHERE {CONDICION_RECUPERABLE}""")).all()
    referencias = [*cargar_consultas_referencia(), *cargar_consultas_referencia(VALIDACION), *cargar_conjunto_prueba()]
    sin_fragmento = {(ref.id, e.seccion_contiene or e.texto_contiene) for ref in referencias for e in ref.esperado
                     if not any(e.cumple(f.codigo_documento, f.seccion, f.texto, f.pagina_inicio, f.pagina_fin)
                                for f in filas)}
    assert sin_fragmento == SUSTITUIDAS_POR_LA_RM429
    assert all(len([e for e in ref.esperado if (ref.id, e.seccion_contiene or e.texto_contiene) not in sin_fragmento])
               for ref in referencias)
