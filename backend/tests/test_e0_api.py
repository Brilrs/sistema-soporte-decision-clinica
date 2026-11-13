"""Parte E0 (backend para las pantallas de la parte E), con modelos falsos y el cliente falso
del modelo de lenguaje (nunca la API real): lista de consultas del paciente y el historial
(M08), verificación, intentos y relevancia por cita en el evento fin y en el resultado
guardado, el modo de LLM falso (CDSS_LLM=falso) y su marca modo_prueba."""
import pytest
from pydantic import ValidationError
from sqlalchemy import text

from app.api.routes import consultas as rutas
from app.rag.cliente_llm import APROBADA, ClienteFalso
from app.services import consultas as srv
from tests.test_d1_grafo import _caso, _ids, entorno  # noqa: F401 (fixtures)
from tests.test_d2_api import (IDENTIDAD_MATEO, _auditoria, _caso_http, _consultar, _cuerpo,  # noqa: F401
                               cliente_http, consultas_d2, usar_entorno)
from tests.test_generacion_bd import engine_clinica, engine_generacion, guia  # noqa: F401 (fixtures)


# ---------------------------------------------------------------------------
# Lista de consultas del paciente (M04 y M08)
# ---------------------------------------------------------------------------
def test_lista_solo_las_consultas_propias_de_la_mas_reciente(cliente_http, cabeceras, consultas_d2, super_engine,
                                                             usar_entorno):
    primera = _caso_http(cliente_http, cabeceras, consultas_d2, super_engine, usar_entorno, "i")[1][-1]["id_consulta"]
    segunda = _caso_http(cliente_http, cabeceras, consultas_d2, super_engine, usar_entorno, "i")[1][-1]["id_consulta"]
    ajena = _caso_http(cliente_http, cabeceras, consultas_d2, super_engine, usar_entorno, "i",
                       usuario="enf.rojas")[1][-1]["id_consulta"]
    id_paciente, _, _ = _ids(super_engine, _caso("i"))
    r = cliente_http.get(f"/api/pacientes/{id_paciente}/consultas", headers=cabeceras("med.salazar"))
    assert r.status_code == 200
    lista = [rutas.ConsultaListada.model_validate(c) for c in r.json()]
    ids = [c.id_consulta for c in lista]
    assert ajena not in ids and ids.index(segunda) < ids.index(primera)
    propia = next(c for c in lista if c.id_consulta == segunda)
    assert propia.estado == "VERIFICADA" and propia.modo_prueba and propia.categoria and propia.tipo_decision is None
    assert "[PACIENTE]" in propia.texto_filtrado
    for dato in IDENTIDAD_MATEO:
        assert dato not in r.text, dato
    ajenas = cliente_http.get(f"/api/pacientes/{id_paciente}/consultas", headers=cabeceras("enf.rojas")).json()
    assert ajena in [c["id_consulta"] for c in ajenas] and segunda not in [c["id_consulta"] for c in ajenas]
    # El historial del paciente (M08) trae la misma lista.
    historial = cliente_http.get(f"/api/pacientes/{id_paciente}/historial", headers=cabeceras("med.salazar")).json()
    assert [c["id_consulta"] for c in historial["consultas"]] == ids
    assert _auditoria(super_engine, "CONSULTAS_LISTADAS", id_paciente)


def test_lista_errores_y_roles(cliente_http, cabeceras):
    assert cliente_http.get("/api/pacientes/00000000-0000-0000-0000-00000000abcd/consultas",
                            headers=cabeceras("med.salazar")).status_code == 404
    r = cliente_http.get("/api/pacientes/00000000-0000-0000-0000-00000000abcd/consultas",
                         headers=cabeceras("admin.cdss"))
    assert r.status_code == 403
    assert cliente_http.get("/api/pacientes/00000000-0000-0000-0000-00000000abcd/consultas").status_code == 401


def test_lista_incluye_la_decision(cliente_http, cabeceras, consultas_d2, super_engine, usar_entorno):
    c = _caso_http(cliente_http, cabeceras, consultas_d2, super_engine, usar_entorno, "b")[1][-1]["id_consulta"]
    cliente_http.post(f"/api/consultas/{c}/decision", json={"tipo_decision": "ACEPTA_RECOMENDACION"},
                      headers=cabeceras("med.salazar"))
    id_paciente, _, _ = _ids(super_engine, _caso("b"))
    lista = cliente_http.get(f"/api/pacientes/{id_paciente}/consultas", headers=cabeceras("med.salazar")).json()
    assert next(x for x in lista if x["id_consulta"] == c)["tipo_decision"] == "ACEPTA_RECOMENDACION"


# ---------------------------------------------------------------------------
# Verificación, intentos y relevancia por cita
# ---------------------------------------------------------------------------
def test_fin_y_resultado_con_verificacion_intentos_y_relevancia(cliente_http, cabeceras, consultas_d2, super_engine,
                                                                usar_entorno):
    fin = _caso_http(cliente_http, cabeceras, consultas_d2, super_engine, usar_entorno, "l")[1][-1]
    assert fin["numero_intentos"] == 1 and len(fin["intentos"]) == 1
    intento = fin["intentos"][0]
    assert intento["tipo_busqueda"] == "INICIAL" and intento["candidatos_evaluados"] > 0
    assert intento["umbral_relevancia"] == pytest.approx(0.05) and intento["resultado"] == "APROBADO"
    v = fin["verificacion"]
    assert (v["valida_citas"], v["valida_consistencia"], v["valida_evidencia"], v["numero_intento"]) == (
        True, True, True, 1)
    assert v["relevancia_maxima"] == intento["relevancia_maxima"]
    assert all(isinstance(c["puntaje_reranker"], float) for c in fin["citas"]) and fin["modo_prueba"] is True
    guardado = cliente_http.get(f"/api/consultas/{fin['id_consulta']}", headers=cabeceras("med.salazar")).json()
    assert guardado["intentos"] == fin["intentos"] and guardado["modo_prueba"] is True
    assert guardado["verificacion"] == fin["verificacion"]
    assert [c["puntaje_reranker"] for c in guardado["citas"]] == [c["puntaje_reranker"] for c in fin["citas"]]


