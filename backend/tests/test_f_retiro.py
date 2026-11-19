"""Sprint 3, parte F: retiro de guías (HU17, decisión 6 del plan).

Todas las guías que se retiran son sintéticas (códigos PRUEBA-F-... o las de la fixture guia de
test_generacion_bd) y se borran al final con la conexión de administración; las referencias que una
prueba agrega en la configuración (umbral, ajuste o parámetro que citan la guía) se restauran en un
finally. De las guías reales de la base de pruebas solo se leen las referencias (GET), nunca se
retiran. La bitácora se conserva: es inmutable."""
import re
import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from app.core.config import get_settings
from app.core.modelos import EmbedderFalso, TokenizadorFalso
from app.core.vectores import AlmacenMemoria, RegistroVector
from app.indexador.__main__ import MENSAJE_OBSOLETA, procesar_pendientes
from app.indexador.indexacion import Indexador
from app.indexador.repositorio import USUARIO_SISTEMA, Repositorio
from app.rag.bm25 import CacheBM25, terminos_consulta
from app.rag.punteros import ReglaPuntero, buscar_destino
from app.rag.recuperacion import FILTRO_VECTORIAL, comprobar_fragmentos
from app.services import conocimiento as srv
from tests.test_d1_grafo import entorno  # noqa: F401 (fixture)
from tests.test_d2_api import _caso_http, cliente_http, consultas_d2, usar_entorno  # noqa: F401
from tests.test_generacion_bd import engine_clinica, engine_generacion, guia  # noqa: F401 (fixtures)
from tests.test_indexador_flujo import engine_indexador  # noqa: F401 (fixture)
from tests.test_indexador_m11 import carpetas  # noqa: F401 (fixture)

URL = "/api/conocimiento/documentos"
ADMIN = "admin.cdss"
ROLES_SIN_PERMISO = ["enf.rojas", "med.salazar", "nut.vilca", "coord.ortiz"]
NTS = "10000000-0000-0000-0000-000000000213"
RM429 = "10000000-0000-0000-0000-000000000429"
MOTIVO = "Guía de prueba reemplazada por una versión nueva"
TERMINOS = terminos_consulta("sulfato ferroso hierro suplementación", [])


# ---------------------------------------------------------------------------
# Ayudantes
# ---------------------------------------------------------------------------
def _borrar(super_engine, condicion: str, p: dict) -> None:
    with super_engine.begin() as c:
        ids = [r[0] for r in c.execute(text(f"SELECT id_documento FROM conocimiento.documento_fuente WHERE {condicion}"), p)]
        q = {"ids": ids}
        # Primero todos los fragmentos: uno puede apuntar a otra guía de la prueba como modificatoria.
        c.execute(text("DELETE FROM conocimiento.trabajo_indexacion WHERE id_documento = ANY(:ids)"), q)
        c.execute(text("DELETE FROM conocimiento.fragmento WHERE id_documento = ANY(:ids)"), q)
        c.execute(text("DELETE FROM conocimiento.documento_fuente WHERE id_documento = ANY(:ids)"), q)


@pytest.fixture
def guias_f(super_engine):
    """Crea guías sintéticas (nivel 1 o 2, con fragmentos si se piden); al final las borra con sus
    trabajos y fragmentos, aunque la prueba falle. Exige una cola sin trabajos activos."""
    with super_engine.connect() as c:
        activos = c.execute(text("SELECT count(*) FROM conocimiento.trabajo_indexacion "
                                 "WHERE estado IN ('PENDIENTE','EN_CURSO')")).scalar()
    assert activos == 0, "La base de pruebas tiene trabajos activos de otra prueba"

    def crear(nivel: int = 2, codigo: str | None = None, fragmentos: int = 0) -> dict:
        id_doc = str(uuid.uuid4())
        codigo = codigo or f"PRUEBA-F-{id_doc[:8]}"
        with super_engine.begin() as c:
            c.execute(text(
                """INSERT INTO conocimiento.documento_fuente
                     (id_documento, titulo, codigo_documento, entidad_emisora, tipo_documento, nivel, anio_publicacion,
                      idioma, cargado_por, estado_indexacion, ruta_blob, hash_archivo, total_fragmentos)
                   VALUES (:id, 'Guía sintética de la parte F', :cod, 'OTRA', 'LITERATURA', :n, 2024, 'es', :u,
                           'COMPLETADA', 'local://prueba/f.pdf', :h, :t)"""),
                {"id": id_doc, "cod": codigo, "n": nivel, "u": USUARIO_SISTEMA, "h": uuid.uuid4().hex * 2, "t": fragmentos})
            for orden in range(1, fragmentos + 1):
                c.execute(text(
                    """INSERT INTO conocimiento.fragmento (id_documento, numero_orden, seccion, pagina_inicio, pagina_fin,
                         texto, numero_tokens, modelo_embedding, vigente)
                       VALUES (:d, :o, :s, 1, 1, :t, 20, 'falso', true)"""),
                    {"d": id_doc, "o": orden, "s": f"Sección {orden}", "t": f"Texto sintético de la parte F número {orden}"})
        return {"id": id_doc, "codigo": codigo, "nivel": nivel}

    yield crear
    _borrar(super_engine, "codigo_documento LIKE 'PRUEBA-F-%'", {})


