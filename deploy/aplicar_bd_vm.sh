#!/bin/bash
# Ejecuta db/aplicar_bd.sh en la VM sin instalar psql en el host (Sprint 3, parte L).
#
#   ./deploy/aplicar_bd_vm.sh --solo-migraciones   # base existente: migraciones y usuarios nuevos
#   ./deploy/aplicar_bd_vm.sh                      # base vacía: esquema, catálogos, usuarios y migraciones
#
# La primera vez no hace falta: el contenedor db crea todo al iniciarse con el volumen vacío
# (db/init). Este script sirve para aplicar migraciones nuevas sobre una base con datos.
#
# Usa el cliente psql 16 de la imagen postgres:16-alpine (la misma del servicio db) en un contenedor
# temporal conectado a la red del stack. Las contraseñas pasan como variables de entorno por nombre
# (-e NOMBRE, sin el valor en la línea de comandos), y aplicar_bd.sh las lee con \getenv.
set -euo pipefail
RAIZ="$(cd "$(dirname "$0")/.." && pwd)"
ENV_ARCHIVO="${CDSS_ENV_ARCHIVO:-$RAIZ/.env}"
IMAGEN="${CDSS_IMAGEN_PSQL:-postgres:16-alpine}"

if [ ! -f "$ENV_ARCHIVO" ]; then
  echo "ERROR: falta $ENV_ARCHIVO (deploy/cargar_secretos.sh)" >&2
  exit 1
fi
set -a
# shellcheck disable=SC1090
source "$ENV_ARCHIVO"
set +a

# Red y nombre del servidor: los del stack (cdss-anemia, servicio db), o los indicados para pruebas.
if [ -n "${CDSS_BD_RED:-}" ]; then
  RED="$CDSS_BD_RED"
else
  ID_DB="$(cd "$RAIZ" && docker compose ps -q db)"
  if [ -z "$ID_DB" ]; then
    echo "ERROR: el servicio db no está en marcha (docker compose up -d db)" >&2
    exit 1
  fi
  RED="$(docker inspect -f '{{range $nombre, $_ := .NetworkSettings.Networks}}{{$nombre}}{{end}}' "$ID_DB")"
fi
export PGHOST="${CDSS_BD_HOST:-db}" PGUSER=postgres PGDATABASE=cdss
export PGPASSWORD="${POSTGRES_PASSWORD:?Falta POSTGRES_PASSWORD en $ENV_ARCHIVO}"

docker run --rm --network "$RED" \
  -e PGHOST -e PGUSER -e PGDATABASE -e PGPASSWORD \
  -e CDSS_DB_PWD_CLINICA -e CDSS_DB_PWD_GENERACION -e CDSS_DB_PWD_ADMIN \
  -e CDSS_DB_PWD_AUDITOR -e CDSS_DB_PWD_INDEXADOR \
  -v "$RAIZ/db:/cdss-db:ro" \
  "$IMAGEN" bash /cdss-db/aplicar_bd.sh "$@"
