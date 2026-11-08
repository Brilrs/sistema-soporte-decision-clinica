"""Clientes del modelo de lenguaje: real (API de Anthropic) y falso (respuestas programadas).

El cliente real es el único punto del sistema que envía datos a un servicio externo.
No se puede crear con CDSS_ENTORNO=pruebas, y se configura con max_retries=0: el SDK
no reintenta por su cuenta y los reintentos los decide la verificación (Tabla 10),
dentro del presupuesto de tiempo del RNF3. Nunca registra la clave.

El cliente falso arma la respuesta a partir de la solicitud recibida, según el modo
programado para cada intento: aprobada, cita inventada, clasificación contradictoria,
evidencia insuficiente, esquema inválido, respuesta cortada por max_tokens, tiempo
agotado, rechazo, error de la API, traducción con cifras distintas o dosis inventada."""
import json
import os
import re
import time
from dataclasses import dataclass, field
from typing import Protocol

ENTORNO_PRUEBAS = "pruebas"
FIN_NORMAL = "end_turn"
FIN_RECHAZO = "refusal"
FIN_MAX_TOKENS = "max_tokens"


class ErrorClienteLLM(Exception):
    """Error al llamar al modelo de lenguaje."""


class ErrorTiempoAgotado(ErrorClienteLLM):
    """La API no respondió dentro de TIMEOUT_LLM_S."""


class ErrorAPI(ErrorClienteLLM):
    """La API devolvió un error (autenticación, límite de uso, servidor o conexión)."""


class ErrorEntornoPruebas(RuntimeError):
    """Se intentó crear el cliente real con CDSS_ENTORNO=pruebas."""


@dataclass(frozen=True)
class ConfiguracionLLM:
    modelo: str
    max_tokens: int
    timeout_s: float
    razonamiento: str
    esfuerzo: str


@dataclass(frozen=True)
class RespuestaLLM:
    texto: str
    fin: str
    modelo: str
    tokens_entrada: int
    tokens_salida: int
    tokens_razonamiento: int | None
    latencia_ms: int
    categoria_rechazo: str | None = None
    id_solicitud: str | None = None


class ClienteLLM(Protocol):
    def generar(self, sistema: str, contenido: str, esquema: dict, config: ConfiguracionLLM) -> RespuestaLLM: ...


def entorno_actual() -> str:
    return os.environ.get("CDSS_ENTORNO", "desarrollo")


class ClienteAnthropic:
    """Messages API con salida estructurada (output_config.format)."""

    def __init__(self, api_key: str | None = None):
        if entorno_actual() == ENTORNO_PRUEBAS:
            raise ErrorEntornoPruebas("El cliente real del modelo de lenguaje no se puede crear en pruebas")
        clave = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not clave:
            raise ErrorAPI("Falta ANTHROPIC_API_KEY")
        import anthropic

        self._anthropic = anthropic
        self._cliente = anthropic.Anthropic(api_key=clave, max_retries=0)

    def __repr__(self) -> str:
        return "ClienteAnthropic()"

    def generar(self, sistema: str, contenido: str, esquema: dict, config: ConfiguracionLLM) -> RespuestaLLM:
        a = self._anthropic
        inicio = time.perf_counter()
        try:
            r = self._cliente.messages.create(
                model=config.modelo, max_tokens=config.max_tokens, system=sistema,
                thinking={"type": config.razonamiento}, timeout=config.timeout_s,
                messages=[{"role": "user", "content": contenido}],
                output_config={"effort": config.esfuerzo, "format": {"type": "json_schema", "schema": esquema}},
            )
        except a.APITimeoutError as e:
            raise ErrorTiempoAgotado(f"Sin respuesta en {config.timeout_s:g} s") from e
        except a.APIStatusError as e:
            raise ErrorAPI(f"La API respondió {e.status_code} ({type(e).__name__})") from e
        except a.APIConnectionError as e:
            raise ErrorAPI("No se pudo conectar con la API") from e
        return respuesta_desde_mensaje(r, round((time.perf_counter() - inicio) * 1000))


