"""Parte G, paso d1: el reranker lee los fragmentos de la RM 429 sin la instrucción de modificación.

Unidad: texto_para_reranker con el texto real de la Tabla N° 4 y de un texto de la RM 429, otros
documentos y fragmentos sin marcas intactos; seleccionar entrega al reranker el texto recortado y
guarda el texto completo (el que va a la solicitud, las citas y M05); la verificación 6.1 acepta un
extracto de la parte que el reranker no lee y 6.2 no depende del texto."""
from types import SimpleNamespace

from app.core.modelos import RerankerFalso
from app.rag import recuperacion as rec
from app.rag import verificacion as ver
from app.rag.normalizacion import ConsultaNormalizada
from app.rag.parametros import ParametrosRecuperacion
from app.rag.proteccion import DatosClinicos, construir_solicitud

RM429 = "RM 429-2024/MINSA"
NTS213 = "NTS 213-MINSA/DGIESP-2024"

# Texto real del fragmento de la Tabla N° 4 (versión 5 de la indexación), con las filas de niños.
TABLA_4 = (
    "NTS 213 modificada por RM 429-2024/MINSA, numeral 6.1.1 A Tabla 4\n"
    "5. Modificar la Tabla N° 4 del literal A del subnumeral 6.1.1 del numeral 6.1 del apartado VI de la "
    "NTS N° 213-MINSA/DGIESP-2024, conforme al siguiente detalle:\n"
    "\"VI. DISPOSICIONES ESPECÍFICAS\n"
    "6.1. INTERVENCIONES SANITARIAS EN LA ANEMIA POR DEFICIENCIA DE HIERRO\n"
    "6.1.1. Acciones de prevención (Anexo N° 1)\n"
    "A. Medición de hemoglobina\n"
    "(...)\n"
    "Tabla N° 4\n"
    "Medición de hemoglobina por grupo de edad durante la suplementación\n"
    "\n"
    "| Condición/Grupo de edad | Medición de hemoglobina |\n"
    "| --- | --- |\n"
    "| 6 a 11 meses de edad | 3 mediciones: a partir de los 6 meses de edad; al tercer mes de iniciada la "
    "suplementación (control); al término de la suplementación (control) |\n"
    "| 12 a 23 meses de edad | 3 mediciones: antes de iniciar la suplementación; al tercer mes de iniciada la "
    "suplementación (control); al término de la suplementación (control) |")

# Texto real de un fragmento de texto de la RM 429 (definición de adherencia).
ADHERENCIA = (
    "NTS 213 modificada por RM 429-2024/MINSA, numeral 5.1 Adherencia al suplemento de hierro\n"
    "1.\n"
    "Modificar la definición operativa \"Adherencia al suplemento de hierro\" del numeral 5.1 del apartado V de "
    "la NTS N° 213-MINSA/DGIESP-2024, conforme al siguiente detalle:\n"
    "\"V.\n"
    "DISPOSICIONES GENERALES\n"
    "5.1.\n"
    "Definiciones Operativas\n"
    "• Adherencia al suplemento de hierro:\n"
    "Es el grado de cumplimiento del régimen de suplementación o tratamiento en relación con la dosis y "
    "tiempo indicado.")

# Fragmento de la RM 429 cuya tabla empieza en la segunda línea (Tablas 12 y 13): no cambia.
TABLA_12 = ("NTS 213 modificada por RM 429-2024/MINSA, numeral 6.1.2 A (Tablas 12 y 13)\n"
            "Tabla N° 12\nSignos y síntomas de la anemia\n\n| Órganos o sistemas afectados | Síntomas y signos |")


def test_la_tabla_4_conserva_la_primera_linea_y_empieza_en_la_tabla():
    recortado = rec.texto_para_reranker(RM429, TABLA_4)
    primera, segunda, *_ = recortado.split("\n")
    assert primera == TABLA_4.split("\n")[0]
    assert segunda == "Tabla N° 4"
    assert "| 12 a 23 meses de edad |" in recortado
    assert "Modificar" not in recortado and "DISPOSICIONES" not in recortado and "(...)" not in recortado
    assert recortado == primera + "\n" + TABLA_4[TABLA_4.index("Tabla N° 4\nMedición"):]


def test_un_texto_de_la_rm_429_pierde_la_instruccion_y_conserva_la_ruta():
    recortado = rec.texto_para_reranker(RM429, ADHERENCIA)
    assert recortado.split("\n")[0] == ADHERENCIA.split("\n")[0]
    assert recortado.split("\n")[1] == "\"V."
    assert "Modificar" not in recortado and "conforme al siguiente detalle" not in recortado
    assert "DISPOSICIONES GENERALES" in recortado and recortado.endswith("tiempo indicado.")


def test_otros_documentos_quedan_identicos():
    for codigo in (NTS213, "OMS-2024-ANEMIA", "OTRO"):
        assert rec.texto_para_reranker(codigo, TABLA_4) == TABLA_4
        assert rec.texto_para_reranker(codigo, ADHERENCIA) == ADHERENCIA


def test_un_fragmento_de_la_rm_429_sin_marcas_queda_identico():
    sin_marcas = "NTS 213 modificada por RM 429-2024/MINSA, numeral 7\nTexto sin instrucción ni tabla."
    assert rec.texto_para_reranker(RM429, sin_marcas) == sin_marcas
    assert rec.texto_para_reranker(RM429, TABLA_12) == TABLA_12
    assert rec.texto_para_reranker(RM429, "Una sola línea") == "Una sola línea"


