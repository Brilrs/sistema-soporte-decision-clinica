"""HU12 · Rutas de la base de conocimiento (M11, parte F2b): permisos, validaciones de la subida en
su orden, filas y archivo creados, límite de trabajos activos, auditoría sin contenido, lista,
detalle y reintento. Los documentos se crean en la base de pruebas y se borran al final con la
conexión de administración; los PDF van a una carpeta temporal (CDSS_DIR_GUIAS_CARGADAS de la
prueba). La auditoría se conserva: la bitácora es inmutable."""
import json
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from app.main import app
from app.services import conocimiento as srv
from tests.test_indexador_flujo import _citar

URL = "/api/conocimiento/documentos"
ADMIN = "admin.cdss"
ROLES_SIN_PERMISO = ["enf.rojas", "med.salazar", "nut.vilca", "coord.ortiz"]
MAX_PRUEBA = 4096


def pdf(n: int = 600) -> bytes:
    """Bytes que empiezan con la firma %PDF- y son distintos en cada llamada (otro SHA-256).
    La API no interpreta el PDF: eso lo hace el indexador."""
    cuerpo = f"%PDF-1.4\n% {uuid.uuid4()}\n".encode()
    return cuerpo + b"0" * max(0, n - len(cuerpo))


def metadatos(**cambios) -> dict:
    base = {"titulo": "Guía metodológica de prueba", "codigo_documento": "PRUEBA-F2B", "entidad_emisora": "OTRA",
            "tipo_documento": "LITERATURA", "anio_publicacion": "2024", "idioma": "es", "nivel": "2"}
    base.update(cambios)
    return {k: v for k, v in base.items() if v is not None}


@pytest.fixture
def carpeta(tmp_path, monkeypatch):
    destino = tmp_path / "guias_cargadas"
    monkeypatch.setattr(srv, "parametros_subida", lambda: srv.ParametrosSubida(destino, MAX_PRUEBA))
    return destino


def _borrar_documentos(super_engine, ids):
    with super_engine.begin() as c:
        for id_doc in ids:
            p = {"id": id_doc}
            frag = "SELECT id_fragmento FROM conocimiento.fragmento WHERE id_documento = :id"
            intentos = f"SELECT id_intento FROM asistencia.fragmento_recuperado WHERE id_fragmento IN ({frag})"
            consultas = f"SELECT id_consulta FROM asistencia.intento_generacion WHERE id_intento IN ({intentos})"
            c.execute(text(f"DELETE FROM asistencia.cita_evidencia WHERE id_fragmento IN ({frag})"), p)
            c.execute(text(f"DELETE FROM asistencia.recomendacion WHERE id_intento IN ({intentos})"), p)
            ids_consultas = [r[0] for r in c.execute(text(consultas), p)]
            c.execute(text(f"DELETE FROM asistencia.fragmento_recuperado WHERE id_fragmento IN ({frag})"), p)
            for idc in ids_consultas:
                c.execute(text("DELETE FROM asistencia.intento_generacion WHERE id_consulta = :c"), {"c": idc})
                c.execute(text("DELETE FROM asistencia.consulta WHERE id_consulta = :c"), {"c": idc})
            c.execute(text("DELETE FROM conocimiento.fragmento WHERE id_documento = :id"), p)
            c.execute(text("DELETE FROM conocimiento.trabajo_indexacion WHERE id_documento = :id"), p)
            c.execute(text("DELETE FROM conocimiento.documento_fuente WHERE id_documento = :id"), p)


