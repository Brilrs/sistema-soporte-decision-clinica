"""Sprint 3, parte K: respaldo y restauración de la colección de ChromaDB y de las guías cargadas.

Casi todo usa ServidorMemoria (colecciones en memoria) y carpetas temporales; PostgreSQL es la base de
pruebas, con guías sintéticas PRUEBA-K-... que se borran al terminar. La prueba con ChromaDB real
(marca chroma_real) solo corre localmente, con CHROMA_URL_PRUEBAS, y usa colecciones
guias_clinicas_prueba_k... que descarta al final; nunca toca guias_clinicas."""
import json
import re
import os
import random
import shutil
import struct
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from app.core.fechas import ZONA_PERU
from app.core.vectores import (COLECCION, ESPACIO, PREFIJO_PRUEBA, RegistroVector, ServidorChroma,
                               ServidorMemoria)
from app.indexador.repositorio import USUARIO_SISTEMA
from app.respaldo import __main__ as cli
from app.respaldo.destinos import DestinoBlob, DestinoLocal, ErrorRespaldo, sha256_bytes
from app.respaldo.operaciones import (ARCHIVO_VECTORES, CARPETA_GUIAS, TOLERANCIA_VECTOR, comparar, crear,
                                      descartar_coleccion, diferencia_vector, leer_vectores, restaurar, verificar,
                                      verificar_carpeta)
from app.respaldo.postgres import FuentePostgres

AHORA = datetime(2026, 11, 19, 10, 30, 0, tzinfo=ZONA_PERU)
DIM = 6


# ---------------------------------------------------------------------------
# Fixtures y ayudantes
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def fuente():
    engine = create_engine(os.environ["DATABASE_URL_INDEXADOR"])
    yield FuentePostgres(engine)
    engine.dispose()


def _borrar_guias_k(super_engine) -> None:
    with super_engine.begin() as c:
        ids = [r[0] for r in c.execute(text(
            "SELECT id_documento FROM conocimiento.documento_fuente WHERE codigo_documento LIKE 'PRUEBA-K-%'"))]
        c.execute(text("DELETE FROM conocimiento.trabajo_indexacion WHERE id_documento = ANY(:ids)"), {"ids": ids})
        c.execute(text("DELETE FROM conocimiento.fragmento WHERE id_documento = ANY(:ids)"), {"ids": ids})
        c.execute(text("DELETE FROM conocimiento.documento_fuente WHERE id_documento = ANY(:ids)"), {"ids": ids})


@pytest.fixture
def guias_k(super_engine):
    """Dos guías sintéticas: nivel 1 vigente con 4 fragmentos (uno no vigente y una versión anterior) y
    nivel 2 obsoleta con 2. Al final se borran, aunque la prueba falle."""
    with super_engine.connect() as c:
        activos = c.execute(text("SELECT count(*) FROM conocimiento.trabajo_indexacion "
                                 "WHERE estado IN ('PENDIENTE','EN_CURSO')")).scalar()
    assert activos == 0, "La base de pruebas tiene trabajos activos de otra prueba"
    _borrar_guias_k(super_engine)
    docs = []
    with super_engine.begin() as c:
        for nivel, estado, total in ((1, "VIGENTE", 4), (2, "OBSOLETA", 2)):
            id_doc = str(uuid.uuid4())
            retiro = estado == "OBSOLETA"
            c.execute(text(
                """INSERT INTO conocimiento.documento_fuente
                     (id_documento, titulo, codigo_documento, entidad_emisora, tipo_documento, nivel, anio_publicacion,
                      idioma, cargado_por, estado_indexacion, ruta_blob, hash_archivo, total_fragmentos, estado,
                      retirado_por, fecha_retiro, motivo_retiro)
                   VALUES (:id, 'Guía sintética de la parte K', :cod, 'OTRA', 'LITERATURA', :n, 2024, 'es', :u,
                           'COMPLETADA', 'local://prueba/k.pdf', :h, :t, :e,
                           CASE WHEN :r THEN CAST(:u AS uuid) END, CASE WHEN :r THEN now() END,
                           CASE WHEN :r THEN 'Retiro sintético de la parte K' END)"""),
                {"id": id_doc, "cod": f"PRUEBA-K-{id_doc[:8]}", "n": nivel, "u": USUARIO_SISTEMA,
                 "h": uuid.uuid4().hex * 2, "t": total, "e": estado, "r": retiro})
            for version, cantidad in ((1, 1), (2, total)) if nivel == 1 else ((1, total),):
                for orden in range(1, cantidad + 1):
                    c.execute(text(
                        """INSERT INTO conocimiento.fragmento (id_documento, numero_orden, seccion, pagina_inicio,
                             pagina_fin, texto, numero_tokens, modelo_embedding, vigente, version_indexacion, motivo_exclusion)
                           VALUES (:d, :o, 'Sección', 1, 1, 'Texto sintético de la parte K', 20, 'falso', :v, :ver,
                                   CASE WHEN :v THEN NULL ELSE 'EXCLUIDO: prueba de la parte K' END)"""),
                        {"d": id_doc, "o": orden, "v": orden != 2, "ver": version})
            docs.append({"id": id_doc, "nivel": nivel, "estado": estado})
    yield docs
    _borrar_guias_k(super_engine)


def _float32(x: float) -> float:
    """Un float representable en float32, como los que guarda ChromaDB."""
    return struct.unpack("f", struct.pack("f", x))[0]


def _vector(semilla: str) -> list[float]:
    azar = random.Random(semilla)
    return [_float32(azar.uniform(-1, 1)) for _ in range(DIM - 2)] + [0.1, 1e-30]


