"""Gestión de pacientes (IPacientes): registro, búsqueda, ficha, tamizajes e historial.

Trabaja solo con la conexión del componente clínico (cdss_clinica). La identidad
(nombre, DNI, historia clínica y dirección) se cifra con pgcrypto (AES-256) usando
CDSS_CLAVE_PII y se descifra únicamente en el servidor para mostrar la ficha
(re-vinculación 7.1). El DNI y la historia clínica se guardan además como HMAC
para buscarlos sin descifrar."""
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.fechas import edad_en_meses, hoy
from app.core.seguridad import hmac_identificador
from app.services.clasificacion import (Evaluacion, clasificar, guardar_resultado, motivo_fuera_de_rango,
                                        rango_edad_clasificable)

NOMBRE_SINTOMA_OTRO = "Otro"
DIAS_VIGENCIA_POR_DEFECTO = 30


class ErrorDatos(Exception):
    """Datos que no cumplen una regla del negocio (se responde con 422)."""


class ErrorDuplicado(Exception):
    """DNI o historia clínica ya registrados (se responde con 409)."""


@dataclass
class DatosTamizaje:
    fecha_tamizaje: date
    hemoglobina_g_dl: Decimal | None
    metodo_medicion: str | None
    peso_kg: Decimal | None
    talla_cm: Decimal | None
    recibe_suplementacion_hierro: bool | None
    lactancia_materna_actual: bool | None
    parasitosis_reciente: bool | None
    observaciones: str | None
    sintomas: list[tuple[int, str | None]]  # (id_sintoma, detalle)


def _clave() -> str:
    return get_settings().clave_pii


def _cifrar(parametro: str) -> str:
    return f"pgp_sym_encrypt(:{parametro}, :k, 'cipher-algo=aes256')"


def _descifrar(columna: str) -> str:
    return f"pgp_sym_decrypt({columna}, :k)"


# ---------------------------------------------------------------------------
# Catálogos y parámetros
# ---------------------------------------------------------------------------
def dias_vigencia(sesion: Session) -> int:
    valor = sesion.execute(text("""SELECT valor FROM configuracion.parametro_sistema
                                    WHERE clave = 'DIAS_VIGENCIA_TAMIZAJE' AND vigente_hasta IS NULL""")).scalar()
    try:
        return int(valor)
    except (TypeError, ValueError):
        return DIAS_VIGENCIA_POR_DEFECTO


def es_vigente(fecha_tamizaje: date | None, dias: int) -> bool | None:
    if fecha_tamizaje is None:
        return None
    return (hoy() - fecha_tamizaje).days <= dias


def altitud_de(sesion: Session, ubigeo: str) -> int:
    altitud = sesion.execute(text("SELECT altitud_msnm FROM clinico.distrito WHERE ubigeo = :u"),
                             {"u": ubigeo}).scalar()
    if altitud is None:
        raise ErrorDatos("El distrito de residencia no existe en el catálogo")
    return altitud


def _validar_sintomas(sesion: Session, sintomas: list[tuple[int, str | None]]) -> None:
    catalogo = dict(sesion.execute(text("SELECT id_sintoma, nombre FROM clinico.sintoma")).all())
    vistos: set[int] = set()
    for id_sintoma, detalle in sintomas:
        if id_sintoma not in catalogo:
            raise ErrorDatos(f"El síntoma {id_sintoma} no existe en el catálogo")
        if id_sintoma in vistos:
            raise ErrorDatos(f"El síntoma «{catalogo[id_sintoma]}» está repetido")
        vistos.add(id_sintoma)
        if catalogo[id_sintoma] == NOMBRE_SINTOMA_OTRO and not (detalle and detalle.strip()):
            raise ErrorDatos("Especifique el síntoma cuando marque «Otro»")


def validar_edad_tamizaje(sesion: Session, fecha_nacimiento: date, fecha_tamizaje: date) -> int:
    if fecha_tamizaje > hoy():
        raise ErrorDatos("La fecha del tamizaje no puede ser posterior a hoy")
    if fecha_tamizaje < fecha_nacimiento:
        raise ErrorDatos("La fecha del tamizaje no puede ser anterior a la fecha de nacimiento")
    edad = edad_en_meses(fecha_nacimiento, fecha_tamizaje)
    if edad > 59:
        raise ErrorDatos("El sistema atiende a niños de 0 a 59 meses; a la fecha del tamizaje el niño tiene "
                         f"{edad} meses")
    return edad


