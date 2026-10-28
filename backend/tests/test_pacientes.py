"""HU02, HU04, HU05 y HU18 · Registro, búsqueda, ficha, nuevo tamizaje e historial.

Todos los pacientes de estas pruebas son ficticios y se generan al vuelo; el
fixture pacientes_creados los elimina al terminar."""
import json
import random
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.core.config import get_settings
from app.core.db import engines
from app.core.fechas import edad_en_meses, hoy
from app.core.seguridad import hmac_identificador
from app.services.clasificacion import clasificar

UBIGEO = "150134"  # San Luis (catálogo de distritos)


def _dni() -> str:
    return f"9{random.randint(0, 9_999_999):07d}"


def _hc() -> str:
    return f"PRB-{random.randint(0, 999_999):06d}"


def _paciente(**cambios) -> dict:
    datos = {
        "nombres_apellidos": f"Prueba Ficticia {random.randint(0, 999_999):06d}",
        "dni": _dni(),
        "numero_hc": _hc(),
        "direccion": "Calle Ficticia 123",
        "ubigeo_residencia": UBIGEO,
        "fecha_nacimiento": str(hoy() - timedelta(days=430)),
        "sexo": "M",
        "edad_gestacional_nacer": "A_TERMINO",
        "bajo_peso_nacer": False,
        "tamizaje": _tamizaje(),
    }
    datos.update(cambios)
    return datos


def _tamizaje(**cambios) -> dict:
    datos = {
        "fecha_tamizaje": str(hoy()),
        "hemoglobina_g_dl": 9.8,
        "metodo_medicion": "HEMOGLOBINOMETRO",
        "peso_kg": 9.6,
        "talla_cm": 76.5,
        "recibe_suplementacion_hierro": False,
        "lactancia_materna_actual": True,
        "parasitosis_reciente": False,
        "observaciones": "Dato de prueba",
        "sintomas": [],
    }
    datos.update(cambios)
    return datos


def _id_sintoma(nombre: str) -> int:
    with engines()["clinica"].connect() as c:
        return c.execute(text("SELECT id_sintoma FROM clinico.sintoma WHERE nombre = :n"), {"n": nombre}).scalar_one()


def _registrar(cliente, cabeceras, pacientes_creados, usuario="enf.rojas", **cambios):
    datos = _paciente(**cambios)
    r = cliente.post("/api/pacientes", json=datos, headers=cabeceras(usuario))
    assert r.status_code == 201, r.text
    pacientes_creados.append(r.json()["id_paciente"])
    return datos, r.json()


def _eventos(super_engine, id_entidad: str | None = None, tipo: str | None = None, desde: int = 0) -> list[dict]:
    with super_engine.connect() as c:
        return [dict(f) for f in c.execute(text(
            """SELECT id_evento, tipo_evento, entidad, id_entidad, detalle::text AS detalle
                 FROM auditoria.evento_auditoria
                WHERE id_evento > :desde
                  AND (CAST(:ie AS text) IS NULL OR id_entidad = :ie)
                  AND (CAST(:t AS text) IS NULL OR tipo_evento = :t)
                ORDER BY id_evento"""), {"desde": desde, "ie": id_entidad, "t": tipo}).mappings().all()]


def _ultimo_evento(super_engine) -> int:
    with super_engine.connect() as c:
        return c.execute(text("SELECT coalesce(max(id_evento), 0) FROM auditoria.evento_auditoria")).scalar()


