#!/bin/bash
# Crea los usuarios de conexión del backend dentro del contenedor de PostgreSQL.
# Lo ejecuta automáticamente la imagen oficial de postgres en la primera inicialización.
set -euo pipefail
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -v pwd_clinica="$CDSS_DB_PWD_CLINICA" \
  -v pwd_generacion="$CDSS_DB_PWD_GENERACION" \
  -v pwd_admin="$CDSS_DB_PWD_ADMIN" \
  -v pwd_auditor="$CDSS_DB_PWD_AUDITOR" <<'SQL'
\o /dev/null
SELECT set_config('cdss.pwd_clinica', :'pwd_clinica', false),
       set_config('cdss.pwd_generacion', :'pwd_generacion', false),
       set_config('cdss.pwd_admin', :'pwd_admin', false),
       set_config('cdss.pwd_auditor', :'pwd_auditor', false);
\o
\i /cdss-sql/usuarios_bd.sql
SQL
