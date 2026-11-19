"""Parte E1b del Sprint 3: edición de los parámetros de M12 (HU14). PUT por grupo con control optimista
(409), modo de evaluación (423), validaciones duras (422), advertencias con confirmación escrita,
confirmar contra la norma, trigger de inserción de la migración 016, efecto de los cambios en la
clasificación y en la vigencia, y eventos.

Cada prueba que cambia parámetros usa el fixture restaurar: al terminar, con la conexión de
administración (propietaria, exenta de los triggers), borra las versiones creadas y reabre las
cerradas. Nada depende de la hora: las fechas se comparan con now() de la base o con hoy()."""
import json
import re
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.config import get_settings
from app.core.db import engines
from app.core.fechas import hoy
from app.main import app
from app.services import parametros_edicion as edicion
from app.services.clasificacion import clasificar
from app.services.pacientes import dias_vigencia, es_vigente

RAIZ = Path(__file__).resolve().parents[2]
MIGRACION_016 = RAIZ / "db" / "migraciones" / "016_parametros_insercion.sql"
RUTAS = {"puntos_corte": "/api/parametros/puntos-corte", "ajuste_altitud": "/api/parametros/ajuste-altitud",
         "vigencia_tamizaje": "/api/parametros/vigencia-tamizaje"}
TABLAS = {"configuracion.umbral_hemoglobina": "id_umbral", "configuracion.ajuste_altitud": "id_ajuste",
          "configuracion.parametro_sistema": "id_parametro"}
MOTIVO = "Ajuste de prueba según la norma de referencia"
REFERENCIA = "NTS 213-MINSA/DGIESP-2024, Tabla 4, p. 12"


# ---------------------------------------------------------------------------
# Restauración de la configuración
# ---------------------------------------------------------------------------
@pytest.fixture
def restaurar(super_engine):
    """Foto de las tres tablas versionadas; al final, borra las filas nuevas y reabre las cerradas."""
    with super_engine.connect() as c:
        foto = {t: dict(c.execute(text(f"SELECT {col}, vigente_hasta FROM {t}")).all()) for t, col in TABLAS.items()}
    yield
    with super_engine.begin() as c:
        for t, col in TABLAS.items():
            c.execute(text(f"DELETE FROM {t} WHERE NOT ({col} = ANY(:ids))"), {"ids": list(foto[t])})
        for t, col in TABLAS.items():
            actuales = dict(c.execute(text(f"SELECT {col}, vigente_hasta FROM {t}")).all())
            for ident, hasta in foto[t].items():
                if actuales.get(ident) != hasta:
                    c.execute(text(f"UPDATE {t} SET vigente_hasta = :h WHERE {col} = :i"), {"h": hasta, "i": ident})


@pytest.fixture(autouse=True)
def _restaurar_siempre(restaurar):
    """Toda prueba de este archivo restaura la configuración, también las de errores: si una mutación
    quita una barrera, el cambio que se cuela no contamina las pruebas siguientes."""
    yield


def _leer(cliente, cabeceras, usuario="coord.ortiz") -> dict:
    r = cliente.get("/api/parametros", headers=cabeceras(usuario))
    assert r.status_code == 200, r.text
    return r.json()


def _put(cliente, cabeceras, grupo: str, cuerpo: dict, usuario="coord.ortiz"):
    return cliente.put(RUTAS[grupo], json=cuerpo, headers=cabeceras(usuario))


def _comunes(grupo_leido: dict, **extra) -> dict:
    return {"version": grupo_leido["version"], "motivo_cambio": MOTIVO, **extra}


def _cuerpo_vigencia(p: dict, valor, **extra) -> dict:
    return {**_comunes(p["vigencia_tamizaje"]), "valor": valor, **extra}


def _cuerpo_puntos(p: dict, cambios: dict | None = None, verificar: set | None = None, **extra) -> dict:
    """cambios: {(edad_min, categoria): {"hb_min_g_dl": x, ...}}; verificar: {(edad_min, categoria)}."""
    tramos = json.loads(json.dumps(p["puntos_corte"]["tramos"]))
    for t in tramos:
        for c in t["categorias"]:
            clave = (t["edad_min_meses"], c["categoria"])
            c.update((cambios or {}).get(clave, {}))
            if verificar and clave in verificar:
                c["verificado"] = True
    return {**_comunes(p["puntos_corte"]), "tramos": tramos, **extra}


def _cuerpo_ajustes(p: dict, rangos: list | None = None, **extra) -> dict:
    return {**_comunes(p["ajuste_altitud"]), "rangos": rangos if rangos is not None else
            json.loads(json.dumps(p["ajuste_altitud"]["rangos"])), **extra}


