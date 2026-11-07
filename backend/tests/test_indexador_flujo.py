"""Flujo de indexación contra PostgreSQL con el usuario cdss_indexador, ChromaDB en
memoria y modelos falsos: consistencia entre ambos almacenes, compensación,
idempotencia por SHA-256, transcripciones sin verificar, avance en
trabajo_indexacion y reindexación por versiones."""
import os
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from app.indexador.config import FuenteDocumento
from app.indexador.extraccion import PaginaTexto
from app.indexador.indexacion import Indexador, Opciones
from app.indexador.repositorio import USUARIO_SISTEMA, Repositorio
from app.core.modelos import EmbedderFalso, TokenizadorFalso
from app.core.vectores import AlmacenMemoria

FRASE = "El establecimiento de salud brinda la suplementación preventiva con hierro según la edad y el peso."
PAGINAS = [
    PaginaTexto(1, ["V. DISPOSICIONES GENERALES", "5.1. Suplementación preventiva"] + [FRASE] * 40),
    PaginaTexto(2, ["5.2. Tratamiento"] + [FRASE.replace("preventiva", "terapéutica")] * 40
                + ["Tabla N° 7", "Dosis de prueba", "Edad Dosis", "12 a 23 meses 2 mg/kg/día", "Fuente: MINSA"]),
]


@pytest.fixture(scope="module")
def engine_indexador():
    url = os.environ.get("DATABASE_URL_INDEXADOR")
    if not url:
        pytest.fail("Falta DATABASE_URL_INDEXADOR en .env.test (usuario cdss_indexador de la base de pruebas)")
    return create_engine(url)


@pytest.fixture
def documento(super_engine):
    """Documento temporal de nivel 1; al final se borra todo con la conexión de
    administración (cdss_indexador no tiene DELETE). La auditoría se conserva."""
    id_doc = str(uuid.uuid4())
    with super_engine.begin() as c:
        c.execute(text(
            """INSERT INTO conocimiento.documento_fuente
                 (id_documento, titulo, codigo_documento, entidad_emisora, tipo_documento, nivel, anio_publicacion,
                  idioma, cargado_por)
               VALUES (:id, 'Documento de prueba del indexador', 'PRUEBA', 'MINSA', 'NORMA_TECNICA', 1, 2024, 'es', :u)"""
        ), {"id": id_doc, "u": USUARIO_SISTEMA})
    yield id_doc
    with super_engine.begin() as c:
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


class AlmacenQueFalla(AlmacenMemoria):
    def agregar(self, registros):
        raise ConnectionError("ChromaDB no responde")


class RepositorioQueFallaTrasChroma(Repositorio):
    """Falla después de que los vectores ya se escribieron en ChromaDB."""

    def avance(self, id_trabajo, etapa, procesados=0, total=None):
        if etapa == "INDEXACION" and procesados > 0:
            raise RuntimeError("Fallo simulado después de escribir en ChromaDB")
        super().avance(id_trabajo, etapa, procesados, total)


def _fuente(id_doc: str, transcripciones: str | None = None) -> FuenteDocumento:
    return FuenteDocumento(clave="prueba", id_documento=id_doc, archivo="prueba.pdf", transcripciones=transcripciones)


def _indexar(engine, id_doc, almacen=None, repo_cls=Repositorio, opciones=Opciones(), hash_archivo=None,
             transcripciones=None, paginas=PAGINAS, id_trabajo=None):
    repo = repo_cls(engine)
    almacen = almacen if almacen is not None else AlmacenMemoria()
    indexador = Indexador(repo, almacen, EmbedderFalso(), TokenizadorFalso(), lote_progreso=4)
    resultado = indexador.indexar(_fuente(id_doc, transcripciones), None, opciones, id_trabajo,
                                  extraer=lambda _doc: paginas, hash_archivo=hash_archivo or uuid.uuid4().hex * 2,
                                  ruta_blob="local://prueba/prueba.pdf")
    return resultado, repo, almacen


