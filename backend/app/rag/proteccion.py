"""Capa 4 · Protección de datos: solicitud mínima y control previo al envío.

La solicitud al modelo de lenguaje se arma con una lista blanca explícita (Tabla 7 de
la guía OE2): cada campo que sale del sistema está escrito aquí, uno por uno, de modo
que una columna nueva de la base queda fuera por defecto. Se leen con la sesión de
cdss_generacion, que no tiene acceso a la identidad del paciente, a texto_consulta ni a
observaciones:

- edad en meses (no la fecha de nacimiento), sexo, altitud (no el distrito), Hb
  observada y ajustada, clasificación y nivel de riesgo calculados por el sistema,
  peso, antecedentes (suplementación, lactancia, parasitosis, bajo peso al nacer,
  edad gestacional) y síntomas del catálogo (sin el detalle libre);
- el tamizaje anterior como meses transcurridos, con su Hb y su clasificación;
- el texto filtrado de la consulta y el idioma de la respuesta;
- los fragmentos enviados, con etiquetas únicas F-01 a F-05.

No se envían observaciones, talla, fechas, distrito ni identificadores.

La solicitud se serializa en forma canónica (claves ordenadas, sin espacios) y se
calcula su SHA-256. El control previo recorre cada palabra y cada número de la
solicitud serializada, incluidos los fragmentos de evidencia, y los compara con las
huellas HMAC del paciente (filtro_texto.generar_huellas). Una coincidencia bloquea el
envío; el registro del bloqueo nunca guarda la solicitud ni el valor que coincidió."""
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import Connection, text
from sqlalchemy.orm import Session

from app.rag.filtro_texto import HuellasPaciente, clave_huellas, huella, normalizar_palabra
from app.rag.recuperacion import FragmentoRecuperado

VERSION_SOLICITUD = "1"
NORMA_NACIONAL = "NORMA_NACIONAL"
OMS = "OMS"
ENTIDADES_NACIONALES = frozenset({"MINSA"})
_PALABRA = re.compile(r"[^\W\d_]+")
_DIGITOS = re.compile(r"\d+")
# Números escritos con separadores («81 234 567», «81.234.567»): se prueban también
# los grupos de cifras unidos.
_GRUPO_DE_CIFRAS = re.compile(r"\d+(?:[ .-]\d+)+")


@dataclass(frozen=True)
class DatosClinicos:
    """Campos autorizados de la Tabla 7. Agregar un campo aquí es la única forma de
    que llegue a la solicitud."""
    edad_meses: int
    sexo: str
    altitud_msnm: int | None
    hb_observada_g_dl: float | None
    hb_ajustada_g_dl: float | None
    clasificacion: str | None
    nivel_riesgo: str | None
    requiere_derivacion: bool
    peso_kg: float | None
    suplementacion_hierro: bool | None
    lactancia_materna_actual: bool | None
    parasitosis_reciente: bool | None
    bajo_peso_nacer: bool | None
    edad_gestacional: str
    sintomas: tuple[str, ...]
    tamizaje_anterior: dict | None


@dataclass(frozen=True)
class SolicitudProtegida:
    contenido: dict
    serializada: str
    hash_sha256: str
    etiquetas: dict[str, FragmentoRecuperado]


@dataclass(frozen=True)
class ResultadoControl:
    aprobado: bool
    coincidencias: int
    tipos: tuple[str, ...]


def _numero(valor: Decimal | None) -> float | None:
    return None if valor is None else float(valor)


def meses_entre(anterior: date, actual: date) -> int:
    meses = (actual.year - anterior.year) * 12 + actual.month - anterior.month
    return meses - (actual.day < anterior.day)


_TAMIZAJE = """
    SELECT t.id_paciente, t.fecha_tamizaje, t.edad_meses, t.hemoglobina_g_dl, t.peso_kg,
           t.recibe_suplementacion_hierro, t.lactancia_materna_actual, t.parasitosis_reciente,
           p.sexo, p.bajo_peso_nacer, p.edad_gestacional_nacer,
           r.altitud_msnm, r.hb_ajustada_g_dl, r.nivel_riesgo, c.nombre AS clasificacion,
           COALESCE(c.requiere_derivacion, false) AS requiere_derivacion
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
_ANTERIOR = """
    SELECT h.fecha_tamizaje, h.hemoglobina_g_dl, h.clasificacion
      FROM asistencia.v_historial_hemoglobina h
     WHERE h.id_paciente = :p AND h.fecha_tamizaje < :f
     ORDER BY h.fecha_tamizaje DESC
     LIMIT 1
