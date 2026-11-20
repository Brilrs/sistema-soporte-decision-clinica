"""Sprint 3, parte Z: el 409 de un PDF ya cargado dice, si la guía existente está retirada (OBSOLETA), que
lo está, sin revelar nada más que el título. Mismo código HTTP, mismo motivo de auditoría (`duplicado`) y
mismo detalle (`id_documento_existente`) que antes. Cubre los dos sitios de la API (la comprobación previa
y la carrera entre dos subidas, que llega como IntegrityError) y el mensaje del indexador.

Documentos en la base de pruebas, borrados al final con la conexión de administración (fixture `creados`
de test_conocimiento_api). La guía se marca como retirada con UPDATE en la base de pruebas."""
import uuid

import pytest
from sqlalchemy import text

from app.indexador.repositorio import USUARIO_SISTEMA
from app.services import conocimiento as srv
from tests.test_conocimiento_api import (_archivos, _cargar, _eventos, ahora, carpeta, creados, pdf,  # noqa: F401
                                         subir)
from tests.test_indexador_flujo import _indexar, engine_indexador  # noqa: F401 (fixture)

TITULO = "Guía Z de prueba del duplicado"
MENSAJE_VIGENTE = f"Este archivo ya está cargado como «{TITULO}»"
MENSAJE_RETIRADA = f"Este archivo ya está cargado como «{TITULO}» y esa guía está retirada"
MOTIVO_RETIRO = "Retiro sintético de la parte Z"


def _retirar(super_engine, id_doc: str) -> None:
    with super_engine.begin() as c:
        c.execute(text(
            """UPDATE conocimiento.documento_fuente
                  SET estado = 'OBSOLETA', retirado_por = CAST(:u AS uuid), fecha_retiro = now(), motivo_retiro = :m
                WHERE id_documento = :id"""), {"id": id_doc, "u": USUARIO_SISTEMA, "m": MOTIVO_RETIRO})


@pytest.mark.parametrize("retirada, esperado", [(False, MENSAJE_VIGENTE), (True, MENSAJE_RETIRADA)])
def test_el_409_dice_si_la_guia_existente_esta_retirada(cliente, cabeceras, carpeta, creados, super_engine, ahora,
                                                        retirada, esperado):
    contenido = pdf()
    primero = _cargar(cliente, cabeceras, creados, contenido=contenido, titulo=TITULO, codigo_documento="PRUEBA-F2B-Z")
    id_doc = primero["documento"]["id_documento"]
    if retirada:
        _retirar(super_engine, id_doc)
    r = subir(cliente, cabeceras, contenido=contenido, titulo="Otra guía")
    assert r.status_code == 409
    # Mensaje exacto: solo el título y, si corresponde, que está retirada (ni el motivo, ni quién, ni cuándo).
    assert r.json() == {"detail": esperado}
    assert MOTIVO_RETIRO not in r.text and id_doc not in r.text
    # El motivo y el detalle de la auditoría no cambian
    assert [e["detalle"] for e in _eventos(super_engine, "GUIA_CARGA_RECHAZADA", ahora)] == [
        {"motivo": "duplicado", "id_documento_existente": id_doc}]
    assert _archivos(carpeta) == [f"{id_doc}.pdf"]


@pytest.mark.parametrize("retirada, esperado", [(False, MENSAJE_VIGENTE), (True, MENSAJE_RETIRADA)])
def test_la_carrera_entre_dos_subidas_da_el_mismo_mensaje(cliente, cabeceras, carpeta, creados, super_engine,
                                                         monkeypatch, retirada, esperado):
    """La comprobación previa no ve la otra subida (que gana entre la comprobación y el INSERT): el INSERT
    choca con la restricción única del SHA-256 y el 409 se arma con la guía que ganó."""
    contenido = pdf()
    primero = _cargar(cliente, cabeceras, creados, contenido=contenido, titulo=TITULO, codigo_documento="PRUEBA-F2B-Z")
    if retirada:
        _retirar(super_engine, primero["documento"]["id_documento"])
    original = srv.documento_con_hash
    llamadas = {"n": 0}

    def no_la_ve_la_primera_vez(sesion, sha256):
        llamadas["n"] += 1
        return None if llamadas["n"] == 1 else original(sesion, sha256)
    monkeypatch.setattr(srv, "documento_con_hash", no_la_ve_la_primera_vez)
    r = subir(cliente, cabeceras, contenido=contenido, titulo="Otra guía")
    assert r.status_code == 409 and r.json() == {"detail": esperado} and llamadas["n"] == 2
    assert _archivos(carpeta) == [f"{primero['documento']['id_documento']}.pdf"]  # el de la segunda se borró


