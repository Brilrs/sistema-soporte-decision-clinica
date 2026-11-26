"""Sprint 3, parte C1: API del reporte exportable (M09, HU10).

Las consultas salen del grafo con modelos falsos y el cliente falso del modelo de lenguaje (como en
D2 y E0), así que todas son de prueba (modo_prueba); para una consulta real se cambia modelo_llm con
la conexión de administración. Nunca se llama a la API real. El texto de los PDF se extrae con pypdf
(dependencia solo de desarrollo); no se comparan bytes exactos ni se depende de la hora actual."""
import builtins
import hashlib
import io
import json
import re
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader
from sqlalchemy import text

from app.api.routes import reportes as rutas
from app.main import app
from app.reportes import contenido as cont
from app.services import reportes as srv
from tests.test_d1_grafo import _caso, entorno  # noqa: F401 (fixtures)
from tests.test_d2_api import _caso_http, cliente_http, consultas_d2, usar_entorno  # noqa: F401
from tests.test_generacion_bd import engine_clinica, engine_generacion, guia  # noqa: F401 (fixtures)

NUMERO = re.compile(r"^EV-\d{4}-\d{5,}$")
OTRA_CONSULTA = "00000000-0000-4000-8000-00000000c1c1"


# ---------------------------------------------------------------------------
# Ayudantes
# ---------------------------------------------------------------------------
@pytest.fixture
def verificada(cliente_http, cabeceras, consultas_d2, super_engine, usar_entorno):
    """Consulta VERIFICADA de med.salazar, con citas y la decisión ACEPTA_RECOMENDACION."""
    fin = _caso_http(cliente_http, cabeceras, consultas_d2, super_engine, usar_entorno, "l")[1][-1]
    assert fin["estado"] == "VERIFICADA"
    r = cliente_http.post(f"/api/consultas/{fin['id_consulta']}/decision", json={"tipo_decision": "ACEPTA_RECOMENDACION"},
                          headers=cabeceras("med.salazar"))
    assert r.status_code == 201
    return fin["id_consulta"]


def _exportar(cliente, cabeceras, id_consulta: str, destino="EXPEDIENTE", secciones=(), usuario="med.salazar"):
    return cliente.post(f"/api/consultas/{id_consulta}/reportes", json={"destino": destino, "secciones": list(secciones)},
                        headers=cabeceras(usuario))


def _vista(cliente, cabeceras, id_consulta: str, destino="EXPEDIENTE", secciones=(), usuario="med.salazar"):
    params = {"destino": destino, **({"secciones": ",".join(secciones)} if secciones else {})}
    return cliente.get(f"/api/consultas/{id_consulta}/reportes/vista-previa", params=params, headers=cabeceras(usuario))


def _paginas(pdf: bytes) -> list[str]:
    return [p.extract_text() or "" for p in PdfReader(BytesIO(pdf)).pages]


def _texto(pdf: bytes) -> str:
    return "\n".join(_paginas(pdf))


def _eventos(super_engine, tipo: str, id_consulta: str) -> list[dict]:
    with super_engine.connect() as c:
        return [r[0] for r in c.execute(text(
            "SELECT detalle FROM auditoria.evento_auditoria WHERE tipo_evento = :t AND id_entidad = :e ORDER BY id_evento"),
            {"t": tipo, "e": id_consulta})]


def _reportes_en_bd(super_engine, id_consulta: str) -> list[dict]:
    with super_engine.connect() as c:
        return [dict(f) for f in c.execute(text(
            """SELECT numero_reporte, destino, secciones_incluidas, formato, hash_documento, u.nombre_usuario
                 FROM asistencia.reporte r JOIN seguridad.usuario u ON u.id_usuario = r.id_usuario
                WHERE r.id_consulta = CAST(:c AS uuid)"""), {"c": id_consulta}).mappings()]


def _sin_prueba(super_engine, id_consulta: str) -> None:
    """Convierte una consulta del cliente falso en «real» (modelo_llm distinto de modelo-falso)."""
    with super_engine.begin() as c:
        c.execute(text("UPDATE asistencia.intento_generacion SET modelo_llm = 'claude-sonnet-5-5' "
                       "WHERE id_consulta = CAST(:c AS uuid)"), {"c": id_consulta})