# ---------------------------------------------------------------------------
# Registro (HU02, HU05)
# ---------------------------------------------------------------------------
def test_registro_cifra_la_identidad_y_clasifica_el_tamizaje(cliente, cabeceras, pacientes_creados):
    sintomas = [{"id_sintoma": _id_sintoma("Palidez")}, {"id_sintoma": _id_sintoma("Otro"), "detalle": "Llanto"}]
    datos, r = _registrar(cliente, cabeceras, pacientes_creados, tamizaje=_tamizaje(sintomas=sintomas))
    id_paciente = r["id_paciente"]

    with engines()["clinica"].connect() as c:
        fila = c.execute(text("""SELECT * FROM clinico.paciente_identidad WHERE id_paciente = CAST(:id AS uuid)"""),
                         {"id": id_paciente}).mappings().one()
        for columna, valor in (("nombres_apellidos_cifrado", datos["nombres_apellidos"]),
                               ("dni_cifrado", datos["dni"]), ("numero_hc_cifrado", datos["numero_hc"])):
            assert valor.encode() not in bytes(fila[columna])
            assert c.execute(text("SELECT pgp_sym_decrypt(CAST(:b AS bytea), :k)"),
                             {"b": bytes(fila[columna]), "k": get_settings().clave_pii}).scalar_one() == valor
        assert fila["dni_hash"] == hmac_identificador(datos["dni"])
        assert fila["numero_hc_hash"] == hmac_identificador(datos["numero_hc"])

        altitud = c.execute(text("SELECT altitud_msnm FROM clinico.distrito WHERE ubigeo = :u"), {"u": UBIGEO}).scalar()
        edad = edad_en_meses(hoy() - timedelta(days=430), hoy())
        esperado = clasificar(c, Decimal("9.8"), edad, altitud).clasificacion
        guardado = c.execute(text("""SELECT r.*, c.nombre FROM clinico.resultado_clasificacion r
                                       JOIN configuracion.categoria_anemia c ON c.id_categoria = r.id_categoria
                                      WHERE r.id_tamizaje = CAST(:t AS uuid)"""),
                             {"t": r["tamizaje"]["id_tamizaje"]}).mappings().one()
        sintomas_guardados = c.execute(text("""SELECT count(*) FROM clinico.tamizaje_sintoma
                                                WHERE id_tamizaje = CAST(:t AS uuid)"""),
                                       {"t": r["tamizaje"]["id_tamizaje"]}).scalar()

    assert r["tamizaje"]["edad_meses"] == edad
    assert r["tamizaje"]["clasificacion"]["categoria"] == esperado.categoria == guardado["nombre"]
    assert Decimal(str(r["tamizaje"]["clasificacion"]["hb_ajustada_g_dl"])) == esperado.hb_ajustada_g_dl
    assert guardado["altitud_msnm"] == altitud and guardado["id_umbral"] == esperado.id_umbral
    assert sintomas_guardados == 2


def test_registro_sin_hemoglobina_guarda_el_tamizaje_sin_clasificar(cliente, cabeceras, pacientes_creados):
    _, r = _registrar(cliente, cabeceras, pacientes_creados, tamizaje=_tamizaje(hemoglobina_g_dl=None))
    assert r["tamizaje"]["clasificacion"] is None
    assert r["tamizaje"]["motivo_sin_clasificacion"] == "Falta la hemoglobina"


def test_registro_menor_de_la_edad_clasificable(cliente, cabeceras, pacientes_creados):
    _, r = _registrar(cliente, cabeceras, pacientes_creados, fecha_nacimiento=str(hoy() - timedelta(days=60)))
    assert r["tamizaje"]["clasificacion"] is None
    assert "rango de edad" in r["tamizaje"]["motivo_sin_clasificacion"]


def test_registro_sin_tamizaje(cliente, cabeceras, pacientes_creados):
    _, r = _registrar(cliente, cabeceras, pacientes_creados, tamizaje=None)
    assert r["tamizaje"] is None


