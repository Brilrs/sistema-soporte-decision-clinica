"""Grupo etario de cada fragmento: edad mínima y máxima en meses y población.

Las reglas leen los títulos de la sección (normas MINSA) o el texto del fragmento (guías
de la OMS y modificatoria), según grupos_etarios.yaml, y reconocen las formas de las guías:
«menor de 6 meses», «6 a 11 meses», «6 meses a 11 años», «5 a 11 años», «6–23 months»,
«60 months and older», «preschool-age», y las poblaciones (niño, adolescente, gestante o
puérpera, mujer en edad fértil). Sin edad ni población, el fragmento aplica a todos
(GENERAL). Las correcciones manuales del YAML reemplazan el rango calculado: un
documento entero puede quedar GENERAL, y cada fragmento revisado se identifica por su id
de la página de revisión (documento y orden), con el comienzo de su texto como
salvaguarda por si la fragmentación cambió.

Un rango sacado del texto que mezcla varios rangos o poblaciones queda marcado como
dudoso para la revisión en la página grupos_etarios.html."""
import re
from dataclasses import dataclass, field, replace
from functools import lru_cache
from pathlib import Path

import yaml

from app.rag.texto import sin_tildes

REGLAS = Path(__file__).with_name("grupos_etarios.yaml")
NINO = "NINO"
ADOLESCENTE = "ADOLESCENTE"
GESTANTE = "GESTANTE"
MUJER_EDAD_FERTIL = "MUJER_EDAD_FERTIL"
GENERAL = "GENERAL"
POBLACIONES = (NINO, ADOLESCENTE, GESTANTE, MUJER_EDAD_FERTIL, GENERAL)
SECCION = "SECCION"
TEXTO = "TEXTO"
MANUAL = "MANUAL"
ORIGENES = ("TITULO", TEXTO, MANUAL)
# Rango de la adolescencia en meses (12 a 17 años), para los títulos que la nombran
# junto a un rango de edad de niños.
RANGO_ADOLESCENTE = (144, 215)
RANGO_ESCOLAR = (60, 155)
RANGO_PREESCOLAR = (24, 59)


@dataclass(frozen=True)
class GrupoEtario:
    edad_min_meses: int | None
    edad_max_meses: int | None
    poblacion: str
    origen: str
    dudoso: bool = False

    def incluye(self, edad_meses: int) -> bool | None:
        """True si el rango incluye la edad, False si la excluye, None si no tiene rango."""
        if self.edad_min_meses is None and self.edad_max_meses is None:
            return None
        minimo = self.edad_min_meses if self.edad_min_meses is not None else 0
        maximo = self.edad_max_meses if self.edad_max_meses is not None else 10_000
        return minimo <= edad_meses <= maximo


def _anios(n: str) -> int:
    return int(n) * 12


_RANGOS = [
    (re.compile(r"\bmenor(?:es)? de (\d+) meses"), lambda m: (0, int(m[1]) - 1)),
    (re.compile(r"\bmenor(?:es)? de (\d+) anos"), lambda m: (0, _anios(m[1]) - 1)),
    (re.compile(r"\b(\d+) meses a (\d+) anos"), lambda m: (int(m[1]), _anios(m[2]) + 11)),
    (re.compile(r"\b(\d+) meses a (\d+) meses"), lambda m: (int(m[1]), int(m[2]))),
    (re.compile(r"\b(\d+) (?:a|-) (\d+) meses"), lambda m: (int(m[1]), int(m[2]))),
    (re.compile(r"\b(\d+) (?:a|-) (\d+) anos"), lambda m: (_anios(m[1]), _anios(m[2]) + 11)),
    (re.compile(r"\b(\d+) ?- ?(\d+) months"), lambda m: (int(m[1]), int(m[2]))),
    (re.compile(r"\b(\d+) months (?:of age )?and older"), lambda m: (int(m[1]), RANGO_ESCOLAR[1])),
    (re.compile(r"\b(\d+) ?- ?(\d+) years"), lambda m: (_anios(m[1]), _anios(m[2]) + 11)),
    (re.compile(r"\b(?:under|less than|younger than) (\d+) years"), lambda m: (0, _anios(m[1]) - 1)),
    (re.compile(r"\bpreschool"), lambda m: RANGO_PREESCOLAR),
    (re.compile(r"\bschool-age"), lambda m: RANGO_ESCOLAR),
]
_POBLACIONES = [
    (GESTANTE, re.compile(r"\bgestante|\bpuerpera|\bembaraz|\bpregnan|\bpostpartum")),
    (MUJER_EDAD_FERTIL, re.compile(r"\bmujer(?:es)? en edad fertil|\bmenstruating women|\bwomen of reproductive age")),
    (ADOLESCENTE, re.compile(r"\badolescente|\badolescent")),
    (NINO, re.compile(r"\bnin[oa]s?\b|\blactante|\brecien nacid|\bprematur|\bbajo peso al nacer|\binfant|\bchild")),
]


