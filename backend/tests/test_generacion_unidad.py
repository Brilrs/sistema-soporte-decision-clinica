"""Parte C sin base de datos ni API: filtro del texto libre, solicitud mínima, hash,
control previo, esquema de respuesta, controles de verificación, decisiones de la
Tabla 10 y clientes del modelo de lenguaje."""
import json

import pytest

from app.rag import generacion as gen
from app.rag import verificacion as ver
from app.rag.cliente_llm import (APROBADA, CITA_INVENTADA, CLASIFICACION_CONTRADICTORIA, CORTADA_MAX_TOKENS,
                                 DOSIS_INVENTADA, ERROR_API, ESQUEMA_INVALIDO, EVIDENCIA_INSUFICIENTE,
                                 EXTRACTO_INVENTADO, RECHAZO, TIEMPO_AGOTADO, TRADUCCION_CIFRAS_DISTINTAS,
                                 ClienteAnthropic, ClienteFalso, ConfiguracionLLM, ErrorEntornoPruebas)
from app.rag.filtro_texto import (DNI, FECHA, HC, NOMBRE, PACIENTE, TELEFONO, IdentidadPaciente,
                                  cargar_nombres_frecuentes, filtrar_texto, generar_huellas, idioma_respuesta,
                                  normalizar_palabra)
from app.rag.proteccion import (DatosClinicos, construir_solicitud, controlar_identificadores, hash_solicitud,
                                serializar)
from app.rag.recuperacion import FragmentoRecuperado

MATEO = IdentidadPaciente("Mateo Quispe Huamán", "81234567", "00452")
CONFIG = gen.ConfiguracionGeneracion(
    llm=ConfiguracionLLM("modelo-falso", 1000, 15, "between_tools", "medium"), version_prompt="v1.0",
    precio_entrada_usd_mtok=gen.Decimal("2.00"), precio_salida_usd_mtok=gen.Decimal("10.00"))
TEXTO_NTS = ("Tratamiento de la anemia leve en niños de 6 a 23 meses: sulfato ferroso 3 mg/kg/día durante "
             "6 meses continuos. Control de hemoglobina al mes, a los 3 y a los 6 meses de iniciado el tratamiento.")
TEXTO_OMS = ("Daily iron supplementation with 10 to 12.5 mg elemental iron is recommended for infants and young "
             "children aged 6 to 23 months in settings where anaemia prevalence is 40% or higher.")


def _datos(clasificacion="ANEMIA_LEVE", riesgo="MODERADO", derivacion=False, **cambios) -> DatosClinicos:
    base = dict(edad_meses=14, sexo="M", altitud_msnm=160, hb_observada_g_dl=9.8, hb_ajustada_g_dl=9.8,
                clasificacion=clasificacion, nivel_riesgo=riesgo, requiere_derivacion=derivacion, peso_kg=9.6,
                suplementacion_hierro=False, lactancia_materna_actual=True, parasitosis_reciente=False,
                bajo_peso_nacer=False, edad_gestacional="A_TERMINO", sintomas=("Hiporexia", "Palidez"),
                tamizaje_anterior={"meses_transcurridos": 4, "hb_g_dl": 10.1, "clasificacion": "ANEMIA_LEVE"})
    return DatosClinicos(**{**base, **cambios})


def _fragmento(i: int, texto: str, idioma: str = "es", codigo: str = "NTS 213-MINSA/DGIESP-2024") -> FragmentoRecuperado:
    return FragmentoRecuperado(
        id_fragmento=f"00000000-0000-0000-0000-{i:012d}", posicion_bm25=i, posicion_vectorial=i, posicion_rrf=i,
        puntaje_rrf=0.03, puntaje_reranker=0.9, posicion_final=i, seleccionado=True, id_documento=f"doc-{idioma}",
        documento="Guía", codigo_documento=codigo, seccion="5.2 Tratamiento", pagina_inicio=10, pagina_fin=10,
        idioma=idioma, tipo_contenido="TEXTO", texto=texto)


