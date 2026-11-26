"""Fila 165: fragmentos garantizados por la clasificación (sección garantizados de punteros.yaml).

Con un tamizaje ANEMIA_SEVERA o que requiere derivación, el fragmento «7. Tratamiento de anemia
severa» de la NTS 213 (página 22) debe estar entre los enviados aunque la pregunta sea de dosis o
controles. Unidad: carga de la regla, (a) severo con pregunta de dosis, (b) severo con pregunta de
derivación (una sola vez), (c) anemia leve sin cambios, (d) fragmento no encontrado sin error,
convivencia con la regla de punteros y la constancia en la solicitud. Base de pruebas: búsqueda
por documento, página y encabezado (no por id), la recuperación completa con y sin la regla, y que
el grafo pasa la clasificación del tamizaje."""
import logging
import re
import uuid
from dataclasses import replace
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from app.rag import grafo as g
from app.rag import punteros as pt
from app.rag import recuperacion as rec
from app.rag import verificacion as ver
from app.rag.normalizacion import normalizar
from app.rag.proteccion import DatosClinicos, construir_solicitud
from tests.test_d1_grafo import _caso_e2e, entorno  # noqa: F401 (fixtures)
from tests.test_g_punteros import REGLA_PRUEBA, _cinco, _destino, _frag, destinos  # noqa: F401 (fixture)
from tests.test_generacion_bd import SISTEMA, consultas, engine_clinica, engine_generacion, guia  # noqa: F401

SEVERO = pt.ContextoClinico("ANEMIA_SEVERA", True)
LEVE = pt.ContextoClinico("ANEMIA_LEVE", False)
NTS = "NTS 213-MINSA/DGIESP-2024"
TEXTO_N7 = ("7. Tratamiento de anemia severa\n- Se indica el tratamiento como un caso de anemia moderada y se refiere "
            "inmediatamente a un establecimiento de salud de mayor capacidad resolutiva.")
REGLA = pt.ReglaGarantizada(
    id="prueba-severa", clasificaciones=frozenset({"ANEMIA_SEVERA"}), con_derivacion=True, documento=NTS, pagina=22,
    encabezado="7. Tratamiento de anemia severa", patron=pt._patron_encabezado("7. Tratamiento de anemia severa"))


def _fila_n7(id_: str = "n7"):
    return SimpleNamespace(id_fragmento=id_, id_documento="doc-nts", titulo="NTS 213", codigo_documento=NTS,
                           idioma="es", seccion="Tratamiento", pagina_inicio=22, pagina_fin=22, texto=TEXTO_N7,
                           tipo_contenido="TEXTO", edad_min_meses=None, edad_max_meses=None, poblacion="GENERAL",
                           rango_dudoso=False, numero_tokens=155)


@pytest.fixture
def n7(monkeypatch):
    """buscar_garantizado de prueba: devuelve el fragmento N7 y cuenta las búsquedas."""
    llamadas = []

    def buscar(sesion, regla):
        llamadas.append(regla.id)
        return _fila_n7()
    monkeypatch.setattr(rec, "buscar_garantizado", buscar)
    return llamadas


def _ids(fragmentos) -> list[str]:
    return [f.id_fragmento for f in fragmentos if f.seleccionado]


# ---------------------------------------------------------------------------
# Unidad
# ---------------------------------------------------------------------------
def test_la_regla_de_anemia_severa_carga_de_punteros_yaml():
    (regla,) = pt.cargar_garantizadas()
    assert (regla.id, regla.documento, regla.pagina, regla.encabezado) == (
        "nts213-anemia-severa-derivacion", NTS, 22, "7. Tratamiento de anemia severa")
    assert regla.aplica_a(SEVERO) and regla.aplica_a(pt.ContextoClinico("ANEMIA_SEVERA", False))
    assert regla.aplica_a(pt.ContextoClinico("ANEMIA_MODERADA", True))  # requiere derivación
    assert not regla.aplica_a(LEVE) and not regla.aplica_a(None)
    # El encabezado al inicio de una línea, sin distinguir mayúsculas ni espacios.
    assert regla.patron.search(TEXTO_N7)
    assert regla.patron.search("texto previo\n7.  TRATAMIENTO DE\nanemia severa\n- Se indica")
    assert not regla.patron.search("17. Tratamiento de anemia severa")
    assert not regla.patron.search("ver el numeral 7. Tratamiento de anemia severa")
    # La regla de punteros de la Tabla 4 sigue cargando del mismo archivo.
    assert [r.id for r in pt.cargar_reglas()] == ["nts213-tabla4"]


