"""Parte G (pendiente P4): conjuntos de aceptación del calendario de control de hemoglobina y la
medición `medir_recuperacion calendario`.

Unidad, sin base ni modelos: huellas de los conjuntos A y B, carga de las tres formas (libre,
estructurada y combinada como la arma el grafo), criterios estricto y aceptado del tratamiento,
--conjunto, y la fila por consulta (estado antes del modelo, tablas de otra edad, agregados por
puntero, puntajes de los evaluados, solo cuenta la última pasada) con su resumen."""
from types import SimpleNamespace

import pytest

from app.rag import recuperacion as rec
from app.rag.consulta_estructurada import combinar_consulta, construir_consulta
from app.rag.referencias import (CALENDARIO, CALENDARIO_B, NTS213, RM429, ConsultaCalendario, cargar_conjunto_calendario,
                                 contexto_desde_yaml, huella_archivo)
from app.scripts import medir_recuperacion as med

HUELLA_A = "de2e1dbce63571b8449c7e4d9be11cb91cdfa5bf3e3a933741a1ffb270fb7ca2"
HUELLA_B = "352334c8d26c41b59b32721edc79e55cddeb96d4db85f393f1f75018af4b5593"
TITULO_20 = "Tabla N° 20\nControl de hemoglobina en el tratamiento de anemia\n\n| Edad | Control |"
SEGUIMIENTO = "Seguimiento de casos de anemia. (...) Control de hemoglobina (Tabla N° 20)"


def _f(codigo: str, texto: str):
    return SimpleNamespace(codigo_documento=codigo, texto=texto)


def _cal(fila: str = "12 a 23 meses de edad") -> ConsultaCalendario:
    return ConsultaCalendario(id="X01", tipo="CALENDARIO", consulta="q", edad_meses=15, fila=fila)


def _trat() -> ConsultaCalendario:
    return ConsultaCalendario(id="X02", tipo="TRATAMIENTO", consulta="q", edad_meses=30)


# ---------------------------------------------------------------------------
# Conjuntos congelados
# ---------------------------------------------------------------------------
def test_huellas_de_los_conjuntos_congelados():
    assert huella_archivo(CALENDARIO) == HUELLA_A
    assert huella_archivo(CALENDARIO_B) == HUELLA_B


def test_b_sin_retornos_ni_guiones_largos():
    datos = CALENDARIO_B.read_bytes()
    assert b"\r" not in datos and "\u2014".encode() not in datos and "\u2013".encode() not in datos


def test_carga_de_b_con_las_tres_formas():
    b = cargar_conjunto_calendario(CALENDARIO_B)
    assert [q.id for q in b] == [f"B{i:02d}" for i in range(1, 21)]
    formas = [(q.tipo, q.forma) for q in b]
    assert formas.count(("CALENDARIO", "libre")) == 4 and formas.count(("CALENDARIO", "estructurada")) == 5
    assert formas.count(("CALENDARIO", "combinada")) == 4 and formas.count(("TRATAMIENTO", "libre")) == 2
    assert formas.count(("TRATAMIENTO", "estructurada")) == 3 and formas.count(("TRATAMIENTO", "combinada")) == 2
    b10 = next(q for q in b if q.id == "B10")
    estructurada = construir_consulta(contexto_desde_yaml({
        "edad_meses": 23, "categoria": "SIN_ANEMIA", "nivel_riesgo": "MODERADO", "hb_ajustada_g_dl": 11.3,
        "recibe_suplementacion_hierro": False, "bajo_peso_nacer": True}))
    assert b10.consulta == combinar_consulta(estructurada, "¿Qué análisis de sangre le tocan mientras dure la suplementación?")
    assert b10.consulta.endswith("y cuándo se mide la hemoglobina? ¿Qué análisis de sangre le tocan mientras dure "
                                 "la suplementación?")
    assert all(q.fila for q in b if q.tipo == "CALENDARIO") and not any(q.fila for q in b if q.tipo == "TRATAMIENTO")


def test_carga_de_a_sin_cambios():
    a = cargar_conjunto_calendario(CALENDARIO)
    assert len(a) == 16 and {q.forma for q in a} == {"libre", "estructurada"}
    a08 = next(q for q in a if q.id == "A08")
    assert a08.estructurada and a08.consulta == construir_consulta(contexto_desde_yaml({
        "edad_meses": 10, "categoria": "SIN_ANEMIA", "nivel_riesgo": "MODERADO", "hb_ajustada_g_dl": 11.1,
        "recibe_suplementacion_hierro": True, "bajo_peso_nacer": True, "prematuro": True}))


