"""Configuración del backend, leída de variables de entorno (.env en desarrollo,
Azure Key Vault en producción)."""
from functools import lru_cache

from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    entorno: str = Field("desarrollo", alias="CDSS_ENTORNO")

    # Una conexión por componente, cada una con su usuario de base de datos
    # (mínimo privilegio, ver db/sql/usuarios_bd.sql).
    database_url_clinica: str = Field(..., alias="DATABASE_URL_CLINICA")
    database_url_generacion: str = Field(..., alias="DATABASE_URL_GENERACION")
    database_url_admin: str = Field(..., alias="DATABASE_URL_ADMIN")

    # Autenticación
    jwt_secreto: str = Field(..., alias="JWT_SECRETO", min_length=32)
    jwt_minutos: int = Field(480, alias="JWT_MINUTOS")
    max_intentos_fallidos: int = Field(5, alias="MAX_INTENTOS_FALLIDOS")
    # Política de contraseñas de las cuentas (HU11): longitud mínima, con al menos una letra y un número
    contrasena_longitud_minima: int = Field(10, alias="CONTRASENA_LONGITUD_MINIMA", ge=8, le=64)

    # Protección de la identidad del paciente
    clave_pii: str = Field(..., alias="CDSS_CLAVE_PII", min_length=32)
    clave_hmac: str = Field(..., alias="CDSS_CLAVE_HMAC", min_length=32)

    # Servicios
    chroma_url: str = Field("http://chromadb:8000", alias="CHROMA_URL")
    modelos_url: str = Field("http://modelos:8000", alias="MODELOS_URL")
    modelos_timeout_s: float = Field(120.0, alias="MODELOS_TIMEOUT_S", gt=0)
    cors_origenes: list[str] = Field(default_factory=lambda: ["http://localhost:5173"], alias="CORS_ORIGENES")

    # Consultas (parte D): llamadas simultáneas al servicio modelos (embedding y reranker)
    # y a la API del modelo de lenguaje. Vacío en MAX_CONCURRENCIA_RERANKER significa
    # automático: núcleos visibles dividido por los hilos que informa el servicio modelos
    # (mínimo 1). Son de infraestructura, no de parametro_sistema.
    max_concurrencia_reranker: int | None = Field(None, alias="MAX_CONCURRENCIA_RERANKER", ge=1, le=16)
    max_concurrencia_llm: int = Field(4, alias="MAX_CONCURRENCIA_LLM", ge=1, le=32)
    # Calentamiento al arrancar: con true, además de los modelos locales, hace una llamada
    # sintética a la API del modelo de lenguaje (nunca con CDSS_ENTORNO=pruebas).
    calentar_llm: bool = Field(False, alias="CALENTAR_LLM")
    # Modelo de lenguaje del servicio de consultas: real (API de Anthropic) o falso (cliente
    # falso, sin costo, para revisar la interfaz). falso solo se acepta con
    # CDSS_ENTORNO=desarrollo; en otro entorno la configuración no carga y el backend no arranca.
    llm: Literal["real", "falso"] = Field("real", alias="CDSS_LLM")

    @model_validator(mode="after")
    def _llm_falso_solo_en_desarrollo(self):
        if self.llm == "falso" and self.entorno != "desarrollo":
            raise ValueError(f"CDSS_LLM=falso solo se admite con CDSS_ENTORNO=desarrollo (entorno actual: "
                             f"{self.entorno}). Use CDSS_LLM=real o quite la variable.")
        return self

    @field_validator("max_concurrencia_reranker", mode="before")
    @classmethod
    def _vacio_es_automatico(cls, valor):
        return None if isinstance(valor, str) and not valor.strip() else valor


@lru_cache
def get_settings() -> Settings:
    return Settings()
