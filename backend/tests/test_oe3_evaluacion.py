"""OE3: job de evaluación (docs/diseno_evaluacion_oe3.md). Sin base de datos ni red: conjunto y
esquema, emparejamiento de criterios, CUE, corrección, cuadrantes, juez con caché e informe. Las
pruebas que necesitan RAGAS están en test_oe3_ragas.py (solo corren en la imagen de evaluación)."""
import copy
import json
import shutil
from pathlib import Path

import pytest
import yaml

from app.evaluacion import cue, dataset, informe, juzgar
from app.evaluacion import prompts_juez as pj
from app.evaluacion.dataset import Alternativa, Criterio
from app.evaluacion.extraer import texto_respuesta
from app.evaluacion.juez import (ConfiguracionJuez, ErrorJuez, Juez, JuezAnthropic, JuezFalso, RespuestaJuez,
                                 costo_usd)

RAIZ = Path(__file__).resolve().parents[2]
CONJUNTO = RAIZ / "jobs" / "evaluacion_oe3" / "conjunto"
NTS, RM, OMS = "NTS 213-MINSA/DGIESP-2024", "RM 429-2024/MINSA", "OMS 2024"


def frag(etiqueta, documento, texto, pagina=(10, 10), vigente=True, idioma="es", enviado=True):
    return cue.Fragmento(etiqueta, f"id-{etiqueta}", documento, pagina[0], pagina[1], texto, vigente, enviado, idioma)


def alt(documento, texto, paginas=(10, 10), pendiente=False):
    return Alternativa(documento, paginas, "x", texto, pendiente)


# ---------------------------------------------------------------------------
# Conjunto y esquema
# ---------------------------------------------------------------------------
PILOTO_ORIGINAL = frozenset(f"OE3-P{i:02d}" for i in range(1, 13))
# Revisión de la coordinación CRED (ficha firmada el 27/11/2026): los 48, «De acuerdo».
CARGO_REVISOR = "Coordinador CRED, Centro de Salud San Luis"
FECHA_REVISION = "2026-11-27"
# Composición de los 48 casos (docs/diseno_evaluacion_oe3.md, sección 9).
COMPOSICION = {
    "sin_anemia": [1, 9, 11, 13, 14, 15, 16, 17],
    "leve": [2, 10, 18, 19, 20, 21, 22, 23],
    "moderada": [3, 4, 24, 25, 26, 27, 28, 29],
    "severa_con_derivacion": [5, 6, 12, 30, 31, 32, 33, 34],
    "calendario_hb": [35, 36, 37, 38, 39, 40],
    "evidencia_insuficiente": [7, 41, 42, 43, 44, 45],
    "fuera_de_dominio": [8, 46, 47, 48],
}


@pytest.fixture(scope="module")
def conjunto48():
    """Toda la carpeta evaluacion/ (grupo por omisión): los 12 casos que vienen del piloto y los 36
    que lo completan (P13 a P48), revisados por la coordinación CRED."""
    return dataset.cargar_conjunto(CONJUNTO)


@pytest.fixture(scope="module")
def piloto():
    """Los 12 casos que vienen del piloto (P01 a P12), ahora en evaluacion/; la huella sigue
    cubriendo toda la carpeta."""
    return dataset.cargar_conjunto(CONJUNTO, "evaluacion", set(PILOTO_ORIGINAL))


@pytest.fixture(scope="module")
def esquema():
    return json.loads((CONJUNTO / dataset.ESQUEMA).read_text(encoding="utf-8"))


def test_los_casos_del_piloto_cargan_desde_evaluacion_con_huella(piloto):
    assert len(piloto.casos) == 12 and piloto.grupo == "evaluacion"
    assert [c.id for c in piloto.casos] == [f"OE3-P{i:02d}" for i in range(1, 13)]
    archivos = sorted((CONJUNTO / "evaluacion").glob("*.yaml"))
    def con_lf(ruta):
        return ruta.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")

    lineas = "".join(f"{p.name}  {dataset.sha256(con_lf(p))}\n" for p in archivos)
    assert piloto.huella == dataset.sha256(lineas.encode())
    assert piloto.manifiesto()["casos"] == 12 and len(piloto.huellas) == len(archivos) == 48
    for c in piloto.casos:
        assert piloto.huellas[c.archivo] == dataset.sha256(con_lf(CONJUNTO / "evaluacion" / c.archivo))


def test_el_grupo_por_omision_es_evaluacion_y_el_piloto_quedo_sin_casos(conjunto48):
    assert dataset.GRUPO_DEFECTO == "evaluacion" and conjunto48.grupo == "evaluacion"
    assert set(dataset.GRUPOS) == {"piloto", "evaluacion"}
    assert not list((CONJUNTO / "piloto").glob("*.yaml"))
    with pytest.raises(dataset.ErrorConjunto, match="No hay casos"):
        dataset.cargar_conjunto(CONJUNTO, "piloto")


def test_la_cli_usa_evaluacion_por_omision(capsys):
    from app.evaluacion.__main__ import main
    assert main(["validar", "--conjunto", str(CONJUNTO)]) == 0
    manifiesto = json.loads(capsys.readouterr().out)
    assert manifiesto["grupo"] == "evaluacion" and manifiesto["casos"] == 48


def test_los_48_casos_tienen_ids_unicos_y_la_composicion_del_diseno(conjunto48):
    ids = [c.id for c in conjunto48.casos]
    assert len(ids) == 48 and len(set(ids)) == 48
    assert ids == [f"OE3-P{i:02d}" for i in range(1, 49)]
    grupos = {i: g for g, ns in COMPOSICION.items() for i in ns}
    assert sorted(grupos) == list(range(1, 49))  # cada caso en un solo grupo
    assert [len(ns) for ns in COMPOSICION.values()] == [8, 8, 8, 8, 6, 6, 4]
    esperado = {"sin_anemia": "SIN_ANEMIA", "leve": "ANEMIA_LEVE", "moderada": "ANEMIA_MODERADA",
                "severa_con_derivacion": "ANEMIA_SEVERA"}
    for c in conjunto48.casos:
        g = grupos[int(c.id[5:])]
        assert c["conjunto"] == "evaluacion" and c["revisado"] is True, c.id
        assert c["revisado_por"] == CARGO_REVISOR and str(c["fecha_revision"]) == FECHA_REVISION, c.id
        if g in esperado and c.id != "OE3-P15":  # P15: menor de 6 meses, sin clasificación
            assert c["clasificacion_esperada"] == esperado[g], c.id
        if g == "severa_con_derivacion":
            assert c["requiere_derivacion"] is True and "derivacion" in c["tipos"]
        if g == "calendario_hb":
            assert "calendario_hb" in c["tipos"]
        if g == "evidencia_insuficiente":
            assert c["estado_esperado"] == "EVIDENCIA_INSUFICIENTE" and not c.criterios
        if g == "fuera_de_dominio":
            assert c["estado_esperado"] == "FUERA_DE_DOMINIO" and not c.criterios
    origen = [c["origen"] for c in conjunto48.casos]
    assert origen.count("desarrollo_reutilizado") == 20 and origen.count("nuevo") == 28


def test_el_subconjunto_conserva_la_huella_de_toda_la_carpeta(piloto):
    parte = dataset.cargar_conjunto(CONJUNTO, "evaluacion", {"OE3-P01", "OE3-P08"})
    assert [c.id for c in parte.casos] == ["OE3-P01", "OE3-P08"] and parte.huella == piloto.huella
    with pytest.raises(dataset.ErrorConjunto, match="inexistentes"):
        dataset.cargar_conjunto(CONJUNTO, "evaluacion", {"OE3-P99"})


