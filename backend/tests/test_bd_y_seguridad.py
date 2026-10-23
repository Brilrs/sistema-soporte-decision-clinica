"""Mínimo privilegio, cifrado de la identidad e inmutabilidad de la auditoría."""
from datetime import date

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, ProgrammingError

from app.core.config import get_settings
from app.core.db import engines
from app.core.fechas import edad_en_meses
from app.core.seguridad import hmac_identificador


def test_componente_de_generacion_no_puede_leer_la_identidad():
    with engines()["generacion"].connect() as c:
        with pytest.raises(ProgrammingError):
            c.execute(text("SELECT * FROM clinico.paciente_identidad LIMIT 1"))


def test_componente_de_generacion_lee_datos_clinicos_seudonimizados():
    with engines()["generacion"].connect() as c:
        assert c.execute(text("SELECT count(*) FROM clinico.tamizaje")).scalar() > 0


def test_identidad_cifrada_y_recuperable_solo_con_la_clave():
    with engines()["clinica"].connect() as c:
        crudo = c.execute(text("""SELECT nombres_apellidos_cifrado FROM clinico.paciente_identidad
                                   WHERE dni_hash = :h"""), {"h": hmac_identificador("81234567")}).scalar_one()
        assert b"Mateo" not in bytes(crudo)
        nombre = c.execute(text("SELECT pgp_sym_decrypt(CAST(:b AS bytea), :k)"),
                           {"b": bytes(crudo), "k": get_settings().clave_pii}).scalar_one()
        assert nombre == "Mateo Quispe Huamán"


def test_bitacora_de_auditoria_no_admite_cambios(super_engine):
    with engines()["clinica"].connect() as c:
        with pytest.raises(ProgrammingError):
            c.execute(text("DELETE FROM auditoria.evento_auditoria"))
    with super_engine.begin() as c:
        c.execute(text("INSERT INTO auditoria.evento_auditoria (tipo_evento) VALUES ('PRUEBA')"))
    with super_engine.connect() as c:
        with pytest.raises(DBAPIError):
            c.execute(text("UPDATE auditoria.evento_auditoria SET tipo_evento = 'X'"))


def test_un_solo_valor_vigente_por_parametro(super_engine):
    with super_engine.connect() as c:
        with pytest.raises(DBAPIError):
            c.execute(text("""INSERT INTO configuracion.parametro_sistema (clave, valor, tipo_dato, descripcion, modificado_por)
                              VALUES ('UMBRAL_RELEVANCIA', '0.7', 'DECIMAL', 'duplicado',
                                      '00000000-0000-0000-0000-000000000001')"""))


@pytest.mark.parametrize("nac, ref, esperado", [
    (date(2025, 7, 12), date(2026, 9, 26), 14),
    (date(2025, 7, 12), date(2026, 7, 11), 11),
    (date(2025, 7, 12), date(2026, 7, 12), 12),
    (date(2024, 1, 31), date(2024, 2, 29), 0),
    (date(2021, 10, 20), date(2026, 10, 19), 59),
])
def test_edad_en_meses(nac, ref, esperado):
    assert edad_en_meses(nac, ref) == esperado


def test_hmac_normaliza_espacios_y_mayusculas():
    assert hmac_identificador(" 8123 4567 ") == hmac_identificador("81234567")
    assert hmac_identificador("hc-001") == hmac_identificador("HC-001")
    assert len(hmac_identificador("81234567")) == 64
