# Mediciones del Sprint 2

Resumen de las mediciones de rendimiento. Los datos completos están en `data/mediciones/`,
que no se versiona.

## Parte B: recuperación

Mediciones del 05 y 06/11/2026 con las guías indexadas en la versión 3 (180 fragmentos
recuperables). Las dos primeras secciones resumen el motor ONNX int8 ya aplicado y el conjunto
de validación; las siguientes son el estudio con fp32 que llevó a elegirlo. Detalle por consulta
y por paso en `data/mediciones/b2_informe.md` (int8) y `data/mediciones/b_informe.md` (estudio).

### Motor ONNX int8 aplicado (06/11/2026)

Mediciones repetidas con el motor ONNX int8 ya integrado en el servicio `modelos`, el
diccionario con el concepto de clasificación o severidad de la anemia y los parámetros de la
migración 005 (8 candidatos de hasta 256 tokens). Detalle en `data/mediciones/b2_informe.md`.

**Latencia, 8 x 256, 30 consultas de latencia (p50 / p90):**

| Entorno | Embedding | Reranker | Total de la recuperación | Primera consulta tras reiniciar |
| --- | --- | --- | --- | --- |
| Normal (4 hilos) | 0,29 / 0,37 s | 3,20 / 3,28 s | 3,53 / 3,63 s | 4,80 s |
| B2ms (2 vCPU) | 0,41 / 0,54 s | 4,27 / 4,49 s | 4,76 / 5,09 s | 6,63 s |

BM25, ChromaDB, RRF y PostgreSQL siguen por debajo de 15 ms cada uno. La primera consulta
incluye la construcción del índice BM25 en el backend (1,1 s).

**Arranque del servicio `modelos`** (desde `up` hasta que responde `/salud`, que es cuando
Docker lo marca healthy):

| Motor del reranker | Entorno | Hasta healthy | Carga de modelos | Calentamiento del embedding | Calentamiento del reranker |
| --- | --- | --- | --- | --- | --- |
| ONNX int8 | Normal | 51 a 57 s | 14 a 16 s | 30 a 32 s | 3,0 a 3,3 s |
| ONNX int8 | B2ms | 63 s | sin desglose | sin desglose | sin desglose |
| fp32 | Normal | 75 a 78 s | 9 s | 23 s | 37 s |

La primera consulta real ya no paga el arranque en frío (antes 127 s en el entorno normal y
160 s en B2ms).

**Calidad con los mismos candidatos (int8 frente a fp32, 256 tokens):**

| Medida | fp32 | ONNX int8 |
| --- | --- | --- |
| Acierto top 5, 20 consultas de referencia, 8 candidatos | 95 % (19/20) | 95 % (19/20) |
| Acierto top 5, 20 consultas de referencia, 20 candidatos | 90 % (18/20) | 90 % (18/20) |
| Coincidencia del top 5 con fp32, 30 consultas de latencia (8 / 20 candidatos) | 100 % | **97 % / 97 %** |
| Coincidencia del top 5 con fp32, 20 de referencia (8 / 20 candidatos) | 100 % | 96 % / 94 % |
| Reranker de 20 x 256, entorno normal (p50 por consulta) | 16,6 s | 8,0 s |

Las 63 consultas medidas tuvieron exactamente los mismos candidatos en ambos motores. La
diferencia de puntaje por par tiene mediana 0,003 y p90 0,04. Solo RRF, sin reranker, acierta
80 %. Con el concepto nuevo de severidad, la R19 ya acierta; falla solo la R08 (la sección
esperada no llega a los 8 candidatos).

**UMBRAL_RELEVANCIA recalibrado con int8** (puntaje máximo por consulta, 8 x 256):

| Umbral | Consultas del dominio que lo alcanzan (50) | Fuera del dominio que lo alcanzan (13) |
| --- | --- | --- |
| 0,10 | 100 % | 15 % |
| **0,15** | **100 %** | 8 % (solo la gestante) |
| 0,20 | 98 % | 8 % |
| 0,30 | 90 % | 8 % |
| 0,60 (valor anterior) | 64 % | 8 % |

El máximo más bajo dentro del dominio es 0,169 (R14) y el más alto fuera, sin la gestante, es
0,102. El valor 0,15 queda entre ambos, con poco margen hacia arriba: se mantiene **0,15**.