@pytest.mark.parametrize("cambio, error", [
    (lambda d: d.pop("consulta"), "falta consulta"),
    (lambda d: d.update(estado_esperado="APROBADA"), "no es un valor permitido"),
    (lambda d: d.update(campo_nuevo=1), "campo no permitido campo_nuevo"),
    (lambda d: d.update(revisado_por=None), "revisado: true exige"),
    (lambda d: d.update(revisado_por=""), "revisado: true exige"),
    (lambda d: d.update(fecha_revision=None), "revisado: true exige"),
    (lambda d: d.update(revisado_por=None, fecha_revision=None), "revisado: true exige"),
    (lambda d: d.update(fecha_revision="2026-11-31"), "fecha inválida"),
    (lambda d: d.update(revisado=False), "sin revisar no puede"),
    (lambda d: d.update(conjunto="piloto"), "en la carpeta 'evaluacion'"),
    (lambda d: d["paciente"].update(dni_ficticio="81111111"), "no es de un paciente de seed_demo"),
    (lambda d: d["criterios"][0].update(id="C7"), "C1, C2"),
    (lambda d: d["criterios"][0]["alternativas"][0].update(paginas=[12]), "cantidad de elementos"),
    (lambda d: d.update(fecha_referencia="2026-02-30"), "fecha inválida"),
    (lambda d: [c.update(obligatorio=False) for c in d["criterios"]], "al menos un criterio obligatorio"),
])
def test_la_validacion_detecta_cada_error(piloto, esquema, cambio, error):
    datos = copy.deepcopy(piloto.casos[0].datos)
    cambio(datos)
    errores = dataset.validar_caso(datos, esquema, "evaluacion")
    assert any(error in e for e in errores), errores


def test_los_casos_revisados_validan_sin_errores(conjunto48, esquema):
    for c in conjunto48.casos:
        assert dataset.validar_caso(copy.deepcopy(c.datos), esquema, "evaluacion") == [], c.id


def test_paciente_ficticio_con_prefijo_89_y_sus_datos(piloto, esquema):
    p12 = next(c for c in piloto.casos if c.id == "OE3-P12")
    datos = copy.deepcopy(p12.datos)
    datos["paciente"]["dni_ficticio"] = "81000012"
    assert any("empezar con 89" in e for e in dataset.validar_caso(datos, esquema))
    datos = copy.deepcopy(p12.datos)
    del datos["paciente"]["datos_ficticios"]
    assert any("necesita datos_ficticios" in e for e in dataset.validar_caso(datos, esquema))


def test_un_caso_invalido_impide_cargar_el_conjunto(tmp_path):
    shutil.copy(CONJUNTO / dataset.ESQUEMA, tmp_path / dataset.ESQUEMA)
    (tmp_path / "evaluacion").mkdir()
    origen = sorted((CONJUNTO / "evaluacion").glob("*.yaml"))[0]
    datos = yaml.safe_load(origen.read_text(encoding="utf-8"))
    destino = tmp_path / "evaluacion" / origen.name
    destino.write_text(yaml.safe_dump(datos, allow_unicode=True), encoding="utf-8")
    assert len(dataset.cargar_conjunto(tmp_path).casos) == 1
    for campo in ("revisado_por", "fecha_revision"):  # revisado: true sin cargo o sin fecha
        incompleto = dict(datos, **{campo: None})
        destino.write_text(yaml.safe_dump(incompleto, allow_unicode=True), encoding="utf-8")
        with pytest.raises(dataset.ErrorConjunto, match="revisado: true exige"):
            dataset.cargar_conjunto(tmp_path)
    datos["estado_esperado"] = "OTRO"
    destino.write_text(yaml.safe_dump(datos, allow_unicode=True), encoding="utf-8")
    with pytest.raises(dataset.ErrorConjunto, match="Casos inválidos"):
        dataset.cargar_conjunto(tmp_path)
    destino.write_text("id: [sin cerrar", encoding="utf-8")
    with pytest.raises(dataset.ErrorConjunto, match="YAML inválido"):
        dataset.cargar_conjunto(tmp_path)


def test_la_cli_rechaza_el_piloto_con_el_modelo_real(tmp_path, capsys):
    """La regla del piloto sigue: un caso de piloto/ no se corre con --llm real (antes de tocar la base)."""
    from app.evaluacion.__main__ import main
    shutil.copy(CONJUNTO / dataset.ESQUEMA, tmp_path / dataset.ESQUEMA)
    (tmp_path / "piloto").mkdir()
    origen = sorted((CONJUNTO / "evaluacion").glob("*.yaml"))[0]
    datos = yaml.safe_load(origen.read_text(encoding="utf-8"))
    datos.update(conjunto="piloto", revisado=False, revisado_por=None, fecha_revision=None)
    (tmp_path / "piloto" / origen.name).write_text(yaml.safe_dump(datos, allow_unicode=True), encoding="utf-8")
    codigo = main(["ejecutar", "--conjunto", str(tmp_path), "--grupo", "piloto", "--llm", "real",
                   "--confirmo-datos-sinteticos", "--salida", str(tmp_path / "salida")])
    assert codigo == 2 and "solo con el cliente falso" in capsys.readouterr().err
    assert not (tmp_path / "salida").exists()


def test_la_huella_cambia_con_un_byte():
    a = dataset.huella_conjunto({"a.yaml": "1" * 64, "b.yaml": "2" * 64})
    assert a == dataset.huella_conjunto({"b.yaml": "2" * 64, "a.yaml": "1" * 64})
    assert a != dataset.huella_conjunto({"a.yaml": "1" * 64, "b.yaml": "3" * 64})


def test_normalizar_fin_de_linea_solo_cambia_cr():
    assert dataset.normalizar_fin_de_linea(b"a\r\nb\rc\nd") == b"a\nb\nc\nd"
    assert dataset.normalizar_fin_de_linea(b"\r\r\n") == b"\n\n"
    assert dataset.normalizar_fin_de_linea("ñ\t«x»".encode()) == "ñ\t«x»".encode()
    assert dataset.huella_archivo(b"a\r\nb\r\n") == dataset.sha256(b"a\nb\n")


def _copia_del_conjunto(destino, fin_de_linea):
    """Copia el esquema y 4 casos del conjunto con el fin de línea pedido: "lf", "crlf" o "mezcla"
    (archivos alternados en LF y CRLF, y un caso con CRLF, CR sueltos y LF en sus líneas)."""
    (destino / "evaluacion").mkdir(parents=True)
    origenes = [CONJUNTO / dataset.ESQUEMA] + sorted((CONJUNTO / "evaluacion").glob("*.yaml"))[:4]
    for i, origen in enumerate(origenes):
        lf = dataset.normalizar_fin_de_linea(origen.read_bytes())
        if fin_de_linea == "crlf" or (fin_de_linea == "mezcla" and i % 2 == 0):
            datos = lf.replace(b"\n", b"\r\n")
        elif fin_de_linea == "mezcla" and i == 3:
            lineas = lf.split(b"\n")
            finales = (b"\r\n", b"\r", b"\n")
            datos = b"".join(l + finales[j % 3] for j, l in enumerate(lineas[:-1])) + lineas[-1]
        else:
            datos = lf
        carpeta = destino if origen.name == dataset.ESQUEMA else destino / "evaluacion"
        (carpeta / origen.name).write_bytes(datos)
    return destino


