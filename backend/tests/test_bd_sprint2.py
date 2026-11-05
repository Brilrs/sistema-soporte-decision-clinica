"""Sprint 2: migración idempotente, ajuste por altitud de la RM 429-2024/MINSA,
parámetros del modelo de lenguaje y mínimo privilegio de los componentes de
generación e indexación."""
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, ProgrammingError

from app.core.db import engines
from app.services.clasificacion import clasificar

MIGRACION = Path(__file__).resolve().parents[2] / "db" / "migraciones" / "001_sprint2.sql"
SISTEMA = "00000000-0000-0000-0000-000000000001"
NTS_213 = "10000000-0000-0000-0000-000000000213"
RM_429 = "10000000-0000-0000-0000-000000000429"
ESQUEMAS = "('seguridad','clinico','asistencia','conocimiento','configuracion','auditoria')"

FOTO = f"""
SELECT 'col '||table_schema||'.'||table_name||'.'||column_name||' '||data_type||' '||is_nullable||' '||coalesce(column_default,'')
  FROM information_schema.columns WHERE table_schema IN {ESQUEMAS}
UNION ALL SELECT 'con '||conrelid::regclass||' '||conname||' '||pg_get_constraintdef(oid)
  FROM pg_constraint WHERE connamespace::regnamespace::text IN {ESQUEMAS}
UNION ALL SELECT 'idx '||schemaname||'.'||indexname||' '||indexdef FROM pg_indexes WHERE schemaname IN {ESQUEMAS}
UNION ALL SELECT 'tgr '||grantee||' '||table_schema||'.'||table_name||' '||privilege_type
  FROM information_schema.role_table_grants WHERE grantee LIKE 'rol_%'
UNION ALL SELECT 'cgr '||grantee||' '||table_schema||'.'||table_name||'.'||column_name||' '||privilege_type
  FROM information_schema.column_privileges WHERE grantee LIKE 'rol_%'
UNION ALL SELECT 'doc '||id_documento||' '||titulo||' '||coalesce(fecha_publicacion::text,'')||' '||idioma||' '
       ||coalesce(ruta_blob,'')||' '||coalesce(hash_archivo,'') FROM conocimiento.documento_fuente
UNION ALL SELECT 'par '||id_parametro||' '||clave||'='||valor||' '||coalesce(vigente_hasta::text,'vigente')
  FROM configuracion.parametro_sistema
UNION ALL SELECT 'alt '||id_ajuste||' '||altitud_min_msnm||'-'||altitud_max_msnm||'='||ajuste_g_dl||' '
       ||coalesce(vigente_hasta::text,'vigente') FROM configuracion.ajuste_altitud
ORDER BY 1"""


def _foto(super_engine) -> list[str]:
    with super_engine.connect() as c:
        return list(c.execute(text(FOTO)).scalars())


def _aplicar_migracion(super_engine) -> None:
    crudo = super_engine.raw_connection()
    try:
        with crudo.cursor() as cur:
            cur.execute(MIGRACION.read_text(encoding="utf-8"))
        crudo.commit()
    finally:
        crudo.close()


def _ejecutar(engine, sql: str, rol: str | None = None) -> None:
    """Ejecuta la sentencia en una transacción que siempre se deshace."""
    with engine.connect() as c:
        try:
            if rol:
                c.execute(text(f"SET LOCAL ROLE {rol}"))
            c.execute(text(sql))
        finally:
            c.rollback()


# ---------------------------------------------------------------------------
# Migración
# ---------------------------------------------------------------------------
def test_la_migracion_es_idempotente(super_engine):
    antes = _foto(super_engine)
    _aplicar_migracion(super_engine)
    _aplicar_migracion(super_engine)
    assert _foto(super_engine) == antes


# ---------------------------------------------------------------------------
# Documentos fuente
# ---------------------------------------------------------------------------
def test_documentos_de_la_nts_213_y_su_modificatoria():
    with engines()["clinica"].connect() as c:
        filas = c.execute(text("SELECT * FROM conocimiento.documento_fuente")).all()
    docs = {str(f.id_documento): f for f in filas}
    nts, rm = docs[NTS_213], docs[RM_429]
    assert (nts.fecha_publicacion, nts.version, nts.pagina_inicio_cuerpo, nts.pagina_fin_cuerpo) == (
        date(2024, 4, 8), "RM 251-2024/MINSA", 4, 36)
    assert (rm.tipo_documento, rm.nivel, rm.anio_publicacion, rm.fecha_publicacion, rm.estado) == (
        "RESOLUCION", 1, 2024, date(2024, 6, 18), "VIGENTE")
    assert (rm.pagina_inicio_cuerpo, rm.pagina_fin_cuerpo, rm.idioma) == (4, 11, "es")
    assert {docs[d].idioma for d in docs if docs[d].entidad_emisora == "OMS"} == {"en"}


