FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# Usuario sin privilegios dentro del contenedor
RUN useradd --create-home cdss
USER cdss

# Procesos fuera de línea (indexador de guías y evaluación). Se ejecutan con
# docker compose run --rm jobs python -m app.<módulo>
FROM base AS jobs
CMD ["python", "-c", "print('Indique el proceso: docker compose run --rm jobs python -m app.<módulo>')"]

# API (target por defecto)
FROM base AS api
EXPOSE 8000
# --proxy-headers: toma la IP real del cliente que reenvía Nginx (auditoría)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
