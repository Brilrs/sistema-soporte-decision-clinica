"""Sprint 3, parte B: GET /api/consultas («Historial de consultas», P10) y el nombre de quien
registró la decisión en el resultado de la consulta (P12).

Sin el grafo ni el modelo de lenguaje: cada prueba crea un paciente ficticio (sexo y fechas
explícitos) e inserta sus consultas con la conexión de administración en días de marzo de 2031,
una ventana que ninguna otra prueba usa, así los filtros de fecha aíslan sus datos. Al terminar se
borran las consultas y luego el paciente."""
import logging
import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from app.core.fechas import edad_en_meses, hoy
from app.rag.cliente_llm import MODELO_FALSO
from app.services.resultados import LARGO_PREGUNTA, recortar_pregunta
from tests.test_pacientes import _registrar

UTC = timezone.utc
LIMA = timezone(timedelta(hours=-5))  # Perú no usa horario de verano
DIA = date(2031, 3, 10)
VENTANA = {"fecha_desde": "2031-03-01", "fecha_hasta": "2031-03-31"}
TEXTO_ORIGINAL = "TEXTO ORIGINAL QUE NO DEBE SALIR"
USUARIOS = ("enf.rojas", "med.salazar", "nut.vilca")


@pytest.fixture
def paciente_b(cliente, cabeceras, pacientes_creados, super_engine):
    """Paciente ficticio con sexo y fecha de nacimiento explícitos y su tamizaje."""
    datos, creado = _registrar(cliente, cabeceras, pacientes_creados, sexo="F",
                               fecha_nacimiento=str(hoy() - timedelta(days=430)))
    with super_engine.connect() as c:
        id_tamizaje = c.execute(text("SELECT id_tamizaje::text FROM clinico.tamizaje WHERE id_paciente = CAST(:p AS uuid)"),
                                {"p": creado["id_paciente"]}).scalar_one()
    return {**datos, "id_paciente": creado["id_paciente"], "id_tamizaje": id_tamizaje}


@pytest.fixture
def consultas_b(super_engine, paciente_b):
    """Inserta consultas y las borra al final (antes que el paciente: depende de paciente_b)."""
    creadas: list[str] = []

    def insertar(usuario: str, inicio: datetime, *, estado: str = "VERIFICADA", prueba: bool = False,
                 texto_filtrado: str | None = "¿Qué dosis de hierro le corresponde a [PACIENTE]?",
                 id_consulta: str | None = None) -> str:
        id_consulta = id_consulta or str(uuid.uuid4())
        with super_engine.begin() as c:
            c.execute(text(
                """INSERT INTO asistencia.consulta (id_consulta, id_tamizaje, id_usuario, texto_consulta, texto_filtrado,
                                                     estado, numero_intentos, fecha_hora_inicio)
                   SELECT CAST(:c AS uuid), CAST(:t AS uuid), u.id_usuario, :original, :filtrado, :estado, :n, :inicio
                     FROM seguridad.usuario u WHERE u.nombre_usuario = :usuario"""),
                {"c": id_consulta, "t": paciente_b["id_tamizaje"], "original": TEXTO_ORIGINAL, "filtrado": texto_filtrado,
                 "estado": estado, "n": 1 if prueba else 0, "inicio": inicio, "usuario": usuario})
            if prueba:
                c.execute(text(
                    """INSERT INTO asistencia.intento_generacion (id_consulta, numero_intento, tipo_busqueda,
                           consulta_reformulada, candidatos_evaluados, umbral_relevancia, resultado, modelo_llm)
                       VALUES (CAST(:c AS uuid), 1, 'INICIAL', 'consulta de prueba', 0, 0.15, 'APROBADO', :m)"""),
                    {"c": id_consulta, "m": MODELO_FALSO})
        creadas.append(id_consulta)
        return id_consulta

    yield insertar
    if creadas:
        with super_engine.begin() as c:
            p = {"ids": creadas}
            c.execute(text("DELETE FROM asistencia.intento_generacion WHERE id_consulta::text = ANY(:ids)"), p)
            c.execute(text("DELETE FROM asistencia.decision_clinica WHERE id_consulta::text = ANY(:ids)"), p)
            c.execute(text("DELETE FROM asistencia.consulta WHERE id_consulta::text = ANY(:ids)"), p)


def _momento(dia: date, hora: int, minuto: int = 0, segundo: int = 0) -> datetime:
    """Hora de Lima (como la ve el profesional)."""
    return datetime(dia.year, dia.month, dia.day, hora, minuto, segundo, tzinfo=LIMA)


def _listar(cliente, cabeceras, usuario: str, **parametros):
    return cliente.get("/api/consultas", params={**VENTANA, **parametros}, headers=cabeceras(usuario))


