#!/bin/bash
# Crea los usuarios de conexión del backend dentro del contenedor de PostgreSQL.
# Lo ejecuta automáticamente la imagen oficial de postgres en la primera inicialización.
# En una base existente se puede volver a ejecutar para crear los usuarios nuevos:
#   docker compose exec db bash /docker-entrypoint-initdb.d/03_usuarios_bd.sh
# Las contraseñas no van en la línea de comandos de psql (con -v se verían en la lista de procesos,
# también desde el host): psql las lee de las variables de entorno del contenedor con \getenv
# (psql 16 de la imagen).
set -euo pipefail
for variable in CDSS_DB_PWD_CLINICA CDSS_DB_PWD_GENERACION CDSS_DB_PWD_ADMIN CDSS_DB_PWD_AUDITOR \
                CDSS_DB_PWD_INDEXADOR; do
  if [ -z "${!variable:-}" ]; then
    echo "Falta la variable de entorno $variable" >&2
    exit 1
  fi
done
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<'SQL'
\getenv pwd_clinica CDSS_DB_PWD_CLINICA
\getenv pwd_generacion CDSS_DB_PWD_GENERACION
\getenv pwd_admin CDSS_DB_PWD_ADMIN
\getenv pwd_auditor CDSS_DB_PWD_AUDITOR
\getenv pwd_indexador CDSS_DB_PWD_INDEXADOR
\o /dev/null
SELECT set_config('cdss.pwd_clinica', :'pwd_clinica', false),
       set_config('cdss.pwd_generacion', :'pwd_generacion', false),
       set_config('cdss.pwd_admin', :'pwd_admin', false),
       set_config('cdss.pwd_auditor', :'pwd_auditor', false),
       set_config('cdss.pwd_indexador', :'pwd_indexador', false);
\o
\i /cdss-sql/usuarios_bd.sql
SQL