def test_la_carrera_sin_guia_visible_conserva_el_mensaje_generico(cliente, cabeceras, carpeta, creados, monkeypatch):
    contenido = pdf()
    _cargar(cliente, cabeceras, creados, contenido=contenido, titulo=TITULO, codigo_documento="PRUEBA-F2B-Z")
    monkeypatch.setattr(srv, "documento_con_hash", lambda sesion, sha256: None)
    r = subir(cliente, cabeceras, contenido=contenido, titulo="Otra guía")
    assert r.status_code == 409 and r.json() == {"detail": "Este archivo ya está cargado"}


def test_el_mensaje_sigue_yendo_al_campo_del_archivo_en_m11():
    """M11 (`erroresDeLaApi` en textos.ts) ubica junto al archivo los 409 que contienen «ya está cargado»."""
    for existente in ({"titulo": TITULO, "estado": "VIGENTE"}, {"titulo": TITULO, "estado": "OBSOLETA"}):
        assert "ya está cargado" in srv.mensaje_duplicado(existente)
    assert srv.mensaje_duplicado({"titulo": TITULO, "estado": "VIGENTE"}) == MENSAJE_VIGENTE
    assert srv.mensaje_duplicado({"titulo": TITULO, "estado": "OBSOLETA"}) == MENSAJE_RETIRADA


# ---------------------------------------------------------------------------
# Indexador
# ---------------------------------------------------------------------------
@pytest.fixture
def dos_documentos(super_engine):
    ids = [str(uuid.uuid4()), str(uuid.uuid4())]
    with super_engine.begin() as c:
        for id_doc in ids:
            c.execute(text(
                """INSERT INTO conocimiento.documento_fuente
                     (id_documento, titulo, codigo_documento, entidad_emisora, tipo_documento, nivel, anio_publicacion,
                      idioma, cargado_por)
                   VALUES (:id, :t, 'PRUEBA-Z', 'OTRA', 'LITERATURA', 2, 2024, 'es', :u)"""),
                {"id": id_doc, "t": TITULO, "u": USUARIO_SISTEMA})
    yield ids
    with super_engine.begin() as c:
        for id_doc in ids:
            for tabla in ("fragmento", "trabajo_indexacion", "documento_fuente"):
                c.execute(text(f"DELETE FROM conocimiento.{tabla} WHERE id_documento = :id"), {"id": id_doc})


@pytest.mark.parametrize("retirada", [False, True])
def test_el_indexador_dice_si_el_documento_con_el_mismo_archivo_esta_retirado(engine_indexador, dos_documentos,
                                                                             super_engine, retirada):
    existente, nuevo = dos_documentos
    hash_archivo = uuid.uuid4().hex * 2
    with super_engine.begin() as c:
        c.execute(text("UPDATE conocimiento.documento_fuente SET hash_archivo = :h WHERE id_documento = :id"),
                  {"h": hash_archivo, "id": existente})
    if retirada:
        _retirar(super_engine, existente)
    resultado, _, almacen = _indexar(engine_indexador, nuevo, hash_archivo=hash_archivo)
    sufijo = ", que está retirado" if retirada else ""
    assert resultado.estado == "ERROR"
    assert resultado.mensaje == f"El archivo ya está cargado como el documento {existente}{sufijo}"
    assert almacen.registros == {}