# ---------------------------------------------------------------------------
# Criterios
# ---------------------------------------------------------------------------
def test_calendario_estricto_y_aceptado_son_la_fila_de_la_rm_429():
    q = _cal()
    con_fila = _f(RM429, "| 12 a 23 meses de edad | 3 mediciones |")
    for criterio in (q.acierta_estricto, q.acierta_aceptado, q.acierta):
        assert criterio(con_fila)
        assert not criterio(_f(NTS213, "| 12 a 23 meses de edad | 3 mediciones |"))
        assert not criterio(_f(RM429, "| 24 a 35 meses de edad | 2 mediciones |"))


def test_tratamiento_estricto_exige_el_titulo_de_la_tabla_20():
    q = _trat()
    assert q.acierta_estricto(_f(NTS213, TITULO_20)) and q.acierta(_f(NTS213, TITULO_20))
    assert not q.acierta_estricto(_f(NTS213, SEGUIMIENTO)) and not q.acierta(_f(NTS213, SEGUIMIENTO))
    assert not q.acierta_estricto(_f(RM429, TITULO_20))


def test_tratamiento_aceptado_admite_la_tabla_o_el_fragmento_que_la_cita():
    q = _trat()
    assert q.acierta_aceptado(_f(NTS213, TITULO_20)) and q.acierta_aceptado(_f(NTS213, SEGUIMIENTO))
    assert not q.acierta_aceptado(_f(RM429, SEGUIMIENTO)) and not q.acierta_aceptado(_f("OMS 2024", SEGUIMIENTO))
    for otra in ("Ver Tabla N° 2.", "según Tabla N° 200", "Tabla N° 21", "Tabla 20", "control de hemoglobina"):
        assert not q.acierta_aceptado(_f(NTS213, otra)), otra


# ---------------------------------------------------------------------------
# Opción --conjunto
# ---------------------------------------------------------------------------
def test_opcion_conjunto():
    assert med.conjuntos_calendario("a,referencias") == ["a", "referencias"]
    assert med.conjuntos_calendario(" B ") == ["b"]
    for malo in ("c", "a,a", "", "a,,x"):
        with pytest.raises(Exception):
            med.conjuntos_calendario(malo)
    with pytest.raises(SystemExit):
        med.main(["calendario", "--conjunto", "prueba"])


# ---------------------------------------------------------------------------
# Fila por consulta y resumen
# ---------------------------------------------------------------------------
def _fr(id_: str, puntaje: float | None, seleccionado: bool, codigo: str = "OTRO", texto: str = "texto",
        tipo: str = "TEXTO", edades: tuple = (None, None), poblacion: str = "GENERAL", origen: str = rec.RERANKER,
        posicion: int | None = None) -> rec.FragmentoRecuperado:
    return rec.FragmentoRecuperado(
        id_fragmento=id_, posicion_bm25=None, posicion_vectorial=None, posicion_rrf=1, puntaje_rrf=0.01,
        puntaje_reranker=puntaje, posicion_final=posicion, seleccionado=seleccionado, id_documento="doc",
        documento="Documento", codigo_documento=codigo, seccion="s", pagina_inicio=1, pagina_fin=1, idioma="es",
        tipo_contenido=tipo, texto=texto, edad_min_meses=edades[0], edad_max_meses=edades[1], poblacion=poblacion,
        origen=origen)


def _pasada(fragmentos: list, relevancia: float | None, tipo: str = "INICIAL", ms: float = 100.0):
    return SimpleNamespace(fragmentos=fragmentos, seleccionados=[f for f in fragmentos if f.seleccionado],
                           relevancia_maxima=relevancia, umbral_relevancia=0.15, tipo_busqueda=tipo,
                           tiempos_ms={"reranker": ms})


def test_estado_previo_es_el_control_6_3_de_la_ultima_pasada():
    assert med.estado_previo(_pasada([], 0.15)) == med.PASA_AL_MODELO
    assert med.estado_previo(_pasada([], 0.149)) == med.EVIDENCIA_INSUFICIENTE
    assert med.estado_previo(_pasada([], None)) == med.EVIDENCIA_INSUFICIENTE