@pytest.fixture
def creados(super_engine):
    """Documentos que crea cada prueba. Exige una cola vacía al empezar (el límite de trabajos
    activos lo necesita) y al final borra todo lo creado, aunque la prueba falle."""
    with super_engine.connect() as c:
        activos = c.execute(text("SELECT count(*) FROM conocimiento.trabajo_indexacion "
                                 "WHERE estado IN ('PENDIENTE','EN_CURSO')")).scalar()
    assert activos == 0, "La base de pruebas tiene trabajos activos de otra prueba"
    ids: list[str] = []
    yield ids
    with super_engine.connect() as c:
        ids += [r[0] for r in c.execute(text(
            "SELECT id_documento::text FROM conocimiento.documento_fuente WHERE codigo_documento LIKE 'PRUEBA-F2B%'"))]
    _borrar_documentos(super_engine, set(ids))


def subir(cliente, cabeceras, contenido: bytes | None = None, nombre="guia.pdf", usuario=ADMIN, **cambios):
    contenido = pdf() if contenido is None else contenido
    return cliente.post(URL, headers=cabeceras(usuario), data=metadatos(**cambios),
                        files={"archivo": (nombre, contenido, "application/pdf")})


def _cargar(cliente, cabeceras, creados, **cambios) -> dict:
    r = subir(cliente, cabeceras, **cambios)
    assert r.status_code == 201, r.text
    creados.append(r.json()["documento"]["id_documento"])
    return r.json()


def _eventos(super_engine, tipo: str, desde) -> list[dict]:
    with super_engine.connect() as c:
        return [dict(f._mapping) for f in c.execute(text(
            """SELECT e.entidad, e.id_entidad, e.detalle FROM auditoria.evento_auditoria e
                JOIN seguridad.usuario u ON u.id_usuario = e.id_usuario
               WHERE e.tipo_evento = :t AND e.fecha_hora >= :d AND u.nombre_usuario = :a ORDER BY e.id_evento"""),
            {"t": tipo, "d": desde, "a": ADMIN})]


@pytest.fixture
def ahora(super_engine):
    with super_engine.connect() as c:
        return c.execute(text("SELECT clock_timestamp()")).scalar()


def _archivos(carpeta) -> list[str]:
    return sorted(p.name for p in carpeta.iterdir()) if carpeta.exists() else []


# ---------------------------------------------------------------------------
# Permisos
# ---------------------------------------------------------------------------
RUTAS = [("get", URL), ("post", URL), ("get", "/api/conocimiento/trabajos?activos=true"),
         ("get", f"{URL}/{uuid.uuid4()}"), ("post", f"{URL}/{uuid.uuid4()}/reintentar")]


@pytest.mark.parametrize("metodo,ruta", RUTAS)
def test_sin_sesion_responde_401(cliente, metodo, ruta):
    assert getattr(cliente, metodo)(ruta).status_code == 401


@pytest.mark.parametrize("usuario", ROLES_SIN_PERMISO)
@pytest.mark.parametrize("metodo,ruta", RUTAS)
def test_roles_sin_administrar_guias_reciben_403(cliente, cabeceras, carpeta, creados, usuario, metodo, ruta):
    kwargs = {"files": {"archivo": ("guia.pdf", pdf(), "application/pdf")}, "data": metadatos()} \
        if (metodo, ruta) == ("post", URL) else {}
    r = getattr(cliente, metodo)(ruta, headers=cabeceras(usuario), **kwargs)
    assert r.status_code == 403
    assert _archivos(carpeta) == []


# ---------------------------------------------------------------------------
# Validaciones de la subida, en su orden
# ---------------------------------------------------------------------------
def test_extension_distinta_de_pdf_responde_415(cliente, cabeceras, carpeta, creados, super_engine, ahora):
    r = subir(cliente, cabeceras, nombre="guia.docx")
    assert r.status_code == 415 and ".pdf" in r.json()["detail"]
    assert _archivos(carpeta) == []
    assert [e["detalle"] for e in _eventos(super_engine, "GUIA_CARGA_RECHAZADA", ahora)] == [{"motivo": "no_es_pdf"}]


def test_extension_pdf_sin_firma_responde_415(cliente, cabeceras, carpeta, creados):
    r = subir(cliente, cabeceras, contenido=b"<html>no soy un PDF</html>" * 10)
    assert r.status_code == 415 and "%PDF-" in r.json()["detail"]
    assert _archivos(carpeta) == []


