"""Interfaces del servicio de modelos locales (bge-m3 y bge-reranker-v2-m3) con
dos versiones: la real, por HTTP al contenedor modelos, y una falsa determinista
para las pruebas automáticas, que no necesitan los modelos."""
import hashlib
import math
import re
from typing import Protocol

import httpx

DIMENSION = 1024
_PALABRAS = re.compile(r"\w+")
_TOKENS = re.compile(r"\w+|[^\w\s]")


class Embedder(Protocol):
    nombre: str

    def embeber(self, textos: list[str]) -> list[list[float]]: ...


class Tokenizador(Protocol):
    def contar(self, textos: list[str]) -> list[int]: ...


class Reranker(Protocol):
    def puntuar(self, consulta: str, candidatos: list[str]) -> list[float]: ...


class ClienteModelos:
    """Cliente HTTP del servicio modelos. Los lotes respetan los límites del
    servicio (64 textos por petición)."""

    def __init__(self, url: str, timeout_s: float = 900.0):
        self._http = httpx.Client(base_url=url.rstrip("/"), timeout=timeout_s)

    def post(self, ruta: str, cuerpo: dict) -> dict:
        r = self._http.post(ruta, json=cuerpo)
        r.raise_for_status()
        return r.json()

    def salud(self) -> dict:
        r = self._http.get("/salud")
        r.raise_for_status()
        return r.json()


class EmbedderHttp:
    nombre = "bge-m3"

    def __init__(self, cliente: ClienteModelos, lote: int = 8):
        self._cliente = cliente
        self._lote = lote

    def embeber(self, textos: list[str]) -> list[list[float]]:
        vectores: list[list[float]] = []
        for i in range(0, len(textos), self._lote):
            datos = self._cliente.post("/embeddings", {"textos": textos[i:i + self._lote]})
            if datos["dimension"] != DIMENSION:
                raise ValueError(f"El servicio de modelos devolvió vectores de {datos['dimension']} dimensiones")
            vectores.extend(datos["vectores"])
        return vectores


class TokenizadorHttp:
    def __init__(self, cliente: ClienteModelos, lote: int = 64):
        self._cliente = cliente
        self._lote = lote

    def contar(self, textos: list[str]) -> list[int]:
        cuentas: list[int] = []
        for i in range(0, len(textos), self._lote):
            cuentas.extend(self._cliente.post("/tokens", {"textos": textos[i:i + self._lote]})["tokens"])
        return cuentas


class RerankerHttp:
    def __init__(self, cliente: ClienteModelos):
        self._cliente = cliente

    def puntuar(self, consulta: str, candidatos: list[str]) -> list[float]:
        return self._cliente.post("/reranquear", {"consulta": consulta, "candidatos": candidatos})["puntajes"]


def _indice(termino: str) -> tuple[int, float]:
    h = hashlib.blake2b(termino.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(h[:4], "big") % DIMENSION, (1.0 if h[4] % 2 == 0 else -1.0)


class EmbedderFalso:
    """Bolsa de palabras con hash en 1024 dimensiones, normalizada: textos con
    palabras en común quedan cerca, igual que con el modelo real."""
    nombre = "falso-bolsa-de-palabras"

    def embeber(self, textos: list[str]) -> list[list[float]]:
        vectores = []
        for texto in textos:
            v = [0.0] * DIMENSION
            for termino in _PALABRAS.findall(texto.lower()):
                i, signo = _indice(termino)
                v[i] += signo
            norma = math.sqrt(sum(x * x for x in v)) or 1.0
            vectores.append([x / norma for x in v])
        return vectores


class TokenizadorFalso:
    """Aproximación determinista: palabras y signos de puntuación."""

    def contar(self, textos: list[str]) -> list[int]:
        return [len(_TOKENS.findall(t)) for t in textos]


class RerankerFalso:
    """Proporción de términos de la consulta presentes en cada candidato."""

    def puntuar(self, consulta: str, candidatos: list[str]) -> list[float]:
        terminos = set(_PALABRAS.findall(consulta.lower()))
        if not terminos:
            return [0.0] * len(candidatos)
        return [len(terminos & set(_PALABRAS.findall(c.lower()))) / len(terminos) for c in candidatos]