def normalizar(texto: str) -> str:
    """Sin mayúsculas ni tildes y con los guiones de rango unificados."""
    return sin_tildes(texto.lower()).replace("–", "-").replace("—", "-")


def _frase(t: str, m: re.Match) -> str:
    """La coincidencia completada hasta el final de la palabra («pregnan» a «pregnant»)."""
    return m[0] + re.match(r"[\w-]*", t[m.end():])[0]


def frases_de_rango(texto: str) -> list[tuple[tuple[int, int], str]]:
    """Cada rango distinto hallado, con la frase (normalizada) que lo originó."""
    t = normalizar(texto)
    encontrados: list[tuple[tuple[int, int], str]] = []
    for patron, rango in _RANGOS:
        for m in patron.finditer(t):
            r = rango(m)
            if r[0] <= r[1] and r not in [e[0] for e in encontrados]:
                encontrados.append((r, _frase(t, m)))
    return encontrados


def frases_de_poblacion(texto: str) -> list[tuple[str, str]]:
    """Cada población hallada, con la primera frase (normalizada) que la nombra."""
    t = normalizar(texto)
    return [(p, _frase(t, m)) for p, patron in _POBLACIONES if (m := patron.search(t))]


def rangos_en(texto: str) -> list[tuple[int, int]]:
    return [r for r, _ in frases_de_rango(texto)]


def poblaciones_en(texto: str) -> list[str]:
    return [p for p, _ in frases_de_poblacion(texto)]


def combinar(rangos: list[tuple[int, int]], poblaciones: list[str], origen: str) -> GrupoEtario:
    """Un grupo a partir de los rangos y poblaciones hallados."""
    no_ninos = [p for p in poblaciones if p != NINO]
    if rangos:
        if ADOLESCENTE in poblaciones:
            rangos = [*rangos, RANGO_ADOLESCENTE]
        minimo, maximo = min(r[0] for r in rangos), max(r[1] for r in rangos)
        poblacion = NINO if minimo < RANGO_ADOLESCENTE[0] else ADOLESCENTE
        dudoso = len(rangos) > 1 or bool(no_ninos)
        return GrupoEtario(minimo, maximo, poblacion, origen, dudoso)
    if not poblaciones:
        return GrupoEtario(None, None, GENERAL, origen)
    if NINO in poblaciones and no_ninos:
        return GrupoEtario(None, None, GENERAL, origen, dudoso=origen == TEXTO)
    if NINO in poblaciones:
        return GrupoEtario(None, None, NINO, origen)
    principal = no_ninos[0] if ADOLESCENTE not in no_ninos else ADOLESCENTE
    rango = RANGO_ADOLESCENTE if principal == ADOLESCENTE else (None, None)
    return GrupoEtario(rango[0], rango[1], principal, origen, dudoso=len(no_ninos) > 1)


def textos_de_seccion(seccion: str | None) -> list[str]:
    """Último nivel de la ruta, títulos contenidos («; ») y título de la tabla («|»)."""
    if not seccion:
        return []
    principal, _, tabla = seccion.partition(" | ")
    partes = principal.split(" > ")[-1].split("; ")
    return [p for p in [*partes, tabla] if p.strip()]


MODOS_DOCUMENTO = (SECCION, TEXTO, GENERAL)
_ID_FRAGMENTO = re.compile(r"^[a-z0-9]+-\d{3}$")