# ---------------------------------------------------------------------------
# Registro (HU02, HU05)
# ---------------------------------------------------------------------------
def _verificar_unicidad(sesion: Session, dni: str | None, numero_hc: str | None,
                        excluir: str | None = None) -> None:
    for valor, columna, nombre in ((dni, "dni_hash", "DNI"), (numero_hc, "numero_hc_hash", "número de historia clínica")):
        if valor is None:
            continue
        existe = sesion.execute(
            text(f"""SELECT 1 FROM clinico.paciente_identidad
                      WHERE {columna} = :h AND (CAST(:ex AS uuid) IS NULL OR id_paciente <> CAST(:ex AS uuid))"""),
            {"h": hmac_identificador(valor), "ex": excluir},
        ).first()
        if existe:
            raise ErrorDuplicado(f"Ya existe un paciente registrado con ese {nombre}")


def registrar_paciente(sesion: Session, id_usuario: str, *, nombres_apellidos: str, dni: str, numero_hc: str,
                       direccion: str | None, ubigeo_residencia: str, fecha_nacimiento: date, sexo: str,
                       edad_gestacional_nacer: str, bajo_peso_nacer: bool | None) -> str:
    if fecha_nacimiento > hoy():
        raise ErrorDatos("La fecha de nacimiento no puede ser posterior a hoy")
    altitud_de(sesion, ubigeo_residencia)
    _verificar_unicidad(sesion, dni, numero_hc)

    id_paciente = sesion.execute(
        text("""INSERT INTO clinico.paciente (ubigeo_residencia, fecha_nacimiento, sexo, edad_gestacional_nacer,
                                              bajo_peso_nacer, registrado_por)
                VALUES (:ub, :nac, :sx, :eg, :bp, CAST(:u AS uuid)) RETURNING id_paciente::text"""),
        {"ub": ubigeo_residencia, "nac": fecha_nacimiento, "sx": sexo, "eg": edad_gestacional_nacer,
         "bp": bajo_peso_nacer, "u": id_usuario},
    ).scalar_one()
    sesion.execute(
        text(f"""INSERT INTO clinico.paciente_identidad
                   (id_paciente, nombres_apellidos_cifrado, dni_cifrado, dni_hash,
                    numero_hc_cifrado, numero_hc_hash, direccion_cifrada)
                 VALUES (CAST(:id AS uuid), {_cifrar('nom')}, {_cifrar('dni')}, :dh, {_cifrar('hc')}, :hh,
                         CASE WHEN CAST(:dir AS text) IS NULL THEN NULL ELSE {_cifrar('dir')} END)"""),
        {"id": id_paciente, "nom": nombres_apellidos, "dni": dni, "dh": hmac_identificador(dni),
         "hc": numero_hc, "hh": hmac_identificador(numero_hc), "dir": direccion, "k": _clave()},
    )
    return id_paciente


def datos_permanentes(sesion: Session, id_paciente: str):
    return sesion.execute(
        text("""SELECT p.id_paciente::text, p.fecha_nacimiento, p.sexo, p.ubigeo_residencia,
                       p.edad_gestacional_nacer, p.bajo_peso_nacer, p.fecha_registro,
                       d.nombre AS distrito, d.provincia, d.departamento, d.altitud_msnm,
                       u.nombre_completo AS registrado_por
                  FROM clinico.paciente p
                  JOIN clinico.distrito d ON d.ubigeo = p.ubigeo_residencia
                  JOIN seguridad.usuario u ON u.id_usuario = p.registrado_por
                 WHERE p.id_paciente = CAST(:id AS uuid)"""),
        {"id": id_paciente},
    ).mappings().first()