def _vigentes(super_engine, tabla: str) -> list[int]:
    col = TABLAS[tabla]
    with super_engine.connect() as c:
        return sorted(c.execute(text(f"SELECT {col} FROM {tabla} WHERE vigente_hasta IS NULL")).scalars())


def _eventos(super_engine, desde: int, tipo: str = "PARAMETRO_CAMBIADO") -> list:
    with super_engine.connect() as c:
        return c.execute(text("""SELECT detalle, entidad, id_usuario::text FROM auditoria.evento_auditoria
                                  WHERE id_evento > :d AND tipo_evento = :t ORDER BY id_evento"""),
                         {"d": desde, "t": tipo}).mappings().all()


def _ultimo_evento(super_engine) -> int:
    with super_engine.connect() as c:
        return c.execute(text("SELECT coalesce(max(id_evento), 0) FROM auditoria.evento_auditoria")).scalar_one()


def _campos(r) -> set:
    return {e["campo"] for e in r.json().get("errores", [])}


# ---------------------------------------------------------------------------
# Permisos
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("grupo", list(RUTAS))
def test_sin_sesion_responde_401(cliente, grupo):
    assert cliente.put(RUTAS[grupo], json={}).status_code == 401


@pytest.mark.parametrize("usuario", ["admin.cdss", "enf.rojas", "med.salazar", "nut.vilca"])
@pytest.mark.parametrize("grupo", list(RUTAS))
def test_solo_el_coordinador_edita(cliente, cabeceras, usuario, grupo, restaurar):
    p = _leer(cliente, cabeceras)
    cuerpo = {"vigencia_tamizaje": _cuerpo_vigencia(p, 45), "puntos_corte": _cuerpo_puntos(p),
              "ajuste_altitud": _cuerpo_ajustes(p)}[grupo]
    r = _put(cliente, cabeceras, grupo, cuerpo, usuario)
    assert r.status_code == 403 and r.json()["detail"] == "Su rol no tiene el permiso CONFIGURAR_PARAMETROS"
    assert _leer(cliente, cabeceras)[grupo]["version"] == p[grupo]["version"]


# ---------------------------------------------------------------------------
# Cambio de la vigencia: efecto, historial, huella, versión y evento
# ---------------------------------------------------------------------------
def test_cambiar_la_vigencia_crea_una_version_y_se_aplica_en_la_consulta_siguiente(cliente, cabeceras, super_engine,
                                                                                 restaurar):
    p = _leer(cliente, cabeceras)
    huella = cliente.get("/api/parametros/huella", headers=cabeceras("coord.ortiz")).json()["huella"]
    hace_40 = hoy() - timedelta(days=40)
    with engines()["clinica"].connect() as c:
        assert dias_vigencia(c) == 30 and es_vigente(hace_40, dias_vigencia(c)) is False
    desde = _ultimo_evento(super_engine)

    r = _put(cliente, cabeceras, "vigencia_tamizaje", _cuerpo_vigencia(p, 45, referencia=REFERENCIA))
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["grupo"]["valor"] == "45" and d["grupo"]["motivo_cambio"] == MOTIVO and d["grupo"]["referencia"] == REFERENCIA
    assert d["grupo"]["version"] != p["vigencia_tamizaje"]["version"]
    assert d["resumen"]["cerrados"] == [p["vigencia_tamizaje"]["id_parametro"]]
    assert d["resumen"]["creados"] == [d["grupo"]["id_parametro"]]
    assert d["resumen"]["cambios"] == [{"elemento": "DIAS_VIGENCIA_TAMIZAJE", "antes": {"valor": "30", "verificado": False},
                                        "despues": {"valor": "45", "verificado": False}}]
    # La consulta siguiente usa la vigencia nueva (no hay caché).
    with engines()["clinica"].connect() as c:
        assert dias_vigencia(c) == 45 and es_vigente(hace_40, dias_vigencia(c)) is True
    # Huella e historial.
    assert cliente.get("/api/parametros/huella", headers=cabeceras("coord.ortiz")).json()["huella"] != huella
    historial = cliente.get("/api/parametros/historial?grupo=vigencia_tamizaje", headers=cabeceras("admin.cdss")).json()
    nueva, cerrada = historial["versiones"][0], next(v for v in historial["versiones"] if v["id"] == d["resumen"]["cerrados"][0])
    assert (nueva["valores"], nueva["vigente"], nueva["motivo_cambio"], nueva["referencia"]) == (
        {"valor": "45"}, True, MOTIVO, REFERENCIA)
    assert nueva["modificado_por"] == cliente.get("/api/auth/me", headers=cabeceras("coord.ortiz")).json()["nombre_completo"]
    assert cerrada["vigente"] is False and cerrada["vigente_hasta"] == nueva["vigente_desde"]
    # Evento sin datos personales.
    eventos = _eventos(super_engine, desde)
    assert len(eventos) == 1 and eventos[0]["entidad"] == "configuracion.parametro_sistema"
    assert set(eventos[0]["detalle"]) == {"grupo", "cerrados", "creados", "cambios", "advertencias_confirmadas",
                                          "motivo_cambio", "referencia", "id_documento"}
    assert eventos[0]["detalle"]["advertencias_confirmadas"] == []


