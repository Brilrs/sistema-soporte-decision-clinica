# Servicio interno de modelos locales: bge-m3 (embeddings) y bge-reranker-v2-m3.
# PyTorch solo CPU; los pesos no se copian en la imagen: se leen de /modelos
# (carpeta ./data/modelos del equipo), descargada con descargar-modelos.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /srv

COPY requirements.txt requirements-ml.txt ./
RUN pip install --index-url https://download.pytorch.org/whl/cpu --extra-index-url https://pypi.org/simple \
        torch==2.6.0+cpu \
    && pip install -r requirements.txt -r requirements-ml.txt

COPY revisiones.json ./
COPY app ./app

# Usuario sin privilegios dentro del contenedor
RUN useradd --create-home cdss
USER cdss

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
