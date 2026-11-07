"""2.4 · Reformulación y normalización de la consulta, con reglas locales y sin el
modelo de lenguaje.

Expande las abreviaturas, reconoce los conceptos del diccionario por su término
preferido o sus sinónimos (sin tildes y por raíz, de modo que «niños» coincide con
«niño») y devuelve sus descriptores MeSH y DeCS, los equivalentes en inglés para
buscar en las guías OMS y los términos de expansión para la búsqueda ampliada. Sin
licencia de UMLS, el CUI queda vacío."""
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

from app.rag.texto import palabras, sin_tildes, stemmer

DICCIONARIO = Path(__file__).with_name("diccionario_normalizacion.yaml")


@dataclass(frozen=True)
class Concepto:
    clave: str
    preferido: str
    sinonimos: tuple[str, ...]
    mesh_id: str
    mesh_termino: str
    decs_termino: str
    ingles: tuple[str, ...]
    verificar: bool
    dominio: bool = False


@dataclass(frozen=True)
class TerminoNormalizado:
    clave: str
    preferido: str
    encontrado: str
    mesh_id: str
    mesh_termino: str
    decs_termino: str
    dominio: bool = False
    cui: str | None = None


@dataclass
class ConsultaNormalizada:
    texto: str
    texto_normalizado: str
    terminos: list[TerminoNormalizado] = field(default_factory=list)
    equivalentes_ingles: list[str] = field(default_factory=list)
    expansion: list[str] = field(default_factory=list)

    @property
    def descriptores_mesh(self) -> list[str]:
        return [t.mesh_termino for t in self.terminos if t.mesh_termino]

    def texto_ampliado(self) -> str:
        """Consulta de la búsqueda ampliada: el texto normalizado con los sinónimos y
        los equivalentes en inglés de los conceptos reconocidos."""
        return " ".join([self.texto_normalizado, *self.expansion, *self.equivalentes_ingles])


@dataclass(frozen=True, eq=False)
class Diccionario:
    abreviaturas: dict[str, str]
    conceptos: tuple[Concepto, ...]


@lru_cache
def cargar_diccionario(ruta: Path = DICCIONARIO) -> Diccionario:
    datos = yaml.safe_load(ruta.read_text(encoding="utf-8"))
    conceptos = tuple(
        Concepto(
            clave=c["clave"], preferido=c["preferido"], sinonimos=tuple(c.get("sinonimos") or ()),
            mesh_id=str(c["mesh"].get("id") or ""), mesh_termino=str(c["mesh"].get("termino") or ""),
            decs_termino=str(c["decs"].get("termino") or ""), ingles=tuple(c.get("ingles") or ()),
            verificar=bool(c.get("verificar", True)), dominio=bool(c.get("dominio", False)),
        )
        for c in datos["conceptos"]
    )
    claves = [c.clave for c in conceptos]
    if len(set(claves)) != len(claves):
        raise ValueError("El diccionario de normalización tiene claves de concepto repetidas")
    abreviaturas = {sin_tildes(str(k)): str(v) for k, v in datos["abreviaturas"].items()}
    return Diccionario(abreviaturas, conceptos)


@lru_cache(maxsize=4096)
def _raices(texto: str) -> tuple[str, ...]:
    return tuple(stemmer("es").stemWords(palabras(texto)))


def _contiene(secuencia: tuple[str, ...], frase: tuple[str, ...]) -> bool:
    n = len(frase)
    return n > 0 and any(secuencia[i:i + n] == frase for i in range(len(secuencia) - n + 1))


@lru_cache
def _patron_abreviaturas(diccionario: Diccionario) -> re.Pattern:
    claves = sorted(diccionario.abreviaturas, key=len, reverse=True)
    return re.compile(r"(?<![a-z0-9])(" + "|".join(re.escape(k) for k in claves) + r")\.?(?![a-z0-9])")


def expandir_abreviaturas(texto: str, diccionario: Diccionario | None = None) -> str:
    diccionario = diccionario or cargar_diccionario()
    return _patron_abreviaturas(diccionario).sub(lambda m: diccionario.abreviaturas[m.group(1)], sin_tildes(texto))


def normalizar(texto: str, diccionario: Diccionario | None = None) -> ConsultaNormalizada:
    diccionario = diccionario or cargar_diccionario()
    normalizado = expandir_abreviaturas(texto, diccionario)
    raices = _raices(normalizado)
    resultado = ConsultaNormalizada(texto=texto, texto_normalizado=normalizado)
    presentes = set()
    for c in diccionario.conceptos:
        encontrado = next((f for f in (c.preferido, *c.sinonimos) if _contiene(raices, _raices(f))), None)
        if encontrado is None:
            continue
        resultado.terminos.append(TerminoNormalizado(c.clave, c.preferido, encontrado, c.mesh_id, c.mesh_termino,
                                                     c.decs_termino, c.dominio))
        for frase in (c.preferido, *c.sinonimos):
            raiz = _raices(frase)
            if raiz not in presentes and not _contiene(raices, raiz):
                presentes.add(raiz)
                resultado.expansion.append(frase)
        for frase in c.ingles:
            if frase not in resultado.equivalentes_ingles:
                resultado.equivalentes_ingles.append(frase)
    return resultado