def test_la_extension_se_comprueba_antes_que_la_firma(cliente, cabeceras, carpeta, creados):
    """Con la extensión y la firma incorrectas, el mensaje es el de la extensión."""
    r = subir(cliente, cabeceras, contenido=b"texto plano, sin firma", nombre="guia.txt")
    assert r.status_code == 415 and ".pdf" in r.json()["detail"]


def test_tamano_maximo_cortado_mientras_se_lee_responde_413(cliente, cabeceras, carpeta, creados, super_engine, ahora):
    r = subir(cliente, cabeceras, contenido=pdf(MAX_PRUEBA + 1))
    assert r.status_code == 413 and "máximo" in r.json()["detail"]
    assert _archivos(carpeta) == [], "el temporal debe borrarse"
    assert [e["detalle"] for e in _eventos(super_engine, "GUIA_CARGA_RECHAZADA", ahora)] == [
        {"motivo": "tamano", "max_bytes": MAX_PRUEBA}]


def test_un_archivo_del_tamano_maximo_exacto_se_acepta(cliente, cabeceras, carpeta, creados):
    _cargar(cliente, cabeceras, creados, contenido=pdf(MAX_PRUEBA))


def test_corte_de_tamano_sin_leer_el_resto(tmp_path):
    """recibir_pdf deja de leer al pasar el máximo: no consume el archivo entero."""
    leidos = []

    class Origen:
        def __init__(self):
            self.datos = pdf(10 * srv.BLOQUE)

        def read(self, n):
            bloque, self.datos = self.datos[:n], self.datos[n:]
            leidos.append(len(bloque))
            return bloque

    with pytest.raises(srv.ErrorGuia) as e:
        srv.recibir_pdf("g.pdf", Origen(), srv.ParametrosSubida(tmp_path, 2 * srv.BLOQUE))
    assert e.value.codigo == 413 and sum(leidos) <= 3 * srv.BLOQUE + len(srv.FIRMA_PDF)
    assert list(tmp_path.iterdir()) == []


def test_mismo_archivo_responde_409_con_el_titulo_existente(cliente, cabeceras, carpeta, creados, super_engine, ahora):
    contenido = pdf()
    primero = _cargar(cliente, cabeceras, creados, contenido=contenido, titulo="Guía original de prueba")
    r = subir(cliente, cabeceras, contenido=contenido, titulo="Otra guía")
    assert r.status_code == 409 and "«Guía original de prueba»" in r.json()["detail"]
    assert _archivos(carpeta) == [f"{primero['documento']['id_documento']}.pdf"]
    assert [e["detalle"] for e in _eventos(super_engine, "GUIA_CARGA_RECHAZADA", ahora)] == [
        {"motivo": "duplicado", "id_documento_existente": primero["documento"]["id_documento"]}]


@pytest.mark.parametrize("cambios,campo", [
    ({"titulo": ""}, "titulo"),
    ({"titulo": None}, "titulo"),
    ({"entidad_emisora": "UNICEF"}, "entidad_emisora"),
    ({"tipo_documento": "ARTICULO"}, "tipo_documento"),
    ({"idioma": "fr"}, "idioma"),
    ({"anio_publicacion": "dos mil"}, "anio_publicacion"),
    ({"anio_publicacion": "2999"}, "anio_publicacion"),
    ({"nivel": "3"}, "nivel"),
    ({"codigo_documento": "X" * 81}, "codigo_documento"),
    ({"pagina_inicio_cuerpo": "0", "pagina_fin_cuerpo": "4"}, "pagina_inicio_cuerpo"),
    ({"pagina_inicio_cuerpo": "5", "pagina_fin_cuerpo": "4"}, "mayor"),
    ({"pagina_inicio_cuerpo": "5"}, "ninguna"),
    ({"campo_extra": "x"}, "campo_extra"),
])
def test_metadatos_no_validos_responden_422(cliente, cabeceras, carpeta, creados, cambios, campo):
    r = subir(cliente, cabeceras, **cambios)
    assert r.status_code == 422, r.text
    assert r.json()["detail"].startswith("Metadatos no válidos") and campo in r.json()["detail"]
    assert _archivos(carpeta) == []


