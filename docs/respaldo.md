# Respaldo de la base de conocimiento (Sprint 3, parte K)

Trabajo `python -m app.respaldo` (código en `backend/app/respaldo/`, imagen de jobs, usuario
`cdss_indexador`). Respalda la colección `guias_clinicas` de ChromaDB y las guías cargadas desde
M11, restaura en una colección vacía y comprueba una colección contra PostgreSQL. No necesita
ninguna migración: `cdss_indexador` ya tiene SELECT en `conocimiento` e INSERT en la bitácora.

## Qué se respalda y qué no

| Qué | ¿Entra? | Cómo |
| --- | --- | --- |
| Colección `guias_clinicas` de ChromaDB | Sí | Por la API de ChromaDB: ids, vectores, textos y metadatos de cada vector, y los metadatos de la colección (la distancia coseno, `hnsw:space`). No se copian los archivos del volumen `datos_chroma` |
| Guías cargadas desde M11 (volumen `datos_guias_cargadas`) | Sí | Copia de cada PDF con su SHA-256 |
| Guías de nivel 1 de `./data/guias` | No | Son archivos del equipo, fuera de Docker; se respaldan con la carpeta del proyecto |
| PostgreSQL | No | En Azure tiene respaldo automático y restauración a un punto en el tiempo. En desarrollo, `pg_dump` (abajo) |
| Pesos de los modelos (`./data/modelos`) | No | Se vuelven a descargar con `descargar-modelos` |

Exportar por la API, y no copiar el volumen, da un respaldo independiente de la versión interna de
ChromaDB y de su formato en disco, que se puede comprobar archivo por archivo y restaurar en otra
colección para compararla con la original.

## Formato

Cada respaldo es una carpeta `respaldo_AAAAMMDD_HHMMSS` (hora de Perú) dentro del destino:

| Archivo | Contenido |
| --- | --- |
| `coleccion.json` | Nombre y metadatos de la colección (`{"hnsw:space": "cosine"}`) |
| `vectores.jsonl` | Un vector por línea, ordenados por id: `id`, `vector`, `texto` y `metadatos`. Los floats se escriben con la representación exacta de Python: el archivo guarda exactamente lo que devolvió ChromaDB (ver «Normalización de ChromaDB con coseno») |
| `guias_cargadas/` | Los PDF del volumen `datos_guias_cargadas` |
| `manifiesto.json` | Fecha, versión del código (`CDSS_VERSION_CODIGO` o git) y huella SHA-256 de `backend/app`, versión de ChromaDB, modelo de embeddings, número de vectores y de vigentes, vectores por nivel, guías con su SHA-256, si se forzó y cuántos trabajos había activos, y la lista de archivos con su tamaño y SHA-256 |
| `manifiesto.json.sha256` | El SHA-256 del manifiesto |

## Comandos

Desde la raíz del repositorio, con el stack levantado. La primera vez, y después de cambiar el
código: `docker compose build respaldo respaldo-guias`.

| Comando | Qué hace |
| --- | --- |
| `docker compose run --rm respaldo python -m app.respaldo verificar` | Solo lectura. Comprueba la colección contra PostgreSQL: ids iguales a los fragmentos de la última versión de cada documento (sin faltantes ni huérfanos), vigencia igual a `fragmento.vigente`, `estado_documento` y `nivel` iguales a `documento_fuente`, y distancia coseno. Imprime vectores, vigentes, por nivel y por estado. `--coleccion NOMBRE` para otra colección |
| `docker compose run --rm respaldo python -m app.respaldo crear` | Crea `data/respaldos/respaldo_AAAAMMDD_HHMMSS`. Se niega si hay trabajos de indexación pendientes o en curso (la instantánea no sería coherente); `--forzar` respalda igual y lo anota en el manifiesto. `--conservar N` (7 por omisión) borra los respaldos más antiguos de ese mismo destino |
| `docker compose run --rm respaldo python -m app.respaldo restaurar respaldo_AAAAMMDD_HHMMSS --coleccion guias_clinicas_prueba_restauracion` | Comprueba primero todos los SHA-256 y el manifiesto (si algo no coincide, se niega sin escribir nada). Crea la colección con los metadatos originales, carga los vectores, comprueba que los ids, textos y metadatos quedaron idénticos y los vectores dentro de la tolerancia de 1e-6 (informa la diferencia máxima), y verifica la colección contra PostgreSQL. Sin `--coleccion` restaura en `guias_clinicas`, solo si no existe o está vacía |
| `docker compose run --rm respaldo-guias python -m app.respaldo restaurar respaldo_AAAAMMDD_HHMMSS --con-guias` | Igual, y además copia al volumen los PDF que faltan (con el volumen en escritura). Un archivo que ya existe con otro contenido no se sobrescribe: se informa |
| `docker compose run --rm respaldo python -m app.respaldo comparar guias_clinicas guias_clinicas_prueba_restauracion` | Comprueba que dos colecciones coinciden: metadatos de la colección, ids, textos y metadatos idénticos, vectores dentro de la tolerancia de 1e-6 (informa la diferencia máxima), y que 5 consultas con vectores guardados devuelven los mismos 5 primeros resultados en el mismo orden |
| `docker compose run --rm respaldo python -m app.respaldo descartar-coleccion guias_clinicas_prueba_restauracion` | Borra una colección de prueba. Solo acepta nombres que empiezan con `guias_clinicas_prueba_`: nunca borra `guias_clinicas` |