def _identidad(vista: dict) -> tuple[str, str]:
    campos = {c["etiqueta"]: c["valor"] for c in vista["bloques"][0]["campos"]}
    return campos.get("Paciente") or campos["Nombre"], campos["Historia clínica"]


# ---------------------------------------------------------------------------
# Sesión, permiso, propiedad y estado
# ---------------------------------------------------------------------------
def _las_tres(cliente, cabeceras_de=None, id_consulta=OTRA_CONSULTA):
    h = cabeceras_de or {}
    return [cliente.post(f"/api/consultas/{id_consulta}/reportes", json={"destino": "EXPEDIENTE"}, headers=h),
            cliente.get(f"/api/consultas/{id_consulta}/reportes/vista-previa", params={"destino": "EXPEDIENTE"}, headers=h),
            cliente.get(f"/api/consultas/{id_consulta}/reportes", headers=h)]


def test_sin_sesion_401(cliente_http):
    assert [r.status_code for r in _las_tres(cliente_http)] == [401, 401, 401]


def test_sin_permiso_403(cliente_http, cabeceras):
    # El Administrador no tiene EXPORTAR_REPORTE.
    assert [r.status_code for r in _las_tres(cliente_http, cabeceras("admin.cdss"))] == [403, 403, 403]


def test_consulta_de_otro_404_con_evento(cliente_http, cabeceras, verificada, super_engine):
    respuestas = _las_tres(cliente_http, cabeceras("enf.rojas"), verificada)
    assert [r.status_code for r in respuestas] == [404, 404, 404]
    assert all(r.json()["detail"] == "La consulta no existe" for r in respuestas)
    acciones = {e["accion"] for e in _eventos(super_engine, "ACCESO_DENEGADO_CONSULTA", verificada)}
    assert {"exportar_reporte", "vista_previa_reporte", "listar_reportes"} <= acciones
    assert _reportes_en_bd(super_engine, verificada) == []


def test_consulta_sin_resultado_409(cliente_http, cabeceras, consultas_d2, super_engine, usar_entorno):
    fin = _caso_http(cliente_http, cabeceras, consultas_d2, super_engine, usar_entorno, "g")[1][-1]
    assert fin["estado"] not in cont.ESTADOS_CON_RESULTADO
    r = _exportar(cliente_http, cabeceras, fin["id_consulta"])
    assert r.status_code == 409 and fin["estado"] in r.json()["detail"]
    assert _vista(cliente_http, cabeceras, fin["id_consulta"]).status_code == 409
    assert _reportes_en_bd(super_engine, fin["id_consulta"]) == []


def test_evidencia_insuficiente_si_se_exporta(cliente_http, cabeceras, consultas_d2, super_engine, usar_entorno):
    fin = _caso_http(cliente_http, cabeceras, consultas_d2, super_engine, usar_entorno, "j")[1][-1]
    assert fin["estado"] == "EVIDENCIA_INSUFICIENTE"
    r = _exportar(cliente_http, cabeceras, fin["id_consulta"], secciones=["RECOMENDACION", "EVIDENCIAS"])
    assert r.status_code == 201
    texto = _texto(r.content)
    assert "Evidencia insuficiente" in texto and "La consulta no tiene evidencias citadas." in texto


@pytest.mark.parametrize("cuerpo, campo", [
    ({"destino": "OTRO"}, "destino"),
    ({"destino": "EXPEDIENTE", "secciones": ["NOEXISTE"]}, "secciones.0"),
    ({"destino": "CUIDADOR", "secciones": ["EVIDENCIAS"]}, "secciones"),
    ({"destino": "CUIDADOR", "secciones": ["VERIFICACION"]}, "secciones"),
    ({"destino": "EXPEDIENTE", "formato": "IMPRESION"}, "formato"),
    ({"destino": "EXPEDIENTE", "extra": 1}, "extra"),
    ({}, "destino"),
])
def test_cuerpo_invalido_422(cliente_http, cabeceras, verificada, super_engine, cuerpo, campo):
    r = cliente_http.post(f"/api/consultas/{verificada}/reportes", json=cuerpo, headers=cabeceras("med.salazar"))
    assert r.status_code == 422
    assert [e["campo"] for e in r.json()["errores"]] == [campo]
    assert _reportes_en_bd(super_engine, verificada) == []


