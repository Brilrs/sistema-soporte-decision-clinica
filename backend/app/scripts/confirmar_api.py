"""Confirmación mínima de la API de Anthropic antes de construir la generación (C, paso 0).

Hace tres solicitudes con un caso 100 % sintético, sin datos de pacientes:
  1. Consulta los datos del modelo en la Models API (no envía contenido).
  2. Una llamada mínima a la Messages API con salida estructurada (output_config.format),
     la configuración de razonamiento y el esfuerzo previstos, y registra el uso de tokens,
     la latencia, el modelo efectivo y el costo con los precios de parametro_sistema.
  3. Una solicitud con temperature, que la API debe rechazar con un error 400 antes de
     generar (no produce salida ni se factura).

Uso (dentro del contenedor o con el entorno virtual, con ANTHROPIC_API_KEY definida):
    python -m app.scripts.confirmar_api --confirmo-datos-sinteticos [--salida RUTA.json]

Nunca imprime ni guarda la clave. Con CDSS_ENTORNO=pruebas no se ejecuta."""
import argparse
import json
import os
import sys
import time
from decimal import Decimal
from pathlib import Path

MODELO = "claude-sonnet-5-5"
PRECIO_ENTRADA_USD_MTOK = Decimal("2.00")
PRECIO_SALIDA_USD_MTOK = Decimal("10.00")
MAX_TOKENS = 400
ESFUERZO = "medium"
RAZONAMIENTO = {"type": "between_tools"}

SISTEMA = ("Eres un asistente de prueba. Responde solo con la información del fragmento entregado y "
           "cita su etiqueta. Responde en español.")
# Caso inventado para la prueba: no corresponde a ningún paciente.
CASO_SINTETICO = {
    "aviso": "Caso sintético de prueba, sin datos de pacientes reales",
    "paciente": {"edad_meses": 14, "sexo": "M", "hb_ajustada_g_dl": 9.8, "clasificacion": "anemia leve"},
    "consulta": "¿Qué indica el fragmento sobre el control de hemoglobina?",
    "evidencia": [{"etiqueta": "F-01", "fuente": "Documento sintético de prueba",
                   "texto": "El control de hemoglobina se realiza al mes, a los 3 meses y a los 6 meses "
                            "de iniciado el tratamiento."}],
}
ESQUEMA = {
    "type": "object",
    "properties": {
        "respuesta": {"type": "string"},
        "citas": {"type": "array", "items": {"type": "string", "enum": ["F-01"]}},
        "evidencia_suficiente": {"type": "boolean"},
    },
    "required": ["respuesta", "citas", "evidencia_suficiente"],
    "additionalProperties": False,
}


def _costo(entrada: int, salida: int) -> Decimal:
    return ((entrada * PRECIO_ENTRADA_USD_MTOK + salida * PRECIO_SALIDA_USD_MTOK) / Decimal(1_000_000)
            ).quantize(Decimal("0.00001"))


def _modelo(cliente) -> dict:
    datos = cliente.models.retrieve(MODELO)
    return json.loads(datos.model_dump_json())


def _llamada(cliente) -> dict:
    inicio = time.perf_counter()
    r = cliente.messages.create(
        model=MODELO, max_tokens=MAX_TOKENS, system=SISTEMA, thinking=RAZONAMIENTO,
        messages=[{"role": "user", "content": json.dumps(CASO_SINTETICO, ensure_ascii=False)}],
        output_config={"effort": ESFUERZO, "format": {"type": "json_schema", "schema": ESQUEMA}},
    )
    latencia_ms = round((time.perf_counter() - inicio) * 1000)
    texto = "".join(b.text for b in r.content if b.type == "text")
    uso = json.loads(r.usage.model_dump_json())
    return {
        "id_solicitud": r._request_id, "modelo_efectivo": r.model, "stop_reason": r.stop_reason,
        "stop_details": None if r.stop_details is None else json.loads(r.stop_details.model_dump_json()),
        "tipos_de_bloque": [b.type for b in r.content], "respuesta": json.loads(texto) if texto else None,
        "uso": uso, "latencia_ms": latencia_ms,
        "costo_usd": str(_costo(r.usage.input_tokens, r.usage.output_tokens)),
    }


def _temperatura(cliente, anthropic) -> dict:
    try:
        cliente.messages.create(model=MODELO, max_tokens=16, extra_body={"temperature": 0},
                                messages=[{"role": "user", "content": "Prueba sintética."}])
    except anthropic.BadRequestError as e:
        return {"rechazada": True, "estado_http": e.status_code, "mensaje": e.message}
    return {"rechazada": False}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--confirmo-datos-sinteticos", action="store_true",
                   help="Confirma que la solicitud solo lleva el caso sintético de este script")
    p.add_argument("--salida", type=Path, help="Archivo JSON donde guardar el resultado")
    a = p.parse_args(argv)
    if not a.confirmo_datos_sinteticos:
        p.error("Falta --confirmo-datos-sinteticos")
    if os.environ.get("CDSS_ENTORNO") == "pruebas":
        p.error("No se llama a la API real con CDSS_ENTORNO=pruebas")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        p.error("Falta ANTHROPIC_API_KEY en el entorno")
    import anthropic

    cliente = anthropic.Anthropic(max_retries=0, timeout=60.0)
    resultado = {
        "sdk": anthropic.__version__,
        "version_api": cliente.default_headers.get("anthropic-version"),
        "configuracion": {"modelo": MODELO, "max_tokens": MAX_TOKENS, "esfuerzo": ESFUERZO,
                          "razonamiento": RAZONAMIENTO},
        "modelo": _modelo(cliente),
        "llamada": _llamada(cliente),
        "temperatura": _temperatura(cliente, anthropic),
    }
    texto = json.dumps(resultado, ensure_ascii=False, indent=2)
    if a.salida:
        a.salida.parent.mkdir(parents=True, exist_ok=True)
        a.salida.write_text(texto + "\n", encoding="utf-8")
    print(texto)
    return 0


if __name__ == "__main__":
    sys.exit(main())