@pytest.fixture
def ahora(super_engine):
    with super_engine.connect() as c:
        return c.execute(text("SELECT clock_timestamp()")).scalar()


@pytest.fixture
def modo_evaluacion(monkeypatch):
    monkeypatch.setattr(get_settings(), "modo_evaluacion", True)


def _retirar(cliente, cabeceras, id_doc: str, motivo: str = MOTIVO, confirmacion: str | None = None, usuario=ADMIN):
    cuerpo = {"motivo": motivo} if confirmacion is None else {"motivo": motivo, "confirmacion": confirmacion}
    return cliente.post(f"{URL}/{id_doc}/retiro", json=cuerpo, headers=cabeceras(usuario))


def _referencias(cliente, cabeceras, id_doc: str, usuario=ADMIN):
    return cliente.get(f"{URL}/{id_doc}/referencias", headers=cabeceras(usuario))


def _fila(super_engine, id_doc: str):
    with super_engine.connect() as c:
        return c.execute(text(
            """SELECT d.estado, d.fecha_retiro, d.motivo_retiro, u.nombre_usuario AS retirado_por,
                      (SELECT count(*) FROM conocimiento.trabajo_indexacion t WHERE t.id_documento = d.id_documento) AS trabajos
                 FROM conocimiento.documento_fuente d LEFT JOIN seguridad.usuario u ON u.id_usuario = d.retirado_por
                WHERE d.id_documento = :id"""), {"id": id_doc}).one()


def _trabajos(super_engine, id_doc: str) -> list:
    with super_engine.connect() as c:
        return c.execute(text("SELECT tipo, estado, mensaje_error FROM conocimiento.trabajo_indexacion "
                              "WHERE id_documento = :id ORDER BY fecha_solicitud, id_trabajo"), {"id": id_doc}).all()


def _eventos(super_engine, tipo: str, id_doc: str, desde) -> list[dict]:
    with super_engine.connect() as c:
        return [r[0] for r in c.execute(text(
            """SELECT detalle FROM auditoria.evento_auditoria
                WHERE tipo_evento = :t AND id_entidad = :e AND fecha_hora >= :d ORDER BY id_evento"""),
            {"t": tipo, "e": id_doc, "d": desde})]


def _sin_cambios(super_engine, id_doc: str) -> None:
    f = _fila(super_engine, id_doc)
    assert (f.estado, f.fecha_retiro, f.motivo_retiro, f.retirado_por, f.trabajos) == ("VIGENTE", None, None, None, 0)


# ---------------------------------------------------------------------------
# Permisos y existencia
# ---------------------------------------------------------------------------
def _rutas(id_doc: str):
    return [("get", f"{URL}/{id_doc}/referencias", None), ("post", f"{URL}/{id_doc}/retiro", {"motivo": MOTIVO})]


def test_sin_sesion_responde_401(cliente, super_engine, guias_f):
    d = guias_f()
    for metodo, ruta, cuerpo in _rutas(d["id"]):
        assert getattr(cliente, metodo)(ruta, **({"json": cuerpo} if cuerpo else {})).status_code == 401
    _sin_cambios(super_engine, d["id"])


@pytest.mark.parametrize("usuario", ROLES_SIN_PERMISO)
def test_roles_sin_administrar_guias_reciben_403_sin_cambiar_nada(cliente, cabeceras, super_engine, guias_f, usuario):
    d = guias_f()
    assert _referencias(cliente, cabeceras, d["id"], usuario).status_code == 403
    assert _retirar(cliente, cabeceras, d["id"], usuario=usuario).status_code == 403
    _sin_cambios(super_engine, d["id"])


