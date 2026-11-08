"""Capa 6 · Verificación de la respuesta y decisión de reintento (Tablas 9 y 10 de la guía OE2).

Controles en línea:
- 6.1 Citas: cada paso de la recomendación tiene al menos una cita; toda etiqueta citada
  corresponde a un fragmento enviado en ese intento; cada etiqueta de los pasos tiene su
  extracto, y el extracto aparece en el texto de ese fragmento. Además (controles
  adicionales de la parte C): las cifras de dosis de la recomendación figuran en los
  fragmentos citados con la misma unidad; las cifras y unidades de extracto_traducido
  coinciden con las del extracto original, y los fragmentos citados siguen vigentes.
  Se acepta además una dosis derivada en mg si se cumplen tres condiciones: el fragmento
  citado tiene una cifra en mg/kg/día (o en mg/kg por dosis con la frecuencia indicada),
  el peso es el de los datos estructurados de la solicitud (peso_kg, no una cifra escrita
  por el modelo) y el valor es peso x cifra con una tolerancia del 1 %.
- 6.2 Consistencia clínica: la clasificación y el nivel de riesgo de la respuesta son
  los que calculó el sistema; sin anemia (o sin clasificación) no hay pasos de
  tratamiento, y si la clasificación requiere derivación hay un paso de derivación.
- 6.3 Suficiencia de la evidencia: el puntaje máximo del reranker alcanza
  UMBRAL_RELEVANCIA y el modelo no declaró evidencia insuficiente.

Decisión (decidir), con un único reintento:
- Los tres controles se cumplen: APROBADO, consulta VERIFICADA.
- Falla 6.3 en el primer intento: búsqueda ampliada y nueva generación.
- Falla 6.1 o 6.2, o la respuesta es inválida (no cumple el esquema o se cortó por
  max_tokens), en el primer intento: nueva generación con los mismos fragmentos.
- Cualquier falla de 6.1, 6.2 o 6.3 en el reintento: EVIDENCIA_INSUFICIENTE.
- Respuesta inválida en el reintento: ERROR.
- Tiempo agotado, rechazo o error de la API (no están en la Tabla 10): ERROR sin
  reintento, para no pasar del máximo de 25 s del RNF3 y porque no hay modelo de
  respaldo (MODELO_RESPALDO vacío).
- Solicitud bloqueada por el control previo: ERROR."""
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field

from app.rag import generacion as gen
from app.rag.proteccion import DatosClinicos, SolicitudProtegida

SIN_CLASIFICACION = "SIN_CLASIFICACION"
SIN_ANEMIA = "SIN_ANEMIA"
TRATAMIENTO = "TRATAMIENTO"
DERIVACION = "DERIVACION"

APROBADO = "APROBADO"
REINTENTO = "REINTENTO"
EVIDENCIA_INSUFICIENTE = "EVIDENCIA_INSUFICIENTE"
ERROR = "ERROR"
VERIFICADA = "VERIFICADA"
REGENERAR = "REGENERAR"
AMPLIADA = "AMPLIADA"

MENSAJE_EVIDENCIA_INSUFICIENTE = "Evidencia insuficiente: aplicar criterio clínico."
MENSAJE_NO_EVALUADA = "No se pudo evaluar la consulta. Aplique su criterio clínico."

_UNIDADES = [
    (r"mg\s*/\s*kg(?:\s*/\s*(?:d[ií]a|day|d))?", "mg/kg"),
    (r"mg", "mg"),
    (r"m[lL]", "ml"),
    (r"gotas?|drops?", "gotas"),
    (r"(?:mcg|µg|μg|ug)", "mcg"),
    (r"UI|IU", "UI"),
]
_DOSIS = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(" + "|".join(p for p, _ in _UNIDADES) + r")(?![\w/]*\s*d[lL])(?!\w)", re.IGNORECASE)
_NUMERO = re.compile(r"\d+(?:[.,]\d+)?")
_SIMBOLOS_DE_TABLA = re.compile(r"[|_•*·]+")
_POR_KG = re.compile(r"(\d+(?:[.,]\d+)?)\s*mg\s*/\s*kg(\s*/\s*(?:d[ií]a|day|d)\b)?", re.IGNORECASE)
# Frecuencia que acompaña a una dosis en mg/kg sin «/día», en el texto que la sigue.
_FRECUENCIA = re.compile(r"diari|al d[ií]a|por d[ií]a|cada \d+|veces al|por dosis|una vez|daily|per day|per dose|"
                         r"once|twice|semanal|weekly", re.IGNORECASE)
