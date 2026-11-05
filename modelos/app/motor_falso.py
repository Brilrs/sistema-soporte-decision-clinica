"""Motor determinístico sin PyTorch para pruebas y entornos sin modelos.

Los vectores son una bolsa de palabras proyectada con un hash en 1024 dimensiones y
normalizada, de modo que textos con palabras en común quedan cerca. El puntaje del
reranker es la proporción de palabras de la consulta presentes en el candidato. Los
tokens se cuentan como palabras y signos. No tiene valor semántico real."""
import hashlib
import math
import re
import unicodedata

DIMENSION = 1024
_PALABRA = re.compile(r"\w+|[^\w\s]")


def _normalizar(texto: str) -> str:
    sin_tildes = unicodedata.normalize("NFKD", texto.lower())
    return "".join(c for c in sin_tildes if not unicodedata.combining(c))


def _palabras(texto: str) -> list[str]:
    return re.findall(r"\w+", _normalizar(texto))


class MotorFalso:
    def info(self) -> dict:
        return {"motor": "falso", "modelos": {"bge-m3": {"dimension": DIMENSION}, "bge-reranker-v2-m3": {}}}

    def embeddings(self, textos: list[str]) -> list[list[float]]:
        vectores = []
        for texto in textos:
            v = [0.0] * DIMENSION
            for palabra in _palabras(texto):
                indice = int.from_bytes(hashlib.sha256(palabra.encode()).digest()[:4], "big") % DIMENSION
                v[indice] += 1.0
            norma = math.sqrt(sum(x * x for x in v)) or 1.0
            vectores.append([x / norma for x in v])
        return vectores

    def reranquear(self, consulta: str, candidatos: list[str]) -> list[float]:
        terminos = set(_palabras(consulta))
        if not terminos:
            return [0.0] * len(candidatos)
        return [round(len(terminos & set(_palabras(c))) / len(terminos), 6) for c in candidatos]

    def contar_tokens(self, textos: list[str]) -> list[int]:
        return [len(_PALABRA.findall(t)) for t in textos]
