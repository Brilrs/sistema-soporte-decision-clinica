"""Indexador sin base de datos, sin modelos y sin PDF: limpieza de páginas,
tokens sospechosos, fragmentación, anclas de la RM 429-2024/MINSA,
transcripciones y valores críticos."""
import re

import pytest

from app.indexador.chunker import Avisos, fragmentar
from app.indexador.errores import ErrorAncla, ErrorIndexacion
from app.indexador.extraccion import PaginaTexto, detectar_sospechosos, limpiar_paginas
from app.indexador.indexacion import preparar
from app.indexador.informes import buscar_valor, cargar_valores, informe_valores
from app.indexador.modificaciones import (ConflictoDerivado, MapaModificaciones, Modificacion, TramoSustituido,
                                          cargar_mapa)
from app.indexador.segmentacion import Segmento, TextoDocumento, segmentar
from app.indexador.servicios import DIMENSION, EmbedderFalso, RerankerFalso, TokenizadorFalso
from app.indexador.transcripciones import DIR_TRANSCRIPCIONES, cargar_transcripciones, leer_transcripcion
from tests.indexador_util import fuente, paginas_de_prueba

TOK = TokenizadorFalso()


# ---------------------------------------------------------------------------
# Limpieza de páginas y tokens sospechosos
# ---------------------------------------------------------------------------
def test_limpieza_quita_encabezados_repetidos_numeracion_y_ruido():
    encabezado = ["NTS N° 213 /MINSA-DGIESP-2024", "NORMA TÉCNICA DE SALUD: PREVENCIÓN Y CONTROL DE LA ANEMIA"]
    cuerpos = ["Suplementación preventiva en gestantes.", "Tratamiento de la anemia severa.",
               "Consejería nutricional en el establecimiento.", "Medición de hemoglobina al año.",
               "Visita domiciliaria de seguimiento."]
    paginas = [PaginaTexto(n, encabezado + [c, "^?'°", "(•••)", str(n)]) for n, c in zip(range(4, 9), cuerpos)]
    limpias = limpiar_paginas(paginas)
    for p, c in zip(limpias, cuerpos):
        assert p.lineas == [c, "(...)"]


def test_limpieza_conserva_una_linea_que_no_se_repite():
    paginas = [PaginaTexto(n, ["Encabezado común de la norma técnica", f"Línea {n}"]) for n in range(1, 5)]
    paginas[0].lineas.insert(0, "Título que aparece una sola vez")
    assert "Título que aparece una sola vez" in limpiar_paginas(paginas)[0].lineas


@pytest.mark.parametrize("texto, patron", [
    ("De 6 a 23 meses <7.0 7.0-9.4 9.5-10.4 5.10.5", "cifra_con_dos_puntos"),
    ("De 5 a 11 años < 8.0 8.0-10.9 11.0-11.4 S 11.5", "letra_pegada_a_cifra"),
    ("Primer Trimestre < 7.0 7.0-9.9 10.0-10.9 i11.0", "letra_pegada_a_cifra"),
    ("si el valor es z 10.5g/dL, se indica", "letra_pegada_a_cifra"),
    ("la hemoglobina es s 12 g/dL, 2 veces por semana", "letra_pegada_a_cifra"),
    ("cuando la hemoglobina es 2 11.5 g/dL durante", "dos_por_mayor_igual"),
    ("Varones de 15 años a más < 8.0 8.0-10.9 11.0-12.9 SY3.0", "simbolo_extrano_en_cifra"),
    ("De 24 a 59 meses <7.0 7.0-9.9 10.0-10.9 >,11.0", "simbolo_extrano_en_cifra"),
    ("5a a 8va semana de vida S 8.0 >ao", "cifra_con_letra_o"),
])
def test_detecta_tokens_sospechosos(texto, patron):
    assert patron in detectar_sospechosos(texto)


@pytest.mark.parametrize("texto", [
    "5.4.4. Se considera reinicio de la suplementación",
    "se reinicia la indicación a 3 meses de iniciada",
    "De 6 a 23 meses < 7,0 7.0 - 9.4 9.5 - 10.4 ≥ 10.5",
    "dosis de 3 mg/kg/día durante 6 meses",
])
def test_no_marca_texto_correcto(texto):
    assert detectar_sospechosos(texto) == {}