_VENTANA_FRECUENCIA = 80
TOLERANCIA_DOSIS_DERIVADA = 0.01
_COMILLAS = str.maketrans({"“": '"', "”": '"', "«": '"', "»": '"', "‘": "'", "’": "'", "\u2013": "-", "\u2014": "-",
                           " ": " "})


@dataclass
class ResultadoVerificacion:
    valida_citas: bool
    valida_consistencia: bool
    valida_evidencia: bool
    motivos: list[str] = field(default_factory=list)

    @property
    def aprobada(self) -> bool:
        return self.valida_citas and self.valida_consistencia and self.valida_evidencia


@dataclass(frozen=True)
class Decision:
    resultado_intento: str
    siguiente: str | None
    estado_final: str | None
    mensaje: str | None


def normalizar_texto(texto: str) -> str:
    """Para comparar extractos, igual en los dos lados: Unicode NFC, comillas y guiones
    unificados, símbolos de tabla y de viñeta (|, guiones bajos, •, *, ·) como espacios,
    espacios y saltos de línea simples y sin mayúsculas. Solo quita formato: las
    palabras y su orden deben coincidir (sin coincidencia aproximada)."""
    t = unicodedata.normalize("NFC", texto).translate(_COMILLAS)
    t = _SIMBOLOS_DE_TABLA.sub(" ", t)
    return " ".join(t.split()).lower()


def _numero(n: str) -> str:
    return n.replace(",", ".")


def _familia(unidad: str) -> str:
    for patron, familia in _UNIDADES:
        if re.fullmatch(patron, unidad, re.IGNORECASE):
            return familia
    return unidad.lower()


def dosis(texto: str) -> set[tuple[str, str]]:
    """Cifras de dosis (número y familia de unidad) de un texto; no cuenta g/dL."""
    return {(_numero(n), _familia(u)) for n, u in _DOSIS.findall(texto)}


def cifras(texto: str) -> Counter:
    return Counter(_numero(n) for n in _NUMERO.findall(texto))


def cifras_por_kg(texto: str) -> set[float]:
    """Cifras en mg/kg/día, o en mg/kg con la frecuencia indicada, de un fragmento."""
    cifras_kg = set()
    for m in _POR_KG.finditer(texto):
        if m.group(2) or _FRECUENCIA.search(texto[m.end():m.end() + _VENTANA_FRECUENCIA]):
            cifras_kg.add(float(_numero(m.group(1))))
    return cifras_kg


def es_dosis_derivada(cifra: tuple[str, str], por_kg: set[float], peso_kg: float | None) -> bool:
    """Una dosis en mg igual al peso de los datos estructurados por una cifra en mg/kg del
    fragmento citado, con TOLERANCIA_DOSIS_DERIVADA."""
    numero, familia = cifra
    if familia != "mg" or not peso_kg or not por_kg:
        return False
    valor = float(numero)
    return any(abs(valor - peso_kg * c) <= TOLERANCIA_DOSIS_DERIVADA * peso_kg * c for c in por_kg)


def _etiquetas_de_pasos(respuesta: dict) -> list[str]:
    return [e for paso in respuesta["recomendacion"] for e in paso["citas"]]


def control_citas(respuesta: dict, solicitud: SolicitudProtegida, vigentes: set[str],
                  peso_kg: float | None = None) -> list[str]:
    """6.1 y los controles adicionales. Devuelve los motivos de falla (vacío si pasa)."""
    motivos = []
    enviadas = solicitud.etiquetas
    idioma = solicitud.contenido["idioma_respuesta"]
    citas = {}
    for cita in respuesta["citas"]:
        citas.setdefault(cita["etiqueta"], []).append(cita)
    for i, paso in enumerate(respuesta["recomendacion"], start=1):
        if not paso["citas"]:
            motivos.append(f"6.1: el paso {i} no tiene cita")
    for e in sorted(set(_etiquetas_de_pasos(respuesta)) | set(citas)):
        if e not in enviadas:
            motivos.append(f"6.1: {e} no corresponde a un fragmento enviado")
    for e in sorted(set(_etiquetas_de_pasos(respuesta)) - set(citas)):
        if e in enviadas:
            motivos.append(f"6.1: {e} se cita sin extracto")
    for e, lista in citas.items():
        f = enviadas.get(e)
        if f is None:
            continue
        for cita in lista:
            if normalizar_texto(cita["extracto"]) not in normalizar_texto(f.texto):
                motivos.append(f"6.1: el extracto de {e} no aparece en el fragmento")
            traducido = cita.get("extracto_traducido")
            if f.idioma != idioma and not traducido:
                motivos.append(f"Traducción: falta la traducción de apoyo de {e}")
            if traducido and (cifras(traducido) != cifras(cita["extracto"])
                              or dosis(traducido) != dosis(cita["extracto"])):
                motivos.append(f"Traducción: las cifras o unidades de {e} no coinciden con el original")
        if f.id_fragmento not in vigentes:
            motivos.append(f"Vigencia: {e} ya no es un fragmento vigente")
    for i, paso in enumerate(respuesta["recomendacion"], start=1):
        fuentes = [enviadas[e].texto for e in paso["citas"] if e in enviadas]
        disponibles = set().union(*(dosis(t) for t in fuentes)) if fuentes else set()
        por_kg = set().union(*(cifras_por_kg(t) for t in fuentes)) if fuentes else set()
        faltan = {d for d in dosis(paso["texto"]) - disponibles if not es_dosis_derivada(d, por_kg, peso_kg)}
        if faltan:
            motivos.append(f"Dosis: el paso {i} tiene cifras que no están en sus fragmentos citados "
                           f"({', '.join(f'{n} {u}' for n, u in sorted(faltan))})")
    return motivos


