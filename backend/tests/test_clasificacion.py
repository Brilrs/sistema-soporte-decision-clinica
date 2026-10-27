"""2.3 · Cálculo clínico determinístico.

Los puntos de corte y el ajuste por altitud del catálogo están marcados [VERIFICAR]
y pueden corregirse. Por eso estas pruebas no escriben valores clínicos fijos: leen
los vigentes de configuracion y comprueban que el cálculo los aplique bien."""
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.core.db import engines
from app.services.clasificacion import clasificar, rango_edad_clasificable

PASO = Decimal("0.1")


@pytest.fixture(scope="module")
def conexion():
    with engines()["clinica"].connect() as c:
        yield c


@pytest.fixture(scope="module")
def umbrales(conexion):
    return conexion.execute(text(
        """SELECT u.id_umbral, u.edad_min_meses, u.edad_max_meses, u.hb_min_g_dl, u.hb_max_g_dl,
                  c.nombre AS categoria, c.nivel_riesgo
             FROM configuracion.umbral_hemoglobina u
             JOIN configuracion.categoria_anemia c ON c.id_categoria = u.id_categoria
            WHERE u.vigente_hasta IS NULL""")).mappings().all()


@pytest.fixture(scope="module")
def ajustes(conexion):
    return conexion.execute(text(
        """SELECT id_ajuste, altitud_min_msnm, altitud_max_msnm, ajuste_g_dl
             FROM configuracion.ajuste_altitud WHERE vigente_hasta IS NULL
            ORDER BY altitud_min_msnm""")).mappings().all()


def test_hay_parametros_vigentes(umbrales, ajustes):
    assert umbrales and ajustes


def test_cada_limite_de_cada_punto_de_corte_se_clasifica_en_su_categoria(conexion, umbrales, ajustes):
    """Para cada rango vigente: sus dos límites caen en su categoría y el valor
    inmediatamente fuera del límite cae en otra. Se prueba con todas las altitudes:
    la Hb observada es la ajustada más el ajuste del rango."""
    for aj in ajustes:
        altitud = aj["altitud_min_msnm"]
        for u in umbrales:
            for edad in (u["edad_min_meses"], u["edad_max_meses"]):
                casos = []
                if u["hb_min_g_dl"] is not None:
                    casos += [(u["hb_min_g_dl"], True), (u["hb_min_g_dl"] - PASO, False)]
                if u["hb_max_g_dl"] is not None:
                    casos += [(u["hb_max_g_dl"], True), (u["hb_max_g_dl"] + PASO, False)]
                for hb_ajustada, dentro in casos:
                    ev = clasificar(conexion, hb_ajustada + aj["ajuste_g_dl"], edad, altitud)
                    assert ev.clasificacion is not None, (u, aj, hb_ajustada, ev.motivo)
                    assert ev.clasificacion.hb_ajustada_g_dl == hb_ajustada
                    if dentro:
                        assert ev.clasificacion.categoria == u["categoria"], (u, aj, hb_ajustada)
                        assert ev.clasificacion.id_umbral == u["id_umbral"]
                        assert ev.clasificacion.nivel_riesgo == u["nivel_riesgo"]
                    else:
                        assert ev.clasificacion.categoria != u["categoria"], (u, aj, hb_ajustada)


def test_el_ajuste_aplicado_corresponde_al_rango_de_altitud(conexion, ajustes, umbrales):
    edad = umbrales[0]["edad_min_meses"]
    for aj in ajustes:
        for altitud in (aj["altitud_min_msnm"], aj["altitud_max_msnm"]):
            ev = clasificar(conexion, Decimal("12.0"), edad, altitud)
            c = ev.clasificacion
            assert c is not None, ev.motivo
            assert c.id_ajuste == aj["id_ajuste"]
            assert c.ajuste_hb_g_dl == aj["ajuste_g_dl"]
            assert c.hb_ajustada_g_dl == Decimal("12.0") - aj["ajuste_g_dl"]
            assert c.altitud_msnm == altitud


def test_altitud_de_un_distrito_del_catalogo(conexion, ajustes, umbrales):
    """La altitud del distrito de mayor altura del catálogo usa el ajuste de su rango."""
    altitud = conexion.execute(text("SELECT max(altitud_msnm) FROM clinico.distrito")).scalar()
    esperado = next(a for a in ajustes if a["altitud_min_msnm"] <= altitud <= a["altitud_max_msnm"])
    ev = clasificar(conexion, Decimal("12.0"), umbrales[0]["edad_min_meses"], altitud)
    assert ev.clasificacion.ajuste_hb_g_dl == esperado["ajuste_g_dl"]


def test_edades_fuera_de_los_puntos_de_corte_no_se_clasifican(conexion, ajustes):
    minima, maxima = rango_edad_clasificable(conexion)
    altitud = ajustes[0]["altitud_min_msnm"]
    for edad in (minima - 1, maxima + 1):
        if edad < 0:
            continue
        ev = clasificar(conexion, Decimal("11.0"), edad, altitud)
        assert ev.clasificacion is None
        assert "rango de edad" in ev.motivo
        assert f"{minima} a {maxima} meses" in ev.motivo


def test_sin_hemoglobina_no_se_clasifica(conexion, umbrales, ajustes):
    ev = clasificar(conexion, None, umbrales[0]["edad_min_meses"], ajustes[0]["altitud_min_msnm"])
    assert ev.clasificacion is None and ev.motivo == "Falta la hemoglobina"


def test_altitud_sin_rango_configurado(conexion, ajustes, umbrales):
    sin_rango = max(a["altitud_max_msnm"] for a in ajustes) + 1
    ev = clasificar(conexion, Decimal("11.0"), umbrales[0]["edad_min_meses"], sin_rango)
    assert ev.clasificacion is None and "altitud" in ev.motivo
