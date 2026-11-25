#!/bin/bash
# Restauración probada de un respaldo de ChromaDB desde Azure Blob (Sprint 3, parte L). No toca la
# colección real guias_clinicas.
#
#   ./deploy/probar_restauracion_chroma.sh                             # el respaldo más nuevo
#   ./deploy/probar_restauracion_chroma.sh respaldo_AAAAMMDD_HHMMSS    # uno dado
#
# 1. Restaura el respaldo en la colección guias_clinicas_prueba_restauracion (comprueba los SHA-256 y
#    el manifiesto antes de escribir, y la colección restaurada contra PostgreSQL).
# 2. Compara esa colección con guias_clinicas (ids, textos, metadatos, vectores con tolerancia 1e-6 y
#    5 consultas).
# 3. Descarta la colección de prueba, también si algo falló.
#
# La restauración real (en una ChromaDB vacía, después de PostgreSQL) está en docs/respaldo.md,
# «Orden de restauración», con --destino blob.
set -euo pipefail
# shellcheck source=deploy/comun.sh
source "$(dirname "$0")/comun.sh"

COLECCION_PRUEBA=guias_clinicas_prueba_restauracion
PATRON='^respaldo_[0-9]{8}_[0-9]{6}$'

descartar() {
  docker compose run --rm -T respaldo python -m app.respaldo descartar-coleccion "$COLECCION_PRUEBA" \
    > /dev/null 2>&1 || true
}

main() {
  cargar_conf
  cd "$RAIZ"
  esperar_servicio db
  esperar_servicio chromadb
  local nombre="${1:-}" token
  if [ -z "$nombre" ]; then
    token="$(token_imds "https%3A%2F%2Fstorage.azure.com%2F")"
    nombre="$(blob_listar "$token" "respaldo_" | cut -d/ -f1 | grep -E "$PATRON" | sort -u | tail -n 1 || true)"
    if [ -z "$nombre" ]; then
      error "No hay respaldos de ChromaDB en el contenedor $CONTENEDOR_RESPALDOS"
      return 1
    fi
  fi
  if ! [[ "$nombre" =~ $PATRON ]]; then
    error "Nombre de respaldo no válido: $nombre (se espera respaldo_AAAAMMDD_HHMMSS)"
    return 2
  fi
  descartar  # por si quedó de una prueba anterior
  trap descartar EXIT
  echo "Restaurando $nombre en $COLECCION_PRUEBA"
  docker compose run --rm -T respaldo python -m app.respaldo restaurar "$nombre" --destino blob \
    --coleccion "$COLECCION_PRUEBA"
  docker compose run --rm -T respaldo python -m app.respaldo comparar guias_clinicas "$COLECCION_PRUEBA"
  echo "Restauración probada: $nombre coincide con guias_clinicas. Se descarta $COLECCION_PRUEBA."
}

main "$@"
