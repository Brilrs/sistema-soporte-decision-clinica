#!/bin/bash
# Aplica el esquema, los catálogos y los usuarios de conexión en una base existente
# (por ejemplo, Azure Database for PostgreSQL - Servidor flexible).
#
# Uso:
#   export PGHOST=... PGUSER=... PGPASSWORD=... PGDATABASE=cdss PGSSLMODE=require
#   export CDSS_DB_PWD_CLINICA=... CDSS_DB_PWD_GENERACION=... CDSS_DB_PWD_ADMIN=... CDSS_DB_PWD_AUDITOR=...
#   ./db/aplicar_bd.sh
#
# En Azure, antes de ejecutarlo, agregue PGCRYPTO y BTREE_GIST al parámetro
# del servidor "azure.extensions".
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
psql -v ON_ERROR_STOP=1 -f "$DIR/init/01_esquema.sql"
psql -v ON_ERROR_STOP=1 -f "$DIR/init/02_catalogos.sql"
psql -v ON_ERROR_STOP=1 \
  -v pwd_clinica="$CDSS_DB_PWD_CLINICA" -v pwd_generacion="$CDSS_DB_PWD_GENERACION" \
  -v pwd_admin="$CDSS_DB_PWD_ADMIN" -v pwd_auditor="$CDSS_DB_PWD_AUDITOR" <<SQL
\o /dev/null
SELECT set_config('cdss.pwd_clinica', :'pwd_clinica', false),
       set_config('cdss.pwd_generacion', :'pwd_generacion', false),
       set_config('cdss.pwd_admin', :'pwd_admin', false),
       set_config('cdss.pwd_auditor', :'pwd_auditor', false);
\o
\i $DIR/sql/usuarios_bd.sql
SQL
echo "Base de datos lista."