def test_un_documento_indexado_exige_ruta_y_hash(super_engine):
    with pytest.raises(DBAPIError):
        _ejecutar(super_engine, f"""UPDATE conocimiento.documento_fuente
                                       SET estado_indexacion = 'COMPLETADA', ruta_blob = NULL, hash_archivo = NULL
                                     WHERE id_documento = '{RM_429}'""")


# ---------------------------------------------------------------------------
# Ajuste por altitud
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("altitud, ajuste", [
    (4499, "2.9"), (4500, "3.3"), (4999, "3.3"), (5000, "4.0"), (5500, "4.0"),
])
def test_ajuste_por_altitud_de_la_rm_429(altitud, ajuste):
    with engines()["clinica"].connect() as c:
        ev = clasificar(c, Decimal("15.0"), 24, altitud)
    assert ev.clasificacion is not None, ev.motivo
    assert ev.clasificacion.ajuste_hb_g_dl == Decimal(ajuste)


def test_los_dos_rangos_altos_se_atribuyen_a_la_rm_429():
    with engines()["clinica"].connect() as c:
        filas = c.execute(text("""SELECT altitud_min_msnm, altitud_max_msnm, ajuste_g_dl, id_documento::text
                                    FROM configuracion.ajuste_altitud
                                   WHERE vigente_hasta IS NULL AND altitud_min_msnm >= 4500
                                   ORDER BY altitud_min_msnm""")).all()
    assert [tuple(f) for f in filas] == [(4500, 4999, Decimal("3.3"), RM_429), (5000, 5500, Decimal("4.0"), RM_429)]


def test_la_clasificacion_ignora_los_ajustes_cerrados(super_engine):
    """Un rango cerrado que se superpone con todos los vigentes no debe aplicarse."""
    with super_engine.begin() as c:
        id_cerrado = c.execute(text(f"""INSERT INTO configuracion.ajuste_altitud
                                          (id_documento, altitud_min_msnm, altitud_max_msnm, ajuste_g_dl,
                                           vigente_desde, vigente_hasta, modificado_por)
                                        VALUES ('{RM_429}', 0, 5500, 9.9, now() - interval '2 days',
                                                now() - interval '1 day', '{SISTEMA}')
                                        RETURNING id_ajuste""")).scalar_one()
    try:
        with engines()["clinica"].connect() as c:
            for altitud in (100, 4700, 5200):
                ev = clasificar(c, Decimal("15.0"), 24, altitud)
                assert ev.clasificacion.id_ajuste != id_cerrado
                assert ev.clasificacion.ajuste_hb_g_dl != Decimal("9.9")
    finally:
        with super_engine.begin() as c:
            c.execute(text("DELETE FROM configuracion.ajuste_altitud WHERE id_ajuste = :i"), {"i": id_cerrado})


# ---------------------------------------------------------------------------
# Parámetros del sistema
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def parametros():
    with engines()["clinica"].connect() as c:
        return c.execute(text("""SELECT clave, valor, tipo_dato, vigente_hasta
                                   FROM configuracion.parametro_sistema""")).mappings().all()


def _vigente(parametros, clave):
    vigentes = [p for p in parametros if p["clave"] == clave and p["vigente_hasta"] is None]
    assert len(vigentes) <= 1
    return vigentes[0] if vigentes else None


def test_modelo_llm_vigente(parametros):
    assert _vigente(parametros, "MODELO_LLM")["valor"] == "claude-sonnet-5-5"


def test_temperatura_cerrada_con_historial(parametros):
    assert _vigente(parametros, "TEMPERATURA_LLM") is None
    assert any(p["clave"] == "TEMPERATURA_LLM" for p in parametros)