def _solicitud(datos=None, consulta="tratamiento de anemia leve", idioma="es", fragmentos=None):
    fragmentos = fragmentos or [_fragmento(1, TEXTO_NTS), _fragmento(2, TEXTO_OMS, "en", "OMS 2024")]
    return construir_solicitud(datos or _datos(), consulta, idioma, fragmentos, {"doc-es": "MINSA", "doc-en": "OMS"})


def _respuesta(cliente: ClienteFalso, solicitud):
    return gen.generar(cliente, solicitud, CONFIG)


# ---------------------------------------------------------------------------
# Filtro del texto libre
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("texto, esperado", [
    ("¿Qué tratamiento le doy a Mateo Quispe?", "¿Qué tratamiento le doy a [PACIENTE]?"),
    ("mateo tiene palidez", "[PACIENTE] tiene palidez"),
    ("QUISPE HUAMAN no toma el hierro", "[PACIENTE] no toma el hierro"),
    ("DNI 81234567", "DNI [DNI]"),
    ("dni 81 234 567", "dni [DNI]"),
    ("HC 00452", "HC [HC]"),
    ("historia clínica N° 77812", "[HC]"),
    ("llamar al 987 654 321", "llamar al [TELEFONO]"),
    ("teléfono: (01) 456-7890", "[TELEFONO]"),
    ("nació el 12/07/2025", "nació el [FECHA]"),
    ("nació el 12 de julio de 2025", "nació el [FECHA]"),
    ("otro DNI 44556677", "otro DNI [DNI]"),
])
def test_filtro_reemplaza_los_identificadores(texto, esperado):
    assert filtrar_texto(texto, MATEO).texto_filtrado == esperado


@pytest.mark.parametrize("texto", ["Hb 9,8 g/dL a los 14 meses", "niños de 6 a 23 meses", "sulfato ferroso 3 mg/kg/día",
                                   "control en 1, 3 y 6 meses", "Hb 10.1 hace 4 meses en julio",
                                   "palidez e hiporexia, Rosa y Luz en el patio", "clara de huevo y flor de brócoli"])
def test_filtro_sin_falsos_positivos(texto):
    r = filtrar_texto(texto, MATEO)
    assert r.texto_filtrado == texto and not r.reemplazos


def test_filtro_reemplaza_nombres_frecuentes_de_terceros():
    r = filtrar_texto("La mamá, Juana Ccori, pregunta si puede darle hierro", MATEO)
    assert r.texto_filtrado == f"La mamá, {NOMBRE}, pregunta si puede darle hierro"


def test_lista_de_nombres_sin_palabras_comunes_ni_terminos_clinicos():
    nombres = cargar_nombres_frecuentes()
    assert 250 <= len(nombres) <= 350
    for comun in ("rosa", "luz", "flor", "mateo", "dolores", "clara", "flores", "rojas", "torres", "julio", "severo",
                  "hierro", "anemia", "palidez"):
        assert comun not in nombres


def test_marcas_y_partes_del_nombre_del_paciente():
    r = filtrar_texto("Mateo Quispe Huamán, DNI 81234567, HC 00452, cel 912345678, 01/02/2026", MATEO)
    assert r.texto_filtrado == f"{PACIENTE}, DNI {DNI}, HC {HC}, {TELEFONO}, {FECHA}"


def test_huellas_de_cada_parte_del_nombre_dni_e_historia_sin_guardar_valores():
    huellas = generar_huellas(MATEO)
    assert len(huellas) == 5
    assert "Mateo" not in repr(huellas) and "81234567" not in repr(huellas) and "protegida" in repr(MATEO)


def test_huellas_con_etiqueta_distinta_de_dni_hash():
    from app.core.seguridad import hmac_identificador
    from app.rag.filtro_texto import huella
    assert hmac_identificador("81234567") != huella("81234567")


def test_idioma_de_la_respuesta():
    assert idioma_respuesta("What iron dose should a child with mild anemia receive?") == "en"
    assert idioma_respuesta("¿Qué dosis de hierro le corresponde?") == "es"
    assert idioma_respuesta("Dosis de hierro para anemia leve, responde en inglés") == "en"
    assert idioma_respuesta("What is the dose? Responde en español") == "es"