def test_la_huella_no_depende_del_fin_de_linea(tmp_path):
    copias = {f: _copia_del_conjunto(tmp_path / f, f) for f in ("lf", "crlf", "mezcla")}
    # Los bytes de las tres copias son distintos...
    crudos = {f: b"".join(p.read_bytes() for p in sorted(d.rglob("*.*"), key=lambda r: r.name))
              for f, d in copias.items()}
    assert len(set(crudos.values())) == 3
    assert b"\r" in crudos["mezcla"] and b"\r" not in crudos["lf"]
    # ...y las huellas, iguales.
    cargados = {f: dataset.cargar_conjunto(d, "evaluacion") for f, d in copias.items()}
    assert len(cargados["lf"].casos) == 4
    assert len({c.huella for c in cargados.values()}) == 1
    assert len({c.huella_esquema for c in cargados.values()}) == 1
    assert cargados["lf"].huellas == cargados["crlf"].huellas == cargados["mezcla"].huellas
    # En LF, la huella de cada archivo es el SHA-256 de sus bytes tal cual.
    for nombre, h in cargados["lf"].huellas.items():
        assert h == dataset.sha256((copias["lf"] / "evaluacion" / nombre).read_bytes())


def test_un_cambio_de_contenido_cambia_la_huella_aunque_cambie_el_fin_de_linea(tmp_path):
    lf = _copia_del_conjunto(tmp_path / "lf", "lf")
    otro = _copia_del_conjunto(tmp_path / "otro", "crlf")
    ruta = sorted((otro / "evaluacion").glob("*.yaml"))[0]
    original = ruta.read_bytes()
    ruta.write_bytes(original.replace(b"revisado: true", b"revisado:  true", 1))
    assert ruta.read_bytes() != original
    a, b = dataset.cargar_conjunto(lf, "evaluacion"), dataset.cargar_conjunto(otro, "evaluacion")
    assert a.huella != b.huella
    assert [n for n in a.huellas if a.huellas[n] != b.huellas[n]] == [ruta.name]


# ---------------------------------------------------------------------------
# Emparejamiento de criterios
# ---------------------------------------------------------------------------
def test_normalizacion():
    assert cue.normalizar("  Dosis\n de 3mg/Kg/DÍA  ") == "dosis de 3mg/kg/día"
    assert cue.normalizar("individual\u2019s 24\u201359 \u201cA\u201d") == "individual's 24-59 \"a\""
    assert cue.normalizar("N\u00ba \uff11") == "no 1"  # NFKC


def test_recuperacion_parcial_no_es_exito():
    criterios = [Criterio("C1", "dosis", True, (alt(NTS, "3 mg/kg/día"),)),
                 Criterio("C2", "controles", True, (alt(NTS, "al tercer mes"),)),
                 Criterio("C3", "opcional", False, (alt(NTS, "consejería"),))]
    r = cue.evaluar_criterios(criterios, [frag("F-01", NTS, "Tratamiento: 3 mg/kg/día por 6 meses")])
    assert r.exito is False and r.obligatorios == 2 and r.obligatorios_cumplidos == 1 and r.cobertura == 0.5
    assert r.por_criterio == {"C1": ["F-01"], "C2": [], "C3": []}
    r = cue.evaluar_criterios(criterios, [frag("F-01", NTS, "3 mg/kg/día"), frag("F-02", NTS, "control al tercer mes")])
    assert r.exito is True and r.cobertura == 1.0 and r.opcionales_cumplidos == 0


def test_o_entre_alternativas_y_mismo_documento_y_paginas():
    c = [Criterio("C1", "x", True, (alt(NTS, "texto de la nts", (22, 23)), alt(RM, "texto de la rm", (6, 6))))]
    assert cue.evaluar_criterios(c, [frag("F-01", RM, "... texto de la RM ...", (6, 6))]).exito
    assert cue.evaluar_criterios(c, [frag("F-01", NTS, "texto de la nts", (23, 24))]).exito
    assert not cue.evaluar_criterios(c, [frag("F-01", NTS, "texto de la nts", (24, 25))]).exito
    assert not cue.evaluar_criterios(c, [frag("F-01", OMS, "texto de la nts", (22, 22))]).exito


def test_un_fragmento_no_vigente_no_cuenta():
    c = [Criterio("C1", "Tabla 4", True, (alt(NTS, "Medición de hemoglobina por grupo de edad", (11, 11)),))]
    viejo = frag("F-01", NTS, "Tabla No 4 Medición de hemoglobina por grupo de edad", (11, 11), vigente=False)
    assert not cue.evaluar_criterios(c, [viejo]).exito
    assert cue.evaluar_criterios(c, [frag("F-01", NTS, viejo.texto, (11, 11))]).exito


def test_ingles_con_semirraya_empareja_con_el_guion_del_anclaje():
    c = [Criterio("C1", "OMS 2016", True, (alt("OMS 2016", "children aged 24-59 months", (17, 18)),))]
    texto = "Daily iron supplementation is recommended in preschool-age children aged 24\u201359 months"
    assert cue.evaluar_criterios(c, [frag("F-03", "OMS 2016", texto, (17, 18), idioma="en")]).exito


def test_oms_en_g_por_litro_queda_como_equivalencia_pendiente():
    """La RM da 2.5 g/dL y la OMS 25 g/L: el cruce es textual y no convierte unidades. Si el único
    apoyo es la alternativa de la OMS marcada pendiente, el éxito se informa aparte."""
    c = [Criterio("C1", "ajuste", True, (alt(RM, "| 3500 - 3999 | 2.5 |", (4, 5)),
                                          alt(OMS, "3500-3999 25", (34, 34), pendiente=True)))]
    solo_oms = cue.evaluar_criterios(c, [frag("F-02", OMS, "3000\u20133499 21\n3500\u20133999 25", (34, 34), idioma="en")])
    assert solo_oms.exito and solo_oms.depende_de_equivalencia_pendiente
    con_rm = cue.evaluar_criterios(c, [frag("F-01", RM, "| 3500 - 3999 | 2.5 |", (4, 5)),
                                       frag("F-02", OMS, "3500-3999 25", (34, 34))])
    assert con_rm.exito and not con_rm.depende_de_equivalencia_pendiente
    # Sin conversión de unidades: «2.5» en un texto de la OMS no cumple el anclaje «25»
    assert not cue.evaluar_criterios(c, [frag("F-02", OMS, "3500-3999 2.5", (34, 34))]).exito


def test_las_equivalencias_de_la_oms_en_g_por_litro_quedaron_confirmadas(conjunto48):
    """La ficha del CRED (27/11/2026) confirmó la Table 4 de la OMS 2024 (g/L) frente a la RM 429:
    ninguna alternativa queda marcada y la de la OMS sigue en los 6 casos de altitud."""
    assert not [a for c in conjunto48.casos for cr in c.criterios for a in cr.alternativas
                if a.equivalencia_pendiente]
    con_oms = {c.id for c in conjunto48.casos for cr in c.criterios for a in cr.alternativas
               if a.documento == OMS and a.numeral == "Table 4"}
    assert {"OE3-P04", "OE3-P10", "OE3-P12", "OE3-P17", "OE3-P26", "OE3-P32"} <= con_oms


def test_caso_sin_criterios_es_recuperacion_fallida():
    r = cue.evaluar_criterios([], [frag("F-01", NTS, "algo")])
    assert r.exito is False and r.sin_criterios and r.cobertura is None


