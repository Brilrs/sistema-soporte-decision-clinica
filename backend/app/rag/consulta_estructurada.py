"""Consulta de recuperación construida con los datos estructurados del tamizaje.

El grafo de la parte D la usa para buscar la evidencia del caso del paciente. Se
arma solo con columnas estructuradas: edad en meses, clasificación y nivel de
riesgo ya calculados (resultado_clasificacion, con la altitud aplicada), los
antecedentes del tamizaje y del nacimiento, y los síntomas del catálogo. Nunca lee
texto_consulta ni observaciones, ni la identidad del paciente: leer_contexto
funciona con la sesión de cdss_generacion.

La consulta describe el caso con los términos de las guías (suplementación
preventiva, tratamiento, referencia a un establecimiento de mayor capacidad
resolutiva, ajuste por altitud) y termina en la pregunta que corresponde a la
clasificación. No incluye el sexo, el peso ni fechas, que no ayudan a recuperar
evidencia."""
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import Connection, text
from sqlalchemy.orm import Session

SIN_ANEMIA = "SIN_ANEMIA"
ANEMIA_LEVE = "ANEMIA_LEVE"
ANEMIA_MODERADA = "ANEMIA_MODERADA"
ANEMIA_SEVERA = "ANEMIA_SEVERA"

_CATEGORIAS = {
    SIN_ANEMIA: "sin anemia",
    ANEMIA_LEVE: "anemia leve",
    ANEMIA_MODERADA: "anemia moderada",
    ANEMIA_SEVERA: "anemia severa",
}
_RIESGOS = {"BAJO": "bajo", "MODERADO": "moderado", "ALTO": "alto", "MUY_ALTO": "muy alto"}
# Síntomas del catálogo clinico.sintoma; «Otro» no aporta a la búsqueda.
_SINTOMAS_IGNORADOS = frozenset({"otro"})


@dataclass(frozen=True)
class ContextoClinico:
    """Datos estructurados del tamizaje que admite la consulta de recuperación."""
    edad_meses: int
    categoria: str | None = None
    nivel_riesgo: str | None = None
    hb_ajustada_g_dl: Decimal | None = None
    altitud_msnm: int | None = None
    ajuste_hb_g_dl: Decimal | None = None
    requiere_derivacion: bool = False
    recibe_suplementacion_hierro: bool | None = None
    lactancia_materna_actual: bool | None = None
    parasitosis_reciente: bool | None = None
    bajo_peso_nacer: bool | None = None
    prematuro: bool | None = None
    sintomas: tuple[str, ...] = ()


def _decimal(valor: Decimal) -> str:
    return f"{valor:.1f}".replace(".", ",")


def _lista(elementos: list[str]) -> str:
    if len(elementos) <= 1:
        return "".join(elementos)
    return ", ".join(elementos[:-1]) + " y " + elementos[-1]


def _descripcion(c: ContextoClinico) -> str:
    sujeto = "Lactante" if c.edad_meses < 12 else "Niño"
    partes = [f"{sujeto} de {c.edad_meses} meses"]
    ajustada = bool(c.altitud_msnm is not None and c.ajuste_hb_g_dl)
    if c.categoria in _CATEGORIAS:
        estado = _CATEGORIAS[c.categoria]
        if c.hb_ajustada_g_dl is not None:
            hb = "hemoglobina ajustada" if ajustada else "hemoglobina"
            estado += f" ({hb} {_decimal(c.hb_ajustada_g_dl)} g/dL)"
        partes.append(estado if c.categoria == SIN_ANEMIA else f"con {estado}")
    if c.nivel_riesgo in _RIESGOS:
        partes.append(f"riesgo {_RIESGOS[c.nivel_riesgo]}")
    if ajustada:
        partes.append(f"residente a {c.altitud_msnm} msnm con ajuste de hemoglobina por altitud")
    if c.prematuro and c.bajo_peso_nacer:
        partes.append("nacido prematuro y con bajo peso al nacer")
    elif c.prematuro:
        partes.append("nacido prematuro")
    elif c.bajo_peso_nacer:
        partes.append("con bajo peso al nacer")
    if c.recibe_suplementacion_hierro is True:
        partes.append("recibe suplementación con hierro")
    elif c.recibe_suplementacion_hierro is False:
        partes.append("sin suplementación con hierro")
    if c.lactancia_materna_actual and c.edad_meses < 6:
        partes.append("con lactancia materna exclusiva")
    if c.parasitosis_reciente:
        partes.append("con parasitosis reciente")
    sintomas = [s.lower() for s in c.sintomas if s.lower() not in _SINTOMAS_IGNORADOS]
    if sintomas:
        partes.append("con " + _lista(sintomas))
    return ", ".join(partes)