# ---------------------------------------------------------------------------
# Solicitud mínima, hash y control previo
# ---------------------------------------------------------------------------
def test_solicitud_solo_con_los_campos_de_la_lista_blanca():
    s = _solicitud().contenido
    assert set(s) == {"version_solicitud", "idioma_respuesta", "consulta", "paciente", "tamizaje_anterior", "evidencia"}
    assert set(s["paciente"]) == {
        "edad_meses", "sexo", "altitud_msnm", "hb_observada_g_dl", "hb_ajustada_g_dl", "clasificacion", "nivel_riesgo",
        "requiere_derivacion", "peso_kg", "suplementacion_hierro", "lactancia_materna_actual", "parasitosis_reciente",
        "bajo_peso_nacer", "edad_gestacional", "sintomas"}
    assert set(s["tamizaje_anterior"]) == {"meses_transcurridos", "hb_g_dl", "clasificacion"}
    assert [e["etiqueta"] for e in s["evidencia"]] == ["F-01", "F-02"]
    assert [e["tipo_fuente"] for e in s["evidencia"]] == ["NORMA_NACIONAL", "OMS"]
    texto = serializar(s)
    for prohibido in ("talla", "observaciones", "distrito", "ubigeo", "fecha", "dni", "nombre"):
        assert prohibido not in texto


def test_hash_reproducible_e_independiente_del_orden_de_las_claves():
    a, b = _solicitud(), _solicitud()
    assert a.hash_sha256 == b.hash_sha256 == hash_solicitud(a.serializada)
    assert len(a.hash_sha256) == 64
    invertido = json.loads(a.serializada, object_pairs_hook=lambda pares: dict(reversed(pares)))
    assert hash_solicitud(serializar(invertido)) == a.hash_sha256
    assert _solicitud(consulta="otra consulta").hash_sha256 != a.hash_sha256


def test_control_aprueba_una_solicitud_sin_identificadores():
    r = controlar_identificadores(_solicitud().serializada, generar_huellas(MATEO))
    assert r.aprobado and r.coincidencias == 0


@pytest.mark.parametrize("consulta", ["tratamiento para mateo", "tratamiento para QUISPE", "dni 81234567",
                                      "dni 81.234.567", "historia 00452"])
def test_control_bloquea_un_identificador_colado_en_la_consulta(consulta):
    r = controlar_identificadores(_solicitud(consulta=consulta).serializada, generar_huellas(MATEO))
    assert not r.aprobado and r.coincidencias >= 1


def test_control_bloquea_un_nombre_colado_en_un_fragmento_de_evidencia():
    fragmentos = [_fragmento(1, TEXTO_NTS + " Caso de Huamán atendido en el establecimiento.")]
    r = controlar_identificadores(_solicitud(fragmentos=fragmentos).serializada, generar_huellas(MATEO))
    assert not r.aprobado and r.tipos == ("PALABRA",)


def test_control_no_devuelve_el_valor_que_coincidio():
    r = controlar_identificadores(_solicitud(consulta="mateo").serializada, generar_huellas(MATEO))
    assert "mateo" not in repr(r).lower()


# ---------------------------------------------------------------------------
# Esquema, prompt y parámetros de la generación
# ---------------------------------------------------------------------------
def test_esquema_cumple_las_limitaciones_de_la_salida_estructurada():
    esquema = gen.cargar_esquema()

    def recorrer(nodo):
        if isinstance(nodo, dict):
            if nodo.get("type") == "object":
                assert nodo.get("additionalProperties") is False
                assert set(nodo.get("required", [])) == set(nodo.get("properties", {}))
            assert not {"minLength", "maxLength", "minimum", "maximum", "maxItems"} & set(nodo)
            assert nodo.get("minItems", 0) in (0, 1)
            for v in nodo.values():
                recorrer(v)
        elif isinstance(nodo, list):
            for v in nodo:
                recorrer(v)
    recorrer(esquema)


