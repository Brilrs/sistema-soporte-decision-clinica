#!/bin/bash
# Respaldo de PostgreSQL hacia Azure Blob (Sprint 3, parte L). PostgreSQL va en el contenedor db de la
# VM, así que este es su único respaldo (no hay el respaldo automático del servicio administrado).
#
#   ./deploy/respaldo_pg.sh        (lo ejecuta cada día cdss-respaldo-pg.timer)
#
# 1. pg_dump de la base cdss en formato custom (comprimido) dentro del contenedor db.
# 2. Comprueba que el archivo se lee completo (pg_restore --list).
# 3. Lo sube a Blob como pg/cdss_AAAAMMDD_HHMMSS.dump (hora de Lima), lo vuelve a bajar y compara el
#    SHA-256.
# 4. Retención: conserva los CONSERVAR_RESPALDOS_PG más nuevos y borra los más antiguos. Solo toca
#    blobs con el nombre exacto pg/cdss_AAAAMMDD_HHMMSS.dump.
#
# Código de salida 0 si todo salió bien; distinto de 0 si algo falló (systemd lo registra).
# Restauración: deploy/restaurar_pg.sh.
set -euo pipefail
# shellcheck source=deploy/comun.sh
source "$(dirname "$0")/comun.sh"

PATRON='^pg/cdss_[0-9]{8}_[0-9]{6}\.dump$'

main() {
  cargar_conf
  cd "$RAIZ"
  esperar_servicio db

  local carpeta nombre archivo copia huella token
  carpeta="$(mktemp -d)"
  # shellcheck disable=SC2064
  trap "rm -rf '$carpeta'" EXIT
  nombre="pg/cdss_$(TZ=America/Lima date +%Y%m%d_%H%M%S).dump"
  archivo="$carpeta/respaldo.dump"

  echo "pg_dump de la base cdss"
  docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "$archivo"
  if [ ! -s "$archivo" ]; then
    error "pg_dump no produjo datos"
    return 1
  fi
  if ! docker compose exec -T db pg_restore --list < "$archivo" > /dev/null; then
    error "El respaldo no se puede leer con pg_restore: no se sube"
    return 1
  fi
  huella="$(sha256 "$archivo")"

  token="$(token_imds "https%3A%2F%2Fstorage.azure.com%2F")"
  echo "Subiendo $nombre ($(wc -c < "$archivo") bytes)"
  blob_subir "$token" "$archivo" "$nombre"
  copia="$carpeta/comprobacion.dump"
  blob_bajar "$token" "$nombre" "$copia"
  if [ "$(sha256 "$copia")" != "$huella" ]; then
    error "El blob $nombre no coincide con el archivo subido (SHA-256): no se aplica la retención"
    return 1
  fi
  echo "Subido y comprobado: $nombre (SHA-256 $huella)"

  # Retención, solo después de un respaldo completo y comprobado.
  local respaldos total sobran viejo
  mapfile -t respaldos < <(blob_listar "$token" "pg/" | grep -E "$PATRON" | sort)
  total="${#respaldos[@]}"
  sobran=$(( total - CONSERVAR_RESPALDOS_PG ))
  if [ "$sobran" -gt 0 ]; then
    for viejo in "${respaldos[@]:0:$sobran}"; do
      blob_borrar "$token" "$viejo"
      echo "Borrado por la retención: $viejo"
    done
  fi
  echo "Respaldos de PostgreSQL en Blob: $(( total > CONSERVAR_RESPALDOS_PG ? CONSERVAR_RESPALDOS_PG : total )) (se conservan $CONSERVAR_RESPALDOS_PG)"
}

main "$@"
