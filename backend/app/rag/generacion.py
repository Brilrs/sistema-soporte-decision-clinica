"""Capa 5 · Generación de la respuesta con el modelo de lenguaje.

Envía la solicitud protegida (proteccion.py) a la Messages API con salida estructurada
según esquema_respuesta.json y el prompt clínico versionado (prompts/, VERSION_PROMPT).
El modelo, el máximo de tokens, el tiempo de espera, el razonamiento, el esfuerzo y
los precios salen de parametro_sistema. No se envía temperatura: claude-sonnet-5-5 la
rechaza y TEMPERATURA_LLM está cerrado.

Resultados posibles de una llamada:
- RESPUESTA: JSON que cumple el esquema; pasa a la verificación.
- INVALIDA: no cumple el esquema o se cortó por max_tokens (no se verifica).
- TIEMPO_AGOTADO, RECHAZO (stop_reason refusal) o ERROR_API: la consulta termina en
  ERROR sin reintento (ver verificacion.decidir).

Por cada llamada quedan los tokens de entrada, de salida y de razonamiento, la latencia,
el modelo efectivo y el costo con PRECIO_ENTRADA_USD_MTOK y PRECIO_SALIDA_USD_MTOK."""
import json
import re
from dataclasses import dataclass
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

from sqlalchemy import Connection
from sqlalchemy.orm import Session

from app.rag.cliente_llm import (FIN_MAX_TOKENS, FIN_RECHAZO, ClienteLLM, ConfiguracionLLM, ErrorAPI,
                                 ErrorTiempoAgotado, RespuestaLLM)
from app.rag.parametros import ErrorParametro, leer_parametros
from app.rag.proteccion import SolicitudProtegida

ESQUEMA = Path(__file__).with_name("esquema_respuesta.json")
PROMPTS = Path(__file__).with_name("prompts")
VERSIONES_PROMPT = {"v1.0": "clinico_v1.md", "v1.1": "clinico_v1_1.md", "v1.2": "clinico_v1_2.md"}
# Versiones que solo se usan en mediciones (medir_consulta --versiones-prompt); no pueden ser VERSION_PROMPT.
VERSIONES_EXPERIMENTALES = frozenset({"v1.2"})
_COMENTARIO_INICIAL = re.compile(r"\A\s*<!--.*?-->\s*", re.S)
RAZONAMIENTOS = frozenset({"between_tools", "adaptive"})
ESFUERZOS = frozenset({"low", "medium", "high"})

RESPUESTA = "RESPUESTA"
INVALIDA = "INVALIDA"
TIEMPO_AGOTADO = "TIEMPO_AGOTADO"
RECHAZO = "RECHAZO"
ERROR_API = "ERROR_API"
_CAMPOS_ENUM = ("clasificacion_confirmada", "nivel_riesgo")


@dataclass(frozen=True)
class ConfiguracionGeneracion:
    llm: ConfiguracionLLM
    version_prompt: str
    precio_entrada_usd_mtok: Decimal
    precio_salida_usd_mtok: Decimal


@dataclass(frozen=True)
class ResultadoGeneracion:
    estado: str
    respuesta: dict | None
    texto: str | None
    motivo: str | None
    modelo: str
    tokens_entrada: int | None
    tokens_salida: int | None
    tokens_razonamiento: int | None
    latencia_ms: int | None
    costo_usd: Decimal | None
    categoria_rechazo: str | None = None
    fin: str | None = None


def configuracion_generacion(sesion: Session | Connection) -> ConfiguracionGeneracion:
    v = leer_parametros(sesion, ["MODELO_LLM", "MAX_TOKENS_SALIDA", "TIMEOUT_LLM_S", "VERSION_PROMPT",
                                 "PRECIO_ENTRADA_USD_MTOK", "PRECIO_SALIDA_USD_MTOK", "RAZONAMIENTO_LLM",
                                 "ESFUERZO_LLM"])
    if v["RAZONAMIENTO_LLM"] not in RAZONAMIENTOS:
        raise ErrorParametro(f"RAZONAMIENTO_LLM: «{v['RAZONAMIENTO_LLM']}» no es {sorted(RAZONAMIENTOS)}")
    if v["ESFUERZO_LLM"] not in ESFUERZOS:
        raise ErrorParametro(f"ESFUERZO_LLM: «{v['ESFUERZO_LLM']}» no es {sorted(ESFUERZOS)}")
    if v["VERSION_PROMPT"] not in VERSIONES_PROMPT:
        raise ErrorParametro(f"VERSION_PROMPT: no hay prompt para «{v['VERSION_PROMPT']}»")
    if v["VERSION_PROMPT"] in VERSIONES_EXPERIMENTALES:
        raise ErrorParametro(f"VERSION_PROMPT: «{v['VERSION_PROMPT']}» es experimental y no puede ser la vigente")
    return ConfiguracionGeneracion(
        llm=ConfiguracionLLM(modelo=v["MODELO_LLM"], max_tokens=v["MAX_TOKENS_SALIDA"], timeout_s=v["TIMEOUT_LLM_S"],
                             razonamiento=v["RAZONAMIENTO_LLM"], esfuerzo=v["ESFUERZO_LLM"]),
        version_prompt=v["VERSION_PROMPT"],
        precio_entrada_usd_mtok=Decimal(str(v["PRECIO_ENTRADA_USD_MTOK"])),
        precio_salida_usd_mtok=Decimal(str(v["PRECIO_SALIDA_USD_MTOK"])),
    )