def test_guia_inexistente_responde_404(cliente, cabeceras):
    otro = str(uuid.uuid4())
    assert _referencias(cliente, cabeceras, otro).status_code == 404
    r = _retirar(cliente, cabeceras, otro)
    assert r.status_code == 404 and r.json()["codigo"] == "NO_ENCONTRADA"


# ---------------------------------------------------------------------------
# Nivel 2: sin restricción
# ---------------------------------------------------------------------------
def test_nivel_2_sin_referencias_ni_confirmacion_se_retira(cliente, cabeceras, super_engine, guias_f, ahora):
    d = guias_f(nivel=2)
    ref = _referencias(cliente, cabeceras, d["id"]).json()
    assert ref == {"id_documento": d["id"], "nivel": 2, "estado": "VIGENTE", "codigo_confirmacion": None,
                   "referencias": [], "puede_retirarse": True}
    r = _retirar(cliente, cabeceras, d["id"], motivo=f"  {MOTIVO}  ")
    assert r.status_code == 201, r.text
    cuerpo = r.json()
    assert cuerpo["documento"]["estado"] == "OBSOLETA" and cuerpo["documento"]["motivo_retiro"] == MOTIVO
    assert cuerpo["documento"]["retirado_por"] and cuerpo["documento"]["fecha_retiro"]
    assert cuerpo["documento"]["ultimo_trabajo"]["tipo"] == "RETIRO"
    assert (cuerpo["trabajo"]["tipo"], cuerpo["trabajo"]["estado"], cuerpo["trabajo"]["id_documento"]) == \
        ("RETIRO", "PENDIENTE", d["id"])
    f = _fila(super_engine, d["id"])
    assert (f.estado, f.motivo_retiro, f.retirado_por) == ("OBSOLETA", MOTIVO, ADMIN) and f.fecha_retiro is not None
    assert [(t.tipo, t.estado) for t in _trabajos(super_engine, d["id"])] == [("RETIRO", "PENDIENTE")]
    # El detalle muestra quién, cuándo y por qué; la guía se conserva.
    det = cliente.get(f"{URL}/{d['id']}", headers=cabeceras(ADMIN)).json()
    assert det["estado"] == "OBSOLETA" and det["motivo_retiro"] == MOTIVO and det["retirado_por"] == cuerpo["documento"]["retirado_por"]


def test_evento_guia_retirada_sin_datos_personales(cliente, cabeceras, super_engine, guias_f, ahora):
    d = guias_f(nivel=2)
    r = _retirar(cliente, cabeceras, d["id"])
    assert r.status_code == 201
    eventos = _eventos(super_engine, "GUIA_RETIRADA", d["id"], ahora)
    assert eventos == [{"id_documento": d["id"], "codigo_documento": d["codigo"], "nivel": 2, "motivo": MOTIVO,
                        "id_trabajo": r.json()["trabajo"]["id_trabajo"]}]
    texto = str(eventos[0])
    nombre = r.json()["documento"]["retirado_por"]
    assert nombre not in texto and "Guía sintética" not in texto and ADMIN not in texto


@pytest.mark.parametrize("motivo", ["corto", " " * 20 + "123456789" + " " * 20, "x" * 251])
def test_motivo_fuera_de_10_a_250_caracteres_responde_422(cliente, cabeceras, super_engine, guias_f, motivo):
    d = guias_f(nivel=2)
    r = _retirar(cliente, cabeceras, d["id"], motivo=motivo)
    assert r.status_code == 422 and r.json()["codigo"] == "MOTIVO_INVALIDO"
    _sin_cambios(super_engine, d["id"])


def test_motivo_de_250_caracteres_se_acepta(cliente, cabeceras, guias_f):
    d = guias_f(nivel=2)
    assert _retirar(cliente, cabeceras, d["id"], motivo="m" * 250).status_code == 201


def test_ya_obsoleta_responde_409(cliente, cabeceras, super_engine, guias_f):
    d = guias_f(nivel=2)
    assert _retirar(cliente, cabeceras, d["id"]).status_code == 201
    with super_engine.begin() as c:  # el trabajo RETIRO terminó: solo queda la guarda de estado
        c.execute(text("UPDATE conocimiento.trabajo_indexacion SET estado = 'COMPLETADO', fecha_fin = now() "
                       "WHERE id_documento = :id"), {"id": d["id"]})
    r = _retirar(cliente, cabeceras, d["id"])
    assert r.status_code == 409 and r.json()["codigo"] == "YA_OBSOLETA"
    assert len(_trabajos(super_engine, d["id"])) == 1