# ---------------------------------------------------------------------------
# Servicios falsos
# ---------------------------------------------------------------------------
def test_embedder_falso_es_determinista_y_normalizado():
    a, b, c = EmbedderFalso().embeber(["hierro en niños", "hierro en niños", "clima de Lima"])
    assert len(a) == DIMENSION and a == b
    assert abs(sum(x * x for x in a) - 1.0) < 1e-9
    assert sum(x * y for x, y in zip(a, b)) > sum(x * y for x, y in zip(a, c))


def test_reranker_falso_premia_terminos_compartidos():
    alto, bajo = RerankerFalso().puntuar("dosis de hierro", ["dosis de hierro en gotas", "clima de Lima"])
    assert alto > bajo


# ---------------------------------------------------------------------------
# Fragmentación 500/800/80
# ---------------------------------------------------------------------------
def _documento_sintetico() -> TextoDocumento:
    frase = "El establecimiento de salud brinda la suplementación preventiva con hierro según la edad del paciente."
    lineas = ["V. DISPOSICIONES GENERALES", "5.1. Definiciones Operativas"]
    lineas += [frase] * 60
    lineas += ["5.2. Atención con pertinencia cultural"]
    lineas += [frase.replace("preventiva", "terapéutica")] * 10
    lineas += ["Tabla N° 2", "Dosis estandarizada de suplementos de hierro", "Edad Dosis Producto",
               "4-5 meses 6 gotas 11 gotas", "6-8 meses 7 gotas 13 gotas", "Fuente: Organización Mundial de la Salud"]
    lineas += ["5.3. Atención en los establecimientos de salud", frase]
    return TextoDocumento.desde_paginas([PaginaTexto(4, lineas[:40]), PaginaTexto(5, lineas[40:])])


def test_fragmentos_respetan_objetivo_maximo_y_solapamiento():
    doc = _documento_sintetico()
    seg = segmentar(doc, []).segmentos
    fragmentos = fragmentar(seg, doc, TOK, objetivo=500, maximo=800, solapamiento=80)
    textos = [f for f in fragmentos if f.tipo_contenido == "TEXTO"]
    assert all(f.numero_tokens <= 800 for f in textos)
    assert any(f.numero_tokens >= 500 for f in textos)
    largos = [f for f in textos if f.seccion and "5.1." in f.seccion]
    assert len(largos) >= 2
    # el inicio de cada fragmento de la sección repite el final del anterior (solapamiento)
    for previo, siguiente in zip(largos, largos[1:]):
        assert siguiente.texto.split(". ")[0] in previo.texto


def test_corta_en_numerales_y_no_a_mitad_de_frase():
    doc = _documento_sintetico()
    fragmentos = fragmentar(segmentar(doc, []).segmentos, doc, TOK)
    for f in fragmentos:
        if f.tipo_contenido == "TEXTO":
            assert f.texto.rstrip().endswith((".", ":", "GENERALES", "Operativas"))
            assert len(re.findall(r"^5\.\d\. ", f.texto, re.MULTILINE)) <= 1
    assert any(f.texto.startswith("5.2. Atención con pertinencia cultural") for f in fragmentos)


def test_tabla_queda_entera_en_un_fragmento():
    doc = _documento_sintetico()
    tablas = [f for f in fragmentar(segmentar(doc, []).segmentos, doc, TOK) if f.tipo_contenido == "TABLA"]
    assert len(tablas) == 1
    assert "4-5 meses 6 gotas" in tablas[0].texto and "6-8 meses 7 gotas" in tablas[0].texto
    assert "Tabla N° 2" in tablas[0].seccion


def _tabla_ocr(filas: int) -> TextoDocumento:
    lineas = [f"{n}-{n + 1} meses {n} gotas {n + 5} gotas sulfato ferroso complejo polimaltosado férrico diaria "
              "durante seis meses continuos en el año con control de hemoglobina" for n in range(filas)]
    return TextoDocumento.desde_paginas([PaginaTexto(1, ["Tabla N° 9", "Edad Dosis Producto Duración"] + lineas
                                                     + ["Fuente: MINSA"])])


def test_tabla_entre_el_maximo_y_el_limite_del_servicio_se_mantiene_entera():
    doc = _tabla_ocr(36)
    avisos = Avisos()
    fragmentos = fragmentar(segmentar(doc, []).segmentos, doc, TOK, avisos=avisos)
    assert len(fragmentos) == 1 and 800 < fragmentos[0].numero_tokens <= 1024
    assert any("se mantiene entera" in a for a in avisos.mensajes)


