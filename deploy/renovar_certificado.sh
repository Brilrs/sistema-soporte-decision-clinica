#!/bin/bash
# Certificado de Let's Encrypt para CDSS_DOMINIO (Sprint 3, parte L), con certbot en un contenedor
# (servicio certbot de docker-compose.prod.yml, perfil certbot).
#
#   ./deploy/renovar_certificado.sh emitir     # primera vez: Nginx detenido, certbot escucha en el 80
#   ./deploy/renovar_certificado.sh            # renovación (cdss-certificado.timer, dos veces al día)
#
# emitir: el certificado aún no existe y Nginx no arranca sin él, así que certbot usa el modo
#   standalone (su propio servidor en el puerto 80) y después se levanta Nginx.
# renovar: con Nginx en marcha, certbot deja el desafío en el volumen certbot_webroot, que Nginx sirve
#   en /.well-known/acme-challenge/ (puerto 80). Solo renueva si faltan menos de 30 días; después se
#   recarga Nginx para que tome el certificado nuevo.
set -euo pipefail
# shellcheck source=deploy/comun.sh
source "$(dirname "$0")/comun.sh"

main() {
  local accion="${1:-renovar}"
  cargar_conf
  cd "$RAIZ"
  local correo=(--register-unsafely-without-email)
  if [ -n "${CERTBOT_CORREO:-}" ]; then
    correo=(--email "$CERTBOT_CORREO")
  fi
  case "$accion" in
    emitir)
      docker compose stop nginx
      docker compose run --rm -p 80:80 certbot certonly --standalone --non-interactive --agree-tos \
        "${correo[@]}" --key-type ecdsa -d "$CDSS_DOMINIO"
      docker compose up -d nginx
      echo "Certificado emitido para $CDSS_DOMINIO y Nginx levantado."
      ;;
    renovar)
      esperar_servicio nginx
      docker compose run --rm -T certbot renew --webroot -w /var/www/certbot --non-interactive
      docker compose exec -T nginx nginx -s reload
      echo "Renovación revisada y Nginx recargado."
      ;;
    *)
      error "Uso: $0 [emitir|renovar]"
      return 2
      ;;
  esac
}

main "$@"
