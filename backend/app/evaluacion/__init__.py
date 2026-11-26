"""Trabajo de evaluación del OE3 (RAGAS y CUE). Diseño en docs/diseno_evaluacion_oe3.md.

No forma parte del sistema: no lo importa ninguna ruta ni servicio, y la imagen del backend no lo
incluye (backend/.dockerignore). Corre en la imagen y el perfil `evaluacion` de docker-compose.yml:

    docker compose --profile evaluacion run --rm evaluacion python -m app.evaluacion --help

Fases separadas: validar, ejecutar (una sola vez, con el grafo real), extraer (solo lectura),
juzgar (k repeticiones, con caché) e informe.
"""