def test_tabla_mayor_al_limite_del_servicio_se_parte_por_filas_con_encabezado():
    doc = _tabla_ocr(60)
    avisos = Avisos()
    partes = fragmentar(segmentar(doc, []).segmentos, doc, TOK, avisos=avisos)
    assert len(partes) >= 2 and all(f.tipo_contenido == "TABLA" for f in partes)
    assert all(f.numero_tokens <= 1024 for f in partes)
    assert all(f.texto.startswith("Tabla N° 9\nEdad Dosis Producto Duración\n") for f in partes)
    assert "Fuente: MINSA" in partes[-1].texto and "Fuente: MINSA" not in partes[0].texto
    filas = [l for f in partes for l in f.texto.split("\n") if "gotas" in l]
    assert len(filas) == 60 and len(set(filas)) == 60
    assert [f.seccion.endswith(f"(parte {k} de {len(partes)})") for k, f in enumerate(partes, 1)] == [True] * len(partes)
    assert any("partida en" in a for a in avisos.mensajes)


# ---------------------------------------------------------------------------
# Anclas de las modificaciones
# ---------------------------------------------------------------------------
def _mapa(inicio: str, fin: str) -> MapaModificaciones:
    return MapaModificaciones(
        codigo="RM 429-2024/MINSA", documento_modificatorio="rm429", id_documento_modificatorio="id-429",
        documento_modificado="rm251",
        modificaciones=(Modificacion(1, "5.4.4", "modifica", (1, 1), 1, "^1", (TramoSustituido(1, 1, inicio, fin),)),),
    )


def _doc_anclas() -> TextoDocumento:
    return TextoDocumento.desde_paginas([PaginaTexto(1, [
        "5.4.3. Recomendaciones ante efectos adversos.",
        "5.4.4. Se considera reinicio cuando no se consumió por un periodo menor a 3 meses.",
        "5.4.5. Excepcionalmente, el técnico inicia la suplementación.",
    ])])


def test_ancla_unica_marca_el_texto_sustituido():
    r = segmentar(_doc_anclas(), [], _mapa(r"^5\.4\.4\.", r"menor a 3 meses\."), "modificado")
    sustituidos = [s for s in r.segmentos if not s.vigente]
    assert len(sustituidos) == 1
    assert sustituidos[0].texto.startswith("5.4.4.")
    assert sustituidos[0].motivo_exclusion == "Sustituido por RM 429-2024/MINSA, modificación N.° 1"
    assert sustituidos[0].id_documento_modificatorio == "id-429"
    assert all("periodo menor a 3 meses" not in s.texto for s in r.segmentos if s.vigente)


@pytest.mark.parametrize("inicio, fin, veces", [
    (r"^5\.4\.9\.", r"menor a 3 meses\.", 0),
    (r"^5\.4\.\d\.", r"menor a 3 meses\.", 3),
    (r"^5\.4\.4\.", r"tratamiento\.", 0),
])
def test_ancla_que_no_aparece_una_vez_da_error(inicio, fin, veces):
    with pytest.raises(ErrorAncla, match=f"aparece {veces} veces"):
        segmentar(_doc_anclas(), [], _mapa(inicio, fin), "modificado")


def test_tramos_superpuestos_dan_error():
    mapa = _mapa(r"^5\.4\.4\.", r"menor a 3 meses\.")
    mapa = MapaModificaciones(**{**mapa.__dict__, "modificaciones": mapa.modificaciones + (
        Modificacion(2, "5.4.4", "modifica", (1, 1), 1, "^2", (TramoSustituido(1, 1, r"Se considera", r"técnico"),)),
    )})
    with pytest.raises(ErrorIndexacion, match="Se superponen"):
        segmentar(_doc_anclas(), [], mapa, "modificado")


