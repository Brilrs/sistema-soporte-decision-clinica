# Imagen solo para medir rerankers alternativos (parte B del Sprint 2). No forma parte
# del sistema ni de docker-compose.yml. Parte de la imagen del servicio modelos y agrega
# optimum y onnxruntime para exportar y cuantizar a ONNX int8.
#   docker compose build modelos
#   docker build -t cdss-anemia-experimento-reranker modelos/experimentos
FROM cdss-anemia-modelos
USER root
RUN pip install "optimum[onnxruntime]==1.24.0" "onnxruntime==1.20.1"
COPY reranker_alternativo.py /srv/experimentos/
USER cdss
ENTRYPOINT ["python", "/srv/experimentos/reranker_alternativo.py"]