def test_prompt_versionado_con_las_reglas_clinicas():
    prompt = gen.cargar_prompt("v1.0")
    for regla in ("Responde solo con la información de los fragmentos", "No inventes dosis", "prevalecen sobre los de la OMS",
                  "evidencia_suficiente", "idioma_respuesta", "extracto_traducido", "no sustituye su criterio clínico"):
        assert regla in prompt
    assert "\u2014" not in prompt and "\u2013" not in prompt


def test_respuesta_aprobada_cumple_el_esquema_y_calcula_el_costo():
    r = _respuesta(ClienteFalso([APROBADA]), _solicitud())
    assert r.estado == gen.RESPUESTA and r.respuesta["citas"][0]["etiqueta"] == "F-01"
    assert r.costo_usd == gen.costo_usd(r.tokens_entrada, r.tokens_salida, CONFIG)
    assert gen.costo_usd(1_000_000, 100_000, CONFIG) == gen.Decimal("3.00000")


def test_mayusculas_de_los_enum_no_invalidan_la_respuesta():
    cuerpo = json.loads(ClienteFalso([APROBADA]).generar("", _solicitud().serializada, {}, CONFIG.llm).texto)
    cuerpo["clasificacion_confirmada"] = "Anemia_Leve"
    respuesta, motivo = gen.interpretar(json.dumps(cuerpo))
    assert motivo is None and respuesta["clasificacion_confirmada"] == "ANEMIA_LEVE"


@pytest.mark.parametrize("modo, estado", [(ESQUEMA_INVALIDO, gen.INVALIDA), (CORTADA_MAX_TOKENS, gen.INVALIDA),
                                          (TIEMPO_AGOTADO, gen.TIEMPO_AGOTADO), (RECHAZO, gen.RECHAZO),
                                          (ERROR_API, gen.ERROR_API)])
def test_generacion_clasifica_las_respuestas_que_no_se_verifican(modo, estado):
    r = _respuesta(ClienteFalso([modo]), _solicitud())
    assert r.estado == estado and r.respuesta is None


def test_respuesta_cortada_por_max_tokens_registra_los_tokens_de_razonamiento():
    r = _respuesta(ClienteFalso([CORTADA_MAX_TOKENS]), _solicitud())
    assert r.estado == gen.INVALIDA and "MAX_TOKENS_SALIDA" in r.motivo
    assert r.tokens_razonamiento == 500 and r.tokens_salida > r.tokens_razonamiento


def test_cliente_real_no_se_puede_crear_en_pruebas(monkeypatch):
    monkeypatch.setenv("CDSS_ENTORNO", "pruebas")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "clave-que-no-se-usa")
    with pytest.raises(ErrorEntornoPruebas):
        ClienteAnthropic()


def test_las_pruebas_corren_con_cdss_entorno_pruebas():
    import os
    assert os.environ.get("CDSS_ENTORNO") == "pruebas"


def test_cliente_falso_rechaza_modos_desconocidos():
    with pytest.raises(ValueError):
        ClienteFalso(["inventado"])


# ---------------------------------------------------------------------------
# Verificación (6.1, 6.2, 6.3 y controles adicionales)
# ---------------------------------------------------------------------------
VIGENTES = {_fragmento(1, "").id_fragmento, _fragmento(2, "").id_fragmento}


def _verificar(modo, datos=None, preferir_ingles=False, relevancia=0.9, vigentes=VIGENTES, idioma="es"):
    datos = datos or _datos()
    solicitud = _solicitud(datos, idioma=idioma)
    r = _respuesta(ClienteFalso([modo], preferir_ingles=preferir_ingles), solicitud)
    assert r.estado == gen.RESPUESTA, r.motivo
    return ver.verificar(r.respuesta, solicitud, datos, relevancia, 0.15, vigentes)


def test_respuesta_aprobada_pasa_los_tres_controles():
    assert _verificar(APROBADA).aprobada


def test_respuesta_con_cita_de_la_oms_y_traduccion_de_apoyo_pasa():
    v = _verificar(APROBADA, preferir_ingles=True)
    assert v.aprobada, v.motivos