def test_trabajo_de_indexacion_activo_responde_409(cliente, cabeceras, super_engine, guias_f):
    d = guias_f(nivel=2)
    with super_engine.begin() as c:
        c.execute(text("INSERT INTO conocimiento.trabajo_indexacion (id_documento, tipo, estado, solicitado_por) "
                       "VALUES (:d, 'REINDEXACION', 'PENDIENTE', :u)"), {"d": d["id"], "u": USUARIO_SISTEMA})
    r = _retirar(cliente, cabeceras, d["id"])
    assert r.status_code == 409 and r.json()["codigo"] == "TRABAJO_ACTIVO"
    f = _fila(super_engine, d["id"])
    assert f.estado == "VIGENTE" and f.trabajos == 1


def test_modo_de_evaluacion_responde_423_sin_cambiar_nada(cliente, cabeceras, super_engine, guias_f, ahora,
                                                          modo_evaluacion):
    d = guias_f(nivel=2)
    r = _retirar(cliente, cabeceras, d["id"])
    assert r.status_code == 423 and "modo de evaluación" in r.json()["detail"]
    _sin_cambios(super_engine, d["id"])
    assert _eventos(super_engine, "PARAMETRO_CAMBIO_BLOQUEADO", d["id"], ahora) == [{"accion": "RETIRAR_GUIA"}]
    assert _eventos(super_engine, "GUIA_RETIRADA", d["id"], ahora) == []


# ---------------------------------------------------------------------------
# Nivel 1: guardas y confirmación con el código
# ---------------------------------------------------------------------------
def test_nivel_1_sin_referencias_exige_el_codigo_exacto(cliente, cabeceras, super_engine, guias_f):
    d = guias_f(nivel=1)
    ref = _referencias(cliente, cabeceras, d["id"]).json()
    assert ref["referencias"] == [] and ref["puede_retirarse"] is True and ref["codigo_confirmacion"] == d["codigo"]
    for confirmacion in (None, "", d["codigo"].lower(), f" {d['codigo']}", d["codigo"] + "."):
        r = _retirar(cliente, cabeceras, d["id"], confirmacion=confirmacion)
        assert r.status_code == 422 and r.json()["codigo"] == "CONFIRMACION_INCORRECTA", confirmacion
        _sin_cambios(super_engine, d["id"])
    assert _retirar(cliente, cabeceras, d["id"], confirmacion=d["codigo"]).status_code == 201


def _referencia_en_configuracion(super_engine, tabla: str, llave: str, id_doc: str):
    """Hace que una fila vigente de la tabla cite la guía; devuelve una función que la restaura."""
    with super_engine.begin() as c:
        fila = c.execute(text(f"SELECT {llave}, id_documento FROM configuracion.{tabla} "
                              f"WHERE vigente_hasta IS NULL ORDER BY {llave} LIMIT 1")).one()
        c.execute(text(f"UPDATE configuracion.{tabla} SET id_documento = :d WHERE {llave} = :k"), {"d": id_doc, "k": fila[0]})

    def restaurar():
        with super_engine.begin() as c:
            c.execute(text(f"UPDATE configuracion.{tabla} SET id_documento = :d WHERE {llave} = :k"),
                      {"d": fila[1], "k": fila[0]})
    return restaurar


def _guarda(caso: str, super_engine, guias_f, monkeypatch, d: dict):
    """Prepara una sola referencia del tipo pedido; devuelve la función que la deshace."""
    if caso == "umbral":
        return _referencia_en_configuracion(super_engine, "umbral_hemoglobina", "id_umbral", d["id"])
    if caso == "ajuste":
        return _referencia_en_configuracion(super_engine, "ajuste_altitud", "id_ajuste", d["id"])
    if caso == "parametro":
        return _referencia_en_configuracion(super_engine, "parametro_sistema", "id_parametro", d["id"])
    if caso == "modificacion":
        otra = guias_f(nivel=1, fragmentos=2)
        with super_engine.begin() as c:
            c.execute(text("UPDATE conocimiento.fragmento SET id_documento_modificatorio = :m, vigente = false, "
                           "motivo_exclusion = 'Sustituido por la guía de prueba' "
                           "WHERE id_documento = :o AND numero_orden = 1"), {"m": d["id"], "o": otra["id"]})
        return lambda: None
    if caso in ("mapa_base", "mapa_modificatorio"):
        otro = str(uuid.uuid4())
        base, modificatoria = (d["id"], otro) if caso == "mapa_base" else (otro, d["id"])
        monkeypatch.setattr(srv, "_ids_del_manifiesto", lambda: {"base": base})
        monkeypatch.setattr(srv, "_mapas", lambda: [("prueba.yaml", SimpleNamespace(
            codigo="PRUEBA-F-MODIFICATORIA", documento_modificado="base", id_documento_modificatorio=modificatoria))])
        return lambda: None
    if caso in ("puntero_origen", "puntero_destino"):
        origen, destino = (d["codigo"], "OTRO") if caso == "puntero_origen" else ("OTRO", d["codigo"])
        monkeypatch.setattr(srv, "reglas_vigentes", lambda: (ReglaPuntero("prueba-f", origen, re.compile("x"), destino, "m"),))
        return lambda: None
    raise AssertionError(caso)


