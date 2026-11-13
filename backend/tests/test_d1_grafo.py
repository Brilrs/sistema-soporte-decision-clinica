"""Parte D1 contra PostgreSQL, con modelos falsos, ChromaDB en memoria y el cliente falso
del modelo de lenguaje (nunca la API real): el grafo de la consulta y el servicio de
consultas. Cada estado final, el rol de base de datos de cada nodo, que cdss_generacion no
lea la identidad ni el texto libre, que el estado del grafo, los eventos y los registros no
lleven identificadores ni huellas, la persistencia (20 candidatos, tiempos, consulta
previa), la concurrencia con el evento «en_cola», el calentamiento sin API y la migración 010."""
import asyncio
import dataclasses
import json
import logging
import re
import time
from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import event, text
from sqlalchemy.exc import DBAPIError

from app.core.modelos import EmbedderFalso, RerankerFalso
from app.core.seguridad import hmac_identificador
from app.rag import grafo as g
from app.rag.bm25 import CacheBM25
from app.rag.cliente_llm import APROBADA, CITA_INVENTADA, EVIDENCIA_INSUFICIENTE, TIEMPO_AGOTADO, ClienteFalso
from app.rag.dominio import FiltroDominio
from app.rag.filtro_texto import HuellasPaciente, IdentidadPaciente, generar_huellas
from app.rag.recuperacion import Servicios
from app.rag.verificacion import MENSAJE_EVIDENCIA_INSUFICIENTE, MENSAJE_NO_EVALUADA
from app.scripts import prueba_punta_a_punta as e2e
from app.services import consultas as srv
from tests.test_generacion_bd import consultas, engine_clinica, engine_generacion, guia  # noqa: F401 (fixtures)

MIGRACION_010 = Path(__file__).resolve().parents[2] / "db" / "migraciones" / "010_grafo_consulta.sql"
MATEO = IdentidadPaciente("Mateo Quispe Huamán", "81234567", "00452")
TEXTOS_DE_IDENTIDAD = ("Mateo", "Quispe", "Huamán", "81234567", "00452", "987654321")
TIEMPOS_INTENTO = {"recuperacion", "proteccion", "llamada_modelo", "verificacion", "espera_modelos", "espera_llm"}


# ---------------------------------------------------------------------------
# Entorno y utilidades
# ---------------------------------------------------------------------------
@pytest.fixture
def entorno(engine_clinica, engine_generacion, guia):  # noqa: F811
    servicios = Servicios(EmbedderFalso(), RerankerFalso(), guia["almacen"], CacheBM25())
    fecha, _ = e2e.cargar_casos()
    with engine_generacion.connect() as c:
        from app.rag.parametros import parametros_recuperacion
        parametros = replace(parametros_recuperacion(c), umbral_relevancia=0.05, fragmentos_enviados=6)
    return srv.EntornoConsulta(engine_clinica, engine_generacion, servicios, FiltroDominio(EmbedderFalso()),
                               ClienteFalso([APROBADA]), g.Limites(1, 4), parametros, fecha)


def _caso(id_caso: str) -> dict:
    return next(c for c in e2e.cargar_casos()[1] if c["id"] == id_caso)


def _ids(super_engine, caso: dict) -> tuple[str, str, str]:
    """(id_paciente, id_tamizaje, id_usuario) del caso, con la conexión de administración."""
    with super_engine.connect() as c:
        fila = c.execute(text(
            """SELECT t.id_paciente::text, t.id_tamizaje::text FROM clinico.tamizaje t
                 JOIN clinico.paciente_identidad i ON i.id_paciente = t.id_paciente
                WHERE i.dni_hash = :h AND t.fecha_tamizaje = :f"""),
            {"h": hmac_identificador(caso["dni"]), "f": caso["fecha_tamizaje"]}).one()
        usuario = c.execute(text("SELECT id_usuario::text FROM seguridad.usuario WHERE nombre_usuario = :u"),
                            {"u": e2e.USUARIO}).scalar_one()
    return fila[0], fila[1], usuario