def _preguntas(c: ContextoClinico) -> list[str]:
    if c.categoria in (ANEMIA_LEVE, ANEMIA_MODERADA, ANEMIA_SEVERA):
        preguntas = []
        if c.categoria == ANEMIA_SEVERA or c.requiere_derivacion:
            preguntas.append("¿Cuándo se refiere a un establecimiento de mayor capacidad resolutiva?")
        preguntas.append("¿Qué tratamiento con hierro le corresponde, en qué dosis y por cuánto tiempo, "
                         "y cómo es el seguimiento con control de hemoglobina?")
    else:
        # Sin anemia o sin clasificación (menores de 6 meses: no hay punto de corte).
        preguntas = ["¿Qué suplementación preventiva con hierro le corresponde a su edad, en qué dosis, "
                     "y cuándo se mide la hemoglobina?"]
    if c.parasitosis_reciente:
        preguntas.append("¿Se administra tratamiento antiparasitario junto con el hierro?")
    return preguntas


def construir_consulta(contexto: ContextoClinico) -> str:
    """Texto de la consulta de recuperación para el caso del paciente."""
    return " ".join([_descripcion(contexto) + ".", *_preguntas(contexto)])


_CONTEXTO = """
    SELECT t.edad_meses, t.recibe_suplementacion_hierro, t.lactancia_materna_actual, t.parasitosis_reciente,
           p.bajo_peso_nacer, p.edad_gestacional_nacer, c.nombre AS categoria, r.nivel_riesgo, r.hb_ajustada_g_dl,
           r.altitud_msnm, r.ajuste_hb_g_dl, c.requiere_derivacion
      FROM clinico.tamizaje t
      JOIN clinico.paciente p ON p.id_paciente = t.id_paciente
      LEFT JOIN clinico.resultado_clasificacion r ON r.id_tamizaje = t.id_tamizaje
      LEFT JOIN configuracion.categoria_anemia c ON c.id_categoria = r.id_categoria
     WHERE t.id_tamizaje = CAST(:t AS uuid)
"""

_SINTOMAS = """
    SELECT s.nombre FROM clinico.tamizaje_sintoma ts JOIN clinico.sintoma s ON s.id_sintoma = ts.id_sintoma
     WHERE ts.id_tamizaje = CAST(:t AS uuid) ORDER BY s.nombre
"""


def leer_contexto(sesion: Session | Connection, id_tamizaje: str) -> ContextoClinico:
    """Contexto del tamizaje con las columnas que cdss_generacion puede leer. La
    altitud sale del resultado de la clasificación (cdss_generacion no lee distrito)."""
    fila = sesion.execute(text(_CONTEXTO), {"t": id_tamizaje}).first()
    if fila is None:
        raise LookupError("El tamizaje no existe")
    sintomas = tuple(sesion.execute(text(_SINTOMAS), {"t": id_tamizaje}).scalars())
    prematuro = None if fila.edad_gestacional_nacer == "NO_REGISTRADO" else fila.edad_gestacional_nacer == "PRETERMINO"
    return ContextoClinico(
        edad_meses=fila.edad_meses, categoria=fila.categoria, nivel_riesgo=fila.nivel_riesgo,
        hb_ajustada_g_dl=fila.hb_ajustada_g_dl, altitud_msnm=fila.altitud_msnm, ajuste_hb_g_dl=fila.ajuste_hb_g_dl,
        requiere_derivacion=bool(fila.requiere_derivacion), recibe_suplementacion_hierro=fila.recibe_suplementacion_hierro,
        lactancia_materna_actual=fila.lactancia_materna_actual, parasitosis_reciente=fila.parasitosis_reciente,
        bajo_peso_nacer=fila.bajo_peso_nacer, prematuro=prematuro, sintomas=sintomas,
    )