**Memoria pico:** `modelos` 1919 MiB en B2ms (límite 4608 MiB) y 1976 MiB en el entorno normal,
que incluye la fase con fp32. El backend no pasa de 116 MiB. La exportación (`exportar-onnx`)
llega a su límite de 6 GiB, que en Docker incluye la caché de escritura del archivo, y terminó
bien en las dos ejecuciones (453 y 592 s, mismo SHA-256).

### Conjunto de validación

`consultas_validacion.yaml` tiene consultas nuevas, escritas después de fijar reglas, diccionario
y umbrales, y no se usó para ajustar nada: 15 de recuperación con su sección esperada (tomada de
los títulos de las guías, no de los resultados) y 30 del filtro de dominio (15 dentro y 15
fuera, incluidas 3 de manipulación con frases que las reglas no conocen). El filtro de dominio
se evalúa además sobre las 15 consultas de recuperación (45 casos en total).

| Medida | Consultas de ajuste | Conjunto de validación |
| --- | --- | --- |
| Acierto top 5, ONNX int8 8 x 256 | 95 % (19/20) | **47 % (7/15)** |
| Acierto top 5, ONNX int8 20 x 256 | 90 % (18/20) | 60 % (9/15) |
| Acierto top 5, solo RRF | 80 % (16/20) | 53 % (8/15) |
| Consultas que alcanzan UMBRAL_RELEVANCIA 0,15 | 50/50 | 14/15 |
| Filtro de dominio, exactitud con 0,65 | 85/85 | **44/45 (98 %)** |

- **Recuperación:** de los 8 fallos, en 4 (V07, V10, V11 y V12) la sección esperada no llega a
  los 20 candidatos de la fusión RRF y en 3 (V06, V09 y V14) queda entre las posiciones 9 y 13,
  fuera de los 8 que evalúa el reranker. El problema principal está en la primera etapa (BM25 y
  embeddings), no en el reranker. En V11 la respuesta del sistema es la modificación 6.1.3 E de
  la RM 429, que reemplaza justo el literal esperado de la NTS y no figura entre las esperadas:
  con ella serían 8 de 15. No se corrigió para no cambiar el conjunto después de ver el resultado.
- **Filtro de dominio:** el único error es «Niña de 8 años con anemia leve», que queda dentro
  porque las reglas de población no cubren a los niños de 5 a 11 años (la NTS sí los trata). Las
  tres consultas de manipulación nuevas no las detecta la regla, pero quedan fuera por similitud.

**Limitación de las muestras pequeñas.** Con 20 consultas de referencia cada una vale 5 puntos y
con 15 de validación, casi 7. El intervalo de confianza al 95 % (Wilson) de 7/15 va de 25 % a
70 %, y el de 19/20, de 76 % a 99 %. La diferencia entre ambos conjuntos es mayor que ese ruido:
indica que las 20 de referencia, escritas junto con el diccionario, sobrestiman la calidad. Antes
de cerrar el Sprint conviene ampliar el conjunto de validación con consultas escritas por el
equipo clínico y medir de nuevo, y revisar la primera etapa (más candidatos por método o una
expansión distinta) usando para el ajuste un conjunto distinto del de validación.

### Condiciones

- **Entorno normal:** Windows 11, Docker Desktop sobre WSL2, 8 CPU visibles, sin límite de CPU.
  PyTorch usa 4 hilos por defecto.
- **Perfil B2ms** (`docker-compose.b2ms.yml`): todos los servicios en los CPU 0 y 1 y límites de
  memoria que suman 7,06 GiB. PyTorch detecta los 2 CPU y usa 2 hilos por defecto, así que
  fijar `MODELOS_HILOS=2` no cambia nada (9,2 s y 10,3 s de p90 en el reranker con 8 x 256,
  dentro de la variación).
- **Calidad:** 20 consultas de referencia con su sección esperada (`consultas_referencia.yaml`,
  pendientes de revisión). Una consulta acierta si la sección esperada está en el top 5.
- **Latencia:** las consultas sintéticas de `consultas_latencia.yaml` (40 a 90 palabras), con
  dos de calentamiento. Fueron 10 por configuración en el entorno normal; en B2ms, 10 para 8
  candidatos y 5 para 20 x 1024 y 12 x 512, que superan el objetivo por más de 8 veces.
