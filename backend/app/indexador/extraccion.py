"""Extracción del texto de los PDF con pdfplumber y limpieza de cada página:
recorte a la zona del cuerpo (sin sellos ni firmas de los márgenes), descarte
de encabezados y numeración repetidos, y detección de tokens sospechosos del OCR."""
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Recorte:
    """Zona del cuerpo en puntos PDF, medida desde el borde superior izquierdo.
    derecha e inferior en None equivalen al ancho y alto de la página."""
    izquierda: float = 0
    superior: float = 0
    derecha: float | None = None
    inferior: float | None = None


@dataclass
class PaginaTexto:
    numero: int
    lineas: list[str] = field(default_factory=list)

    @property
    def texto(self) -> str:
        return "\n".join(self.lineas)


# Tokens del OCR que suelen esconder un símbolo perdido (≥, ≤) o una cifra mal leída.
PATRONES_SOSPECHOSOS: dict[str, re.Pattern] = {
    # 5.10.5 en lugar de ≥10.5
    "cifra_con_dos_puntos": re.compile(r"(?<![\d.])\d\.\d{2}\.\d(?!\.?\d)"),
    # s 10.5, z 10.5g/dL, i11.0, ¿ 10.5: una letra suelta en lugar de ≥ o ≤
    "letra_pegada_a_cifra": re.compile(
        r"(?<![\w.,/])[aszi¿](?:\s?\d{1,2}[.,]\d(?!\d)|\s?\d{1,2}(?=\s?g/?d[lL]))", re.IGNORECASE
    ),
    # 2 11.5 en lugar de ≥ 11.5
    "dos_por_mayor_igual": re.compile(r"(?<![\w.,])2\s1\d[.,]\d(?!\d)"),
    # £ 12.0, SY2.0, >,11.0
    "simbolo_extrano_en_cifra": re.compile(r"[£¥§&]\s?\d|\bSY\d|>\s?,\s?\d"),
    # >ao en lugar de >8.0
    "cifra_con_letra_o": re.compile(r"(?<![\w])\d+[.,][oO]\b|>\s?ao\b"),
}

_NUMERO_PAGINA = re.compile(r"^\d{1,3}$")
_OMISION = re.compile(r"^[-\s]*\(\s*[.•…:\-\s'\"]*\s*\)[\s\"'.,”“•:]*$")
_CLAVE_REPETIDA = re.compile(r"[\d\W_]+")


def detectar_sospechosos(texto: str) -> dict[str, list[str]]:
    hallazgos: dict[str, list[str]] = {}
    for nombre, patron in PATRONES_SOSPECHOSOS.items():
        encontrados = [m.group(0) for m in patron.finditer(texto)]
        if encontrados:
            hallazgos[nombre] = encontrados
    return hallazgos


def contar_sospechosos(texto: str) -> int:
    return sum(len(v) for v in detectar_sospechosos(texto).values())


def _es_ruido(linea: str) -> bool:
    """Restos de sellos y firmas: líneas cortas casi sin letras ni cifras."""
    alfanumericos = sum(c.isalnum() for c in linea)
    if alfanumericos == 0:
        return True
    return len(linea) <= 12 and alfanumericos / len(linea) < 0.5


def limpiar_paginas(paginas: list[PaginaTexto], extremo: int = 4, min_paginas: int = 3) -> list[PaginaTexto]:
    """Quita encabezados y pies que se repiten en al menos la mitad de las páginas
    (entre las primeras y últimas `extremo` líneas), la numeración y el ruido."""
    claves: Counter = Counter()
    for p in paginas:
        candidatas = {(_CLAVE_REPETIDA.sub("", l.lower())) for l in p.lineas[:extremo] + p.lineas[-extremo:]}
        claves.update(c for c in candidatas if len(c) >= 12)
    umbral = max(min_paginas, (len(paginas) + 1) // 2)
    repetidas = {c for c, n in claves.items() if n >= umbral}

    limpias = []
    for p in paginas:
        lineas = []
        for i, linea in enumerate(p.lineas):
            l = linea.strip()
            if not l or _NUMERO_PAGINA.match(l):
                continue
            if _OMISION.match(l):
                lineas.append("(...)")
                continue
            en_extremo = i < extremo or i >= len(p.lineas) - extremo
            if en_extremo and _CLAVE_REPETIDA.sub("", l.lower()) in repetidas:
                continue
            if _es_ruido(l):
                continue
            lineas.append(l)
        limpias.append(PaginaTexto(p.numero, lineas))
    return limpias


def extraer_pdf(ruta: Path, pagina_inicio: int | None, pagina_fin: int | None, recorte: Recorte) -> list[PaginaTexto]:
    import pdfplumber

    paginas = []
    with pdfplumber.open(ruta) as pdf:
        inicio = pagina_inicio or 1
        fin = min(pagina_fin or len(pdf.pages), len(pdf.pages))
        for numero in range(inicio, fin + 1):
            pagina = pdf.pages[numero - 1]
            caja = (
                max(0, recorte.izquierda),
                max(0, recorte.superior),
                min(pagina.width, recorte.derecha or pagina.width),
                min(pagina.height, recorte.inferior or pagina.height),
            )
            texto = pagina.within_bbox(caja).extract_text() or ""
            paginas.append(PaginaTexto(numero, texto.splitlines()))
    return limpiar_paginas(paginas)