def _solicitud(super_engine, caso: dict, **cambios) -> srv.SolicitudConsulta:
    id_paciente, id_tamizaje, id_usuario = _ids(super_engine, caso)
    datos = dict(id_paciente=id_paciente, id_usuario=id_usuario, texto_consulta=caso["consulta"],
                 id_tamizaje=id_tamizaje, confirma_tamizaje_no_vigente=bool(caso.get("confirma_tamizaje_no_vigente")))
    datos.update(cambios)
    return srv.SolicitudConsulta(**datos)


def _ejecutar(entorno, consultas, solicitud, modos=None, preferir_ingles=False) -> list[dict]:  # noqa: F811
    entorno = replace(entorno, cliente=ClienteFalso(modos or [APROBADA], preferir_ingles=preferir_ingles))
    eventos = asyncio.run(srv.eventos_de(solicitud, entorno))
    fin = eventos[-1]
    if fin.get("id_consulta"):
        consultas.append(fin["id_consulta"])
    fin["_cliente"] = entorno.cliente
    return eventos


def _caso_e2e(entorno, consultas, super_engine, id_caso: str, **cambios) -> list[dict]:  # noqa: F811
    caso = _caso(id_caso)
    falso = caso.get("falso") or {}
    return _ejecutar(entorno, consultas, _solicitud(super_engine, caso, **cambios), falso.get("modos"),
                     bool(falso.get("preferir_ingles")))


def _consulta(super_engine, id_consulta: str):
    with super_engine.connect() as c:
        return c.execute(text(
            """SELECT estado, numero_intentos, latencia_total_ms, tiempos_ms, id_consulta_previa::text AS previa,
                      texto_filtrado, confirma_tamizaje_no_vigente
                 FROM asistencia.consulta WHERE id_consulta = CAST(:c AS uuid)"""), {"c": id_consulta}).one()


def _intentos(super_engine, id_consulta: str):
    with super_engine.connect() as c:
        return c.execute(text(
            """SELECT id_intento::text, numero_intento, tipo_busqueda, resultado, control_identificadores, tiempos_ms
                 FROM asistencia.intento_generacion WHERE id_consulta = CAST(:c AS uuid) ORDER BY numero_intento"""),
            {"c": id_consulta}).all()


def _contexto(entorno, texto: str, eventos: list) -> g.Contexto:
    return g.Contexto(entorno.clinica, entorno.generacion, entorno.servicios, entorno.dominio, entorno.cliente,
                      entorno.limites, eventos.append, time.perf_counter(), parametros=entorno.parametros,
                      fecha_referencia=entorno.fecha_referencia, texto_consulta=texto)


def _entrada(solicitud: srv.SolicitudConsulta) -> dict:
    return {"id_tamizaje": solicitud.id_tamizaje, "id_paciente": solicitud.id_paciente,
            "id_usuario": solicitud.id_usuario, "confirma_tamizaje_no_vigente": solicitud.confirma_tamizaje_no_vigente,
            "id_consulta_previa": solicitud.id_consulta_previa}