def test_dni_o_historia_clinica_duplicados(cliente, cabeceras, pacientes_creados):
    datos, _ = _registrar(cliente, cabeceras, pacientes_creados)
    r = cliente.post("/api/pacientes", json=_paciente(dni=datos["dni"]), headers=cabeceras("enf.rojas"))
    assert r.status_code == 409 and "DNI" in r.json()["detail"]
    # La historia clínica se compara normalizada (sin espacios ni distinción de mayúsculas)
    hc_variante = " " + datos["numero_hc"].lower() + " "
    r = cliente.post("/api/pacientes", json=_paciente(numero_hc=hc_variante), headers=cabeceras("enf.rojas"))
    assert r.status_code == 409 and "historia clínica" in r.json()["detail"]


@pytest.mark.parametrize("cambios, mensaje", [
    ({"dni": "1234"}, "El DNI debe tener 8 dígitos"),
    ({"ubigeo_residencia": "999999"}, "distrito"),
    ({"tamizaje": _tamizaje(fecha_tamizaje=str(hoy() + timedelta(days=1)))}, "posterior a hoy"),
    ({"tamizaje": _tamizaje(fecha_tamizaje=str(hoy() - timedelta(days=500)))}, "anterior a la fecha de nacimiento"),
    ({"fecha_nacimiento": str(hoy() - timedelta(days=365 * 6))}, "0 a 59 meses"),
    ({"tamizaje": _tamizaje(hemoglobina_g_dl=25)}, "hemoglobina_g_dl"),
    ({"tamizaje": _tamizaje(hemoglobina_g_dl=9.85)}, "decimales"),
    ({"sexo": "X"}, "sexo"),
])
def test_validaciones_con_mensajes_en_espanol(cliente, cabeceras, pacientes_creados, cambios, mensaje):
    r = cliente.post("/api/pacientes", json=_paciente(**cambios), headers=cabeceras("enf.rojas"))
    assert r.status_code == 422, r.text
    assert mensaje in r.json()["detail"]
    assert "Input should" not in r.text and "Value error" not in r.text


def test_sintoma_otro_exige_detalle(cliente, cabeceras):
    datos = _paciente(tamizaje=_tamizaje(sintomas=[{"id_sintoma": _id_sintoma("Otro")}]))
    r = cliente.post("/api/pacientes", json=datos, headers=cabeceras("enf.rojas"))
    assert r.status_code == 422 and "«Otro»" in r.json()["detail"]
    # El registro se revierte por completo: el paciente no quedó guardado
    with engines()["clinica"].connect() as c:
        assert c.execute(text("SELECT 1 FROM clinico.paciente_identidad WHERE dni_hash = :h"),
                         {"h": hmac_identificador(datos["dni"])}).first() is None


# ---------------------------------------------------------------------------
# Búsqueda y panel (M02)
# ---------------------------------------------------------------------------
def test_busqueda_por_dni_historia_clinica_y_nombre(cliente, cabeceras, pacientes_creados):
    datos, r = _registrar(cliente, cabeceras, pacientes_creados)
    h = cabeceras("enf.rojas")
    for termino in (datos["dni"], f" {datos['numero_hc'].lower()} ", datos["nombres_apellidos"].split(" ", 1)[1].lower(),
                    datos["nombres_apellidos"].upper()):
        encontrados = cliente.post("/api/pacientes/buscar", json={"texto": termino}, headers=h).json()
        assert [p["id_paciente"] for p in encontrados] == [r["id_paciente"]], termino
    fila = encontrados[0]
    assert fila["nombres_apellidos"] == datos["nombres_apellidos"] and fila["numero_hc"] == datos["numero_hc"]
    assert fila["ultimo_tamizaje"]["vigente"] is True
    assert cliente.post("/api/pacientes/buscar", json={"texto": "00000000"}, headers=h).json() == []
    # Los comodines de SQL se buscan como texto literal
    assert cliente.post("/api/pacientes/buscar", json={"texto": "%%%"}, headers=h).json() == []


