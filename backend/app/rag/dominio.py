"""2.1 · Filtro de dominio: reglas y similitud semántica, en este orden.

1. Manipulación: frases que intentan cambiar las instrucciones del sistema (en español
   o inglés) dejan la consulta fuera del dominio.
2. Población fuera del alcance: gestantes, puérperas, adolescentes, mujeres en edad
   fértil, adultos y niños de 5 años o más (o de más de 59 meses). El sistema atiende
   a niños del servicio CRED de 0 a 59 meses.
3. Términos del dominio: anemia, hemoglobina, hierro, ferritina, suplementación o
   micronutrientes, o un concepto del diccionario de normalización marcado con
   dominio: true (por ejemplo «chispitas» o «sangrecita»), dejan la consulta dentro.
4. Similitud: sin esos términos, coseno entre el embedding de la consulta y los de las
   consultas de referencia (dominio_referencia.yaml). Queda dentro si la referencia
   más parecida es de dentro y su similitud alcanza UMBRAL_DOMINIO.

Las similitudes se calculan también en los casos 2 y 3, para el registro y la
calibración del umbral."""
import math
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from app.core.modelos import Embedder
from app.rag.normalizacion import normalizar
from app.rag.texto import sin_tildes, terminos

REFERENCIAS = Path(__file__).with_name("dominio_referencia.yaml")
DENTRO = "DENTRO_DEL_DOMINIO"
FUERA = "FUERA_DE_DOMINIO"

_MANIPULACION = re.compile("|".join([
    r"\bignor\w*\s+(?:\w+\s+){0,3}instruc",
    r"\bolvid\w*\s+(?:\w+\s+){0,3}(?:instruc|eres|anterior)",
    r"\b(?:prompt|instrucciones)\s+(?:\w+\s+){0,2}sistema\b",
    r"\bsystem\s+prompt\b",
    r"\bmodo\s+(?:desarrollador|developer|sin\s+restricciones)\b",
    r"\bsin\s+restricciones\b",
    r"\b(?:actua|comportate|responde)\s+como\s+(?:si\s+fueras\s+)?(?:un|una)\b",
    r"\bjailbreak\b",
    r"\bignore\s+(?:all\s+|any\s+)?(?:previous|prior|above)\b",
    r"\b(?:revela|muestra\w*)\s+(?:\w+\s+){0,2}(?:prompt|instrucciones)\b",
]))
_POBLACION_FUERA = re.compile(
    r"\b(?:gestantes?|embarazad[ao]s?|embarazo|puerperas?|puerperio|adolescentes?|adult[oa]s?(?:\s+mayor(?:es)?)?"
    r"|ancian[oa]s?|mujer(?:es)?\s+en\s+edad\s+fertil|(?:varon|mujer|hombre|paciente)\s+de\s+(?:1[2-9]|[2-9]\d)\s+anos)\b"
)
# Edad del paciente fuera del alcance: 5 años o más, o más de 59 meses. No cuentan
# los límites de un rango o de una población («menores de 5 años», «de 0 a 5 años»,
# «hasta los 5 años»), que describen el alcance en lugar de la edad del niño.
_NUMEROS = {"cinco": 5, "seis": 6, "siete": 7, "ocho": 8, "nueve": 9, "diez": 10, "once": 11, "doce": 12}
_EDAD = re.compile(
    r"(?<![\w,.])(?P<previo>(?:\w+\s+){0,2})(?P<n>\d{1,3}|" + "|".join(_NUMEROS) + r")\s+(?P<unidad>anos?|meses)\b"
)
_LIMITE_DE_RANGO = re.compile(
    r"(?:\bmenor(?:es)?\s+de|\bmenos\s+de|\bhasta(?:\s+los)?|\bantes\s+de(?:\s+los)?|\ba(?:\s+los)?|\by(?:\s+los)?"
    r"|\bpor\s+(?:mas\s+de|encima\s+de)|\bdurante(?:\s+los)?|\bcada|\bdentro\s+de(?:\s+los)?)\s*$"
)
_TERMINOS_DOMINIO = frozenset(terminos("anemia anemias hemoglobina hierro ferritina ferroso ferropenia suplementacion "
                                       "suplemento micronutrientes multimicronutrientes polimaltosado"))


@dataclass(frozen=True)
class ResultadoDominio:
    estado: str
    motivo: str
    similitud_dentro: float
    similitud_fuera: float
    referencia_dentro: str = ""
    referencia_fuera: str = ""
    terminos_dominio: tuple[str, ...] = ()

    @property
    def dentro(self) -> bool:
        return self.estado == DENTRO


