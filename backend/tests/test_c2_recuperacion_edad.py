"""Parte C2 sin base de datos ni modelos: recuadros de recomendación de la OMS, grupo
etario de los fragmentos, bonificación por edad en la fusión, edad escrita en la consulta,
variantes con bonificación y página de revisión de los grupos etarios."""
import pytest

from app.core.modelos import TokenizadorFalso
from app.indexador.chunker import SECCION_RECUADRO, fragmentar
from app.indexador.extraccion import PaginaTexto
from app.indexador.grupos_etarios import (ADOLESCENTE, GENERAL, GESTANTE, MANUAL, NINO, Reglas, asignar_grupos,
                                          cargar_reglas, combinar, grupo_de, motivo_dudoso,
                                          rangos_en)
from app.indexador.pagina_grupos import describir_rango, pagina_grupos
from app.indexador.segmentacion import TextoDocumento, segmentar
from app.rag.dominio import edad_mencionada_meses
from app.rag.recuperacion import ajustar_por_edad, signo_edad
from app.scripts.variantes_recuperacion import ACTUAL, Variante, evaluados, rejilla_edad

TOK = TokenizadorFalso()
EVIDENCIA = ("The quality of evidence for the critical outcomes was very low for anaemia and low for growth, using "
             "GRADE methodology. ")
RECOMENDACION = ("• Daily iron supplementation is recommended as a public health intervention in preschool-age "
                 "children aged 24–59 months, living in settings where anaemia is highly prevalent.")


# ---------------------------------------------------------------------------
# Recuadros de recomendación de la OMS
# ---------------------------------------------------------------------------
def _doc_oms() -> TextoDocumento:
    lineas = [EVIDENCIA] * 12 + [
        "The GRADE summary of findings table for children aged 24–59 months is shown in Annex 1B. Recommendation",
        RECOMENDACION, "The suggested scheme for daily iron supplementation is presented in Table B."]
    return TextoDocumento.desde_paginas([PaginaTexto(17, lineas)])


def test_el_recuadro_de_recomendacion_abre_su_propio_fragmento():
    doc = _doc_oms()
    fragmentos = fragmentar(segmentar(doc, []).segmentos, doc, TOK)
    recuadro = next(f for f in fragmentos if f.texto.startswith("Recommendation"))
    assert recuadro.texto.split("\n")[1].startswith("• Daily iron supplementation is recommended")
    assert recuadro.seccion.startswith(f"{SECCION_RECUADRO}: Daily iron supplementation is recommended")
    anterior = fragmentos[fragmentos.index(recuadro) - 1]
    assert anterior.texto.endswith("is shown in Annex 1B.") and "Recommendation" not in anterior.texto


def test_recommendations_dentro_de_una_frase_no_corta():
    doc = TextoDocumento.desde_paginas([PaginaTexto(1, [
        EVIDENCIA * 3, "using the Grading of Recommendations", "Assessment, Development and Evaluation methodology."])])
    fragmentos = fragmentar(segmentar(doc, []).segmentos, doc, TOK)
    assert len(fragmentos) == 1 and fragmentos[0].seccion is None


# ---------------------------------------------------------------------------
# Grupo etario
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("texto, rango", [
    ("2. Tratamiento en el niño y la niña menor de 6 meses de edad", (0, 5)),
    ("3. Tratamiento en el niño y la niña de 6 meses a 11 años de edad", (6, 143)),
    ("3. En el niño y la niña de 12 meses a 23 meses de edad", (12, 23)),
    ("4. En el niño y la niña de 24 a 59 meses", (24, 59)),
    ("5. En el niño y la niña de 5 a 11 años", (60, 143)),
    ("children aged 6–23 months", (6, 23)),
    ("school-age children aged 60 months and older", (60, 155)),
    ("Daily iron in preschool-age children", (24, 59)),
])
def test_rangos_de_edad_de_las_guias(texto, rango):
    assert rango in rangos_en(texto)


def test_grupo_desde_el_titulo_de_la_seccion():
    seccion = ("6.1.2. Acciones de recuperación > B. Tratamiento > 3. Tratamiento en el niño y la niña de 6 meses a "
               "11 años de edad | 6.1.2 B.3 y Tabla N° 17 Tratamiento de a...")
    g = grupo_de("rm251", seccion, "texto que no se lee para la NTS")
    assert (g.edad_min_meses, g.edad_max_meses, g.poblacion, g.origen, g.dudoso) == (6, 143, NINO, "TITULO", False)


