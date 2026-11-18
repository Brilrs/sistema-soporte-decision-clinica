"""Consultas de referencia (calidad de la recuperación), de latencia, del conjunto de
validación y del conjunto de prueba final, y criterio de acierto: una consulta acierta si algún fragmento del top 5
cumple alguna de sus secciones esperadas."""
import re
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import yaml

from app.rag.consulta_estructurada import ContextoClinico, combinar_consulta, construir_consulta

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


CALENDARIO = DIR / "consultas_calendario.yaml"
CALENDARIO_B = DIR / "consultas_calendario_b.yaml"
CALENDARIO_TIPO = "CALENDARIO"
TRATAMIENTO_TIPO = "TRATAMIENTO"
RM429 = "RM 429-2024/MINSA"
NTS213 = "NTS 213-MINSA/DGIESP-2024"
TITULO_TABLA_20 = "Control de hemoglobina en el tratamiento de anemia"
# Mención de la Tabla N° 20 (no la N° 2 ni la N° 200): la tiene la tabla y el fragmento
# «Seguimiento de casos de anemia» de la NTS 213, que la cita.
_MENCION_TABLA_20 = re.compile(r"Tabla N° 20(?!\d)")
LIBRE, ESTRUCTURADA, COMBINADA = "libre", "estructurada", "combinada"


@dataclass(frozen=True)
class ConsultaCalendario:
    """Consulta de un conjunto de aceptación del calendario de control de hemoglobina (parte G).

    Criterios, sobre un fragmento enviado al modelo:
      CALENDARIO: fragmento de la RM 429 con la fila de la Tabla N° 4 de la edad (estricto y
        aceptado son el mismo).
      TRATAMIENTO estricto: fragmento de la NTS 213 con el título de la Tabla N° 20.
      TRATAMIENTO aceptado: fragmento de la NTS 213 que menciona la Tabla N° 20 (la tabla o el
        fragmento que la cita)."""
    id: str
    tipo: str
    consulta: str
    edad_meses: int
    fila: str | None = None
    estructurada: bool = False
    forma: str = LIBRE

    def acierta_estricto(self, fragmento) -> bool:
        if self.tipo == CALENDARIO_TIPO:
            return fragmento.codigo_documento == RM429 and f"| {self.fila} |" in fragmento.texto
        return fragmento.codigo_documento == NTS213 and TITULO_TABLA_20 in fragmento.texto

    def acierta_aceptado(self, fragmento) -> bool:
        if self.tipo == CALENDARIO_TIPO:
            return self.acierta_estricto(fragmento)
        return fragmento.codigo_documento == NTS213 and bool(_MENCION_TABLA_20.search(fragmento.texto))

    def acierta(self, fragmento) -> bool:
        """Criterio del conjunto A (el estricto)."""
        return self.acierta_estricto(fragmento)


def huella_archivo(ruta: Path) -> str:
    """SHA-256 del contenido con fin de línea LF (el que guarda git), igual en Windows y en Linux."""
    import hashlib
    return hashlib.sha256(ruta.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def _consulta_calendario(c: dict) -> ConsultaCalendario:
    """Libre: la pregunta sola. Estructurada: construir_consulta del contexto. Combinada: la
    estructurada más la pregunta, como la arma el grafo (combinar_consulta)."""
    if "contexto" in c:
        texto = combinar_consulta(construir_consulta(contexto_desde_yaml(c["contexto"])), c.get("pregunta"))
        forma = COMBINADA if c.get("pregunta") else ESTRUCTURADA
    else:
        texto, forma = c["consulta"], LIBRE
    return ConsultaCalendario(id=c["id"], tipo=c["tipo"], edad_meses=int(c["edad_meses"]), fila=c.get("fila"),
                              consulta=texto, estructurada="contexto" in c, forma=forma)


def cargar_conjunto_calendario(ruta: Path = CALENDARIO) -> list[ConsultaCalendario]:
    return [_consulta_calendario(c) for c in yaml.safe_load(ruta.read_text(encoding="utf-8"))["consultas"]]


def cargar_consultas_latencia(ruta: Path = DIR / "consultas_latencia.yaml") -> list[str]:
    return [str(c) for c in yaml.safe_load(ruta.read_text(encoding="utf-8"))["consultas"]]


def cargar_validacion_dominio(ruta: Path = VALIDACION) -> tuple[list[str], list[str]]:
    """Consultas del conjunto de validación para el filtro de dominio: (dentro, fuera)."""
    datos = yaml.safe_load(ruta.read_text(encoding="utf-8"))["dominio"]
    return [str(t) for t in datos["dentro"]], [str(t) for t in datos["fuera"]]