@lru_cache
def cargar_prompt(version: str) -> str:
    """Texto del prompt, sin el comentario HTML inicial (notas internas que el modelo no recibe)."""
    texto = (PROMPTS / VERSIONES_PROMPT[version]).read_text(encoding="utf-8")
    return _COMENTARIO_INICIAL.sub("", texto, count=1).strip()


@lru_cache
def _esquema_texto() -> str:
    return ESQUEMA.read_text(encoding="utf-8")


def cargar_esquema() -> dict:
    return json.loads(_esquema_texto())


def costo_usd(tokens_entrada: int, tokens_salida: int, config: ConfiguracionGeneracion) -> Decimal:
    total = tokens_entrada * config.precio_entrada_usd_mtok + tokens_salida * config.precio_salida_usd_mtok
    return (total / Decimal(1_000_000)).quantize(Decimal("0.00001"))


_TIPOS = {"object": dict, "array": list, "string": str, "boolean": bool, "integer": int, "number": (int, float),
          "null": type(None)}


def errores_de_esquema(valor, esquema: dict, ruta: str = "$") -> list[str]:
    """Valida con las reglas que usa esquema_respuesta.json: type (también como lista),
    enum, properties, required, additionalProperties false, items, minItems y pattern."""
    tipos = esquema.get("type")
    if tipos is not None:
        tipos = tipos if isinstance(tipos, list) else [tipos]
        es_bool = isinstance(valor, bool)
        if not any(isinstance(valor, _TIPOS[t]) and (t == "boolean" or not es_bool) for t in tipos):
            return [f"{ruta}: se esperaba {'/'.join(tipos)}"]
    errores = []
    if "enum" in esquema and valor not in esquema["enum"]:
        errores.append(f"{ruta}: valor fuera de la lista permitida")
    if isinstance(valor, str) and "pattern" in esquema and not re.search(esquema["pattern"], valor):
        errores.append(f"{ruta}: no cumple el patrón")
    if isinstance(valor, dict):
        propiedades = esquema.get("properties", {})
        errores += [f"{ruta}.{c}: falta" for c in esquema.get("required", []) if c not in valor]
        if esquema.get("additionalProperties") is False:
            errores += [f"{ruta}.{c}: campo no permitido" for c in valor if c not in propiedades]
        for c, sub in propiedades.items():
            if c in valor:
                errores += errores_de_esquema(valor[c], sub, f"{ruta}.{c}")
    if isinstance(valor, list):
        if len(valor) < esquema.get("minItems", 0):
            errores.append(f"{ruta}: tiene menos elementos que el mínimo")
        if "items" in esquema:
            for i, elemento in enumerate(valor):
                errores += errores_de_esquema(elemento, esquema["items"], f"{ruta}[{i}]")
    return errores


def _normalizar_mayusculas(respuesta: dict) -> dict:
    """La salida estructurada no garantiza las mayúsculas de los enum: se comparan sin ellas."""
    for campo in _CAMPOS_ENUM:
        if isinstance(respuesta.get(campo), str):
            respuesta[campo] = respuesta[campo].upper()
    for paso in respuesta.get("recomendacion") or []:
        if isinstance(paso, dict) and isinstance(paso.get("tipo"), str):
            paso["tipo"] = paso["tipo"].upper()
    return respuesta


def interpretar(texto: str) -> tuple[dict | None, str | None]:
    """JSON de la respuesta y, si no cumple el esquema, el motivo."""
    try:
        respuesta = json.loads(texto)
    except json.JSONDecodeError:
        return None, "La respuesta no es un JSON válido"
    if not isinstance(respuesta, dict):
        return None, "La respuesta no es un objeto JSON"
    respuesta = _normalizar_mayusculas(respuesta)
    errores = errores_de_esquema(respuesta, cargar_esquema())
    if errores:
        return None, "No cumple el esquema: " + "; ".join(errores[:5])
    return respuesta, None


def _sin_llamada(estado: str, motivo: str, config: ConfiguracionGeneracion) -> ResultadoGeneracion:
    return ResultadoGeneracion(estado, None, None, motivo, config.llm.modelo, None, None, None, None, None)


def generar(cliente: ClienteLLM, solicitud: SolicitudProtegida, config: ConfiguracionGeneracion) -> ResultadoGeneracion:
    """Una llamada al modelo con la solicitud ya aprobada por el control previo."""
    try:
        r: RespuestaLLM = cliente.generar(cargar_prompt(config.version_prompt), solicitud.serializada,
                                          cargar_esquema(), config.llm)
    except ErrorTiempoAgotado as e:
        return _sin_llamada(TIEMPO_AGOTADO, str(e), config)
    except ErrorAPI as e:
        return _sin_llamada(ERROR_API, str(e), config)

    costo = costo_usd(r.tokens_entrada, r.tokens_salida, config)
    base = dict(texto=r.texto or None, fin=r.fin, modelo=r.modelo, tokens_entrada=r.tokens_entrada, tokens_salida=r.tokens_salida,
                tokens_razonamiento=r.tokens_razonamiento, latencia_ms=r.latencia_ms, costo_usd=costo)
    if r.fin == FIN_RECHAZO:
        return ResultadoGeneracion(RECHAZO, None, motivo="El modelo rechazó la solicitud",
                                   categoria_rechazo=r.categoria_rechazo, **base)
    if r.fin == FIN_MAX_TOKENS:
        return ResultadoGeneracion(INVALIDA, None, motivo="La respuesta se cortó al llegar a MAX_TOKENS_SALIDA", **base)
    respuesta, motivo = interpretar(r.texto)
    if respuesta is None:
        return ResultadoGeneracion(INVALIDA, None, motivo=motivo, **base)
    return ResultadoGeneracion(RESPUESTA, respuesta, motivo=None, **base)