@pytest.mark.parametrize("modo, control", [(CITA_INVENTADA, "valida_citas"), (EXTRACTO_INVENTADO, "valida_citas"),
                                           (DOSIS_INVENTADA, "valida_citas"),
                                           (CLASIFICACION_CONTRADICTORIA, "valida_consistencia"),
                                           (EVIDENCIA_INSUFICIENTE, "valida_evidencia")])
def test_cada_control_detecta_su_falla(modo, control):
    v = _verificar(modo)
    assert not getattr(v, control) and not v.aprobada


def test_traduccion_con_cifras_distintas_falla_6_1():
    v = _verificar(TRADUCCION_CIFRAS_DISTINTAS, preferir_ingles=True)
    assert not v.valida_citas and any(m.startswith("Traducción") for m in v.motivos)


def test_fragmento_citado_que_dejo_de_ser_vigente_falla_6_1():
    v = _verificar(APROBADA, vigentes=set())
    assert not v.valida_citas and any(m.startswith("Vigencia") for m in v.motivos)


def test_puntaje_bajo_el_umbral_falla_6_3():
    assert not _verificar(APROBADA, relevancia=0.05).valida_evidencia


def test_tratamiento_a_un_nino_sin_anemia_falla_6_2():
    solicitud = _solicitud(_datos("ANEMIA_LEVE", "MODERADO"))
    r = _respuesta(ClienteFalso([APROBADA]), solicitud)
    v = ver.verificar(r.respuesta, solicitud, _datos("SIN_ANEMIA", "BAJO"), 0.9, 0.15, VIGENTES)
    assert not v.valida_consistencia
    assert "6.2: indica tratamiento de la anemia a un niño sin anemia" in v.motivos


def test_anemia_severa_sin_derivacion_falla_6_2():
    datos = _datos("ANEMIA_SEVERA", "MUY_ALTO", derivacion=True)
    solicitud = _solicitud(datos)
    r = _respuesta(ClienteFalso([APROBADA]), solicitud)
    r.respuesta["recomendacion"] = [p for p in r.respuesta["recomendacion"] if p["tipo"] != "DERIVACION"]
    assert not ver.verificar(r.respuesta, solicitud, datos, 0.9, 0.15, VIGENTES).valida_consistencia
    assert _verificar(APROBADA, datos=datos).aprobada


def test_control_de_dosis_acepta_las_cifras_del_fragmento_citado():
    solicitud = _solicitud()
    r = _respuesta(ClienteFalso([APROBADA]), solicitud)
    r.respuesta["recomendacion"][0]["texto"] = "Sulfato ferroso 3 mg/kg/día durante 6 meses; Hb 9,8 g/dL."
    assert ver.verificar(r.respuesta, solicitud, _datos(), 0.9, 0.15, VIGENTES).valida_citas
    r.respuesta["recomendacion"][0]["texto"] = "Sulfato ferroso 4 mg/kg/día."
    assert not ver.verificar(r.respuesta, solicitud, _datos(), 0.9, 0.15, VIGENTES).valida_citas


def test_cifras_de_dosis_y_traduccion():
    assert ver.dosis("3 mg/kg/día y 12,5 mg; Hb 9,8 g/dL; 10 ml") == {("3", "mg/kg"), ("12.5", "mg"), ("10", "ml")}
    assert ver.dosis("3 mg/kg/day") == ver.dosis("3 mg/kg/día")
    assert ver.cifras("10 to 12.5 mg") == ver.cifras("10 a 12,5 mg")


# ---------------------------------------------------------------------------
# Tabla 10
# ---------------------------------------------------------------------------
APROBADA_V = ver.ResultadoVerificacion(True, True, True)
FALLA_CITAS = ver.ResultadoVerificacion(False, True, True)
FALLA_CONSISTENCIA = ver.ResultadoVerificacion(True, False, True)
FALLA_EVIDENCIA = ver.ResultadoVerificacion(True, True, False)