- **Rerankers alternativos:** se midieron en un contenedor aparte limitado a 2 CPU
  (`modelos/experimentos`), con los mismos candidatos que el reranker del servicio.

### Latencia por paso (p50 / p90)

Fuera del reranker, la recuperación tarda menos de 0,6 s incluso en B2ms. Con el modelo ya
cargado, el embedding de la consulta toma 0,4 s (normal) y 0,5 s (B2ms). BM25 tarda 2 ms,
ChromaDB 15 ms, la fusión RRF menos de 1 ms y cada comprobación en PostgreSQL 2 a 3 ms. El
índice BM25 se construye en 1,2 s la primera vez y se reutiliza mientras no cambie la base.

| Configuración (candidatos x tokens) | Reranker normal | Total normal | Reranker B2ms | Total B2ms |
| --- | --- | --- | --- | --- |
| 20 x 1024 (valores actuales) | 55,2 / 65,9 s | 55,6 / 66,4 s | 75,5 / 84,5 s | 76,0 / 85,0 s |
| 20 x 512 | 36,7 / 39,9 s | 37,1 / 40,2 s | | |
| 20 x 384 | 26,1 / 27,9 s | 26,4 / 28,3 s | | |
| 20 x 256 | 17,0 / 17,2 s | 17,3 / 17,5 s | | |
| 12 x 1024 | 32,0 / 39,5 s | 32,3 / 39,8 s | | |
| 12 x 512 | 21,7 / 22,5 s | 22,0 / 22,8 s | 28,7 / 30,2 s | 29,2 / 31,0 s |
| 12 x 384 | 15,6 / 16,3 s | 15,9 / 16,5 s | | |
| 12 x 256 | 10,2 / 10,5 s | 10,5 / 10,8 s | | |
| 8 x 1024 | 23,2 / 31,5 s | 23,5 / 31,8 s | | |
| 8 x 512 | 14,3 / 14,6 s | 14,7 / 15,0 s | | |
| 8 x 384 | 10,4 / 10,5 s | 10,7 / 10,8 s | 14,3 / 14,8 s | 14,8 / 15,4 s |
| 8 x 256 | 6,7 / 6,9 s | 7,0 / 7,3 s | 9,1 / 9,2 s | 9,5 / 9,8 s |

**Primera consulta en frío** (servicio `modelos` recién reiniciado, 20 x 1024): 127 s en el
entorno normal (35 s de embedding y 90 s de reranker) y 160 s en B2ms (40 s y 118 s). Después
de reiniciar `modelos` hace falta una consulta de calentamiento antes de abrir el servicio.

### Calidad frente a velocidad (bge-reranker-v2-m3 fp32)

| Candidatos x tokens | Acierto top 5 | Coincidencia del top 5 con 20 x 1024 |
| --- | --- | --- |
| 20 x 1024 | 80 % (16/20) | 100 % |
| 20 x 512 | 85 % (17/20) | 93 % |
| 20 x 384 | 90 % (18/20) | 85 % |
| 20 x 256 | 85 % (17/20) | 78 % |
| 12 x 1024 | 80 % (16/20) | 87 % |
| 12 x 512 | 85 % (17/20) | 80 % |
| 12 x 384 | 90 % (18/20) | 76 % |
| 12 x 256 | 85 % (17/20) | 71 % |
| 8 x 1024 | 80 % (16/20) | 78 % |
| 8 x 512 | 85 % (17/20) | 73 % |
| 8 x 384 | 90 % (18/20) | 72 % |
| 8 x 256 | 90 % (18/20) | 70 % |
| Solo RRF, sin reranker | 80 % (16/20) | 59 % |

Acortar los textos no empeora el acierto: lo mejora. Con 1024 tokens, los fragmentos largos
(tablas de 700 a 1000 tokens) dominan el puntaje aunque la parte relevante sea corta. La
coincidencia con 20 x 1024 baja porque cambian los fragmentos de las posiciones 3 a 5, no los
que aciertan. Con 8 x 256 fallan R08 y R19; con 20 x 1024, R01, R09, R18 y R19. La R19 (severidad según la
OMS) falla en todas las configuraciones porque la Tabla 3 de la OMS no llega a los 20
candidatos: al diccionario le falta el concepto «severidad» (propuesta en las dudas).