def test_nivel_1_responde_422_con_el_mensaje_de_la_linea_de_comandos(cliente, cabeceras, carpeta, creados,
                                                                       super_engine, ahora):
    r = subir(cliente, cabeceras, nivel="1")
    assert r.status_code == 422 and r.json()["detail"] == srv.MENSAJE_NIVEL_1
    assert _archivos(carpeta) == []
    assert [e["detalle"] for e in _eventos(super_engine, "GUIA_CARGA_RECHAZADA", ahora)] == [
        {"motivo": "nivel", "nivel": 1}]


def test_el_duplicado_se_comprueba_antes_que_los_metadatos_y_el_nivel(cliente, cabeceras, carpeta, creados):
    contenido = pdf()
    _cargar(cliente, cabeceras, creados, contenido=contenido)
    assert subir(cliente, cabeceras, contenido=contenido, nivel="1", idioma="fr").status_code == 409


# ---------------------------------------------------------------------------
# Subida correcta
# ---------------------------------------------------------------------------
def test_subida_crea_documento_trabajo_archivo_y_auditoria(cliente, cabeceras, carpeta, creados, super_engine, ahora):
    contenido = pdf(2000)
    r = _cargar(cliente, cabeceras, creados, contenido=contenido, nombre="../../etc/passwd.pdf",
                pagina_inicio_cuerpo="2", pagina_fin_cuerpo="3")
    doc, trabajo = r["documento"], r["trabajo"]
    assert doc["nivel"] == 2 and doc["estado"] == "VIGENTE" and doc["estado_indexacion"] == "PENDIENTE"
    assert doc["fragmentos_vigentes"] == 0 and doc["citas_30_dias"] == 0 and doc["version_indexacion"] is None
    assert trabajo["tipo"] == "INDEXACION" and trabajo["estado"] == "PENDIENTE"
    assert doc["ultimo_trabajo"]["id_trabajo"] == trabajo["id_trabajo"]
    # El archivo se guarda con el id del documento, nunca con el nombre enviado.
    assert _archivos(carpeta) == [f"{doc['id_documento']}.pdf"]
    assert (carpeta / f"{doc['id_documento']}.pdf").read_bytes() == contenido
    with super_engine.connect() as c:
        fila = c.execute(text(
            """SELECT d.ruta_blob, d.hash_archivo, d.pagina_inicio_cuerpo, d.pagina_fin_cuerpo, u.nombre_usuario
                 FROM conocimiento.documento_fuente d JOIN seguridad.usuario u ON u.id_usuario = d.cargado_por
                WHERE d.id_documento = :id"""), {"id": doc["id_documento"]}).one()
    import hashlib
    assert fila.ruta_blob == f"local://guias_cargadas/{doc['id_documento']}.pdf"
    assert fila.hash_archivo == hashlib.sha256(contenido).hexdigest()
    assert (fila.pagina_inicio_cuerpo, fila.pagina_fin_cuerpo, fila.nombre_usuario) == (2, 3, ADMIN)
    # Ninguna respuesta lleva rutas del servidor.
    assert "guias_cargadas" not in json.dumps(r) and "ruta" not in json.dumps(r)
    eventos = _eventos(super_engine, "GUIA_CARGADA", ahora)
    assert len(eventos) == 1 and eventos[0]["entidad"] == "documento_fuente"
    assert eventos[0]["id_entidad"] == doc["id_documento"]
    assert eventos[0]["detalle"] == {
        "id_documento": doc["id_documento"], "nivel": 2, "tipo_documento": "LITERATURA", "entidad_emisora": "OTRA",
        "anio_publicacion": 2024, "idioma": "es", "tamano_bytes": 2000, "sha256": fila.hash_archivo}


