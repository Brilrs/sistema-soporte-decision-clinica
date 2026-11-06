"""Transcripciones manuales de las tablas y párrafos críticos. Cada archivo .md
lleva un encabezado YAML entre líneas '---' con el documento, las páginas, la
tabla, las anclas que delimitan en el texto extraído la zona que reemplaza, y
quién y cuándo la verificó contra la imagen de la página."""
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import yaml

DIR_TRANSCRIPCIONES = Path(__file__).parent / "transcripciones"
TIPOS = ("TEXTO", "TABLA")


@dataclass(frozen=True)
class Transcripcion:
    clave: str
    documento: str
    pagina: int
    pagina_fin: int
    tabla: str
    tipo_contenido: str
    ancla_inicio: str
    ancla_fin: str
    verificado_por: str | None
    fecha_verificacion: date | None
    texto: str
    ruta: Path

    @property
    def verificada(self) -> bool:
        return bool(self.verificado_por) and self.fecha_verificacion is not None


def leer_transcripcion(ruta: Path) -> Transcripcion:
    contenido = ruta.read_text(encoding="utf-8")
    partes = contenido.split("---", 2)
    if not contenido.startswith("---") or len(partes) < 3:
        raise ValueError(f"{ruta.name}: falta el encabezado YAML entre líneas '---'")
    meta = yaml.safe_load(partes[1]) or {}
    for campo in ("documento", "pagina", "tabla", "ancla_inicio", "ancla_fin"):
        if not meta.get(campo):
            raise ValueError(f"{ruta.name}: falta el campo '{campo}' en el encabezado")
    tipo = meta.get("tipo_contenido", "TABLA")
    if tipo not in TIPOS:
        raise ValueError(f"{ruta.name}: tipo_contenido debe ser TEXTO o TABLA")
    fecha = meta.get("fecha_verificacion")
    if isinstance(fecha, str):
        fecha = date.fromisoformat(fecha) if fecha.strip() else None
    return Transcripcion(
        clave=f"{ruta.parent.name}/{ruta.stem}",
        documento=str(meta["documento"]),
        pagina=int(meta["pagina"]),
        pagina_fin=int(meta.get("pagina_fin") or meta["pagina"]),
        tabla=str(meta["tabla"]),
        tipo_contenido=tipo,
        ancla_inicio=str(meta["ancla_inicio"]),
        ancla_fin=str(meta["ancla_fin"]),
        verificado_por=(str(meta["verificado_por"]).strip() or None) if meta.get("verificado_por") else None,
        fecha_verificacion=fecha,
        texto=partes[2].strip(),
        ruta=ruta,
    )


def cargar_transcripciones(carpeta: str | None, base: Path = DIR_TRANSCRIPCIONES) -> list[Transcripcion]:
    if not carpeta:
        return []
    directorio = Path(carpeta) if Path(carpeta).is_absolute() else base / carpeta
    if not directorio.is_dir():
        raise ValueError(f"No existe la carpeta de transcripciones {directorio}")
    return [leer_transcripcion(r) for r in sorted(directorio.glob("*.md"))]