def evaluar_tamizaje(sesion: Session, paciente, datos: DatosTamizaje) -> tuple[int, Evaluacion]:
    """Valida el tamizaje y calcula su clasificación sin guardar nada (vista previa de M14)."""
    edad = validar_edad_tamizaje(sesion, paciente["fecha_nacimiento"], datos.fecha_tamizaje)
    _validar_sintomas(sesion, datos.sintomas)
    return edad, clasificar(sesion, datos.hemoglobina_g_dl, edad, paciente["altitud_msnm"])


def registrar_tamizaje(sesion: Session, id_usuario: str, paciente, datos: DatosTamizaje) -> tuple[str, int, Evaluacion]:
    edad, evaluacion = evaluar_tamizaje(sesion, paciente, datos)
    id_tamizaje = sesion.execute(
        text("""INSERT INTO clinico.tamizaje
                  (id_paciente, id_usuario, fecha_tamizaje, edad_meses, hemoglobina_g_dl, metodo_medicion,
                   peso_kg, talla_cm, recibe_suplementacion_hierro, lactancia_materna_actual,
                   parasitosis_reciente, observaciones)
                VALUES (CAST(:p AS uuid), CAST(:u AS uuid), :f, :e, :hb, :met, :peso, :talla, :sup, :lac, :par, :obs)
                RETURNING id_tamizaje::text"""),
        {"p": paciente["id_paciente"], "u": id_usuario, "f": datos.fecha_tamizaje, "e": edad,
         "hb": datos.hemoglobina_g_dl, "met": datos.metodo_medicion, "peso": datos.peso_kg, "talla": datos.talla_cm,
         "sup": datos.recibe_suplementacion_hierro, "lac": datos.lactancia_materna_actual,
         "par": datos.parasitosis_reciente, "obs": datos.observaciones},
    ).scalar_one()
    for id_sintoma, detalle in datos.sintomas:
        sesion.execute(text("""INSERT INTO clinico.tamizaje_sintoma (id_tamizaje, id_sintoma, detalle)
                               VALUES (CAST(:t AS uuid), :s, :d)"""),
                       {"t": id_tamizaje, "s": id_sintoma, "d": detalle.strip() if detalle else None})
    if evaluacion.clasificacion is not None:
        guardar_resultado(sesion, id_tamizaje, evaluacion.clasificacion)
    return id_tamizaje, edad, evaluacion


# ---------------------------------------------------------------------------
# Ficha y actualización (HU04)
# ---------------------------------------------------------------------------
def ficha(sesion: Session, id_paciente: str) -> dict | None:
    permanentes = datos_permanentes(sesion, id_paciente)
    if permanentes is None:
        return None
    identidad = sesion.execute(
        text(f"""SELECT {_descifrar('nombres_apellidos_cifrado')} AS nombres_apellidos,
                        {_descifrar('dni_cifrado')} AS dni,
                        {_descifrar('numero_hc_cifrado')} AS numero_hc,
                        CASE WHEN direccion_cifrada IS NULL THEN NULL
                             ELSE {_descifrar('direccion_cifrada')} END AS direccion
                   FROM clinico.paciente_identidad WHERE id_paciente = CAST(:id AS uuid)"""),
        {"id": id_paciente, "k": _clave()},
    ).mappings().one()
    return {**dict(permanentes), **dict(identidad),
            "edad_meses_actual": edad_en_meses(permanentes["fecha_nacimiento"], hoy())}


CAMPOS_IDENTIDAD = {"nombres_apellidos": "nombres_apellidos_cifrado", "dni": "dni_cifrado",
                    "numero_hc": "numero_hc_cifrado", "direccion": "direccion_cifrada"}
CAMPOS_PERMANENTES = ("ubigeo_residencia", "fecha_nacimiento", "sexo", "edad_gestacional_nacer", "bajo_peso_nacer")