@pytest.mark.parametrize("params, campo", [
    ({}, "destino"),
    ({"destino": "AMBOS"}, "destino"),
    ({"destino": "EXPEDIENTE", "secciones": "EVIDENCIAS,NOEXISTE"}, "secciones"),
    ({"destino": "CUIDADOR", "secciones": "ADVERTENCIAS"}, "secciones"),
])
def test_vista_previa_invalida_422(cliente_http, cabeceras, verificada, params, campo):
    r = cliente_http.get(f"/api/consultas/{verificada}/reportes/vista-previa", params=params, headers=cabeceras("med.salazar"))
    assert r.status_code == 422
    assert [e["campo"] for e in r.json()["errores"]] == [campo]


# ---------------------------------------------------------------------------
# PDF, cabeceras, hash y registro
# ---------------------------------------------------------------------------
def test_pdf_con_cabeceras_hash_y_registro(cliente_http, cabeceras, verificada, super_engine):
    nombre, hc = _identidad(_vista(cliente_http, cabeceras, verificada).json())
    r = _exportar(cliente_http, cabeceras, verificada, secciones=["EVIDENCIAS"])
    assert r.status_code == 201 and r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF-")
    numero, huella = r.headers["x-reporte-numero"], r.headers["x-reporte-hash"]
    assert NUMERO.match(numero)
    assert huella == hashlib.sha256(r.content).hexdigest()
    assert r.headers["cache-control"] == "no-store"
    assert r.headers["content-disposition"] == f'attachment; filename="{numero}.pdf"'
    for cabecera in ("content-disposition", "x-reporte-numero", "x-reporte-hash"):
        assert nombre not in r.headers[cabecera] and hc not in r.headers[cabecera]
    # Los metadatos del PDF llevan el número, no el paciente.
    metadatos = json.dumps(dict(PdfReader(BytesIO(r.content)).metadata), ensure_ascii=False)
    assert numero in metadatos and nombre not in metadatos and hc not in metadatos
    filas = _reportes_en_bd(super_engine, verificada)
    assert filas == [{"numero_reporte": numero, "destino": "EXPEDIENTE", "secciones_incluidas":
                      ["PACIENTE", "CLASIFICACION", "EVIDENCIAS"], "formato": "PDF", "hash_documento": huella,
                      "nombre_usuario": "med.salazar"}]
    texto = _texto(r.content)
    assert numero in texto and nombre in texto and hc in texto


def test_numero_correlativo_unico_y_creciente_y_lista(cliente_http, cabeceras, verificada):
    a = _exportar(cliente_http, cabeceras, verificada)
    b = _exportar(cliente_http, cabeceras, verificada, destino="CUIDADOR")
    assert a.status_code == b.status_code == 201
    na, nb = a.headers["x-reporte-numero"], b.headers["x-reporte-numero"]
    assert na != nb and int(nb.rsplit("-", 1)[1]) > int(na.rsplit("-", 1)[1])
    assert a.headers["x-reporte-hash"] != b.headers["x-reporte-hash"]
    lista = cliente_http.get(f"/api/consultas/{verificada}/reportes", headers=cabeceras("med.salazar"))
    assert lista.status_code == 200
    elementos = [rutas.ReporteListado.model_validate(x) for x in lista.json()]
    assert [(x.numero_reporte, x.destino, x.hash_documento) for x in elementos] == [
        (nb, "CUIDADOR", b.headers["x-reporte-hash"]), (na, "EXPEDIENTE", a.headers["x-reporte-hash"])]
    assert "%PDF" not in lista.text


def test_concurrencia_no_repite_numero(verificada, cabeceras, monkeypatch, super_engine):
    """Cuatro exportaciones a la vez: todas reservan su número antes de que ninguna lo registre."""
    n = 4
    barrera = threading.Barrier(n, timeout=20)
    original = srv.generar_pdf

    def esperar_a_las_demas(*args, **kwargs):
        barrera.wait()
        return original(*args, **kwargs)

    monkeypatch.setattr(srv, "generar_pdf", esperar_a_las_demas)
    h = cabeceras("med.salazar")

    def una(_):
        with TestClient(app, raise_server_exceptions=False) as c:
            return c.post(f"/api/consultas/{verificada}/reportes", json={"destino": "EXPEDIENTE"}, headers=h)

    with ThreadPoolExecutor(n) as ejecutor:
        respuestas = list(ejecutor.map(una, range(n)))
    assert [r.status_code for r in respuestas] == [201] * n
    numeros = [r.headers["x-reporte-numero"] for r in respuestas]
    assert len(set(numeros)) == n
    assert sorted(f["numero_reporte"] for f in _reportes_en_bd(super_engine, verificada)) == sorted(numeros)