def _ids(respuesta) -> list[str]:
    assert respuesta.status_code == 200, respuesta.text
    return [c["id_consulta"] for c in respuesta.json()["consultas"]]


def _duenos(super_engine, ids: list[str]) -> set[str]:
    with super_engine.connect() as c:
        return set(c.execute(text(
            """SELECT u.nombre_usuario FROM asistencia.consulta q JOIN seguridad.usuario u ON u.id_usuario = q.id_usuario
                WHERE q.id_consulta::text = ANY(:ids)"""), {"ids": ids}).scalars())


# ---------------------------------------------------------------------------
# Solo las consultas propias
# ---------------------------------------------------------------------------
def test_cada_usuario_ve_solo_sus_consultas(cliente, cabeceras, consultas_b, super_engine):
    propias = {u: {consultas_b(u, _momento(DIA, 9 + i, k)) for k in range(2)} for i, u in enumerate(USUARIOS)}
    for usuario in USUARIOS:
        r = _listar(cliente, cabeceras, usuario)
        assert set(_ids(r)) == propias[usuario], usuario
        assert r.json()["total"] == 2
    # Sin filtros de fecha (todas sus consultas, en páginas de 100), ninguna es de otro usuario.
    for usuario in USUARIOS:
        vistos, desplazamiento = [], 0
        while True:
            pagina = cliente.get("/api/consultas", params={"limite": 100, "desplazamiento": desplazamiento},
                                 headers=cabeceras(usuario)).json()
            vistos += [c["id_consulta"] for c in pagina["consultas"]]
            desplazamiento += 100
            if desplazamiento >= pagina["total"]:
                break
        assert len(vistos) == pagina["total"] and propias[usuario] <= set(vistos)
        assert _duenos(super_engine, vistos) == {usuario}


def test_no_hay_parametro_para_pedir_las_de_otro(cliente, cabeceras, consultas_b, super_engine):
    ajena = consultas_b("enf.rojas", _momento(DIA, 10))
    with super_engine.connect() as c:
        id_rojas = c.execute(text("SELECT id_usuario::text FROM seguridad.usuario WHERE nombre_usuario = 'enf.rojas'")).scalar()
    for extra in ({"id_usuario": id_rojas}, {"usuario": "enf.rojas"}):
        r = cliente.get("/api/consultas", params={**VENTANA, **extra}, headers=cabeceras("med.salazar"))
        assert ajena not in _ids(r)


def test_sin_permiso_403_y_sin_sesion_401(cliente, cabeceras):
    # El Administrador no tiene REALIZAR_CONSULTA; sin token, el proyecto responde 401 en todas las rutas.
    assert cliente.get("/api/consultas", headers=cabeceras("admin.cdss")).status_code == 403
    assert cliente.get("/api/consultas").status_code == 401


# ---------------------------------------------------------------------------
# Contenido de cada elemento
# ---------------------------------------------------------------------------
def test_elemento_con_paciente_edad_clasificacion_y_pregunta_recortada(cliente, cabeceras, consultas_b, paciente_b):
    larga = "¿" + " ".join(["Cuánto hierro necesita [PACIENTE] según su edad y su hemoglobina"] * 4) + "?"
    id_c = consultas_b("med.salazar", _momento(DIA, 11), texto_filtrado=larga)
    r = _listar(cliente, cabeceras, "med.salazar")
    c = next(x for x in r.json()["consultas"] if x["id_consulta"] == id_c)
    assert c["id_paciente"] == paciente_b["id_paciente"]
    assert (c["nombres_apellidos"], c["numero_hc"]) == (paciente_b["nombres_apellidos"], paciente_b["numero_hc"])
    nacimiento = date.fromisoformat(paciente_b["fecha_nacimiento"])
    assert c["edad_meses"] == edad_en_meses(nacimiento, DIA)
    assert c["estado"] == "VERIFICADA" and c["categoria"] == "ANEMIA_LEVE" and c["nivel_riesgo"] == "MODERADO"
    assert c["modo_prueba"] is False
    assert c["pregunta"].endswith("…") and len(c["pregunta"]) <= LARGO_PREGUNTA + 1 and larga.startswith(c["pregunta"][:-1])
    assert set(c) == {"id_consulta", "id_paciente", "nombres_apellidos", "numero_hc", "edad_meses", "estado", "categoria",
                      "nivel_riesgo", "fecha_hora_inicio", "modo_prueba", "pregunta"}
    # Ningún dato personal que M02 no muestre: ni DNI, ni dirección, ni el texto original.
    for dato in (paciente_b["dni"], paciente_b["direccion"], TEXTO_ORIGINAL):
        assert dato not in r.text