### Rerankers alternativos (2 CPU, mismos candidatos)

| Reranker | Tokens | Acierto top 5 (8 cand.) | Coincidencia del top 5 con fp32 (8 cand.) | Reranker p50 / p90, 8 candidatos |
| --- | --- | --- | --- | --- |
| bge-reranker-v2-m3 fp32 (servicio, B2ms) | 384 | 90 % | 100 % | 14,3 / 14,8 s |
| bge-reranker-v2-m3 fp32 (servicio, B2ms) | 256 | 90 % | 100 % | 9,1 / 9,2 s |
| bge-reranker-v2-m3 ONNX int8 | 384 | 85 % | 94 % (30 consultas de latencia) | 7,2 / 7,4 s |
| bge-reranker-v2-m3 ONNX int8 | 256 | 90 % | 96 % (20 de referencia) | 4,4 / 4,5 s |
| bge-reranker-v2-m3 ONNX int8, **4 CPU** | 256 | 90 % | 96 % (20 de referencia) | **3,2 / 3,3 s** |
| mmarco-mMiniLMv2-L12 fp32 (118 M parámetros) | 384 | 80 % | 75 % | 1,2 / 1,3 s |
| mmarco-mMiniLMv2-L12 ONNX int8 | 384 | 75 % | 73 % | 0,85 / 0,87 s |

ONNX int8 cumple el requisito de coincidir al menos 90 % con fp32 (91 % con 20 candidatos y
94 % con 8 en las 30 consultas de latencia, y 94 % y 96 % a 256 tokens en las 20 de
referencia) y es 2 veces más rápido. El reranker pequeño es rápido pero ordena peor que RRF
solo y no separa las consultas del dominio de las de fuera (máximo p10 dentro 0,07 frente a
p90 fuera 0,10), así que no sirve para el umbral. El modelo int8 pesa 0,57 GB frente a 2,27 GB.

### Memoria pico (docker stats durante las mediciones)

| Servicio | Normal | Límite normal | B2ms | Límite B2ms |
| --- | --- | --- | --- | --- |
| modelos | 1766 MiB | 5632 MiB | 1432 MiB | 4608 MiB |
| backend (proceso de medición) | 116 MiB | 512 MiB | 103 MiB | 512 MiB |
| chromadb | 66 MiB | 768 MiB | 117 MiB | 512 MiB |
| db | 33 MiB | 768 MiB | 35 MiB | 768 MiB |
| nginx | 6 MiB | 64 MiB | 5 MiB | 64 MiB |

El índice BM25 y el cliente de ChromaDB caben con holgura en los 512 MiB del backend. En B2ms
el uso real suma unos 1,7 GiB, muy por debajo de los 7,06 GiB de límites; `modelos` podría
bajar de 4,5 GiB si se adopta el modelo int8 (0,57 GB de pesos en lugar de 2,27 GB).

### Umbrales calibrados

**UMBRAL_RELEVANCIA** (puntaje máximo del reranker en cada consulta, 8 x 256):

| Umbral | Consultas de referencia que lo alcanzan (fp32 / int8) | Consultas fuera del dominio que lo alcanzan |
| --- | --- | --- |
| 0,15 | 20 de 20 / 20 de 20 | 1 de 13 (la de la gestante, que el filtro de dominio ya detiene) |
| 0,20 | 20 de 20 / 19 de 20 | 1 de 13 |
| 0,60 (valor actual) | 12 de 20 / 12 de 20 | 1 de 13 |

Fuera del dominio, el puntaje máximo no pasa de 0,11 salvo la consulta de la gestante (0,996,
la NTS sí trata ese tema). Con 0,60, 8 de las 20 consultas válidas irían a la búsqueda ampliada
o terminarían en evidencia insuficiente. Propuesta: **0,15**.

**UMBRAL_DOMINIO:** con las reglas de manipulación, de población fuera del alcance y de
términos del dominio (incluidos los sinónimos del diccionario como «chispitas» o
«sangrecita»), las 72 consultas del dominio quedan dentro y las 13 de fuera quedan fuera desde
0,65. La similitud solo decide las consultas sin términos del dominio; la más parecida de las
de fuera (neumonía en un niño) tiene 0,603. Propuesta: **0,65**. Es una calibración sobre el
mismo conjunto con el que se ajustaron las reglas, así que conviene revisarla con consultas
reales sintéticas nuevas antes de cerrarla.