`restaurar` acepta el nombre de un respaldo del destino o una carpeta dentro de `data/respaldos`
(por ejemplo, una copia). Código de salida: 0 si todo está bien, 1 si algo falla, no coincide o se
niega (con el motivo en la salida de errores), 2 si los argumentos no son válidos. Así se puede
programar y vigilar.

Cada `crear` y `restaurar` deja un evento en la bitácora (RESPALDO_CREADO y RESPALDO_RESTAURADO,
entidad `respaldo`, id el nombre del respaldo) con conteos, el destino y si se forzó. Sin datos
personales, títulos, nombres de archivos ni rutas del servidor.

### Antes de congelar el sistema para el OE3

Ejecutar `verificar` y guardar su salida junto a la huella de configuración
(`python -m app.scripts.huella_configuracion`). Debe decir «Coincide con PostgreSQL». Después, un
`crear` deja la base de conocimiento congelada en un respaldo con su manifiesto.

## Normalización de ChromaDB con coseno

Con distancia coseno, ChromaDB (su índice hnswlib) normaliza cada vector al guardarlo: acumula la
norma en float32 y multiplica cada componente por su inverso. Los vectores de bge-m3 ya son
unitarios, pero al volver a normalizarlos en float32 cambia el último dígito de algunos componentes
(en la colección real, diferencias de unos 1e-8 a 3e-8 por componente). Por eso un vector restaurado
no es bit a bit el exportado, y la igualdad exacta es imposible por la API de ChromaDB.

`restaurar` y `comparar` comparan los ids, los textos y los metadatos de forma exacta, y los vectores
componente a componente, con la misma longitud y una tolerancia absoluta de **1e-6**
(`TOLERANCIA_VECTOR` en `backend/app/respaldo/operaciones.py`): unas 30 veces la diferencia que
produce la normalización, y muy por debajo de cualquier cambio real de un vector. Ambos informan la
diferencia máxima observada. Un vector fuera de la tolerancia sigue siendo un error. Esa diferencia
no cambia los resultados de las consultas: `comparar` lo comprueba con 5 consultas, que deben
devolver los mismos 5 primeros ids en el mismo orden (comparación exacta).

## Si restaurar falla a mitad

Las comprobaciones de los SHA-256 y del manifiesto se hacen antes de escribir: si fallan, no se
escribe nada. La comprobación posterior (lo restaurado frente al respaldo) se hace después de cargar
los vectores: si falla, la colección **ya quedó escrita y no se borra sola**. El mensaje lo dice. Si
es una colección de prueba, se limpia con
`docker compose run --rm respaldo python -m app.respaldo descartar-coleccion guias_clinicas_prueba_...`;
si fue `guias_clinicas` (solo cuando estaba vacía), vaciar ChromaDB como en «Orden de restauración»
antes de repetir.

## Destino Azure Blob

`--destino blob` en `crear` y `restaurar`. Sube los mismos archivos bajo el prefijo
`respaldo_AAAAMMDD_HHMMSS/` del contenedor; al subir, vuelve a bajar cada archivo y compara su
SHA-256; al bajar, comprueba el manifiesto y cada archivo antes de restaurar. La retención funciona
igual, solo sobre los prefijos de respaldos.

| Variable | Uso |
| --- | --- |
| `RESPALDO_CONTENEDOR_BLOB` | Nombre del contenedor (obligatoria) |
| `AZURE_STORAGE_CONNECTION_STRING` | Cadena de conexión de la cuenta (desde Key Vault) |
| `AZURE_STORAGE_ACCOUNT_URL` | Sin cadena de conexión: URL de la cuenta (`https://<cuenta>.blob.core.windows.net`) con la identidad administrada de la máquina |
| `AZURE_CLIENT_ID` | Solo si la máquina tiene más de una identidad administrada |

Dependencias `azure-storage-blob` y `azure-identity`, solo en la imagen de jobs. Las pruebas usan un
cliente simulado; **la prueba real contra Azure se hace en la parte L.**

## Retención

`--conservar N` (7 por omisión, mínimo 1), después de un respaldo completo. Solo borra, en ese mismo
destino, carpetas (o prefijos de Blob) con el nombre exacto `respaldo_AAAAMMDD_HHMMSS`; nunca otras
carpetas, archivos ni otros destinos. Un respaldo que falla a mitad se borra y no cuenta.

## Orden de restauración

PostgreSQL primero, después ChromaDB y al final verificar:

1. **PostgreSQL.** En Azure, restauración a un punto en el tiempo (parte L). En desarrollo, con el
   respaldo de `pg_dump` (abajo).