def respuesta_desde_mensaje(r, latencia_ms: int) -> RespuestaLLM:
    """Convierte el Message del SDK. Los tokens de razonamiento vienen en
    usage.output_tokens_details.thinking_tokens (ya incluidos en output_tokens); si la API
    no envía el detalle quedan en None, no en 0. Con RAZONAMIENTO_LLM = between_tools y sin
    herramientas el modelo no razona y la API informa 0."""
    detalles = getattr(r.usage, "output_tokens_details", None)
    return RespuestaLLM(
        texto="".join(b.text for b in r.content if b.type == "text"), fin=r.stop_reason, modelo=r.model,
        tokens_entrada=r.usage.input_tokens, tokens_salida=r.usage.output_tokens,
        tokens_razonamiento=None if detalles is None else detalles.thinking_tokens, latencia_ms=latencia_ms,
        categoria_rechazo=r.stop_details.category if r.stop_reason == FIN_RECHAZO and r.stop_details else None,
        id_solicitud=getattr(r, "_request_id", None),
    )


# ---------------------------------------------------------------------------
# Cliente falso
# ---------------------------------------------------------------------------
APROBADA = "aprobada"
CITA_INVENTADA = "cita_inventada"
EXTRACTO_INVENTADO = "extracto_inventado"
CLASIFICACION_CONTRADICTORIA = "clasificacion_contradictoria"
EVIDENCIA_INSUFICIENTE = "evidencia_insuficiente"
ESQUEMA_INVALIDO = "esquema_invalido"
CORTADA_MAX_TOKENS = "cortada_max_tokens"
TIEMPO_AGOTADO = "tiempo_agotado"
RECHAZO = "rechazo"
ERROR_API = "error_api"
TRADUCCION_CIFRAS_DISTINTAS = "traduccion_cifras_distintas"
DOSIS_INVENTADA = "dosis_inventada"
MODOS = (APROBADA, CITA_INVENTADA, EXTRACTO_INVENTADO, CLASIFICACION_CONTRADICTORIA, EVIDENCIA_INSUFICIENTE,
         ESQUEMA_INVALIDO, CORTADA_MAX_TOKENS, TIEMPO_AGOTADO, RECHAZO, ERROR_API, TRADUCCION_CIFRAS_DISTINTAS,
         DOSIS_INVENTADA)
_FRASE = re.compile(r"[^.;:\n]{20,200}")
_OTRA = {"SIN_ANEMIA": "ANEMIA_MODERADA", "ANEMIA_LEVE": "SIN_ANEMIA", "ANEMIA_MODERADA": "ANEMIA_LEVE",
         "ANEMIA_SEVERA": "ANEMIA_LEVE", "SIN_CLASIFICACION": "ANEMIA_LEVE"}
_RIESGO = {"SIN_ANEMIA": "BAJO", "ANEMIA_LEVE": "MODERADO", "ANEMIA_MODERADA": "ALTO", "ANEMIA_SEVERA": "MUY_ALTO"}


def _extracto(texto: str) -> str:
    m = _FRASE.search(texto)
    return (m.group() if m else texto[:120]).strip()


def _tipo_paso(clasificacion: str) -> str:
    return "PREVENCION" if clasificacion in ("SIN_ANEMIA", "SIN_CLASIFICACION") else "TRATAMIENTO"