def test_evento_y_registros_sin_datos_personales(cliente_http, cabeceras, verificada, super_engine, caplog):
    vista = _vista(cliente_http, cabeceras, verificada).json()
    nombre, hc = _identidad(vista)
    dni = _caso("l")["dni"]
    with caplog.at_level("DEBUG"):
        r = _exportar(cliente_http, cabeceras, verificada, secciones=["RECOMENDACION", "DECISION"])
    eventos = _eventos(super_engine, "REPORTE_GENERADO", verificada)
    assert eventos == [{"numero_reporte": r.headers["x-reporte-numero"], "destino": "EXPEDIENTE", "secciones": 4,
                        "hash_prefijo": r.headers["x-reporte-hash"][:12], "modo_prueba": True}]
    previas = _eventos(super_engine, "REPORTE_VISTA_PREVIA", verificada)
    assert previas == [{"destino": "EXPEDIENTE", "secciones": 2, "modo_prueba": True}]
    registros = json.dumps(eventos + previas, ensure_ascii=False) + "\n".join(x.getMessage() for x in caplog.records)
    for dato in (nombre, hc, dni):
        assert dato not in registros


def test_no_queda_ningun_pdf_en_disco(cliente_http, cabeceras, verificada, monkeypatch):
    escrituras: list[str] = []
    abrir, abrir_io = builtins.open, io.open

    def vigilado(original):
        def abrir_vigilado(archivo, modo="r", *args, **kwargs):
            if any(m in str(modo) for m in "wax+"):
                escrituras.append(str(archivo))
            return original(archivo, modo, *args, **kwargs)
        return abrir_vigilado

    carpetas = [Path(tempfile.gettempdir()), Path.cwd()]
    antes = {p for d in carpetas for p in d.glob("*.pdf")}
    monkeypatch.setattr(builtins, "open", vigilado(abrir))
    monkeypatch.setattr(io, "open", vigilado(abrir_io))
    r = _exportar(cliente_http, cabeceras, verificada, destino="CUIDADOR", secciones=["RECOMENDACION", "FIRMA"])
    monkeypatch.undo()
    assert r.status_code == 201
    assert escrituras == []
    assert {p for d in carpetas for p in d.glob("*.pdf")} == antes


def test_vista_previa_no_escribe_y_trae_el_contenido(cliente_http, cabeceras, verificada, super_engine):
    with super_engine.connect() as c:
        secuencia = c.execute(text("SELECT last_value, is_called FROM asistencia.reporte_numero_seq")).one()
    r = _vista(cliente_http, cabeceras, verificada, secciones=["EVIDENCIAS", "VERIFICACION", "DECISION", "FIRMA"])
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    vista = rutas.VistaPrevia.model_validate(r.json())
    assert vista.secciones == ["PACIENTE", "CLASIFICACION", "EVIDENCIAS", "VERIFICACION", "DECISION", "FIRMA"]
    assert [b.seccion for b in vista.bloques] == ["PACIENTE", "CLASIFICACION", "EVIDENCIAS", "VERIFICACION", "DECISION"]
    assert vista.firma and vista.frase_final == cont.FRASE_FINAL and vista.modo_prueba
    assert "numero_reporte" not in r.text and "hash" not in r.text
    decision = {c.etiqueta: c.valor for c in vista.bloques[-1].campos}
    assert decision["Tipo de decisión"] == "Acepta la recomendación" and decision["Registrada por"]
    with super_engine.connect() as c:
        assert c.execute(text("SELECT last_value, is_called FROM asistencia.reporte_numero_seq")).one() == secuencia
    assert _reportes_en_bd(super_engine, verificada) == []
    assert _eventos(super_engine, "REPORTE_GENERADO", verificada) == []


# ---------------------------------------------------------------------------
# Contenido del PDF
# ---------------------------------------------------------------------------
TITULO_DE = {s: cont.TITULOS[s] for s in cont.SECCIONES_POR_DESTINO["EXPEDIENTE"] if s != "FIRMA"}