def test_fallo_de_la_base_al_insertar_no_deja_archivo(cliente, cabeceras, carpeta, creados, monkeypatch, super_engine):
    def falla(*a, **k):
        raise OperationalError("INSERT", {}, Exception("la base no responde"))
    monkeypatch.setattr(srv, "insertar_documento", falla)
    r = TestClient(app, raise_server_exceptions=False).post(
        URL, headers=cabeceras(ADMIN), data=metadatos(), files={"archivo": ("g.pdf", pdf(), "application/pdf")})
    assert r.status_code == 500 and "base no responde" not in r.text and "Traceback" not in r.text
    assert _archivos(carpeta) == []


def test_fallo_del_commit_despues_de_mover_no_deja_archivo(cliente, cabeceras, carpeta, creados, monkeypatch,
                                                           super_engine):
    """El archivo se renombra antes del commit; si el commit falla, se borra y no queda documento."""
    from sqlalchemy.orm import Session
    original = Session.commit

    def commit(self):
        if any(p.suffix == ".pdf" for p in carpeta.iterdir()):
            raise OperationalError("COMMIT", {}, Exception("conexión perdida"))
        return original(self)
    monkeypatch.setattr(Session, "commit", commit)
    titulo = f"Guía de commit fallido {uuid.uuid4()}"
    r = TestClient(app, raise_server_exceptions=False).post(
        URL, headers=cabeceras(ADMIN), data=metadatos(titulo=titulo),
        files={"archivo": ("g.pdf", pdf(), "application/pdf")})
    monkeypatch.setattr(Session, "commit", original)
    assert r.status_code == 500 and "conexión perdida" not in r.text
    assert _archivos(carpeta) == []
    with super_engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM conocimiento.documento_fuente WHERE titulo = :t"),
                         {"t": titulo}).scalar() == 0


def test_limite_de_dos_trabajos_activos(cliente, cabeceras, carpeta, creados, super_engine):
    _cargar(cliente, cabeceras, creados)
    _cargar(cliente, cabeceras, creados)
    r = subir(cliente, cabeceras)
    assert r.status_code == 409 and r.json()["detail"] == srv.MENSAJE_ACTIVOS
    assert len(_archivos(carpeta)) == 2
    # Al terminar uno, se puede cargar otro.
    with super_engine.begin() as c:
        c.execute(text("""UPDATE conocimiento.trabajo_indexacion SET estado = 'COMPLETADO', fecha_fin = now()
                           WHERE id_documento = :id"""), {"id": creados[0]})
    _cargar(cliente, cabeceras, creados)


def test_limite_se_comprueba_dentro_de_la_transaccion(carpeta, monkeypatch, cliente, cabeceras, creados):
    """Si otra subida llena la cola mientras se recibe el archivo, la segunda comprobación
    (con el candado) la rechaza y no deja archivo."""
    llamadas = {"n": 0}
    original = srv.comprobar_capacidad

    def segunda_falla(sesion):
        llamadas["n"] += 1
        if llamadas["n"] == 2:
            raise srv.ErrorGuia(409, srv.MENSAJE_ACTIVOS)
        original(sesion)
    monkeypatch.setattr(srv, "comprobar_capacidad", segunda_falla)
    assert subir(cliente, cabeceras).status_code == 409 and llamadas["n"] == 2
    assert _archivos(carpeta) == []


# ---------------------------------------------------------------------------
# Lectura
# ---------------------------------------------------------------------------
_orden = {"n": 0}