@pytest.mark.parametrize("clave, valor, tipo", [
    ("PRECIO_ENTRADA_USD_MTOK", "2.00", "DECIMAL"),
    ("PRECIO_SALIDA_USD_MTOK", "10.00", "DECIMAL"),
    ("MODELO_RESPALDO", "", "TEXTO"),
    ("IDIOMA_RESPUESTA_DEFECTO", "es", "TEXTO"),
])
def test_parametros_nuevos(parametros, clave, valor, tipo):
    p = _vigente(parametros, clave)
    assert (p["valor"], p["tipo_dato"]) == (valor, tipo)


def test_umbral_de_dominio_provisional(parametros):
    p = _vigente(parametros, "UMBRAL_DOMINIO")
    assert p["tipo_dato"] == "DECIMAL" and 0 <= Decimal(p["valor"]) <= 1


# ---------------------------------------------------------------------------
# Permisos del componente de generación (cdss_generacion)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("sql", [
    "SELECT texto_consulta FROM asistencia.consulta LIMIT 1",
    "SELECT * FROM asistencia.consulta LIMIT 1",
    "SELECT observaciones FROM clinico.tamizaje LIMIT 1",
    "SELECT * FROM clinico.tamizaje LIMIT 1",
    "SELECT 1 FROM clinico.paciente_identidad LIMIT 1",
    "SELECT 1 FROM conocimiento.trabajo_indexacion LIMIT 1",
    "UPDATE asistencia.consulta SET texto_consulta = 'x' WHERE false",
    "UPDATE asistencia.consulta SET texto_filtrado = 'x' WHERE false",
    "UPDATE asistencia.consulta SET confirma_tamizaje_no_vigente = true WHERE false",
    "UPDATE asistencia.consulta SET idioma_respuesta = 'en' WHERE false",
    "INSERT INTO asistencia.consulta (id_tamizaje, id_usuario, texto_consulta) SELECT NULL, NULL, 'x' WHERE false",
    "UPDATE clinico.tamizaje SET peso_kg = peso_kg WHERE false",
])
def test_generacion_no_accede_a_lo_prohibido(sql):
    with pytest.raises(ProgrammingError, match="permission denied"):
        _ejecutar(engines()["generacion"], sql)


@pytest.mark.parametrize("sql", [
    """SELECT id_consulta, id_consulta_previa, id_tamizaje, id_usuario, texto_filtrado, estado, numero_intentos,
              fecha_hora_inicio, fecha_hora_fin, latencia_total_ms, confirma_tamizaje_no_vigente, idioma_respuesta
         FROM asistencia.consulta LIMIT 1""",
    """SELECT id_tamizaje, id_paciente, fecha_tamizaje, edad_meses, hemoglobina_g_dl, peso_kg, talla_cm,
              recibe_suplementacion_hierro, lactancia_materna_actual, parasitosis_reciente
         FROM clinico.tamizaje LIMIT 1""",
    "SELECT count(*) FROM clinico.tamizaje",
    "SELECT * FROM asistencia.v_historial_hemoglobina LIMIT 1",
    "SELECT * FROM clinico.resultado_clasificacion LIMIT 1",
    "SELECT * FROM clinico.tamizaje_sintoma JOIN clinico.sintoma USING (id_sintoma) LIMIT 1",
    "SELECT sexo, bajo_peso_nacer, edad_gestacional_nacer FROM clinico.paciente LIMIT 1",
    "SELECT * FROM conocimiento.fragmento LIMIT 1",
    "SELECT * FROM configuracion.parametro_sistema LIMIT 1",
    """UPDATE asistencia.consulta SET estado = estado, numero_intentos = numero_intentos,
              fecha_hora_fin = fecha_hora_fin, latencia_total_ms = latencia_total_ms WHERE false""",
    "INSERT INTO auditoria.evento_auditoria (tipo_evento) VALUES ('PRUEBA_PERMISOS')",
])
def test_generacion_lee_y_escribe_lo_necesario(sql):
    _ejecutar(engines()["generacion"], sql)