GUARDAS = {"umbral": "UMBRAL_HEMOGLOBINA", "ajuste": "AJUSTE_ALTITUD", "parametro": "PARAMETRO_SISTEMA",
           "modificacion": "MODIFICACION", "mapa_base": "MAPA_MODIFICACIONES", "mapa_modificatorio": "MAPA_MODIFICACIONES",
           "puntero_origen": "PUNTERO", "puntero_destino": "PUNTERO"}


@pytest.mark.parametrize("caso", list(GUARDAS))
def test_cada_referencia_vigente_bloquea_el_nivel_1_con_409_y_su_lista(cliente, cabeceras, super_engine, guias_f,
                                                                       monkeypatch, caso):
    d = guias_f(nivel=1)
    deshacer = _guarda(caso, super_engine, guias_f, monkeypatch, d)
    try:
        ref = _referencias(cliente, cabeceras, d["id"]).json()
        assert [x["tipo"] for x in ref["referencias"]] == [GUARDAS[caso]] and ref["puede_retirarse"] is False
        assert ref["referencias"][0]["descripcion"]
        r = _retirar(cliente, cabeceras, d["id"], confirmacion=d["codigo"])
        assert r.status_code == 409 and r.json()["codigo"] == "REFERENCIAS_VIGENTES"
        assert r.json()["referencias"] == ref["referencias"]
        _sin_cambios(super_engine, d["id"])
    finally:
        deshacer()


def test_la_misma_referencia_no_bloquea_el_nivel_2(cliente, cabeceras, super_engine, guias_f, monkeypatch):
    d = guias_f(nivel=2)
    deshacer = _guarda("umbral", super_engine, guias_f, monkeypatch, d)
    try:
        assert _referencias(cliente, cabeceras, d["id"]).json()["referencias"] == []
        assert _retirar(cliente, cabeceras, d["id"]).status_code == 201
    finally:
        deshacer()


def test_referencias_reales_de_la_nts_213_y_la_rm_429(cliente, cabeceras, super_engine):
    """Solo lectura: las guías reales de la base de pruebas tienen el mapa del indexador y la regla de
    punteros; ninguna prueba intenta retirarlas."""
    nts = _referencias(cliente, cabeceras, NTS).json()
    tipos = {x["tipo"] for x in nts["referencias"]}
    assert {"MAPA_MODIFICACIONES", "PUNTERO"} <= tipos and nts["puede_retirarse"] is False
    assert any("RM 429-2024/MINSA" in x["descripcion"] for x in nts["referencias"])
    rm = _referencias(cliente, cabeceras, RM429).json()
    assert {"MAPA_MODIFICACIONES", "PUNTERO"} <= {x["tipo"] for x in rm["referencias"]}
    assert any("destino" in x["descripcion"] for x in rm["referencias"] if x["tipo"] == "PUNTERO")


# ---------------------------------------------------------------------------
# Trabajo RETIRO del indexador (cdss_indexador, almacén en memoria)
# ---------------------------------------------------------------------------
def _almacen_con(d: dict, super_engine) -> AlmacenMemoria:
    almacen = AlmacenMemoria()
    with super_engine.connect() as c:
        filas = c.execute(text("SELECT id_fragmento::text, texto FROM conocimiento.fragmento WHERE id_documento = :d"),
                          {"d": d["id"]}).all()
    for id_f, texto in filas:
        almacen.agregar([RegistroVector(id_f, EmbedderFalso().embeber([texto])[0], texto, {
            "id_documento": d["id"], "nivel": d["nivel"], "estado_documento": "VIGENTE", "vigente": True})])
    return almacen


class AlmacenQueFalla(AlmacenMemoria):
    def actualizar_metadatos(self, ids, cambios):
        raise RuntimeError("ChromaDB no responde")