@pytest.mark.parametrize("numero, estado, verificacion, esperado", [
    (1, gen.RESPUESTA, APROBADA_V, (ver.APROBADO, None, ver.VERIFICADA)),
    (2, gen.RESPUESTA, APROBADA_V, (ver.APROBADO, None, ver.VERIFICADA)),
    (1, gen.RESPUESTA, FALLA_CITAS, (ver.REINTENTO, ver.REGENERAR, None)),
    (1, gen.RESPUESTA, FALLA_CONSISTENCIA, (ver.REINTENTO, ver.REGENERAR, None)),
    (1, gen.INVALIDA, None, (ver.REINTENTO, ver.REGENERAR, None)),
    (1, gen.RESPUESTA, FALLA_EVIDENCIA, (ver.REINTENTO, ver.AMPLIADA, None)),
    (1, None, None, (ver.REINTENTO, ver.AMPLIADA, None)),
    (2, gen.RESPUESTA, FALLA_CITAS, (ver.EVIDENCIA_INSUFICIENTE, None, ver.EVIDENCIA_INSUFICIENTE)),
    (2, gen.RESPUESTA, FALLA_CONSISTENCIA, (ver.EVIDENCIA_INSUFICIENTE, None, ver.EVIDENCIA_INSUFICIENTE)),
    (2, gen.RESPUESTA, FALLA_EVIDENCIA, (ver.EVIDENCIA_INSUFICIENTE, None, ver.EVIDENCIA_INSUFICIENTE)),
    (2, None, None, (ver.EVIDENCIA_INSUFICIENTE, None, ver.EVIDENCIA_INSUFICIENTE)),
    (2, gen.INVALIDA, None, (ver.ERROR, None, ver.ERROR)),
    (1, gen.TIEMPO_AGOTADO, None, (ver.ERROR, None, ver.ERROR)),
    (1, gen.RECHAZO, None, (ver.ERROR, None, ver.ERROR)),
    (1, gen.ERROR_API, None, (ver.ERROR, None, ver.ERROR)),
])
def test_decisiones_de_la_tabla_10(numero, estado, verificacion, esperado):
    d = ver.decidir(numero, estado, verificacion)
    assert (d.resultado_intento, d.siguiente, d.estado_final) == esperado


def test_mensajes_al_profesional():
    assert ver.decidir(2, gen.RESPUESTA, FALLA_CITAS).mensaje == "Evidencia insuficiente: aplicar criterio clínico."
    for estado in (gen.TIEMPO_AGOTADO, gen.RECHAZO, gen.ERROR_API):
        assert ver.decidir(1, estado, None).mensaje == "No se pudo evaluar la consulta. Aplique su criterio clínico."
    assert ver.decidir(1, None, None, bloqueada=True).estado_final == ver.ERROR


def test_normalizacion_de_extractos():
    assert ver.normalizar_texto("Sulfato  ferroso\n«3 mg»") == ver.normalizar_texto('sulfato ferroso "3 mg"')
    assert normalizar_palabra("HUAMÁN") == "huaman"


# ---------------------------------------------------------------------------
# Corrida real: tokens de razonamiento, prompt v1.1 e informe ampliado
# ---------------------------------------------------------------------------
def _mensaje_sdk(detalles: bool):
    from anthropic.types import Message
    uso = {"input_tokens": 5019, "output_tokens": 703}
    if detalles:
        uso["output_tokens_details"] = {"thinking_tokens": 37}
    return Message.model_validate({
        "id": "msg_prueba", "type": "message", "role": "assistant", "model": "claude-sonnet-5-5",
        "content": [{"type": "text", "text": "{}"}], "stop_reason": "max_tokens", "stop_sequence": None,
        "usage": uso})


def test_tokens_de_razonamiento_se_leen_de_output_tokens_details():
    from app.rag.cliente_llm import respuesta_desde_mensaje
    r = respuesta_desde_mensaje(_mensaje_sdk(True), 10)
    assert (r.tokens_entrada, r.tokens_salida, r.tokens_razonamiento, r.fin) == (5019, 703, 37, "max_tokens")
    assert respuesta_desde_mensaje(_mensaje_sdk(False), 10).tokens_razonamiento is None