def test_recortar_pregunta():
    assert recortar_pregunta(None) is None
    assert recortar_pregunta("  ¿Dosis   de\nhierro?  ") == "¿Dosis de hierro?"
    exacta = "a" * LARGO_PREGUNTA
    assert recortar_pregunta(exacta) == exacta
    assert recortar_pregunta("palabra " * 30) == ("palabra " * 12).rstrip() + "…"
    assert recortar_pregunta("x" * 150) == "x" * LARGO_PREGUNTA + "…"


def test_consulta_de_prueba_marcada_y_no_oculta(cliente, cabeceras, consultas_b):
    real = consultas_b("med.salazar", _momento(DIA, 8))
    prueba = consultas_b("med.salazar", _momento(DIA, 9), prueba=True)
    marcas = {c["id_consulta"]: c["modo_prueba"] for c in _listar(cliente, cabeceras, "med.salazar").json()["consultas"]}
    assert marcas == {real: False, prueba: True}


# ---------------------------------------------------------------------------
# Filtros
# ---------------------------------------------------------------------------
def test_filtro_por_estado(cliente, cabeceras, consultas_b):
    verificada = consultas_b("med.salazar", _momento(DIA, 8))
    insuficiente = consultas_b("med.salazar", _momento(DIA, 9), estado="EVIDENCIA_INSUFICIENTE")
    en_proceso = consultas_b("med.salazar", _momento(DIA, 10), estado="EN_PROCESO")
    assert _ids(_listar(cliente, cabeceras, "med.salazar", estado="VERIFICADA")) == [verificada]
    assert _ids(_listar(cliente, cabeceras, "med.salazar", estado="EVIDENCIA_INSUFICIENTE")) == [insuficiente]
    assert _ids(_listar(cliente, cabeceras, "med.salazar", estado="EN_PROCESO")) == [en_proceso]
    assert _ids(_listar(cliente, cabeceras, "med.salazar", estado="ERROR")) == []


def test_fechas_son_dias_de_lima_inclusivos(cliente, cabeceras, consultas_b):
    # 23:59:59 del 9 en Lima son las 04:59:59 del 10 en UTC; 00:00 del 10 en Lima, las 05:00 UTC.
    ultimo_del_9 = consultas_b("med.salazar", datetime(2031, 3, 10, 4, 59, 59, tzinfo=UTC))
    primero_del_10 = consultas_b("med.salazar", datetime(2031, 3, 10, 5, 0, 0, tzinfo=UTC))
    ultimo_del_10 = consultas_b("med.salazar", _momento(DIA, 23, 59, 59))
    primero_del_11 = consultas_b("med.salazar", _momento(date(2031, 3, 11), 0))
    assert _ids(_listar(cliente, cabeceras, "med.salazar", fecha_desde="2031-03-10", fecha_hasta="2031-03-10")) == [
        ultimo_del_10, primero_del_10]
    assert _ids(_listar(cliente, cabeceras, "med.salazar", fecha_desde="2031-03-01", fecha_hasta="2031-03-09")) == [
        ultimo_del_9]
    assert _ids(_listar(cliente, cabeceras, "med.salazar", fecha_desde="2031-03-11", fecha_hasta="2031-03-31")) == [
        primero_del_11]
    # Solo uno de los dos extremos.
    solo_desde = _ids(cliente.get("/api/consultas", params={"fecha_desde": "2031-03-11"}, headers=cabeceras("med.salazar")))
    assert primero_del_11 in solo_desde and ultimo_del_10 not in solo_desde
    solo_hasta = _ids(cliente.get("/api/consultas", params={"fecha_hasta": "2031-03-09", "limite": 100},
                                  headers=cabeceras("med.salazar")))
    assert ultimo_del_9 in solo_hasta and primero_del_10 not in solo_hasta


@pytest.mark.parametrize("parametros, campo", [
    ({"estado": "TERMINADA"}, "estado"),
    ({"fecha_desde": "2031-13-01"}, "fecha_desde"),
    ({"fecha_hasta": "ayer"}, "fecha_hasta"),
    ({"fecha_desde": "2031-03-10", "fecha_hasta": "2031-03-09"}, "fecha_hasta"),
    ({"limite": 0}, "limite"),
    ({"limite": 101}, "limite"),
    ({"limite": "veinte"}, "limite"),
    ({"desplazamiento": -1}, "desplazamiento"),
])
def test_filtros_invalidos_422_con_el_formato_del_proyecto(cliente, cabeceras, parametros, campo):
    r = cliente.get("/api/consultas", params=parametros, headers=cabeceras("med.salazar"))
    assert r.status_code == 422
    cuerpo = r.json()
    assert cuerpo["detail"].startswith("Revise los datos ingresados.")
    assert [e["campo"] for e in cuerpo["errores"]] == [campo]


