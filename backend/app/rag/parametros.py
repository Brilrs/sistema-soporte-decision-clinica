"""Parámetros de la recuperación, leídos de configuracion.parametro_sistema con su
vigencia. Ningún valor operativo queda fijo en el código: la coordinación los
cambia desde M12 y el cambio se aplica en la siguiente consulta."""
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import Connection, text
from sqlalchemy.orm import Session

CLAVES = {
    "CANDIDATOS_BUSQUEDA": "candidatos_busqueda",
    "CANDIDATOS_BUSQUEDA_AMPLIADA": "candidatos_busqueda_ampliada",
    "RRF_K": "rrf_k",
    "FRAGMENTOS_ENVIADOS": "fragmentos_enviados",
    "UMBRAL_RELEVANCIA": "umbral_relevancia",
    "UMBRAL_DOMINIO": "umbral_dominio",
    "CANDIDATOS_RERANKER": "candidatos_reranker",
    "MAX_LONGITUD_RERANKER": "max_longitud_reranker",
    "DIAS_VIGENCIA_TAMIZAJE": "dias_vigencia_tamizaje",
    "BONIFICACION_EDAD": "bonificacion_edad",
}


class ErrorParametro(Exception):
    """Falta un parámetro vigente o su valor no es válido."""


@dataclass(frozen=True)
class ParametrosRecuperacion:
    candidatos_busqueda: int
    candidatos_busqueda_ampliada: int
    rrf_k: int
    fragmentos_enviados: int
    umbral_relevancia: float
    umbral_dominio: float
    candidatos_reranker: int
    max_longitud_reranker: int
    dias_vigencia_tamizaje: int
    bonificacion_edad: float


def _convertir(clave: str, valor: str, tipo: str, minimo: Decimal | None, maximo: Decimal | None):
    try:
        numero = int(valor) if tipo == "ENTERO" else float(Decimal(valor)) if tipo == "DECIMAL" else None
    except (ValueError, ArithmeticError) as e:
        raise ErrorParametro(f"{clave}: el valor «{valor}» no es de tipo {tipo}") from e
    if numero is None:
        return valor
    if (minimo is not None and numero < minimo) or (maximo is not None and numero > maximo):
        raise ErrorParametro(f"{clave}: {numero} está fuera del rango permitido ({minimo} a {maximo})")
    return numero


def leer_parametros(sesion: Session | Connection, claves: list[str] | None = None) -> dict:
    """Valor vigente de cada clave, convertido según tipo_dato y validado con su rango."""
    claves = claves or list(CLAVES)
    filas = sesion.execute(text(
        """SELECT DISTINCT ON (clave) clave, valor, tipo_dato, valor_minimo, valor_maximo
             FROM configuracion.parametro_sistema
            WHERE clave = ANY(:claves)
              AND vigente_desde <= now() AND (vigente_hasta IS NULL OR vigente_hasta > now())
            ORDER BY clave, vigente_desde DESC"""
    ), {"claves": claves}).all()
    valores = {f.clave: _convertir(f.clave, f.valor, f.tipo_dato, f.valor_minimo, f.valor_maximo) for f in filas}
    faltantes = sorted(set(claves) - valores.keys())
    if faltantes:
        raise ErrorParametro(f"No hay valor vigente para: {', '.join(faltantes)}")
    return valores


def parametros_recuperacion(sesion: Session | Connection) -> ParametrosRecuperacion:
    valores = leer_parametros(sesion)
    return ParametrosRecuperacion(**{CLAVES[k]: v for k, v in valores.items()})