def test_dos_cambios_el_mismo_dia_sobre_la_misma_fila(cliente, cabeceras, super_engine, restaurar):
    p = _leer(cliente, cabeceras)
    primero = _put(cliente, cabeceras, "vigencia_tamizaje", _cuerpo_vigencia(p, 45))
    assert primero.status_code == 200
    segundo = _put(cliente, cabeceras, "vigencia_tamizaje",
                   {**_cuerpo_vigencia(p, 50), "version": primero.json()["grupo"]["version"]})
    assert segundo.status_code == 200, segundo.text
    id_45 = primero.json()["grupo"]["id_parametro"]
    with super_engine.connect() as c:
        desde, hasta = c.execute(text("SELECT vigente_desde, vigente_hasta FROM configuracion.parametro_sistema "
                                      "WHERE id_parametro = :i"), {"i": id_45}).one()
    assert hasta is not None and hasta >= desde
    assert _leer(cliente, cabeceras)["vigencia_tamizaje"]["valor"] == "50"


# ---------------------------------------------------------------------------
# Control optimista (409) y modo de evaluación (423)
# ---------------------------------------------------------------------------
def test_version_vieja_responde_409_y_dos_put_con_la_misma_version_solo_pasa_el_primero(cliente, cabeceras, super_engine,
                                                                                       restaurar):
    p = _leer(cliente, cabeceras)
    cuerpo = _cuerpo_vigencia(p, 45)
    assert _put(cliente, cabeceras, "vigencia_tamizaje", cuerpo).status_code == 200
    vigentes = _vigentes(super_engine, "configuracion.parametro_sistema")
    r = _put(cliente, cabeceras, "vigencia_tamizaje", {**cuerpo, "valor": 50})
    assert r.status_code == 409
    assert r.json()["codigo"] == "VERSION_DESACTUALIZADA"
    assert r.json()["detail"].startswith("Los parámetros cambiaron desde que los abrió")
    assert r.json()["version_actual"] == _leer(cliente, cabeceras)["vigencia_tamizaje"]["version"]
    assert _vigentes(super_engine, "configuracion.parametro_sistema") == vigentes
    assert _leer(cliente, cabeceras)["vigencia_tamizaje"]["valor"] == "45"


@pytest.mark.parametrize("grupo", list(RUTAS))
def test_version_de_otro_grupo_responde_409(cliente, cabeceras, grupo):
    p = _leer(cliente, cabeceras)
    otro = "puntos_corte" if grupo != "puntos_corte" else "ajuste_altitud"
    cuerpo = {"vigencia_tamizaje": _cuerpo_vigencia(p, 45), "puntos_corte": _cuerpo_puntos(p),
              "ajuste_altitud": _cuerpo_ajustes(p)}[grupo]
    r = _put(cliente, cabeceras, grupo, {**cuerpo, "version": p[otro]["version"]})
    assert r.status_code == 409


def test_modo_de_evaluacion_responde_423_sin_cambiar_nada(cliente, cabeceras, super_engine, monkeypatch, restaurar):
    p = _leer(cliente, cabeceras)
    monkeypatch.setattr(get_settings(), "modo_evaluacion", True)
    desde = _ultimo_evento(super_engine)
    for grupo, cuerpo in (("vigencia_tamizaje", _cuerpo_vigencia(p, 45)), ("puntos_corte", _cuerpo_puntos(p)),
                          ("ajuste_altitud", _cuerpo_ajustes(p))):
        r = _put(cliente, cabeceras, grupo, cuerpo)
        assert r.status_code == 423 and r.json()["detail"].startswith("El sistema está en modo de evaluación")
    assert _leer(cliente, cabeceras)["vigencia_tamizaje"]["version"] == p["vigencia_tamizaje"]["version"]
    acciones = [e["detalle"]["accion"] for e in _eventos(super_engine, desde, "PARAMETRO_CAMBIO_BLOQUEADO")]
    assert acciones == ["EDITAR_VIGENCIA_TAMIZAJE", "EDITAR_PUNTOS_CORTE", "EDITAR_AJUSTE_ALTITUD"]
    assert _eventos(super_engine, desde) == []


