#!/bin/bash
# Restauración de un respaldo de PostgreSQL desde Azure Blob (Sprint 3, parte L).
#
#   ./deploy/restaurar_pg.sh                                   # prueba con el respaldo más nuevo
#   ./deploy/restaurar_pg.sh pg/cdss_AAAAMMDD_HHMMSS.dump      # prueba con un respaldo dado
#   ./deploy/restaurar_pg.sh pg/cdss_AAAAMMDD_HHMMSS.dump --sobre-cdss --confirmo
#
# Por omisión es una prueba que no toca la base real: restaura en la base aparte
# cdss_prueba_restauracion, compara la cantidad de tablas y de filas de las tablas principales con
# cdss, y la borra al final. Así se comprueba que el respaldo sirve.
#
# Con --sobre-cdss --confirmo restaura sobre la base cdss (borra y vuelve a crear sus objetos), con el
# backend y el indexador detenidos. Después hay que restaurar ChromaDB del mismo momento
# (docs/respaldo.md, «Orden de restauración») y verificarla.
set -euo pipefail
# shellcheck source=deploy/comun.sh
source "$(dirname "$0")/comun.sh"

PATRON='^pg/cdss_[0-9]{8}_[0-9]{6}\.dump$'
PRUEBA=cdss_prueba_restauracion
TABLAS="seguridad.usuario clinico.paciente clinico.tamizaje asistencia.consulta conocimiento.documento_fuente conocimiento.fragmento configuracion.parametro_sistema"

consulta_sql() {  # base, sql: imprime el resultado sin encabezados
  docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$1" -At -v ON_ERROR_STOP=1 -c "$2"' sh "$1" "$2"
}

main() {
  local nombre="" sobre_cdss=false confirmo=false argumento
  for argumento in "$@"; do
    case "$argumento" in
      --sobre-cdss) sobre_cdss=true ;;
      --confirmo) confirmo=true ;;
      -*) error "Opción no reconocida: $argumento"; return 2 ;;
      *) nombre="$argumento" ;;
    esac
  done
  if [ "$sobre_cdss" = true ] && [ "$confirmo" != true ]; then
    error "--sobre-cdss reemplaza la base cdss: agregue --confirmo para hacerlo"
    return 2
  fi
  if [ "$sobre_cdss" = true ] && [ -z "$nombre" ]; then
    error "--sobre-cdss exige el nombre del respaldo (pg/cdss_AAAAMMDD_HHMMSS.dump)"
    return 2
  fi

  cargar_conf
  cd "$RAIZ"
  esperar_servicio db
  local token carpeta archivo
  token="$(token_imds "https%3A%2F%2Fstorage.azure.com%2F")"
  if [ -z "$nombre" ]; then
    nombre="$(blob_listar "$token" "pg/" | grep -E "$PATRON" | sort | tail -n 1 || true)"
    if [ -z "$nombre" ]; then
      error "No hay respaldos de PostgreSQL en el contenedor $CONTENEDOR_RESPALDOS"
      return 1
    fi
  fi
  if ! [[ "$nombre" =~ $PATRON ]]; then
    error "Nombre de respaldo no válido: $nombre (se espera pg/cdss_AAAAMMDD_HHMMSS.dump)"
    return 2
  fi

  carpeta="$(mktemp -d)"
  # shellcheck disable=SC2064
  trap "rm -rf '$carpeta'" EXIT
  archivo="$carpeta/respaldo.dump"
  echo "Bajando $nombre"
  blob_bajar "$token" "$nombre" "$archivo"
  docker compose exec -T db pg_restore --list < "$archivo" > /dev/null

  if [ "$sobre_cdss" = true ]; then
    echo "Restaurando sobre cdss (backend e indexador detenidos)"
    docker compose stop backend indexador
    docker compose exec -T db sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists' < "$archivo"
    docker compose start backend indexador
    echo "Restaurado sobre cdss. Siga con ChromaDB del mismo momento y verifíquela (docs/respaldo.md)."
    return 0
  fi

  echo "Prueba de restauración en la base $PRUEBA"
  docker compose exec -T db sh -c 'dropdb -U "$POSTGRES_USER" --if-exists "$1" && createdb -U "$POSTGRES_USER" "$1"' sh "$PRUEBA"
  # shellcheck disable=SC2064
  trap "rm -rf '$carpeta'; docker compose exec -T db sh -c 'dropdb -U \"\$POSTGRES_USER\" --if-exists $PRUEBA' >/dev/null 2>&1 || true" EXIT
  docker compose exec -T db sh -c 'pg_restore -U "$POSTGRES_USER" -d "$1" --exit-on-error' sh "$PRUEBA" < "$archivo"

  local sql_tablas="SELECT count(*) FROM information_schema.tables WHERE table_schema IN ('seguridad','clinico','asistencia','conocimiento','configuracion','auditoria')"
  local tablas_cdss tablas_prueba tabla n_cdss n_prueba
  tablas_cdss="$(consulta_sql cdss "$sql_tablas")"
  tablas_prueba="$(consulta_sql "$PRUEBA" "$sql_tablas")"
  printf '%-34s %12s %12s\n' "Tabla" "cdss" "restaurada"
  printf '%-34s %12s %12s\n' "(tablas y vistas)" "$tablas_cdss" "$tablas_prueba"
  for tabla in $TABLAS; do
    n_cdss="$(consulta_sql cdss "SELECT count(*) FROM $tabla")"
    n_prueba="$(consulta_sql "$PRUEBA" "SELECT count(*) FROM $tabla")"
    printf '%-34s %12s %12s\n' "$tabla" "$n_cdss" "$n_prueba"
  done
  if [ "$tablas_cdss" != "$tablas_prueba" ]; then
    error "La base restaurada no tiene las mismas tablas que cdss"
    return 1
  fi
  echo "Restauración probada: $nombre se restauró completo en $PRUEBA (las filas pueden diferir si cdss cambió después del respaldo). La base de prueba se borra."
}

main "$@"