def actualizar_paciente(sesion: Session, id_paciente: str, cambios: dict) -> list[str]:
    """Corrige datos permanentes o de identidad. Los tamizajes y sus clasificaciones no se
    tocan: son instantáneas del control en que se registraron. Devuelve los campos cambiados."""
    if "fecha_nacimiento" in cambios:
        nac = cambios["fecha_nacimiento"]
        if nac > hoy():
            raise ErrorDatos("La fecha de nacimiento no puede ser posterior a hoy")
        primero = sesion.execute(text("""SELECT min(fecha_tamizaje) FROM clinico.tamizaje
                                          WHERE id_paciente = CAST(:id AS uuid)"""), {"id": id_paciente}).scalar()
        if primero is not None and primero < nac:
            raise ErrorDatos("La fecha de nacimiento no puede ser posterior a un tamizaje ya registrado")
    if "ubigeo_residencia" in cambios:
        altitud_de(sesion, cambios["ubigeo_residencia"])
    _verificar_unicidad(sesion, cambios.get("dni"), cambios.get("numero_hc"), excluir=id_paciente)

    permanentes = {c: cambios[c] for c in CAMPOS_PERMANENTES if c in cambios}
    if permanentes:
        asignaciones = ", ".join(f"{c} = :{c}" for c in permanentes)
        sesion.execute(text(f"UPDATE clinico.paciente SET {asignaciones} WHERE id_paciente = CAST(:id AS uuid)"),
                       {**permanentes, "id": id_paciente})

    identidad = {c: cambios[c] for c in CAMPOS_IDENTIDAD if c in cambios}
    if identidad:
        asignaciones = [f"{CAMPOS_IDENTIDAD[c]} = CASE WHEN CAST(:{c} AS text) IS NULL THEN NULL ELSE {_cifrar(c)} END"
                        for c in identidad]
        if "dni" in identidad:
            asignaciones.append("dni_hash = :dni_hash")
            identidad["dni_hash"] = hmac_identificador(identidad["dni"])
        if "numero_hc" in identidad:
            asignaciones.append("numero_hc_hash = :hc_hash")
            identidad["hc_hash"] = hmac_identificador(identidad["numero_hc"])
        asignaciones.append("fecha_actualizacion = now()")
        sesion.execute(text(f"""UPDATE clinico.paciente_identidad SET {', '.join(asignaciones)}
                                WHERE id_paciente = CAST(:id AS uuid)"""),
                       {**identidad, "id": id_paciente, "k": _clave()})
    return sorted([*permanentes, *(c for c in CAMPOS_IDENTIDAD if c in cambios)])


# ---------------------------------------------------------------------------
# Búsqueda y panel (M02)
# ---------------------------------------------------------------------------
_LISTADO = f"""
SELECT p.id_paciente::text, p.fecha_nacimiento, p.sexo,
       {_descifrar('i.nombres_apellidos_cifrado')} AS nombres_apellidos,
       {_descifrar('i.numero_hc_cifrado')} AS numero_hc,
       ult.fecha_tamizaje, ult.fecha_registro AS fecha_registro_tamizaje,
       ult.hemoglobina_g_dl, ult.hb_ajustada_g_dl, ult.categoria, ult.nivel_riesgo,
       {{coincidencia}} AS coincidencia
  FROM clinico.paciente p
  JOIN clinico.paciente_identidad i ON i.id_paciente = p.id_paciente
  LEFT JOIN LATERAL (
        SELECT t.fecha_tamizaje, t.fecha_registro, t.hemoglobina_g_dl, r.hb_ajustada_g_dl,
               c.nombre AS categoria, r.nivel_riesgo
          FROM clinico.tamizaje t
          LEFT JOIN clinico.resultado_clasificacion r ON r.id_tamizaje = t.id_tamizaje
          LEFT JOIN configuracion.categoria_anemia c ON c.id_categoria = r.id_categoria
         WHERE t.id_paciente = p.id_paciente
         ORDER BY t.fecha_tamizaje DESC, t.fecha_registro DESC
         LIMIT 1) ult ON true
 WHERE {{filtro}}
 ORDER BY greatest(ult.fecha_registro, p.fecha_registro) DESC
 LIMIT :limite"""


def _sin_tildes(expresion: str) -> str:
    """Minúsculas y sin tildes ni diéresis, para que «Huaman» encuentre «Huamán» y «nunez»
    encuentre «Núñez» sin extensiones de la base. Incluye también las mayúsculas
    acentuadas por si la intercalación del servidor no las convierte con lower()."""
    return f"translate(lower({expresion}), 'áéíóúüñÁÉÍÓÚÜÑ', 'aeiouunaeiouun')"