# ---------------------------------------------------------------------------
# Validación: errores duros
# ---------------------------------------------------------------------------
def test_la_base_sembrada_pasa_su_propia_validacion(cliente, cabeceras):
    p = _leer(cliente, cabeceras)
    for grupo, cuerpo in (("puntos_corte", _cuerpo_puntos(p)), ("ajuste_altitud", _cuerpo_ajustes(p)),
                          ("vigencia_tamizaje", _cuerpo_vigencia(p, p["vigencia_tamizaje"]["valor"]))):
        r = _put(cliente, cabeceras, grupo, cuerpo)
        assert (r.status_code, r.json()["codigo"]) == (422, "SIN_CAMBIOS"), (grupo, r.text)
        assert r.json()["detail"].startswith("No hay cambios")


def _mutar_tramos(p, funcion):
    cuerpo = _cuerpo_puntos(p)
    funcion(cuerpo["tramos"])
    return cuerpo


def _categoria(tramos, edad_min, nombre):
    t = next(t for t in tramos if t["edad_min_meses"] == edad_min)
    return next(c for c in t["categorias"] if c["categoria"] == nombre)


CASOS_PUNTOS = [
    ("tramo distinto", lambda ts: ts[0].update(edad_max_meses=22), "tramos"),
    ("falta una categoría", lambda ts: ts[0]["categorias"].pop(), "tramos.0.categorias"),
    ("dos decimales", lambda ts: _categoria(ts, 24, "SIN_ANEMIA").update(hb_min_g_dl=11.05), "tramos.1.categorias.0.hb_min_g_dl"),
    ("severa con mínimo", lambda ts: _categoria(ts, 6, "ANEMIA_SEVERA").update(hb_min_g_dl=3.0), "tramos.0.categorias.3.hb_min_g_dl"),
    ("sin anemia con máximo", lambda ts: _categoria(ts, 6, "SIN_ANEMIA").update(hb_max_g_dl=15.0), "tramos.0.categorias.0.hb_max_g_dl"),
    ("hueco", lambda ts: _categoria(ts, 6, "ANEMIA_LEVE").update(hb_max_g_dl=10.3), "tramos.0.categorias.0.hb_min_g_dl"),
    ("traslape", lambda ts: _categoria(ts, 24, "ANEMIA_MODERADA").update(hb_max_g_dl=10.2), "tramos.1.categorias.1.hb_min_g_dl"),
    ("fuera de rango", lambda ts: _categoria(ts, 6, "ANEMIA_SEVERA").update(hb_max_g_dl=1.5), "tramos.0.categorias.3.hb_max_g_dl"),
    ("mínimo mayor que máximo", lambda ts: _categoria(ts, 6, "ANEMIA_LEVE").update(hb_min_g_dl=10.6),
     "tramos.0.categorias.1.hb_min_g_dl"),
]


@pytest.mark.parametrize("nombre,mutar,campo", CASOS_PUNTOS, ids=[c[0] for c in CASOS_PUNTOS])
def test_errores_duros_de_los_puntos_de_corte(cliente, cabeceras, super_engine, nombre, mutar, campo):
    p = _leer(cliente, cabeceras)
    vigentes = _vigentes(super_engine, "configuracion.umbral_hemoglobina")
    r = _put(cliente, cabeceras, "puntos_corte", _mutar_tramos(p, mutar))
    assert r.status_code == 422 and r.json()["codigo"] == "VALIDACION", r.text
    assert campo in _campos(r), _campos(r)
    assert r.json()["detail"].startswith("Revise los datos ingresados.")
    assert _vigentes(super_engine, "configuracion.umbral_hemoglobina") == vigentes


def _rangos(p):
    return json.loads(json.dumps(p["ajuste_altitud"]["rangos"]))


CASOS_ALTITUD = [
    ("no empieza en 0", lambda rs: rs[0].update(altitud_min_msnm=1), "rangos.0.altitud_min_msnm"),
    ("hueco", lambda rs: rs[1].update(altitud_min_msnm=501), "rangos.1.altitud_min_msnm"),
    ("traslape", lambda rs: rs[1].update(altitud_min_msnm=499), "rangos.1.altitud_min_msnm"),
    ("cobertura", lambda rs: rs.__delitem__(slice(8, None)), "rangos.7.altitud_max_msnm"),
    ("ajuste fuera de rango", lambda rs: rs[-1].update(ajuste_g_dl=6.5), f"rangos.{10}.ajuste_g_dl"),
    ("dos decimales", lambda rs: rs[1].update(ajuste_g_dl=0.45), "rangos.1.ajuste_g_dl"),
    ("decrece", lambda rs: rs[2].update(ajuste_g_dl=0.3), "rangos.2.ajuste_g_dl"),
]


