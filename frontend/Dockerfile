# Etapa 1: compilar la aplicación React
FROM node:22-alpine AS compilacion
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

# Etapa 2: Nginx sirve la aplicación y redirige /api al backend
FROM nginx:1.27-alpine
COPY --from=compilacion /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
# Reglas comunes a desarrollo y producción, y la plantilla HTTPS que usa docker-compose.prod.yml
# (NGINX_ENVSUBST_TEMPLATE_DIR=/etc/nginx/cdss/plantillas). En desarrollo la plantilla no se usa.
COPY nginx/cdss_rutas.conf /etc/nginx/cdss/rutas.conf
COPY nginx.prod.conf.template /etc/nginx/cdss/plantillas/default.conf.template
EXPOSE 80 443
