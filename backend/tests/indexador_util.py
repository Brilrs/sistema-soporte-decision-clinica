"""Utilidades compartidas por las pruebas del indexador."""
import re
from pathlib import Path

from app.indexador.config import cargar_manifiesto
from app.indexador.extraccion import PaginaTexto

DATOS = Path(__file__).parent / "datos"


def paginas_de_prueba(clave: str) -> list[PaginaTexto]:
    texto = (DATOS / f"{clave}_texto_extraido.txt").read_text(encoding="utf-8")
    partes = re.split(r"^===== PAGINA (\d+) =====\n", texto, flags=re.MULTILINE)
    return [PaginaTexto(int(n), cuerpo.rstrip("\n").split("\n")) for n, cuerpo in zip(partes[1::2], partes[2::2])]


def fuente(clave: str):
    return next(f for f in cargar_manifiesto("fuentes_iniciales.yaml") if f.clave == clave)
