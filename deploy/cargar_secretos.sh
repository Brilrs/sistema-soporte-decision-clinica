#!/bin/bash
# Escribe el .env de la VM con los secretos de Azure Key Vault (Sprint 3, parte L).
#
#   ./deploy/cargar_secretos.sh
#
# - Lee cada secreto con la identidad administrada de la VM (rol «Key Vault Secrets User»), sin la
#   CLI de Azure ni credenciales en disco.
# - Escribe .env en la raíz del repositorio con permisos 600 (solo el dueño lo lee), de una sola vez:
#   primero en un archivo temporal y luego lo renombra. Si falta un secreto obligatorio o no es
#   válido, no cambia el .env existente.
# - Nunca imprime ni registra un valor: solo los nombres.
# - Se niega a reemplazar un .env que no haya escrito este script (por ejemplo, el de desarrollo).
#
# Nombres de los secretos y su variable: docs/despliegue_azure.md, «Secretos en Key Vault».
set -euo pipefail
# shellcheck source=deploy/comun.sh
source "$(dirname "$0")/comun.sh"

MARCA="# Generado por deploy/cargar_secretos.sh: no editar a mano (se reemplaza en cada ejecución)."
DESTINO="${CDSS_ENV_ARCHIVO:-$RAIZ/.env}"

# nombre en Key Vault : variable de entorno : validación
#   url:   solo letras, números y . _ ~ - (va dentro de DATABASE_URL_*), al menos 16 caracteres
#   clave: al menos 32 caracteres (el backend lo exige)
#   texto: no vacío
OBLIGATORIOS=(
  "postgres-password:POSTGRES_PASSWORD:url"
  "db-pwd-clinica:CDSS_DB_PWD_CLINICA:url"
  "db-pwd-generacion:CDSS_DB_PWD_GENERACION:url"
  "db-pwd-admin:CDSS_DB_PWD_ADMIN:url"
  "db-pwd-auditor:CDSS_DB_PWD_AUDITOR:url"
  "db-pwd-indexador:CDSS_DB_PWD_INDEXADOR:url"
  "jwt-secreto:JWT_SECRETO:clave"
  "clave-pii:CDSS_CLAVE_PII:clave"
  "clave-hmac:CDSS_CLAVE_HMAC:clave"
  "anthropic-api-key:ANTHROPIC_API_KEY:texto"
)
# Opcionales: si no existen, la variable no se escribe.
#   seed-contrasena: solo para cargar las cuentas sintéticas de seed_demo (validación con usuarios).
#   blob-cadena-conexion: solo si no se usa la identidad administrada para Blob.
OPCIONALES=(
  "seed-contrasena:SEED_CONTRASENA:texto"
  "blob-cadena-conexion:AZURE_STORAGE_CONNECTION_STRING:texto"
)

valido() {
  local tipo="$1" valor="$2"
  case "$valor" in *$'\n'*|*$'\r'*|*"'"*) return 1 ;; esac
  case "$tipo" in
    url) [[ "$valor" =~ ^[A-Za-z0-9._~-]{16,}$ ]] ;;
    clave) [ "${#valor}" -ge 32 ] ;;
    texto) [ -n "$valor" ] ;;
  esac
}

linea() { printf "%s='%s'\n" "$1" "$2"; }

main() {
  cargar_conf
  if [ -f "$DESTINO" ] && ! grep -qxF "$MARCA" "$DESTINO"; then
    error "$DESTINO existe y no lo escribió este script: no se reemplaza. Muévalo antes de seguir."
    return 1
  fi
  local token
  token="$(token_imds "https%3A%2F%2Fvault.azure.net")"

  umask 077
  local temporal
  temporal="$(mktemp "$(dirname "$DESTINO")/.env.XXXXXX")"
  # shellcheck disable=SC2064
  trap "rm -f '$temporal'" EXIT

  local version
  version="$(git -C "$RAIZ" rev-parse --short HEAD 2>/dev/null || echo desconocida)"
  {
    echo "$MARCA"
    echo "# Configuración (sin secretos), de deploy/despliegue.conf"
    linea COMPOSE_FILE "docker-compose.yml:docker-compose.prod.yml"
    linea CDSS_DOMINIO "$CDSS_DOMINIO"
    linea RESPALDO_CONTENEDOR_BLOB "$CONTENEDOR_RESPALDOS"
    linea AZURE_STORAGE_ACCOUNT_URL "https://$CUENTA_ALMACENAMIENTO.blob.core.windows.net"
    linea CDSS_VERSION_CODIGO "$version"
    linea CDSS_SEED_EXIGIR_CAMBIO "true"
    if [ -n "${AZURE_CLIENT_ID:-}" ]; then
      linea AZURE_CLIENT_ID "$AZURE_CLIENT_ID"
    fi
    echo "# Secretos de Key Vault $KEY_VAULT"
  } > "$temporal"

  local entrada nombre variable tipo valor estado faltan=0
  for entrada in "${OBLIGATORIOS[@]}" "${OPCIONALES[@]}"; do
    IFS=: read -r nombre variable tipo <<< "$entrada"
    estado=0
    valor="$(kv_secreto "$token" "$nombre")" || estado=$?
    if [ "$estado" -eq 2 ]; then
      if [[ " ${OPCIONALES[*]} " == *" $entrada "* ]]; then
        aviso "  $nombre: no existe (opcional, se omite $variable)"
        continue
      fi
      error "Falta el secreto obligatorio $nombre ($variable) en $KEY_VAULT"
      faltan=1
      continue
    elif [ "$estado" -ne 0 ]; then
      return 1
    fi
    if ! valido "$tipo" "$valor"; then
      case "$tipo" in
        url) error "El secreto $nombre debe tener al menos 16 caracteres y solo letras, números y . _ ~ - (va dentro de una URL de conexión). Genérelo con openssl rand -hex 32" ;;
        clave) error "El secreto $nombre debe tener al menos 32 caracteres" ;;
        texto) error "El secreto $nombre está vacío o tiene comillas simples o saltos de línea" ;;
      esac
      faltan=1
      continue
    fi
    linea "$variable" "$valor" >> "$temporal"
    aviso "  $nombre: ok ($variable)"
  done
  valor=""
  if [ "$faltan" -ne 0 ]; then
    error "No se escribió $DESTINO"
    return 1
  fi
  chmod 600 "$temporal"
  mv -f "$temporal" "$DESTINO"
  trap - EXIT
  echo "Escrito $DESTINO (permisos 600)."
}

main "$@"
