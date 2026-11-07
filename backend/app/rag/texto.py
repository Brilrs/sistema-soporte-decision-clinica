"""Procesamiento léxico común: minúsculas, sin tildes, sin palabras vacías y con
raíces según el idioma (snowballstemmer en español e inglés). Lo usan el índice
BM25, la normalización y el filtro de dominio."""
import re
import unicodedata
from functools import lru_cache

import snowballstemmer

IDIOMAS = {"es": "spanish", "en": "english"}

# Cifras con decimales (11.5, 9,8) como un solo término; el resto, palabras.
_TERMINO = re.compile(r"\d+(?:[.,]\d+)?|[a-z]+")

PALABRAS_VACIAS = {
    "es": frozenset("""
        a al algo algun alguna algunas alguno algunos ante antes aquel aquella aquellas aquellos aqui asi
        aun cada como con contra cual cuales cuando cuanto de del desde donde dos el ella ellas ello ellos
        en entre era eran es esa esas ese eso esos esta estaba estado estan estar estas este esto estos
        fue fueron ha han hasta hay la las le les lo los mas me mi mis mucho muy nada ni no nos nosotros
        o otra otras otro otros para pero poco por porque que quien quienes se sea segun ser si sido sin
        sobre solo son su sus tambien tan tanto te tiene tienen todo todos tu tus un una unas uno unos
        usted ustedes y ya debe deben puede pueden hacer hace
    """.split()),
    "en": frozenset("""
        a about above after again against all am an and any are as at be because been before being below
        between both but by can could did do does doing down during each few for from further had has
        have having he her here hers him his how i if in into is it its itself just me more most my no
        nor not now of off on once only or other our out over own same she should so some such than that
        the their them then there these they this those through to too under until up very was we were
        what when where which while who whom why will with would you your
    """.split()),
}


def sin_tildes(texto: str) -> str:
    descompuesto = unicodedata.normalize("NFKD", texto.lower())
    return "".join(c for c in descompuesto if not unicodedata.combining(c))


@lru_cache(maxsize=2)
def stemmer(idioma: str):
    return snowballstemmer.stemmer(IDIOMAS[idioma])


def palabras(texto: str) -> list[str]:
    """Términos en minúsculas y sin tildes, con las cifras decimales unidas por punto."""
    return [t.replace(",", ".") for t in _TERMINO.findall(sin_tildes(texto))]


def terminos(texto: str, idioma: str = "es") -> list[str]:
    """Términos para la búsqueda léxica: sin palabras vacías y reducidos a su raíz."""
    if idioma not in IDIOMAS:
        raise ValueError(f"Idioma no admitido: {idioma}")
    vacias = PALABRAS_VACIAS[idioma]
    utiles = [p for p in palabras(texto) if p not in vacias and (len(p) > 1 or p.isdigit())]
    return stemmer(idioma).stemWords(utiles)