@pytest.mark.parametrize("nombre,mutar,campo", CASOS_ALTITUD, ids=[c[0] for c in CASOS_ALTITUD])
def test_errores_duros_del_ajuste_por_altitud(cliente, cabeceras, super_engine, nombre, mutar, campo):
    p = _leer(cliente, cabeceras)
    assert len(p["ajuste_altitud"]["rangos"]) == 11
    rangos = _rangos(p)
    mutar(rangos)
    r = _put(cliente, cabeceras, "ajuste_altitud", _cuerpo_ajustes(p, rangos))
    assert r.status_code == 422 and r.json()["codigo"] == "VALIDACION", r.text
    assert campo in _campos(r), _campos(r)


@pytest.mark.parametrize("valor", [100, 6, 91])
def test_errores_duros_de_la_vigencia(cliente, cabeceras, valor):
    p = _leer(cliente, cabeceras)
    r = _put(cliente, cabeceras, "vigencia_tamizaje", _cuerpo_vigencia(p, valor))
    assert r.status_code == 422 and _campos(r) == {"valor"}
    assert "entre 7 y 90" in r.json()["errores"][0]["mensaje"]


@pytest.mark.parametrize("cambios,campo", [
    ({"motivo_cambio": "corto"}, "motivo_cambio"),
    ({"motivo_cambio": "x" * 501}, "motivo_cambio"),
    ({"version": "no-es-una-version"}, "version"),
    ({"id_documento": "00000000-0000-4000-8000-00000000abcd"}, "id_documento"),
    ({"verificado": True}, "referencia"),
])
def test_errores_del_cuerpo_comun(cliente, cabeceras, cambios, campo):
    p = _leer(cliente, cabeceras)
    r = _put(cliente, cabeceras, "vigencia_tamizaje", {**_cuerpo_vigencia(p, 45), **cambios})
    assert r.status_code == 422 and campo in _campos(r), r.text


# ---------------------------------------------------------------------------
# Advertencias y confirmación escrita
# ---------------------------------------------------------------------------
CASOS_ADVERTENCIA = [
    ("límite de Hb cambia más de 1,0", "puntos_corte",
     lambda p: _cuerpo_puntos(p, {(24, "ANEMIA_MODERADA"): {"hb_max_g_dl": 8.5}, (24, "ANEMIA_LEVE"): {"hb_min_g_dl": 8.6}}),
     "tramos.1.categorias.1.hb_min_g_dl"),
    ("sin anemia fuera de 10,0 a 12,0", "puntos_corte",
     lambda p: _cuerpo_puntos(p, {(6, "ANEMIA_LEVE"): {"hb_max_g_dl": 9.8}, (6, "SIN_ANEMIA"): {"hb_min_g_dl": 9.9}}),
     "tramos.0.categorias.0.hb_min_g_dl"),
    ("ajuste cambia más de 0,5", "ajuste_altitud",
     lambda p: _cuerpo_ajustes(p, [*_rangos(p)[:-1], {**_rangos(p)[-1], "ajuste_g_dl": 4.6}]), "rangos.10.ajuste_g_dl"),
    ("vigencia mayor de 60", "vigencia_tamizaje", lambda p: _cuerpo_vigencia(p, 75), "valor"),
]


@pytest.mark.parametrize("nombre,grupo,cuerpo,campo", CASOS_ADVERTENCIA, ids=[c[0] for c in CASOS_ADVERTENCIA])
def test_advertencias_exigen_confirmo(cliente, cabeceras, super_engine, nombre, grupo, cuerpo, campo, restaurar):
    p = _leer(cliente, cabeceras)
    base = cuerpo(p)
    for confirmacion in (None, "confirmo", "SI"):
        r = _put(cliente, cabeceras, grupo, {**base, "confirmacion_escrita": confirmacion})
        assert r.status_code == 422 and r.json()["codigo"] == "REQUIERE_CONFIRMACION", r.text
        assert campo in {a["campo"] for a in r.json()["advertencias"]}
    assert _leer(cliente, cabeceras)[grupo]["version"] == p[grupo]["version"]
    desde = _ultimo_evento(super_engine)
    r = _put(cliente, cabeceras, grupo, {**base, "confirmacion_escrita": "CONFIRMO"})
    assert r.status_code == 200, r.text
    assert r.json()["resumen"]["advertencias_confirmadas"]
    assert _eventos(super_engine, desde)[0]["detalle"]["advertencias_confirmadas"] == r.json()["resumen"]["advertencias_confirmadas"]