# ---------------------------------------------------------------------------
# Paginación y orden
# ---------------------------------------------------------------------------
def test_paginacion_total_y_limites(cliente, cabeceras, consultas_b):
    ids = [consultas_b("med.salazar", _momento(DIA, 8 + i)) for i in range(5)]
    esperado = list(reversed(ids))  # más reciente primero
    paginas = [_listar(cliente, cabeceras, "med.salazar", limite=2, desplazamiento=d).json() for d in (0, 2, 4, 6)]
    assert [p["total"] for p in paginas] == [5, 5, 5, 5]
    assert [len(p["consultas"]) for p in paginas] == [2, 2, 1, 0]
    assert [c["id_consulta"] for p in paginas for c in p["consultas"]] == esperado
    assert (paginas[1]["limite"], paginas[1]["desplazamiento"]) == (2, 2)
    por_omision = _listar(cliente, cabeceras, "med.salazar").json()
    assert por_omision["limite"] == 20 and por_omision["desplazamiento"] == 0
    maximo = _listar(cliente, cabeceras, "med.salazar", limite=100).json()
    assert maximo["limite"] == 100 and len(maximo["consultas"]) == 5


def test_orden_estable_con_la_misma_fecha_y_hora(cliente, cabeceras, consultas_b):
    # Se insertan con el id creciente para que el orden físico no coincida con el esperado.
    mismo = _momento(DIA, 12)
    prefijo = uuid.uuid4().hex[:8]
    ids = [consultas_b("med.salazar", mismo, id_consulta=f"{prefijo}-0000-4000-8000-0000000000{i:02d}") for i in range(1, 7)]
    anterior = consultas_b("med.salazar", _momento(DIA, 11))
    esperado = sorted(ids, reverse=True) + [anterior]
    for _ in range(3):
        assert _ids(_listar(cliente, cabeceras, "med.salazar")) == esperado
    paginado = [c for d in (0, 3, 6) for c in _ids(_listar(cliente, cabeceras, "med.salazar", limite=3, desplazamiento=d))]
    assert paginado == esperado


# ---------------------------------------------------------------------------
# Registros sin datos personales
# ---------------------------------------------------------------------------
def test_auditoria_y_registros_sin_datos_personales(cliente, cabeceras, consultas_b, paciente_b, super_engine, caplog):
    consultas_b("med.salazar", _momento(DIA, 10))
    with super_engine.connect() as c:
        desde = c.execute(text("SELECT coalesce(max(id_evento), 0) FROM auditoria.evento_auditoria")).scalar()
    with caplog.at_level(logging.DEBUG):
        assert _listar(cliente, cabeceras, "med.salazar", estado="VERIFICADA").status_code == 200
    with super_engine.connect() as c:
        eventos = c.execute(text(
            """SELECT tipo_evento, entidad, detalle::text AS detalle FROM auditoria.evento_auditoria
                WHERE id_evento > :d AND tipo_evento = 'CONSULTAS_LISTADAS'"""), {"d": desde}).mappings().all()
    assert len(eventos) == 1 and eventos[0]["entidad"] == "usuario"
    assert '"total": 1' in eventos[0]["detalle"] and '"estado": "VERIFICADA"' in eventos[0]["detalle"]
    registros = eventos[0]["detalle"] + "\n".join(r.getMessage() for r in caplog.records)
    for dato in (paciente_b["nombres_apellidos"], paciente_b["numero_hc"], paciente_b["dni"], TEXTO_ORIGINAL):
        assert dato not in registros, dato


# ---------------------------------------------------------------------------
# P12: quién registró la decisión
# ---------------------------------------------------------------------------
def test_registrada_por_solo_con_decision(cliente, cabeceras, consultas_b, super_engine):
    con_decision = consultas_b("med.salazar", _momento(DIA, 10))
    sin_decision = consultas_b("med.salazar", _momento(DIA, 11))
    with super_engine.connect() as c:
        nombre = c.execute(text("SELECT nombre_completo FROM seguridad.usuario WHERE nombre_usuario = 'med.salazar'")).scalar()
    h = cabeceras("med.salazar")
    assert cliente.get(f"/api/consultas/{sin_decision}", headers=h).json()["decision"] is None
    creada = cliente.post(f"/api/consultas/{con_decision}/decision", json={"tipo_decision": "ACEPTA_RECOMENDACION"},
                          headers=h)
    assert creada.status_code == 201 and creada.json()["registrada_por"] == nombre
    decision = cliente.get(f"/api/consultas/{con_decision}", headers=h).json()["decision"]
    assert decision["registrada_por"] == nombre and decision["tipo_decision"] == "ACEPTA_RECOMENDACION"
    assert cliente.get(f"/api/consultas/{sin_decision}", headers=h).json()["decision"] is None