def _con_fragmento(super_engine, id_doc: str, version: int, vigente: bool = True) -> str:
    _orden["n"] += 1
    with super_engine.begin() as c:
        return c.execute(text(
            """INSERT INTO conocimiento.fragmento (id_documento, numero_orden, texto, numero_tokens, modelo_embedding,
                 version_indexacion, vigente, motivo_exclusion)
               VALUES (:d, :o, 'texto de prueba', 3, 'bge-m3', :v, :vig, CASE WHEN :vig THEN NULL ELSE 'Reemplazado' END)
               RETURNING id_fragmento::text"""),
            {"d": id_doc, "o": _orden["n"], "v": version, "vig": vigente}).scalar()


def test_lista_con_citas_versiones_y_orden_estable(cliente, cabeceras, carpeta, creados, super_engine):
    doc = _cargar(cliente, cabeceras, creados)["documento"]["id_documento"]
    _con_fragmento(super_engine, doc, 1, vigente=False)
    citado = _con_fragmento(super_engine, doc, 2)
    _con_fragmento(super_engine, doc, 2)
    _citar(super_engine, citado)
    _citar(super_engine, citado)
    r = cliente.get(URL, headers=cabeceras(ADMIN))
    assert r.status_code == 200
    lista = r.json()
    fila = next(d for d in lista if d["id_documento"] == doc)
    assert (fila["fragmentos_vigentes"], fila["citas_30_dias"], fila["version_indexacion"]) == (2, 2, 2)
    assert fila["version"] is None and fila["ultimo_trabajo"]["estado"] == "PENDIENTE"
    assert lista == sorted(lista, key=srv.clave_orden)  # orden propio, independiente de la colación
    titulos = [d["titulo"] for d in lista]
    norma = next(t for t in titulos if t.startswith("Norma técnica de salud"))
    nts = next(t for t in titulos if t.startswith("NTS 213"))
    assert titulos.index(norma) < titulos.index(nts)  # sin distinguir mayúsculas, con cualquier colación
    assert cliente.get(URL, headers=cabeceras(ADMIN)).json() == lista
    assert "ruta" not in r.text and "guias_cargadas" not in r.text


def test_las_citas_de_consultas_de_prueba_no_se_cuentan(cliente, cabeceras, carpeta, creados, super_engine):
    doc = _cargar(cliente, cabeceras, creados)["documento"]["id_documento"]
    citado = _con_fragmento(super_engine, doc, 1)
    _citar(super_engine, citado)
    with super_engine.begin() as c:
        c.execute(text("""UPDATE asistencia.intento_generacion SET modelo_llm = 'modelo-falso'
                           WHERE id_intento IN (SELECT id_intento FROM asistencia.fragmento_recuperado
                                                 WHERE id_fragmento = :f)"""), {"f": citado})
    fila = next(d for d in cliente.get(URL, headers=cabeceras(ADMIN)).json() if d["id_documento"] == doc)
    assert fila["citas_30_dias"] == 0


def test_detalle_con_versiones_trabajos_y_quien_cargo(cliente, cabeceras, carpeta, creados, super_engine):
    doc = _cargar(cliente, cabeceras, creados, pagina_inicio_cuerpo="1", pagina_fin_cuerpo="9")["documento"]
    _con_fragmento(super_engine, doc["id_documento"], 1, vigente=False)
    _con_fragmento(super_engine, doc["id_documento"], 2)
    r = cliente.get(f"{URL}/{doc['id_documento']}", headers=cabeceras(ADMIN))
    assert r.status_code == 200
    d = r.json()
    assert d["versiones"] == [
        {"version_indexacion": 2, "fragmentos": 1, "vigentes": 1, "modelo_embedding": "bge-m3"},
        {"version_indexacion": 1, "fragmentos": 1, "vigentes": 0, "modelo_embedding": "bge-m3"}]
    assert [t["tipo"] for t in d["trabajos"]] == ["INDEXACION"]
    assert d["cargado_por"] and d["cargado_por"] != ADMIN  # nombre completo, no el usuario
    assert (d["pagina_inicio_cuerpo"], d["pagina_fin_cuerpo"]) == (1, 9) and len(d["hash_archivo"]) == 64
    assert "ruta" not in r.text and "guias_cargadas" not in r.text


