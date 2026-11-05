#!/bin/bash
# Crea el archivo .env con secretos aleatorios para el entorno local. Si ya existe,
# solo agrega al final las variables que le falten: nunca cambia ni regenera las
# que ya tiene. Para otro archivo: CDSS_ENV_ARCHIVO=/ruta/al/.env ./generar_env.sh
set -euo pipefail
cd "$(dirname "$0")"
ARCHIVO="${CDSS_ENV_ARCHIVO:-.env}"
aleatorio() { openssl rand -hex "$1"; }

nuevo=false
if [ ! -f "$ARCHIVO" ]; then
  nuevo=true
  : > "$ARCHIVO"
fi
agregadas=()

# agregar CLAVE VALOR: escribe CLAVE=VALOR solo si CLAVE no está definida.
agregar() {
  if grep -q "^$1=" "$ARCHIVO"; then
    return
  fi
  # Si la última línea no termina en salto de línea, se agrega uno antes.
  if [ -s "$ARCHIVO" ] && [ -n "$(tail -c1 "$ARCHIVO")" ]; then
    printf '\n' >> "$ARCHIVO"
  fi
  printf '%s=%s\n' "$1" "$2" >> "$ARCHIVO"
  agregadas+=("$1")
}

agregar POSTGRES_PASSWORD "$(aleatorio 16)"
agregar CDSS_DB_PWD_CLINICA "$(aleatorio 16)"
agregar CDSS_DB_PWD_GENERACION "$(aleatorio 16)"
agregar CDSS_DB_PWD_ADMIN "$(aleatorio 16)"
agregar CDSS_DB_PWD_AUDITOR "$(aleatorio 16)"
agregar CDSS_DB_PWD_INDEXADOR "$(aleatorio 16)"
agregar JWT_SECRETO "$(aleatorio 32)"
agregar CDSS_CLAVE_PII "$(aleatorio 32)"
agregar CDSS_CLAVE_HMAC "$(aleatorio 32)"
agregar SEED_CONTRASENA 'Cdss2026!'
agregar ANTHROPIC_API_KEY ''
agregar OPENROUTER_API_KEY ''

if [ "$nuevo" = true ]; then
  echo "$ARCHIVO creado. Guarde CDSS_CLAVE_PII: sin ella no se puede descifrar la identidad de los pacientes."
elif [ "${#agregadas[@]}" -gt 0 ]; then
  echo "$ARCHIVO ya existía; se agregaron: ${agregadas[*]}. Las demás variables no se modificaron."
else
  echo "$ARCHIVO ya existía y tiene todas las variables; no se modificó."
fi