def test_busqueda_por_nombre_sin_tildes_ni_mayusculas(cliente, cabeceras, pacientes_creados):
    sufijo = f"Prb{random.randint(0, 999_999):06d}"
    _, r = _registrar(cliente, cabeceras, pacientes_creados, nombres_apellidos=f"Ximena Núñez Huamán {sufijo}")
    h = cabeceras("enf.rojas")

    def ids(termino: str) -> list[str]:
        return [p["id_paciente"] for p in cliente.post("/api/pacientes/buscar", json={"texto": termino}, headers=h).json()]

    for termino in ("Huaman", "nunez", "NUÑEZ", "NÚÑEZ HUAMÁN", "ximena nunez"):
        assert r["id_paciente"] in ids(termino), termino
    assert ids(f"nunez huaman {sufijo.lower()}") == [r["id_paciente"]]
    # También sobre los datos de demostración: «Huaman» encuentra «Mateo Quispe Huamán»
    nombres = [p["nombres_apellidos"] for p in cliente.post("/api/pacientes/buscar", json={"texto": "huaman"}, headers=h).json()]
    assert "Mateo Quispe Huamán" in nombres
    assert ids("Nuñezz") == []


def test_pacientes_recientes_con_el_ultimo_tamizaje(cliente, cabeceras, pacientes_creados):
    _, r = _registrar(cliente, cabeceras, pacientes_creados)
    lista = cliente.get("/api/pacientes", headers=cabeceras("enf.rojas")).json()
    assert len(lista) <= 20
    assert lista[0]["id_paciente"] == r["id_paciente"]
    assert lista[0]["ultimo_tamizaje"]["categoria"] == r["tamizaje"]["clasificacion"]["categoria"]


def test_datos_de_demostracion_clasificados(cliente, cabeceras):
    """seed_demo clasifica sus tamizajes; el menor de 6 meses queda sin clasificar."""
    h = cabeceras("enf.rojas")
    mateo = cliente.post("/api/pacientes/buscar", json={"texto": "81234567"}, headers=h).json()[0]
    assert mateo["ultimo_tamizaje"]["categoria"] is not None
    sofia = cliente.post("/api/pacientes/buscar", json={"texto": "82123456"}, headers=h).json()[0]
    assert sofia["ultimo_tamizaje"]["categoria"] is None
    luana = cliente.post("/api/pacientes/buscar", json={"texto": "81567890"}, headers=h).json()[0]
    assert luana["ultimo_tamizaje"]["vigente"] is False


def test_indicadores_sin_valores_inventados(cliente, cabeceras):
    datos = cliente.get("/api/pacientes/indicadores", headers=cabeceras("enf.rojas")).json()
    assert datos["evaluaciones_hoy"] is None and datos["tiempo_medio_respuesta_s"] is None
    assert isinstance(datos["con_anemia_detectada"], int) and isinstance(datos["controles_pendientes"], int)
    assert datos["controles_pendientes"] >= 1  # al menos el tamizaje no vigente de los datos de demostración


# ---------------------------------------------------------------------------
# Permisos por rol
# ---------------------------------------------------------------------------
def test_permisos_por_rol(cliente, cabeceras, pacientes_creados):
    _, r = _registrar(cliente, cabeceras, pacientes_creados, usuario="med.salazar")
    id_paciente = r["id_paciente"]
    coord, admin = cabeceras("coord.ortiz"), cabeceras("admin.cdss")
    # La coordinación consulta pero no registra
    assert cliente.get("/api/pacientes", headers=coord).status_code == 200
    assert cliente.get(f"/api/pacientes/{id_paciente}", headers=coord).status_code == 200
    assert cliente.get(f"/api/pacientes/{id_paciente}/historial", headers=coord).status_code == 200
    assert cliente.post("/api/pacientes", json=_paciente(), headers=coord).status_code == 403
    assert cliente.post(f"/api/pacientes/{id_paciente}/tamizajes", json=_tamizaje(), headers=coord).status_code == 403
    assert cliente.patch(f"/api/pacientes/{id_paciente}", json={"sexo": "F"}, headers=coord).status_code == 403
    # La administración no accede a los pacientes
    for ruta in ("/api/pacientes", "/api/pacientes/indicadores", f"/api/pacientes/{id_paciente}",
                 f"/api/pacientes/{id_paciente}/historial"):
        assert cliente.get(ruta, headers=admin).status_code == 403, ruta
    # Sin sesión
    assert cliente.get("/api/pacientes").status_code == 401
    assert cliente.post("/api/pacientes", json=_paciente()).status_code == 401
    # Nutricionista registra
    _registrar(cliente, cabeceras, pacientes_creados, usuario="nut.vilca")