def test_detalle_de_un_documento_inexistente_responde_404(cliente, cabeceras):
    assert cliente.get(f"{URL}/{uuid.uuid4()}", headers=cabeceras(ADMIN)).status_code == 404


def test_trabajos_activos(cliente, cabeceras, carpeta, creados, super_engine):
    a = _cargar(cliente, cabeceras, creados)
    b = _cargar(cliente, cabeceras, creados)
    with super_engine.begin() as c:
        c.execute(text("""UPDATE conocimiento.trabajo_indexacion SET estado = 'EN_CURSO', etapa = 'EMBEDDINGS',
                            procesados = 8, total = 40, fecha_inicio = now() WHERE id_trabajo = :t"""),
                  {"t": a["trabajo"]["id_trabajo"]})
        c.execute(text("""UPDATE conocimiento.trabajo_indexacion SET estado = 'ERROR', mensaje_error = 'falló',
                            fecha_fin = now() WHERE id_trabajo = :t"""), {"t": b["trabajo"]["id_trabajo"]})
    activos = cliente.get("/api/conocimiento/trabajos?activos=true", headers=cabeceras(ADMIN)).json()
    assert [(t["id_documento"], t["estado"], t["etapa"], t["procesados"], t["total"]) for t in activos] == [
        (a["documento"]["id_documento"], "EN_CURSO", "EMBEDDINGS", 8, 40)]
    assert activos[0]["titulo"] == "Guía metodológica de prueba"
    todos = cliente.get("/api/conocimiento/trabajos", headers=cabeceras(ADMIN)).json()
    assert {b["trabajo"]["id_trabajo"], a["trabajo"]["id_trabajo"]} <= {t["id_trabajo"] for t in todos}


# ---------------------------------------------------------------------------
# Reintento
# ---------------------------------------------------------------------------
def _en_error(super_engine, id_doc: str) -> None:
    with super_engine.begin() as c:
        c.execute(text("""UPDATE conocimiento.trabajo_indexacion SET estado = 'ERROR', mensaje_error = 'falló',
                            fecha_fin = now() WHERE id_documento = :id AND estado IN ('PENDIENTE','EN_CURSO')"""),
                  {"id": id_doc})
        c.execute(text("UPDATE conocimiento.documento_fuente SET estado_indexacion = 'ERROR' WHERE id_documento = :id"),
                  {"id": id_doc})


@pytest.mark.parametrize("con_fragmentos,tipo", [(False, "INDEXACION"), (True, "REINDEXACION")])
def test_reintentar_un_documento_en_error(cliente, cabeceras, carpeta, creados, super_engine, ahora,
                                          con_fragmentos, tipo):
    doc = _cargar(cliente, cabeceras, creados)["documento"]["id_documento"]
    _en_error(super_engine, doc)
    if con_fragmentos:
        _con_fragmento(super_engine, doc, 1)
    r = cliente.post(f"{URL}/{doc}/reintentar", headers=cabeceras(ADMIN))
    assert r.status_code == 201, r.text
    assert (r.json()["trabajo"]["tipo"], r.json()["trabajo"]["estado"]) == (tipo, "PENDIENTE")
    detalle = cliente.get(f"{URL}/{doc}", headers=cabeceras(ADMIN)).json()
    assert detalle["estado_indexacion"] == "PENDIENTE" and len(detalle["trabajos"]) == 2
    eventos = _eventos(super_engine, "GUIA_REINDEXACION_SOLICITADA", ahora)
    assert [(e["id_entidad"], e["detalle"]) for e in eventos] == [
        (doc, {"id_trabajo": r.json()["trabajo"]["id_trabajo"], "tipo": tipo})]
    # Ya tiene un trabajo activo: otro reintento responde 409.
    assert cliente.post(f"{URL}/{doc}/reintentar", headers=cabeceras(ADMIN)).status_code == 409