def _servidor_como_pg(fuente) -> ServidorMemoria:
    """Una colección guias_clinicas igual a lo que PostgreSQL espera, con metadatos como los del indexador."""
    servidor = ServidorMemoria()
    almacen = servidor.crear(COLECCION, {ESPACIO: "cosine"})
    almacen.agregar([
        RegistroVector(id_, _vector(id_), f"Texto «{id_[:8]}» con acentos: hemoglobina ≥ 11,0 g/dL", {
            "id_documento": e.id_documento, "id_fragmento": id_, "nivel": e.nivel, "estado_documento": e.estado_documento,
            "vigente": e.vigente, "idioma": "es", "seccion": "", "paginas": "1-1", "pagina_inicio": 1, "pagina_fin": 1,
            "edad_min_meses": -1, "edad_max_meses": 59, "verificado": False, "version_indexacion": 2, "peso": 0.5})
        for id_, e in fuente.fragmentos_esperados().items()])
    return servidor


@pytest.fixture
def entorno(tmp_path, fuente, guias_k):
    servidor = _servidor_como_pg(fuente)
    assert servidor.abrir(COLECCION).contar() == 6
    guias = tmp_path / "guias_cargadas"
    guias.mkdir()
    (guias / "a.pdf").write_bytes(b"%PDF-1.4 guia a")
    (guias / "b.pdf").write_bytes(b"%PDF-1.4 guia b " * 50)
    return {"servidor": servidor, "destino": DestinoLocal(tmp_path / "respaldos"), "guias": guias, "tmp": tmp_path}


def _crear(entorno, fuente, destino=None, **extra):
    opciones = {"dir_guias": entorno["guias"], "ahora": AHORA, **extra}
    return crear(entorno["servidor"], destino or entorno["destino"], fuente, **opciones)


def _registros(almacen) -> dict[str, RegistroVector]:
    return {r.id: r for r in almacen.obtener(almacen.ids())}


def _ultimo_evento(super_engine) -> int:
    with super_engine.connect() as c:
        return c.execute(text("SELECT coalesce(max(id_evento), 0) FROM auditoria.evento_auditoria")).scalar_one()


def _eventos(super_engine, desde: int) -> list[dict]:
    with super_engine.connect() as c:
        return [dict(f) for f in c.execute(text(
            """SELECT tipo_evento, entidad, id_entidad, id_usuario::text AS id_usuario, detalle::text AS detalle
                 FROM auditoria.evento_auditoria WHERE id_evento > :d AND entidad = 'respaldo' ORDER BY id_evento"""),
            {"d": desde}).mappings()]


# ---------------------------------------------------------------------------
# Crear y restaurar
# ---------------------------------------------------------------------------
def test_ida_y_vuelta_identica(entorno, fuente):
    r = _crear(entorno, fuente)
    assert r.nombre == "respaldo_20261119_103000" and (r.vectores, r.vigentes, r.guias) == (6, 4, 2)
    carpeta = entorno["tmp"] / "respaldos" / r.nombre
    nombres = sorted(p.relative_to(carpeta).as_posix() for p in carpeta.rglob("*") if p.is_file())
    assert nombres == ["coleccion.json", "guias_cargadas/a.pdf", "guias_cargadas/b.pdf", "manifiesto.json",
                       "manifiesto.json.sha256", "vectores.jsonl"]
    manifiesto = json.loads((carpeta / "manifiesto.json").read_text(encoding="utf-8"))
    assert manifiesto["vectores"] == 6 and manifiesto["vectores_vigentes"] == 4
    assert manifiesto["coleccion"] == {"nombre": COLECCION, "metadatos": {ESPACIO: "cosine"}}
    assert manifiesto["modelo_embeddings"] == ["falso"] and manifiesto["version_chromadb"] == "memoria"
    assert manifiesto["forzado"] is False and manifiesto["fecha"] == "2026-11-19T10:30:00-05:00"
    assert manifiesto["huella_codigo"] and manifiesto["version_codigo"]
    assert {a["ruta"] for a in manifiesto["archivos"]} == set(nombres) - {"manifiesto.json", "manifiesto.json.sha256"}
    assert [g["archivo"] for g in manifiesto["guias_cargadas"]] == ["a.pdf", "b.pdf"]

    vacio = ServidorMemoria()
    rr = restaurar(vacio, entorno["destino"], fuente, r.nombre)
    assert rr.vectores == 6 and rr.verificacion.ok
    original = entorno["servidor"].abrir(COLECCION)
    restaurado = vacio.abrir(COLECCION)
    assert restaurado.metadatos_coleccion == original.metadatos_coleccion == {ESPACIO: "cosine"}
    assert _registros(restaurado) == _registros(original)
    # Los floats vuelven bit a bit (también los muy pequeños y los de float32)
    for id_, reg in _registros(original).items():
        assert [struct.pack("d", x) for x in _registros(restaurado)[id_].vector] == [struct.pack("d", x) for x in reg.vector]