def test_fila_de_tratamiento_con_estricto_aceptado_y_otras_medidas():
    seguimiento = _fr("s11", 0.6, True, NTS213, SEGUIMIENTO, posicion=1)
    tabla_otra_edad = _fr("t6", 0.4, True, "NTS", "| 6 a 11 |", "TABLA", (6, 11), "NINO", posicion=2)
    tabla_dudosa = _fr("td", 0.3, True, "NTS", "| 6 a 11 |", "TABLA", (6, 11), "NINO", posicion=3)
    agregado = _fr("t4", None, True, RM429, "Tabla N° 4", "TABLA", origen=rec.PUNTERO)
    descartado = _fr("d", 0.05, False, posicion=4)
    no_evaluado = _fr("n", None, False)
    fila = med.fila_calendario("B", _trat(), 30, [_pasada([seguimiento, tabla_otra_edad, tabla_dudosa, agregado,
                                                           descartado, no_evaluado], 0.6)], {"td"})
    assert fila["t20_estricto"] is False and fila["t20_aceptado"] is True and fila["acierta"] is False
    assert fila["tablas_otra_edad"] == ["t6"] and fila["agregados_puntero"] == ["t4"]
    assert fila["estado_previo"] == med.PASA_AL_MODELO and fila["pasadas"] == 1 and fila["forma"] == "libre"
    puntajes = fila["detalle_pasadas"][0]["puntajes"]
    assert [p["id"] for p in puntajes] == ["s11", "t6", "td", "d"]
    assert [p["seleccionado"] for p in puntajes] == [True, True, True, False]
    assert fila["detalle_pasadas"][0]["relevancia_maxima"] == 0.6 and fila["reranker_ms"] == [100.0]


def test_fila_de_calendario_cuenta_solo_la_ultima_pasada():
    con_fila = _fr("t4", 0.8, True, RM429, "| 12 a 23 meses de edad | 3 mediciones |", "TABLA", posicion=1)
    inicial = _pasada([_fr("x", 0.1, False, posicion=1)], 0.1, ms=90.0)
    ampliada = _pasada([_fr("x", 0.05, False, posicion=1)], 0.05, "AMPLIADA", ms=110.0)
    fila = med.fila_calendario("A", _cal(), 15, [_pasada([con_fila], 0.8), ampliada], set())
    assert fila["acierta"] is False and fila["estado_previo"] == med.EVIDENCIA_INSUFICIENTE
    fila = med.fila_calendario("A", _cal(), 15, [inicial, _pasada([con_fila], 0.8, "AMPLIADA")], set())
    assert fila["acierta"] is True and fila["estado_previo"] == med.PASA_AL_MODELO and fila["pasadas"] == 2
    assert fila["t20_estricto"] is None and fila["t20_aceptado"] is None
    assert [p["tipo_busqueda"] for p in fila["detalle_pasadas"]] == ["INICIAL", "AMPLIADA"]


def test_fila_de_referencia_y_puntero_sin_tabla():
    puntero = _fr("p", 0.7, True, NTS213, "Se mide la hemoglobina según Tabla N° 4.", posicion=1)
    ref = SimpleNamespace(acierta=lambda f: f.id_fragmento == "p")
    fila = med.fila_calendario("REFERENCIA", ref, None, [_pasada([puntero], 0.7)], set())
    assert fila["tipo"] == "REFERENCIA" and fila["acierta"] is True and fila["puntero_sin_tabla"] is True


def test_resumen_por_conjunto_con_estricto_y_aceptado():
    def fila(conjunto, tipo, acierta, estricto=None, aceptado=None, estado=med.PASA_AL_MODELO, ms=(100.0,)):
        return {"conjunto": conjunto, "tipo": tipo, "acierta": acierta, "t20_estricto": estricto,
                "t20_aceptado": aceptado, "puntero_sin_tabla": False, "tablas_otra_edad": [],
                "agregados_puntero": ["t4"] if conjunto == "A" and acierta else [], "estado_previo": estado,
                "reranker_ms": list(ms)}
    consultas = {"A01": fila("A", "CALENDARIO", True), "A02": fila("A", "CALENDARIO", False),
                 "A13": fila("A", "TRATAMIENTO", True, True, True), "A15": fila("A", "TRATAMIENTO", False, False, True),
                 "A16": fila("A", "TRATAMIENTO", False, False, False, med.EVIDENCIA_INSUFICIENTE, (100.0, 300.0)),
                 "R01": fila("REFERENCIA", "REFERENCIA", True, ms=(200.0,))}
    r = med.resumen_calendario(consultas)
    assert r["A"]["CALENDARIO"] == {"total": 2, "aciertos": 1, "fallan": ["A02"]}
    assert r["A"]["TRATAMIENTO"] == {"total": 3, "aciertos": 1, "fallan": ["A15", "A16"], "estricto": 1,
                                     "aceptado": 2, "fallan_aceptado": ["A16"]}
    assert r["A"]["evidencia_insuficiente"] == ["A16"] and r["A"]["agregados_puntero"] == ["A01", "A13"]
    assert r["A"]["reranker_ms"] == {"p50": 100.0, "p90": 200.0, "n": 6}
    assert r["REFERENCIA"]["REFERENCIA"] == {"total": 1, "aciertos": 1, "fallan": []}
    assert r["reranker_ms"]["n"] == 7 and "B" not in r
