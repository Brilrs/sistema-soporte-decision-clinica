# Jobs (procesos fuera de línea)

El contenedor `jobs` usa la imagen del backend (destino `jobs` del `backend/Dockerfile`) y no
arranca con el resto del sistema. Agrupa los procesos que no forman parte de la atención en
tiempo real:

- `indexador` (Sprint 2): código en [`backend/app/indexador`](../backend/app/indexador).
- `evaluacion`: métricas RAGAS y CUE del OE3 (Sprint 2, parte posterior).
- `respaldo`: copia del índice de ChromaDB hacia Azure Blob Storage (Sprint 3).

## Indexador de guías

Se conecta a PostgreSQL con el usuario `cdss_indexador` (sin acceso a datos clínicos ni permiso
de eliminación), a ChromaDB y al servicio `modelos`. Lee los PDF de `./data/guias` (solo
lectura) y escribe los informes en `./data/mediciones`.

```bash
docker compose build jobs
docker compose run --rm jobs python -m app.indexador <comando> [opciones]
```

| Comando | Qué hace |
| --- | --- |
| `cargar --manifiesto fuentes_iniciales.yaml` | Calcula el SHA-256 de los PDF del manifiesto, actualiza la ruta y el hash de las filas ya sembradas de `documento_fuente` (sin crear duplicados) e indexa cada documento. `--solo rm251 rm429` limita a esas claves. |
| `procesar --documento <clave o id>` | Indexa un documento. `--archivo` indica otro PDF. |
| `comparar` | Informe de extracción en `data/mediciones/a2_extraccion.md`: páginas, tokens sospechosos del OCR, fragmentos, transcripciones, anclas, texto sustituido, tamaños y conflictos derivados. No escribe en la base. |
| `verificar-valores` | Lista de comprobación en `data/mediciones/verificacion_valores_criticos.md` (cada valor crítico, su transcripción, la página y la imagen) y página local `data/mediciones/verificacion.html`: imagen y texto de cada transcripción lado a lado, valores críticos resaltados, casilla y notas guardadas en el navegador y botón «Copiar resumen». |
| `trabajador` | Toma los trabajos `PENDIENTE` de `conocimiento.trabajo_indexacion` (`FOR UPDATE SKIP LOCKED`) cada 5 s. Lo usará la pantalla M11. `--una-vez` termina cuando no quedan pendientes. |

Opciones comunes:

- `--reindexar`: crea una versión nueva aunque el archivo no cambió (por ejemplo, después de
  verificar o corregir una transcripción). Sin ella, volver a cargar el mismo archivo no hace nada.
- `--permitir-no-verificadas`: **solo desarrollo**. Sin esta opción, un documento de nivel 1
  con transcripciones sin verificar queda en ERROR. Con ella se indexa y esos fragmentos quedan
  con `verificado = false`.
- `--falsos`: embeddings y tokens falsos, sin el servicio `modelos` (pruebas rápidas).

### Cómo funciona

1. **Extracción** con pdfplumber, recortando cada página a la zona del cuerpo (sin sellos ni
   firmas) y quitando encabezados y numeración repetidos. Solo se leen las páginas del cuerpo
   (`pagina_inicio_cuerpo` y `pagina_fin_cuerpo`): NTS 213 págs. 4 a 36, RM 429 págs. 4 a 11,
   OMS 2024 págs. 22 a 55 y OMS 2016 págs. 13 a 28 (sin resumen ejecutivo, referencias ni anexos). Un detector marca los tokens del OCR que
   esconden un símbolo perdido (`5.10.5`, `S 11.5`, `i11.0`, `2 11.5` en lugar de ≥).
2. **Transcripciones** (`transcripciones/<documento>/*.md`): las tablas y párrafos críticos se
   transcriben a mano y reemplazan la zona del texto extraído entre sus anclas. Cada archivo
   lleva en su encabezado `verificado_por` y `fecha_verificacion`, vacíos hasta la verificación.
