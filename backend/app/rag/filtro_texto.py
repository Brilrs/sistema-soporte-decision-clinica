"""Capa 4.3 · Filtro del texto libre de la consulta.

Se ejecuta en la API con la sesión de cdss_clinica, que ya conoce la identidad del
paciente: descifra su nombre, DNI e historia clínica dentro del servidor y reemplaza
en el texto que escribió el profesional:

- el nombre y cada apellido del paciente, sin mayúsculas ni tildes, por [PACIENTE];
- los números de DNI y cualquier número de 8 dígitos, por [DNI];
- la historia clínica (el número del paciente o el que sigue a «HC» o «historia
  clínica»), por [HC];
- los teléfonos, por [TELEFONO], y las fechas completas, por [FECHA];
- los nombres y apellidos frecuentes de nombres_frecuentes.yaml, por [NOMBRE] (pueden
  ser de la madre, del padre o de otro niño).

También genera las huellas HMAC del paciente para el control previo al envío
(proteccion.py): cada parte del nombre de 3 letras o más, el DNI y la historia clínica,
con una clave derivada de CDSS_CLAVE_HMAC con una etiqueta propia, distinta de la de
dni_hash. Las huellas solo viven en memoria: nunca se guardan ni se registran.

El texto filtrado se guarda en asistencia.consulta.texto_filtrado; texto_consulta solo
lo lee cdss_clinica."""
import hashlib
import hmac
import re
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml
from sqlalchemy import Connection, text
from sqlalchemy.orm import Session

from app.core.config import get_settings

NOMBRES_FRECUENTES = Path(__file__).with_name("nombres_frecuentes.yaml")
PACIENTE = "[PACIENTE]"
NOMBRE = "[NOMBRE]"
DNI = "[DNI]"
HC = "[HC]"
TELEFONO = "[TELEFONO]"
FECHA = "[FECHA]"
MARCAS = (PACIENTE, NOMBRE, DNI, HC, TELEFONO, FECHA)
ETIQUETA_HUELLAS = b"cdss-huellas-solicitud-v1"
LARGO_MINIMO_PARTE = 3
# Partículas de los nombres compuestos («de la Cruz», «San Martín»): son palabras
# comunes y no identifican; la parte que las acompaña sí se filtra.
PARTICULAS = frozenset({"de", "del", "la", "las", "los", "y", "e", "san", "santa", "da", "do", "dos", "van", "von"})

_MESES = "enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|setiembre|octubre|noviembre|diciembre"
_FECHA = re.compile(
    rf"\b\d{{1,2}}\s*[/.-]\s*\d{{1,2}}\s*[/.-]\s*\d{{2,4}}\b"
    rf"|\b\d{{4}}-\d{{1,2}}-\d{{1,2}}\b"
    rf"|\b\d{{1,2}}\s+de\s+(?:{_MESES})\s+(?:de\s+|del\s+)?\d{{4}}\b",
    re.IGNORECASE)
_TELEFONO = re.compile(
    r"(?:\b(?:tel[eé]fono|telf?|tlf|cel(?:ular)?|whatsapp|wsp)\b\.?\s*(?:n[°º.o]*\s*)?:?\s*(?:\+?51[\s-]?)?[\d(][\d\s()-]{5,}\d)"
    r"|(?:(?<!\d)(?:\+?51[\s-]?)?9\d{2}[\s-]?\d{3}[\s-]?\d{3}(?!\d))",
    re.IGNORECASE)
_HC = re.compile(
    r"\b(?:h\.?\s?c\.?|historia(?:\s+cl[ií]nica)?)\s*(?:n[°º.o]*\s*)?:?\s*\d{3,10}\b", re.IGNORECASE)
_OCHO_DIGITOS = re.compile(r"(?<!\d)\d{8}(?!\d)")
_PALABRA = re.compile(r"[^\W\d_]+")
_NUMERO_CON_SEPARADORES = re.compile(r"\d(?:[\d\s.-]*\d)?")
_CIFRAS = re.compile(r"\d+")
_MARCAS_REPETIDAS = re.compile(r"(\[(?:PACIENTE|NOMBRE)\])(?:\s+\1)+")


def normalizar_palabra(palabra: str) -> str:
    """Minúsculas y sin tildes (la ñ queda como n)."""
    descompuesta = unicodedata.normalize("NFD", palabra.lower())
    return "".join(c for c in descompuesta if unicodedata.category(c) != "Mn")


