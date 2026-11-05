#!/bin/bash
# Aplica las migraciones de db/migraciones dentro del contenedor de PostgreSQL.
# En la primera inicialización no cambian nada (01 y 02 ya crean el estado final),
# pero se ejecutan para comprobar que siguen siendo idempotentes.
# En una base existente se aplican con:
#   docker compose exec db bash /docker-entrypoint-initdb.d/04_migraciones.sh
set -euo pipefail
for archivo in /cdss-migraciones/*.sql; do
  echo "Aplicando $(basename "$archivo")"
  psql -q -v ON_ERROR_STOP=1 --single-transaction --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" -f "$archivo"
done