### Tabla de decisión

Objetivo: reranker con p90 menor a 3,5 s en una VM de 2 vCPU (B2ms), con calidad aceptable
(acierto en el top 5 de al menos 0,8).

| Opción | Acierto top 5 | Reranker p90 B2ms | ¿Cumple 3,5 s en B2ms? | Observaciones |
| --- | --- | --- | --- | --- |
| 1. bge fp32, 20 x 1024 (actual) | 80 % | 84,5 s | No | 24 veces el objetivo |
| 1. bge fp32, menos candidatos y textos más cortos (8 x 256) | 90 % | 9,2 s | No | Mejor calidad, pero 2,6 veces el objetivo |
| 2. bge ONNX int8, 8 x 256 | 90 % | 4,5 s | No | Coincide 96 % con fp32; con 4 vCPU: 3,3 s |
| 3. Reranker pequeño (mmarco L12) | 75 a 80 % | 0,9 a 1,3 s | Sí | Peor que RRF solo y sin umbral útil |
| 4. Solo RRF, sin reranker | 80 % | 0 s (total 0,6 s) | Sí | Pierde 10 puntos y el puntaje de relevancia del umbral |

### Recomendación (05/11/2026)

1. **Reranker:** bge-reranker-v2-m3 en ONNX int8, con `CANDIDATOS_RERANKER = 8` y
   `MAX_LONGITUD_RERANKER = 256`. Mantiene la calidad de fp32 (90 % de acierto, 96 % de
   coincidencia) y es el único con puntajes que separan las consultas del dominio. Requiere
   agregar al servicio `modelos` un motor ONNX (no se implementó: espera tu aprobación).
2. **Servidor en Azure:** el resultado sí exige más CPU. Con 2 vCPU, ninguna opción con
   reranker baja de 3,5 s (la mejor, int8 8 x 256, queda en 4,5 s); con 4 vCPU, int8 8 x 256
   queda en 3,3 s. Se recomienda una VM de 4 vCPU y 16 GiB (por ejemplo B4ms o D4s_v5). Las
   B son de rendimiento ampliable: con los créditos de CPU agotados rinden por debajo de lo
   medido, así que para carga sostenida conviene la D4s_v5.
3. **Si el servidor sigue siendo B2ms:** int8 8 x 256 (4,5 s) supera el objetivo del reranker
   pero puede caber en el p90 total de 10 s si la generación es corta; se confirmará en D con la
   latencia completa. La alternativa sin reranker (solo RRF) cumple de sobra, pierde 10 puntos
   de acierto y obliga a cambiar la verificación 6.3, que hoy usa el puntaje del reranker.
4. **Umbrales:** `UMBRAL_RELEVANCIA = 0,15` y `UMBRAL_DOMINIO = 0,65`.
5. **Calentamiento:** una consulta de calentamiento al iniciar `modelos`, porque la primera en
   frío tarda de 2 a 3 minutos.

Aprobada el 06/11/2026: el motor ONNX int8, el calentamiento y los parámetros de la migración
005 están aplicados (ver «Motor ONNX int8 aplicado»). Los modelos del experimento con rerankers
alternativos se borraron de `data/modelos`; para repetir el paso 3 hay que prepararlos de nuevo.

### Cómo repetir las mediciones

Se ejecutan en Git Bash, desde la raíz del repositorio, con el sistema levantado, los modelos
descargados y las guías indexadas. Usan la imagen del backend con el código montado en solo
lectura y escriben en `data/mediciones/`. Los tiempos son los del equipo de desarrollo.