def test_la_distancia_se_conserva_y_la_consulta_devuelve_lo_mismo(entorno, fuente):
    r = _crear(entorno, fuente)
    servidor = entorno["servidor"]
    restaurar(servidor, entorno["destino"], fuente, r.nombre, coleccion=PREFIJO_PRUEBA + "restauracion")
    original, copia = servidor.abrir(COLECCION), servidor.abrir(PREFIJO_PRUEBA + "restauracion")
    assert copia.metadatos_coleccion[ESPACIO] == "cosine"
    consulta = [0.3, -0.2, 0.9, 0.1, 0.0, 0.5]
    assert copia.consultar(consulta, 5) == original.consultar(consulta, 5)
    comparacion = comparar(servidor, COLECCION, PREFIJO_PRUEBA + "restauracion")
    assert comparacion.identicas and comparacion.consultas == 5
    # Con otra distancia (l2, la de ChromaDB por omisión) el orden cambia: la distancia es esencial.
    # Vectores e ids fijos (no los de guias_k, que salen de uuid al azar y con 6 vectores a veces dan el
    # mismo orden con las dos distancias). Con la consulta [1, 0, 0, 0, 0, 0]:
    #   k-direccion [0.1, 0, ...]: misma dirección y chico: coseno 0;      l2 al cuadrado 0.81
    #   k-desviado  [1, 0.3, ...]: algo desviado y cerca:   coseno 0.0422; l2 al cuadrado 0.09
    #   k-lejano    [0, 1, ...]:   perpendicular:           coseno 1;      l2 al cuadrado 2
    # Coseno ordena direccion, desviado, lejano; l2 ordena desviado, direccion, lejano.
    fijos = [RegistroVector("k-direccion", [0.1, 0.0, 0.0, 0.0, 0.0, 0.0], "Texto fijo 1", {}),
             RegistroVector("k-desviado", [1.0, 0.3, 0.0, 0.0, 0.0, 0.0], "Texto fijo 2", {}),
             RegistroVector("k-lejano", [0.0, 1.0, 0.0, 0.0, 0.0, 0.0], "Texto fijo 3", {})]
    coseno_fija = servidor.crear(PREFIJO_PRUEBA + "coseno_fija", {ESPACIO: "cosine"})
    l2_fija = servidor.crear(PREFIJO_PRUEBA + "l2_fija", {})
    for almacen in (coseno_fija, l2_fija):
        almacen.agregar(fijos)
    consulta_fija = [1.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    por_coseno, por_l2 = coseno_fija.consultar(consulta_fija, 3), l2_fija.consultar(consulta_fija, 3)
    assert [i for i, _ in por_coseno] == ["k-direccion", "k-desviado", "k-lejano"]
    assert [i for i, _ in por_l2] == ["k-desviado", "k-direccion", "k-lejano"]
    assert [round(d, 4) for _, d in por_coseno] == [0.0, 0.0422, 1.0]
    assert [round(d, 4) for _, d in por_l2] == [0.09, 0.81, 2.0]
    # La copia de la colección con l2 no coincide con la original (distinta distancia)
    l2 = servidor.crear(PREFIJO_PRUEBA + "l2", {})
    l2.agregar(original.obtener(original.ids()))
    assert not comparar(servidor, COLECCION, PREFIJO_PRUEBA + "l2").identicas


def test_la_restauracion_se_niega_si_la_coleccion_tiene_datos(entorno, fuente):
    r = _crear(entorno, fuente)
    antes = _registros(entorno["servidor"].abrir(COLECCION))
    with pytest.raises(ErrorRespaldo, match="ya tiene 6 vectores"):
        restaurar(entorno["servidor"], entorno["destino"], fuente, r.nombre)
    assert _registros(entorno["servidor"].abrir(COLECCION)) == antes
    # Una colección vacía con los mismos metadatos sí se usa
    vacio = ServidorMemoria()
    vacio.crear(COLECCION, {ESPACIO: "cosine"})
    assert restaurar(vacio, entorno["destino"], fuente, r.nombre).vectores == 6
    # Vacía pero con otra distancia: se niega
    otro = ServidorMemoria()
    otro.crear(COLECCION, {})
    with pytest.raises(ErrorRespaldo, match="otros metadatos"):
        restaurar(otro, entorno["destino"], fuente, r.nombre)
    assert otro.abrir(COLECCION).contar() == 0


def _alterar_vector(carpeta: Path) -> None:
    ruta = carpeta / ARCHIVO_VECTORES
    datos = ruta.read_bytes()
    ruta.write_bytes(datos.replace(b'"texto": "Texto', b'"texto": "Textx', 1))


def _quitar_guia(carpeta: Path) -> None:
    (carpeta / CARPETA_GUIAS / "a.pdf").unlink()


def _cambiar_manifiesto(carpeta: Path) -> None:
    ruta = carpeta / "manifiesto.json"
    ruta.write_text(ruta.read_text(encoding="utf-8").replace('"vectores": 6', '"vectores": 5'), encoding="utf-8")


def _cambiar_huella(carpeta: Path) -> None:
    (carpeta / "manifiesto.json.sha256").write_text("0" * 64 + "  manifiesto.json\n", encoding="utf-8")


def _rehacer_manifiesto(carpeta: Path) -> None:
    """El manifiesto cambiado con su SHA-256 rehecho: no coincide con los archivos que describe."""
    _cambiar_manifiesto(carpeta)
    datos = (carpeta / "manifiesto.json").read_bytes()
    (carpeta / "manifiesto.json.sha256").write_text(f"{sha256_bytes(datos)}  manifiesto.json\n", encoding="utf-8")


@pytest.mark.parametrize("alterar, motivo", [
    (_alterar_vector, "vectores.jsonl no coincide"),
    (_quitar_guia, "Falta el archivo guias_cargadas/a.pdf"),
    (_cambiar_manifiesto, "manifiesto no coincide con su SHA-256"),
    (_cambiar_huella, "manifiesto no coincide con su SHA-256"),
    (_rehacer_manifiesto, "número de vectores no coincide"),
])
def test_restaurar_se_niega_y_no_escribe_nada_si_el_respaldo_no_coincide(entorno, fuente, super_engine, alterar,
                                                                         motivo):
    r = _crear(entorno, fuente)
    alterar(entorno["tmp"] / "respaldos" / r.nombre)
    vacio, desde = ServidorMemoria(), _ultimo_evento(super_engine)
    guias = entorno["tmp"] / "guias_destino"
    guias.mkdir()
    with pytest.raises(ErrorRespaldo, match=motivo):
        restaurar(vacio, entorno["destino"], fuente, r.nombre, con_guias=True, dir_guias=guias)
    assert vacio.listar() == [] and list(guias.iterdir()) == []
    assert _eventos(super_engine, desde) == []


def test_restaurar_desde_una_ruta_y_respaldo_inexistente(entorno, fuente):
    r = _crear(entorno, fuente)
    copia = entorno["tmp"] / "copia"
    shutil.copytree(entorno["tmp"] / "respaldos" / r.nombre, copia)
    assert restaurar(ServidorMemoria(), entorno["destino"], fuente, str(copia)).vectores == 6
    with pytest.raises(ErrorRespaldo, match="No existe el respaldo"):
        restaurar(ServidorMemoria(), entorno["destino"], fuente, "respaldo_20000101_000000")


# ---------------------------------------------------------------------------
# Trabajos de indexación activos
# ---------------------------------------------------------------------------
def test_se_niega_con_trabajos_activos_y_forzar_lo_anota(entorno, fuente, guias_k, super_engine):
    with super_engine.begin() as c:
        c.execute(text("INSERT INTO conocimiento.trabajo_indexacion (id_documento, tipo, estado, solicitado_por) "
                       "VALUES (:d, 'INDEXACION', 'PENDIENTE', :u)"), {"d": guias_k[0]["id"], "u": USUARIO_SISTEMA})
    with pytest.raises(ErrorRespaldo, match="1 trabajos de indexación pendientes o en curso"):
        _crear(entorno, fuente)
    assert entorno["destino"].listar() == []
    r = _crear(entorno, fuente, forzar=True)
    manifiesto = json.loads((entorno["tmp"] / "respaldos" / r.nombre / "manifiesto.json").read_text(encoding="utf-8"))
    assert r.forzado and manifiesto["forzado"] is True and manifiesto["trabajos_activos"] == 1


# ---------------------------------------------------------------------------
# Verificar contra PostgreSQL
# ---------------------------------------------------------------------------
def _primero(almacen, vigente: bool | None = None) -> str:
    return next(r.id for r in almacen.obtener(almacen.ids()) if vigente is None or r.metadatos["vigente"] is vigente)


def _cambiar(almacen, id_: str, **cambios) -> None:
    almacen.actualizar_metadatos([id_], cambios)


def test_verificar_coincide_y_resume(entorno, fuente):
    v = verificar(entorno["servidor"], fuente)
    assert v.ok and v.problemas == []
    assert (v.vectores, v.vigentes, v.distancia) == (6, 4, "cosine")
    assert v.por_nivel == {"1": 4, "2": 2} and v.por_estado == {"OBSOLETA": 2, "VIGENTE": 4}


@pytest.mark.parametrize("caso, lista", [
    ("faltante", "faltantes"),
    ("huerfano", "huerfanos"),
    ("vigencia", "vigencia_distinta"),
    ("estado", "estado_distinto"),
    ("nivel", "nivel_distinto"),
])
def test_verificar_detecta_cada_discrepancia(entorno, fuente, monkeypatch, capsys, caso, lista):
    almacen = entorno["servidor"].abrir(COLECCION)
    id_ = _primero(almacen, vigente=True)
    if caso == "faltante":
        almacen.eliminar([id_])
    elif caso == "huerfano":
        id_ = str(uuid.uuid4())
        almacen.agregar([RegistroVector(id_, _vector(id_), "huérfano", {"vigente": True, "nivel": 1})])
    elif caso == "vigencia":
        _cambiar(almacen, id_, vigente=False)
    elif caso == "estado":
        _cambiar(almacen, id_, estado_documento="OTRO_ESTADO")
    else:
        _cambiar(almacen, id_, nivel=almacen.obtener([id_])[0].metadatos["nivel"] + 10)
    v = verificar(entorno["servidor"], fuente)
    assert not v.ok and getattr(v, lista) == [id_]
    otras = {"faltantes", "huerfanos", "vigencia_distinta", "estado_distinto", "nivel_distinto", "documento_distinto"}
    assert all(getattr(v, o) == [] for o in otras - {lista})
    # Por la línea de comandos: código distinto de cero y el motivo en pantalla
    monkeypatch.setattr(cli, "ServidorChroma", lambda url: entorno["servidor"])
    monkeypatch.setattr(cli, "_fuente", lambda e: fuente)
    assert cli.main(["verificar"]) == 1
    assert "NO COINCIDE" in capsys.readouterr().out


def test_verificar_detecta_otra_distancia_y_coleccion_inexistente(entorno, fuente, monkeypatch, capsys):
    almacen = entorno["servidor"].abrir(COLECCION)
    l2 = ServidorMemoria()
    l2.crear(COLECCION, {}).agregar(almacen.obtener(almacen.ids()))
    v = verificar(l2, fuente)
    assert not v.ok and v.distancia is None and v.problemas == ["distancia None en lugar de 'cosine'"]
    assert not verificar(ServidorMemoria(), fuente).ok
    monkeypatch.setattr(cli, "ServidorChroma", lambda url: entorno["servidor"])
    monkeypatch.setattr(cli, "_fuente", lambda e: fuente)
    assert cli.main(["verificar"]) == 0
    assert "Coincide con PostgreSQL" in capsys.readouterr().out
    assert cli.main(["verificar", "--coleccion", PREFIJO_PRUEBA + "no_existe"]) == 1


# ---------------------------------------------------------------------------
# Retención
# ---------------------------------------------------------------------------
def test_conservar_solo_borra_respaldos_del_propio_destino(entorno, fuente):
    raiz = entorno["tmp"] / "respaldos"
    otro_destino = entorno["tmp"] / "otro_destino" / "respaldo_20200101_000000"
    otro_destino.mkdir(parents=True)
    raiz.mkdir()
    (raiz / "respaldo_20200101_000000").mkdir()                 # respaldo antiguo de este destino
    (raiz / "copia_alterada").mkdir()                            # carpeta con otro nombre
    (raiz / "respaldo_viejo").mkdir()                            # no cumple el patrón
    (raiz / "respaldo_20190101_000000").write_text("archivo")   # un archivo, no una carpeta
    (raiz / "notas.txt").write_text("notas")
    creados = [_crear(entorno, fuente, ahora=AHORA + timedelta(seconds=s), conservar=2) for s in (0, 1, 2)]
    assert creados[-1].eliminados == ["respaldo_20261119_103000"]
    assert creados[1].eliminados == ["respaldo_20200101_000000"]
    assert sorted(p.name for p in raiz.iterdir()) == [
        "copia_alterada", "notas.txt", "respaldo_20190101_000000", "respaldo_20261119_103001",
        "respaldo_20261119_103002", "respaldo_viejo"]
    assert otro_destino.is_dir()
    with pytest.raises(ErrorRespaldo, match="1 o más"):
        _crear(entorno, fuente, conservar=0)


def test_dos_respaldos_en_el_mismo_segundo(entorno, fuente):
    _crear(entorno, fuente)
    with pytest.raises(ErrorRespaldo, match="Ya existe el respaldo"):
        _crear(entorno, fuente)


# ---------------------------------------------------------------------------
# Descartar colecciones
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("nombre", [COLECCION, PREFIJO_PRUEBA, "otra", "guias_clinicas_2", " guias_clinicas_prueba_x"])
def test_descartar_se_niega_fuera_de_las_colecciones_de_prueba(entorno, nombre):
    servidor = entorno["servidor"]
    if nombre not in servidor.listar():
        servidor.crear(nombre, {})
    with pytest.raises(ErrorRespaldo, match="Solo se pueden descartar colecciones de prueba"):
        descartar_coleccion(servidor, nombre)
    assert nombre in servidor.listar() and servidor.abrir(COLECCION).contar() == 6


def test_descartar_una_coleccion_de_prueba(entorno, monkeypatch, capsys):
    servidor = entorno["servidor"]
    servidor.crear(PREFIJO_PRUEBA + "restauracion", {ESPACIO: "cosine"})
    monkeypatch.setattr(cli, "ServidorChroma", lambda url: servidor)
    assert cli.main(["descartar-coleccion", COLECCION]) == 1
    assert "no se borra" in capsys.readouterr().err
    assert cli.main(["descartar-coleccion", PREFIJO_PRUEBA + "restauracion"]) == 0
    assert servidor.listar() == [COLECCION]
    assert cli.main(["descartar-coleccion", PREFIJO_PRUEBA + "restauracion"]) == 1  # ya no existe


# ---------------------------------------------------------------------------
# Guías cargadas
# ---------------------------------------------------------------------------
def test_las_guias_restauradas_no_sobrescriben_un_archivo_distinto(entorno, fuente):
    r = _crear(entorno, fuente)
    destino = entorno["tmp"] / "volumen"
    destino.mkdir()
    (destino / "a.pdf").write_bytes(b"otro contenido local")
    rr = restaurar(ServidorMemoria(), entorno["destino"], fuente, r.nombre, con_guias=True, dir_guias=destino)
    assert rr.guias_distintas == ["a.pdf"] and rr.guias_copiadas == ["b.pdf"] and rr.guias_existentes == []
    assert (destino / "a.pdf").read_bytes() == b"otro contenido local"
    assert (destino / "b.pdf").read_bytes() == (entorno["guias"] / "b.pdf").read_bytes()
    assert sorted(p.name for p in destino.iterdir()) == ["a.pdf", "b.pdf"]  # sin temporales
    rr = restaurar(ServidorMemoria(), entorno["destino"], fuente, r.nombre, con_guias=True, dir_guias=destino)
    assert rr.guias_existentes == ["b.pdf"] and rr.guias_copiadas == []
    with pytest.raises(ErrorRespaldo, match="--con-guias"):
        restaurar(ServidorMemoria(), entorno["destino"], fuente, r.nombre, con_guias=True,
                  dir_guias=entorno["tmp"] / "no_existe")


def test_sin_carpeta_de_guias_el_respaldo_no_las_incluye(entorno, fuente):
    r = _crear(entorno, fuente, dir_guias=entorno["tmp"] / "no_existe")
    assert r.guias == 0 and verificar_carpeta(entorno["tmp"] / "respaldos" / r.nombre)["guias_cargadas"] == []


# ---------------------------------------------------------------------------
# Destino Azure Blob con un cliente simulado (la prueba real se hace en la parte L)
# ---------------------------------------------------------------------------
class ClienteBlobSimulado:
    def __init__(self):
        self.blobs: dict[str, bytes] = {}

    def subir(self, nombre: str, datos: bytes) -> None:
        if nombre in self.blobs:
            raise ValueError("ya existe")
        self.blobs[nombre] = bytes(datos)

    def bajar(self, nombre: str) -> bytes:
        return self.blobs[nombre]

    def listar(self, prefijo: str) -> list[str]:
        return sorted(n for n in self.blobs if n.startswith(prefijo))

    def borrar(self, nombre: str) -> None:
        del self.blobs[nombre]


def test_destino_blob_sube_baja_y_detecta_una_alteracion(entorno, fuente):
    cliente = ClienteBlobSimulado()
    cliente.blobs["otra_cosa/archivo.txt"] = b"no es un respaldo"
    destino = DestinoBlob(cliente, entorno["tmp"])
    r = _crear(entorno, fuente, destino=destino)
    prefijo = f"{r.nombre}/"
    assert sorted(n.removeprefix(prefijo) for n in cliente.listar(prefijo)) == [
        "coleccion.json", "guias_cargadas/a.pdf", "guias_cargadas/b.pdf", "manifiesto.json",
        "manifiesto.json.sha256", "vectores.jsonl"]
    assert destino.listar() == [r.nombre]

    vacio = ServidorMemoria()
    assert restaurar(vacio, destino, fuente, r.nombre).vectores == 6
    assert _registros(vacio.abrir(COLECCION)) == _registros(entorno["servidor"].abrir(COLECCION))

    cliente.blobs[f"{prefijo}vectores.jsonl"] = cliente.blobs[f"{prefijo}vectores.jsonl"].replace(b"Texto", b"Textx", 1)
    otro = ServidorMemoria()
    with pytest.raises(ErrorRespaldo, match="bajado de Blob no coincide"):
        restaurar(otro, destino, fuente, r.nombre)
    assert otro.listar() == []

    # Retención en Blob: solo los prefijos de respaldos, nunca otros blobs
    _crear(entorno, fuente, destino=destino, ahora=AHORA + timedelta(seconds=1), conservar=1)
    assert destino.listar() == ["respaldo_20261119_103001"] and "otra_cosa/archivo.txt" in cliente.blobs
    destino.limpiar()


def test_destino_blob_detecta_una_subida_corrupta(entorno, fuente):
    class Corrupto(ClienteBlobSimulado):
        def subir(self, nombre, datos):
            super().subir(nombre, datos[:-1] if nombre.endswith(".jsonl") else datos)

    cliente = Corrupto()
    destino = DestinoBlob(cliente, entorno["tmp"])
    with pytest.raises(ErrorRespaldo, match="no quedó igual en Blob"):
        _crear(entorno, fuente, destino=destino)
    assert cliente.blobs == {}  # lo subido a medias se descarta
    destino.limpiar()


def test_blob_sin_configuracion_da_un_error_claro(monkeypatch):
    from app.respaldo.destinos import cliente_azure_desde_entorno
    monkeypatch.delenv("RESPALDO_CONTENEDOR_BLOB", raising=False)
    with pytest.raises(ErrorRespaldo, match="RESPALDO_CONTENEDOR_BLOB"):
        cliente_azure_desde_entorno()


# ---------------------------------------------------------------------------
# Eventos y línea de comandos
# ---------------------------------------------------------------------------
def test_eventos_sin_datos_personales_ni_rutas(entorno, fuente, super_engine):
    desde = _ultimo_evento(super_engine)
    r = _crear(entorno, fuente)
    volumen = entorno["tmp"] / "volumen_vacio"
    volumen.mkdir()
    restaurar(ServidorMemoria(), entorno["destino"], fuente, r.nombre, con_guias=True, dir_guias=volumen)
    eventos = _eventos(super_engine, desde)
    assert [e["tipo_evento"] for e in eventos] == ["RESPALDO_CREADO", "RESPALDO_RESTAURADO"]
    for e in eventos:
        assert e["entidad"] == "respaldo" and e["id_entidad"] == r.nombre and e["id_usuario"] == USUARIO_SISTEMA
        detalle = json.loads(e["detalle"])
        texto = e["detalle"]
        assert "/" not in texto and "\\" not in texto and str(entorno["tmp"]) not in texto
        assert "a.pdf" not in texto and "Texto" not in texto and "@" not in texto
        assert all(isinstance(v, (int, bool)) or v in ("local", COLECCION, "ok") for v in detalle.values())
    assert json.loads(eventos[0]["detalle"]) == {
        "coleccion": COLECCION, "vectores": 6, "vigentes": 4, "guias": 2, "destino": "local", "forzado": False,
        "trabajos_activos": 0, "respaldos_eliminados": 0}
    assert json.loads(eventos[1]["detalle"]) == {
        "coleccion": COLECCION, "vectores": 6, "guias_copiadas": 2, "guias_existentes": 0, "guias_distintas": 0,
        "verificacion": "ok"}


def test_linea_de_comandos_crear_restaurar_y_comparar(entorno, fuente, monkeypatch, capsys):
    servidor = entorno["servidor"]
    monkeypatch.setattr(cli, "ServidorChroma", lambda url: servidor)
    monkeypatch.setattr(cli, "_fuente", lambda e: fuente)
    monkeypatch.setenv("RESPALDO_DIR", str(entorno["tmp"] / "respaldos"))
    monkeypatch.setenv("RESPALDO_DIR_GUIAS", str(entorno["guias"]))
    assert cli.main(["crear"]) == 0
    salida = capsys.readouterr().out
    assert "Respaldo creado: respaldo_" in salida and "6 vectores (4 vigentes), 2 guías cargadas" in salida
    nombre = entorno["destino"].listar()[0]
    assert cli.main(["restaurar", nombre]) == 1  # la colección real tiene datos
    assert "no se sobrescribe" in capsys.readouterr().err
    destino = PREFIJO_PRUEBA + "restauracion"
    assert cli.main(["restaurar", nombre, "--coleccion", destino]) == 0
    assert "Coincide con PostgreSQL" in capsys.readouterr().out
    assert cli.main(["comparar", COLECCION, destino]) == 0
    assert "Las colecciones coinciden" in capsys.readouterr().out
    servidor.abrir(destino).actualizar_metadatos([servidor.abrir(destino).ids()[0]], {"vigente": "no"})
    assert cli.main(["comparar", COLECCION, destino]) == 1
    assert "metadatos distinto" in capsys.readouterr().out
    assert cli.main(["crear", "--coleccion", PREFIJO_PRUEBA + "no_existe"]) == 1
    assert "no existe" in capsys.readouterr().err


def test_compose_y_requisitos():
    raiz = Path(__file__).resolve().parents[2]
    compose = (raiz / "docker-compose.yml").read_text(encoding="utf-8")
    assert "respaldo:" in compose and 'profiles: ["respaldo"]' in compose
    assert "./data/respaldos:/datos/respaldos" in compose
    requisitos = (raiz / "backend" / "requirements-jobs.txt").read_text(encoding="utf-8")
    assert "azure-storage-blob==" in requisitos and "azure-identity==" in requisitos
    assert "azure" not in (raiz / "backend" / "requirements.txt").read_text(encoding="utf-8")
    assert "data/*" in (raiz / ".gitignore").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# ChromaDB real (solo local): CHROMA_URL_PRUEBAS=http://localhost:8001 pytest -m chroma_real
# ---------------------------------------------------------------------------
@pytest.mark.chroma_real
def test_ida_y_vuelta_con_chromadb_real(tmp_path, fuente):
    url = os.environ.get("CHROMA_URL_PRUEBAS")
    if not url:
        pytest.skip("Defina CHROMA_URL_PRUEBAS (por ejemplo http://localhost:8001) para usar ChromaDB real")
    servidor = ServidorChroma(url, lote=7)
    sufijo = uuid.uuid4().hex[:8]
    origen, copia = f"{PREFIJO_PRUEBA}k{sufijo}_a", f"{PREFIJO_PRUEBA}k{sufijo}_b"
    antes = servidor.listar()
    real = servidor.abrir(COLECCION)
    conteo_real = real.contar() if real else None
    try:
        # 200 vectores unitarios de 1024 dimensiones (como bge-m3): pasan por el índice HNSW, que con
        # coseno normaliza en float32; con pocos vectores ChromaDB los devuelve sin normalizar.
        registros = _unitarios()
        servidor.crear(origen, {ESPACIO: "cosine"}).agregar(registros)
        r = crear(servidor, DestinoLocal(tmp_path), fuente, dir_guias=None, coleccion=origen, ahora=AHORA)
        assert r.vectores == 200
        rr = restaurar(servidor, DestinoLocal(tmp_path), fuente, r.nombre, coleccion=copia)
        assert rr.vectores == 200 and rr.diferencia_maxima <= TOLERANCIA_VECTOR
        restaurada = servidor.abrir(copia)
        assert restaurada.metadatos_coleccion[ESPACIO] == "cosine"
        exportados = {x.id: x for x in leer_vectores(tmp_path / r.nombre)}
        for x in restaurada.obtener(restaurada.ids()):
            original = exportados[x.id]
            assert (x.texto, x.metadatos) == (original.texto, original.metadatos)
            assert diferencia_vector(x.vector, original.vector) <= TOLERANCIA_VECTOR
        comparacion = comparar(servidor, origen, copia)
        assert comparacion.identicas and comparacion.consultas == 5, comparacion.diferencias
        print(f"diferencia máxima con ChromaDB real: restaurar {rr.diferencia_maxima:.2e}, "
              f"comparar {comparacion.diferencia_maxima:.2e}")
    finally:
        for nombre in (origen, copia):
            if nombre in servidor.listar():
                servidor.borrar(nombre)
    assert servidor.listar() == antes
    if conteo_real is not None:
        assert servidor.abrir(COLECCION).contar() == conteo_real


# ---------------------------------------------------------------------------
# Normalización de ChromaDB con coseno (corrección de la parte K)
# ---------------------------------------------------------------------------
def _unitarios(cantidad: int = 200, dim: int = 1024, semilla: int = 213) -> list[RegistroVector]:
    """Vectores unitarios aleatorios (semilla fija), como los de bge-m3."""
    azar = random.Random(semilla)
    registros = []
    for i in range(cantidad):
        v = [azar.gauss(0, 1) for _ in range(dim)]
        norma = sum(x * x for x in v) ** 0.5
        registros.append(RegistroVector(f"frag-{i:04d}", [x / norma for x in v], f"Texto {i}",
                                        {"vigente": i % 4 != 0, "nivel": 1, "estado_documento": "VIGENTE"}))
    return registros


@pytest.fixture
def normalizante(fuente):
    """Servidor que normaliza en float32 al agregar (como ChromaDB) con 200 vectores unitarios en la
    colección de origen; los vectores guardados ya pasaron por una normalización."""
    servidor = ServidorMemoria(normalizar_como_chroma=True)
    servidor.crear(PREFIJO_PRUEBA + "origen", {ESPACIO: "cosine"}).agregar(_unitarios())
    return servidor


def _respaldo_normalizante(normalizante, fuente, tmp_path):
    destino = DestinoLocal(tmp_path)
    r = crear(normalizante, destino, fuente, dir_guias=None, coleccion=PREFIJO_PRUEBA + "origen", ahora=AHORA)
    return destino, r


def test_ida_y_vuelta_con_la_normalizacion_de_chromadb(normalizante, fuente, tmp_path):
    destino, r = _respaldo_normalizante(normalizante, fuente, tmp_path)
    rr = restaurar(normalizante, destino, fuente, r.nombre, coleccion=PREFIJO_PRUEBA + "copia")
    assert rr.vectores == 200
    # La normalización cambió el último dígito de algunos componentes: no son iguales bit a bit
    origen, copia = normalizante.abrir(PREFIJO_PRUEBA + "origen"), normalizante.abrir(PREFIJO_PRUEBA + "copia")
    a, b = _registros(origen), _registros(copia)
    assert set(a) == set(b) and sum(a[i].vector != b[i].vector for i in a) > 0
    assert 0 < rr.diferencia_maxima <= TOLERANCIA_VECTOR and rr.diferencia_maxima < 1e-7
    assert all((a[i].texto, a[i].metadatos) == (b[i].texto, b[i].metadatos) for i in a)
    comparacion = comparar(normalizante, PREFIJO_PRUEBA + "origen", PREFIJO_PRUEBA + "copia")
    assert comparacion.identicas and comparacion.consultas == 5
    assert comparacion.diferencia_maxima == rr.diferencia_maxima
    consulta = _unitarios(1, semilla=7)[0].vector
    assert [i for i, _ in copia.consultar(consulta, 5)] == [i for i, _ in origen.consultar(consulta, 5)]


class ServidorQueAltera(ServidorMemoria):
    """Al agregar, altera un registro (vector, longitud, texto o metadatos), para probar que la
    comprobación posterior de restaurar lo detecta."""

    def __init__(self, campo: str):
        super().__init__(normalizar_como_chroma=True)
        self.campo = campo

    def crear(self, nombre, metadatos):
        almacen = super().crear(nombre, metadatos)
        agregar = almacen.agregar

        def alterado(registros):
            agregar([_alterar(r, self.campo) if r.id == "frag-0007" else r for r in registros])

        almacen.agregar = alterado
        return almacen


def _alterar(r: RegistroVector, campo: str) -> RegistroVector:
    if campo == "vector":
        return RegistroVector(r.id, [r.vector[0] + 1e-3] + r.vector[1:], r.texto, r.metadatos)
    if campo == "longitud":
        return RegistroVector(r.id, r.vector[:-1], r.texto, r.metadatos)
    if campo == "texto":
        return RegistroVector(r.id, r.vector, r.texto + " cambiado", r.metadatos)
    return RegistroVector(r.id, r.vector, r.texto, {**r.metadatos, "vigente": "otro"})


@pytest.mark.parametrize("campo", ["vector", "longitud", "texto", "metadatos"])
def test_restaurar_falla_si_lo_restaurado_no_coincide_y_no_borra(normalizante, fuente, tmp_path, campo):
    destino, r = _respaldo_normalizante(normalizante, fuente, tmp_path)
    servidor = ServidorQueAltera(campo)
    nombre = PREFIJO_PRUEBA + "copia"
    with pytest.raises(ErrorRespaldo) as error:
        restaurar(servidor, destino, fuente, r.nombre, coleccion=nombre)
    mensaje = str(error.value)
    assert "1 vectores distintos" in mensaje and "tolerancia de 1e-06" in mensaje
    assert "ya quedó escrita y no se borra sola" in mensaje and f"descartar-coleccion {nombre}" in mensaje
    assert servidor.abrir(nombre).contar() == 200  # no se borró nada


@pytest.mark.parametrize("campo, esperado", [
    ("vector", "vector distinto, fuera de la tolerancia"),
    ("longitud", "vector distinto, fuera de la tolerancia"),
    ("texto", "texto distinto"),
    ("metadatos", "metadatos distinto"),
])
def test_comparar_detecta_un_vector_fuera_de_la_tolerancia_o_un_texto_o_metadato_distinto(normalizante, campo,
                                                                                          esperado):
    origen = normalizante.abrir(PREFIJO_PRUEBA + "origen")
    otra = normalizante.crear(PREFIJO_PRUEBA + "otra", {ESPACIO: "cosine"})
    otra.agregar(origen.obtener(origen.ids()))
    otra.registros["frag-0007"] = _alterar(otra.registros["frag-0007"], campo)
    resultado = comparar(normalizante, PREFIJO_PRUEBA + "origen", PREFIJO_PRUEBA + "otra")
    assert not resultado.identicas
    assert [d for d in resultado.diferencias if esperado in d and "frag-0007" in d] != [], resultado.diferencias


def test_la_salida_informa_la_diferencia_maxima(normalizante, fuente, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "ServidorChroma", lambda url: normalizante)
    monkeypatch.setattr(cli, "_fuente", lambda e: fuente)
    monkeypatch.setenv("RESPALDO_DIR", str(tmp_path))
    _, r = _respaldo_normalizante(normalizante, fuente, tmp_path)
    capsys.readouterr()
    cli.main(["restaurar", r.nombre, "--coleccion", PREFIJO_PRUEBA + "copia"])  # 1: no son fragmentos de PostgreSQL
    salida = capsys.readouterr().out
    patron = re.compile(r"diferencia máxima de \d\.\de-0[78] por la normalización de ChromaDB \(tolerancia 1e-06\)")
    assert "200 vectores, idénticos al respaldo en ids, textos y metadatos; los vectores coinciden con una" in salida
    assert patron.search(salida), salida
    assert cli.main(["comparar", PREFIJO_PRUEBA + "origen", PREFIJO_PRUEBA + "copia"]) == 0
    salida = capsys.readouterr().out
    assert "Las colecciones coinciden: idénticas en ids, textos y metadatos" in salida and patron.search(salida)
    assert "las 5 consultas devuelven los mismos 5 primeros resultados en el mismo orden" in salida