def _indexador(engine_indexador, almacen) -> Indexador:  # noqa: F811
    return Indexador(Repositorio(engine_indexador), almacen, EmbedderFalso(), TokenizadorFalso(), lote_progreso=2)


def test_el_trabajo_retiro_actualiza_los_metadatos_sin_borrar_y_es_idempotente(
        cliente, cabeceras, super_engine, guias_f, engine_indexador, carpetas, ahora):  # noqa: F811
    d = guias_f(nivel=1, fragmentos=5)
    almacen = _almacen_con(d, super_engine)
    assert _retirar(cliente, cabeceras, d["id"], confirmacion=d["codigo"]).status_code == 201
    indexador = _indexador(engine_indexador, almacen)
    assert procesar_pendientes(indexador, carpetas[0], una_vez=True) == 0
    metadatos = almacen.metadatos_de_documento(d["id"])
    assert len(metadatos) == 5 and {m["estado_documento"] for m in metadatos.values()} == {"OBSOLETA"}
    assert all(m["vigente"] is True for m in metadatos.values())  # solo cambia estado_documento
    assert [(t.tipo, t.estado, t.mensaje_error) for t in _trabajos(super_engine, d["id"])] == [("RETIRO", "COMPLETADO", None)]
    with super_engine.connect() as c:  # los fragmentos de PostgreSQL no se tocan
        assert c.execute(text("SELECT count(*) FROM conocimiento.fragmento WHERE id_documento = :d AND vigente"),
                         {"d": d["id"]}).scalar() == 5
    # Idempotente: volver a aplicarlo deja lo mismo.
    assert indexador.retirar(d["id"]) == 5
    assert almacen.metadatos_de_documento(d["id"]) == metadatos
    assert [e["vectores"] for e in _eventos(super_engine, "GUIA_RETIRO_APLICADO", d["id"], ahora)] == [5, 5]


def test_un_fallo_del_retiro_deja_el_trabajo_en_error_y_reintentar_crea_otro_retiro(
        cliente, cabeceras, super_engine, guias_f, engine_indexador, carpetas, ahora):  # noqa: F811
    d = guias_f(nivel=2, fragmentos=3)
    assert _retirar(cliente, cabeceras, d["id"]).status_code == 201
    falla = AlmacenQueFalla()
    falla.registros = _almacen_con(d, super_engine).registros
    assert procesar_pendientes(_indexador(engine_indexador, falla), carpetas[0], una_vez=True) == 0
    [t] = _trabajos(super_engine, d["id"])
    assert (t.tipo, t.estado) == ("RETIRO", "ERROR")
    assert "ChromaDB no responde" in t.mensaje_error and "Reintentar" in t.mensaje_error
    assert _eventos(super_engine, "GUIA_RETIRO_ERROR", d["id"], ahora)
    assert _fila(super_engine, d["id"]).estado == "OBSOLETA"  # el retiro en PostgreSQL se mantiene
    r = cliente.post(f"{URL}/{d['id']}/reintentar", headers=cabeceras(ADMIN))
    assert r.status_code == 201 and r.json()["trabajo"]["tipo"] == "RETIRO"
    assert _eventos(super_engine, "GUIA_RETIRO_REINTENTADO", d["id"], ahora)
    # Con el almacén sano, el nuevo RETIRO termina y ya no se puede reintentar.
    almacen = AlmacenMemoria()
    almacen.registros = falla.registros
    procesar_pendientes(_indexador(engine_indexador, almacen), carpetas[0], una_vez=True)
    assert [(t.tipo, t.estado) for t in _trabajos(super_engine, d["id"])] == [("RETIRO", "ERROR"), ("RETIRO", "COMPLETADO")]
    r = cliente.post(f"{URL}/{d['id']}/reintentar", headers=cabeceras(ADMIN))
    assert r.status_code == 409 and r.json()["detail"] == srv.MENSAJE_OBSOLETA


