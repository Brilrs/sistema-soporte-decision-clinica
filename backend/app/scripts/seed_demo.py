"""Carga usuarios de prueba y pacientes ficticios para el desarrollo y las demostraciones.

Uso (desde backend/):
    python -m app.scripts.seed_demo

- Las cuentas se crean con la conexión del componente de administración.
- Los pacientes se crean con la conexión del componente clínico; nombre, DNI,
  historia clínica y dirección se cifran con pgcrypto (AES-256) y el DNI y la
  historia clínica se guardan además como HMAC para la búsqueda.
- Los tamizajes con hemoglobina se clasifican con los parámetros vigentes
  (cálculo clínico determinístico), igual que al registrarlos desde la aplicación.
- Todos los datos son ficticios. El script es idempotente: no duplica registros.
"""
import os
from datetime import date

from sqlalchemy import text

from app.core.config import get_settings
from app.core.db import engines
from app.core.fechas import edad_en_meses
from app.core.seguridad import hash_contrasena, hmac_identificador
from app.services.clasificacion import clasificar, guardar_resultado

USUARIOS = [
    # nombre_usuario, nombre_completo, rol, correo
    ("admin.cdss", "Equipo de tesis", "Administrador", "admin.cdss@example.org"),
    ("enf.rojas", "Lic. Rosa Rojas", "Enfermera CRED", "rosa.rojas@example.org"),
    ("med.salazar", "Dr. Luis Salazar", "Médico", "luis.salazar@example.org"),
    ("nut.vilca", "Lic. Ana Vilca", "Nutricionista", "ana.vilca@example.org"),
    ("coord.ortiz", "Dra. Carmen Ortiz", "Coordinador CRED", "carmen.ortiz@example.org"),
]

# nombre, dni, hc, sexo, nacimiento, ubigeo, edad_gestacional, bajo_peso, tamizajes
# tamizaje: (fecha, hb o None, peso, talla, suplementación, lactancia, parasitosis, síntomas, observaciones)
PACIENTES = [
    ("Mateo Quispe Huamán", "81234567", "00452", "M", date(2025, 7, 12), "150134", "A_TERMINO", False, [
        (date(2026, 1, 15), 11.0, 7.4, 66.0, False, True, False, [], "Control de crecimiento"),
        (date(2026, 5, 12), 10.1, 8.6, 72.1, False, True, False, ["Palidez"], None),
        (date(2026, 9, 26), 9.8, 9.6, 76.5, False, True, False, ["Palidez", "Hiporexia"],
         "Madre refiere poco apetito desde hace 3 semanas"),
    ]),
    ("Valentina Ccori Mamani", "81345678", "00391", "F", date(2026, 1, 10), "150134", "A_TERMINO", False, [
        (date(2026, 10, 19), 11.6, 8.1, 70.2, True, True, False, [], None),
    ]),
    ("Thiago Huanca Flores", "81456789", "00517", "M", date(2025, 2, 5), "150134", "PRETERMINO", True, [
        (date(2026, 10, 18), 8.9, 9.8, 79.0, True, False, True, ["Palidez", "Fatiga o somnolencia"],
         "Recibe tratamiento antiparasitario"),
    ]),
    ("Luana Paucar Ríos", "81567890", "00288", "F", date(2023, 12, 20), "150134", "A_TERMINO", False, [
        (date(2026, 7, 28), 10.4, 12.1, 89.0, False, False, False, [], None),  # tamizaje no vigente
    ]),
    ("Gael Torres Condori", "81678901", "00602", "M", date(2026, 3, 15), "150134", "NO_REGISTRADO", None, [
        (date(2026, 10, 19), None, 7.6, 66.8, False, True, False, [], None),  # falta la hemoglobina
    ]),
    ("Camila Mamani Choque", "81789012", "00733", "F", date(2025, 4, 3), "210101", "A_TERMINO", False, [
        (date(2026, 10, 10), 11.9, 9.9, 78.4, True, True, False, [], "Residente en Puno"),
    ]),
    ("Sebastián Rojas Lazo", "81890123", "00811", "M", date(2023, 6, 1), "120101", "A_TERMINO", False, [
        (date(2026, 10, 12), 12.5, 15.2, 98.0, False, False, False, ["Irritabilidad"], None),
    ]),
    ("Isabella Flores Cárdenas", "81901234", "00845", "F", date(2024, 8, 9), "150134", "PRETERMINO", True, [
        (date(2026, 10, 16), 6.8, 10.4, 82.5, False, False, True, ["Palidez", "Fatiga o somnolencia"], None),
    ]),
    ("Diego Ramos Paredes", "82012345", "00902", "M", date(2022, 8, 22), "150103", "A_TERMINO", False, [
        (date(2026, 10, 14), 11.4, 16.0, 103.5, False, False, False, [], None),
    ]),
    ("Sofía Gutiérrez Huamán", "82123456", "00955", "F", date(2026, 6, 2), "150134", "A_TERMINO", False, [
        (date(2026, 10, 15), 11.2, 6.3, 61.0, False, True, False, [], "Menor de 6 meses"),
    ]),
]


