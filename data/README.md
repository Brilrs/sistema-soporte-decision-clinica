# data/

Carpeta local con archivos grandes o que no deben publicarse. Su contenido no se
versiona: Git solo sigue este README (regla `data/*` con la excepción
`!data/README.md` en `.gitignore`).

| Carpeta | Contenido | Quién la usa |
| --- | --- | --- |
| `guias/` | PDF originales de las guías clínicas de nivel 1: NTS 213-MINSA/DGIESP-2024 (RM 251-2024/MINSA), su modificatoria (RM 429-2024/MINSA) y las guías OMS 2024 y 2016 | Servicio `jobs` (indexador), montada en `/datos/guias` en solo lectura |
| `modelos/` | Pesos de bge-m3 y bge-reranker-v2-m3 en la revisión fijada en `modelos/revisiones.json` (unos 4,6 GB), dentro de `modelos/hf` | Servicio `modelos`, montada en `/modelos` en solo lectura; se llena una vez con `docker compose run --rm descargar-modelos` |
| `mediciones/` | Resultados de mediciones de memoria y tiempos (docker stats, latencias de recuperación y del reranker) | Scripts de medición del Sprint 2 |

`data/modelos` es una carpeta del equipo y no un volumen de Docker, así que
`docker compose down -v` no la borra. Los índices (PostgreSQL y ChromaDB) y los PDF
cargados desde la pantalla de base de conocimiento sí viven en volúmenes de Docker.