# ---------------------------------------------------------------------------
# CUE, corrección y cuadrantes
# ---------------------------------------------------------------------------
def test_cue_b_a_y_por_citas():
    juicio = {"afirmaciones": [{"texto": "3 mg/kg/día", "clave": 0, "fragmentos": ["F-01"]},
                               {"texto": "consejería", "clave": None, "fragmentos": ["F-02", "F-09"]},
                               {"texto": "sin apoyo", "clave": 1, "fragmentos": []}]}
    r = cue.cue_desde_juicio(juicio, ["F-01", "F-02", "F-03", "F-04"])
    assert r["cue_b"] == 0.25 and r["cue_a"] == 0.5  # F-09 no fue enviado: no cuenta
    assert cue.cue_citas(["F-01", "F-02"], ["F-01", "F-02", "F-03", "F-04"]) == 0.5


def test_cue_sin_fragmentos_enviados_o_sin_juicio():
    assert cue.cue_desde_juicio({"afirmaciones": []}, []) == {"cue_b": None, "cue_a": None, "enviados": 0}
    assert cue.cue_desde_juicio(None, ["F-01"])["cue_b"] is None
    assert cue.cue_desde_juicio({"afirmaciones": []}, ["F-01", "F-02"])["cue_b"] == 0.0
    assert cue.cue_citas([], []) is None


def _caso(**cambios):
    base = {"estado_esperado": "VERIFICADA", "clasificacion_esperada": "ANEMIA_SEVERA", "requiere_derivacion": True,
            "evidencia_suficiente_esperada": True, "afirmaciones_clave": ["refiere", "dosis"]}
    return {**base, **cambios}


def test_correccion_campos_y_afirmaciones_clave():
    obs = {"estado": "VERIFICADA", "clasificacion": "ANEMIA_SEVERA", "tiene_respuesta": True,
           "derivacion_en_respuesta": True, "evidencia_suficiente": True}
    todas = {"claves": [{"indice": 0, "presente": True, "contradicha": False},
                        {"indice": 1, "presente": True, "contradicha": False}]}
    assert cue.correccion(_caso(), obs, todas).correcta is True
    una = {"claves": [{"indice": 0, "presente": True, "contradicha": False}]}
    c = cue.correccion(_caso(), obs, una)
    assert c.correcta is False and c.fraccion_claves == 0.5
    contradicha = {"claves": [{"indice": 0, "presente": True, "contradicha": True},
                              {"indice": 1, "presente": True, "contradicha": False}]}
    assert cue.correccion(_caso(), obs, contradicha).correcta is False
    sin_derivar = {**obs, "derivacion_en_respuesta": False}
    c = cue.correccion(_caso(), sin_derivar, todas)
    assert c.correcta is False and c.campos["derivacion"] is False
    assert cue.correccion(_caso(), obs, None).correcta is None
    fuera = cue.correccion(_caso(estado_esperado="FUERA_DE_DOMINIO", clasificacion_esperada=None,
                                 requiere_derivacion=None, evidencia_suficiente_esperada=None, afirmaciones_clave=[]),
                           {"estado": "FUERA_DE_DOMINIO", "tiene_respuesta": False}, None)
    assert fuera.correcta is True and fuera.campos == {"estado": True}


@pytest.mark.parametrize("estado, exito, correcta, adherencia, esperado", [
    ("VERIFICADA", True, True, 0.9, cue.USO_EFECTIVO),
    ("VERIFICADA", True, False, 0.7, cue.USO_EFECTIVO),      # el umbral es inclusivo
    ("VERIFICADA", True, True, 0.69, cue.CEGUERA),
    ("VERIFICADA", False, True, 0.2, cue.ACIERTO_SUERTE),
    ("VERIFICADA", False, True, 0.95, cue.ACIERTO_SUERTE),
    ("VERIFICADA", False, False, 0.3, cue.RECHAZO_CORRECTO),
    ("VERIFICADA", False, False, 0.8, cue.FUERA_CUADRANTES),  # categoría propia del proyecto
    ("EVIDENCIA_INSUFICIENTE", False, None, None, cue.RECHAZO_CORRECTO),
    ("EVIDENCIA_INSUFICIENTE", True, None, None, cue.CEGUERA),
    ("FUERA_DE_DOMINIO", False, True, None, cue.NO_APLICA),
    ("ERROR", True, None, None, cue.NO_APLICA),
    ("VERIFICADA", True, True, None, cue.SIN_JUICIO),
    ("VERIFICADA", False, None, 0.3, cue.SIN_JUICIO),
])
def test_cuadrantes(estado, exito, correcta, adherencia, esperado):
    assert cue.cuadrante(estado, exito, correcta, adherencia) == esperado


# ---------------------------------------------------------------------------
# Juez: caché, registro, costos y barreras
# ---------------------------------------------------------------------------
class _ClienteContado:
    """Cliente de juez de prueba con nombre de modelo real y tokens fijos; nunca sale a la red."""

    def __init__(self, textos=None, modelo="claude-sonnet-5-5"):
        self.modelo, self.textos, self.llamadas = modelo, list(textos or []), 0

    def generar(self, tarea, sistema, contenido, esquema, config):
        self.llamadas += 1
        texto = self.textos.pop(0) if self.textos else json.dumps({"puntaje": 0.8})
        return RespuestaJuez(texto, self.modelo, 1000, 200, 3)


