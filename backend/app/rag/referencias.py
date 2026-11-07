"""Consultas de referencia (calidad de la recuperación), de latencia, del conjunto de
validación y del conjunto de prueba final, y criterio de acierto: una consulta acierta si algún fragmento del top 5
cumple alguna de sus secciones esperadas."""
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import yaml

from app.rag.consulta_estructurada import ContextoClinico, construir_consulta

DIR = Path(__file__).parent
VALIDACION = DIR / "consultas_validacion.yaml"
PRUEBA = DIR / "consultas_prueba.yaml"


@dataclass(frozen=True)
class Esperado:
    documento: str
    seccion_contiene: str | None = None
    texto_contiene: str | None = None
    paginas: tuple[int, int] | None = None
    agregada_tras_resultado: bool = False

    def cumple(self, codigo_documento: str | None, seccion: str | None, texto: str,
               pagina_inicio: int | None, pagina_fin: int | None) -> bool:
        if codigo_documento != self.documento:
            return False
        if self.seccion_contiene is not None:
            return self.seccion_contiene.lower() in (seccion or "").lower()
        if self.texto_contiene is not None:
            return self.texto_contiene.lower() in texto.lower()
        if self.paginas is not None and pagina_inicio is not None:
            return pagina_inicio <= self.paginas[1] and (pagina_fin or pagina_inicio) >= self.paginas[0]
        return False


@dataclass(frozen=True)
class ConsultaReferencia:
    id: str
    consulta: str
    esperado: tuple[Esperado, ...]
    idioma_fuente: str = "es"

    def acierta(self, fragmento, original: bool = False) -> bool:
        """original: solo las secciones esperadas escritas antes de ver los resultados."""
        return any(e.cumple(fragmento.codigo_documento, fragmento.seccion, fragmento.texto, fragmento.pagina_inicio,
                            fragmento.pagina_fin)
                   for e in self.esperado if not (original and e.agregada_tras_resultado))

    @property
    def corregida_tras_resultado(self) -> bool:
        return any(e.agregada_tras_resultado for e in self.esperado)


def _esperados(c: dict) -> tuple[Esperado, ...]:
    return tuple(Esperado(documento=e["documento"], seccion_contiene=e.get("seccion_contiene"),
                          texto_contiene=e.get("texto_contiene"),
                          paginas=tuple(e["paginas"]) if e.get("paginas") else None,
                          agregada_tras_resultado=bool(e.get("agregada_tras_resultado", False)))
                 for e in c["esperado"])


def _consulta(c: dict, texto: str) -> ConsultaReferencia:
    return ConsultaReferencia(id=c["id"], consulta=texto, idioma_fuente=c.get("idioma_fuente", "es"),
                              esperado=_esperados(c))


def cargar_consultas_referencia(ruta: Path = DIR / "consultas_referencia.yaml") -> list[ConsultaReferencia]:
    datos = yaml.safe_load(ruta.read_text(encoding="utf-8"))
    return [_consulta(c, c["consulta"]) for c in datos["consultas"]]


def contexto_desde_yaml(datos: dict) -> ContextoClinico:
    valores = dict(datos)
    for campo in ("hb_ajustada_g_dl", "ajuste_hb_g_dl"):
        if valores.get(campo) is not None:
            valores[campo] = Decimal(str(valores[campo]))
    valores["sintomas"] = tuple(valores.get("sintomas") or ())
    return ContextoClinico(**valores)


def cargar_conjunto_prueba(ruta: Path = PRUEBA) -> list[ConsultaReferencia]:
    """Conjunto de prueba final: los casos clínicos con la consulta que arma
    construir_consulta y las preguntas libres. Solo para la medición final."""
    datos = yaml.safe_load(ruta.read_text(encoding="utf-8"))
    casos = [_consulta(c, construir_consulta(contexto_desde_yaml(c["contexto"]))) for c in datos["casos"]]
    return casos + [_consulta(c, c["consulta"]) for c in datos["libres"]]


def cargar_consultas_latencia(ruta: Path = DIR / "consultas_latencia.yaml") -> list[str]:
    return [str(c) for c in yaml.safe_load(ruta.read_text(encoding="utf-8"))["consultas"]]


def cargar_validacion_dominio(ruta: Path = VALIDACION) -> tuple[list[str], list[str]]:
    """Consultas del conjunto de validación para el filtro de dominio: (dentro, fuera)."""
    datos = yaml.safe_load(ruta.read_text(encoding="utf-8"))["dominio"]
    return [str(t) for t in datos["dentro"]], [str(t) for t in datos["fuera"]]