def _volcar(valor, tipos: set) -> str:
    """JSON de cualquier valor del estado (dataclasses incluidas); anota los tipos vistos."""
    def defecto(o):
        tipos.add(type(o))
        if dataclasses.is_dataclass(o):
            return {f.name: getattr(o, f.name) for f in dataclasses.fields(o)}
        if isinstance(o, (set, frozenset)):
            return sorted(o, key=str)
        if isinstance(o, (Decimal, date)):
            return str(o)
        return repr(o)
    return json.dumps(valor, default=defecto, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Estados finales
# ---------------------------------------------------------------------------
def test_los_doce_casos_de_punta_a_punta_por_el_grafo(entorno, consultas, super_engine):  # noqa: F811
    for caso in e2e.cargar_casos()[1]:
        eventos = _caso_e2e(entorno, consultas, super_engine, caso["id"])
        fin = eventos[-1]
        assert fin["tipo"] == "fin" and fin["estado"] == caso["esperado"], (caso["id"], fin)
        fila = _consulta(super_engine, fin["id_consulta"])
        assert fila.estado == caso["esperado"] and fila.latencia_total_ms is not None
        etapas = [e["etapa"] for e in eventos if e["tipo"] == "etapa"]
        assert etapas[0] == "validar" and etapas[-1] == "salida"
        # Tiempos de la consulta: por nodo, total y hasta el primer evento.
        t = fila.tiempos_ms
        assert set(t) == {"total_ms", "primer_evento_ms", "por_nodo", "etapas", "espera_ms"}
        assert set(t["por_nodo"]) == set(etapas) - {"salida"} and t["primer_evento_ms"] <= t["total_ms"]
        assert fin["tiempos_ms"]["total_ms"] == t["total_ms"]
        for i in _intentos(super_engine, fin["id_consulta"]):
            assert set(i.tiempos_ms) == TIEMPOS_INTENTO
        if caso["esperado"] == "VERIFICADA":
            assert etapas[:8] == list(g.NODOS) and fin["recomendacion"] and fin["citas"]
            assert fila.numero_intentos == len(_intentos(super_engine, fin["id_consulta"])) >= 1
    # g: DATOS_FALTANTES y h: FUERA_DE_DOMINIO terminan en validar, sin intentos.


def test_datos_faltantes_y_fuera_de_dominio_terminan_en_validar(entorno, consultas, super_engine):  # noqa: F811
    for id_caso, estado in (("g", "DATOS_FALTANTES"), ("h", "FUERA_DE_DOMINIO")):
        eventos = _caso_e2e(entorno, consultas, super_engine, id_caso)
        assert [e["etapa"] for e in eventos if e["tipo"] == "etapa"] == ["validar", "salida"]
        fin = eventos[-1]
        assert fin["estado"] == estado and fin["numero_intentos"] == 0 and fin["intentos"] == []
        assert not fin["_cliente"].llamadas and fin["verificacion"] is None and fin["modo_prueba"] is False
        assert not _intentos(super_engine, fin["id_consulta"])
    assert fin["mensaje"] == g.MENSAJE_FUERA_DE_DOMINIO


def test_tamizaje_no_vigente_y_consulta_nueva_que_confirma(entorno, consultas, super_engine):  # noqa: F811
    eventos = _caso_e2e(entorno, consultas, super_engine, "f", confirma_tamizaje_no_vigente=False)
    fin = eventos[-1]
    assert fin["estado"] == "TAMIZAJE_NO_VIGENTE" and fin["vigencia"]["dias_transcurridos"] == 84
    assert _consulta(super_engine, fin["id_consulta"]).estado == "TAMIZAJE_NO_VIGENTE"
    assert not _intentos(super_engine, fin["id_consulta"])
    previa = fin["id_consulta"]
    eventos = _caso_e2e(entorno, consultas, super_engine, "f", confirma_tamizaje_no_vigente=True,
                        id_consulta_previa=previa)
    fila = _consulta(super_engine, eventos[-1]["id_consulta"])
    assert (eventos[-1]["estado"], fila.previa, fila.confirma_tamizaje_no_vigente) == ("VERIFICADA", previa, True)


def test_consulta_previa_invalida_se_rechaza(entorno, consultas, super_engine):  # noqa: F811
    verificada = _caso_e2e(entorno, consultas, super_engine, "b")[-1]["id_consulta"]
    with pytest.raises(srv.ErrorSolicitud):
        _caso_e2e(entorno, consultas, super_engine, "b", id_consulta_previa=verificada)


@pytest.mark.parametrize("modos, estado, resultados, mensaje", [
    ([CITA_INVENTADA, APROBADA], "VERIFICADA", ["REINTENTO", "APROBADO"], None),
    ([CITA_INVENTADA, CITA_INVENTADA], "EVIDENCIA_INSUFICIENTE", ["REINTENTO", "EVIDENCIA_INSUFICIENTE"],
     MENSAJE_EVIDENCIA_INSUFICIENTE),
    ([EVIDENCIA_INSUFICIENTE, APROBADA], "VERIFICADA", ["REINTENTO", "APROBADO"], None),
    ([TIEMPO_AGOTADO], "ERROR", ["ERROR"], MENSAJE_NO_EVALUADA),
])
def test_un_solo_reintento_segun_la_tabla_10(entorno, consultas, super_engine, modos, estado, resultados,  # noqa: F811
                                             mensaje):
    eventos = _ejecutar(entorno, consultas, _solicitud(super_engine, _caso("b")), modos)
    fin = eventos[-1]
    assert (fin["estado"], fin["mensaje"]) == (estado, mensaje)
    intentos = _intentos(super_engine, fin["id_consulta"])
    assert [i.resultado for i in intentos] == resultados and len(fin["_cliente"].llamadas) == len(resultados)
    etapas = [e["etapa"] for e in eventos if e["tipo"] == "etapa"]
    if modos[0] == EVIDENCIA_INSUFICIENTE:
        # 6.3 en el primer intento: vuelve a recuperar con la búsqueda ampliada.
        assert [i.tipo_busqueda for i in intentos] == ["INICIAL", "AMPLIADA"] and etapas.count("recuperar") == 2
    elif len(intentos) == 2:
        # 6.1 en el primer intento: regenera con la misma recuperación.
        assert [i.tipo_busqueda for i in intentos] == ["INICIAL", "INICIAL"] and etapas.count("recuperar") == 1
        assert etapas.count("proteger") == 2


def test_sin_fragmentos_sobre_el_umbral_pasa_de_recuperar_a_verificar(entorno, consultas, super_engine):  # noqa: F811
    entorno = replace(entorno, parametros=replace(entorno.parametros, umbral_relevancia=0.99))
    eventos = _ejecutar(entorno, consultas, _solicitud(super_engine, _caso("b")))
    fin = eventos[-1]
    assert fin["estado"] == "EVIDENCIA_INSUFICIENTE" and not fin["_cliente"].llamadas
    assert [e["etapa"] for e in eventos if e["tipo"] == "etapa"] == [
        "validar", "clasificar", "normalizar", "recuperar", "verificar", "recuperar", "verificar", "salida"]


def test_solicitud_bloqueada_es_un_estado_final_propio(entorno, consultas, super_engine, monkeypatch):  # noqa: F811
    # Huellas de un «paciente» cuyo apellido aparece en la guía de prueba («ferroso»).
    monkeypatch.setattr(g, "generar_huellas", lambda _: generar_huellas(IdentidadPaciente("Ana Ferroso", "1", "2")))
    eventos = _ejecutar(entorno, consultas, _solicitud(super_engine, _caso("b")))
    fin = eventos[-1]
    assert (fin["estado"], fin["mensaje"]) == ("SOLICITUD_BLOQUEADA", g.MENSAJE_BLOQUEADA)
    assert not fin["_cliente"].llamadas
    assert [e["etapa"] for e in eventos if e["tipo"] == "etapa"][-2:] == ["proteger", "salida"]
    (i,) = _intentos(super_engine, fin["id_consulta"])
    assert (i.resultado, i.control_identificadores) == ("ERROR", False)
    assert _consulta(super_engine, fin["id_consulta"]).estado == "SOLICITUD_BLOQUEADA"


def test_un_error_inesperado_cierra_la_consulta_en_error_sin_registrar_datos(entorno, consultas, super_engine,  # noqa: F811
                                                                            monkeypatch, caplog):
    def falla(*_):
        raise RuntimeError("detalle con 81234567 y Mateo")
    monkeypatch.setattr(g, "recuperar_fragmentos", falla)
    with caplog.at_level(logging.DEBUG):
        eventos = _ejecutar(entorno, consultas, _solicitud(super_engine, _caso("b")))
    fin = eventos[-1]
    assert (fin["tipo"], fin["estado"], fin["mensaje"]) == ("error", "ERROR", MENSAJE_NO_EVALUADA)
    assert _consulta(super_engine, fin["id_consulta"]).estado == "ERROR"
    assert "81234567" not in caplog.text and "Mateo" not in caplog.text and "RuntimeError" in caplog.text


def test_el_tamizaje_de_otro_paciente_se_rechaza_sin_crear_la_consulta(entorno, consultas, super_engine):  # noqa: F811
    otro, _, _ = _ids(super_engine, _caso("a"))
    solicitud = _solicitud(super_engine, _caso("b"), id_paciente=otro)
    with super_engine.connect() as c:
        antes = c.execute(text("SELECT count(*) FROM asistencia.consulta")).scalar_one()
    with pytest.raises(srv.ErrorSolicitud, match="no pertenece"):
        _ejecutar(entorno, consultas, solicitud)
    with super_engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM asistencia.consulta")).scalar_one() == antes


def test_sin_id_tamizaje_usa_el_mas_reciente_del_paciente(entorno, consultas, super_engine):  # noqa: F811
    eventos = _ejecutar(entorno, consultas, _solicitud(super_engine, _caso("b"), id_tamizaje=None))
    assert eventos[-1]["estado"] == "VERIFICADA"


# ---------------------------------------------------------------------------
# Roles por nodo y lo que lee cdss_generacion
# ---------------------------------------------------------------------------
def test_cada_nodo_usa_su_rol_y_generacion_no_toca_identidad(entorno, consultas, super_engine):  # noqa: F811
    sentencias: list[str] = []

    def anotar(conn, cursor, sentencia, parametros, contexto, varios):
        sentencias.append(sentencia)
    event.listen(entorno.generacion, "before_cursor_execute", anotar)
    try:
        solicitud = _solicitud(super_engine, _caso("i"))
        eventos: list = []
        ctx = _contexto(replace(entorno, cliente=ClienteFalso([CITA_INVENTADA, APROBADA])), solicitud.texto_consulta,
                        eventos)
        final = g.ejecutar_grafo(_entrada(solicitud), ctx)
        consultas.append(final["id_consulta"])
    finally:
        event.remove(entorno.generacion, "before_cursor_execute", anotar)
    assert final["estado_final"] == "VERIFICADA"
    assert {nodo for nodo, _ in ctx.sesiones} == set(g.NODOS)
    for nodo, rol in ctx.sesiones:
        assert rol == g.ROL_POR_NODO[nodo], (nodo, rol)
    todo = " ".join(sentencias).lower()
    assert sentencias and "paciente_identidad" not in todo and "texto_consulta" not in todo
    assert "observaciones" not in todo and "clinico.distrito" not in todo and "pgp_sym_decrypt" not in todo


def test_cdss_generacion_no_puede_leer_la_identidad(engine_generacion):  # noqa: F811
    for consulta in ("SELECT dni_cifrado FROM clinico.paciente_identidad LIMIT 1",
                     "SELECT texto_consulta FROM asistencia.consulta LIMIT 1",
                     "SELECT observaciones FROM clinico.tamizaje LIMIT 1",
                     "SELECT altitud_msnm FROM clinico.distrito LIMIT 1"):
        with pytest.raises(DBAPIError), engine_generacion.connect() as c:
            c.execute(text(consulta))


# ---------------------------------------------------------------------------
# Identidad fuera del estado, de los eventos y de los registros; huellas solo como digests
# ---------------------------------------------------------------------------
def test_el_estado_del_grafo_y_los_eventos_no_llevan_identificadores(entorno, consultas, super_engine,  # noqa: F811
                                                                    caplog):
    solicitud = _solicitud(super_engine, _caso("i"))
    huellas = generar_huellas(MATEO)
    eventos: list = []
    ctx = _contexto(entorno, solicitud.texto_consulta, eventos)
    tipos: set = set()
    with caplog.at_level(logging.DEBUG):
        estados = list(g.grafo().stream(_entrada(solicitud), context=ctx, stream_mode="values"))
    consultas.append(estados[-1]["id_consulta"])
    assert estados[-1]["estado_final"] == "VERIFICADA"
    volcado = " ".join(_volcar(e, tipos) for e in estados) + _volcar(eventos, tipos) + caplog.text
    for dato in TEXTOS_DE_IDENTIDAD:
        assert dato not in volcado, dato
    assert not any(h in volcado for h in huellas.valores)
    assert HuellasPaciente not in tipos and IdentidadPaciente not in tipos
    assert "[PACIENTE]" in estados[-1]["texto_filtrado"]
    # El texto original solo vive en el contexto hasta que validar lo usa.
    assert ctx.texto_consulta is None


def test_proteger_recibe_solo_los_digests_de_las_huellas(entorno, consultas, super_engine, monkeypatch):  # noqa: F811
    solicitud = _solicitud(super_engine, _caso("i"))
    eventos: list = []
    ctx = _contexto(entorno, solicitud.texto_consulta, eventos)
    vistos: list = []
    original = g.controlar_identificadores

    def espia(serializada, huellas):
        vistos.append((huellas, ctx.texto_consulta, ctx.nodo_actual))
        return original(serializada, huellas)
    monkeypatch.setattr(g, "controlar_identificadores", espia)
    final = g.ejecutar_grafo(_entrada(solicitud), ctx)
    consultas.append(final["id_consulta"])
    ((huellas, texto_original, nodo),) = vistos
    assert nodo == "proteger" and texto_original is None and isinstance(huellas, HuellasPaciente)
    assert huellas.valores == generar_huellas(MATEO).valores
    assert all(re.fullmatch(r"[0-9a-f]{64}", h) for h in huellas.valores)
    assert not ({"mateo", "quispe", "huaman", "81234567", "00452"} & set(huellas.valores))
    assert "huellas" not in final and "HuellasPaciente" not in repr(ctx) and "<protegida>" not in repr(final)
    # El servicio borra las huellas y el texto original al terminar.
    ctx_servicio = srv.ejecutar_en_hilo(solicitud, solicitud.id_tamizaje, entorno, lambda e: None,
                                        time.perf_counter())
    consultas.append(ctx_servicio.id_consulta)
    assert ctx_servicio.huellas is None and ctx_servicio.texto_consulta is None


# ---------------------------------------------------------------------------
# Persistencia: 20 candidatos de la fusión
# ---------------------------------------------------------------------------
def test_se_guardan_los_candidatos_no_evaluados_con_null(entorno, consultas, super_engine):  # noqa: F811
    entorno = replace(entorno, parametros=replace(entorno.parametros, candidatos_reranker=3, fragmentos_enviados=2))
    fin = _ejecutar(entorno, consultas, _solicitud(super_engine, _caso("b")))[-1]
    (intento,) = _intentos(super_engine, fin["id_consulta"])
    with super_engine.connect() as c:
        filas = c.execute(text(
            """SELECT puntaje_reranker, posicion_final, enviado_al_llm, etiqueta_cita
                 FROM asistencia.fragmento_recuperado WHERE id_intento = CAST(:i AS uuid)
                ORDER BY posicion_rrf"""), {"i": intento.id_intento}).all()
    evaluados = [f for f in filas if f.puntaje_reranker is not None]
    no_evaluados = [f for f in filas if f.puntaje_reranker is None]
    assert len(evaluados) == 3 and len(no_evaluados) == len(filas) - 3 >= 1
    assert all(f.posicion_final is None and not f.enviado_al_llm for f in no_evaluados)
    assert sorted(f.etiqueta_cita for f in filas if f.enviado_al_llm) == ["F-01", "F-02"]


# ---------------------------------------------------------------------------
# Concurrencia y calentamiento
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("configurada, hilos, nucleos, esperado", [
    (None, 4, 8, 2), (None, 2, 2, 1), (None, 4, 2, 1), (3, 4, 8, 3), (None, None, 2, 1),
])
def test_concurrencia_del_reranker_por_defecto(configurada, hilos, nucleos, esperado):
    assert srv.concurrencia_reranker(configurada, hilos, nucleos) == esperado


class _RerankerLento(RerankerFalso):
    def puntuar(self, consulta, textos, max_longitud=None):
        time.sleep(0.4)
        return super().puntuar(consulta, textos, max_longitud)


def test_una_consulta_sin_turno_emite_en_cola_y_cuenta_la_espera(entorno, consultas, super_engine):  # noqa: F811
    servicios = replace(entorno.servicios, reranker=_RerankerLento())
    entorno = replace(entorno, servicios=servicios, limites=g.Limites(1, 4))
    solicitudes = [_solicitud(super_engine, _caso("b")), _solicitud(super_engine, _caso("c"))]

    async def ambas():
        return await asyncio.gather(*(srv.eventos_de(s, replace(entorno, cliente=ClienteFalso([APROBADA])))
                                      for s in solicitudes))
    resultados = asyncio.run(ambas())
    for eventos in resultados:
        consultas.append(eventos[-1]["id_consulta"])
        assert eventos[-1]["estado"] == "VERIFICADA"
    en_cola = [e for eventos in resultados for e in eventos if e["tipo"] == "en_cola"]
    assert en_cola and all(e["recurso"] == g.MODELOS for e in en_cola)
    esperas = [_consulta(super_engine, ev[-1]["id_consulta"]).tiempos_ms["espera_ms"]["modelos"] for ev in resultados]
    assert max(esperas) >= 200


def test_el_calentamiento_no_llama_a_la_api_en_pruebas(entorno, monkeypatch):
    cliente = ClienteFalso([APROBADA])
    entorno = replace(entorno, cliente=cliente)
    tiempos = srv.calentar(entorno, llamar_llm=True)
    assert not cliente.llamadas and {"embedding", "reranker", "bm25", "grafo"} <= set(tiempos)
    monkeypatch.setattr(srv, "entorno_actual", lambda: "desarrollo")
    srv.calentar(entorno, llamar_llm=True)
    assert len(cliente.llamadas) == 1 and cliente.llamadas[0]["solicitud"]["evidencia"] == []
    srv.calentar(entorno, llamar_llm=False)
    assert len(cliente.llamadas) == 1


# ---------------------------------------------------------------------------
# Migración 010
# ---------------------------------------------------------------------------
def test_migracion_010_es_idempotente_y_admite_los_estados_nuevos(super_engine):
    sql = MIGRACION_010.read_text(encoding="utf-8")
    with super_engine.begin() as c:
        c.exec_driver_sql(sql)
        c.exec_driver_sql(sql)
        definicion = c.execute(text("SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                                    "WHERE conname = 'consulta_estado_check'")).scalar_one()
        nulos = dict(c.execute(text(
            """SELECT column_name, is_nullable FROM information_schema.columns
                WHERE table_schema = 'asistencia' AND table_name = 'fragmento_recuperado'
                  AND column_name IN ('puntaje_reranker', 'posicion_final')""")).all())
        tiempos = c.execute(text("SELECT count(*) FROM information_schema.columns WHERE table_schema = 'asistencia' "
                                 "AND column_name = 'tiempos_ms'")).scalar_one()
    assert "TAMIZAJE_NO_VIGENTE" in definicion and "SOLICITUD_BLOQUEADA" in definicion
    assert nulos == {"puntaje_reranker": "YES", "posicion_final": "YES"} and tiempos == 2


def test_percentiles_y_resumen_de_medir_consulta():
    from app.scripts.medir_consulta import percentil, resumen
    assert percentil([], 50) is None
    assert [percentil(list(range(1, 13)), p) for p in (50, 90, 100)] == [6, 11, 12]
    filas = [{"coincide": True, "estado": "VERIFICADA", "total_cliente_ms": 100, "primer_evento_ms": 10,
              "tiempos_ms": {"por_nodo": {"validar": 5}, "espera_ms": {"modelos": 30, "llm": 0}},
              "intentos": [{"modelo_llm": "m", "costo_usd": 0.01, "tokens_entrada": 5, "tokens_salida": 2}]},
             {"coincide": False, "estado": "ERROR", "total_cliente_ms": 50, "primer_evento_ms": 20,
              "tiempos_ms": None, "intentos": []}]
    r = resumen(filas)
    assert (r["consultas"], r["coinciden"], r["intentos_enviados"], r["espera_cola_ms_max"]) == (2, 1, 1, 30)
    assert r["total_verificadas_ms"]["p50"] == 100 and r["por_nodo_p50_ms"] == {"validar": 5}


def test_limite_provisional_hasta_que_modelos_informa_sus_hilos(monkeypatch):
    class Salud:
        respuestas: list = [ConnectionError("sin modelos"), {"hilos": 4}]

        def salud(self):
            r = self.respuestas.pop(0)
            if isinstance(r, Exception):
                raise r
            return r
    monkeypatch.setattr(srv, "_modelos_por_defecto", lambda: (Salud(), None, None))
    monkeypatch.setattr(srv, "nucleos_visibles", lambda: 8)
    monkeypatch.setattr(srv, "_limites", None)
    monkeypatch.setattr(srv, "_limites_definitivos", False)
    provisional = srv.limites_por_defecto()
    assert (provisional.reranker, provisional.llm) == (1, 4)
    definitivo = srv.limites_por_defecto()
    assert definitivo.reranker == 2 and srv.limites_por_defecto() is definitivo


def test_el_calentamiento_reintenta_hasta_que_los_servicios_responden(monkeypatch):
    from app import main
    llamadas = []

    def calentar():
        llamadas.append(1)
        if len(llamadas) < 3:
            raise ConnectionError("modelos todavía arrancando")
        return {"embedding": 1}
    monkeypatch.setattr(srv, "calentar", calentar)
    assert asyncio.run(main.calentar_con_reintentos(reintentos=5, pausa_s=0)) == {"embedding": 1}
    assert len(llamadas) == 3
    llamadas.clear()
    monkeypatch.setattr(srv, "calentar", lambda: (_ for _ in ()).throw(ConnectionError()))
    assert asyncio.run(main.calentar_con_reintentos(reintentos=2, pausa_s=0)) is None


def test_sin_clave_de_la_api_el_cliente_no_disponible_lleva_a_error(entorno, consultas, super_engine):  # noqa: F811
    cliente = srv.ClienteNoDisponible("Falta ANTHROPIC_API_KEY")
    eventos = asyncio.run(srv.eventos_de(_solicitud(super_engine, _caso("b")), replace(entorno, cliente=cliente)))
    consultas.append(eventos[-1]["id_consulta"])
    assert (eventos[-1]["estado"], eventos[-1]["mensaje"]) == ("ERROR", MENSAJE_NO_EVALUADA)


@pytest.mark.parametrize("valor, esperado", [("", None), ("  ", None), ("3", 3)])
def test_max_concurrencia_reranker_vacia_es_automatica(monkeypatch, valor, esperado):
    from app.core.config import Settings
    monkeypatch.setenv("MAX_CONCURRENCIA_RERANKER", valor)
    assert Settings().max_concurrencia_reranker == esperado