# ---------------------------------------------------------------------------
# Ficha y corrección (HU04)
# ---------------------------------------------------------------------------
def test_ficha_descifra_la_identidad_y_queda_auditada(cliente, cabeceras, pacientes_creados, super_engine):
    datos, r = _registrar(cliente, cabeceras, pacientes_creados)
    desde = _ultimo_evento(super_engine)
    ficha = cliente.get(f"/api/pacientes/{r['id_paciente']}", headers=cabeceras("enf.rojas")).json()
    assert (ficha["dni"], ficha["numero_hc"], ficha["direccion"]) == (datos["dni"], datos["numero_hc"], datos["direccion"])
    assert ficha["distrito"] == "San Luis" and isinstance(ficha["altitud_msnm"], int)
    assert [e["tipo_evento"] for e in _eventos(super_engine, r["id_paciente"], desde=desde)] == ["IDENTIDAD_CONSULTADA"]


def test_paciente_inexistente(cliente, cabeceras):
    h = cabeceras("enf.rojas")
    assert cliente.get("/api/pacientes/00000000-0000-0000-0000-000000000000", headers=h).status_code == 404
    assert cliente.get("/api/pacientes/no-es-un-uuid", headers=h).status_code == 422


def test_correccion_de_datos_actualiza_el_hmac_y_no_toca_los_tamizajes(cliente, cabeceras, pacientes_creados,
                                                                      super_engine):
    datos, r = _registrar(cliente, cabeceras, pacientes_creados)
    id_paciente, h = r["id_paciente"], cabeceras("enf.rojas")
    nueva_hc = _hc()
    antes = cliente.get(f"/api/pacientes/{id_paciente}/historial", headers=h).json()["tamizajes"]
    desde = _ultimo_evento(super_engine)

    respuesta = cliente.patch(f"/api/pacientes/{id_paciente}",
                              json={"numero_hc": nueva_hc, "ubigeo_residencia": "210101", "direccion": ""}, headers=h)
    assert respuesta.status_code == 200, respuesta.text
    ficha = respuesta.json()
    assert ficha["numero_hc"] == nueva_hc and ficha["direccion"] is None and ficha["distrito"] == "Puno"
    assert cliente.post("/api/pacientes/buscar", json={"texto": nueva_hc}, headers=h).json()[0]["id_paciente"] == id_paciente
    assert cliente.post("/api/pacientes/buscar", json={"texto": datos["numero_hc"]}, headers=h).json() == []
    # La clasificación anterior es una instantánea: no cambia con el distrito
    assert cliente.get(f"/api/pacientes/{id_paciente}/historial", headers=h).json()["tamizajes"] == antes

    eventos = _eventos(super_engine, id_paciente, "PACIENTE_ACTUALIZADO", desde)
    assert len(eventos) == 1
    assert '"numero_hc"' in eventos[0]["detalle"] and nueva_hc not in eventos[0]["detalle"]