def _escapar_like(texto: str) -> str:
    return texto.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _fila_listado(f, dias: int) -> dict:
    return {
        "id_paciente": f["id_paciente"],
        "nombres_apellidos": f["nombres_apellidos"],
        "numero_hc": f["numero_hc"],
        "sexo": f["sexo"],
        "edad_meses_actual": edad_en_meses(f["fecha_nacimiento"], hoy()),
        "ultimo_tamizaje": None if f["fecha_tamizaje"] is None else {
            "fecha_tamizaje": f["fecha_tamizaje"],
            "fecha_registro": f["fecha_registro_tamizaje"],
            "hemoglobina_g_dl": f["hemoglobina_g_dl"],
            "hb_ajustada_g_dl": f["hb_ajustada_g_dl"],
            "categoria": f["categoria"],
            "nivel_riesgo": f["nivel_riesgo"],
            "vigente": es_vigente(f["fecha_tamizaje"], dias),
        },
    }


def recientes(sesion: Session, limite: int = 20) -> list[dict]:
    sql = _LISTADO.format(coincidencia="NULL", filtro="true")
    filas = sesion.execute(text(sql), {"k": _clave(), "limite": limite}).mappings().all()
    dias = dias_vigencia(sesion)
    return [_fila_listado(f, dias) for f in filas]


def buscar(sesion: Session, termino: str, limite: int = 20) -> tuple[list[dict], list[str]]:
    """Busca por DNI o historia clínica (HMAC, coincidencia exacta) y, si el texto tiene
    letras y al menos 3 caracteres, por nombre (descifrando en el servidor).
    Devuelve los pacientes y los tipos de coincidencia encontrados (para la auditoría)."""
    termino = termino.strip()
    hash_termino = hmac_identificador(termino)
    por_nombre = len(termino) >= 3 and any(ch.isalpha() for ch in termino)
    filtro = "i.dni_hash = :h OR i.numero_hc_hash = :h"
    if por_nombre:
        filtro += (f" OR {_sin_tildes(_descifrar('i.nombres_apellidos_cifrado'))}"
                   f" LIKE '%' || {_sin_tildes(':patron')} || '%'")
    coincidencia = """CASE WHEN i.dni_hash = :h THEN 'DNI' WHEN i.numero_hc_hash = :h THEN 'HC'
                           ELSE 'NOMBRE' END"""
    filas = sesion.execute(
        text(_LISTADO.format(coincidencia=coincidencia, filtro=filtro)),
        {"k": _clave(), "h": hash_termino, "patron": _escapar_like(termino), "limite": limite},
    ).mappings().all()
    dias = dias_vigencia(sesion)
    return [_fila_listado(f, dias) for f in filas], sorted({f["coincidencia"] for f in filas})


def indicadores(sesion: Session) -> dict:
    """Indicadores de M02. Los que dependen de las consultas (Sprint 2) se devuelven
    como nulos para que la interfaz muestre «Sin datos»."""
    dias = dias_vigencia(sesion)
    fila = sesion.execute(
        text("""WITH ultimo AS (
                  SELECT DISTINCT ON (t.id_paciente) t.id_paciente, t.fecha_tamizaje, c.nombre AS categoria
                    FROM clinico.tamizaje t
                    LEFT JOIN clinico.resultado_clasificacion r ON r.id_tamizaje = t.id_tamizaje
                    LEFT JOIN configuracion.categoria_anemia c ON c.id_categoria = r.id_categoria
                   ORDER BY t.id_paciente, t.fecha_tamizaje DESC, t.fecha_registro DESC)
                SELECT count(*) FILTER (WHERE categoria IS NOT NULL AND categoria <> 'SIN_ANEMIA') AS con_anemia,
                       count(*) FILTER (WHERE fecha_tamizaje < CAST(:limite AS date)) AS no_vigentes
                  FROM ultimo"""),
        {"limite": hoy() - timedelta(days=dias)},
    ).mappings().one()
    return {
        "evaluaciones_hoy": None,
        "con_anemia_detectada": fila["con_anemia"],
        "controles_pendientes": fila["no_vigentes"],
        "tiempo_medio_respuesta_s": None,
        "dias_vigencia_tamizaje": dias,
    }