def test_no_se_reindexa_ni_se_reintenta_la_indexacion_de_una_obsoleta(
        cliente, cabeceras, super_engine, guias_f, engine_indexador, carpetas):  # noqa: F811
    d = guias_f(nivel=2)
    assert _retirar(cliente, cabeceras, d["id"]).status_code == 201
    with super_engine.begin() as c:  # el retiro terminó y la indexación quedó en ERROR
        c.execute(text("UPDATE conocimiento.trabajo_indexacion SET estado = 'COMPLETADO', fecha_fin = now() "
                       "WHERE id_documento = :id"), {"id": d["id"]})
        c.execute(text("UPDATE conocimiento.documento_fuente SET estado_indexacion = 'ERROR' WHERE id_documento = :id"),
                  {"id": d["id"]})
    r = cliente.post(f"{URL}/{d['id']}/reintentar", headers=cabeceras(ADMIN))
    assert r.status_code == 409 and r.json()["detail"] == srv.MENSAJE_OBSOLETA
    # Defensa del trabajador: una indexación de una obsoleta que llegue a la cola termina en ERROR.
    with super_engine.begin() as c:
        c.execute(text("INSERT INTO conocimiento.trabajo_indexacion (id_documento, tipo, estado, solicitado_por) "
                       "VALUES (:d, 'REINDEXACION', 'PENDIENTE', :u)"), {"d": d["id"], "u": USUARIO_SISTEMA})
    procesar_pendientes(_indexador(engine_indexador, AlmacenMemoria()), carpetas[0], una_vez=True)
    assert _trabajos(super_engine, d["id"])[-1][1:] == ("ERROR", MENSAJE_OBSOLETA)


# ---------------------------------------------------------------------------
# Recuperación, consultas anteriores y huella (guías sintéticas de la fixture guia)
# ---------------------------------------------------------------------------
@pytest.fixture
def guia_retirable(guia, super_engine):  # noqa: F811
    """La guía PRUEBA-C-MINSA de la fixture guia. Al final borra sus trabajos (los de retiro), antes
    de que la fixture guia borre la guía."""
    with super_engine.connect() as c:
        id_doc = c.execute(text("SELECT id_documento::text FROM conocimiento.documento_fuente "
                                "WHERE id_documento = ANY(CAST(:ids AS uuid[])) AND codigo_documento = 'PRUEBA-C-MINSA'"),
                           {"ids": [x["id_documento"] for x in guia["docs"]]}).scalar_one()
    datos = next(x for x in guia["docs"] if x["id_documento"] == id_doc)
    yield {"id": id_doc, "codigo": "PRUEBA-C-MINSA", "fragmentos": datos["ids"], "almacen": guia["almacen"]}
    with super_engine.begin() as c:
        c.execute(text("DELETE FROM conocimiento.trabajo_indexacion WHERE id_documento = :id"), {"id": id_doc})


def test_una_guia_retirada_no_se_recupera_por_ninguna_via(cliente, cabeceras, super_engine, guia_retirable,
                                                          engine_generacion):  # noqa: F811
    g = guia_retirable
    cache = CacheBM25()
    regla = ReglaPuntero("prueba-f", "PRUEBA-C-OMS", re.compile("x"), g["codigo"], "Sección 3")
    with engine_generacion.connect() as c:
        antes = cache.obtener(c)
        assert any(i in g["fragmentos"] for i, _ in antes.buscar(TERMINOS, 50))
        assert set(comprobar_fragmentos(c, g["fragmentos"])) == set(g["fragmentos"])
        assert buscar_destino(c, regla) is not None
    assert _retirar(cliente, cabeceras, g["id"], confirmacion=g["codigo"]).status_code == 201
    with engine_generacion.connect() as c:
        # BM25: la caché cambia de huella y se reconstruye sola, sin reiniciar.
        despues = cache.obtener(c)
        assert cache.reconstrucciones == 2
        assert not any(i in g["fragmentos"] for i, _ in despues.buscar(TERMINOS, 50))
        # Vectorial: ChromaDB aún tiene el metadato viejo (el RETIRO no corrió) y los devuelve...
        vector = EmbedderFalso().embeber(["sulfato ferroso"])[0]
        assert {m["estado_documento"] for m in g["almacen"].metadatos_de_documento(g["id"]).values()} == {"VIGENTE"}
        assert any(i in g["fragmentos"] for i, _ in g["almacen"].consultar(vector, 50, FILTRO_VECTORIAL))
        # ...pero la comprobación final contra PostgreSQL los descarta.
        assert comprobar_fragmentos(c, g["fragmentos"]) == {}
        # Punteros: el destino retirado ya no se agrega.
        assert buscar_destino(c, regla) is None


def test_una_consulta_nueva_no_cita_la_guia_retirada(cliente, cabeceras, super_engine, guia_retirable, cliente_http,
                                                     consultas_d2, usar_entorno):  # noqa: F811
    g = guia_retirable
    assert _retirar(cliente, cabeceras, g["id"], confirmacion=g["codigo"]).status_code == 201
    _, eventos = _caso_http(cliente_http, cabeceras, consultas_d2, super_engine, usar_entorno, "i")
    fin = eventos[-1]
    with super_engine.connect() as c:
        usados = {r[0] for r in c.execute(text(
            """SELECT fr.id_fragmento::text FROM asistencia.fragmento_recuperado fr
                 JOIN asistencia.intento_generacion i ON i.id_intento = fr.id_intento
                WHERE i.id_consulta = CAST(:c AS uuid)"""), {"c": fin["id_consulta"]})}
    assert not usados & set(g["fragmentos"])
    assert all(cita.get("fuente") != g["codigo"] for cita in fin.get("citas") or [])


