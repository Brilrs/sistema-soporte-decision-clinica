"""Punteros entre documentos (Sprint 2, parte G, pendiente P4).

Algunos fragmentos remiten a una tabla («según Tabla N° 4») cuya versión vigente está en otro
documento: la RM 429-2024/MINSA modificó la Tabla N° 4 de la NTS 213. Si el modelo recibe el
puntero sin la tabla, responde sin el calendario. Las reglas de punteros.yaml dicen de forma
explícita, por documento, a qué fragmento lleva cada puntero; la recuperación
(recuperacion.aplicar_punteros) agrega ese fragmento a los enviados en lugar del último.

La resolución es determinista: el documento destino y la marca de su sección salen del mapa de
modificaciones del indexador, y el destino debe ser un único fragmento recuperable de hasta
MAX_TOKENS_AGREGADO tokens."""
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml
from sqlalchemy import Connection, text
from sqlalchemy.orm import Session

from app.indexador.modificaciones import cargar_mapa
from app.rag.bm25 import CONDICION_RECUPERABLE

REGLAS = Path(__file__).parent / "punteros.yaml"
# Topes por intento: un fragmento agregado, de hasta unos 600 tokens.
MAX_AGREGADOS = 1
MAX_TOKENS_AGREGADO = 600

PUNTERO = "PUNTERO"
RERANKER = "RERANKER"


@dataclass(frozen=True)
class ReglaPuntero:
    id: str
    documento_origen: str
    patron: re.Pattern
    documento_destino: str
    marca_seccion: str

    def aplica_a(self, codigo_documento: str | None, texto: str) -> bool:
        return codigo_documento == self.documento_origen and bool(self.patron.search(texto))


def _regla(datos: dict) -> ReglaPuntero:
    mapa = cargar_mapa(datos["mapa"])
    numero = int(datos["modificacion"])
    modificacion = next((m for m in mapa.modificaciones if m.numero == numero), None)
    if modificacion is None:
        raise ValueError(f"Regla {datos['id']}: el mapa {datos['mapa']} no tiene la modificación {numero}")
    if modificacion.numeral != str(datos["numeral"]):
        raise ValueError(f"Regla {datos['id']}: la modificación {numero} del mapa es «{modificacion.numeral}», "
                         f"no «{datos['numeral']}»")
    return ReglaPuntero(
        id=str(datos["id"]), documento_origen=str(datos["documento_origen"]),
        patron=re.compile(datos["patron"], re.IGNORECASE), documento_destino=mapa.codigo,
        # La misma marca que pone segmentacion.segmentar en la sección de cada modificación.
        marca_seccion=f"(mod. {mapa.codigo}, modificación N.° {numero})",
    )


def cargar_reglas(ruta: Path = REGLAS) -> tuple[ReglaPuntero, ...]:
    datos = yaml.safe_load(ruta.read_text(encoding="utf-8")) or {}
    reglas = tuple(_regla(r) for r in datos.get("reglas") or [])
    ids = [r.id for r in reglas]
    if len(ids) != len(set(ids)):
        raise ValueError("punteros.yaml: hay reglas con el mismo id")
    return reglas


@lru_cache(maxsize=1)
def reglas_vigentes() -> tuple[ReglaPuntero, ...]:
    return cargar_reglas()


_DESTINO = f"""
    SELECT f.id_fragmento::text AS id_fragmento, f.id_documento::text AS id_documento, d.titulo,
           d.codigo_documento, d.idioma, f.seccion, f.pagina_inicio, f.pagina_fin, f.texto, f.tipo_contenido,
           f.edad_min_meses, f.edad_max_meses, f.poblacion, f.rango_dudoso, f.numero_tokens
      FROM conocimiento.fragmento f
      JOIN conocimiento.documento_fuente d ON d.id_documento = f.id_documento
     WHERE d.codigo_documento = :codigo AND strpos(f.seccion, :marca) > 0 AND {CONDICION_RECUPERABLE}
     ORDER BY f.numero_orden
"""


def buscar_destino(sesion: Session | Connection, regla: ReglaPuntero):
    """Fila del fragmento destino, o None si no hay exactamente uno recuperable o si supera
    MAX_TOKENS_AGREGADO."""
    filas = sesion.execute(text(_DESTINO), {"codigo": regla.documento_destino, "marca": regla.marca_seccion}).all()
    if len(filas) != 1 or (filas[0].numero_tokens or 0) > MAX_TOKENS_AGREGADO:
        return None
    return filas[0]