def test_gestantes_adolescentes_y_tabla_general():
    assert grupo_de("rm251", "B > 5. Tratamiento en gestantes y puérperas", "").poblacion == GESTANTE
    adolescente = grupo_de("rm251", "B > 4. Tratamiento de el/la adolescente y mujer en edad fértil", "")
    assert adolescente.poblacion == ADOLESCENTE and adolescente.dudoso
    tabla20 = grupo_de("rm251", "B > 11. Seguimiento | Tabla N° 20 Control de hemoglobina en el niño y la niña, "
                                "el/la adolescente y mujer en edad fértil y gestante", "")
    assert (tabla20.poblacion, tabla20.edad_min_meses, tabla20.edad_max_meses) == (GENERAL, None, None)
    assert grupo_de("rm251", "A. Medición de hemoglobina", "").poblacion == GENERAL


def test_grupo_desde_el_texto_marca_dudosos():
    unico = grupo_de("oms2016", None, "Recommendation\n" + RECOMENDACION)
    assert (unico.edad_min_meses, unico.edad_max_meses, unico.dudoso) == (24, 59, False)
    varios = grupo_de("oms2016", None, "children aged 6–23 months and preschool children aged 24–59 months")
    assert (varios.edad_min_meses, varios.edad_max_meses, varios.dudoso) == (6, 59, True)


def test_correccion_manual_reemplaza_el_rango_calculado():
    reglas = Reglas({"oms2016": "TEXTO"}, [{"documento": "oms2016", "texto_contiene": "highly PREVALENT",
                                            "edad_min_meses": 24, "edad_max_meses": 59, "poblacion": NINO}])
    g = grupo_de("oms2016", None, "children aged 6–23 months ... settings where anaemia is highly prevalent", reglas)
    assert (g.edad_min_meses, g.edad_max_meses, g.origen, g.dudoso) == (24, 59, MANUAL, False)


def test_sin_edad_ni_poblacion_aplica_a_todos():
    g = combinar([], [], "TEXTO")
    assert (g.poblacion, g.edad_min_meses, g.edad_max_meses, g.dudoso) == (GENERAL, None, None, False)
    assert g.incluye(14) is None


def test_reglas_del_yaml_cubren_los_documentos_del_manifiesto():
    assert set(cargar_reglas().documentos) == {"rm251", "rm429", "oms2024", "oms2016"}


def test_asignar_grupos_completa_los_fragmentos():
    doc = TextoDocumento.desde_paginas([PaginaTexto(1, ["4. En el niño y la niña de 24 a 59 meses", EVIDENCIA * 2])])
    fragmentos = fragmentar(segmentar(doc, []).segmentos, doc, TOK)
    asignar_grupos(fragmentos, "rm251")
    assert (fragmentos[0].edad_min_meses, fragmentos[0].edad_max_meses, fragmentos[0].poblacion) == (24, 59, NINO)


# ---------------------------------------------------------------------------
# Bonificación por edad en la fusión
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("edad, minimo, maximo, poblacion, signo", [
    (20, 6, 143, NINO, 1), (20, 0, 5, NINO, -1), (49, 24, 59, NINO, 1), (49, 60, 143, NINO, -1),
    (20, None, None, GESTANTE, -1), (20, 144, 215, ADOLESCENTE, -1), (20, None, None, GENERAL, 0),
    (20, None, None, NINO, 0), (None, 0, 5, NINO, 0), (20, 6, None, NINO, 1),
])
def test_signo_de_la_bonificacion(edad, minimo, maximo, poblacion, signo):
    assert signo_edad(edad, minimo, maximo, poblacion) == signo


@pytest.mark.parametrize("edad, minimo, maximo, poblacion", [
    (20, 6, 143, NINO), (20, 0, 5, NINO), (20, None, None, GESTANTE), (20, 144, 215, ADOLESCENTE),
])
def test_un_rango_dudoso_sin_corregir_se_trata_como_general(edad, minimo, maximo, poblacion):
    assert signo_edad(edad, minimo, maximo, poblacion, rango_dudoso=True) == 0