@pytest.mark.parametrize("estado", ["PENDIENTE", "COMPLETADA"])
def test_reintentar_fuera_de_error_responde_409(cliente, cabeceras, carpeta, creados, super_engine, estado):
    doc = _cargar(cliente, cabeceras, creados)["documento"]["id_documento"]
    if estado == "COMPLETADA":
        with super_engine.begin() as c:
            c.execute(text("""UPDATE conocimiento.trabajo_indexacion SET estado = 'COMPLETADO', fecha_fin = now()
                               WHERE id_documento = :id"""), {"id": doc})
            c.execute(text("""UPDATE conocimiento.documento_fuente SET estado_indexacion = 'COMPLETADA'
                               WHERE id_documento = :id"""), {"id": doc})
    r = cliente.post(f"{URL}/{doc}/reintentar", headers=cabeceras(ADMIN))
    assert r.status_code == 409


def test_reintentar_con_un_trabajo_activo_responde_409_aunque_el_documento_este_en_error(
        cliente, cabeceras, carpeta, creados, super_engine):
    """Documento en ERROR con su trabajo todavía PENDIENTE (p. ej., un reintento ya pedido)."""
    doc = _cargar(cliente, cabeceras, creados)["documento"]["id_documento"]
    with super_engine.begin() as c:
        c.execute(text("UPDATE conocimiento.documento_fuente SET estado_indexacion = 'ERROR' WHERE id_documento = :id"),
                  {"id": doc})
    r = cliente.post(f"{URL}/{doc}/reintentar", headers=cabeceras(ADMIN))
    assert r.status_code == 409 and "pendiente o en curso" in r.json()["detail"]


def test_reintentar_respeta_el_limite_de_trabajos_activos(cliente, cabeceras, carpeta, creados, super_engine):
    fallido = _cargar(cliente, cabeceras, creados)["documento"]["id_documento"]
    _en_error(super_engine, fallido)
    _cargar(cliente, cabeceras, creados)
    _cargar(cliente, cabeceras, creados)
    r = cliente.post(f"{URL}/{fallido}/reintentar", headers=cabeceras(ADMIN))
    assert r.status_code == 409 and r.json()["detail"] == srv.MENSAJE_ACTIVOS


def test_reintentar_un_documento_inexistente_responde_404(cliente, cabeceras):
    assert cliente.post(f"{URL}/{uuid.uuid4()}/reintentar", headers=cabeceras(ADMIN)).status_code == 404


# ---------------------------------------------------------------------------
# Auditoría y seguridad
# ---------------------------------------------------------------------------
def test_la_auditoria_no_guarda_titulo_ni_nombre_de_archivo(cliente, cabeceras, carpeta, creados, super_engine, ahora):
    titulo = f"Título que no debe auditarse {uuid.uuid4()}"
    _cargar(cliente, cabeceras, creados, titulo=titulo, nombre="nombre-secreto.pdf")
    subir(cliente, cabeceras, nivel="1", titulo=titulo, nombre="nombre-secreto.pdf")
    with super_engine.connect() as c:
        detalles = [r[0] for r in c.execute(text(
            "SELECT detalle::text FROM auditoria.evento_auditoria WHERE tipo_evento LIKE 'GUIA_%' AND fecha_hora >= :d"),
            {"d": ahora})]
    assert len(detalles) == 2
    assert not any(titulo in d or "nombre-secreto" in d or "guias_cargadas" in d or "%PDF" in d for d in detalles)


def test_cdss_admin_no_lee_datos_clinicos(super_engine):
    """La conexión de M11 no gana acceso a la identidad del paciente ni a los tamizajes."""
    from app.core.db import engines
    for tabla in ("clinico.paciente", "clinico.tamizaje"):
        with engines()["admin"].connect() as c, pytest.raises(Exception, match="permission denied|permiso denegado"):
            c.execute(text(f"SELECT 1 FROM {tabla} LIMIT 1"))