def test_las_consultas_anteriores_conservan_sus_citas(cliente, cabeceras, super_engine, guia_retirable, cliente_http,
                                                      consultas_d2, usar_entorno):  # noqa: F811
    g = guia_retirable
    _, eventos = _caso_http(cliente_http, cabeceras, consultas_d2, super_engine, usar_entorno, "i")
    fin = eventos[-1]
    assert fin["estado"] == "VERIFICADA"
    id_consulta = fin["id_consulta"]
    medico = cabeceras("med.salazar")
    antes = cliente_http.get(f"/api/consultas/{id_consulta}", headers=medico).json()
    citadas = [c for c in antes["citas"] if c["fuente"] == g["codigo"]]
    assert citadas, "La consulta de prueba debe citar la guía que se va a retirar"
    assert _retirar(cliente, cabeceras, g["id"], confirmacion=g["codigo"]).status_code == 201
    # M05: el resultado guardado conserva las citas.
    despues = cliente_http.get(f"/api/consultas/{id_consulta}", headers=medico).json()
    assert despues["citas"] == antes["citas"] and despues["estado"] == "VERIFICADA"
    # M08: la consulta sigue en el historial del paciente.
    id_paciente = despues["id_paciente"]
    lista = cliente_http.get(f"/api/pacientes/{id_paciente}/consultas", headers=medico).json()
    assert any(x["id_consulta"] == id_consulta and x["estado"] == "VERIFICADA" for x in lista)
    # M09: la vista previa del reporte trae las citas de la guía retirada.
    vista = cliente_http.get(f"/api/consultas/{id_consulta}/reportes/vista-previa?destino=EXPEDIENTE&secciones=EVIDENCIAS",
                            headers=medico)
    assert vista.status_code == 200 and g["codigo"] in vista.text
    # M13: el detalle de auditoría conserva los fragmentos con su documento.
    auditoria = cliente_http.get(f"/api/auditoria/consultas/{id_consulta}", headers=cabeceras("coord.ortiz"))
    assert auditoria.status_code == 200 and g["codigo"] in auditoria.text


def test_la_huella_de_configuracion_cambia_al_retirar(cliente, cabeceras, guia_retirable):
    g = guia_retirable
    antes = cliente.get("/api/parametros/huella", headers=cabeceras("coord.ortiz")).json()
    assert _retirar(cliente, cabeceras, g["id"], confirmacion=g["codigo"]).status_code == 201
    despues = cliente.get("/api/parametros/huella", headers=cabeceras("coord.ortiz")).json()
    assert despues["huella"] != antes["huella"]
    por_nombre = lambda h: {c["nombre"]: c["huella"] for c in h["componentes"]}  # noqa: E731
    cambiados = {k for k, v in por_nombre(despues).items() if por_nombre(antes)[k] != v}
    assert cambiados == {"indexacion"}


# ---------------------------------------------------------------------------
# Migración 017: coherencia del retiro
# ---------------------------------------------------------------------------
def test_migracion_017_es_idempotente_y_exige_datos_de_retiro_coherentes(super_engine, guias_f):
    from pathlib import Path
    sql = (Path(__file__).resolve().parents[2] / "db" / "migraciones" / "017_retiro_guias.sql").read_text(encoding="utf-8")
    for _ in range(2):
        with super_engine.begin() as c:
            c.connection.dbapi_connection.cursor().execute(sql)
    d = guias_f(nivel=2)
    for cambio in ("estado = 'OBSOLETA'",
                   "estado = 'OBSOLETA', retirado_por = :u, fecha_retiro = now(), motivo_retiro = 'corto'",
                   "motivo_retiro = 'Motivo sin estado obsoleto'"):
        with pytest.raises(Exception, match="ck_documento_fuente_retiro"):
            with super_engine.begin() as c:
                c.execute(text(f"UPDATE conocimiento.documento_fuente SET {cambio} WHERE id_documento = :id"),
                          {"id": d["id"], "u": USUARIO_SISTEMA})
    _sin_cambios(super_engine, d["id"])