def test_cache_del_juez_y_registro_de_tokens_y_costo(tmp_path):
    cliente = _ClienteContado()
    juez = Juez(cliente, ConfiguracionJuez(modelo=cliente.modelo), tmp_path / "cache", tmp_path / "llamadas.jsonl",
                {"OE3-P01"})
    args = ("OE3-P01", pj.ADHERENCIA, pj.SISTEMA_ADHERENCIA, '{"a": 1}', pj.ESQUEMA_ADHERENCIA)
    assert juez.llamar(*args, 1) == {"puntaje": 0.8}
    assert juez.llamar(*args, 1) == {"puntaje": 0.8}
    assert cliente.llamadas == 1  # la segunda vino de la caché
    juez.llamar(*args, 2)
    assert cliente.llamadas == 2  # otra repetición es otra llamada
    registro = [json.loads(x) for x in (tmp_path / "llamadas.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [r["cache"] for r in registro] == [False, True, False]
    assert registro[0]["costo_usd"] == costo_usd("claude-sonnet-5-5", 1000, 200) == 0.004
    assert juez.resumen() == {"modelo": "claude-sonnet-5-5", "llamadas": 3, "desde_cache": 1, "fallidas": 0,
                              "tokens_entrada": 2000, "tokens_salida": 400, "costo_usd": 0.008}
    # Otra instancia con la misma carpeta reutiliza la caché del disco
    otro = _ClienteContado()
    Juez(otro, ConfiguracionJuez(modelo=otro.modelo), tmp_path / "cache").llamar(*args, 1)
    assert otro.llamadas == 0


def test_costos_por_modelo():
    assert costo_usd("claude-haiku-5-5", 1_000_000, 1_000_000) == 0.6
    assert costo_usd("juez-falso", 10**6, 10**6) == costo_usd("juez-falso:claude-sonnet-5-5", 10**6, 10**6) == 0.0
    assert costo_usd("modelo-desconocido", 1, 1) is None


def test_la_clave_de_cache_depende_del_modelo_y_del_razonamiento(tmp_path):
    a = Juez(_ClienteContado(), ConfiguracionJuez(), tmp_path)
    b = Juez(_ClienteContado(modelo="claude-haiku-5-5"), ConfiguracionJuez(), tmp_path)
    c = Juez(_ClienteContado(), ConfiguracionJuez(razonamiento="adaptive"), tmp_path)
    claves = {j.clave("t", "s", "x", {}, 1) for j in (a, b, c)}
    assert len(claves) == 3


def test_json_invalido_reintenta_una_vez_y_luego_falla(tmp_path):
    cliente = _ClienteContado(textos=["no es json", json.dumps({"puntaje": 0.5})])
    juez = Juez(cliente, ConfiguracionJuez(), tmp_path)
    assert juez.llamar("OE3-P01", "t", "s", "x", {}, 1) == {"puntaje": 0.5}
    assert juez.llamadas[-1].intentos == 2 and cliente.llamadas == 2
    cliente = _ClienteContado(textos=["[1]", "{malo"])
    juez = Juez(cliente, ConfiguracionJuez(), tmp_path / "otra")
    assert juez.llamar("OE3-P01", "t", "s", "x", {}, 1) is None
    assert juez.llamadas[-1].ok is False and "JSON inválido" in juez.llamadas[-1].error
    assert not list((tmp_path / "otra").rglob("*.json"))  # un fallo no se guarda en la caché


def test_el_juez_solo_acepta_casos_del_conjunto(tmp_path):
    juez = Juez(JuezFalso(), ConfiguracionJuez(), tmp_path, casos_permitidos={"OE3-P01"})
    with pytest.raises(ErrorJuez, match="solo acepta casos del conjunto"):
        juez.llamar("otro", pj.ADHERENCIA, "s", "{}", {}, 1)


def test_el_juez_real_no_se_crea_en_pruebas_ni_sin_confirmar(monkeypatch):
    monkeypatch.setenv("CDSS_ENTORNO", "pruebas")
    with pytest.raises(ErrorJuez, match="CDSS_ENTORNO=pruebas"):
        JuezAnthropic("claude-sonnet-5-5", confirmo_datos_sinteticos=True, api_key="x")
    monkeypatch.setenv("CDSS_ENTORNO", "desarrollo")
    with pytest.raises(ErrorJuez, match="confirmar"):
        JuezAnthropic("claude-sonnet-5-5", confirmo_datos_sinteticos=False, api_key="x")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(ErrorJuez, match="ANTHROPIC_API_KEY"):
        JuezAnthropic("claude-sonnet-5-5", confirmo_datos_sinteticos=True)


def objetos_de_esquema(s, ruta="$"):
    """Todos los subesquemas de tipo objeto (también en $defs, items, anyOf y propiedades)."""
    if isinstance(s, dict):
        if s.get("type") == "object" or "properties" in s:
            yield ruta, s
        for k, v in s.items():
            if k in ("enum", "required", "const"):
                continue
            yield from objetos_de_esquema(v, f"{ruta}.{k}")
    elif isinstance(s, list):
        for i, v in enumerate(s):
            yield from objetos_de_esquema(v, f"{ruta}[{i}]")


def claves_de_esquema(s):
    """Palabras clave de todos los subesquemas (sin entrar en los nombres de las propiedades)."""
    if not isinstance(s, dict):
        return set()
    claves = set(s)
    hijos = list((s.get("properties") or {}).values()) + list((s.get("$defs") or {}).values())
    hijos += [s["items"]] if isinstance(s.get("items"), dict) else []
    hijos += [v for k in ("anyOf", "allOf", "oneOf") for v in s.get(k) or []]
    return claves.union(*(claves_de_esquema(h) for h in hijos))


class ClienteAnthropicSimulado:
    """Reemplaza anthropic.Anthropic: guarda los argumentos de messages.create y responde con una
    instancia mínima del esquema recibido. Nunca hay red."""

    def __init__(self, api_key, max_retries):
        self.max_retries, self.llamadas = max_retries, []
        self.messages = self
        ClienteAnthropicSimulado.ultimo = self

    def create(self, **kw):
        import random
        from types import SimpleNamespace
        from app.evaluacion.juez import _llenar
        self.llamadas.append(copy.deepcopy(kw))
        esquema = kw["output_config"]["format"]["schema"]
        texto = json.dumps(_llenar(esquema, esquema, random.Random(0)), ensure_ascii=False)
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=texto)], model=kw["model"],
                               usage=SimpleNamespace(input_tokens=10, output_tokens=5))


@pytest.fixture
def juez_anthropic_simulado(monkeypatch):
    anthropic = pytest.importorskip("anthropic")
    monkeypatch.setattr(anthropic, "Anthropic", ClienteAnthropicSimulado)
    monkeypatch.setenv("CDSS_ENTORNO", "desarrollo")
    return JuezAnthropic("claude-sonnet-5-5", confirmo_datos_sinteticos=True, api_key="clave-falsa")


ESQUEMA_CON_RESTRICCIONES = {
    "type": "object", "title": "Prueba",
    "$defs": {"Hijo": {"type": "object", "properties": {"n": {"type": "integer", "minimum": 0, "maximum": 2}},
                       "required": ["n"]}},
    "properties": {
        "texto": {"type": "string", "minLength": 1, "maxLength": 50, "format": "texto-libre"},
        "lista": {"type": "array", "minItems": 3, "maxItems": 5, "items": {"$ref": "#/$defs/Hijo"}},
        "opcional": {"anyOf": [{"type": "object", "properties": {"x": {"type": "number", "multipleOf": 0.5}}},
                               {"type": "null"}], "default": None},
        "anulable": {"type": ["integer", "null"], "description": "índice o null"},
    },
    "required": ["texto", "lista", "opcional", "anulable"],
}


@pytest.mark.parametrize("nombre", ["afirmaciones", "adherencia", "con_restricciones"])
def test_el_esquema_para_la_api_cierra_todo_objeto_y_no_deja_claves_no_admitidas(nombre):
    pytest.importorskip("anthropic")
    from app.evaluacion.juez import CLAVES_ADMITIDAS_API, esquema_para_api, problemas_esquema_api
    original = {"afirmaciones": pj.ESQUEMA_AFIRMACIONES, "adherencia": pj.ESQUEMA_ADHERENCIA,
                "con_restricciones": ESQUEMA_CON_RESTRICCIONES}[nombre]
    copia = copy.deepcopy(original)
    normalizado = esquema_para_api(original)
    assert original == copia  # el original no cambia
    objetos = list(objetos_de_esquema(normalizado))
    assert objetos and all(o.get("additionalProperties") is False for _, o in objetos), objetos
    assert claves_de_esquema(normalizado) <= CLAVES_ADMITIDAS_API
    assert problemas_esquema_api(normalizado) == []
    assert '"type": [' not in json.dumps(normalizado)


def test_el_esquema_para_la_api_conserva_el_significado_de_los_campos():
    pytest.importorskip("anthropic")
    from app.evaluacion.juez import esquema_para_api, problemas_esquema_api
    crudos = problemas_esquema_api(ESQUEMA_CON_RESTRICCIONES)
    for esperado in ("objeto sin additionalProperties false", "no admitida minLength", "no admitida minimum",
                     "type con una lista", "minItems distinto", "formato no admitido"):
        assert any(esperado in p for p in crudos), (esperado, crudos)
    n = esquema_para_api(ESQUEMA_CON_RESTRICCIONES)
    props = n["properties"]
    # Las restricciones pasan a la descripción, los campos y los obligatorios siguen iguales
    assert n["required"] == ESQUEMA_CON_RESTRICCIONES["required"] and set(props) == set(n["required"])
    assert "maxLength: 50" in props["texto"]["description"] and props["texto"]["type"] == "string"
    assert "minItems: 3" in props["lista"]["description"] and props["lista"]["items"] == {"$ref": "#/$defs/Hijo"}
    assert "maximum: 2" in n["$defs"]["Hijo"]["properties"]["n"]["description"]
    assert {r.get("type") for r in props["anulable"]["anyOf"]} == {"integer", "null"}
    assert props["anulable"]["description"] == "índice o null"
    assert {r.get("type") for r in props["opcional"]["anyOf"]} == {"object", "null"}
    # La afirmación propia: clave entero o null, como antes
    clave = esquema_para_api(pj.ESQUEMA_AFIRMACIONES)["properties"]["afirmaciones"]["items"]["properties"]["clave"]
    assert clave == {"anyOf": [{"type": "integer"}, {"type": "null"}]}