def test_conflicto_excluido_solo_quita_la_oracion():
    doc = TextoDocumento.desde_paginas([PaginaTexto(1, [
        "El niño con bajo peso inicia a los 30 días de nacido y termina a los 5 meses",
        "29 días. El niño a término inicia a los 4 meses.",
    ])])
    mapa = MapaModificaciones(
        codigo="RM 429-2024/MINSA", documento_modificatorio="rm429", id_documento_modificatorio="id-429",
        documento_modificado="rm251", modificaciones=(),
        conflictos=(ConflictoDerivado("B1", "Tabla 5", 6, 1, 1, r"y termina a los 5 meses\s*29 d[ií]as", True),),
    )
    r = segmentar(doc, [], mapa, "modificado")
    vigentes = [s.texto for s in r.segmentos if s.vigente]
    assert vigentes == ["El niño con bajo peso inicia a los 30 días de nacido. El niño a término inicia a los 4 meses."]
    excluido = next(s for s in r.segmentos if not s.vigente)
    assert excluido.texto == "y termina a los 5 meses\n29 días"
    assert excluido.motivo_exclusion.startswith("Conflicto derivado con RM 429-2024/MINSA, modificación N.° 6")


def test_mapa_rm429_tiene_las_12_modificaciones():
    mapa = cargar_mapa("rm429_2024.yaml")
    assert [m.numero for m in mapa.modificaciones] == list(range(1, 13))
    assert all(m.tramos for m in mapa.modificaciones)
    b1 = next(c for c in mapa.conflictos if c.id == "B1_termina_5_meses_29_dias")
    assert b1.excluir and b1.ancla == r"y termina a los 5 meses\s*29 d[ií]as"


def test_cada_modificacion_deja_un_fragmento_no_vigente_en_la_rm251():
    prep = preparar(fuente("rm251"), paginas_de_prueba("rm251"), TOK)
    mapa = cargar_mapa("rm429_2024.yaml")
    motivos = {f.motivo_exclusion for f in prep.fragmentos if not f.vigente}
    for m in mapa.modificaciones:
        assert mapa.motivo(m.numero) in motivos, f"La modificación {m.numero} no dejó fragmentos no vigentes"
    assert all(f.id_documento_modificatorio == mapa.id_documento_modificatorio
               for f in prep.fragmentos if not f.vigente)


def test_ningun_fragmento_vigente_de_la_rm251_contiene_las_anclas():
    prep = preparar(fuente("rm251"), paginas_de_prueba("rm251"), TOK)
    mapa = cargar_mapa("rm429_2024.yaml")
    vigentes = [f.texto for f in prep.fragmentos if f.vigente]
    for m in mapa.modificaciones:
        for t in m.tramos:
            # El ancla de inicio identifica el texto sustituido; las de fin pueden ser genéricas
            # (p. ej., la nota "(*) Alternativa al sulfato ferroso") y repetirse en otras tablas.
            assert not any(re.search(t.inicio, x, re.MULTILINE | re.IGNORECASE) for x in vigentes), \
                f"Modificación {m.numero}: '{t.inicio}' sigue en un fragmento vigente"
    for c in mapa.conflictos:
        if c.excluir:
            assert not any(re.search(c.ancla, x, re.IGNORECASE) for x in vigentes)


def test_rm429_queda_dividida_en_sus_modificaciones():
    prep = preparar(fuente("rm429"), paginas_de_prueba("rm429"), TOK)
    assert {f.modificacion for f in prep.fragmentos} == set(range(1, 13))
    assert all(f.vigente for f in prep.fragmentos)
    assert all(f.texto.startswith("NTS 213 modificada por RM 429-2024/MINSA, numeral ") for f in prep.fragmentos)
    tabla1 = next(f for f in prep.fragmentos if f.modificacion == 2)
    assert tabla1.seccion.startswith("5.3.2 Tabla 1") and tabla1.tipo_contenido == "TABLA"
    assert tabla1.fuente_texto == "TRANSCRIPCION" and "| 5000 - 5500 | 4.0 |" in tabla1.texto


# ---------------------------------------------------------------------------
# Transcripciones y valores críticos
# ---------------------------------------------------------------------------
def test_todas_las_transcripciones_tienen_encabezado_valido():
    for carpeta in ("rm251", "rm429"):
        transcripciones = cargar_transcripciones(carpeta)
        assert transcripciones
        for t in transcripciones:
            assert t.texto and t.tipo_contenido in ("TEXTO", "TABLA") and t.pagina <= t.pagina_fin