# ---------------------------------------------------------------------------
# Confirmar contra la norma
# ---------------------------------------------------------------------------
def test_confirmar_contra_la_norma_crea_una_version_verificada_con_los_mismos_valores(cliente, cabeceras, super_engine,
                                                                                     restaurar):
    p = _leer(cliente, cabeceras)
    previo = _categoria(p["puntos_corte"]["tramos"], 24, "ANEMIA_LEVE")
    sin_referencia = _put(cliente, cabeceras, "puntos_corte", _cuerpo_puntos(p, verificar={(24, "ANEMIA_LEVE")}))
    assert sin_referencia.status_code == 422 and "referencia" in _campos(sin_referencia)
    r = _put(cliente, cabeceras, "puntos_corte", _cuerpo_puntos(p, verificar={(24, "ANEMIA_LEVE")}, referencia=REFERENCIA))
    assert r.status_code == 200, r.text
    resumen = r.json()["resumen"]
    assert resumen["cerrados"] == [previo["id_umbral"]] and len(resumen["creados"]) == 1
    nueva = _categoria(r.json()["grupo"]["tramos"], 24, "ANEMIA_LEVE")
    assert (nueva["hb_min_g_dl"], nueva["hb_max_g_dl"], nueva["verificado"], nueva["referencia"]) == (
        previo["hb_min_g_dl"], previo["hb_max_g_dl"], True, REFERENCIA)
    assert nueva["documento"]["id_documento"] == previo["documento"]["id_documento"]
    # Las demás filas conservan su id.
    otras = {c["id_umbral"] for t in p["puntos_corte"]["tramos"] for c in t["categorias"]} - {previo["id_umbral"]}
    assert otras <= {c["id_umbral"] for t in r.json()["grupo"]["tramos"] for c in t["categorias"]}
    # No se puede quitar la verificación sin cambiar el valor; repetir sin cambios es SIN_CAMBIOS.
    p2 = _leer(cliente, cabeceras)
    quitar = _cuerpo_puntos(p2)
    _categoria(quitar["tramos"], 24, "ANEMIA_LEVE")["verificado"] = False
    r = _put(cliente, cabeceras, "puntos_corte", quitar)
    assert r.status_code == 422 and "tramos.1.categorias.1.verificado" in _campos(r)
    r = _put(cliente, cabeceras, "puntos_corte", {**_cuerpo_puntos(p2), "referencia": REFERENCIA})
    assert r.json()["codigo"] == "SIN_CAMBIOS"


def test_confirmar_la_vigencia_contra_la_norma(cliente, cabeceras, restaurar):
    p = _leer(cliente, cabeceras)
    r = _put(cliente, cabeceras, "vigencia_tamizaje", _cuerpo_vigencia(p, 30, verificado=True, referencia=REFERENCIA))
    assert r.status_code == 200, r.text
    assert (r.json()["grupo"]["valor"], r.json()["grupo"]["verificado"]) == ("30", True)


# ---------------------------------------------------------------------------
# Efecto en la clasificación
# ---------------------------------------------------------------------------
def test_un_punto_de_corte_nuevo_se_aplica_a_tamizajes_nuevos_y_no_a_los_ya_clasificados(cliente, cabeceras, super_engine,
                                                                                       restaurar):
    with super_engine.connect() as c:
        ya_clasificado = c.execute(text("""SELECT id_tamizaje::text, id_umbral, id_ajuste, id_categoria, hb_ajustada_g_dl
                                             FROM clinico.resultado_clasificacion ORDER BY id_tamizaje LIMIT 1""")).one()
    with engines()["clinica"].connect() as c:
        antes = clasificar(c, Decimal("9.9"), 30, 160).clasificacion
    assert antes.categoria == "ANEMIA_MODERADA"
    p = _leer(cliente, cabeceras)
    r = _put(cliente, cabeceras, "puntos_corte",
             _cuerpo_puntos(p, {(24, "ANEMIA_MODERADA"): {"hb_max_g_dl": 9.8}, (24, "ANEMIA_LEVE"): {"hb_min_g_dl": 9.9}}))
    assert r.status_code == 200, r.text
    creados = set(r.json()["resumen"]["creados"])
    with engines()["clinica"].connect() as c:
        despues = clasificar(c, Decimal("9.9"), 30, 160).clasificacion
    assert despues.categoria == "ANEMIA_LEVE" and despues.id_umbral in creados and despues.id_umbral != antes.id_umbral
    with super_engine.connect() as c:
        assert c.execute(text("""SELECT id_tamizaje::text, id_umbral, id_ajuste, id_categoria, hb_ajustada_g_dl
                                   FROM clinico.resultado_clasificacion WHERE id_tamizaje = CAST(:t AS uuid)"""),
                         {"t": ya_clasificado.id_tamizaje}).one() == ya_clasificado