def crear_usuarios(contrasena: str) -> dict[str, str]:
    ids: dict[str, str] = {}
    with engines()["admin"].begin() as c:
        for usuario, nombre, rol, correo in USUARIOS:
            fila = c.execute(
                text("""INSERT INTO seguridad.usuario (id_rol, nombre_completo, nombre_usuario, correo_institucional, hash_contrasena)
                        SELECT id_rol, :n, :u, :c, :h FROM seguridad.rol WHERE nombre = :r
                        ON CONFLICT (nombre_usuario) DO UPDATE SET nombre_completo = EXCLUDED.nombre_completo
                        RETURNING id_usuario::text"""),
                {"n": nombre, "u": usuario, "c": correo, "h": hash_contrasena(contrasena), "r": rol},
            ).scalar_one()
            ids[usuario] = fila
    return ids


def crear_pacientes(id_enfermera: str) -> int:
    clave = get_settings().clave_pii
    creados = 0
    with engines()["clinica"].begin() as c:
        sintomas = dict(c.execute(text("SELECT nombre, id_sintoma FROM clinico.sintoma")).all())
        for nombre, dni, hc, sexo, nac, ubigeo, eg, bajo_peso, tamizajes in PACIENTES:
            if c.execute(text("SELECT 1 FROM clinico.paciente_identidad WHERE dni_hash = :h"),
                         {"h": hmac_identificador(dni)}).first():
                continue
            id_paciente = c.execute(
                text("""INSERT INTO clinico.paciente (ubigeo_residencia, fecha_nacimiento, sexo,
                                                      edad_gestacional_nacer, bajo_peso_nacer, registrado_por)
                        VALUES (:ub, :nac, :sx, :eg, :bp, CAST(:u AS uuid)) RETURNING id_paciente::text"""),
                {"ub": ubigeo, "nac": nac, "sx": sexo, "eg": eg, "bp": bajo_peso, "u": id_enfermera},
            ).scalar_one()
            c.execute(
                text("""INSERT INTO clinico.paciente_identidad
                          (id_paciente, nombres_apellidos_cifrado, dni_cifrado, dni_hash,
                           numero_hc_cifrado, numero_hc_hash, direccion_cifrada)
                        VALUES (CAST(:id AS uuid),
                                pgp_sym_encrypt(:nom, :k, 'cipher-algo=aes256'),
                                pgp_sym_encrypt(:dni, :k, 'cipher-algo=aes256'), :dh,
                                pgp_sym_encrypt(:hc, :k, 'cipher-algo=aes256'), :hh,
                                pgp_sym_encrypt(:dir, :k, 'cipher-algo=aes256'))"""),
                {"id": id_paciente, "nom": nombre, "dni": dni, "dh": hmac_identificador(dni), "hc": hc,
                 "hh": hmac_identificador(hc), "dir": "Dirección ficticia, San Luis", "k": clave},
            )
            for fecha, hb, peso, talla, sup, lac, par, sints, obs in tamizajes:
                id_tamizaje = c.execute(
                    text("""INSERT INTO clinico.tamizaje
                              (id_paciente, id_usuario, fecha_tamizaje, edad_meses, hemoglobina_g_dl, metodo_medicion,
                               peso_kg, talla_cm, recibe_suplementacion_hierro, lactancia_materna_actual,
                               parasitosis_reciente, observaciones)
                            VALUES (CAST(:p AS uuid), CAST(:u AS uuid), :f, :e, :hb, 'HEMOGLOBINOMETRO',
                                    :peso, :talla, :sup, :lac, :par, :obs)
                            RETURNING id_tamizaje::text"""),
                    {"p": id_paciente, "u": id_enfermera, "f": fecha, "e": edad_en_meses(nac, fecha), "hb": hb,
                     "peso": peso, "talla": talla, "sup": sup, "lac": lac, "par": par, "obs": obs},
                ).scalar_one()
                for s in sints:
                    c.execute(text("INSERT INTO clinico.tamizaje_sintoma (id_tamizaje, id_sintoma) VALUES (CAST(:t AS uuid), :s)"),
                              {"t": id_tamizaje, "s": sintomas[s]})
            creados += 1
    return creados


def clasificar_pendientes() -> int:
    """Clasifica los tamizajes con hemoglobina que aún no tienen resultado (incluye los
    cargados por versiones anteriores de este script)."""
    clasificados = 0
    with engines()["clinica"].begin() as c:
        pendientes = c.execute(text(
            """SELECT t.id_tamizaje::text, t.hemoglobina_g_dl, t.edad_meses, d.altitud_msnm
                 FROM clinico.tamizaje t
                 JOIN clinico.paciente p ON p.id_paciente = t.id_paciente
                 JOIN clinico.distrito d ON d.ubigeo = p.ubigeo_residencia
                WHERE t.hemoglobina_g_dl IS NOT NULL
                  AND NOT EXISTS (SELECT 1 FROM clinico.resultado_clasificacion r WHERE r.id_tamizaje = t.id_tamizaje)""")).all()
        for id_tamizaje, hb, edad, altitud in pendientes:
            evaluacion = clasificar(c, hb, edad, altitud)
            if evaluacion.clasificacion is not None:
                guardar_resultado(c, id_tamizaje, evaluacion.clasificacion)
                clasificados += 1
    return clasificados


def main() -> None:
    contrasena = os.environ.get("SEED_CONTRASENA", "Cdss2026!")
    ids = crear_usuarios(contrasena)
    nuevos = crear_pacientes(ids["enf.rojas"])
    clasificados = clasificar_pendientes()
    print(f"Usuarios de prueba: {', '.join(ids)} (contraseña de SEED_CONTRASENA)")
    print(f"Pacientes ficticios creados: {nuevos}")
    print(f"Tamizajes clasificados: {clasificados}")


if __name__ == "__main__":
    main()