def control_consistencia(respuesta: dict, datos: DatosClinicos) -> list[str]:
    """6.2."""
    motivos = []
    clasificacion = datos.clasificacion or SIN_CLASIFICACION
    riesgo = datos.nivel_riesgo or SIN_CLASIFICACION
    if respuesta["clasificacion_confirmada"] != clasificacion:
        motivos.append("6.2: la clasificación de la respuesta no es la calculada por el sistema")
    if respuesta["nivel_riesgo"] != riesgo:
        motivos.append("6.2: el nivel de riesgo de la respuesta no es el calculado por el sistema")
    tipos = {p["tipo"] for p in respuesta["recomendacion"]}
    if clasificacion in (SIN_ANEMIA, SIN_CLASIFICACION) and TRATAMIENTO in tipos:
        motivos.append("6.2: indica tratamiento de la anemia a un niño sin anemia")
    if datos.requiere_derivacion and respuesta["evidencia_suficiente"] and DERIVACION not in tipos:
        motivos.append("6.2: la clasificación requiere derivación y la respuesta no la indica")
    return motivos


def control_evidencia(respuesta: dict | None, relevancia_maxima: float | None, umbral: float) -> list[str]:
    """6.3. Con respuesta None se evalúa solo el puntaje (antes de llamar al modelo)."""
    motivos = []
    if relevancia_maxima is None or relevancia_maxima < umbral:
        motivos.append("6.3: el puntaje máximo del reranker no alcanza el umbral")
    if respuesta is not None and (not respuesta["evidencia_suficiente"] or not respuesta["recomendacion"]):
        motivos.append("6.3: el modelo declaró evidencia insuficiente")
    return motivos


def verificar(respuesta: dict, solicitud: SolicitudProtegida, datos: DatosClinicos, relevancia_maxima: float | None,
              umbral: float, vigentes: set[str]) -> ResultadoVerificacion:
    citas = control_citas(respuesta, solicitud, vigentes, datos.peso_kg)
    consistencia = control_consistencia(respuesta, datos)
    evidencia = control_evidencia(respuesta, relevancia_maxima, umbral)
    return ResultadoVerificacion(not citas, not consistencia, not evidencia, citas + consistencia + evidencia)


def decidir(numero_intento: int, estado_generacion: str | None, verificacion: ResultadoVerificacion | None,
            bloqueada: bool = False) -> Decision:
    """Tabla 10, más los casos que la tabla no cubre (ver el docstring del módulo).
    estado_generacion es None cuando no se llamó al modelo (6.3 falló antes)."""
    primero = numero_intento == 1
    if bloqueada or estado_generacion in (gen.TIEMPO_AGOTADO, gen.RECHAZO, gen.ERROR_API):
        return Decision(ERROR, None, ERROR, MENSAJE_NO_EVALUADA)
    if estado_generacion == gen.INVALIDA:
        if primero:
            return Decision(REINTENTO, REGENERAR, None, None)
        return Decision(ERROR, None, ERROR, MENSAJE_NO_EVALUADA)
    if verificacion is not None and verificacion.aprobada:
        return Decision(APROBADO, None, VERIFICADA, None)
    if not primero:
        return Decision(EVIDENCIA_INSUFICIENTE, None, EVIDENCIA_INSUFICIENTE, MENSAJE_EVIDENCIA_INSUFICIENTE)
    if verificacion is None or not verificacion.valida_evidencia:
        return Decision(REINTENTO, AMPLIADA, None, None)
    return Decision(REINTENTO, REGENERAR, None, None)