def test_un_ajuste_nuevo_se_aplica_a_tamizajes_nuevos(cliente, cabeceras, restaurar):
    with engines()["clinica"].connect() as c:
        antes = clasificar(c, Decimal("11.5"), 30, 160).clasificacion
    p = _leer(cliente, cabeceras)
    rangos = _rangos(p)
    rangos[0]["ajuste_g_dl"] = 0.1
    r = _put(cliente, cabeceras, "ajuste_altitud", _cuerpo_ajustes(p, rangos))
    assert r.status_code == 200, r.text
    assert r.json()["resumen"]["cerrados"] == [antes.id_ajuste]
    with engines()["clinica"].connect() as c:
        despues = clasificar(c, Decimal("11.5"), 30, 160).clasificacion
    assert despues.id_ajuste in r.json()["resumen"]["creados"] and despues.ajuste_hb_g_dl == Decimal("0.1")
    assert despues.hb_ajustada_g_dl == Decimal("11.4")


def test_un_rango_de_altitud_nuevo_reemplaza_a_los_que_cubria(cliente, cabeceras, restaurar):
    """La tabla puede cambiar de forma: 0 a 999 en un solo rango cierra 0 a 499 y 500 a 999."""
    p = _leer(cliente, cabeceras)
    rangos = _rangos(p)
    nuevo = {**rangos[0], "altitud_max_msnm": 999, "ajuste_g_dl": 0.2}
    r = _put(cliente, cabeceras, "ajuste_altitud", _cuerpo_ajustes(p, [nuevo, *rangos[2:]]))
    assert r.status_code == 200, r.text
    assert sorted(r.json()["resumen"]["cerrados"]) == sorted([rangos[0]["id_ajuste"], rangos[1]["id_ajuste"]])
    grupo = r.json()["grupo"]["rangos"]
    assert (grupo[0]["altitud_min_msnm"], grupo[0]["altitud_max_msnm"], grupo[0]["ajuste_g_dl"]) == (0, 999, 0.2)


# ---------------------------------------------------------------------------
# Transacción: cerrar antes de insertar, y todo o nada
# ---------------------------------------------------------------------------
def test_una_falla_a_mitad_de_la_transaccion_no_deja_filas_cerradas(cabeceras, super_engine, monkeypatch, restaurar):
    cliente = TestClient(app, raise_server_exceptions=False)
    p = _leer(cliente, cabeceras)
    vigentes = _vigentes(super_engine, "configuracion.parametro_sistema")

    def fallar(*_args, **_kwargs):
        raise RuntimeError("falla simulada después de cerrar")

    monkeypatch.setattr(edicion, "insertar_parametro", fallar)
    r = _put(cliente, cabeceras, "vigencia_tamizaje", _cuerpo_vigencia(p, 45))
    assert r.status_code == 500
    assert _vigentes(super_engine, "configuracion.parametro_sistema") == vigentes
    assert _leer(cliente, cabeceras)["vigencia_tamizaje"]["valor"] == "30"


# ---------------------------------------------------------------------------
# Migración 016: trigger de inserción
# ---------------------------------------------------------------------------
INSERTAR = """INSERT INTO configuracion.parametro_sistema (clave, valor, tipo_dato, descripcion, modificado_por,
                                                       vigente_desde, vigente_hasta)
              VALUES ('PRUEBA_E1B', '1', 'ENTERO', 'prueba', '00000000-0000-0000-0000-000000000001', {desde}, {hasta})"""
PREPARAR_ROL = """
CREATE ROLE prueba_insercion_e1b NOLOGIN;
GRANT USAGE ON SCHEMA configuracion TO prueba_insercion_e1b;
GRANT SELECT, INSERT ON configuracion.parametro_sistema TO prueba_insercion_e1b;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA configuracion TO prueba_insercion_e1b;
"""


def _insertar(super_engine, rol: str | None, desde: str, hasta: str = "NULL", preparar: str | None = None) -> int:
    with super_engine.connect() as c:
        try:
            if preparar:
                c.connection.dbapi_connection.cursor().execute(preparar)
            if rol:
                c.execute(text(f"SET LOCAL ROLE {rol}"))
            return c.execute(text(INSERTAR.format(desde=desde, hasta=hasta))).rowcount
        finally:
            c.rollback()