"""


def leer_datos_clinicos(sesion: Session | Connection, id_tamizaje: str) -> DatosClinicos:
    """Lee solo los campos de la lista blanca, con la sesión de cdss_generacion."""
    t = sesion.execute(text(_TAMIZAJE), {"t": id_tamizaje}).first()
    if t is None:
        raise LookupError("El tamizaje no existe")
    sintomas = tuple(sesion.execute(text(_SINTOMAS), {"t": id_tamizaje}).scalars())
    a = sesion.execute(text(_ANTERIOR), {"p": t.id_paciente, "f": t.fecha_tamizaje}).first()
    anterior = None if a is None else {
        "meses_transcurridos": meses_entre(a.fecha_tamizaje, t.fecha_tamizaje),
        "hb_g_dl": _numero(a.hemoglobina_g_dl),
        "clasificacion": a.clasificacion,
    }
    return DatosClinicos(
        edad_meses=t.edad_meses, sexo=t.sexo, altitud_msnm=t.altitud_msnm,
        hb_observada_g_dl=_numero(t.hemoglobina_g_dl), hb_ajustada_g_dl=_numero(t.hb_ajustada_g_dl),
        clasificacion=t.clasificacion, nivel_riesgo=t.nivel_riesgo, requiere_derivacion=bool(t.requiere_derivacion),
        peso_kg=_numero(t.peso_kg), suplementacion_hierro=t.recibe_suplementacion_hierro,
        lactancia_materna_actual=t.lactancia_materna_actual, parasitosis_reciente=t.parasitosis_reciente,
        bajo_peso_nacer=t.bajo_peso_nacer, edad_gestacional=t.edad_gestacional_nacer, sintomas=sintomas,
        tamizaje_anterior=anterior,
    )


def entidades_de_documentos(sesion: Session | Connection, ids_documento: list[str]) -> dict[str, str]:
    if not ids_documento:
        return {}
    filas = sesion.execute(text(
        """SELECT id_documento::text, entidad_emisora FROM conocimiento.documento_fuente
            WHERE id_documento = ANY(CAST(:ids AS uuid[]))"""), {"ids": ids_documento}).all()
    return dict(filas)


def etiqueta(posicion: int) -> str:
    return f"F-{posicion:02d}"


def tipo_fuente(entidad: str | None) -> str:
    return NORMA_NACIONAL if entidad in ENTIDADES_NACIONALES else OMS


def construir_solicitud(datos: DatosClinicos, consulta: str, idioma_respuesta: str,
                        fragmentos: list[FragmentoRecuperado], entidades: dict[str, str]) -> SolicitudProtegida:
    """Solicitud mínima con la lista blanca; fragmentos en el orden final del reranker."""
    etiquetas = {etiqueta(i): f for i, f in enumerate(fragmentos, start=1)}
    contenido = {
        "version_solicitud": VERSION_SOLICITUD,
        "idioma_respuesta": idioma_respuesta,
        "consulta": consulta,
        "paciente": {
            "edad_meses": datos.edad_meses,
            "sexo": datos.sexo,
            "altitud_msnm": datos.altitud_msnm,
            "hb_observada_g_dl": datos.hb_observada_g_dl,
            "hb_ajustada_g_dl": datos.hb_ajustada_g_dl,
            "clasificacion": datos.clasificacion,
            "nivel_riesgo": datos.nivel_riesgo,
            "requiere_derivacion": datos.requiere_derivacion,
            "peso_kg": datos.peso_kg,
            "suplementacion_hierro": datos.suplementacion_hierro,
            "lactancia_materna_actual": datos.lactancia_materna_actual,
            "parasitosis_reciente": datos.parasitosis_reciente,
            "bajo_peso_nacer": datos.bajo_peso_nacer,
            "edad_gestacional": datos.edad_gestacional,
            "sintomas": list(datos.sintomas),
        },
        "tamizaje_anterior": None if datos.tamizaje_anterior is None else {
            "meses_transcurridos": datos.tamizaje_anterior["meses_transcurridos"],
            "hb_g_dl": datos.tamizaje_anterior["hb_g_dl"],
            "clasificacion": datos.tamizaje_anterior["clasificacion"],
        },
        "evidencia": [
            {"etiqueta": e, "fuente": f.codigo_documento, "tipo_fuente": tipo_fuente(entidades.get(f.id_documento)),
             "seccion": f.seccion, "idioma": f.idioma, "texto": f.texto}
            for e, f in etiquetas.items()
        ],
    }
    serializada = serializar(contenido)
    return SolicitudProtegida(contenido, serializada, hash_solicitud(serializada), etiquetas)


def serializar(contenido: dict) -> str:
    """Forma canónica: claves ordenadas, UTF-8 sin escapes y sin espacios."""
    return json.dumps(contenido, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def hash_solicitud(serializada: str) -> str:
    return hashlib.sha256(serializada.encode("utf-8")).hexdigest()


def _candidatos(serializada: str) -> tuple[set[str], set[str]]:
    palabras = {normalizar_palabra(p) for p in _PALABRA.findall(serializada)}
    numeros = set(_DIGITOS.findall(serializada))
    for grupo in _GRUPO_DE_CIFRAS.findall(serializada):
        cifras = _DIGITOS.findall(grupo)
        for i in range(len(cifras)):
            for j in range(i + 2, min(len(cifras), i + 4) + 1):
                numeros.add("".join(cifras[i:j]))
    return palabras, numeros


def controlar_identificadores(serializada: str, huellas: HuellasPaciente) -> ResultadoControl:
    """Compara cada palabra y cada número de la solicitud con las huellas del paciente.
    Devuelve cuántas coincidencias hubo y de qué tipo, nunca el valor."""
    clave = clave_huellas()
    palabras, numeros = _candidatos(serializada)
    tipos = []
    for tipo, valores in (("PALABRA", palabras), ("NUMERO", numeros)):
        tipos.extend(tipo for v in valores if huella(v, clave) in huellas)
    return ResultadoControl(aprobado=not tipos, coincidencias=len(tipos), tipos=tuple(sorted(set(tipos))))
