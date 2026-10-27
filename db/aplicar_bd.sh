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
# Funciona en Linux, macOS y Windows (Git Bash con el psql nativo de PostgreSQL).
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
USUARIOS_SQL="$DIR/sql/usuarios_bd.sql"
# En Git Bash, psql es un programa de Windows: dentro del script de psql (\i) la ruta
# debe ir en formato de Windows (C:/...), porque no pasa por la conversión de Git Bash.
if command -v cygpath >/dev/null 2>&1; then
  USUARIOS_SQL="$(cygpath -m "$USUARIOS_SQL")"
fi

psql -v ON_ERROR_STOP=1 -f "$DIR/init/01_esquema.sql"
psql -v ON_ERROR_STOP=1 -f "$DIR/init/02_catalogos.sql"
# Las contraseñas se cargan en la sesión con set_config. \gset guarda el resultado de la
# consulta en variables de psql en lugar de imprimirlo, así que no aparecen en pantalla
# (antes se usaba \o /dev/null, que no existe en Windows). VERBOSITY terse evita que un
# error muestre el contexto con la sentencia ejecutada.
psql -q -v ON_ERROR_STOP=1 \
  -v pwd_clinica="$CDSS_DB_PWD_CLINICA" -v pwd_generacion="$CDSS_DB_PWD_GENERACION" \
  -v pwd_admin="$CDSS_DB_PWD_ADMIN" -v pwd_auditor="$CDSS_DB_PWD_AUDITOR" <<SQL
\set VERBOSITY terse
SELECT set_config('cdss.pwd_clinica', :'pwd_clinica', false) AS clinica,
       set_config('cdss.pwd_generacion', :'pwd_generacion', false) AS generacion,
       set_config('cdss.pwd_admin', :'pwd_admin', false) AS admin,
       set_config('cdss.pwd_auditor', :'pwd_auditor', false) AS auditor
\gset _cfg_
\unset _cfg_clinica
\unset _cfg_generacion
\unset _cfg_admin
\unset _cfg_auditor
\i '$USUARIOS_SQL'
SQL
echo "Base de datos lista."