def test_transcripcion_sin_verificar_y_verificada(tmp_path):
    base = (DIR_TRANSCRIPCIONES / "rm251" / "tabla14_ferritina.md").read_text(encoding="utf-8")
    base = re.sub(r"^verificado_por:.*$", "verificado_por:", base, flags=re.MULTILINE)
    base = re.sub(r"^fecha_verificacion:.*$", "fecha_verificacion:", base, flags=re.MULTILINE)
    sin = tmp_path / "sin.md"
    sin.write_text(base, encoding="utf-8")
    con = tmp_path / "con.md"
    con.write_text(base.replace("verificado_por:\n", "verificado_por: Revisora\n")
                   .replace("fecha_verificacion:\n", "fecha_verificacion: 2026-11-05\n"), encoding="utf-8")
    assert not leer_transcripcion(sin).verificada
    assert leer_transcripcion(con).verificada


def test_las_transcripciones_reemplazan_la_zona_del_ocr():
    prep = preparar(fuente("rm251"), paginas_de_prueba("rm251"), TOK)
    transcritas = [f for f in prep.fragmentos if f.fuente_texto == "TRANSCRIPCION"]
    assert len(transcritas) == len(cargar_transcripciones("rm251"))
    vigentes_ocr = " ".join(f.texto for f in prep.fragmentos if f.vigente and f.fuente_texto == "CAPA_TEXTO")
    for basura in ("si la Hb es ¿ 10.5", "es z 10.5g/dL", "es 2 11.5 g/dL"):
        assert basura not in vigentes_ocr


@pytest.mark.parametrize("valor", cargar_valores(), ids=lambda v: v.id)
def test_valor_critico_en_su_transcripcion(valor):
    t = leer_transcripcion(DIR_TRANSCRIPCIONES / f"{valor.transcripcion}.md")
    assert buscar_valor(valor, t.texto), f"{valor.id}: no se encontró '{valor.regex}'"


def test_lista_de_comprobacion_incluye_pagina_e_imagen():
    from app.indexador.config import cargar_manifiesto
    informe = informe_valores(cargar_manifiesto("fuentes_iniciales.yaml"))
    assert "NO ENCONTRADO" not in informe
    assert informe.count("- [ ] **") == len(cargar_valores())
    assert "data/mediciones/paginas/rm429-07.png" in informe


def test_transcripcion_tabla_markdown_se_parte_repitiendo_el_encabezado():
    doc = TextoDocumento.desde_paginas([PaginaTexto(1, ["texto"])])
    cabecera = "Tabla N° 1\n| Rango | Ajuste |\n| --- | --- |\n"
    filas = "".join(f"| {n} - {n + 499} metros sobre el nivel del mar | {n / 1000:.1f} g/dL |\n" for n in range(0, 40000, 500))
    corta = Segmento(cabecera + filas[:200], 0, 5, 1, 1, tipo_contenido="TABLA", fuente_texto="TRANSCRIPCION")
    assert len(fragmentar([corta], doc, TOK)) == 1
    larga = Segmento(cabecera + filas + "Fuente: OMS 2024", 0, 5, 1, 1, tipo_contenido="TABLA",
                     fuente_texto="TRANSCRIPCION")
    partes = fragmentar([larga], doc, TOK)
    assert len(partes) >= 2
    assert all(f.texto.startswith(cabecera) and f.numero_tokens <= 1024 for f in partes)
    assert partes[-1].texto.endswith("Fuente: OMS 2024")


def test_pagina_de_verificacion_tiene_cada_transcripcion_con_imagen_y_valores(tmp_path):
    from app.indexador.config import cargar_manifiesto
    from app.indexador.pagina_verificacion import pagina_verificacion
    (tmp_path / "paginas").mkdir()
    (tmp_path / "paginas" / "rm429-04.png").write_bytes(b"")
    pagina = pagina_verificacion(cargar_manifiesto("fuentes_iniciales.yaml"), tmp_path)
    total = len(cargar_transcripciones("rm251")) + len(cargar_transcripciones("rm429"))
    assert pagina.count('<section id="') == total
    assert pagina.count('type="checkbox"') == total and pagina.count("<textarea") == total
    assert 'src="paginas/rm429-04.png"' in pagina and "Falta la imagen paginas/rm251-12.png" in pagina
    assert "<mark>| 5000 - 5500 | 4.0 |</mark>" in pagina
    assert "no se encontró en la transcripción" not in pagina
    assert "localStorage" in pagina and 'id="copiar"' in pagina