def test_secciones_elegidas_aparecen_y_las_otras_no(cliente_http, cabeceras, verificada):
    r = _exportar(cliente_http, cabeceras, verificada, secciones=["EVIDENCIAS", "VERIFICACION"])
    texto = _texto(r.content)
    for s in ("PACIENTE", "CLASIFICACION", "EVIDENCIAS", "VERIFICACION"):
        assert TITULO_DE[s] in texto, s
    for s in ("RECOMENDACION", "ADVERTENCIAS", "DECISION"):
        assert TITULO_DE[s] not in texto, s
    assert "Firma y sello del profesional" not in texto and cont.FRASE_FINAL in texto
    assert "6.1 Citas textuales" in texto and "Extracto: «" in texto
    completo = _texto(_exportar(cliente_http, cabeceras, verificada,
                                secciones=list(cont.SECCIONES_POR_DESTINO["EXPEDIENTE"])).content)
    for titulo in TITULO_DE.values():
        assert titulo in completo
    assert "Firma y sello del profesional" in completo and "Registrada por" in completo
    # Caracteres que la fuente debe mostrar (tildes, N.°, comillas latinas) y se pueden copiar.
    assert "N.° EV-" in completo and "Clasificación" in completo and "«" in completo


def test_caracteres_especiales_en_el_pdf():
    """≥, ¿, N° y tildes con DejaVu Sans: se escriben y se extraen tal cual."""
    from datetime import datetime, timezone
    from app.reportes.pdf import generar_pdf
    contenido = {"titulo": cont.TITULO_EXPEDIENTE, "introduccion": None, "establecimiento": "Establecimiento ficticio",
                 "avisos": [], "frase_final": cont.FRASE_FINAL, "firma": False, "generado_por": "Profesional ficticio",
                 "bloques": [{"seccion": "X", "titulo": "Niño de 15 meses", "campos": [{"etiqueta": "Hb", "valor": "≥ 11.0 g/dL"}],
                              "parrafos": ["¿Según la Tabla N° 4?", "Ñandú, acción, pingüino"], "items": []}]}
    texto = _texto(generar_pdf(contenido, "EV-2026-00001", datetime(2026, 1, 2, 15, 0, tzinfo=timezone.utc)))
    for frase in ("≥ 11.0 g/dL", "¿Según la Tabla N° 4?", "Ñandú, acción, pingüino", "Niño de 15 meses"):
        assert frase in texto


def test_pdf_determinista_con_el_mismo_contenido():
    from datetime import datetime, timezone
    from app.reportes.pdf import generar_pdf
    contenido = {"titulo": "T", "introduccion": None, "establecimiento": "E", "avisos": [], "bloques": [],
                 "frase_final": cont.FRASE_FINAL, "firma": True, "generado_por": "G"}
    emision = datetime(2026, 1, 2, 15, 0, tzinfo=timezone.utc)
    assert generar_pdf(contenido, "EV-2026-00007", emision) == generar_pdf(contenido, "EV-2026-00007", emision)


def test_marca_de_prueba_en_cada_pagina_y_en_el_evento(cliente_http, cabeceras, verificada, super_engine):
    r = _exportar(cliente_http, cabeceras, verificada, secciones=list(cont.SECCIONES_POR_DESTINO["EXPEDIENTE"]))
    paginas = _paginas(r.content)
    assert all(cont.AVISO_PRUEBA in p for p in paginas)
    _sin_prueba(super_engine, verificada)
    real = _exportar(cliente_http, cabeceras, verificada)
    assert cont.AVISO_PRUEBA not in _texto(real.content)
    assert [e["modo_prueba"] for e in _eventos(super_engine, "REPORTE_GENERADO", verificada)] == [True, False]


# ---------------------------------------------------------------------------
# Reporte para el cuidador: solo frases fijas, con la línea de revisión pendiente
# ---------------------------------------------------------------------------
def _frases_del_archivo() -> set[str]:
    f = cont.frases()
    return {*f["clasificacion"].values(), f["que_es_anemia"], f["derivacion"], *f["pasos"].values(),
            f["pasos_no_disponibles"], *f["indicaciones_generales"]}