3. **Mapa de modificaciones** (`modificaciones/rm429_2024.yaml`): el texto de la RM 251 que la
   RM 429 sustituye se guarda como fragmento no vigente con el motivo y el documento
   modificatorio. Cada modificación de la RM 429 es un fragmento propio con el encabezado
   "NTS 213 modificada por RM 429-2024/MINSA, numeral X". Si un ancla no aparece exactamente
   una vez, el documento queda en ERROR con el detalle.
4. **Fragmentación**: objetivo 500 tokens, máximo 800 y solapamiento 80 (parámetros del
   sistema), contados con `/tokens` del servicio `modelos`. Corta en apartados y numerales y
   nunca a mitad de frase. Cada tabla queda entera en un solo fragmento; la que supera los 1024
   tokens que admite el servicio `modelos` se parte por grupos de filas y cada parte repite el
   título y el encabezado de columnas.
5. **Indexación**: embeddings bge-m3, y luego una sola transacción en PostgreSQL. Los vectores
   se agregan a ChromaDB (colección `guias_clinicas`, distancia coseno) antes del commit. Si
   ChromaDB falla, no queda nada; si falla después, se borran esos vectores. El avance se
   escribe en `trabajo_indexacion` cada 16 fragmentos, en transacciones separadas.
6. **Versiones**: reindexar crea la versión N+1; los fragmentos anteriores pasan a no vigentes
   ("REINDEXADO") pero se conservan, así que las citas ya registradas siguen apuntando a su
   texto. ChromaDB solo guarda la versión vigente.

### Verificar las transcripciones

```bash
# Imágenes de las páginas (contenedor temporal, no forma parte de las imágenes del proyecto)
docker run --rm -v "$PWD/data/guias:/guias:ro" -v "$PWD/data/mediciones/paginas:/out" alpine:3.20 \
  sh -c "apk add --no-cache poppler-utils >/dev/null && \
         pdftoppm -r 120 -f 4 -l 11 -png /guias/NTS_213_RM429_2024_modificatoria.pdf /out/rm429 && \
         pdftoppm -r 120 -f 4 -l 36 -png /guias/NTS_213_RM251_2024.pdf /out/rm251"

docker compose run --rm jobs python -m app.indexador verificar-valores
```

Abra `data/mediciones/verificacion.html` con doble clic (o use la lista en Markdown), marque cada transcripción, complete
`verificado_por` y `fecha_verificacion` (AAAA-MM-DD) en cada transcripción y vuelva a indexar
con `cargar --reindexar --solo rm429 rm251`. Las transcripciones van dentro de la imagen, así que
antes de indexar hay que ejecutar `docker compose build jobs`; con la imagen anterior el documento
queda en ERROR por transcripciones sin verificar.

### Pruebas

```bash
cd backend
pytest -q              # CI: sin PDF ni modelos (embeddings, tokens y ChromaDB falsos)
pytest -q -m lenta     # PDF reales de data/guias y, con DATABASE_URL_INDEXADOR, los fragmentos indexados
```

Los textos de `backend/tests/datos` permiten probar las anclas en CI sin los PDF; se regeneran
si cambia la extracción.

Las pruebas lentas de la recuperación (`tests/test_rag_lento.py`: tasa de acierto de las 20
consultas de referencia y una consulta en español que recupera un fragmento en inglés de la
OMS) usan los modelos reales, que no tienen puerto publicado, así que se ejecutan dentro de la
red de Docker con el código montado (Git Bash, desde la raíz del repositorio):

```bash
PWD_GEN=$(grep '^CDSS_DB_PWD_GENERACION=' .env | cut -d= -f2-)
MSYS_NO_PATHCONV=1 docker compose run --rm -T \
  -e DATABASE_URL_GENERACION="postgresql+psycopg://cdss_generacion:${PWD_GEN}@db:5432/cdss" \
  -v "$(pwd -W)/backend:/app" -w /app jobs \
  sh -c "pip install -q --user pytest && python -m pytest -q -p no:cacheprovider -m lenta tests/test_rag_lento.py"
```

Las mediciones de rendimiento de la recuperación se describen en `docs/mediciones_sprint2.md`.