# ---------------------------------------------------------------------------
# Historial (M08 y referencia del control anterior en M14)
# ---------------------------------------------------------------------------
def historial(sesion: Session, id_paciente: str) -> list[dict]:
    filas = sesion.execute(
        text("""SELECT t.id_tamizaje::text, t.fecha_tamizaje, t.fecha_registro, t.edad_meses, t.hemoglobina_g_dl,
                       t.metodo_medicion, t.peso_kg, t.talla_cm, t.recibe_suplementacion_hierro,
                       t.lactancia_materna_actual, t.parasitosis_reciente, t.observaciones,
                       u.nombre_completo AS profesional,
                       r.altitud_msnm, r.ajuste_hb_g_dl, r.hb_ajustada_g_dl, r.nivel_riesgo,
                       c.nombre AS categoria, c.requiere_derivacion,
                       coalesce((SELECT json_agg(json_build_object('id_sintoma', s.id_sintoma, 'nombre', s.nombre,
                                                                   'detalle', ts.detalle) ORDER BY s.id_sintoma)
                                   FROM clinico.tamizaje_sintoma ts
                                   JOIN clinico.sintoma s ON s.id_sintoma = ts.id_sintoma
                                  WHERE ts.id_tamizaje = t.id_tamizaje), '[]') AS sintomas
                  FROM clinico.tamizaje t
                  JOIN seguridad.usuario u ON u.id_usuario = t.id_usuario
                  LEFT JOIN clinico.resultado_clasificacion r ON r.id_tamizaje = t.id_tamizaje
                  LEFT JOIN configuracion.categoria_anemia c ON c.id_categoria = r.id_categoria
                 WHERE t.id_paciente = CAST(:id AS uuid)
                 ORDER BY t.fecha_tamizaje DESC, t.fecha_registro DESC"""),
        {"id": id_paciente},
    ).mappings().all()
    dias = dias_vigencia(sesion)
    rango = rango_edad_clasificable(sesion)
    resultado = []
    for f in filas:
        clasificacion = None
        motivo = None
        if f["categoria"] is not None:
            clasificacion = {"categoria": f["categoria"], "nivel_riesgo": f["nivel_riesgo"],
                             "requiere_derivacion": f["requiere_derivacion"], "altitud_msnm": f["altitud_msnm"],
                             "ajuste_hb_g_dl": f["ajuste_hb_g_dl"], "hb_ajustada_g_dl": f["hb_ajustada_g_dl"]}
        elif f["hemoglobina_g_dl"] is None:
            motivo = "Falta la hemoglobina"
        elif rango is None or not rango[0] <= f["edad_meses"] <= rango[1]:
            motivo = motivo_fuera_de_rango(rango)
        else:
            motivo = "No se pudo clasificar con los parámetros vigentes al registrarlo"
        resultado.append({
            **{k: f[k] for k in ("id_tamizaje", "fecha_tamizaje", "fecha_registro", "edad_meses", "hemoglobina_g_dl",
                                 "metodo_medicion", "peso_kg", "talla_cm", "recibe_suplementacion_hierro",
                                 "lactancia_materna_actual", "parasitosis_reciente", "observaciones",
                                 "profesional", "sintomas")},
            "vigente": es_vigente(f["fecha_tamizaje"], dias),
            "clasificacion": clasificacion,
            "motivo_sin_clasificacion": motivo,
        })
    return resultado


def franjas_vigentes(sesion: Session) -> list[dict]:
    """Puntos de corte vigentes, para dibujar las franjas del gráfico de M08."""
    return [dict(f) for f in sesion.execute(
        text("""SELECT u.edad_min_meses, u.edad_max_meses, c.nombre AS categoria, c.nivel_riesgo,
                       u.hb_min_g_dl, u.hb_max_g_dl
                  FROM configuracion.umbral_hemoglobina u
                  JOIN configuracion.categoria_anemia c ON c.id_categoria = u.id_categoria
                 WHERE u.vigente_hasta IS NULL
                 ORDER BY u.edad_min_meses, c.orden""")).mappings().all()]
