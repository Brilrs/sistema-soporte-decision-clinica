"""Configuración del backend, leída de variables de entorno (.env en desarrollo,
Azure Key Vault en producción)."""
from functools import lru_cache

from pydantic import Field
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
    cors_origenes: list[str] = Field(default_factory=lambda: ["http://localhost:5173"], alias="CORS_ORIGENES")


@lru_cache
def get_settings() -> Settings:
    return Settings()
