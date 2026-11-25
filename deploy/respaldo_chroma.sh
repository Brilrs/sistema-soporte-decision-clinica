#!/bin/bash
# Respaldo de ChromaDB y de las guías cargadas hacia Azure Blob (Sprint 3, parte L).
#
#   ./deploy/respaldo_chroma.sh    (lo ejecuta cada día cdss-respaldo-chroma.timer)
#
# Usa el trabajo de la parte K (python -m app.respaldo, docs/respaldo.md) con --destino blob: al subir,
# vuelve a bajar cada archivo y compara su SHA-256, y la retención solo borra respaldos completos con
# el nombre respaldo_AAAAMMDD_HHMMSS. Blob con la identidad administrada de la VM
# (AZURE_STORAGE_ACCOUNT_URL y RESPALDO_CONTENEDOR_BLOB en .env, de deploy/cargar_secretos.sh).
#
# Después de crear, verifica la colección contra PostgreSQL (solo lectura). Si hay una indexación en
# curso, crear se niega (código 1) y lo intenta el día siguiente.
# Restauración probada: deploy/probar_restauracion_chroma.sh.
set -euo pipefail
# shellcheck source=deploy/comun.sh
source "$(dirname "$0")/comun.sh"

main() {
  cargar_conf
  cd "$RAIZ"
  esperar_servicio db
  esperar_servicio chromadb
  docker compose run --rm -T respaldo python -m app.respaldo crear --destino blob \
    --conservar "$CONSERVAR_RESPALDOS_CHROMA"
  docker compose run --rm -T respaldo python -m app.respaldo verificar
}

main "$@"
