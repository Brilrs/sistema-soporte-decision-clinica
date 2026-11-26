"""Juez LLM de la evaluación: cliente intercambiable, caché en disco y registro de tokens y costo.

- JuezFalso: determinista y sin red. Es el único que se usa en el desarrollo, en las pruebas y en
  el ensayo del piloto (opción A: el piloto nunca se corre con el modelo real).
- JuezAnthropic: Messages API con salida estructurada. Preparado, no usado: no se puede crear con
  CDSS_ENTORNO=pruebas, exige ANTHROPIC_API_KEY y que quien lo ejecuta confirme que los datos son
  sintéticos. Sin temperatura (Claude Sonnet 5.5 solo admite el valor predeterminado, fila 6),
  max_retries=0; el razonamiento y el esfuerzo son configurables.
- Juez: arma la clave de caché con SHA-256 de (modelo, tarea, sistema, esquema, entrada,
  repetición), reutiliza la respuesta guardada, registra cada llamada en JSONL y solo acepta
  llamadas de casos del conjunto cargado.
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Protocol

from app.evaluacion import prompts_juez as pj
from app.evaluacion.cue import normalizar

MODELO_FALSO = "juez-falso"
# Precios en dólares por millón de tokens (entrada, salida). Verificar contra la página oficial de
# precios antes de la corrida definitiva; el informe guarda la tabla usada.
PRECIOS_USD_MTOK = {
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-opus-5-5": (4.00, 20.00),
    MODELO_FALSO: (0.0, 0.0),
}


class ErrorJuez(Exception):
    """El juez no se puede crear o no se puede usar con estos datos."""


@dataclass(frozen=True)
class ConfiguracionJuez:
    modelo: str = MODELO_FALSO
    razonamiento: str | None = None     # valor de thinking.type; None no lo envía
    esfuerzo: str | None = None         # output_config.effort; None no lo envía
    max_tokens: int = 4000
    timeout_s: float = 120.0
    k: int = 3

    def __post_init__(self):
        if self.k < 1:
            raise ErrorJuez("k debe ser 1 o más")


@dataclass(frozen=True)
class RespuestaJuez:
    texto: str
    modelo: str
    tokens_entrada: int
    tokens_salida: int
    latencia_ms: int


class ClienteJuez(Protocol):
    modelo: str

    def generar(self, tarea: str, sistema: str, contenido: str, esquema: dict,
                config: ConfiguracionJuez) -> RespuestaJuez: ...


def costo_usd(modelo: str, entrada: int, salida: int) -> float | None:
    """Costo en dólares; None si el modelo no está en la tabla. El juez falso no cuesta, aunque
    lleve el nombre del modelo que simula (juez-falso:claude-...)."""
    if modelo == MODELO_FALSO or modelo.startswith(f"{MODELO_FALSO}:"):
        return 0.0
    precio = PRECIOS_USD_MTOK.get(modelo)
    if precio is None:
        return None
    return round(entrada * precio[0] / 1e6 + salida * precio[1] / 1e6, 6)


# ---------------------------------------------------------------------------
# Cliente falso
# ---------------------------------------------------------------------------
_PALABRA = re.compile(r"[a-z0-9áéíóúñü]{4,}")
_ORACION = re.compile(r"[^.;\n]+")


def _palabras(texto: str) -> set[str]:
    return set(_PALABRA.findall(normalizar(texto)))


def _oraciones(texto: str) -> list[str]:
    return [o.strip() for o in _ORACION.findall(texto) if len(o.strip()) >= 12]


def _solapamiento(a: str, b: str) -> float:
    pa = _palabras(a)
    return len(pa & _palabras(b)) / len(pa) if pa else 0.0


@dataclass
class JuezFalso:
    """Respuestas deterministas a partir de la entrada: solapamiento de palabras para los juicios
    propios y valores derivados del SHA-256 del prompt para los de RAGAS. Los números no tienen
    valor como medición: sirven para probar el job de punta a punta sin red."""
    modelo: str = MODELO_FALSO
    llamadas: list[dict] = field(default_factory=list)
    # Para las pruebas: respuestas inválidas en las primeras n llamadas
    invalidas: int = 0

    def generar(self, tarea, sistema, contenido, esquema, config) -> RespuestaJuez:
        self.llamadas.append({"tarea": tarea, "contenido": contenido})
        if len(self.llamadas) <= self.invalidas:
            texto = "{respuesta cortada"
        elif tarea == pj.AFIRMACIONES:
            texto = json.dumps(self._afirmaciones(json.loads(contenido)), ensure_ascii=False)
        elif tarea == pj.ADHERENCIA:
            texto = json.dumps(self._adherencia(json.loads(contenido)), ensure_ascii=False)
        else:
            semilla = int(hashlib.sha256(contenido.encode("utf-8")).hexdigest()[:12], 16)
            texto = json.dumps(_llenar(esquema, esquema, random.Random(semilla)), ensure_ascii=False)
        return RespuestaJuez(texto, self.modelo, max(1, (len(sistema) + len(contenido)) // 4),
                             max(1, len(texto) // 4), 1)

    @staticmethod
    def _soporte(oracion: str, fragmentos: list[dict]) -> list[str]:
        return [f["etiqueta"] for f in fragmentos if _solapamiento(oracion, f["texto"]) >= 0.5]

    def _afirmaciones(self, datos: dict) -> dict:
        claves = datos.get("afirmaciones_clave", [])
        afirmaciones = []
        for o in _oraciones(datos["respuesta"]):
            mejor = max(claves, key=lambda c: _solapamiento(c["texto"], o), default=None)
            clave = mejor["indice"] if mejor and _solapamiento(mejor["texto"], o) >= 0.5 else None
            afirmaciones.append({"texto": o, "clave": clave, "fragmentos": self._soporte(o, datos["fragmentos"])})
        usadas = {a["clave"] for a in afirmaciones}
        return {"afirmaciones": afirmaciones,
                "claves": [{"indice": c["indice"], "presente": c["indice"] in usadas, "contradicha": False}
                           for c in claves]}

    def _adherencia(self, datos: dict) -> dict:
        oraciones = _oraciones(datos["respuesta"])
        sin = [o for o in oraciones if not self._soporte(o, datos["fragmentos"])]
        puntaje = 0.0 if not oraciones else round(1 - len(sin) / len(oraciones), 2)
        return {"puntaje": puntaje, "indicaciones_sin_respaldo": sin,
                "justificacion": "Juicio simulado por solapamiento de palabras (juez falso)."}


def _llenar(s: dict, raiz: dict, azar: random.Random):
    """Instancia mínima y válida de un esquema JSON (con $ref a $defs), para el juez falso."""
    if "$ref" in s:
        nombre = s["$ref"].split("/")[-1]
        return _llenar(raiz.get("$defs", {}).get(nombre, {}), raiz, azar)
    if "anyOf" in s:
        return _llenar(s["anyOf"][0], raiz, azar)
    t = s.get("type")
    if isinstance(t, list):
        t = next((x for x in t if x != "null"), "null")
    if t == "object":
        return {k: _llenar(v, raiz, azar) for k, v in s.get("properties", {}).items()}
    if t == "array":
        return [_llenar(s.get("items", {}), raiz, azar) for _ in range(2)]
    if t == "integer":
        return azar.randint(0, 1)
    if t == "number":
        return round(azar.random(), 2)
    if t == "boolean":
        return azar.random() < 0.5
    if t == "string":
        return "texto simulado"
    return None


# ---------------------------------------------------------------------------
# Cliente de Anthropic (preparado; no se usa con el piloto)
# ---------------------------------------------------------------------------
class JuezAnthropic:
    def __init__(self, modelo: str, confirmo_datos_sinteticos: bool, api_key: str | None = None):
        if os.environ.get("CDSS_ENTORNO", "desarrollo") == "pruebas":
            raise ErrorJuez("El juez real no se puede crear con CDSS_ENTORNO=pruebas")
        if not confirmo_datos_sinteticos:
            raise ErrorJuez("El juez real exige confirmar que los datos son sintéticos")
        clave = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not clave:
            raise ErrorJuez("Falta ANTHROPIC_API_KEY")
        import anthropic
        self.modelo = modelo
        self._cliente = anthropic.Anthropic(api_key=clave, max_retries=0)

    def __repr__(self) -> str:
        return f"JuezAnthropic({self.modelo!r})"

    def generar(self, tarea, sistema, contenido, esquema, config) -> RespuestaJuez:
        inicio = time.perf_counter()
        salida = {"format": {"type": "json_schema", "schema": esquema}}
        if config.esfuerzo:
            salida["effort"] = config.esfuerzo
        extra = {"thinking": {"type": config.razonamiento}} if config.razonamiento else {}
        r = self._cliente.messages.create(
            model=self.modelo, max_tokens=config.max_tokens, system=sistema, timeout=config.timeout_s,
            messages=[{"role": "user", "content": contenido}], output_config=salida, **extra)
        texto = "".join(b.text for b in r.content if b.type == "text")
        return RespuestaJuez(texto, r.model, r.usage.input_tokens, r.usage.output_tokens,
                             round((time.perf_counter() - inicio) * 1000))


def crear_cliente(tipo: str, modelo: str, confirmo_datos_sinteticos: bool = False) -> ClienteJuez:
    if tipo == "falso":
        return JuezFalso(modelo=MODELO_FALSO if modelo in (None, "", MODELO_FALSO) else f"{MODELO_FALSO}:{modelo}")
    if tipo == "anthropic":
        return JuezAnthropic(modelo, confirmo_datos_sinteticos)
    raise ErrorJuez(f"Tipo de juez desconocido: {tipo}")


# ---------------------------------------------------------------------------
# Juez con caché y registro
# ---------------------------------------------------------------------------
@dataclass
class Llamada:
    id_caso: str
    tarea: str
    repeticion: int
    modelo: str
    clave: str
    cache: bool
    ok: bool
    tokens_entrada: int = 0
    tokens_salida: int = 0
    costo_usd: float | None = 0.0
    latencia_ms: int = 0
    intentos: int = 1
    error: str | None = None


class Juez:
    def __init__(self, cliente: ClienteJuez, config: ConfiguracionJuez, dir_cache: Path,
                 registro: Path | None = None, casos_permitidos: set[str] | None = None):
        self.cliente, self.config = cliente, config
        self.dir_cache, self.registro = Path(dir_cache), registro
        self.casos_permitidos = casos_permitidos
        self.llamadas: list[Llamada] = []

    @property
    def modelo(self) -> str:
        return self.cliente.modelo

    def clave(self, tarea: str, sistema: str, contenido: str, esquema: dict, repeticion: int) -> str:
        datos = json.dumps({"modelo": self.modelo, "tarea": tarea, "sistema": sistema, "contenido": contenido,
                            "esquema": esquema, "repeticion": repeticion,
                            "razonamiento": self.config.razonamiento, "esfuerzo": self.config.esfuerzo},
                           ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(datos.encode("utf-8")).hexdigest()

    def _ruta(self, clave: str) -> Path:
        return self.dir_cache / clave[:2] / f"{clave}.json"

    def llamar(self, id_caso: str, tarea: str, sistema: str, contenido: str, esquema: dict,
               repeticion: int) -> dict | None:
        """Devuelve el JSON del juez, o None si dos respuestas seguidas no son JSON válido."""
        if self.casos_permitidos is not None and id_caso not in self.casos_permitidos:
            raise ErrorJuez(f"El juez solo acepta casos del conjunto cargado ({id_caso!r} no lo es)")
        clave = self.clave(tarea, sistema, contenido, esquema, repeticion)
        ruta = self._ruta(clave)
        if ruta.exists():
            guardado = json.loads(ruta.read_text(encoding="utf-8"))
            self._anotar(Llamada(id_caso, tarea, repeticion, self.modelo, clave, True, True,
                                 guardado["tokens_entrada"], guardado["tokens_salida"], 0.0, 0))
            return guardado["datos"]
        entrada = salida = latencia = 0
        error = None
        for intento in (1, 2):
            try:
                r = self.cliente.generar(tarea, sistema, contenido, esquema, self.config)
            except Exception as e:  # noqa: BLE001 (se registra y la métrica queda sin valor)
                error = f"{type(e).__name__}: {e}"[:300]
                break
            entrada += r.tokens_entrada
            salida += r.tokens_salida
            latencia += r.latencia_ms
            try:
                datos = json.loads(r.texto)
                if not isinstance(datos, dict):
                    raise ValueError("no es un objeto")
            except ValueError as e:
                error = f"JSON inválido: {e}"[:300]
                continue
            ruta.parent.mkdir(parents=True, exist_ok=True)
            ruta.write_text(json.dumps({"datos": datos, "tokens_entrada": r.tokens_entrada,
                                        "tokens_salida": r.tokens_salida, "modelo": r.modelo},
                                       ensure_ascii=False), encoding="utf-8")
            self._anotar(Llamada(id_caso, tarea, repeticion, self.modelo, clave, False, True, entrada, salida,
                                 costo_usd(self.modelo, entrada, salida), latencia, intento))
            return datos
        self._anotar(Llamada(id_caso, tarea, repeticion, self.modelo, clave, False, False, entrada, salida,
                             costo_usd(self.modelo, entrada, salida), latencia, 2, error))
        return None

    def _anotar(self, llamada: Llamada) -> None:
        self.llamadas.append(llamada)
        if self.registro is not None:
            self.registro.parent.mkdir(parents=True, exist_ok=True)
            with self.registro.open("a", encoding="utf-8") as f:
                f.write(json.dumps(asdict(llamada), ensure_ascii=False) + "\n")

    def resumen(self) -> dict:
        nuevas = [l for l in self.llamadas if not l.cache]
        costos = [l.costo_usd for l in nuevas if l.costo_usd is not None]
        return {"modelo": self.modelo, "llamadas": len(self.llamadas), "desde_cache": len(self.llamadas) - len(nuevas),
                "fallidas": sum(not l.ok for l in self.llamadas),
                "tokens_entrada": sum(l.tokens_entrada for l in nuevas),
                "tokens_salida": sum(l.tokens_salida for l in nuevas),
                "costo_usd": round(sum(costos), 6) if len(costos) == len(nuevas) else None}
