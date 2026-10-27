"""Mensajes de validación en español.

FastAPI responde los errores de validación (422) con los textos en inglés de
Pydantic. Este manejador los traduce y deja en "detail" un texto legible para la
interfaz, además de la lista por campo en "errores"."""
from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

_MENSAJES = {
    "missing": "es obligatorio",
    "string_too_short": "debe tener al menos {min_length} caracteres",
    "string_too_long": "debe tener como máximo {max_length} caracteres",
    "string_pattern_mismatch": "no tiene el formato esperado",
    "string_type": "debe ser un texto",
    "greater_than": "debe ser mayor que {gt}",
    "greater_than_equal": "debe ser mayor o igual que {ge}",
    "less_than": "debe ser menor que {lt}",
    "less_than_equal": "debe ser menor o igual que {le}",
    "decimal_max_places": "admite como máximo {decimal_places} decimales",
    "decimal_parsing": "debe ser un número",
    "decimal_type": "debe ser un número",
    "int_parsing": "debe ser un número entero",
    "int_type": "debe ser un número entero",
    "bool_parsing": "debe ser sí o no",
    "bool_type": "debe ser sí o no",
    "date_parsing": "debe ser una fecha válida (AAAA-MM-DD)",
    "date_from_datetime_parsing": "debe ser una fecha válida (AAAA-MM-DD)",
    "date_type": "debe ser una fecha válida (AAAA-MM-DD)",
    "literal_error": "debe ser uno de estos valores: {expected}",
    "uuid_parsing": "no es un identificador válido",
    "list_type": "debe ser una lista",
    "model_attributes_type": "tiene un formato no válido",
    "extra_forbidden": "no es un campo permitido",
    "json_invalid": "el cuerpo de la solicitud no es un JSON válido",
}


def _campo(loc: tuple) -> str:
    partes = [str(p) for p in loc if p not in ("body", "query", "path")]
    return ".".join(partes) or "solicitud"


def _mensaje(error: dict) -> str:
    tipo = error.get("type", "")
    if tipo == "value_error":
        # Validaciones propias: el texto ya está en español, sin el prefijo de Pydantic
        return str(error.get("ctx", {}).get("error", error.get("msg", "")))
    plantilla = _MENSAJES.get(tipo)
    if plantilla is None:
        return "no es válido"
    ctx = dict(error.get("ctx", {}))
    if "expected" in ctx:
        ctx["expected"] = str(ctx["expected"]).replace(" or ", " o ")
    try:
        return plantilla.format(**ctx)
    except (KeyError, IndexError):
        return plantilla


async def manejar_error_validacion(_: Request, exc: RequestValidationError) -> JSONResponse:
    errores = [{"campo": _campo(tuple(e.get("loc", ()))), "mensaje": _mensaje(e)} for e in exc.errors()]
    resumen = "; ".join(f"{e['campo']}: {e['mensaje']}" for e in errores)
    return JSONResponse(status_code=422, content={"detail": f"Revise los datos ingresados. {resumen}",
                                                  "errores": errores})
