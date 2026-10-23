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
EXPOSE 80