def test_cuidador_solo_con_frases_del_archivo(cliente_http, cabeceras, verificada):
    vista = _vista(cliente_http, cabeceras, verificada, "CUIDADOR", ["RECOMENDACION"]).json()
    assert vista["titulo"] == cont.frases()["titulo"] and vista["introduccion"] == cont.frases()["introduccion"]
    textos = [t for b in vista["bloques"] if b["seccion"] != "PACIENTE"
              for t in b["parrafos"] + [i["texto"] for i in b["items"]] + [d for i in b["items"] for d in i["detalle"]]]
    assert textos and set(textos) <= _frases_del_archivo()
    assert all(not b["campos"] for b in vista["bloques"] if b["seccion"] != "PACIENTE")
    # Con la decisión ACEPTA_RECOMENDACION, cada tipo de paso aparece una vez con su frase.
    resultado = cliente_http.get(f"/api/consultas/{verificada}", headers=cabeceras("med.salazar")).json()
    tipos = list(dict.fromkeys(p["tipo"] for p in resultado["recomendacion"]["recomendacion"]))
    indicaciones = next(b for b in vista["bloques"] if b["seccion"] == "RECOMENDACION")
    assert [i["texto"] for i in indicaciones["items"]] == [cont.frases()["pasos"][t] for t in tipos]
    # El texto generado de la recomendación no entra al reporte del cuidador.
    pdf = _texto(_exportar(cliente_http, cabeceras, verificada, "CUIDADOR", ["RECOMENDACION"]).content)
    for paso in resultado["recomendacion"]["recomendacion"]:
        assert paso["texto"] not in pdf
    assert resultado["recomendacion"]["resumen"] not in pdf


def test_cuidador_sin_decision_aceptada_no_reformula_los_pasos(cliente_http, cabeceras, consultas_d2, super_engine,
                                                               usar_entorno):
    fin = _caso_http(cliente_http, cabeceras, consultas_d2, super_engine, usar_entorno, "i")[1][-1]
    vista = _vista(cliente_http, cabeceras, fin["id_consulta"], "CUIDADOR", ["RECOMENDACION"]).json()
    indicaciones = next(b for b in vista["bloques"] if b["seccion"] == "RECOMENDACION")
    assert [i["texto"] for i in indicaciones["items"]] == [cont.frases()["pasos_no_disponibles"]]


def test_cuidador_con_la_linea_de_revision_mientras_no_este_revisado(cliente_http, cabeceras, verificada, monkeypatch):
    assert cont.frases()["revisado"] is False
    r = _exportar(cliente_http, cabeceras, verificada, "CUIDADOR", ["RECOMENDACION", "FIRMA"])
    assert all(cont.AVISO_REVISION in p for p in _paginas(r.content))
    expediente = _exportar(cliente_http, cabeceras, verificada)
    assert cont.AVISO_REVISION not in _texto(expediente.content)
    # Con el archivo aprobado (revisado: true) la línea desaparece.
    aprobado = {**cont.frases(), "revisado": True}
    monkeypatch.setattr(cont, "frases", lambda: aprobado)
    revisado = _exportar(cliente_http, cabeceras, verificada, "CUIDADOR", ["RECOMENDACION"])
    assert cont.AVISO_REVISION not in _texto(revisado.content)
    assert _vista(cliente_http, cabeceras, verificada, "CUIDADOR").json()["revision_pendiente"] is False


# Fila 166: derivación una sola vez, frase final para la familia y fecha sin hora (unidad, sin base).
def _datos_cuidador(tipos=("TRATAMIENTO", "DERIVACION", "SEGUIMIENTO"), decision="ACEPTA_RECOMENDACION",
                    requiere_derivacion=True, categoria="ANEMIA_SEVERA", inicio=None) -> cont.DatosReporte:
    from datetime import date, datetime, timezone
    clinico = {"clasificacion": {"categoria": categoria, "nivel_riesgo": "MUY_ALTO", "requiere_derivacion": requiere_derivacion,
                                 "hb_ajustada_g_dl": 6.8, "altitud_msnm": None},
               "decision": None if decision is None else {"tipo_decision": decision},
               "fecha_hora_inicio": inicio or datetime(2026, 11, 26, 15, 30, tzinfo=timezone.utc), "estado": "VERIFICADA"}
    generacion = {"modo_prueba": False, "recomendacion": {"recomendacion": [{"tipo": t, "texto": "x"} for t in tipos]}}
    return cont.DatosReporte(clinico, generacion, "Paciente Ficticio", "HC-PRUEBA", "M", date(2026, 11, 26), 26, 6.8)


