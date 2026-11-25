#!/bin/bash
# Funciones comunes de los scripts de despliegue (Sprint 3, parte L). Se cargan con «source»; no se
# ejecutan solas.
#
# - Sin la CLI de Azure en la VM: Key Vault y Blob se usan por su API REST con curl, con un token de
#   la identidad administrada de la VM (servicio de metadatos de instancia, IMDS).
# - El token nunca va en los argumentos de un proceso (se verían en la lista de procesos): se pasa a
#   curl por la entrada estándar (-K -). Los valores de los secretos tampoco se imprimen.
# - El JSON se lee con python3 (viene con Ubuntu 24.04); CDSS_PYTHON permite otro intérprete.

RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONF="${CDSS_CONF_DESPLIEGUE:-$RAIZ/deploy/despliegue.conf}"
PYTHON="${CDSS_PYTHON:-python3}"
IMDS="${CDSS_IMDS_URL:-http://169.254.169.254}"
VERSION_BLOB="2021-08-06"

error() { echo "ERROR: $*" >&2; }
aviso() { echo "$*" >&2; }

cargar_conf() {
  if [ ! -f "$CONF" ]; then
    error "Falta $CONF. Copie deploy/despliegue.conf.ejemplo como deploy/despliegue.conf y complételo."
    return 1
  fi
  # shellcheck disable=SC1090
  source "$CONF"
  local variable
  for variable in KEY_VAULT CDSS_DOMINIO CUENTA_ALMACENAMIENTO CONTENEDOR_RESPALDOS; do
    if [ -z "${!variable:-}" ]; then
      error "Falta $variable en $CONF"
      return 1
    fi
  done
  CONSERVAR_RESPALDOS_CHROMA="${CONSERVAR_RESPALDOS_CHROMA:-14}"
  CONSERVAR_RESPALDOS_PG="${CONSERVAR_RESPALDOS_PG:-14}"
  local n
  for n in "$CONSERVAR_RESPALDOS_CHROMA" "$CONSERVAR_RESPALDOS_PG"; do
    if ! [[ "$n" =~ ^[1-9][0-9]*$ ]]; then
      error "CONSERVAR_RESPALDOS_CHROMA y CONSERVAR_RESPALDOS_PG deben ser enteros de 1 o más"
      return 1
    fi
  done
}

# Lee un campo de un objeto JSON de la entrada estándar (sin salto de línea final).
campo_json() {
  "$PYTHON" -c 'import json, sys; print(json.load(sys.stdin)[sys.argv[1]], end="")' "$1"
}

# Token de la identidad administrada para un recurso (https://vault.azure.net, https://storage.azure.com).
token_imds() {
  local recurso="$1" url respuesta
  url="$IMDS/metadata/identity/oauth2/token?api-version=2018-02-01&resource=$recurso"
  if [ -n "${AZURE_CLIENT_ID:-}" ]; then
    url="$url&client_id=$AZURE_CLIENT_ID"
  fi
  if ! respuesta="$(curl -sS --fail --max-time 30 -H "Metadata: true" "$url")"; then
    error "No se obtuvo el token de la identidad administrada para $recurso (¿la VM tiene identidad asignada?)"
    return 1
  fi
  printf '%s' "$respuesta" | campo_json access_token
}

# curl con «Authorization: Bearer» leído de la entrada estándar. Uso: curl_token TOKEN args...
curl_token() {
  local token="$1"
  shift
  printf 'header = "Authorization: Bearer %s"\n' "$token" | curl -K - "$@"
}

# Valor de un secreto de Key Vault. Código 0 si existe, 2 si no existe (404), 1 ante otro error.
kv_secreto() {
  local token="$1" nombre="$2" salida codigo
  salida="$(mktemp)"
  codigo="$(curl_token "$token" -sS --max-time 30 -o "$salida" -w '%{http_code}' \
    "https://$KEY_VAULT.vault.azure.net/secrets/$nombre?api-version=7.4")" || codigo="000"
  case "$codigo" in
    200) campo_json value < "$salida"; rm -f "$salida"; return 0 ;;
    404) rm -f "$salida"; return 2 ;;
    *) rm -f "$salida"; error "Key Vault respondió $codigo al leer el secreto $nombre"; return 1 ;;
  esac
}