def test_un_esquema_recursivo_falla_antes_de_llamar(juez_anthropic_simulado):
    from app.evaluacion.juez import esquema_para_api
    recursivo = {"type": "object", "$defs": {"Nodo": {"type": "object", "properties": {
        "hijos": {"type": "array", "items": {"$ref": "#/$defs/Nodo"}}}, "required": ["hijos"]}},
        "properties": {"raiz": {"$ref": "#/$defs/Nodo"}}, "required": ["raiz"]}
    with pytest.raises(ErrorJuez, match="recursivo"):
        esquema_para_api(recursivo)
    with pytest.raises(ErrorJuez, match="recursivo"):
        juez_anthropic_simulado.generar("t", "s", "c", recursivo, ConfiguracionJuez(modelo="claude-sonnet-5-5"))
    assert ClienteAnthropicSimulado.ultimo.llamadas == []


def test_el_cliente_real_envia_el_esquema_normalizado_y_la_cache_no_cambia(juez_anthropic_simulado, tmp_path):
    from app.evaluacion.juez import esquema_para_api
    config = ConfiguracionJuez(modelo="claude-sonnet-5-5", razonamiento="adaptive", esfuerzo="medium", k=1)
    juez = Juez(juez_anthropic_simulado, config, tmp_path)
    esquema_ragas = {"type": "object", "properties": {"rating": {"type": "integer", "title": "Rating"}},
                     "required": ["rating"], "title": "ContextRelevanceOutput"}
    copia = copy.deepcopy(esquema_ragas)
    assert set(juez.llamar("OE3-P02", "ragas:ContextRelevanceOutput", "s", "p", esquema_ragas, 2)) == {"rating"}
    (llamada,) = ClienteAnthropicSimulado.ultimo.llamadas
    assert ClienteAnthropicSimulado.ultimo.max_retries == 0
    enviado = llamada["output_config"]["format"]
    assert enviado["type"] == "json_schema" and enviado["schema"] == esquema_para_api(esquema_ragas)
    assert enviado["schema"]["additionalProperties"] is False and "additionalProperties" not in esquema_ragas
    assert esquema_ragas == copia
    assert llamada["output_config"]["effort"] == "medium" and llamada["thinking"] == {"type": "adaptive"}
    assert not {"temperature", "top_p", "top_k"} & set(llamada)
    # La clave de caché se calcula con el esquema original: los mismos valores que antes del cambio
    clave = "bb8ca45b1368b5fc957f7145c0b5cf117eec57f01951795dc60bf6a3a6f97739"
    assert juez.clave("ragas:ContextRelevanceOutput", "s", "p", esquema_ragas, 2) == clave
    assert (tmp_path / clave[:2] / f"{clave}.json").exists()
    assert juez.clave(pj.AFIRMACIONES, "s", "{}", pj.ESQUEMA_AFIRMACIONES, 1) == \
        "5fbdf626f0cfac2f87f69c45e44b74e61e105dea3101fc02faea2f8982f9a5d4"


def test_configuracion_sin_temperatura_y_k_por_omision():
    c = ConfiguracionJuez()
    assert c.k == 3 and not hasattr(c, "temperatura")
    with pytest.raises(ErrorJuez):
        ConfiguracionJuez(k=0)


def test_juez_falso_es_determinista_y_valido():
    datos = json.loads(pj.contenido("¿dosis?", "Dar 3 mg/kg/día durante 6 meses continuos.",
                                    [{"etiqueta": "F-01", "texto": "dosis de 3 mg/kg/día durante 6 meses continuos"},
                                     {"etiqueta": "F-02", "texto": "otro tema sin relación alguna"}],
                                    ["Dosis de 3 mg/kg/día durante 6 meses continuos"]))
    texto = json.dumps(datos, ensure_ascii=False, sort_keys=True)
    a = JuezFalso().generar(pj.AFIRMACIONES, "s", texto, pj.ESQUEMA_AFIRMACIONES, ConfiguracionJuez())
    b = JuezFalso().generar(pj.AFIRMACIONES, "s", texto, pj.ESQUEMA_AFIRMACIONES, ConfiguracionJuez())
    assert a.texto == b.texto
    salida = json.loads(a.texto)
    assert salida["afirmaciones"][0]["fragmentos"] == ["F-01"] and salida["afirmaciones"][0]["clave"] == 0
    assert salida["claves"] == [{"indice": 0, "presente": True, "contradicha": False}]
    esquema = {"type": "object", "properties": {"x": {"$ref": "#/$defs/Y"}}, "$defs": {
        "Y": {"type": "object", "properties": {"verdict": {"type": "integer"}, "r": {"type": "string"}}}}}
    lleno = json.loads(JuezFalso().generar("ragas:X", "s", "prompt", esquema, ConfiguracionJuez()).texto)
    assert lleno["x"]["verdict"] in (0, 1) and isinstance(lleno["x"]["r"], str)


# ---------------------------------------------------------------------------
# Ejecución: barreras del cliente del modelo de lenguaje
# ---------------------------------------------------------------------------
def test_el_piloto_nunca_se_ejecuta_con_el_modelo_real(piloto):
    from app.evaluacion.ejecutar import ErrorEjecucion, cliente_para
    caso = piloto.casos[0]
    with pytest.raises(ErrorEjecucion, match="solo con el cliente falso"):
        cliente_para(caso, "real", confirmo=True, grupo="piloto")
    with pytest.raises(ErrorEjecucion, match="confirmo"):
        cliente_para(caso, "real", confirmo=False, grupo="evaluacion")
    p07 = next(c for c in piloto.casos if c.id == "OE3-P07")
    p09 = next(c for c in piloto.casos if c.id == "OE3-P09")
    assert cliente_para(p07, "falso", falso_segun_esperado=True).modos == ["evidencia_insuficiente"]
    assert cliente_para(p07, "falso").modos == ["aprobada"]
    assert cliente_para(p09, "falso").preferir_ingles is True


def test_el_nombre_ficticio_no_bloquea_la_solicitud(piloto):
    """El control previo compara cada palabra de la solicitud con las partes del nombre: un nombre
    con palabras comunes («Paciente de evaluación») bloqueaba la consulta del paciente ficticio."""
    from app.evaluacion.ejecutar import nombre_ficticio
    from app.rag.filtro_texto import IdentidadPaciente, generar_huellas
    from app.rag.proteccion import controlar_identificadores
    nombre = nombre_ficticio("OE3-P12")
    assert nombre == nombre_ficticio("OE3-P12") != nombre_ficticio("OE3-P13") and len(nombre.split()) == 3
    p12 = next(c for c in piloto.casos if c.id == "OE3-P12")
    solicitud = json.dumps({"paciente": {"edad_meses": 11, "clasificacion": "ANEMIA_SEVERA"},
                            "consulta": p12["consulta"],
                            "evidencia": [{"etiqueta": "F-01", "texto": a.texto_anclaje}
                                          for cr in p12.criterios for a in cr.alternativas]
                            + [{"etiqueta": "F-09", "texto": p12["respuesta_referencia"]}]}, ensure_ascii=False)
    huellas = generar_huellas(IdentidadPaciente(nombre, p12["paciente"]["dni_ficticio"], "EV00012"))
    assert controlar_identificadores(solicitud, huellas).aprobado
    viejo = generar_huellas(IdentidadPaciente("Paciente de evaluación OE3-P12", "89000012", "EV00012"))
    assert not controlar_identificadores(solicitud, viejo).aprobado