def test_prompt_v1_1_pide_respuesta_compacta_sin_cambiar_la_suficiencia():
    v10, v11 = gen.cargar_prompt("v1.0"), gen.cargar_prompt("v1.1")
    regla_7 = next(linea for linea in v10.splitlines() if linea.startswith("7. "))
    assert regla_7 in v11
    for regla in ("como máximo 3 oraciones", "como máximo 3 pasos", "un solo extracto", "hasta unos 200 caracteres",
                  "como máximo 4 frases", "como máximo 3 frases"):
        assert regla in v11
    assert "—" not in v11 and "–" not in v11


def test_informe_guarda_fragmentos_y_respuesta_aunque_este_cortada():
    from app.scripts.prueba_punta_a_punta import _detalle_intento, fragmentos_enviados, respuesta_modelo
    solicitud = _solicitud()
    enviados = fragmentos_enviados(solicitud)
    assert [f["etiqueta"] for f in enviados] == ["F-01", "F-02"]
    assert enviados[0]["documento"] == "NTS 213-MINSA/DGIESP-2024" and len(enviados[0]["texto_inicio"]) <= 200
    cortada = _respuesta(ClienteFalso([CORTADA_MAX_TOKENS]), solicitud)
    m = respuesta_modelo(cortada)
    assert m["texto_sin_interpretar"] and m["largo_caracteres"] == len(cortada.texto)
    aprobada = respuesta_modelo(_respuesta(ClienteFalso([APROBADA]), solicitud))
    assert set(aprobada) == {"evidencia_suficiente", "resumen", "advertencias", "recomendacion", "citas"}
    intento = {"tiempos_ms": {"recuperacion": 3300, "proteccion": 2, "llamada_modelo": 6000, "verificacion": 1},
               "generacion": cortada.estado, "stop_reason": cortada.fin, "tokens_entrada": 1, "tokens_salida": 2,
               "max_tokens": 1500, "tokens_razonamiento": 0, "version_prompt": "v1.1",
               "fragmentos_enviados": enviados, "respuesta_modelo": m}
    texto = "\n".join(_detalle_intento(intento))
    assert "stop_reason max_tokens" in texto and "F-02 (OMS 2024" in texto and "llamada al modelo 6000" in texto


# ---------------------------------------------------------------------------
# Dosis derivada del peso de los datos estructurados
# ---------------------------------------------------------------------------
def _valida_dosis(paso: str, peso_kg=9.6, texto_fragmento=TEXTO_NTS) -> ver.ResultadoVerificacion:
    datos = _datos(peso_kg=peso_kg)
    solicitud = _solicitud(datos, fragmentos=[_fragmento(1, texto_fragmento)])
    r = _respuesta(ClienteFalso([APROBADA]), solicitud)
    r.respuesta["recomendacion"][0]["texto"] = paso
    return ver.verificar(r.respuesta, solicitud, datos, 0.9, 0.15, {_fragmento(1, "").id_fragmento})


def test_dosis_derivada_correcta_se_acepta():
    v = _valida_dosis("Sulfato ferroso 3 mg/kg/día: 28,8 mg/día de hierro elemental para 9,6 kg, durante 6 meses.")
    assert v.valida_citas, v.motivos
    assert _valida_dosis("Hierro elemental 28,9 mg al día.").valida_citas


def test_dosis_derivada_con_un_peso_distinto_al_de_los_datos_se_rechaza():
    assert not _valida_dosis("Hierro elemental 28,8 mg/día.", peso_kg=12.0).valida_citas
    # El peso lo pone el sistema: una cifra calculada con el peso que escribe el modelo no vale.
    v = _valida_dosis("Para 12 kg corresponden 36 mg/día de hierro elemental.", peso_kg=9.6)
    assert not v.valida_citas and any(m.startswith("Dosis") for m in v.motivos)


def test_cifra_de_dosis_inventada_se_rechaza():
    assert not _valida_dosis("Hierro elemental 50 mg/día.").valida_citas