def solo_digitos(valor: str) -> str:
    return "".join(c for c in valor if c.isdigit())


def partes_del_nombre(nombre_completo: str) -> set[str]:
    """Partes normalizadas de 3 letras o más, sin partículas."""
    return {p for p in (normalizar_palabra(x) for x in _PALABRA.findall(nombre_completo))
            if len(p) >= LARGO_MINIMO_PARTE and p not in PARTICULAS}


def formas_numericas(valor: str) -> set[str]:
    """Formas en que puede aparecer un DNI o una historia clínica: los dígitos tal cual
    y, si tiene ceros a la izquierda, sin ellos cuando quedan 5 dígitos o más (con
    menos, el número coincidiría con cifras comunes de las guías)."""
    digitos = solo_digitos(valor)
    formas = {digitos} if digitos else set()
    sin_ceros = digitos.lstrip("0")
    if len(sin_ceros) >= 5:
        formas.add(sin_ceros)
    return formas


@lru_cache
def cargar_nombres_frecuentes(ruta: Path = NOMBRES_FRECUENTES) -> frozenset[str]:
    datos = yaml.safe_load(ruta.read_text(encoding="utf-8"))
    return frozenset(normalizar_palabra(n) for n in [*datos["nombres"], *datos["apellidos"]])


@dataclass(frozen=True)
class IdentidadPaciente:
    """Identidad descifrada en el servidor. Nunca sale de la API ni se registra."""
    nombres_apellidos: str
    dni: str
    numero_hc: str

    def __repr__(self) -> str:
        return "IdentidadPaciente(<protegida>)"


@dataclass(frozen=True)
class HuellasPaciente:
    """HMAC de cada identificador del paciente para el control previo al envío."""
    valores: frozenset[str] = field(repr=False)

    def __repr__(self) -> str:
        return f"HuellasPaciente({len(self.valores)} huellas)"

    def __contains__(self, huella: str) -> bool:
        return huella in self.valores

    def __len__(self) -> int:
        return len(self.valores)


@dataclass(frozen=True)
class ResultadoFiltro:
    texto_filtrado: str
    reemplazos: dict[str, int]


def clave_huellas() -> bytes:
    return hmac.new(get_settings().clave_hmac.encode(), ETIQUETA_HUELLAS, hashlib.sha256).digest()


def huella(valor: str, clave: bytes | None = None) -> str:
    """HMAC-SHA256 de un valor ya normalizado, con la clave derivada para las huellas."""
    return hmac.new(clave or clave_huellas(), valor.encode(), hashlib.sha256).hexdigest()


def generar_huellas(identidad: IdentidadPaciente) -> HuellasPaciente:
    clave = clave_huellas()
    valores = partes_del_nombre(identidad.nombres_apellidos) | formas_numericas(identidad.dni) \
        | formas_numericas(identidad.numero_hc)
    return HuellasPaciente(frozenset(huella(v, clave) for v in valores))


_IDENTIDAD = """
    SELECT pgp_sym_decrypt(i.nombres_apellidos_cifrado, :k) AS nombres_apellidos,
           pgp_sym_decrypt(i.dni_cifrado, :k) AS dni,
           pgp_sym_decrypt(i.numero_hc_cifrado, :k) AS numero_hc
      FROM clinico.tamizaje t
      JOIN clinico.paciente_identidad i ON i.id_paciente = t.id_paciente
     WHERE t.id_tamizaje = CAST(:t AS uuid)
"""


def leer_identidad(sesion: Session | Connection, id_tamizaje: str) -> IdentidadPaciente | None:
    """Descifra la identidad del paciente del tamizaje. Solo con la sesión de cdss_clinica."""
    fila = sesion.execute(text(_IDENTIDAD), {"t": id_tamizaje, "k": get_settings().clave_pii}).first()
    if fila is None:
        return None
    return IdentidadPaciente(fila.nombres_apellidos, fila.dni, fila.numero_hc)


def _sustituir(patron: re.Pattern, marca: str, texto: str, cuenta: dict[str, int]) -> str:
    texto, n = patron.subn(marca, texto)
    if n:
        cuenta[marca] = cuenta.get(marca, 0) + n
    return texto