@dataclass(frozen=True)
class Reglas:
    documentos: dict[str, str]
    manuales: list[dict]
    fragmentos: dict[str, dict] = field(default_factory=dict)


def id_fragmento(documento: str, orden: int) -> str:
    """Identificador de la página de revisión: documento y orden con tres cifras."""
    return f"{documento}-{orden:03d}"


def _validar_fragmento(f: dict) -> None:
    if not _ID_FRAGMENTO.match(str(f.get("id", ""))) or not str(f.get("inicio", "")).strip():
        raise ValueError(f"grupos_etarios.yaml: cada fragmento necesita id (documento-000) e inicio: {f}")
    if f.get("confirmado"):
        if any(k in f for k in ("poblacion", "edad_min_meses", "edad_max_meses")):
            raise ValueError(f"grupos_etarios.yaml: un fragmento confirmado no lleva rango ni población: {f}")
    elif f.get("poblacion") not in POBLACIONES:
        raise ValueError(f"grupos_etarios.yaml: población no válida en {f}")


@lru_cache
def cargar_reglas(ruta: Path = REGLAS) -> Reglas:
    datos = yaml.safe_load(ruta.read_text(encoding="utf-8"))
    for documento, modo in datos["documentos"].items():
        if modo not in MODOS_DOCUMENTO:
            raise ValueError(f"grupos_etarios.yaml: modo '{modo}' no válido para {documento}")
    for m in datos.get("manuales") or []:
        if m.get("poblacion") not in POBLACIONES:
            raise ValueError(f"grupos_etarios.yaml: población no válida en {m}")
    fragmentos: dict[str, dict] = {}
    for f in datos.get("fragmentos") or []:
        _validar_fragmento(f)
        if f["id"] in fragmentos:
            raise ValueError(f"grupos_etarios.yaml: fragmento repetido {f['id']}")
        fragmentos[f["id"]] = f
    return Reglas(datos["documentos"], datos.get("manuales") or [], fragmentos)


def _plano(texto: str) -> str:
    return " ".join(normalizar(texto).split())


def coincide_inicio(entrada: dict, texto: str) -> bool:
    """El texto del fragmento empieza como dice la entrada (sin mayúsculas, tildes ni
    diferencias de espacios)."""
    return _plano(texto).startswith(_plano(entrada["inicio"]))


def _por_fragmento(documento: str, orden: int | None, texto: str, reglas: Reglas) -> dict | None:
    if orden is None:
        return None
    entrada = reglas.fragmentos.get(id_fragmento(documento, orden))
    return entrada if entrada and coincide_inicio(entrada, texto) else None


def _manual(documento: str, seccion: str | None, texto: str, reglas: Reglas) -> GrupoEtario | None:
    seccion_n, texto_n = normalizar(seccion or ""), normalizar(texto)
    for m in reglas.manuales:
        if m["documento"] != documento:
            continue
        if ("seccion_contiene" in m and normalizar(m["seccion_contiene"]) in seccion_n) or \
                ("texto_contiene" in m and normalizar(m["texto_contiene"]) in texto_n):
            return GrupoEtario(m.get("edad_min_meses"), m.get("edad_max_meses"), m["poblacion"], MANUAL)
    return None


def fuente_del_rango(documento: str, seccion: str | None, texto: str, reglas: Reglas) -> tuple[str, str]:
    """Origen (TITULO o TEXTO) y texto del que se saca el rango calculado."""
    if reglas.documentos.get(documento, TEXTO) == SECCION:
        return "TITULO", " ".join(textos_de_seccion(seccion))
    return TEXTO, texto


def grupo_calculado(documento: str, seccion: str | None, texto: str, reglas: Reglas) -> GrupoEtario:
    origen, fuente = fuente_del_rango(documento, seccion, texto, reglas)
    return combinar(rangos_en(fuente), poblaciones_en(fuente), origen)