def _estado(super_engine, id_doc):
    with super_engine.connect() as c:
        return c.execute(text(
            """SELECT estado_indexacion, total_fragmentos,
                      (SELECT count(*) FROM conocimiento.fragmento f WHERE f.id_documento = d.id_documento)
                 FROM conocimiento.documento_fuente d WHERE id_documento = :id"""
        ), {"id": id_doc}).one()


def test_indexa_con_el_mismo_conteo_en_postgresql_y_chromadb(engine_indexador, super_engine, documento):
    r, repo, almacen = _indexar(engine_indexador, documento)
    assert r.estado == "COMPLETADA" and r.version == 1
    estado, total, en_pg = _estado(super_engine, documento)
    assert estado == "COMPLETADA" and total == en_pg == r.total == len(almacen.ids_de_documento(documento))
    meta = next(iter(almacen.registros.values())).metadatos
    assert {"id_documento", "id_fragmento", "nivel", "estado_documento", "vigente", "idioma", "seccion",
            "paginas"} <= meta.keys()
    assert meta["id_documento"] == documento and meta["nivel"] == 1 and meta["idioma"] == "es"
    with super_engine.connect() as c:
        tipos = set(c.execute(text("SELECT tipo_contenido FROM conocimiento.fragmento WHERE id_documento = :id"),
                              {"id": documento}).scalars())
        evento = c.execute(text(
            """SELECT detalle->>'fragmentos' FROM auditoria.evento_auditoria
                WHERE tipo_evento = 'GUIA_INDEXADA' AND id_entidad = :id"""
        ), {"id": documento}).scalar()
    assert tipos == {"TEXTO", "TABLA"}
    assert int(evento) == r.total


def test_avance_del_trabajo_en_transacciones_separadas(engine_indexador, super_engine, documento):
    repo = Repositorio(engine_indexador)
    id_trabajo = repo.crear_trabajo(documento, "INDEXACION", estado="EN_CURSO")
    r, _, _ = _indexar(engine_indexador, documento, id_trabajo=id_trabajo)
    with super_engine.connect() as c:
        fila = c.execute(text(
            "SELECT estado, etapa, procesados, total, fecha_fin FROM conocimiento.trabajo_indexacion WHERE id_trabajo = :t"
        ), {"t": id_trabajo}).one()
    assert fila.estado == "COMPLETADO" and fila.etapa == "INDEXACION"
    assert fila.procesados == fila.total == r.total and fila.fecha_fin is not None


def test_fallo_de_chromadb_no_deja_nada_y_el_documento_queda_en_error(engine_indexador, super_engine, documento):
    almacen = AlmacenQueFalla()
    r, _, _ = _indexar(engine_indexador, documento, almacen=almacen)
    assert r.estado == "ERROR" and "ChromaDB no responde" in r.mensaje
    estado, total, en_pg = _estado(super_engine, documento)
    assert estado == "ERROR" and en_pg == 0 and total == 0
    assert almacen.registros == {}


def test_fallo_despues_de_chromadb_compensa_borrando_los_vectores(engine_indexador, super_engine, documento):
    r, _, almacen = _indexar(engine_indexador, documento, repo_cls=RepositorioQueFallaTrasChroma)
    assert r.estado == "ERROR" and "después de escribir en ChromaDB" in r.mensaje
    estado, _, en_pg = _estado(super_engine, documento)
    assert estado == "ERROR" and en_pg == 0
    assert almacen.ids_de_documento(documento) == []


def test_recargar_el_mismo_archivo_no_duplica(engine_indexador, super_engine, documento):
    hash_archivo = uuid.uuid4().hex * 2
    almacen = AlmacenMemoria()
    primero, _, _ = _indexar(engine_indexador, documento, almacen=almacen, hash_archivo=hash_archivo)
    segundo, _, _ = _indexar(engine_indexador, documento, almacen=almacen, hash_archivo=hash_archivo)
    assert primero.estado == "COMPLETADA" and segundo.estado == "OMITIDO"
    _, total, en_pg = _estado(super_engine, documento)
    assert en_pg == total == primero.total == len(almacen.ids_de_documento(documento))


