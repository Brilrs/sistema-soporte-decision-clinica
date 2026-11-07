"""Consultas de referencia (calidad de la recuperación), de latencia y del conjunto de
validación, y criterio de acierto: una consulta acierta si algún fragmento del top 5
cumple alguna de sus secciones esperadas."""
from dataclasses import dataclass
from pathlib import Path

import yaml

DIR = Path(__file__).parent
VALIDACION = DIR / "consultas_validacion.yaml"


@dataclass(frozen=True)
class Esperado:
    documento: str
    seccion_contiene: str | None = None
    texto_contiene: str | None = None
    paginas: tuple[int, int] | None = None

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

    def acierta(self, fragmento) -> bool:
        return any(e.cumple(fragmento.codigo_documento, fragmento.seccion, fragmento.texto, fragmento.pagina_inicio,
                            fragmento.pagina_fin) for e in self.esperado)


def cargar_consultas_referencia(ruta: Path = DIR / "consultas_referencia.yaml") -> list[ConsultaReferencia]:
    datos = yaml.safe_load(ruta.read_text(encoding="utf-8"))
    return [
        ConsultaReferencia(
            id=c["id"], consulta=c["consulta"], idioma_fuente=c.get("idioma_fuente", "es"),
            esperado=tuple(Esperado(documento=e["documento"], seccion_contiene=e.get("seccion_contiene"),
                                    texto_contiene=e.get("texto_contiene"),
                                    paginas=tuple(e["paginas"]) if e.get("paginas") else None)
                           for e in c["esperado"]),
        )
        for c in datos["consultas"]
    ]


def cargar_consultas_latencia(ruta: Path = DIR / "consultas_latencia.yaml") -> list[str]:
    return [str(c) for c in yaml.safe_load(ruta.read_text(encoding="utf-8"))["consultas"]]


def cargar_validacion_dominio(ruta: Path = VALIDACION) -> tuple[list[str], list[str]]:
    """Consultas del conjunto de validación para el filtro de dominio: (dentro, fuera)."""
    datos = yaml.safe_load(ruta.read_text(encoding="utf-8"))["dominio"]
    return [str(t) for t in datos["dentro"]], [str(t) for t in datos["fuera"]]