def test_la_correccion_manual_devuelve_la_bonificacion_a_un_dudoso():
    texto = "Children 6-23 months and pregnant women should receive daily iron supplementation."
    calculado = grupo_de("oms2016", None, texto, Reglas({"oms2016": "TEXTO"}, []))
    assert calculado.dudoso
    assert signo_edad(30, calculado.edad_min_meses, calculado.edad_max_meses, calculado.poblacion,
                      calculado.dudoso) == 0
    manual = {"documento": "oms2016", "texto_contiene": "children 6-23 months and pregnant",
              "edad_min_meses": 6, "edad_max_meses": 23, "poblacion": NINO}
    corregido = grupo_de("oms2016", None, texto, Reglas({"oms2016": "TEXTO"}, [manual]))
    assert (corregido.origen, corregido.dudoso) == (MANUAL, False)
    assert signo_edad(30, corregido.edad_min_meses, corregido.edad_max_meses, corregido.poblacion,
                      corregido.dudoso) == -1
    assert signo_edad(12, corregido.edad_min_meses, corregido.edad_max_meses, corregido.poblacion,
                      corregido.dudoso) == 1


def test_la_bonificacion_sube_el_rango_del_paciente_y_baja_el_que_lo_excluye():
    fusion = [("b2_menor_6", 0.032), ("gestante", 0.031), ("seguimiento", 0.030), ("b3_6_a_11_anios", 0.0164)]
    signos = {"b2_menor_6": -1, "gestante": -1, "b3_6_a_11_anios": 1}
    ajustada = [i for i, _ in ajustar_por_edad(fusion, signos, 0.5)]
    assert ajustada == ["seguimiento", "b3_6_a_11_anios", "b2_menor_6", "gestante"]
    assert ajustar_por_edad(fusion, signos, 0.0) == fusion
    assert ajustar_por_edad(fusion, {}, 0.5) == fusion


def test_sin_filtro_duro_un_fragmento_que_excluye_la_edad_sigue_en_la_fusion():
    fusion = [("otro_rango", 0.05), ("general", 0.01)]
    assert [i for i, _ in ajustar_por_edad(fusion, {"otro_rango": -1}, 0.5)] == ["otro_rango", "general"]


@pytest.mark.parametrize("texto, meses", [
    ("¿Qué dosis le corresponde a un lactante de 8 meses?", 8), ("anemia moderada en un niño de 2 años", 24),
    ("niño menor de 6 meses nacido a término", None), ("¿Cómo se ajusta la hemoglobina por altitud?", None),
])
def test_edad_escrita_en_la_consulta(texto, meses):
    assert edad_mencionada_meses(texto) == meses


def test_variantes_con_bonificacion_por_edad():
    assert Variante.desde_nombre("20x60x1:1x8+b0.3") == Variante(bono_edad=0.3)
    assert Variante.desde_nombre("20x60x1:1x8+e+b0.5") == Variante(expansion=True, bono_edad=0.5)
    assert Variante(bono_edad=0.3).nombre == "20x60x1:1x8+b0.3" and ACTUAL.nombre == "20x60x1:1x8"
    consulta = {"bm25": [f"f{i}" for i in range(20)], "vectorial": [f"f{i}" for i in range(20)],
                "signos": {"f15": 1, "f0": -1}}
    assert "f15" not in evaluados(consulta, ACTUAL)
    assert evaluados(consulta, Variante(bono_edad=0.7))[0] == "f15"
    assert [v.bono_edad for v in rejilla_edad()] == [0.1, 0.2, 0.3, 0.5, 0.7]


# ---------------------------------------------------------------------------
# Página de revisión
# ---------------------------------------------------------------------------
def test_pagina_de_revision_pone_primero_los_dudosos():
    base = {"codigo": "OMS 2016", "paginas": "17-17", "seccion": None, "texto": "Texto", "poblacion": NINO,
            "origen_rango": "TEXTO"}
    filas = [{**base, "documento": "oms2016", "orden": 1, "edad_min_meses": 24, "edad_max_meses": 59,
              "rango_dudoso": False},
             {**base, "documento": "oms2016", "orden": 2, "edad_min_meses": 6, "edad_max_meses": 59,
              "rango_dudoso": True}]
    pagina = pagina_grupos(filas)
    assert pagina.index('id="oms2016-002"') < pagina.index('id="oms2016-001"')
    assert "1 dudosos" in pagina and "Rango correcto" in pagina and "<title>Revisión de grupos etarios</title>" in pagina
    assert describir_rango(None, None) == "sin límite de edad" and describir_rango(24, 59) == "24 a 59 meses"


