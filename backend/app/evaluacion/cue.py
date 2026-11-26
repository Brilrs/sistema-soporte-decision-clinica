"""CUE del OE2, éxito de recuperación, corrección, adherencia y cuadrantes RAG-X
(docs/diseno_evaluacion_oe3.md, secciones 3 y 4). Funciones puras: no leen la base ni llaman al juez.

- Éxito de recuperación: están todos los criterios obligatorios entre los fragmentos realmente
  enviados («y» entre criterios, «o» entre alternativas), solo con fragmentos vigentes de la última
  versión de un documento VIGENTE.
- Cruce de una alternativa con un fragmento: mismo documento, páginas que se superponen y texto de
  anclaje contenido en el texto del fragmento, los dos normalizados.
- Cuadrantes: los cuatro del artículo RAG-X más una categoría propia del proyecto para la
  combinación que el artículo no define.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from app.evaluacion.dataset import Alternativa, Criterio

UMBRAL_ADHERENCIA = 0.7  # del artículo RAG-X

USO_EFECTIVO = "uso_efectivo"
CEGUERA = "ceguera_de_informacion"
ACIERTO_SUERTE = "acierto_por_suerte_o_alucinacion"
RECHAZO_CORRECTO = "rechazo_correcto"
# Decisión del proyecto, no del artículo: recuperación fallida, respuesta incorrecta y adherencia alta.
FUERA_CUADRANTES = "incorrecta_con_contexto_fallido"
NO_APLICA = "no_aplica"
SIN_JUICIO = "sin_juicio"
CUADRANTES = (USO_EFECTIVO, CEGUERA, ACIERTO_SUERTE, RECHAZO_CORRECTO)
CATEGORIAS = CUADRANTES + (FUERA_CUADRANTES, NO_APLICA, SIN_JUICIO)

VERIFICADA = "VERIFICADA"
EVIDENCIA_INSUFICIENTE = "EVIDENCIA_INSUFICIENTE"
CON_GENERACION = (VERIFICADA, EVIDENCIA_INSUFICIENTE)

_GUIONES = re.compile("[\u2010-\u2015\u2212]")
_ESPACIOS = re.compile(r"\s+")


def normalizar(texto: str) -> str:
    """NFKC, guiones y rayas a «-», comillas tipográficas a rectas, espacios colapsados y sin
    distinguir mayúsculas (sección 4.1 del diseño)."""
    t = unicodedata.normalize("NFKC", texto)
    t = _GUIONES.sub("-", t)
    t = t.replace("\u2019", "'").replace("\u2018", "'").replace("\u201c", '"').replace("\u201d", '"')
    return _ESPACIOS.sub(" ", t).strip().casefold()


@dataclass(frozen=True)
class Fragmento:
    """Fragmento enviado al modelo (o candidato) tal como lo extrae extraer.py."""
    etiqueta: str | None
    id_fragmento: str
    documento: str
    pagina_inicio: int | None
    pagina_fin: int | None
    texto: str
    vigente: bool
    enviado: bool = True
    idioma: str = "es"
    origen: str = "RERANKER"


def cumple(alternativa: Alternativa, fragmento: Fragmento) -> bool:
    if not fragmento.vigente or fragmento.documento != alternativa.documento:
        return False
    if fragmento.pagina_inicio is None:
        return False
    fin = fragmento.pagina_fin if fragmento.pagina_fin is not None else fragmento.pagina_inicio
    if fin < alternativa.paginas[0] or fragmento.pagina_inicio > alternativa.paginas[1]:
        return False
    return normalizar(alternativa.texto_anclaje) in normalizar(fragmento.texto)


@dataclass
class Recuperacion:
    """Resultado de cruzar los criterios con un grupo de fragmentos."""
    exito: bool
    sin_criterios: bool
    obligatorios: int
    obligatorios_cumplidos: int
    opcionales: int
    opcionales_cumplidos: int
    # Criterio -> etiquetas (o ids) de los fragmentos que lo cumplen
    por_criterio: dict[str, list[str]] = field(default_factory=dict)
    # El éxito depende de una alternativa con equivalencia pendiente de la ficha del CRED
    depende_de_equivalencia_pendiente: bool = False

    @property
    def cobertura(self) -> float | None:
        return None if self.obligatorios == 0 else self.obligatorios_cumplidos / self.obligatorios


def evaluar_criterios(criterios: list[Criterio], fragmentos: list[Fragmento]) -> Recuperacion:
    """«y» entre criterios obligatorios, «o» entre alternativas. Un caso sin criterios no tiene
    evidencia que recuperar: cuenta como recuperación fallida (sección 3.3)."""
    if not criterios:
        return Recuperacion(False, True, 0, 0, 0, 0)
    por_criterio: dict[str, list[str]] = {}
    pendiente = False
    ob = ob_ok = op = op_ok = 0
    for c in criterios:
        firmes, solo_pendientes = [], []
        for f in fragmentos:
            alternativas = [a for a in c.alternativas if cumple(a, f)]
            if not alternativas:
                continue
            nombre = f.etiqueta or f.id_fragmento
            if any(not a.equivalencia_pendiente for a in alternativas):
                firmes.append(nombre)
            else:
                solo_pendientes.append(nombre)
        cumplido = bool(firmes or solo_pendientes)
        por_criterio[c.id] = sorted(set(firmes + solo_pendientes))
        if c.obligatorio:
            ob += 1
            ob_ok += cumplido
            if cumplido and not firmes:
                pendiente = True
        else:
            op += 1
            op_ok += cumplido
    exito = ob > 0 and ob_ok == ob
    return Recuperacion(exito, False, ob, ob_ok, op, op_ok, por_criterio, exito and pendiente)


# ---------------------------------------------------------------------------
# CUE
# ---------------------------------------------------------------------------
def cue_desde_juicio(juicio: dict | None, enviados: list[str]) -> dict:
    """CUE del OE2 por consulta a partir de la salida del juez de afirmaciones.

    B (cifra principal): fragmentos enviados que sustentan al menos una afirmación de la
    respuesta emparejada con una afirmación clave del caso, entre los enviados.
    A: lo mismo con todas las afirmaciones de la respuesta.
    Sin fragmentos enviados no hay CUE (None) y la consulta se informa aparte."""
    if not enviados:
        return {"cue_b": None, "cue_a": None, "enviados": 0}
    if juicio is None:
        return {"cue_b": None, "cue_a": None, "enviados": len(enviados)}
    validos = set(enviados)
    todos, con_clave = set(), set()
    for a in juicio.get("afirmaciones", []):
        sustentan = validos & set(a.get("fragmentos") or [])
        todos |= sustentan
        if a.get("clave") is not None:
            con_clave |= sustentan
    n = len(enviados)
    return {"cue_b": len(con_clave) / n, "cue_a": len(todos) / n, "enviados": n,
            "aprovechados_b": sorted(con_clave), "aprovechados_a": sorted(todos)}


def cue_citas(citados: list[str], enviados: list[str]) -> float | None:
    """Variante sin juez: fragmentos enviados citados en la recomendación, entre los enviados."""
    if not enviados:
        return None
    return len(set(citados) & set(enviados)) / len(enviados)


# ---------------------------------------------------------------------------
# Corrección y cuadrantes
# ---------------------------------------------------------------------------
@dataclass
class Correccion:
    campos: dict[str, bool]
    claves_total: int
    claves_presentes: int
    claves_contradichas: int
    correcta: bool | None

    @property
    def fraccion_claves(self) -> float | None:
        return None if self.claves_total == 0 else self.claves_presentes / self.claves_total


def correccion(caso: dict, observado: dict, juicio: dict | None) -> Correccion:
    """Campos deterministas que el caso evalúa (los que no son null) y todas las afirmaciones
    clave presentes sin contradicción (decisión de la sección 3.3). None si falta el juicio y el
    caso tiene afirmaciones clave."""
    campos = {"estado": observado.get("estado") == caso["estado_esperado"]}
    if caso["clasificacion_esperada"] is not None:
        campos["clasificacion"] = observado.get("clasificacion") == caso["clasificacion_esperada"]
    if caso["requiere_derivacion"] is not None and observado.get("tiene_respuesta"):
        campos["derivacion"] = observado.get("derivacion_en_respuesta") == caso["requiere_derivacion"]
    if caso["evidencia_suficiente_esperada"] is not None and observado.get("tiene_respuesta"):
        campos["evidencia_suficiente"] = observado.get("evidencia_suficiente") == caso["evidencia_suficiente_esperada"]
    claves = caso["afirmaciones_clave"]
    if not claves:
        return Correccion(campos, 0, 0, 0, all(campos.values()))
    if juicio is None:
        return Correccion(campos, len(claves), 0, 0, None)
    estado = {c.get("indice"): c for c in juicio.get("claves", []) if isinstance(c.get("indice"), int)}
    presentes = sum(1 for i in range(len(claves)) if estado.get(i, {}).get("presente"))
    contradichas = sum(1 for i in range(len(claves)) if estado.get(i, {}).get("contradicha"))
    correcta = all(campos.values()) and presentes == len(claves) and contradichas == 0
    return Correccion(campos, len(claves), presentes, contradichas, correcta)


def cuadrante(estado: str | None, exito: bool, correcta: bool | None, adherencia: float | None,
              umbral: float = UMBRAL_ADHERENCIA) -> str:
    """Sección 3.3 del diseño.

    - Sin generación (fuera de dominio, datos faltantes, error...): no_aplica.
    - EVIDENCIA_INSUFICIENTE: ceguera si la recuperación acertó, rechazo correcto si falló.
    - VERIFICADA con recuperación exitosa: uso efectivo con adherencia >= umbral, si no ceguera.
    - VERIFICADA con recuperación fallida: acierto por suerte si la respuesta es correcta; si no,
      rechazo correcto con adherencia < umbral; si no, la categoría propia del proyecto.
    """
    if estado not in CON_GENERACION:
        return NO_APLICA
    if estado == EVIDENCIA_INSUFICIENTE:
        return CEGUERA if exito else RECHAZO_CORRECTO
    if exito:
        if adherencia is None:
            return SIN_JUICIO
        return USO_EFECTIVO if adherencia >= umbral else CEGUERA
    if correcta is None:
        return SIN_JUICIO
    if correcta:
        return ACIERTO_SUERTE
    if adherencia is None:
        return SIN_JUICIO
    return RECHAZO_CORRECTO if adherencia < umbral else FUERA_CUADRANTES