# ---------------------------------------------------------------------------
# Permisos del indexador (cdss_indexador)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("sql", [
    "SELECT 1 FROM clinico.paciente LIMIT 1",
    "SELECT 1 FROM clinico.tamizaje LIMIT 1",
    "SELECT 1 FROM seguridad.usuario LIMIT 1",
    "SELECT 1 FROM asistencia.consulta LIMIT 1",
    "SELECT 1 FROM configuracion.umbral_hemoglobina LIMIT 1",
    "SELECT 1 FROM auditoria.evento_auditoria LIMIT 1",
    "DELETE FROM conocimiento.fragmento WHERE false",
    "DELETE FROM conocimiento.trabajo_indexacion WHERE false",
    "DELETE FROM conocimiento.documento_fuente WHERE false",
    "DELETE FROM auditoria.evento_auditoria WHERE false",
    "UPDATE auditoria.evento_auditoria SET tipo_evento = tipo_evento WHERE false",
    "UPDATE conocimiento.documento_fuente SET titulo = titulo WHERE false",
    "UPDATE conocimiento.documento_fuente SET estado = 'OBSOLETA' WHERE false",
    "UPDATE conocimiento.documento_fuente SET nivel = 2 WHERE false",
    f"""INSERT INTO conocimiento.documento_fuente (titulo, entidad_emisora, tipo_documento, nivel,
                                                  anio_publicacion, cargado_por)
        VALUES ('x', 'OTRA', 'GUIA', 2, 2024, '{SISTEMA}')""",
    "UPDATE configuracion.parametro_sistema SET valor = valor WHERE false",
])
def test_indexador_no_accede_a_lo_prohibido(super_engine, sql):
    with pytest.raises(ProgrammingError, match="permission denied"):
        _ejecutar(super_engine, sql, rol="cdss_indexador")


@pytest.mark.parametrize("sql", [
    "SELECT * FROM conocimiento.documento_fuente",
    "SELECT * FROM conocimiento.fragmento LIMIT 1",
    "SELECT * FROM conocimiento.trabajo_indexacion LIMIT 1",
    "SELECT * FROM configuracion.parametro_sistema WHERE vigente_hasta IS NULL",
    """UPDATE conocimiento.documento_fuente SET ruta_blob = 'local://prueba.pdf', hash_archivo = repeat('a', 64),
              estado_indexacion = 'EN_PROCESO', total_fragmentos = 1 WHERE id_documento = '%s'""" % RM_429,
    """INSERT INTO conocimiento.fragmento (id_documento, numero_orden, texto, numero_tokens, modelo_embedding,
                                          vigente, motivo_exclusion, id_documento_modificatorio)
       VALUES ('%s', 1, 'texto', 1, 'bge-m3', false, 'Sustituido', '%s')""" % (NTS_213, RM_429),
    "UPDATE conocimiento.fragmento SET verificado = verificado WHERE false",
    """INSERT INTO conocimiento.trabajo_indexacion (id_documento, tipo, solicitado_por)
       VALUES ('%s', 'INDEXACION', '%s')""" % (RM_429, SISTEMA),
    "UPDATE conocimiento.trabajo_indexacion SET estado = 'EN_CURSO' WHERE false",
    "INSERT INTO auditoria.evento_auditoria (tipo_evento) VALUES ('PRUEBA_PERMISOS')",
])
def test_indexador_escribe_solo_en_la_base_de_conocimiento(super_engine, sql):
    _ejecutar(super_engine, sql, rol="cdss_indexador")


def test_indexador_sin_permisos_sobre_clinico_ni_seguridad(super_engine):
    with super_engine.connect() as c:
        filas = c.execute(text("""SELECT n.nspname, has_schema_privilege('cdss_indexador', n.nspname, 'USAGE')
                                    FROM pg_namespace n
                                   WHERE n.nspname IN ('clinico', 'seguridad', 'asistencia')""")).all()
        borrado = c.execute(text("""SELECT count(*) FROM information_schema.role_table_grants
                                     WHERE grantee = 'rol_app_indexador' AND privilege_type IN ('DELETE', 'TRUNCATE')""")).scalar()
    assert all(not permitido for _, permitido in filas)
    assert borrado == 0


def test_m11_puede_registrar_trabajos_con_cdss_admin():
    _ejecutar(engines()["admin"], f"""INSERT INTO conocimiento.trabajo_indexacion (id_documento, tipo, solicitado_por)
                                      VALUES ('{RM_429}', 'INDEXACION', '{SISTEMA}')""")


def test_clinica_no_ve_la_cola_de_indexacion():
    with pytest.raises(ProgrammingError, match="permission denied"):
        _ejecutar(engines()["clinica"], "SELECT 1 FROM conocimiento.trabajo_indexacion LIMIT 1")