url_blob() { printf 'https://%s.blob.core.windows.net/%s/%s' "$CUENTA_ALMACENAMIENTO" "$CONTENEDOR_RESPALDOS" "$1"; }

blob_subir() {
  local token="$1" archivo="$2" nombre="$3" codigo
  codigo="$(curl_token "$token" -sS --max-time 3600 -o /dev/null -w '%{http_code}' -X PUT \
    -H "x-ms-version: $VERSION_BLOB" -H "x-ms-blob-type: BlockBlob" \
    -H "Content-Type: application/octet-stream" --data-binary "@$archivo" "$(url_blob "$nombre")")" || codigo="000"
  if [ "$codigo" != "201" ]; then
    error "Blob respondió $codigo al subir $nombre"
    return 1
  fi
}

blob_bajar() {
  local token="$1" nombre="$2" destino="$3" codigo
  codigo="$(curl_token "$token" -sS --max-time 3600 -o "$destino" -w '%{http_code}' \
    -H "x-ms-version: $VERSION_BLOB" "$(url_blob "$nombre")")" || codigo="000"
  if [ "$codigo" != "200" ]; then
    error "Blob respondió $codigo al bajar $nombre"
    return 1
  fi
}

blob_borrar() {
  local token="$1" nombre="$2" codigo
  codigo="$(curl_token "$token" -sS --max-time 60 -o /dev/null -w '%{http_code}' -X DELETE \
    -H "x-ms-version: $VERSION_BLOB" "$(url_blob "$nombre")")" || codigo="000"
  if [ "$codigo" != "202" ]; then
    error "Blob respondió $codigo al borrar $nombre"
    return 1
  fi
}

# Nombres de los blobs con un prefijo, uno por línea (sigue las páginas de NextMarker).
blob_listar() {
  local token="$1" prefijo="$2" marcador="" pagina url
  pagina="$(mktemp)"
  while :; do
    url="https://$CUENTA_ALMACENAMIENTO.blob.core.windows.net/$CONTENEDOR_RESPALDOS?restype=container&comp=list&prefix=$prefijo"
    if [ -n "$marcador" ]; then
      url="$url&marker=$marcador"
    fi
    if ! curl_token "$token" -sS --fail --max-time 60 -o "$pagina" -H "x-ms-version: $VERSION_BLOB" "$url"; then
      rm -f "$pagina"
      error "No se pudo listar el contenedor $CONTENEDOR_RESPALDOS"
      return 1
    fi
    grep -o '<Name>[^<]*</Name>' "$pagina" | sed -e 's#<Name>##' -e 's#</Name>##' || true
    marcador="$(grep -o '<NextMarker>[^<]*</NextMarker>' "$pagina" | sed -e 's#<NextMarker>##' -e 's#</NextMarker>##' || true)"
    [ -z "$marcador" ] && break
  done
  rm -f "$pagina"
}

sha256() { sha256sum "$1" | cut -d' ' -f1; }

# Espera hasta que el contenedor del servicio esté sano (o en marcha, si no tiene healthcheck). Al
# encender la VM, los temporizadores atrasados corren apenas arranca systemd, antes que el stack.
esperar_servicio() {
  local servicio="$1" limite="${2:-900}" inicio id estado
  inicio="$(date +%s)"
  while :; do
    id="$(cd "$RAIZ" && docker compose ps -q "$servicio" 2>/dev/null || true)"
    if [ -n "$id" ]; then
      estado="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$id" 2>/dev/null || true)"
      case "$estado" in healthy|running) return 0 ;; esac
    fi
    if [ $(( $(date +%s) - inicio )) -ge "$limite" ]; then
      error "El servicio $servicio no está listo después de $limite s"
      return 1
    fi
    sleep 10
  done
}
