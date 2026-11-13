"""Decisiones de la revisión de grupos etarios (Brii, 2026-11-12) en grupos_etarios.yaml.

Las pruebas rápidas comprueban el YAML y las reglas. La prueba lenta comprueba los id
contra la fragmentación real: data/mediciones/grupos_etarios.json, que genera
`python -m app.indexador grupos-etarios` con el tokenizador del servicio modelos (la
misma fragmentación que la indexación)."""
import json
from types import SimpleNamespace

import pytest

from app.indexador.config import cargar_config
from app.indexador.grupos_etarios import (GENERAL, MANUAL, NINO, Reglas, asignar_grupos, cargar_reglas,
                                          coincide_inicio, grupo_de, id_fragmento)

GENERALES = ["rm429-005", "rm429-011", "rm429-012", "oms2016-001", "oms2016-003", "oms2016-005", "oms2016-006",
             "oms2016-012", "oms2016-014"]
NINO_24_59 = ["oms2016-008"]
CONFIRMADOS = ["rm251-038", "rm251-060", "rm251-062", "rm429-003", "rm429-007", "rm429-008", "oms2016-002",
               "oms2016-025"]
REVISADOS = GENERALES + NINO_24_59 + CONFIRMADOS


def test_el_yaml_tiene_exactamente_las_decisiones_de_la_revision():
    reglas = cargar_reglas()
    assert sorted(reglas.fragmentos) == sorted(REVISADOS)
    for i in GENERALES:
        e = reglas.fragmentos[i]
        assert (e["poblacion"], e.get("edad_min_meses"), e.get("edad_max_meses")) == (GENERAL, None, None), i
    e = reglas.fragmentos["oms2016-008"]
    assert (e["edad_min_meses"], e["edad_max_meses"], e["poblacion"]) == (24, 59, NINO)
    assert all(reglas.fragmentos[i].get("confirmado") is True for i in CONFIRMADOS)
    assert reglas.documentos["oms2024"] == GENERAL


def test_oms2024_queda_general_sin_rango_ni_dudoso_aunque_el_texto_nombre_poblaciones():
    texto = "Pregnant women, adolescents aged 10-19 years and women of reproductive age 15-49 years were sampled."
    assert grupo_de("oms2024", None, texto, orden=14) == grupo_de("oms2024", None, "Methods.")
    g = grupo_de("oms2024", None, texto, orden=14)
    assert (g.edad_min_meses, g.edad_max_meses, g.poblacion, g.origen, g.dudoso) == (None, None, GENERAL, MANUAL, False)


def _fragmento(orden, texto, seccion=None):
    return SimpleNamespace(orden=orden, texto=texto, seccion=seccion)


def test_la_correccion_por_fragmento_exige_el_mismo_comienzo_del_texto():
    texto = "Children 6-23 months and pregnant women should receive iron."
    reglas = Reglas({"oms2016": "TEXTO"}, [], {
        "oms2016-004": {"id": "oms2016-004", "inicio": "CHILDREN  6-23 months", "poblacion": GENERAL},
        "oms2016-009": {"id": "oms2016-009", "inicio": "Otro comienzo", "confirmado": True},
        "oms2016-030": {"id": "oms2016-030", "inicio": "No existe", "poblacion": GENERAL},
    })
    fragmentos = [_fragmento(4, texto), _fragmento(9, texto)]
    assert asignar_grupos(fragmentos, "oms2016", reglas) == ["oms2016-009", "oms2016-030"]
    corregido, sin_aplicar = fragmentos
    assert (corregido.poblacion, corregido.origen_rango, corregido.rango_dudoso) == (GENERAL, MANUAL, False)
    assert (sin_aplicar.origen_rango, sin_aplicar.rango_dudoso) == ("TEXTO", True)


def test_confirmado_conserva_el_rango_calculado_sin_marca_de_dudoso():
    texto = "Children 6-23 months and pregnant women should receive iron."
    reglas = Reglas({"oms2016": "TEXTO"}, [], {
        "oms2016-004": {"id": "oms2016-004", "inicio": "Children 6-23", "confirmado": True}})
    calculado = grupo_de("oms2016", None, texto, Reglas({"oms2016": "TEXTO"}, []))
    confirmado = grupo_de("oms2016", None, texto, reglas, orden=4)
    assert calculado.dudoso and not confirmado.dudoso and confirmado.origen == MANUAL
    assert (confirmado.edad_min_meses, confirmado.edad_max_meses, confirmado.poblacion) == (6, 23, NINO)


def test_un_yaml_mal_formado_se_rechaza(tmp_path):
    base = "documentos: {oms2016: TEXTO}\nmanuales: []\nfragmentos:\n"
    casos = ['  - {id: oms2016-4, inicio: "x", poblacion: GENERAL}\n',
             '  - {id: oms2016-004, poblacion: GENERAL}\n',
             '  - {id: oms2016-004, inicio: "x", confirmado: true, poblacion: NINO}\n',
             '  - {id: oms2016-004, inicio: "x", poblacion: OTRA}\n',
             '  - {id: oms2016-004, inicio: "x", poblacion: GENERAL}\n  - {id: oms2016-004, inicio: "y", poblacion: NINO}\n']
    for k, caso in enumerate(casos):
        ruta = tmp_path / f"r{k}.yaml"
        ruta.write_text(base + caso, encoding="utf-8")
        with pytest.raises(ValueError):
            cargar_reglas(ruta)
    ruta = tmp_path / "modo.yaml"
    ruta.write_text("documentos: {oms2016: TODO}\nmanuales: []\n", encoding="utf-8")
    with pytest.raises(ValueError):
        cargar_reglas(ruta)


@pytest.mark.lenta
def test_fragmentacion_real_cada_id_existe_ninguno_dudoso_y_oms2024_general():
    ruta = cargar_config().dir_mediciones / "grupos_etarios.json"
    if not ruta.is_file():
        pytest.skip(f"Falta {ruta}: genérelo con python -m app.indexador grupos-etarios")
    filas = {id_fragmento(f["documento"], f["orden"]): f for f in json.loads(ruta.read_text(encoding="utf-8"))}
    reglas = cargar_reglas()
    for i, entrada in reglas.fragmentos.items():
        assert i in filas, f"{i} no existe en la fragmentación real"
        f = filas[i]
        assert coincide_inicio(entrada, f["texto"]), f"{i} ya no empieza con «{entrada['inicio']}»"
        g = grupo_de(f["documento"], f["seccion"], f["texto"], reglas, f["orden"])
        assert g.origen == MANUAL and not g.dudoso, i
    oms2024 = [f for f in filas.values() if f["documento"] == "oms2024"]
    assert oms2024
    for f in oms2024:
        g = grupo_de("oms2024", f["seccion"], f["texto"], reglas, f["orden"])
        assert (g.edad_min_meses, g.edad_max_meses, g.poblacion, g.dudoso) == (None, None, GENERAL, False)
    # El JSON se generó con estas reglas: lo guardado coincide con lo que se calcula ahora.
    for i in [*reglas.fragmentos, *(id_fragmento("oms2024", f["orden"]) for f in oms2024)]:
        f = filas[i]
        g = grupo_de(f["documento"], f["seccion"], f["texto"], reglas, f["orden"])
        assert (f["edad_min_meses"], f["edad_max_meses"], f["poblacion"], f["rango_dudoso"]) == \
            (g.edad_min_meses, g.edad_max_meses, g.poblacion, g.dudoso), f"{i}: regenere la página"