@pytest.mark.parametrize("rol,preparar", [("cdss_admin", None), ("prueba_insercion_e1b", PREPARAR_ROL)])
@pytest.mark.parametrize("desde,hasta,mensaje", [
    ("now()", "now()", "no se puede insertar una versión cerrada"),
    ("now() - interval '2 days'", "NULL", "rige desde hoy"),
    ("now() + interval '2 days'", "NULL", "rige desde hoy"),
])
def test_el_trigger_de_insercion_rechaza_versiones_cerradas_o_fuera_de_hoy(super_engine, rol, preparar, desde, hasta,
                                                                          mensaje):
    with pytest.raises(DBAPIError, match=mensaje):
        _insertar(super_engine, rol, desde, hasta, preparar)


@pytest.mark.parametrize("rol,preparar", [("cdss_admin", None), ("prueba_insercion_e1b", PREPARAR_ROL)])
def test_el_trigger_de_insercion_admite_una_version_vigente_desde_hoy(super_engine, rol, preparar):
    assert _insertar(super_engine, rol, "now()", "NULL", preparar) == 1


def test_el_propietario_esta_exento_del_trigger_de_insercion(super_engine):
    assert _insertar(super_engine, None, "now() - interval '2 days'", "now() - interval '1 day'") == 1


def test_la_migracion_016_se_aplica_dos_veces(super_engine):
    sql = MIGRACION_016.read_text(encoding="utf-8")
    with super_engine.begin() as c:
        cursor = c.connection.dbapi_connection.cursor()  # sin parámetros: los % de los RAISE quedan literales
        cursor.execute(sql)
        cursor.execute(sql)
        triggers = sorted(c.execute(text("""SELECT tgname FROM pg_trigger WHERE NOT tgisinternal
                                              AND tgname LIKE 'tg_%version_nueva'""")).scalars())
    assert triggers == ["tg_ajuste_version_nueva", "tg_parametro_version_nueva", "tg_umbral_version_nueva"]


# ---------------------------------------------------------------------------
# Fixtures del frontend (parte E2)
# ---------------------------------------------------------------------------
DIR_FIXTURES = RAIZ / "frontend" / "src" / "__fixtures__"
_FECHA = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})")
_HEX = re.compile(r'"[0-9a-f]{64}"')


def _normalizar(datos) -> object:
    """Fechas fijas, versiones en orden de aparición e ids de versiones en orden de aparición."""
    texto = _FECHA.sub("2026-10-20T15:00:00Z", json.dumps(datos, ensure_ascii=False))
    versiones: dict[str, str] = {}
    texto = _HEX.sub(lambda m: '"' + versiones.setdefault(m.group(), f"{len(versiones) + 1:064x}") + '"', texto)
    datos = json.loads(texto)
    ids: dict[int, int] = {}

    def recorrer(v, clave=""):
        if isinstance(v, dict):
            return {k: recorrer(x, k) for k, x in v.items()}
        if isinstance(v, list):
            return [recorrer(x, clave) for x in v]
        if clave in ("id_parametro", "id_umbral", "id_ajuste", "cerrados", "creados") and isinstance(v, int):
            return ids.setdefault(v, 1000 + len(ids))
        return v
    return recorrer(datos)


def test_genera_los_fixtures_de_edicion_para_el_frontend(cliente, cabeceras, restaurar):
    p = _leer(cliente, cabeceras)
    salidas = {}
    salidas["parametros_put_confirmacion.json"] = _put(cliente, cabeceras, "vigencia_tamizaje", _cuerpo_vigencia(p, 75)).json()
    salidas["parametros_put_validacion.json"] = _put(cliente, cabeceras, "vigencia_tamizaje", _cuerpo_vigencia(p, 100)).json()
    salidas["parametros_put_sin_cambios.json"] = _put(cliente, cabeceras, "vigencia_tamizaje", _cuerpo_vigencia(p, 30)).json()
    cuerpo = _cuerpo_vigencia(p, 45, referencia=REFERENCIA)
    salidas["parametros_put_cuerpo.json"] = cuerpo
    respuesta = _put(cliente, cabeceras, "vigencia_tamizaje", cuerpo)
    assert respuesta.status_code == 200
    salidas["parametros_put_respuesta.json"] = respuesta.json()
    salidas["parametros_put_conflicto.json"] = _put(cliente, cabeceras, "vigencia_tamizaje", cuerpo).json()
    for archivo, datos in salidas.items():
        (DIR_FIXTURES / archivo).write_text(json.dumps(_normalizar(datos), ensure_ascii=False, indent=2) + "\n",
                                            encoding="utf-8", newline="\n")