def test_correccion_rechaza_datos_no_validos(cliente, cabeceras, pacientes_creados):
    otro, _ = _registrar(cliente, cabeceras, pacientes_creados)
    _, r = _registrar(cliente, cabeceras, pacientes_creados,
                      tamizaje=_tamizaje(fecha_tamizaje=str(hoy() - timedelta(days=10))))
    ruta, h = f"/api/pacientes/{r['id_paciente']}", cabeceras("enf.rojas")
    assert cliente.patch(ruta, json={"dni": otro["dni"]}, headers=h).status_code == 409
    assert cliente.patch(ruta, json={}, headers=h).status_code == 422
    assert cliente.patch(ruta, json={"nombres_apellidos": None}, headers=h).status_code == 422
    # El nacimiento no puede quedar después de un tamizaje ya registrado
    r = cliente.patch(ruta, json={"fecha_nacimiento": str(hoy() - timedelta(days=5))}, headers=h)
    assert r.status_code == 422 and "posterior a un tamizaje" in r.json()["detail"]


# ---------------------------------------------------------------------------
# Nuevo tamizaje (HU18) e historial (M08)
# ---------------------------------------------------------------------------
def test_nuevo_tamizaje_conserva_el_anterior(cliente, cabeceras, pacientes_creados):
    h = cabeceras("enf.rojas")
    dias = cliente.get("/api/pacientes/indicadores", headers=h).json()["dias_vigencia_tamizaje"]
    _, r = _registrar(cliente, cabeceras, pacientes_creados,
                      tamizaje=_tamizaje(fecha_tamizaje=str(hoy() - timedelta(days=min(dias + 1, 420)))))
    id_paciente = r["id_paciente"]
    anterior = cliente.get(f"/api/pacientes/{id_paciente}/historial", headers=h).json()["tamizajes"][0]

    nuevo = cliente.post(f"/api/pacientes/{id_paciente}/tamizajes",
                         json=_tamizaje(hemoglobina_g_dl=11.5, recibe_suplementacion_hierro=True,
                                        sintomas=[{"id_sintoma": _id_sintoma("Hiporexia")}]), headers=h)
    assert nuevo.status_code == 201, nuevo.text

    historial = cliente.get(f"/api/pacientes/{id_paciente}/historial", headers=h).json()
    tamizajes = historial["tamizajes"]
    assert [t["id_tamizaje"] for t in tamizajes] == [nuevo.json()["id_tamizaje"], anterior["id_tamizaje"]]
    assert tamizajes[1] == anterior
    assert tamizajes[0]["vigente"] is True and tamizajes[1]["vigente"] is False
    assert [s["nombre"] for s in tamizajes[0]["sintomas"]] == ["Hiporexia"]
    assert tamizajes[0]["profesional"] == "Lic. Rosa Rojas"
    assert historial["franjas"] and historial["consultas"] == []


def test_vista_previa_no_guarda_y_muestra_el_control_anterior(cliente, cabeceras, pacientes_creados, super_engine):
    _, r = _registrar(cliente, cabeceras, pacientes_creados)
    id_paciente, h = r["id_paciente"], cabeceras("enf.rojas")
    desde = _ultimo_evento(super_engine)
    previa = cliente.post(f"/api/pacientes/{id_paciente}/tamizajes/vista-previa",
                          json=_tamizaje(hemoglobina_g_dl=11.5), headers=h)
    assert previa.status_code == 200, previa.text
    assert previa.json()["anterior"]["id_tamizaje"] == r["tamizaje"]["id_tamizaje"]
    assert previa.json()["clasificacion"] is not None
    assert len(cliente.get(f"/api/pacientes/{id_paciente}/historial", headers=h).json()["tamizajes"]) == 1
    assert _eventos(super_engine, desde=desde, tipo="TAMIZAJE_REGISTRADO") == []