# ---------------------------------------------------------------------------
# Fragmentos garantizados por la clasificación (sección garantizados de punteros.yaml)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ContextoClinico:
    """Datos estructurados del tamizaje que deciden las reglas garantizadas."""
    clasificacion: str | None
    requiere_derivacion: bool = False


@dataclass(frozen=True)
class ReglaGarantizada:
    id: str
    clasificaciones: frozenset[str]
    con_derivacion: bool
    documento: str
    pagina: int
    encabezado: str
    patron: re.Pattern

    def aplica_a(self, contexto: ContextoClinico | None) -> bool:
        if contexto is None:
            return False
        return contexto.clasificacion in self.clasificaciones or (self.con_derivacion and contexto.requiere_derivacion)


def _patron_encabezado(encabezado: str) -> re.Pattern:
    """El encabezado al inicio de una línea, sin distinguir mayúsculas y con cualquier espacio entre
    las palabras («7. Tratamiento de anemia severa» no coincide con «17. Tratamiento ...»)."""
    palabras = encabezado.split()
    if not palabras:
        raise ValueError("encabezado vacío")
    return re.compile(r"^[ \t]*" + r"\s+".join(re.escape(p) for p in palabras), re.IGNORECASE | re.MULTILINE)


def _garantizada(datos: dict) -> ReglaGarantizada:
    clasificaciones = frozenset(str(c) for c in datos.get("clasificaciones") or [])
    con_derivacion = bool(datos.get("requiere_derivacion", False))
    if not clasificaciones and not con_derivacion:
        raise ValueError(f"Regla {datos['id']}: no tiene clasificaciones ni requiere_derivacion")
    return ReglaGarantizada(
        id=str(datos["id"]), clasificaciones=clasificaciones, con_derivacion=con_derivacion,
        documento=str(datos["documento"]), pagina=int(datos["pagina"]), encabezado=str(datos["encabezado"]),
        patron=_patron_encabezado(str(datos["encabezado"])))


def cargar_garantizadas(ruta: Path = REGLAS) -> tuple[ReglaGarantizada, ...]:
    datos = yaml.safe_load(ruta.read_text(encoding="utf-8")) or {}
    reglas = tuple(_garantizada(r) for r in datos.get("garantizados") or [])
    ids = [r.id for r in reglas]
    if len(ids) != len(set(ids)):
        raise ValueError("punteros.yaml: hay reglas garantizadas con el mismo id")
    return reglas


@lru_cache(maxsize=1)
def garantizadas_vigentes() -> tuple[ReglaGarantizada, ...]:
    return cargar_garantizadas()


_GARANTIZADO = f"""
    SELECT f.id_fragmento::text AS id_fragmento, f.id_documento::text AS id_documento, d.titulo,
           d.codigo_documento, d.idioma, f.seccion, f.pagina_inicio, f.pagina_fin, f.texto, f.tipo_contenido,
           f.edad_min_meses, f.edad_max_meses, f.poblacion, f.rango_dudoso, f.numero_tokens
      FROM conocimiento.fragmento f
      JOIN conocimiento.documento_fuente d ON d.id_documento = f.id_documento
     WHERE d.codigo_documento = :codigo AND f.pagina_inicio <= :pagina AND COALESCE(f.pagina_fin, f.pagina_inicio) >= :pagina
       AND {CONDICION_RECUPERABLE}
     ORDER BY f.numero_orden
"""


def buscar_garantizado(sesion: Session | Connection, regla: ReglaGarantizada):
    """Fila del fragmento de la regla, o None si no hay exactamente uno recuperable del documento que
    incluya la página y tenga el encabezado, o si supera MAX_TOKENS_AGREGADO."""
    filas = [f for f in sesion.execute(text(_GARANTIZADO), {"codigo": regla.documento, "pagina": regla.pagina}).all()
             if regla.patron.search(f.texto or "")]
    if len(filas) != 1 or (filas[0].numero_tokens or 0) > MAX_TOKENS_AGREGADO:
        return None
    return filas[0]