def test_motivo_del_rango_dudoso_nombra_las_frases_y_el_rango_tomado():
    reglas = Reglas({"oms2016": "TEXTO", "rm251": "SECCION"}, [])
    texto = "Children 6-23 months and pregnant women should receive daily iron supplementation."
    motivo = motivo_dudoso("oms2016", None, texto, reglas)
    assert "El texto nombra el rango 6 a 23 meses («6-23 months»)" in motivo
    assert "gestantes o puérperas («pregnant»)" in motivo and motivo.endswith("Se tomó 6 a 23 meses, NINO.")
    varios = motivo_dudoso("oms2016", None, "Infants 6-11 months and children 24-59 months.", reglas)
    assert varios.startswith("El texto nombra 2 rangos de edad: 6 a 11 meses") and "6 a 59 meses" in varios
    assert motivo_dudoso("rm251", "6. Tratamiento > 6.1 En niños de 6 a 11 meses", "texto", reglas) is None
    manual = {"documento": "oms2016", "texto_contiene": "children 6-23", "edad_min_meses": 6, "edad_max_meses": 23,
              "poblacion": NINO}
    assert motivo_dudoso("oms2016", None, texto, Reglas({"oms2016": "TEXTO"}, [manual])) is None


def test_pagina_de_revision_muestra_origen_ruta_texto_imagen_y_filtro(tmp_path):
    (tmp_path / "paginas").mkdir()
    (tmp_path / "paginas" / "rm251-12.png").write_bytes(b"png")
    largo = "Hierro en gotas. " * 40
    filas = [
        {"documento": "rm251", "codigo": "RM 251-2024/MINSA", "titulo": "NTS 213", "orden": 7, "paginas": "12-13",
         "seccion": "6. Tratamiento > 6.1 Niños de 6 a 11 meses | Tabla 20", "texto": largo, "edad_min_meses": 6,
         "edad_max_meses": 11, "poblacion": NINO, "origen_rango": "TITULO", "rango_dudoso": False},
        {"documento": "oms2016", "codigo": "OMS 2016", "orden": 3, "paginas": "17-17", "seccion": None,
         "texto": "Children 6-23 months and pregnant women.", "edad_min_meses": 6, "edad_max_meses": 23,
         "poblacion": NINO, "origen_rango": "TEXTO", "rango_dudoso": True},
    ]
    pagina = pagina_grupos(filas, tmp_path, {"rm251": "rm251"})
    assert pagina.index('id="oms2016-003"') < pagina.index('id="rm251-007"')
    assert "NTS 213 · págs. 12 a 13 del PDF" in pagina
    assert "6. Tratamiento › 6.1 Niños de 6 a 11 meses | Tabla 20" in pagina
    assert 'src="paginas/rm251-12.png"' in pagina and "Falta la imagen paginas/rm251-13.png" in pagina
    assert pagina.count("<img ") == 1 and "Falta la imagen paginas/oms2016" not in pagina
    assert largo[:400] in pagina and "Ver completo" in pagina and '<span class="resto" hidden>' in pagina
    assert "<strong>Motivo:</strong>" in pagina and pagina.count('class="motivo"') == 1
    assert '<option value="rm251">RM 251-2024/MINSA (1, 0 dudosos)</option>' in pagina
    assert 'data-documento="oms2016"' in pagina and 'id="copiar"' in pagina and "Revisión de grupos etarios (" in pagina


def test_resumen_edad_por_conjunto():
    from app.scripts.medir_recuperacion import main, resumen_edad
    consultas = {"R01": {"acierta": True}, "R02": {"acierta": False}, "V01": {"acierta": True},
                 "V02": {"acierta": True}, "V03": {"acierta": False}}
    assert resumen_edad(consultas) == {"R": {"aciertos": 1, "total": 2, "fallan": ["R02"]},
                                       "V": {"aciertos": 2, "total": 3, "fallan": ["V03"]}}
    with pytest.raises(SystemExit):
        main(["edad", "--pesos", "0,x"])