@dataclass
class ClienteFalso:
    """Devuelve, en cada llamada, la respuesta del modo siguiente de la lista (el último
    se repite). Prefiere citar un fragmento en inglés si `preferir_ingles`. Guarda las
    solicitudes recibidas para las pruebas."""
    modos: list[str] = field(default_factory=lambda: [APROBADA])
    preferir_ingles: bool = False
    modelo: str = "modelo-falso"
    llamadas: list[dict] = field(default_factory=list)

    def __post_init__(self):
        desconocidos = set(self.modos) - set(MODOS)
        if desconocidos:
            raise ValueError(f"Modos desconocidos: {sorted(desconocidos)}")

    def generar(self, sistema: str, contenido: str, esquema: dict, config: ConfiguracionLLM) -> RespuestaLLM:
        modo = self.modos[min(len(self.llamadas), len(self.modos) - 1)]
        solicitud = json.loads(contenido)
        self.llamadas.append({"modo": modo, "sistema": sistema, "solicitud": solicitud, "config": config})
        if modo == TIEMPO_AGOTADO:
            raise ErrorTiempoAgotado(f"Sin respuesta en {config.timeout_s:g} s")
        if modo == ERROR_API:
            raise ErrorAPI("La API respondió 529 (OverloadedError)")
        if modo == RECHAZO:
            return self._respuesta("", FIN_RECHAZO, categoria_rechazo="general_harms")
        cuerpo = self._cuerpo(modo, solicitud)
        texto = json.dumps(cuerpo, ensure_ascii=False)
        if modo == ESQUEMA_INVALIDO:
            return self._respuesta(json.dumps({"resumen": cuerpo["resumen"]}, ensure_ascii=False), FIN_NORMAL)
        if modo == CORTADA_MAX_TOKENS:
            return self._respuesta(texto[: len(texto) // 2], FIN_MAX_TOKENS, tokens_razonamiento=config.max_tokens // 2)
        return self._respuesta(texto, FIN_NORMAL)

    def _respuesta(self, texto: str, fin: str, categoria_rechazo: str | None = None,
                   tokens_razonamiento: int = 0) -> RespuestaLLM:
        return RespuestaLLM(texto=texto, fin=fin, modelo=self.modelo, tokens_entrada=1200,
                            tokens_salida=max(1, len(texto) // 4) + tokens_razonamiento,
                            tokens_razonamiento=tokens_razonamiento, latencia_ms=5,
                            categoria_rechazo=categoria_rechazo)

    def _cuerpo(self, modo: str, solicitud: dict) -> dict:
        paciente = solicitud["paciente"]
        clasificacion = paciente.get("clasificacion") or "SIN_CLASIFICACION"
        riesgo = paciente.get("nivel_riesgo") or "SIN_CLASIFICACION"
        evidencia = solicitud["evidencia"]
        if modo == EVIDENCIA_INSUFICIENTE or not evidencia:
            return {"clasificacion_confirmada": clasificacion, "nivel_riesgo": riesgo, "evidencia_suficiente": False,
                    "resumen": "Evidencia insuficiente: aplicar criterio clínico.", "recomendacion": [], "citas": [],
                    "factores_identificados": [], "advertencias": []}
        idioma = solicitud["idioma_respuesta"]
        fragmento = next((e for e in evidencia if e["idioma"] != idioma), evidencia[0]) if self.preferir_ingles \
            else evidencia[0]
        extracto = _extracto(fragmento["texto"])
        traducido = None
        if fragmento["idioma"] != idioma:
            traducido = f"Traducción de apoyo simulada: {extracto}"
            if modo == TRADUCCION_CIFRAS_DISTINTAS:
                traducido += " Administrar 99 mg al día."
        etiqueta = fragmento["etiqueta"]
        paso = "Seguir la indicación del fragmento citado."
        if modo == DOSIS_INVENTADA:
            paso = "Administrar sulfato ferroso 7 mg/kg/día durante 9 meses."
        if modo == CITA_INVENTADA:
            etiqueta = "F-09"
        if modo == EXTRACTO_INVENTADO:
            extracto = "Texto que no aparece en ningún fragmento enviado."
        if modo == CLASIFICACION_CONTRADICTORIA:
            clasificacion = _OTRA[clasificacion]
            riesgo = _RIESGO.get(clasificacion, riesgo)
        pasos = [{"texto": paso, "tipo": _tipo_paso(clasificacion), "citas": [etiqueta]}]
        if paciente.get("requiere_derivacion"):
            pasos.append({"texto": "Referir a un establecimiento de mayor capacidad resolutiva.",
                          "tipo": "DERIVACION", "citas": [etiqueta]})
        return {"clasificacion_confirmada": clasificacion, "nivel_riesgo": riesgo, "evidencia_suficiente": True,
                "resumen": "Respuesta simulada a partir del fragmento citado.", "recomendacion": pasos,
                "citas": [{"etiqueta": etiqueta, "extracto": extracto, "extracto_traducido": traducido}],
                "factores_identificados": [], "advertencias": []}