def test_una_regla_garantizada_sin_condicion_no_carga(tmp_path):
    ruta = tmp_path / "punteros.yaml"
    ruta.write_text("garantizados:\n  - {id: x, documento: NTS, pagina: 22, encabezado: '7. Algo'}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="no tiene clasificaciones"):
        pt.cargar_garantizadas(ruta)


def test_a_severo_con_pregunta_de_dosis_el_criterio_entra_quinto(n7):
    """(a) Los cinco enviados son de dosis y controles: N7 entra en el lugar del 5.º y los cuatro
    anteriores no se mueven."""
    fragmentos, _ = rec.aplicar_garantizados(None, _cinco(), [], 5, (REGLA,), SEVERO)
    assert _ids(fragmentos) == ["f0", "f1", "f2", "f3", "n7"]
    agregado = next(f for f in fragmentos if f.id_fragmento == "n7")
    assert agregado.origen == pt.PUNTERO and agregado.referido_por is None and agregado.regla_puntero == "prueba-severa"
    assert (agregado.codigo_documento, agregado.pagina_inicio) == (NTS, 22)
    assert not next(f for f in fragmentos if f.id_fragmento == "f4").seleccionado
    assert all(f.origen == pt.RERANKER for f in fragmentos if f.id_fragmento != "n7")


def test_a_un_criterio_no_evaluado_conserva_su_posicion_rrf(n7):
    """Caso real del 14/11: N7 quedó en el puesto 14 de la fusión, sin pasar por el reranker."""
    sin_evaluar = [_frag("n7", None, False, NTS, TEXTO_N7, posicion_rrf=14)]
    fragmentos, no_evaluados = rec.aplicar_garantizados(None, _cinco(), sin_evaluar, 5, (REGLA,), SEVERO)
    assert no_evaluados == [] and _ids(fragmentos)[-1] == "n7"
    assert next(f for f in fragmentos if f.id_fragmento == "n7").posicion_rrf == 14
    assert [f.id_fragmento for f in fragmentos].count("n7") == 1


def test_b_severo_con_pregunta_de_derivacion_no_duplica(n7):
    """(b) N7 ya está entre los enviados (4.º): no cambia nada y aparece una sola vez."""
    fr = _cinco()
    fr[3] = _frag("n7", 0.875, True, NTS, TEXTO_N7, posicion_rrf=4)
    antes = [(f.id_fragmento, f.seleccionado, f.origen) for f in fr]
    fragmentos, _ = rec.aplicar_garantizados(None, fr, [], 5, (REGLA,), SEVERO)
    assert [(f.id_fragmento, f.seleccionado, f.origen) for f in fragmentos] == antes
    assert [f.id_fragmento for f in fragmentos].count("n7") == 1


def test_c_anemia_leve_no_cambia_ni_busca(n7):
    """(c) Con anemia leve (o sin contexto) el resultado es el mismo y no se consulta la base."""
    for contexto in (LEVE, None):
        fr = _cinco()
        antes = [(f.id_fragmento, f.seleccionado, f.origen) for f in fr]
        fragmentos, _ = rec.aplicar_garantizados(None, fr, [], 5, (REGLA,), contexto)
        assert [(f.id_fragmento, f.seleccionado, f.origen) for f in fragmentos] == antes
    assert n7 == []


def test_d_fragmento_no_encontrado_sigue_con_una_advertencia(monkeypatch, caplog):
    """(d) Sin el fragmento (o si la búsqueda falla) la recuperación sigue igual y queda una advertencia."""
    for buscar in (lambda s, r: None, lambda s, r: (_ for _ in ()).throw(RuntimeError("sin base"))):
        monkeypatch.setattr(rec, "buscar_garantizado", buscar)
        caplog.clear()
        fr = _cinco()
        antes = [(f.id_fragmento, f.seleccionado) for f in fr]
        with caplog.at_level(logging.WARNING, logger=rec.__name__):
            fragmentos, _ = rec.aplicar_garantizados(None, fr, [], 5, (REGLA,), SEVERO)
        assert [(f.id_fragmento, f.seleccionado) for f in fragmentos] == antes
        assert any("prueba-severa" in r.getMessage() for r in caplog.records)


def test_con_menos_de_cinco_se_agrega_sin_quitar(n7):
    fr = [_frag("f0", 0.9, True), _frag("f1", 0.6, True), _frag("f2", 0.1, False)]
    fragmentos, _ = rec.aplicar_garantizados(None, fr, [], 5, (REGLA,), SEVERO)
    assert _ids(fragmentos) == ["f0", "f1", "n7"]


def test_sin_enviados_del_reranker_no_agrega(n7):
    """Sin fragmentos sobre el umbral la búsqueda no fue suficiente (6.3): la regla no la vuelve suficiente."""
    fr = [_frag("f0", 0.1, False), _frag("f1", 0.05, False)]
    fragmentos, _ = rec.aplicar_garantizados(None, fr, [], 5, (REGLA,), SEVERO)
    assert _ids(fragmentos) == [] and n7 == []


def test_con_un_solo_enviado_no_hay_lugar(n7):
    fragmentos, _ = rec.aplicar_garantizados(None, [_frag("f0", 0.9, True)], [], 1, (REGLA,), SEVERO)
    assert _ids(fragmentos) == ["f0"]


def test_no_saca_al_agregado_por_puntero_ni_a_su_referente(destinos, n7):  # noqa: F811
    """Con la Tabla 4 ya agregada por su puntero, N7 sale del lugar del último enviado del reranker
    que no contiene el puntero; el puntero y su referente siguen."""
    fragmentos, no_evaluados = rec.aplicar_punteros(None, _cinco(con_puntero_en=3), [], 5, (REGLA_PRUEBA,))
    assert _ids(fragmentos) == ["f0", "f1", "f2", "f3", "destino"]
    fragmentos, _ = rec.aplicar_garantizados(None, fragmentos, no_evaluados, 5, (REGLA,), SEVERO)
    assert _ids(fragmentos) == ["f0", "f1", "f3", "destino", "n7"]
    assert next(f for f in fragmentos if f.id_fragmento == "destino").referido_por == "f3"


def _datos(clasificacion: str = "ANEMIA_SEVERA") -> DatosClinicos:
    return DatosClinicos(edad_meses=26, sexo="M", altitud_msnm=None, hb_observada_g_dl=6.8, hb_ajustada_g_dl=6.8,
                         clasificacion=clasificacion, nivel_riesgo="MUY_ALTO", requiere_derivacion=True, peso_kg=11.0,
                         suplementacion_hierro=False, lactancia_materna_actual=False, parasitosis_reciente=False,
                         bajo_peso_nacer=False, edad_gestacional="A_TERMINO", sintomas=(), tamizaje_anterior=None)


def test_la_solicitud_no_inventa_una_referencia_y_6_1_acepta_citarlo(n7):
    fragmentos, _ = rec.aplicar_garantizados(None, _cinco(), [], 5, (REGLA,), SEVERO)
    enviados = [f for f in fragmentos if f.seleccionado]
    solicitud = construir_solicitud(_datos(), "consulta", "es", enviados, {})
    evidencia = solicitud.contenido["evidencia"]
    assert evidencia[-1]["etiqueta"] == "F-05" and evidencia[-1]["texto"] == TEXTO_N7
    assert all("agregado_por_referencia_de" not in e for e in evidencia)
    respuesta = {"clasificacion_confirmada": "ANEMIA_SEVERA", "nivel_riesgo": "MUY_ALTO", "evidencia_suficiente": True,
                 "resumen": "r", "advertencias": [], "factores_identificados": [],
                 "recomendacion": [{"texto": "Referir de inmediato a un establecimiento de mayor capacidad.",
                                    "tipo": "DERIVACION", "citas": ["F-05"]}],
                 "citas": [{"etiqueta": "F-05", "extracto": "se refiere inmediatamente a un establecimiento de salud",
                            "extracto_traducido": None}]}
    v = ver.verificar(respuesta, solicitud, _datos(), 0.9, 0.15, {f.id_fragmento for f in enviados})
    assert v.valida_citas and v.valida_evidencia, v.motivos


# ---------------------------------------------------------------------------
# Base de pruebas
# ---------------------------------------------------------------------------
CODIGO = "PRUEBA-GAR-NTS"


def _insertar(c, fragmentos: list[tuple[int, int, str, bool]]) -> list[str]:
    """Documento CODIGO (fuera de la colección vectorial) con fragmentos (página inicio, página fin, texto, vigente)."""
    id_doc = str(uuid.uuid4())
    c.execute(text(
        """INSERT INTO conocimiento.documento_fuente
             (id_documento, titulo, codigo_documento, entidad_emisora, tipo_documento, nivel, anio_publicacion,
              idioma, cargado_por, estado_indexacion, ruta_blob, hash_archivo, total_fragmentos)
           VALUES (:id, 'Guía de prueba garantizados', :cod, 'MINSA', 'GUIA', 1, 2024, 'es', :u, 'COMPLETADA',
                   'local://prueba/gar.pdf', :h, :n)"""),
        {"id": id_doc, "cod": CODIGO, "u": SISTEMA, "h": uuid.uuid4().hex * 2, "n": len(fragmentos)})
    ids = []
    for orden, (inicio, fin, texto, vigente) in enumerate(fragmentos, start=1):
        ids.append(str(uuid.uuid4()))
        c.execute(text(
            """INSERT INTO conocimiento.fragmento (id_fragmento, id_documento, numero_orden, seccion, pagina_inicio,
                 pagina_fin, texto, numero_tokens, modelo_embedding, vigente, motivo_exclusion, tipo_contenido)
               VALUES (:id, :doc, :o, 'Tratamiento', :pi, :pf, :t, 150, 'falso', :v, :m, 'TEXTO')"""),
            {"id": ids[-1], "doc": id_doc, "o": orden, "pi": inicio, "pf": fin, "t": texto, "v": vigente,
             "m": None if vigente else "Sustituido (prueba)"})
    return ids


def _borrar(c) -> None:
    fragmentos = """(SELECT f.id_fragmento FROM conocimiento.fragmento f JOIN conocimiento.documento_fuente d
                       USING (id_documento) WHERE d.codigo_documento = :cod)"""
    c.execute(text(f"DELETE FROM asistencia.cita_evidencia WHERE id_fragmento IN {fragmentos}"), {"cod": CODIGO})
    c.execute(text(f"DELETE FROM asistencia.fragmento_recuperado WHERE id_fragmento IN {fragmentos}"), {"cod": CODIGO})
    c.execute(text(f"DELETE FROM conocimiento.fragmento WHERE id_fragmento IN {fragmentos}"), {"cod": CODIGO})
    c.execute(text("DELETE FROM conocimiento.documento_fuente WHERE codigo_documento = :cod"), {"cod": CODIGO})


@pytest.fixture
def documento_gar(super_engine):
    with super_engine.begin() as c:
        _borrar(c)
        ids = _insertar(c, [
            (21, 22, "Texto previo de la página 21 que sigue en la 22, sin el encabezado.", True),
            (22, 22, TEXTO_N7, True),
            (22, 22, "10. Referencia a establecimiento de mayor capacidad resolutiva", True),
            (22, 22, "17. Tratamiento de anemia severa en otro numeral", True),
            (23, 23, TEXTO_N7.replace("severa\n", "severa (copia de otra página)\n"), True),
            (22, 22, "7. Tratamiento de anemia severa (texto sustituido, no vigente)", False),
        ])
    yield {"n7": ids[1], "copia_no_vigente": ids[5]}
    with super_engine.begin() as c:
        _borrar(c)


def test_busca_por_documento_pagina_y_encabezado(engine_generacion, documento_gar):
    regla = replace(REGLA, documento=CODIGO)
    with engine_generacion.connect() as c:
        assert pt.buscar_garantizado(c, regla).id_fragmento == documento_gar["n7"]
        assert pt.buscar_garantizado(c, replace(regla, pagina=21)) is None   # la página no tiene el encabezado
        assert pt.buscar_garantizado(c, replace(regla, documento="OTRO")) is None


def test_dos_coincidencias_no_agregan_nada(super_engine, engine_generacion, documento_gar):
    with super_engine.begin() as c:
        c.execute(text("UPDATE conocimiento.fragmento SET vigente = true, motivo_exclusion = NULL "
                       "WHERE id_fragmento = CAST(:f AS uuid)"), {"f": documento_gar["copia_no_vigente"]})
    with engine_generacion.connect() as c:
        assert pt.buscar_garantizado(c, replace(REGLA, documento=CODIGO)) is None


CONSULTA_DOSIS = "¿Qué dosis de hierro le corresponde y cada cuánto se controla la hemoglobina?"


def _recuperar(entorno, engine_generacion, monkeypatch, reglas, contexto):  # noqa: F811
    monkeypatch.setattr(rec, "garantizadas_vigentes", lambda: reglas)
    with engine_generacion.connect() as c:
        return rec.recuperar(c, normalizar(CONSULTA_DOSIS), entorno.servicios,
                             replace(entorno.parametros, fragmentos_enviados=5), edad_meses=26, contexto=contexto)


def test_recuperacion_severa_con_pregunta_de_dosis_envia_el_criterio(entorno, engine_generacion, documento_gar,  # noqa: F811
                                                                     monkeypatch):
    regla = replace(REGLA, documento=CODIGO)
    sin = _recuperar(entorno, engine_generacion, monkeypatch, (), SEVERO)
    con = _recuperar(entorno, engine_generacion, monkeypatch, (regla,), SEVERO)
    assert documento_gar["n7"] not in [f.id_fragmento for f in sin.seleccionados]
    assert con.seleccionados[-1].id_fragmento == documento_gar["n7"]
    assert [f.id_fragmento for f in con.seleccionados].count(documento_gar["n7"]) == 1
    assert len(con.seleccionados) <= 5
    # Los anteriores no se mueven y la relevancia y la suficiencia (6.3) no cambian.
    assert [f.id_fragmento for f in con.seleccionados[:-1]] == [f.id_fragmento for f in sin.seleccionados][
        :len(con.seleccionados) - 1]
    assert (con.relevancia_maxima, con.suficiente) == (sin.relevancia_maxima, sin.suficiente)
    # (b) una segunda aplicación sobre el resultado no lo duplica.
    fragmentos, _ = rec.aplicar_garantizados(None, con.fragmentos, con.no_evaluados, 5, (regla,), SEVERO)
    assert [f.id_fragmento for f in fragmentos if f.seleccionado].count(documento_gar["n7"]) == 1


def test_recuperacion_leve_y_sin_fragmento_no_cambia(entorno, engine_generacion, documento_gar,  # noqa: F811
                                                     monkeypatch, caplog):
    regla = replace(REGLA, documento=CODIGO)
    sin = _recuperar(entorno, engine_generacion, monkeypatch, (), LEVE)
    leve = _recuperar(entorno, engine_generacion, monkeypatch, (regla,), LEVE)
    with caplog.at_level(logging.WARNING, logger=rec.__name__):
        ausente = _recuperar(entorno, engine_generacion, monkeypatch, (replace(regla, documento="NO-EXISTE"),), SEVERO)
    clave = [(f.id_fragmento, f.seleccionado, f.origen) for f in sin.fragmentos]
    assert [(f.id_fragmento, f.seleccionado, f.origen) for f in leve.fragmentos] == clave
    assert [(f.id_fragmento, f.seleccionado, f.origen) for f in ausente.fragmentos] == clave
    assert any("prueba-severa" in r.getMessage() for r in caplog.records)


def test_el_grafo_pasa_la_clasificacion_del_tamizaje(entorno, consultas, super_engine, monkeypatch):  # noqa: F811
    vistos = []
    original = g.recuperar_fragmentos

    def espia(*args, **kwargs):
        vistos.append(args[6] if len(args) > 6 else kwargs.get("contexto"))
        return original(*args, **kwargs)
    monkeypatch.setattr(g, "recuperar_fragmentos", espia)
    severo = _caso_e2e(entorno, consultas, super_engine, "d")[-1]
    leve = _caso_e2e(entorno, consultas, super_engine, "b")[-1]
    assert severo["tipo"] == "fin" and leve["tipo"] == "fin", (severo, leve)
    assert vistos[0] == pt.ContextoClinico("ANEMIA_SEVERA", True)
    assert vistos[-1] == pt.ContextoClinico("ANEMIA_LEVE", False)
    assert re.fullmatch(r"[0-9a-f-]{36}", severo["id_consulta"])