def grupo_de(documento: str, seccion: str | None, texto: str, reglas: Reglas | None = None,
             orden: int | None = None) -> GrupoEtario:
    """En orden de prioridad: documento entero GENERAL, corrección del fragmento (por id
    y comienzo del texto), corrección por sección o texto (manuales) y rango calculado.
    Un fragmento confirmado conserva el rango calculado sin la marca de dudoso."""
    reglas = reglas or cargar_reglas()
    if reglas.documentos.get(documento) == GENERAL:
        return GrupoEtario(None, None, GENERAL, MANUAL)
    if entrada := _por_fragmento(documento, orden, texto, reglas):
        if entrada.get("confirmado"):
            return replace(grupo_calculado(documento, seccion, texto, reglas), origen=MANUAL, dudoso=False)
        return GrupoEtario(entrada.get("edad_min_meses"), entrada.get("edad_max_meses"), entrada["poblacion"], MANUAL)
    if manual := _manual(documento, seccion, texto, reglas):
        return manual
    return grupo_calculado(documento, seccion, texto, reglas)


NOMBRES_POBLACION = {NINO: "niños", ADOLESCENTE: "adolescentes", GESTANTE: "gestantes o puérperas",
                     MUJER_EDAD_FERTIL: "mujeres en edad fértil", GENERAL: "todos (GENERAL)"}


def _meses(edad_min: int | None, edad_max: int | None) -> str:
    if edad_min is None and edad_max is None:
        return "sin límite de edad"
    return f"{edad_min if edad_min is not None else 0} a {edad_max} meses" if edad_max is not None         else f"desde {edad_min} meses"


def motivo_dudoso(documento: str, seccion: str | None, texto: str, reglas: Reglas | None = None,
                  orden: int | None = None) -> str | None:
    """Por qué el rango calculado es dudoso: qué rangos y poblaciones se hallaron (con la
    frase que los originó) y qué grupo se tomó. None si no es dudoso o tiene corrección
    manual."""
    reglas = reglas or cargar_reglas()
    if grupo_de(documento, seccion, texto, reglas, orden).origen == MANUAL:
        return None
    origen, fuente = fuente_del_rango(documento, seccion, texto, reglas)
    rangos, poblaciones = frases_de_rango(fuente), frases_de_poblacion(fuente)
    g = combinar([r for r, _ in rangos], [p for p, _ in poblaciones], origen)
    if not g.dudoso:
        return None
    hallado = []
    if rangos:
        lista = "; ".join(f"{_meses(*r)} («{f}»)" for r, f in rangos)
        hallado.append(f"{len(rangos)} rangos de edad: {lista}" if len(rangos) > 1 else f"el rango {lista}")
    # Con un rango de edad, «niños» no agrega nada: solo se nombran las otras poblaciones.
    nombradas = [(p, f) for p, f in poblaciones if not (rangos and p == NINO)]
    if nombradas:
        hallado.append("las poblaciones " if len(nombradas) > 1 else "la población ")
        hallado[-1] += ", ".join(f"{NOMBRES_POBLACION[p]} («{f}»)" for p, f in nombradas)
    donde = "El título de la sección" if origen == "TITULO" else "El texto"
    return (f"{donde} nombra {' y '.join(hallado)}. Se tomó {_meses(g.edad_min_meses, g.edad_max_meses)}, "
            f"{g.poblacion}.")


def asignar_grupos(fragmentos: list, documento: str, reglas: Reglas | None = None) -> list[str]:
    """Completa en cada fragmento edad_min_meses, edad_max_meses, poblacion,
    origen_rango y rango_dudoso. Devuelve los id de las correcciones por fragmento de
    este documento que no se aplicaron (el orden no existe o el texto ya no empieza
    igual), para avisar en vez de corregir otro fragmento."""
    reglas = reglas or cargar_reglas()
    aplicados = set()
    for f in fragmentos:
        g = grupo_de(documento, f.seccion, f.texto, reglas, f.orden)
        f.edad_min_meses, f.edad_max_meses, f.poblacion = g.edad_min_meses, g.edad_max_meses, g.poblacion
        f.origen_rango, f.rango_dudoso = g.origen, g.dudoso
        if _por_fragmento(documento, f.orden, f.texto, reglas):
            aplicados.add(id_fragmento(documento, f.orden))
    if reglas.documentos.get(documento) == GENERAL:
        return []
    propios = {i for i in reglas.fragmentos if i.rsplit("-", 1)[0] == documento}
    return sorted(propios - aplicados)
