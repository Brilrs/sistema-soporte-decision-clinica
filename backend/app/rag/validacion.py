"""2.2 · Datos mínimos y vigencia del tamizaje, y 2.3 · clasificación.

Se ejecuta con la sesión de cdss_clinica (nodos validar y clasificar): necesita la
altitud del distrito y, si el tamizaje aún no tiene resultado_clasificacion, lo
calcula con app.services.clasificacion y lo guarda en esa misma sesión. El
componente de generación solo lee el resultado ya guardado.

Datos mínimos (guía OE2, capa 2.2 y pantalla M06): edad, sexo, altitud de
residencia, hemoglobina y fecha del tamizaje. Del tamizaje se leen solo columnas
estructuradas; nunca observaciones.

Alcance: niños de 0 a 59 meses del servicio CRED. Un tamizaje con otra edad queda
FUERA_DE_ALCANCE y no se clasifica ni pasa a la recuperación. La base de datos ya
lo impide con la restricción de clinico.tamizaje.edad_meses; esta comprobación
protege el flujo si los datos llegan por otra vía."""
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy import Connection, text
from sqlalchemy.orm import Session

from app.core.fechas import hoy
from app.rag.parametros import leer_parametros
from app.services.clasificacion import clasificar, guardar_resultado

VALIDA = "VALIDA"
DATOS_FALTANTES = "DATOS_FALTANTES"
TAMIZAJE_NO_VIGENTE = "TAMIZAJE_NO_VIGENTE"
FUERA_DE_ALCANCE = "FUERA_DE_ALCANCE"
EDAD_MIN_ALCANCE_MESES = 0
EDAD_MAX_ALCANCE_MESES = 59

# Campo, etiqueta para M06 y para qué se necesita.
DATOS_MINIMOS = (
    ("edad_meses", "edad", "La edad en meses define el punto de corte de hemoglobina."),
    ("sexo", "sexo", "El sexo forma parte del contexto clínico mínimo de la consulta."),
    ("altitud_msnm", "altitud", "La altitud de residencia ajusta la hemoglobina antes de clasificar."),
    ("hemoglobina_g_dl", "hemoglobina", "La hemoglobina es necesaria para calcular la clasificación de anemia."),
    ("fecha_tamizaje", "fecha del tamizaje", "La fecha del tamizaje permite comprobar su vigencia."),
)


@dataclass(frozen=True)
class DatoFaltante:
    campo: str
    etiqueta: str
    mensaje: str


@dataclass(frozen=True)
class ResumenClasificacion:
    categoria: str
    nivel_riesgo: str
    hb_ajustada_g_dl: Decimal
    ajuste_hb_g_dl: Decimal
    altitud_msnm: int
    requiere_derivacion: bool
    calculada_ahora: bool


@dataclass
class ResultadoValidacion:
    estado: str
    id_tamizaje: str
    disponibles: dict[str, bool] = field(default_factory=dict)
    faltantes: list[DatoFaltante] = field(default_factory=list)
    dias_transcurridos: int | None = None
    dias_vigencia: int | None = None
    continua_con_tamizaje_no_vigente: bool = False
    clasificacion: ResumenClasificacion | None = None
    motivo_sin_clasificacion: str | None = None


def _datos_tamizaje(sesion: Session | Connection, id_tamizaje: str):
    return sesion.execute(text(
        """SELECT t.id_tamizaje, t.fecha_tamizaje, t.edad_meses, t.hemoglobina_g_dl, p.sexo, d.altitud_msnm
             FROM clinico.tamizaje t
             JOIN clinico.paciente p ON p.id_paciente = t.id_paciente
             LEFT JOIN clinico.distrito d ON d.ubigeo = p.ubigeo_residencia
            WHERE t.id_tamizaje = CAST(:t AS uuid)"""
    ), {"t": id_tamizaje}).first()