def test_intentos_de_un_reintento_y_de_un_estado_sin_intentos(cliente_http, cabeceras, consultas_d2, super_engine,
                                                              usar_entorno):
    fin = _caso_http(cliente_http, cabeceras, consultas_d2, super_engine, usar_entorno, "j")[1][-1]
    assert [i["tipo_busqueda"] for i in fin["intentos"]] == ["INICIAL", "AMPLIADA"]
    assert [i["resultado"] for i in fin["intentos"]] == ["REINTENTO", "EVIDENCIA_INSUFICIENTE"]
    assert fin["verificacion"]["numero_intento"] == 2
    guardado = cliente_http.get(f"/api/consultas/{fin['id_consulta']}", headers=cabeceras("med.salazar")).json()
    assert guardado["intentos"] == fin["intentos"] and guardado["recomendacion"] is None
    fin = _caso_http(cliente_http, cabeceras, consultas_d2, super_engine, usar_entorno, "g")[1][-1]
    assert (fin["intentos"], fin["verificacion"], fin["modo_prueba"]) == ([], None, False)
    guardado = cliente_http.get(f"/api/consultas/{fin['id_consulta']}", headers=cabeceras("med.salazar")).json()
    assert (guardado["intentos"], guardado["verificacion"], guardado["modo_prueba"]) == ([], None, False)


# ---------------------------------------------------------------------------
# LLM falso (CDSS_LLM=falso) y la marca modo_prueba
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("entorno_app", ["pruebas", "produccion", "staging"])
def test_cdss_llm_falso_se_rechaza_fuera_de_desarrollo(monkeypatch, entorno_app):
    from app.core.config import Settings
    monkeypatch.setenv("CDSS_ENTORNO", entorno_app)
    monkeypatch.setenv("CDSS_LLM", "falso")
    with pytest.raises(ValidationError, match="CDSS_LLM=falso solo se admite con CDSS_ENTORNO=desarrollo"):
        Settings()


def test_cdss_llm_falso_en_desarrollo_usa_el_cliente_falso(monkeypatch):
    from app.core.config import Settings
    monkeypatch.setenv("CDSS_ENTORNO", "desarrollo")
    monkeypatch.setenv("CDSS_LLM", "falso")
    assert Settings().llm == "falso"
    monkeypatch.setenv("CDSS_LLM", "otro")
    with pytest.raises(ValidationError):
        Settings()
    monkeypatch.setenv("CDSS_LLM", "falso")
    monkeypatch.setattr(srv, "get_settings", lambda: Settings())
    srv._cliente_llm_por_defecto.cache_clear()
    try:
        assert isinstance(srv._cliente_llm_por_defecto(), ClienteFalso)
    finally:
        srv._cliente_llm_por_defecto.cache_clear()


def test_modo_prueba_solo_con_el_cliente_falso(cliente_http, cabeceras, consultas_d2, super_engine, usar_entorno):
    caso = _caso("b")
    id_paciente, id_tamizaje, _ = _ids(super_engine, caso)
    entorno = usar_entorno()
    usar_entorno(cliente=ClienteFalso([APROBADA], modelo="claude-sonnet-5-5"))  # se comporta como uno real
    fin = _consultar(cliente_http, cabeceras, consultas_d2, id_paciente, _cuerpo(caso, id_tamizaje=id_tamizaje))[1][-1]
    assert fin["estado"] == "VERIFICADA" and fin["modo_prueba"] is False
    guardado = cliente_http.get(f"/api/consultas/{fin['id_consulta']}", headers=cabeceras("med.salazar")).json()
    assert guardado["modo_prueba"] is False
    assert entorno is not None


def test_medir_consulta_con_llm_real_nunca_usa_el_cliente_falso(monkeypatch):
    from app.core.config import Settings
    from app.scripts import medir_consulta, prueba_punta_a_punta

    class ClienteRealSimulado:
        pass
    monkeypatch.setenv("CDSS_ENTORNO", "desarrollo")
    monkeypatch.setenv("CDSS_LLM", "falso")
    monkeypatch.setattr(srv, "get_settings", lambda: Settings())
    monkeypatch.setattr(prueba_punta_a_punta, "ClienteAnthropic", ClienteRealSimulado)
    assert isinstance(medir_consulta.cliente_de_corrida(_caso("a"), "real"), ClienteRealSimulado)
    assert isinstance(medir_consulta.cliente_de_corrida(_caso("a"), "falso"), ClienteFalso)
    monkeypatch.setattr(prueba_punta_a_punta, "ClienteAnthropic", lambda: ClienteFalso())
    with pytest.raises(RuntimeError, match="no puede usar el cliente falso"):
        medir_consulta.cliente_de_corrida(_caso("a"), "real")