def _transcripcion(tmp_path: Path, verificada: bool) -> str:
    carpeta = tmp_path / "transcripciones"
    carpeta.mkdir()
    verificacion = "verificado_por: Revisora\nfecha_verificacion: 2026-11-05\n" if verificada else \
        "verificado_por:\nfecha_verificacion:\n"
    (carpeta / "tabla07.md").write_text(
        "---\ndocumento: PRUEBA\npagina: 2\ntabla: Tabla N° 7 de prueba\ntipo_contenido: TABLA\n"
        "ancla_inicio: '^Tabla N° 7'\nancla_fin: 'Fuente: MINSA'\n" + verificacion +
        "---\nTabla N° 7\n| Edad | Dosis |\n| --- | --- |\n| 12 a 23 meses | 2 mg/kg/día |\n", encoding="utf-8")
    return str(carpeta)


def test_nivel_1_rechaza_transcripciones_sin_verificar(engine_indexador, super_engine, documento, tmp_path):
    r, _, almacen = _indexar(engine_indexador, documento, transcripciones=_transcripcion(tmp_path, False))
    assert r.estado == "ERROR"
    assert "transcripciones sin verificar" in r.mensaje and "--permitir-no-verificadas" in r.mensaje
    estado, _, en_pg = _estado(super_engine, documento)
    assert estado == "ERROR" and en_pg == 0 and almacen.registros == {}


def test_opcion_de_desarrollo_acepta_y_marca_no_verificadas(engine_indexador, super_engine, documento, tmp_path):
    r, _, _ = _indexar(engine_indexador, documento, transcripciones=_transcripcion(tmp_path, False),
                       opciones=Opciones(permitir_no_verificadas=True))
    assert r.estado == "COMPLETADA" and r.no_verificadas == 1
    with super_engine.connect() as c:
        fila = c.execute(text(
            """SELECT tipo_contenido, verificado, fecha_verificacion, vigente FROM conocimiento.fragmento
                WHERE id_documento = :id AND fuente_texto = 'TRANSCRIPCION'"""
        ), {"id": documento}).one()
    assert fila.tipo_contenido == "TABLA" and fila.verificado is False and fila.fecha_verificacion is None
    assert fila.vigente is True


def test_transcripcion_verificada_se_indexa_sin_la_opcion(engine_indexador, super_engine, documento, tmp_path):
    r, _, _ = _indexar(engine_indexador, documento, transcripciones=_transcripcion(tmp_path, True))
    assert r.estado == "COMPLETADA" and r.no_verificadas == 0
    with super_engine.connect() as c:
        verificado = c.execute(text(
            "SELECT verificado FROM conocimiento.fragmento WHERE id_documento = :id AND fuente_texto = 'TRANSCRIPCION'"
        ), {"id": documento}).scalar()
    assert verificado is True