def _armar(d, destino="CUIDADOR", secciones=("PACIENTE", "CLASIFICACION", "RECOMENDACION", "FIRMA")) -> dict:
    return cont.armar(d, destino, list(secciones), "Profesional ficticio", "Establecimiento de prueba", "id")


def _textos_cuidador(vista: dict) -> list[str]:
    return [t for b in vista["bloques"] for t in b["parrafos"] + [i["texto"] for i in b["items"]]]


def test_cuidador_dice_la_derivacion_una_sola_vez():
    f = cont.frases()
    derivacion = (f["derivacion"], f["pasos"]["DERIVACION"])
    # Con el paso DERIVACION en las indicaciones, el párrafo de la clasificación no se agrega.
    textos = _textos_cuidador(_armar(_datos_cuidador()))
    assert sum(t in derivacion for t in textos) == 1 and f["pasos"]["DERIVACION"] in textos
    # Sin el bloque de indicaciones, sin el paso DERIVACION o sin la decisión aceptada, la dice el párrafo.
    for vista in (_armar(_datos_cuidador(), secciones=("PACIENTE", "CLASIFICACION")),
                  _armar(_datos_cuidador(tipos=("TRATAMIENTO",))),
                  _armar(_datos_cuidador(decision="MODIFICA_RECOMENDACION")),
                  _armar(_datos_cuidador(decision=None))):
        textos = _textos_cuidador(vista)
        assert sum(t in derivacion for t in textos) == 1 and f["derivacion"] in textos
    # Sin derivación requerida no hay párrafo; el paso aceptado se reformula igual.
    textos = _textos_cuidador(_armar(_datos_cuidador(requiere_derivacion=False, categoria="ANEMIA_MODERADA")))
    assert f["derivacion"] not in textos and f["pasos"]["DERIVACION"] in textos
    # Ninguna frase agrega plazos.
    assert not any("inmediat" in t.lower() for t in textos)


def test_frase_final_y_fecha_segun_el_destino():
    from datetime import datetime, timezone
    # 03:10 UTC del 27/11 es el 26/11 en Lima: la fecha del cuidador es la de Perú.
    d = _datos_cuidador(inicio=datetime(2026, 11, 27, 3, 10, tzinfo=timezone.utc))
    cuidador = _armar(d)
    assert cuidador["frase_final"] == cont.FRASE_FINAL_CUIDADOR != cont.FRASE_FINAL
    assert not re.search(r"\d", cont.FRASE_FINAL_CUIDADOR)
    campos = {c["etiqueta"]: c["valor"] for c in cuidador["bloques"][0]["campos"]}
    assert campos["Fecha de la evaluación"] == "26/11/2026"
    expediente = _armar(d, "EXPEDIENTE", ("PACIENTE", "CLASIFICACION"))
    assert expediente["frase_final"] == cont.FRASE_FINAL
    campos = {c["etiqueta"]: c["valor"] for c in expediente["bloques"][0]["campos"]}
    assert campos["Fecha de la consulta"] == "26/11/2026 22:10"
    # El aviso de revisión sigue mientras revisado sea false.
    assert cont.frases()["revisado"] is False and cuidador["avisos"] == [cont.AVISO_REVISION]
    assert cuidador["revision_pendiente"] is True


def test_pdf_del_cuidador_con_la_frase_para_la_familia(cliente_http, cabeceras, verificada):
    texto = " ".join(_texto(_exportar(cliente_http, cabeceras, verificada, "CUIDADOR", ["RECOMENDACION"]).content).split())
    assert cont.FRASE_FINAL_CUIDADOR in texto and cont.FRASE_FINAL not in texto
    assert cont.FRASE_FINAL in _texto(_exportar(cliente_http, cabeceras, verificada).content)


def test_el_archivo_de_frases_esta_completo():
    f = cont.frases()
    assert set(f["clasificacion"]) == {*cont.CATEGORIAS, "SIN_CLASIFICACION"}
    assert set(f["pasos"]) == set(cont.TIPOS_PASO)
    assert {"revisado", "revisado_por", "fecha_revision"} <= set(f)
    # Ninguna frase da cifras (dosis, plazos ni edades): solo reformulan lo que ya está en la consulta.
    for frase in _frases_del_archivo():
        assert not re.search(r"\d", frase), frase


