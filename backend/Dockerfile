FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# Usuario sin privilegios dentro del contenedor
RUN useradd --create-home cdss
# PDF cargados desde M11 (volumen datos_guias_cargadas): la carpeta existe en la imagen con dueño
# cdss, así un volumen nuevo se crea con ese dueño y el backend puede escribir en él. Un volumen
# creado antes necesita un chown una sola vez (jobs/README.md, «Volumen de las guías cargadas»).
RUN mkdir -p /datos/guias_cargadas && chown cdss:cdss /datos/guias_cargadas
USER cdss

# Procesos fuera de línea (indexador de guías y evaluación). Se ejecutan con
# docker compose run --rm jobs python -m app.<módulo>
FROM base AS jobs
USER root
COPY requirements-jobs.txt .
RUN pip install --no-cache-dir -r requirements-jobs.txt
USER cdss
CMD ["python", "-m", "app.indexador", "--help"]

# Evaluación del OE3 (docs/diseno_evaluacion_oe3.md): RAGAS y el código de app/evaluacion, que
# .dockerignore deja fuera del contexto principal y entra solo aquí desde el contexto adicional
# codigo_evaluacion (docker-compose.yml). Así las imágenes api y jobs no cambian.
FROM base AS evaluacion
USER root
COPY requirements-evaluacion.txt .
RUN pip install --no-cache-dir -r requirements-evaluacion.txt
COPY --from=codigo_evaluacion . ./app/evaluacion
ENV RAGAS_DO_NOT_TRACK=true
USER cdss
CMD ["python", "-m", "app.evaluacion", "--help"]

# API (target por defecto)
FROM base AS api
EXPOSE 8000
# --proxy-headers: toma la IP real del cliente que reenvía Nginx (auditoría)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