2. **ChromaDB vacía.** En desarrollo: `docker compose stop chromadb backend indexador`,
   `docker volume rm cdss-anemia_datos_chroma` y `docker compose up -d chromadb`. Al arrancar, el
   backend o el indexador pueden crear `guias_clinicas` vacía y con distancia coseno: `restaurar` la
   acepta porque está vacía y tiene los mismos metadatos.
3. **Restaurar:** `docker compose run --rm respaldo-guias python -m app.respaldo restaurar
   respaldo_AAAAMMDD_HHMMSS --con-guias` (sin `--coleccion`).
4. **Verificar:** `restaurar` ya imprime la comprobación; `verificar` la repite. Si PostgreSQL es de
   otro momento que el respaldo de ChromaDB, aparecen faltantes o huérfanos: hay que reindexar los
   documentos afectados desde M11 o usar respaldos del mismo momento.
5. `docker compose up -d` para levantar el resto.

## PostgreSQL en desarrollo (`pg_dump`)

El anexo A de `docs/cierre_sprint2.md` respaldó solo los esquemas `conocimiento` y `auditoria`
antes de una limpieza puntual. Para un respaldo completo de la base de desarrollo (funciona igual en
PowerShell y en Git Bash, porque el archivo se escribe dentro del contenedor y luego se copia):

```bash
docker compose exec db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc -f /tmp/cdss.dump'
docker compose cp db:/tmp/cdss.dump data/respaldos/pg_AAAAMMDD.dump
```

Restaurar (borra y vuelve a crear los objetos; con el backend y el indexador detenidos):

```bash
docker compose stop backend indexador
docker compose cp data/respaldos/pg_AAAAMMDD.dump db:/tmp/cdss.dump
docker compose exec db sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists /tmp/cdss.dump'
```

El nombre `pg_AAAAMMDD.dump` no cumple el patrón de los respaldos de ChromaDB, así que la retención
de `crear` nunca lo borra.

## Programarlo en Azure (parte L)

En la máquina B2ms, un temporizador de systemd (o cron) que ejecute cada noche
`docker compose run --rm respaldo python -m app.respaldo crear --destino blob --conservar 14`, con
las variables de Blob desde Key Vault, y que avise si el código de salida no es 0. Si coincide con
una indexación, el comando se niega (código 1) y el siguiente intento lo hace. Una vez por semana,
`verificar`.

## Qué hacer ante cada error

| Mensaje | Qué hacer |
| --- | --- |
| «Hay N trabajos de indexación pendientes o en curso» | Esperar a que terminen (M11) y repetir. `--forzar` solo si no se puede esperar; el manifiesto lo anota |
| «Ya existe el respaldo …» | Dos respaldos en el mismo segundo: repetir |
| «La colección guias_clinicas ya tiene N vectores: no se sobrescribe ni se borra» | Restaurar en otro nombre con `--coleccion guias_clinicas_prueba_...`, o vaciar ChromaDB como en «Orden de restauración» |
| «existe vacía pero con otros metadatos» | La colección se creó con otra distancia. En desarrollo, vaciar ChromaDB y repetir |
| «no coincide con el manifiesto», «Falta el archivo …», «El manifiesto no coincide con su SHA-256» | El respaldo está alterado o incompleto: no se escribió nada. Usar otro respaldo |
| «La colección restaurada no coincide con el respaldo (N vectores distintos …). La colección … ya quedó escrita y no se borra sola …» | La colección quedó escrita (ver «Si restaurar falla a mitad»). Descartarla si es de prueba y revisar la versión de ChromaDB antes de repetir |
| «… ya existe con otro contenido; no se sobrescribió» | Comparar el PDF del volumen con el del respaldo antes de decidir; el comando no lo cambia |
| «NO COINCIDE: …» en `verificar` | Faltantes o huérfanos: reindexar el documento desde M11. Vigencia o estado distintos: un trabajo de retiro o de indexación quedó a medias; revisar M11 y reintentar |
| «Solo se pueden descartar colecciones de prueba» | Es la barrera esperada: `guias_clinicas` nunca se borra con este comando |
| «Falta RESPALDO_CONTENEDOR_BLOB» u otro de Blob | Revisar las variables de Blob |

## Pruebas

`backend/tests/test_k_respaldo.py`, con colecciones en memoria (`ServidorMemoria`), carpetas
temporales, un cliente de Blob simulado y guías sintéticas `PRUEBA-K-...` en la base de pruebas. La
prueba con ChromaDB real (marca `chroma_real`) no corre en el CI; localmente, con ChromaDB
levantado:

```bash
cd backend
CHROMA_URL_PRUEBAS=http://localhost:8001 pytest -m chroma_real tests/test_k_respaldo.py
```

Usa 200 vectores unitarios aleatorios de 1024 dimensiones (como bge-m3, para que pasen por el
índice HNSW y su normalización) en colecciones `guias_clinicas_prueba_k…` que descarta al terminar,
y comprueba que la colección real conserva su número de vectores. Las pruebas en memoria usan
`ServidorMemoria(normalizar_como_chroma=True)`, que normaliza en float32 al agregar como ChromaDB.
