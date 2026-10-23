#!/bin/bash
# Crea el archivo .env con secretos aleatorios para el entorno local.
set -euo pipefail
cd "$(dirname "$0")"
if [ -f .env ]; then echo ".env ya existe; no se sobrescribe."; exit 0; fi
aleatorio() { openssl rand -hex "$1"; }
cat > .env <<ENV
POSTGRES_PASSWORD=$(aleatorio 16)
CDSS_DB_PWD_CLINICA=$(aleatorio 16)
CDSS_DB_PWD_GENERACION=$(aleatorio 16)
CDSS_DB_PWD_ADMIN=$(aleatorio 16)
CDSS_DB_PWD_AUDITOR=$(aleatorio 16)
JWT_SECRETO=$(aleatorio 32)
CDSS_CLAVE_PII=$(aleatorio 32)
CDSS_CLAVE_HMAC=$(aleatorio 32)
SEED_CONTRASENA=Cdss2026!
ANTHROPIC_API_KEY=
OPENROUTER_API_KEY=
ENV
echo ".env creado. Guarde CDSS_CLAVE_PII: sin ella no se puede descifrar la identidad de los pacientes."