```bash
# 0. Variables (una vez por terminal de Git Bash)
APP="$(pwd -W)/backend/app:/app/app:ro"
MEDIR="python -m app.scripts.medir_recuperacion"
B2MS="-f docker-compose.yml -f docker-compose.b2ms.yml"
D=data/mediciones

# 1. Entorno normal                                                         (unas 2 h 30 min)
docker compose up -d
python backend/app/scripts/muestrear_memoria.py --salida $D/b_memoria_normal.json &    # terminar con: kill %1
MSYS_NO_PATHCONV=1 docker compose run --rm --no-deps -T -v "$APP" backend $MEDIR calidad --grupo referencia > $D/b_calidad.json                        # 45 min
MSYS_NO_PATHCONV=1 docker compose run --rm --no-deps -T -v "$APP" backend $MEDIR calidad --grupo fuera --longitudes 1024,384 > $D/b_calidad_fuera.json     # 18 min
MSYS_NO_PATHCONV=1 docker compose run --rm --no-deps -T -v "$APP" backend $MEDIR calidad --grupo latencia --longitudes 384 > $D/b_calidad_latencia.json    # 13 min
MSYS_NO_PATHCONV=1 docker compose run --rm --no-deps -T -v "$APP" backend $MEDIR dominio > $D/b_dominio.json                                           # 1 min
docker compose restart modelos        # para medir la primera consulta en frío; esperar a que esté healthy
MSYS_NO_PATHCONV=1 docker compose run --rm --no-deps -T -v "$APP" backend $MEDIR latencia --frio --consultas 10 > $D/b_latencia_normal.json              # 47 min
kill %1

# 2. Perfil B2ms                                                            (unos 25 min)
docker compose $B2MS up -d
python backend/app/scripts/muestrear_memoria.py --salida $D/b_memoria_b2ms.json &
MSYS_NO_PATHCONV=1 docker compose $B2MS run --rm --no-deps -T -v "$APP" backend $MEDIR latencia --entorno b2ms --frio --consultas 10   --configuraciones 8x384,8x256 > $D/b_latencia_b2ms.json                                                                             # 8 min
MSYS_NO_PATHCONV=1 docker compose $B2MS run --rm --no-deps -T -v "$APP" backend $MEDIR latencia --entorno b2ms --calentamiento 0 --consultas 5   --configuraciones 20x1024,12x512 > $D/b_latencia_b2ms_caras.json                                                                    # 10 min
MODELOS_HILOS=2 docker compose $B2MS up -d modelos
MSYS_NO_PATHCONV=1 docker compose $B2MS run --rm --no-deps -T -v "$APP" backend $MEDIR latencia --entorno b2ms-2-hilos --consultas 10   --configuraciones 8x256 > $D/b_latencia_b2ms_2hilos.json                                                                            # 3 min
kill %1

# 3. Rerankers alternativos, en un contenedor limitado a 2 CPU               (unas 1 h 15 min)
docker compose build modelos
docker build -t cdss-anemia-experimento-reranker modelos/experimentos
EXP="docker run --rm -e HF_HOME=/modelos/hf -v $(pwd -W)/data/modelos:/modelos -v $(pwd -W)/data/mediciones:/datos cdss-anemia-experimento-reranker"
MSYS_NO_PATHCONV=1 $EXP preparar onnx-int8          # 15 min; exporta y cuantiza (necesita unos 6 GB de memoria libre)
MSYS_NO_PATHCONV=1 $EXP preparar mmarco             # 3 min; descarga de Hugging Face
for v in onnx-int8 mmarco mmarco-onnx-int8; do
  MSYS_NO_PATHCONV=1 docker run --rm --cpuset-cpus 0,1 -e HF_HOME=/modelos/hf -e HF_HUB_OFFLINE=1     -v "$(pwd -W)/data/modelos:/modelos:ro" -v "$(pwd -W)/data/mediciones:/datos:ro"     cdss-anemia-experimento-reranker medir $v --longitud 384 --hilos 2 > $D/b_alternativa_$v.json
done                                                # 25 min
for c in "0,1:2" "0-3:4"; do
  MSYS_NO_PATHCONV=1 docker run --rm --cpuset-cpus "${c%%:*}" -e HF_HOME=/modelos/hf -e HF_HUB_OFFLINE=1     -v "$(pwd -W)/data/modelos:/modelos:ro" -v "$(pwd -W)/data/mediciones:/datos:ro" cdss-anemia-experimento-reranker     medir onnx-int8 --calidad /datos/b_calidad.json --longitud 256 --hilos "${c##*:}" --consultas-latencia 20     > $D/b_alternativa_onnx-int8_256_${c##*:}cpu.json
done                                                # 15 min

# 5. Motor ONNX int8 en el servicio (06/11/2026)                          (unos 55 min)
docker compose build modelos && docker compose run --rm exportar-onnx      # una vez, 8 a 10 min
docker compose up -d                                                      # modelos con int8; esperar healthy (unos 55 s)
python backend/app/scripts/muestrear_memoria.py --salida $D/b2_memoria_normal.json &
MSYS_NO_PATHCONV=1 docker compose run --rm --no-deps -T -v "$APP" backend $MEDIR calidad --grupo todas --longitudes 256 > $D/b2_calidad_int8.json         # 7 min
MSYS_NO_PATHCONV=1 docker compose run --rm --no-deps -T -v "$APP" backend $MEDIR calidad --grupo fuera --longitudes 256 > $D/b2_calidad_fuera_int8.json   # 2 min
MSYS_NO_PATHCONV=1 docker compose run --rm --no-deps -T -v "$APP" backend $MEDIR calidad --grupo validacion --longitudes 256 > $D/b2_validacion_int8.json  # 2 min
MSYS_NO_PATHCONV=1 docker compose run --rm --no-deps -T -v "$APP" backend $MEDIR dominio --conjunto validacion > $D/b2_validacion_dominio.json         # 1 min
docker compose up -d --force-recreate modelos                             # para medir la primera consulta tras reiniciar; esperar healthy
MSYS_NO_PATHCONV=1 docker compose run --rm --no-deps -T -v "$APP" backend $MEDIR latencia --entorno normal-int8 --frio --calentamiento 0 --consultas 30 --configuraciones 8x256 > $D/b2_latencia_int8_normal.json   # 2 min
MODELOS_RERANKER=fp32 docker compose up -d --force-recreate modelos       # fp32 para la coincidencia; esperar healthy
MSYS_NO_PATHCONV=1 docker compose run --rm --no-deps -T -v "$APP" backend $MEDIR calidad --grupo todas --longitudes 256 > $D/b2_calidad_fp32.json         # 15 min
MSYS_NO_PATHCONV=1 docker compose run --rm --no-deps -T -v "$APP" backend $MEDIR calidad --grupo fuera --longitudes 256 > $D/b2_calidad_fuera_fp32.json   # 4 min
kill %1
docker compose $B2MS up -d --force-recreate                               # int8 en B2ms; esperar healthy
python backend/app/scripts/muestrear_memoria.py --salida $D/b2_memoria_b2ms.json &
MSYS_NO_PATHCONV=1 docker compose $B2MS run --rm --no-deps -T -v "$APP" backend $MEDIR latencia --entorno b2ms-int8 --frio --calentamiento 0 --consultas 30 --configuraciones 8x256 > $D/b2_latencia_int8_b2ms.json   # 3 min
kill %1
docker compose up -d --force-recreate
cd backend && .venv/Scripts/python -m app.scripts.informe_recuperacion   --calidad ../$D/b2_calidad_int8.json --negativos ../$D/b2_calidad_fuera_int8.json --umbral-longitud 256 --umbral-candidatos 8   --base-fp32 ../$D/b2_calidad_fp32.json ../$D/b2_calidad_fuera_fp32.json --calidad-alternativas ../$D/b2_calidad_int8.json --longitud-alternativas 256   --latencia ../$D/b2_latencia_int8_normal.json ../$D/b2_latencia_int8_b2ms.json   --validacion-calidad ../$D/b2_validacion_int8.json --validacion-dominio ../$D/b2_validacion_dominio.json > ../$D/b2_informe.md; cd ..

# 4. Volver al entorno normal e informe detallado
docker compose up -d
cd backend && .venv/Scripts/python -m app.scripts.informe_recuperacion   --calidad ../$D/b_calidad.json --negativos ../$D/b_calidad_fuera.json --umbral-longitud 384   --base-fp32 ../$D/b_calidad.json ../$D/b_calidad_latencia.json ../$D/b_calidad_fuera.json   --calidad-alternativas ../$D/b_alternativa_onnx-int8.json ../$D/b_alternativa_mmarco.json ../$D/b_alternativa_mmarco-onnx-int8.json   --latencia ../$D/b_latencia_normal.json ../$D/b_latencia_b2ms.json ../$D/b_latencia_b2ms_caras.json ../$D/b_latencia_b2ms_2hilos.json   --dominio ../$D/b_dominio.json > ../$D/b_informe.md
```