def test_dosis_derivada_sin_cifra_en_mg_por_kg_en_el_fragmento_se_rechaza():
    v = _valida_dosis("Hierro elemental 28,8 mg/día.", texto_fragmento="Sulfato ferroso en gotas, 25 mg de hierro "
                                                                        "elemental por mililitro, durante 6 meses.")
    assert not v.valida_citas


def test_dosis_en_mg_por_kg_por_dosis_exige_la_frecuencia():
    con_frecuencia = "Sulfato ferroso 2 mg/kg por dosis, una vez al día, durante 3 meses."
    sin_frecuencia = "Sulfato ferroso 2 mg/kg de peso corporal durante 3 meses."
    assert _valida_dosis("Hierro elemental 19,2 mg.", texto_fragmento=con_frecuencia).valida_citas
    assert not _valida_dosis("Hierro elemental 19,2 mg.", texto_fragmento=sin_frecuencia).valida_citas
    assert ver.cifras_por_kg("| 6 a 35 meses | 3 mg/Kg/día (Máximo dosis 70 mg/día) |") == {3.0}


def test_dosis_derivada_fuera_de_la_tolerancia_del_1_por_ciento_se_rechaza():
    assert not _valida_dosis("Hierro elemental 29,5 mg/día.").valida_citas


# ---------------------------------------------------------------------------
# Extractos de tablas: formato frente a parafraseo (caso c de la corrida real)
# ---------------------------------------------------------------------------
# Texto de la Tabla N° 20 de la NTS tal como quedó indexado: en la capa de texto, la
# etiqueta de la fila («6 meses a 35 meses») corta la celda en dos.
TABLA_20 = ("Tabla N°20\nControl de hemoglobina en el tratamiento de anemia en el niño y la niña,\n"
            "_________ el/la adolescente y mujer en edad fértil y gestante________\n"
            "Grupo de edad/ Condición Control de hemoglobina\n"
            "Niño < 6 meses nacido a término con Al mes de iniciado tratamiento\n"
            "_____adecuado peso al nacer Al segundo, tercer y sexto mes de iniciado\n"
            "6 meses a 35 meses tratamiento\n36 meses a 11 años\n")
TABLA_17 = "| 6 a 35 meses | 3 mg/Kg/día (Máximo dosis 70 mg/día) | Sulfato Ferroso | gotas o jarabe | Diaria |"


def _extracto_valido(extracto: str, texto_fragmento: str) -> bool:
    solicitud = _solicitud(fragmentos=[_fragmento(1, texto_fragmento)])
    r = _respuesta(ClienteFalso([APROBADA]), solicitud)
    r.respuesta["citas"][0]["extracto"] = extracto
    return ver.verificar(r.respuesta, solicitud, _datos(), 0.9, 0.15, {_fragmento(1, "").id_fragmento}).valida_citas


@pytest.mark.parametrize("extracto, texto", [
    ("adecuado peso al nacer Al segundo, tercer y sexto mes de iniciado", TABLA_20),
    ("el/la adolescente y mujer en edad fértil y gestante", TABLA_20),
    ("GRUPO DE EDAD/ CONDICIÓN   control de hemoglobina", TABLA_20),
    ("6 a 35 meses 3 mg/Kg/día (Máximo dosis 70 mg/día)", TABLA_17),
    ("| 6 a 35 meses | 3 mg/Kg/día", "6 a 35 meses\n3 mg/Kg/día (Máximo dosis 70 mg/día)"),
])
def test_extracto_que_solo_difiere_en_formato_de_tabla_se_acepta(extracto, texto):
    assert _extracto_valido(extracto, texto)


@pytest.mark.parametrize("extracto, texto", [
    # Caso c: el modelo unió la celda quitando la etiqueta de la fila intercalada.
    ("Al segundo, tercer y sexto mes de iniciado tratamiento", TABLA_20),
    ("Control de la hemoglobina al segundo, tercer y sexto mes del tratamiento", TABLA_20),
    ("3 mg/kg al día, máximo 70 mg al día", TABLA_17),
])
def test_extracto_reordenado_o_parafraseado_se_rechaza(extracto, texto):
    assert not _extracto_valido(extracto, texto)