def test_tamizaje_de_paciente_inexistente(cliente, cabeceras):
    r = cliente.post("/api/pacientes/00000000-0000-0000-0000-000000000000/tamizajes", json=_tamizaje(),
                     headers=cabeceras("enf.rojas"))
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Auditoría
# ---------------------------------------------------------------------------
def test_auditoria_sin_identificadores_en_claro(cliente, cabeceras, pacientes_creados, super_engine):
    desde = _ultimo_evento(super_engine)
    datos, r = _registrar(cliente, cabeceras, pacientes_creados)
    h = cabeceras("enf.rojas")
    cliente.post("/api/pacientes/buscar", json={"texto": datos["dni"]}, headers=h)
    cliente.post("/api/pacientes/buscar", json={"texto": datos["nombres_apellidos"]}, headers=h)
    cliente.post(f"/api/pacientes/{r['id_paciente']}/tamizajes", json=_tamizaje(), headers=h)

    eventos = _eventos(super_engine, desde=desde)
    tipos = [e["tipo_evento"] for e in eventos]
    for tipo in ("PACIENTE_REGISTRADO", "TAMIZAJE_REGISTRADO", "PACIENTE_BUSCADO"):
        assert tipo in tipos
    busquedas = [e for e in eventos if e["tipo_evento"] == "PACIENTE_BUSCADO"]
    assert '"DNI"' in busquedas[0]["detalle"] and '"NOMBRE"' in busquedas[1]["detalle"]
    texto = " ".join(str(e) for e in eventos)
    for valor in (datos["dni"], datos["numero_hc"], datos["nombres_apellidos"], datos["direccion"]):
        assert valor not in texto


def test_busqueda_por_post_sin_el_texto_en_la_url_ni_en_la_auditoria(cliente, cabeceras, pacientes_creados,
                                                                    super_engine):
    """La búsqueda viaja en el cuerpo (POST /buscar) y la auditoría no guarda el texto buscado,
    ni cuando hay resultados ni cuando no los hay."""
    datos, r = _registrar(cliente, cabeceras, pacientes_creados)
    h = cabeceras("enf.rojas")
    sin_resultado = "Texto Inexistente Zq"
    terminos = (datos["dni"], f" {datos['numero_hc'].lower()} ", datos["nombres_apellidos"], sin_resultado)
    desde = _ultimo_evento(super_engine)
    for termino in terminos:
        respuesta = cliente.post("/api/pacientes/buscar", json={"texto": termino}, headers=h)
        assert respuesta.status_code == 200
        assert [p["id_paciente"] for p in respuesta.json()] == ([] if termino == sin_resultado else [r["id_paciente"]])

    busquedas = _eventos(super_engine, tipo="PACIENTE_BUSCADO", desde=desde)
    assert len(busquedas) == len(terminos)
    for evento in busquedas:
        assert evento["id_entidad"] is None
        assert set(json.loads(evento["detalle"])) == {"coincidencias", "resultados"}
        for termino in terminos:
            assert termino.strip().lower() not in evento["detalle"].lower()
    assert json.loads(busquedas[-1]["detalle"]) == {"coincidencias": [], "resultados": 0}

    # El listado por GET ya no busca: ignora cualquier parámetro y no registra búsquedas
    desde = _ultimo_evento(super_engine)
    cliente.get("/api/pacientes", params={"q": datos["dni"]}, headers=h)
    assert _eventos(super_engine, tipo="PACIENTE_BUSCADO", desde=desde) == []


def test_busqueda_valida_el_texto_y_los_permisos(cliente, cabeceras):
    ruta = "/api/pacientes/buscar"
    assert cliente.post(ruta, json={"texto": "   "}, headers=cabeceras("enf.rojas")).status_code == 422
    assert cliente.post(ruta, json={}, headers=cabeceras("enf.rojas")).status_code == 422
    assert cliente.post(ruta, json={"texto": "x" * 151}, headers=cabeceras("enf.rojas")).status_code == 422
    assert cliente.post(ruta, json={"texto": "81234567"}, headers=cabeceras("coord.ortiz")).status_code == 200
    assert cliente.post(ruta, json={"texto": "81234567"}, headers=cabeceras("admin.cdss")).status_code == 403
    assert cliente.post(ruta, json={"texto": "81234567"}).status_code == 401