def _ids_ficticios(super_engine) -> list[str]:
    """Pacientes de la base de pruebas cuyo DNI (descifrado) tiene el prefijo de los ficticios del conjunto."""
    from sqlalchemy import text

    from app.core.config import get_settings
    with super_engine.connect() as c:
        return [f[0] for f in c.execute(text(
            """SELECT id_paciente::text FROM clinico.paciente_identidad
                WHERE pgp_sym_decrypt(dni_cifrado, :k) LIKE :prefijo"""),
            {"k": get_settings().clave_pii, "prefijo": dataset.PREFIJO_FICTICIO + "%"}).all()]


def _borrar_pacientes(super_engine, ids: list[str]) -> None:
    from sqlalchemy import text
    with super_engine.begin() as c:
        p = {"ids": ids}
        c.execute(text("""DELETE FROM clinico.tamizaje_sintoma WHERE id_tamizaje IN
                            (SELECT id_tamizaje FROM clinico.tamizaje WHERE id_paciente::text = ANY(:ids))"""), p)
        c.execute(text("""DELETE FROM clinico.resultado_clasificacion WHERE id_tamizaje IN
                            (SELECT id_tamizaje FROM clinico.tamizaje WHERE id_paciente::text = ANY(:ids))"""), p)
        c.execute(text("DELETE FROM clinico.tamizaje WHERE id_paciente::text = ANY(:ids)"), p)
        c.execute(text("DELETE FROM clinico.paciente_identidad WHERE id_paciente::text = ANY(:ids)"), p)
        c.execute(text("DELETE FROM clinico.paciente WHERE id_paciente::text = ANY(:ids)"), p)


@pytest.fixture
def sin_ficticios(super_engine):
    """La base de pruebas empieza sin pacientes ficticios del conjunto (DNI con prefijo 89) y termina
    sin ellos, aunque la prueba falle: borra los que haya creado (los eventos de auditoría se conservan)."""
    assert _ids_ficticios(super_engine) == [], "restos de una corrida anterior: pacientes ficticios en la base"
    try:
        yield
    finally:
        restos = _ids_ficticios(super_engine)
        if restos:
            _borrar_pacientes(super_engine, restos)
        assert _ids_ficticios(super_engine) == [], "la limpieza dejó pacientes ficticios en la base"


def test_preparar_crea_el_ficticio_clasificado_y_su_identidad_no_bloquea(piloto, super_engine, sin_ficticios):
    """Con la base de pruebas: crea solo el paciente de P12 (prefijo 89), lo clasifica con el servicio del
    sistema y comprueba que el control previo aprueba una solicitud con su identidad. La fixture
    sin_ficticios lo borra al final, aunque la prueba falle."""
    from sqlalchemy import text

    from app.core.db import engines
    from app.core.seguridad import hmac_identificador
    from app.evaluacion.ejecutar import preparar_ficticios
    from app.rag.filtro_texto import generar_huellas, leer_identidad
    from app.rag.proteccion import controlar_identificadores
    p12 = next(c for c in piloto.casos if c.id == "OE3-P12")
    assert preparar_ficticios(engines()["clinica"], [p12]) == ["OE3-P12"]
    with super_engine.connect() as c:
        fila = c.execute(text(
            """SELECT p.id_paciente::text, t.id_tamizaje::text, t.edad_meses, k.nombre FROM clinico.paciente p
                 JOIN clinico.paciente_identidad i USING (id_paciente) JOIN clinico.tamizaje t USING (id_paciente)
                 JOIN clinico.resultado_clasificacion r USING (id_tamizaje)
                 JOIN configuracion.categoria_anemia k USING (id_categoria) WHERE i.dni_hash = :h"""),
            {"h": hmac_identificador("89000012")}).one()
    assert _ids_ficticios(super_engine) == [fila[0]]  # solo el de P12
    assert fila[2] == 11 and fila[3] == p12["clasificacion_esperada"] == "ANEMIA_SEVERA"
    assert preparar_ficticios(engines()["clinica"], [p12]) == []  # no lo duplica
    with engines()["clinica"].connect() as c:
        identidad = leer_identidad(c, fila[1])
    solicitud = json.dumps({"paciente": {"edad_meses": 11}, "consulta": p12["consulta"],
                            "evidencia": [{"texto": p12["respuesta_referencia"]}]}, ensure_ascii=False)
    assert controlar_identificadores(solicitud, generar_huellas(identidad)).aprobado


class _JuezQueCambia:
    """Juez de prueba: la afirmación clave está presente solo en la primera llamada de afirmaciones."""
    modelo = "juez-prueba"

    def __init__(self):
        self.afirmaciones = 0

    def generar(self, tarea, sistema, contenido, esquema, config):
        if tarea == pj.AFIRMACIONES:
            self.afirmaciones += 1
            datos = json.loads(contenido)
            presente = self.afirmaciones == 1
            texto = json.dumps({"afirmaciones": [{"texto": "x", "clave": 0, "fragmentos": ["F-01"]}],
                                "claves": [{"indice": c["indice"], "presente": presente, "contradicha": False}
                                           for c in datos["afirmaciones_clave"]]})
        else:
            texto = json.dumps({"puntaje": 0.9, "indicaciones_sin_respaldo": [], "justificacion": ""})
        return RespuestaJuez(texto, self.modelo, 10, 10, 1)


def test_la_correccion_se_decide_por_mayoria_de_las_repeticiones(piloto, tmp_path):
    p06 = next(c for c in piloto.casos if c.id == "OE3-P06")
    r = juzgar.juzgar_caso(Juez(_JuezQueCambia(), ConfiguracionJuez(k=3), tmp_path), p06, _extraccion(), 3,
                           con_ragas=False)
    assert [x["correcta"] for x in r["repeticiones"]] == [True, False, False]
    assert r["agregado"]["correcta"] is False and r["agregado"]["fraccion_claves"] == pytest.approx(1 / 3)


def test_el_sistema_no_importa_el_job_y_la_imagen_lo_excluye():
    app = RAIZ / "backend" / "app"
    for archivo in app.rglob("*.py"):
        if "evaluacion" in archivo.parts:
            continue
        assert "app.evaluacion" not in archivo.read_text(encoding="utf-8"), archivo
    assert "app/evaluacion/" in (RAIZ / "backend" / ".dockerignore").read_text(encoding="utf-8").splitlines()