@dataclass(frozen=True)
class Referencias:
    dentro: list[str]
    fuera: list[str]


def cargar_referencias(ruta: Path = REFERENCIAS) -> Referencias:
    datos = yaml.safe_load(ruta.read_text(encoding="utf-8"))
    return Referencias([str(t) for t in datos["dentro"]], [str(t) for t in datos["fuera"]])


def es_manipulacion(texto: str) -> bool:
    return bool(_MANIPULACION.search(sin_tildes(texto)))


def edad_fuera_del_alcance(texto: str) -> bool:
    """Una edad de 5 años o más, o de más de 59 meses, que no sea el límite de un rango."""
    for m in _EDAD.finditer(sin_tildes(texto)):
        n = int(m["n"]) if m["n"].isdigit() else _NUMEROS[m["n"]]
        fuera = n >= 5 if m["unidad"].startswith("ano") else n > 59
        if fuera and not _LIMITE_DE_RANGO.search(m["previo"]):
            return True
    return False


def es_poblacion_fuera_del_alcance(texto: str) -> bool:
    return bool(_POBLACION_FUERA.search(sin_tildes(texto))) or edad_fuera_del_alcance(texto)


def terminos_del_dominio(texto: str) -> tuple[str, ...]:
    """Raíces propias del dominio y conceptos del diccionario marcados con dominio: true
    (reconoce también sinónimos como «chispitas», «gotitas» o «sangrecita»)."""
    raices = set(terminos(texto)) & _TERMINOS_DOMINIO
    conceptos = {t.clave for t in normalizar(texto).terminos if t.dominio}
    return tuple(sorted(raices | conceptos))


def _coseno(a: list[float], b: list[float]) -> float:
    producto = sum(x * y for x, y in zip(a, b))
    normas = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return producto / normas if normas else 0.0


class FiltroDominio:
    """Los embeddings de las referencias se calculan una vez y se reutilizan."""

    def __init__(self, embedder: Embedder, referencias: Referencias | None = None):
        self.embedder = embedder
        self.referencias = referencias or cargar_referencias()
        self._vectores_por_grupo: dict[str, list[list[float]]] = {}

    def _vectores(self, grupo: str) -> list[list[float]]:
        if grupo not in self._vectores_por_grupo:
            self._vectores_por_grupo[grupo] = self.embedder.embeber(getattr(self.referencias, grupo))
        return self._vectores_por_grupo[grupo]

    def similitudes(self, vector: list[float], grupo: str, excluir: str | None = None) -> list[tuple[float, str]]:
        textos = getattr(self.referencias, grupo)
        return [(_coseno(vector, v), t) for v, t in zip(self._vectores(grupo), textos) if t != excluir]

    def evaluar(self, texto: str, umbral: float, vector: list[float] | None = None,
                excluir_referencia: str | None = None) -> ResultadoDominio:
        """excluir_referencia deja fuera una consulta de referencia de la comparación
        (validación cruzada dejando una fuera, usada en la calibración)."""
        dominio = terminos_del_dominio(texto)
        if es_manipulacion(texto):
            return ResultadoDominio(FUERA, "INTENTO_DE_MANIPULACION", 0.0, 0.0, terminos_dominio=dominio)
        vector = vector if vector is not None else self.embedder.embeber([texto])[0]
        s_dentro, ref_dentro = max(self.similitudes(vector, "dentro", excluir_referencia))
        s_fuera, ref_fuera = max(self.similitudes(vector, "fuera", excluir_referencia))
        if es_poblacion_fuera_del_alcance(texto):
            estado, motivo = FUERA, "POBLACION_FUERA_DEL_ALCANCE"
        elif dominio:
            estado, motivo = DENTRO, "TERMINOS_DEL_DOMINIO"
        elif s_dentro >= s_fuera and s_dentro >= umbral:
            estado, motivo = DENTRO, "SIMILITUD"
        elif s_dentro < s_fuera:
            estado, motivo = FUERA, "MAS_PARECIDA_A_CONSULTAS_FUERA_DEL_DOMINIO"
        else:
            estado, motivo = FUERA, "SIMILITUD_BAJO_EL_UMBRAL"
        return ResultadoDominio(estado, motivo, round(s_dentro, 4), round(s_fuera, 4), ref_dentro, ref_fuera, dominio)
