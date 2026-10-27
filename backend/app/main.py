"""Punto de entrada del backend del CDSS (FastAPI)."""
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import auth, catalogos, pacientes, salud
from app.core.config import get_settings
from app.core.errores import manejar_error_validacion

app = FastAPI(
    title="CDSS Anemia Infantil · API",
    version="0.1.0",
    description="Sistema de soporte a la decisión clínica para la evaluación del riesgo de anemia infantil (CRED).",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origenes,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)

app.add_exception_handler(RequestValidationError, manejar_error_validacion)

app.include_router(salud.router)
app.include_router(auth.router)
app.include_router(catalogos.router)
app.include_router(pacientes.router)