def _citar(super_engine, id_fragmento: str) -> None:
    """Registra una consulta con una cita al fragmento, como lo hará el motor RAG."""
    with super_engine.begin() as c:
        tamizaje, usuario = c.execute(text(
            """SELECT t.id_tamizaje, u.id_usuario FROM clinico.tamizaje t, seguridad.usuario u
                WHERE u.nombre_usuario = 'med.salazar' LIMIT 1"""
        )).one()
        consulta = c.execute(text(
            """INSERT INTO asistencia.consulta (id_tamizaje, id_usuario, texto_consulta, estado)
               VALUES (:t, :u, 'consulta de prueba', 'VERIFICADA') RETURNING id_consulta"""
        ), {"t": tamizaje, "u": usuario}).scalar()
        intento = c.execute(text(
            """INSERT INTO asistencia.intento_generacion (id_consulta, numero_intento, tipo_busqueda, consulta_reformulada,
                 candidatos_evaluados, umbral_relevancia, resultado)
               VALUES (:c, 1, 'INICIAL', 'consulta de prueba', 1, 0.5, 'APROBADO') RETURNING id_intento"""
        ), {"c": consulta}).scalar()
        c.execute(text(
            """INSERT INTO asistencia.fragmento_recuperado (id_intento, id_fragmento, posicion_rrf, puntaje_rrf,
                 puntaje_reranker, posicion_final, enviado_al_llm, etiqueta_cita)
               VALUES (:i, :f, 1, 0.5, 0.9, 1, true, 'F1')"""
        ), {"i": intento, "f": id_fragmento})
        recomendacion = c.execute(text(
            """INSERT INTO asistencia.recomendacion (id_consulta, id_intento, texto_recomendacion)
               VALUES (:c, :i, 'recomendación de prueba') RETURNING id_recomendacion"""
        ), {"c": consulta, "i": intento}).scalar()
        c.execute(text(
            """INSERT INTO asistencia.cita_evidencia (id_recomendacion, id_intento, id_fragmento, orden, texto_citado)
               VALUES (:r, :i, :f, 1, 'texto citado')"""
        ), {"r": recomendacion, "i": intento, "f": id_fragmento})


def test_reindexar_crea_version_2_y_la_cita_de_la_version_1_sigue_resolviendose(
        engine_indexador, super_engine, documento):
    almacen = AlmacenMemoria()
    v1, repo, _ = _indexar(engine_indexador, documento, almacen=almacen)
    citado = repo.fragmentos(documento, 1)[0]
    _citar(super_engine, citado["id_fragmento"])

    v2, _, _ = _indexar(engine_indexador, documento, almacen=almacen, opciones=Opciones(reindexar=True))
    assert (v1.version, v2.version) == (1, 2)

    with super_engine.connect() as c:
        por_version = dict(c.execute(text(
            """SELECT version_indexacion, count(*) FILTER (WHERE vigente) FROM conocimiento.fragmento
                WHERE id_documento = :id GROUP BY 1"""
        ), {"id": documento}).all())
        motivos = set(c.execute(text(
            "SELECT motivo_exclusion FROM conocimiento.fragmento WHERE id_documento = :id AND version_indexacion = 1"
        ), {"id": documento}).scalars())
        cita = c.execute(text(
            """SELECT f.texto, f.version_indexacion, f.vigente, d.titulo
                 FROM asistencia.cita_evidencia ce
                 JOIN conocimiento.fragmento f ON f.id_fragmento = ce.id_fragmento
                 JOIN conocimiento.documento_fuente d ON d.id_documento = f.id_documento
                WHERE ce.id_fragmento = :f"""
        ), {"f": citado["id_fragmento"]}).one()
    assert por_version == {1: 0, 2: v2.vigentes}
    assert motivos == {"REINDEXADO: reemplazado por la versión 2"}
    assert cita.texto == citado["texto"] and cita.version_indexacion == 1 and cita.vigente is False
    assert cita.titulo == "Documento de prueba del indexador"
    # ChromaDB solo conserva los vectores de la versión vigente
    ids_v2 = {f["id_fragmento"] for f in repo.fragmentos(documento, 2)}
    assert set(almacen.ids_de_documento(documento)) == ids_v2
    assert citado["id_fragmento"] not in almacen.registros


def test_trabajador_toma_un_trabajo_pendiente(engine_indexador, super_engine, documento):
    repo = Repositorio(engine_indexador)
    id_trabajo = repo.crear_trabajo(documento, "INDEXACION")
    trabajo = repo.tomar_trabajo()
    assert trabajo is not None and trabajo.id_trabajo == id_trabajo
    with super_engine.connect() as c:
        estado = c.execute(text("SELECT estado FROM conocimiento.trabajo_indexacion WHERE id_trabajo = :t"),
                           {"t": id_trabajo}).scalar()
    assert estado == "EN_CURSO"
    repo.finalizar_trabajo(id_trabajo, "cancelado por la prueba")