def _numeros_del_paciente(texto: str, formas: set[str], marca: str, cuenta: dict[str, int]) -> str:
    """Reemplaza un número del paciente aunque esté escrito con espacios, puntos o guiones."""
    def _cambiar(m: re.Match) -> str:
        if solo_digitos(m.group()) in formas:
            cuenta[marca] = cuenta.get(marca, 0) + 1
            return marca
        return _CIFRAS.sub(_cifra, m.group())

    def _cifra(m: re.Match) -> str:
        if m.group() in formas:
            cuenta[marca] = cuenta.get(marca, 0) + 1
            return marca
        return m.group()
    return _NUMERO_CON_SEPARADORES.sub(_cambiar, texto) if formas else texto


def filtrar_texto(texto: str, identidad: IdentidadPaciente | None,
                  nombres_frecuentes: frozenset[str] | None = None) -> ResultadoFiltro:
    """Reemplaza los identificadores del texto libre por marcas neutras."""
    frecuentes = cargar_nombres_frecuentes() if nombres_frecuentes is None else nombres_frecuentes
    cuenta: dict[str, int] = {}
    resultado = _sustituir(_FECHA, FECHA, texto, cuenta)
    if identidad is not None:
        resultado = _numeros_del_paciente(resultado, formas_numericas(identidad.dni), DNI, cuenta)
        resultado = _numeros_del_paciente(resultado, formas_numericas(identidad.numero_hc), HC, cuenta)
    resultado = _sustituir(_HC, HC, resultado, cuenta)
    resultado = _sustituir(_TELEFONO, TELEFONO, resultado, cuenta)
    resultado = _sustituir(_OCHO_DIGITOS, DNI, resultado, cuenta)

    partes = partes_del_nombre(identidad.nombres_apellidos) if identidad is not None else set()

    def _nombre(m: re.Match) -> str:
        palabra = normalizar_palabra(m.group())
        if palabra in partes:
            cuenta[PACIENTE] = cuenta.get(PACIENTE, 0) + 1
            return PACIENTE
        if palabra in frecuentes:
            cuenta[NOMBRE] = cuenta.get(NOMBRE, 0) + 1
            return NOMBRE
        return m.group()

    resultado = _sustituir_fuera_de_marcas(resultado, _nombre)
    resultado = _MARCAS_REPETIDAS.sub(r"\1", resultado)
    return ResultadoFiltro(resultado, cuenta)


_MARCA = re.compile(r"\[(?:PACIENTE|NOMBRE|DNI|HC|TELEFONO|FECHA)\]")


def _sustituir_fuera_de_marcas(texto: str, funcion) -> str:
    """Aplica el reemplazo de palabras sin tocar las marcas ya puestas."""
    partes, inicio = [], 0
    for m in _MARCA.finditer(texto):
        partes.append(_PALABRA.sub(funcion, texto[inicio:m.start()]))
        partes.append(m.group())
        inicio = m.end()
    partes.append(_PALABRA.sub(funcion, texto[inicio:]))
    return "".join(partes)


_INGLES = frozenset(normalizar_palabra(p) for p in (
    "what which how when should does do is are the of for with and child children infant infants iron "
    "dose treatment anaemia anemia months old recommend recommended guideline please answer english").split())
_ESPANOL = frozenset(normalizar_palabra(p) for p in (
    "qué que cuál cual cómo como cuándo cuando debe dosis tratamiento niño niña meses de del la el los las "
    "para con por hierro anemia recomienda le se es una un y responde español").split())
_PIDE_INGLES = re.compile(r"\b(?:in english|en ingl[eé]s)\b", re.IGNORECASE)
_PIDE_ESPANOL = re.compile(r"\b(?:in spanish|en espa[nñ]ol)\b", re.IGNORECASE)


def idioma_respuesta(texto: str, defecto: str = "es") -> str:
    """'en' si la consulta lo pide explícitamente o está escrita en inglés; si no, el
    idioma por defecto (IDIOMA_RESPUESTA_DEFECTO). Se decide al registrar la consulta."""
    if _PIDE_ESPANOL.search(texto):
        return "es"
    if _PIDE_INGLES.search(texto):
        return "en"
    palabras = [normalizar_palabra(p) for p in _PALABRA.findall(texto)]
    ingles = sum(p in _INGLES and p not in _ESPANOL for p in palabras)
    espanol = sum(p in _ESPANOL and p not in _INGLES for p in palabras)
    return "en" if ingles >= 3 and ingles > 2 * espanol else defecto