def leer_clasificacion(sesion: Session | Connection, id_tamizaje: str) -> ResumenClasificacion | None:
    """Resultado ya guardado; lo pueden leer cdss_clinica y cdss_generacion."""
    fila = sesion.execute(text(
        """SELECT c.nombre, r.nivel_riesgo, r.hb_ajustada_g_dl, r.ajuste_hb_g_dl, r.altitud_msnm,
                  c.requiere_derivacion
             FROM clinico.resultado_clasificacion r
             JOIN configuracion.categoria_anemia c ON c.id_categoria = r.id_categoria
            WHERE r.id_tamizaje = CAST(:t AS uuid)"""
    ), {"t": id_tamizaje}).first()
    if fila is None:
        return None
    return ResumenClasificacion(fila.nombre, fila.nivel_riesgo, fila.hb_ajustada_g_dl, fila.ajuste_hb_g_dl,
                                fila.altitud_msnm, fila.requiere_derivacion, calculada_ahora=False)


def edad_en_alcance(edad_meses: int) -> bool:
    return EDAD_MIN_ALCANCE_MESES <= edad_meses <= EDAD_MAX_ALCANCE_MESES


def dias_desde(fecha_tamizaje: date, referencia: date) -> int:
    return (referencia - fecha_tamizaje).days


def validar_tamizaje(sesion: Session | Connection, id_tamizaje: str, confirma_tamizaje_no_vigente: bool = False,
                     fecha_referencia: date | None = None, con_clasificacion: bool = True) -> ResultadoValidacion:
    """Comprueba los datos mínimos, la vigencia (DIAS_VIGENCIA_TAMIZAJE: el día límite
    se acepta y el siguiente no) y obtiene la clasificación, calculándola y
    guardándola si falta. Con con_clasificacion=False se detiene antes de clasificar (el
    grafo lo hace en su propio nodo con obtener_clasificacion). Usar con la sesión de
    cdss_clinica."""
    datos = _datos_tamizaje(sesion, id_tamizaje)
    if datos is None:
        raise LookupError("El tamizaje no existe")
    resultado = ResultadoValidacion(estado=VALIDA, id_tamizaje=id_tamizaje)
    for campo, etiqueta, mensaje in DATOS_MINIMOS:
        presente = getattr(datos, campo) is not None
        resultado.disponibles[etiqueta] = presente
        if not presente:
            resultado.faltantes.append(DatoFaltante(campo, etiqueta, mensaje))
    if resultado.faltantes:
        resultado.estado = DATOS_FALTANTES
        return resultado
    if not edad_en_alcance(datos.edad_meses):
        resultado.estado = FUERA_DE_ALCANCE
        return resultado

    vigencia = leer_parametros(sesion, ["DIAS_VIGENCIA_TAMIZAJE"])["DIAS_VIGENCIA_TAMIZAJE"]
    resultado.dias_vigencia = vigencia
    resultado.dias_transcurridos = dias_desde(datos.fecha_tamizaje, fecha_referencia or hoy())
    if resultado.dias_transcurridos > vigencia:
        if not confirma_tamizaje_no_vigente:
            resultado.estado = TAMIZAJE_NO_VIGENTE
            return resultado
        resultado.continua_con_tamizaje_no_vigente = True

    if con_clasificacion:
        resultado.clasificacion, resultado.motivo_sin_clasificacion = obtener_clasificacion(sesion, id_tamizaje)
    return resultado


def obtener_clasificacion(sesion: Session | Connection,
                          id_tamizaje: str) -> tuple[ResumenClasificacion | None, str | None]:
    """2.3: la clasificación guardada o, si falta, la calculada y guardada en esta misma
    sesión (cdss_clinica). Devuelve también el motivo cuando no se puede clasificar."""
    guardada = leer_clasificacion(sesion, id_tamizaje)
    if guardada is not None:
        return guardada, None
    datos = _datos_tamizaje(sesion, id_tamizaje)
    evaluacion = clasificar(sesion, datos.hemoglobina_g_dl, datos.edad_meses, datos.altitud_msnm)
    if evaluacion.clasificacion is None:
        return None, evaluacion.motivo
    c = evaluacion.clasificacion
    guardar_resultado(sesion, id_tamizaje, c)
    return ResumenClasificacion(c.categoria, c.nivel_riesgo, c.hb_ajustada_g_dl, c.ajuste_hb_g_dl, c.altitud_msnm,
                                c.requiere_derivacion, calculada_ahora=True), None