# ---------------------------------------------------------------------------
# Fixtures del frontend (parte C2): vista previa de cada destino y lista de reportes
# ---------------------------------------------------------------------------
DIR_FIXTURES = Path(__file__).resolve().parents[2] / "frontend" / "src" / "__fixtures__"
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
FECHA_FIJA = "2026-10-20T10:00:00-05:00"
# Datos ficticios del simulador del frontend (src/pruebas/simulador.ts: FICHA_FIXTURE y USUARIO).
PACIENTE_FIXTURE, HC_FIXTURE, USUARIO_FIXTURE = "Paciente Ficticio Dos", "HC-PRUEBA-2", "Lic. Usuaria Prueba"


def _normalizar_fixture(datos, nombre: str, hc: str, usuario: str, numeros: list[str]) -> object:
    texto = json.dumps(datos, ensure_ascii=False)
    for real, ficticio in ((nombre, PACIENTE_FIXTURE), (hc, HC_FIXTURE), (usuario, USUARIO_FIXTURE)):
        texto = texto.replace(real, ficticio)
    for i, n in enumerate(numeros, start=1):
        texto = texto.replace(n, f"EV-2026-{i:05d}")
    ids: dict[str, str] = {}
    for u in _UUID.findall(texto):
        ids.setdefault(u, f"00000000-0000-4000-8000-{len(ids) + 1:012d}")
    texto = _UUID.sub(lambda m: ids[m.group()], texto)
    texto = re.sub(r'"[0-9a-f]{64}"', lambda m: '"' + "a" * 64 + '"', texto)
    datos = json.loads(texto)

    def fechas(v, clave=""):
        if isinstance(v, dict):
            if v.get("etiqueta") == "Fecha de la evaluación":  # cuidador: fecha de la consulta sin la hora
                return {**v, "valor": "20/10/2026"}
            return {k: fechas(x, k) for k, x in v.items()}
        if isinstance(v, list):
            return [fechas(x, clave) for x in v]
        if clave in ("fecha_consulta", "fecha_generacion"):
            return FECHA_FIJA
        if isinstance(v, str):
            return re.sub(r"\d{2}/\d{2}/\d{4} \d{2}:\d{2}", "20/10/2026 10:00", v)
        return v
    return fechas(datos)


def test_genera_los_fixtures_de_reportes_para_el_frontend(cliente_http, cabeceras, verificada, super_engine):
    h = cabeceras("med.salazar")
    with super_engine.connect() as c:
        usuario = c.execute(text("SELECT nombre_completo FROM seguridad.usuario WHERE nombre_usuario = 'med.salazar'")).scalar()
    todas = list(cont.SECCIONES_POR_DESTINO["EXPEDIENTE"])
    expediente = _vista(cliente_http, cabeceras, verificada, "EXPEDIENTE", todas).json()
    cuidador = _vista(cliente_http, cabeceras, verificada, "CUIDADOR", ["RECOMENDACION", "FIRMA"]).json()
    nombre, hc = _identidad(expediente)
    numeros = [_exportar(cliente_http, cabeceras, verificada, d, s).headers["x-reporte-numero"]
               for d, s in (("EXPEDIENTE", todas), ("CUIDADOR", ["RECOMENDACION", "FIRMA"]))]
    lista = cliente_http.get(f"/api/consultas/{verificada}/reportes", headers=h).json()
    salidas = {"reporte_vista_previa_expediente.json": expediente, "reporte_vista_previa_cuidador.json": cuidador,
               "reportes_lista.json": lista}
    for archivo, datos in salidas.items():
        normalizado = _normalizar_fixture(datos, nombre, hc, usuario, numeros)
        texto = json.dumps(normalizado, ensure_ascii=False, indent=2) + "\n"
        for dato in (nombre, hc, _caso("l")["dni"]):
            assert dato not in texto, (archivo, dato)
        (DIR_FIXTURES / archivo).write_text(texto, encoding="utf-8", newline="\n")
    for v in (expediente, cuidador):
        rutas.VistaPrevia.model_validate(v)
    assert [x["numero_reporte"] for x in lista] == list(reversed(numeros))