def test_la_mencion_de_la_tabla_dentro_de_la_instruccion_no_cuenta_como_inicio():
    # «Modificar la Tabla N° 4» va en medio de la línea: la tabla empieza donde una línea empieza con ella.
    recortado = rec.texto_para_reranker(RM429, TABLA_4)
    assert recortado.count("Tabla N° 4") == 1


# ---------------------------------------------------------------------------
# seleccionar
# ---------------------------------------------------------------------------
class _RerankerQueGuarda(RerankerFalso):
    def __init__(self):
        self.recibidos: list[str] = []

    def puntuar(self, consulta, candidatos, max_longitud=None):
        self.recibidos = list(candidatos)
        return [0.9 if "Modificar" not in t else 0.1 for t in candidatos]


def _fila(id_: str, codigo: str, texto: str):
    return SimpleNamespace(id_fragmento=id_, id_documento="doc-" + id_, titulo="Documento " + id_,
                           codigo_documento=codigo, idioma="es", seccion="s", pagina_inicio=1, pagina_fin=1,
                           texto=texto, tipo_contenido="TABLA", edad_min_meses=None, edad_max_meses=None,
                           poblacion="GENERAL", rango_dudoso=False)


def _parametros() -> ParametrosRecuperacion:
    return ParametrosRecuperacion(candidatos_busqueda=20, candidatos_busqueda_ampliada=40, rrf_k=60,
                                  fragmentos_enviados=5, umbral_relevancia=0.15, umbral_dominio=0.65,
                                  candidatos_reranker=8, max_longitud_reranker=256, dias_vigencia_tamizaje=30,
                                  bonificacion_edad=0.7)


def _seleccionar(monkeypatch):
    filas = {"t4": _fila("t4", RM429, TABLA_4), "nts": _fila("nts", NTS213, ADHERENCIA)}
    monkeypatch.setattr(rec, "comprobar_fragmentos", lambda sesion, ids: {i: filas[i] for i in ids})
    monkeypatch.setattr(rec, "reglas_vigentes", lambda: ())
    cand = rec.Candidatos(tipo_busqueda=rec.INICIAL, texto_busqueda="consulta", candidatos_por_metodo=20,
                          fusionados=[("t4", 0.03, 1), ("nts", 0.02, 2)], filas=filas, posiciones_bm25={},
                          posiciones_vectoriales={}, descartados=[], cronometro=rec.Cronometro())
    reranker = _RerankerQueGuarda()
    consulta = ConsultaNormalizada(texto="consulta", texto_normalizado="consulta")
    return rec.seleccionar(None, consulta, cand, reranker, _parametros()), reranker


def test_el_reranker_recibe_el_texto_recortado_y_se_guarda_el_completo(monkeypatch):
    resultado, reranker = _seleccionar(monkeypatch)
    assert reranker.recibidos == [rec.texto_para_reranker(RM429, TABLA_4), ADHERENCIA]
    por_id = {f.id_fragmento: f for f in resultado.fragmentos}
    assert por_id["t4"].texto == TABLA_4 and por_id["nts"].texto == ADHERENCIA
    # El puntaje es el del texto recortado: la NTS conserva «Modificar» y queda bajo el umbral.
    assert por_id["t4"].puntaje_reranker == 0.9 and por_id["t4"].seleccionado
    assert por_id["nts"].puntaje_reranker == 0.1 and not por_id["nts"].seleccionado
    assert resultado.relevancia_maxima == 0.9


def _datos() -> DatosClinicos:
    return DatosClinicos(edad_meses=14, sexo="F", altitud_msnm=None, hb_observada_g_dl=11.6, hb_ajustada_g_dl=11.6,
                         clasificacion="SIN_ANEMIA", nivel_riesgo="BAJO", requiere_derivacion=False, peso_kg=9.0,
                         suplementacion_hierro=True, lactancia_materna_actual=True, parasitosis_reciente=False,
                         bajo_peso_nacer=False, edad_gestacional="A_TERMINO", sintomas=(), tamizaje_anterior=None)


def test_la_solicitud_y_la_verificacion_usan_el_texto_completo(monkeypatch):
    resultado, _ = _seleccionar(monkeypatch)
    enviados = [f for f in resultado.fragmentos if f.seleccionado]
    solicitud = construir_solicitud(_datos(), "consulta", "es", enviados, {})
    assert solicitud.etiquetas["F-01"].texto == TABLA_4
    assert "Modificar la Tabla N° 4" in str(solicitud.contenido["evidencia"][0])
    # 6.1: un extracto de la parte que el reranker no lee sigue apareciendo en el fragmento.
    respuesta = {"clasificacion_confirmada": "SIN_ANEMIA", "nivel_riesgo": "BAJO", "evidencia_suficiente": True,
                 "resumen": "r", "advertencias": [], "factores_identificados": [],
                 "recomendacion": [{"texto": "Medir la hemoglobina según la tabla.", "tipo": "PREVENCION",
                                    "citas": ["F-01"]}],
                 "citas": [{"etiqueta": "F-01", "extracto": "Modificar la Tabla N° 4 del literal A",
                            "extracto_traducido": None}]}
    v = ver.verificar(respuesta, solicitud, _datos(), resultado.relevancia_maxima, 0.15,
                      {f.id_fragmento for f in enviados})
    assert v.valida_citas and v.valida_consistencia and v.valida_evidencia, v.motivos