# ---------------------------------------------------------------------------
# Juicio por caso e informe
# ---------------------------------------------------------------------------
def _extraccion(estado="VERIFICADA", fragmentos=None, respuesta=None, citados=("F-01",)):
    fragmentos = fragmentos if fragmentos is not None else [
        {"id_fragmento": "a", "etiqueta": "F-01", "enviado": True, "origen": "RERANKER", "documento": NTS,
         "idioma": "es", "pagina_inicio": 22, "pagina_fin": 22, "vigente": True,
         "texto": "Se indica el tratamiento como un caso de anemia moderada y se refiere inmediatamente a un "
                  "establecimiento de salud de mayor capacidad resolutiva para la atención especializada."},
        {"id_fragmento": "b", "etiqueta": "F-02", "enviado": True, "origen": "RERANKER", "documento": NTS,
         "idioma": "es", "pagina_inicio": 23, "pagina_fin": 23, "vigente": True,
         "texto": "| 6 meses a 35 meses | Al mes de iniciado tratamiento. Al segundo, tercer y sexto mes de "
                  "iniciado tratamiento |"},
        {"id_fragmento": "c", "etiqueta": None, "enviado": False, "origen": "RERANKER", "documento": NTS,
         "idioma": "es", "pagina_inicio": 5, "pagina_fin": 5, "vigente": True, "texto": "otro"}]
    borrador = respuesta if respuesta is not None else {
        "resumen": "Anemia severa.", "evidencia_suficiente": True, "clasificacion_confirmada": "ANEMIA_SEVERA",
        "recomendacion": [{"texto": "La hemoglobina se controla al mes, al segundo, al tercer y al sexto mes de "
                                    "iniciado el tratamiento.", "tipo": "TRATAMIENTO", "citas": ["F-02"]},
                          {"texto": "Se refiere inmediatamente a un establecimiento de salud de mayor capacidad "
                                    "resolutiva.", "tipo": "DERIVACION", "citas": ["F-01"]}]}
    return {"estado": estado, "texto_filtrado": "¿Cada cuánto se controla la hemoglobina?",
            "clasificacion": "ANEMIA_SEVERA", "tiene_respuesta": estado in cue.CON_GENERACION,
            "respuesta_borrador": borrador if estado in cue.CON_GENERACION else None,
            "respuesta_texto": texto_respuesta(borrador) if estado in cue.CON_GENERACION else "",
            "evidencia_suficiente": True, "derivacion_en_respuesta": True, "fragmentos": fragmentos,
            "citados": list(citados), "intentos": [{"costo_usd": 0.0, "tokens_entrada": 1200, "tokens_salida": 90,
                                                    "modelo_llm": "modelo-falso"}]}


def test_texto_de_la_respuesta_sin_etiquetas():
    assert texto_respuesta({"resumen": " R. ", "recomendacion": [{"texto": "Paso 1"}, {"texto": ""}]}) == "R.\nPaso 1"
    assert texto_respuesta(None) == ""


def test_juicio_de_un_caso_con_el_juez_falso(piloto, tmp_path):
    p06 = next(c for c in piloto.casos if c.id == "OE3-P06")
    juez = Juez(JuezFalso(), ConfiguracionJuez(k=3), tmp_path, casos_permitidos={p06.id})
    r = juzgar.juzgar_caso(juez, p06, _extraccion(), k=3, con_ragas=False)
    d, a = r["determinista"], r["agregado"]
    assert d["exito_recuperacion"] and d["cobertura_obligatorios"] == 1.0 and d["enviados"] == 2
    assert d["cue_citas"] == 0.5 and not d["perdido_en_seleccion"]
    assert a["cue_b"] == 1.0 and a["adherencia"] is not None and len(r["repeticiones"]) == 3
    assert a["cuadrante"] in cue.CUADRANTES
    # Sin fragmentos enviados: sin CUE ni juicio, recuperación fallida
    r = juzgar.juzgar_caso(juez, p06, _extraccion(fragmentos=[]), k=1, con_ragas=False)
    assert r["agregado"]["cue_b"] is None and r["determinista"]["exito_recuperacion"] is False
    assert r["determinista"]["cue_citas"] is None


def test_wilson_y_bootstrap():
    bajo, alto = informe.wilson(10, 20)
    assert round(bajo, 3) == 0.299 and round(alto, 3) == 0.701
    bajo, alto = informe.wilson(41, 48)
    assert 0.19 < alto - bajo < 0.21  # unos ±10 puntos con 48 casos (sección 9 del diseño)
    assert informe.wilson(0, 0) is None and informe.wilson(5, 5)[1] == 1.0
    valores = [0.2, 0.4, 0.6, 0.8, 1.0]
    assert informe.bootstrap_media(valores) == informe.bootstrap_media(valores)
    ic = informe.bootstrap_media(valores)
    assert ic[0] < 0.6 < ic[1]
    assert informe.bootstrap_media([]) is None and informe.bootstrap_media([0.3]) == (0.3, 0.3)


def test_informe_con_rotulo_de_ensayo_tablas_y_reproducibilidad(piloto, tmp_path, monkeypatch):
    from app.evaluacion import __main__ as cli
    salida = tmp_path / "corrida"
    casos = [c for c in piloto.casos if c.id in ("OE3-P06", "OE3-P07", "OE3-P08")]
    juez = Juez(JuezFalso(), ConfiguracionJuez(k=2), salida / "cache_juez", salida / "juez" / "juez-falso" / "llamadas.jsonl",
                {c.id for c in casos})
    extracciones = {"OE3-P06": _extraccion(),
                    "OE3-P07": _extraccion("EVIDENCIA_INSUFICIENTE", respuesta={
                        "resumen": "Evidencia insuficiente.", "evidencia_suficiente": False, "recomendacion": []}),
                    "OE3-P08": _extraccion("FUERA_DE_DOMINIO", fragmentos=[])}
    resultados = [juzgar.juzgar_caso(juez, c, extracciones[c.id], 2, con_ragas=False) for c in casos]
    cli._escribir_jsonl(salida / "juez" / "juez-falso" / "resultados.jsonl", resultados)
    cli._escribir_jsonl(salida / "extraccion.jsonl", [{"id_caso": k, "extraccion": v} for k, v in extracciones.items()])
    (salida / "juez" / "juez-falso" / "configuracion.json").write_text(json.dumps(
        {"tipo": "falso", "modelo": "juez-falso", "razonamiento": None, "esfuerzo": None, "max_tokens": 4000, "k": 2,
         "temperatura": "sin fijar", "ragas": False}), encoding="utf-8")
    (salida / "manifiesto.json").write_text(json.dumps(
        {"conjunto": piloto.manifiesto(), "llm": "falso", "huella_configuracion_inicio": "h1"}), encoding="utf-8")
    datos = cli.construir_informe(salida, "juez-falso", "v-prueba", "h1", ["ragas==0.4.4"], "0.4.4", True)
    json.dumps(datos, default=str)
    assert datos["ensayo"] and datos["rotulo"] == informe.ROTULO_ENSAYO
    r = datos["resumen"]
    assert r["casos"] == 3 and r["proporciones"]["estado_coincide"]["n"] == 3
    assert r["proporciones"]["exito_recuperacion"]["n"] == 1  # solo P06 tiene generación y criterios
    assert r["cuadrantes"][cue.NO_APLICA] == 1 and r["cuadrantes"][cue.RECHAZO_CORRECTO] == 1
    assert set(datos["desgloses"]) == {"tipo", "origen", "ingles", "cuadrante"}
    assert "anemia_severa" in datos["desgloses"]["tipo"]
    assert datos["costos"]["juez"]["llamadas"] > 0 and datos["costos"]["sistema"]["intentos"] == 3
    md = informe.markdown(datos)
    assert md.startswith(f"# {informe.ROTULO_ENSAYO}")
    for texto in ("## Resultados principales", "Wilson", "bootstrap", "## Cuadrantes (RAG-X) y categoría propia",
                  "## Desglose por tipo de consulta", "## Desglose por cuadrante", "## Costos", "## Reproducibilidad",
                  "`v-prueba`", piloto.huella, "(igual)", "sin temperatura", cue.FUERA_CUADRANTES,
                  "(simulado: cliente falso)"):
        assert texto in md, texto
    assert "\u2013" not in md and "\u2014" not in md
    # Una huella distinta al final queda señalada
    otro = cli.construir_informe(salida, "juez-falso", "v", "h2", [], "0.4.4", True)
    assert "(DISTINTA)" in informe.markdown(otro)
