# Mediciones del Sprint 2

Resumen de las mediciones de rendimiento. Los datos completos están en `data/mediciones/`,
que no se versiona.

## Parte D2: API de consultas por etapas (13/11/2026)

Comprobaciones hechas sin la API de Anthropic:

- **Pruebas:** 608 pruebas sin marca (incluidas las 27 de `test_d2_api.py`, con el cliente falso)
  y las 62 lentas, con la base de pruebas.
- **Formato:** cada línea del stream es un evento válido del contrato (`EventoConsulta`).
- **Cierre de la conexión:** el cliente cierra después del primer evento (validar) y la consulta
  termina en el servidor como VERIFICADA, con sus tiempos y sin transacciones abiertas.
- **Nginx:** `nginx -t` sin errores con el `location` de stream. A través de Nginx, el paciente
  inexistente responde 404, la consulta inexistente 404 y `admin.cdss` 403.

### Stream a través de Nginx (13/11/2026)

`comprobar_stream --confirmo-llamada-real`, ejecutado por el responsable contra `http://nginx`,
con una consulta VERIFICADA de la paciente ficticia de DNI 81345678 y la API real. Se considera
por etapas si las líneas llegan en tres momentos distintos o más y entre la primera y la
última pasa al menos un segundo.

- `Content-Type: application/x-ndjson`: 9 líneas en 8 momentos distintos, del primer evento a
  los 0,31 s al último a los 11,19 s. **Por etapas: sí.**
- Llegada al cliente frente a la hora del servidor: validar 313 / 299 ms, recuperar 4 788 /
  4 775 ms, generar 11 118 / 11 105 ms, `fin` 11 188 / 11 175 ms. Cada línea llega de 13 a 14 ms
  después de que el servidor la escribe: Nginx no guarda la respuesta en un búfer.

Resultado en `data/mediciones/d2_stream_nginx.json`.

### Corrida con el modelo real en el perfil B2ms (13/11/2026)

`medir_consulta --llm real --confirmo-datos-sinteticos --entorno b2ms --etiqueta b2ms_real` con
`docker-compose.b2ms.yml` (todos los servicios en las CPU 0 y 1), ejecutada después del
calentamiento (reranker 1, LLM 4). Prompt v1.1, una repetición.

| Medida | B2ms | Perfil normal (parte D1) |
| --- | --- | --- |
| Estados como se esperaba | 12 de 12 | 12 de 12 |
| Intentos enviados | 11 | 11 |
| Primer evento p50 / p90 | 0,35 / 0,48 s | 0,23 / 0,27 s |
| Total p50 / p90 (todas) | 12,33 / 18,25 s | 11,76 / 12,54 s |
| Total de las verificadas p50 / p90 | 12,66 / 18,92 s; de 11,58 a 18,92 s | 11,79 / 12,54 s |
| Recuperar, mediana | 4,72 s | 3,93 s |
| Generar, mediana | 6,90 s | 7,41 s |
| Costo | 0,24168 USD | 0,24004 USD |
| Tokens de entrada / salida | 71 881 / 9 790 | 71 881 / 9 626 |

- **Caso d:** 18,92 s. La llamada a la API tardó 13,50 s con 1 099 tokens de salida; en los otros 8
  casos verificados tardó de 6,57 a 8,37 s, con 720 a 1 234 tokens. La recuperación del caso d
  tardó 5,00 s, como en los demás (4,55 a 5,00 s). Sin el caso d, el total de las verificadas va de
  11,58 a 14,18 s.
- **Caso j** (reintento con búsqueda ampliada, dos llamadas): 18,25 s, dentro de los 25 s del RNF3
  con reintento. La recuperación ampliada tardó 6,30 s.
- **RNF3, flujo normal** (p90 menor a 10 s): en B2ms el p90 de las verificadas es 18,92 s, y la
  mediana, 12,66 s. No se cumple. Recuperar es 0,8 s más lento que en el perfil normal; la
  llamada a la API no depende del perfil.

Informe en `data/mediciones/d_consulta_real_b2ms_real.md` y `.json`.

### Prompt v1.2 frente a v1.1 (13/11/2026)

`medir_consulta --llm real --confirmo-datos-sinteticos --versiones-prompt v1.1,v1.2`, ejecutada por el
responsable: los 12 casos con cada versión, perfil normal, una repetición. La versión se cambió
solo en memoria; `VERSION_PROMPT` siguió en v1.1.

| Medida | v1.1 | v1.2 |
| --- | --- | --- |
| Estados como se esperaba | 12 de 12 | 12 de 12 (los mismos) |
| Tokens de salida por intento enviado, media / p50 | 863 / 933 | 728 / 820 |
| Generar p50 / p90 | 7,18 / 7,73 s | 6,50 / 7,02 s |
| Total p50 / p90 | 11,58 / 13,50 s | 10,64 / 11,71 s |
| Costo de los 12 casos | 0,239 USD | 0,227 USD |

Comparación de los textos de los 9 casos verificados (`app/scripts/comparar_prompts.py`, sin
llamar a la API; informe en `data/mediciones/comparacion_prompts_v1_1_v1_2.md`):

- **Dosis:** ninguna dosis del texto de v1.1 falta en v1.2. En e y k, v1.2 agrega la dosis
  calculada con el peso (29,7 mg/día con 9,9 kg).
- **Caso d (anemia severa):** v1.2 pone el paso de TRATAMIENTO antes que el de DERIVACION, y v1.1
  los pone al revés. v1.2 omite el incremento ≥ 1 g/dL a los 30 días (F-02, que deja de citar) y
  la advertencia «La decisión final corresponde al profesional tratante».
- **Caso f:** v1.2 omite «Al concluir el tratamiento se inicia la suplementación preventiva según
  edad» y la advertencia de que la recomendación de la OMS es preventiva y no aplica al
  tratamiento.
- **Caso l:** v1.2 omite la advertencia sobre la diferencia entre la OMS y la norma nacional (6 y
  3 meses según la edad).

**Decisión (13/11/2026): v1.2 no se adopta y v1.1 sigue vigente.** v1.2 baja 0,7 s la mediana de
generar y 1,8 s el p90 total, pero omite contenido clínico de los casos d, f y l. Tampoco alcanza
el RNF3: su p90 de 11,71 s sigue por encima de los 10 s. `clinico_v1_2.md` queda marcado como
experimental, y `configuracion_generacion` rechaza una versión experimental como `VERSION_PROMPT`.

**Hallazgo: las advertencias no se verifican contra las fuentes.** En el caso l, v1.2 advierte
que «la NTS 213 acepta además … micronutrientes en polvo como alternativas». El texto sí aparece
en un fragmento enviado al modelo, pero con dos diferencias:
- El fragmento es F-04 (RM 429-2024/MINSA, numeral 6.1.1 B, Tabla 8, modificación N.° 7), no la
  NTS 213.
- La fila es la de 24 a 35 meses. Para la paciente de 49 meses (36 a 59 meses), la misma tabla
  indica 30 mg de hierro elemental en jarabe.

El control 6.1 comprueba las etiquetas y los extractos de las citas, y 6.2 las dosis y la
clasificación. Ninguno compara el contenido de las advertencias con los fragmentos.

## Parte D1: grafo de la consulta (13/11/2026)

Los 12 casos de `casos_e2e.yaml` por el grafo de LangGraph y el servicio de consultas
(`app/scripts/medir_consulta.py`), con el cliente falso del modelo de lenguaje: el tiempo de la
llamada al modelo no está incluido. Versión 5 de las guías, `BONIFICACION_EDAD` 0,7, reranker
ONNX int8 de 8 candidatos de 256 tokens. Tres repeticiones por perfil, una consulta a la vez,
con el calentamiento previo. El total es el que ve el cliente del servicio, desde la solicitud
hasta el evento «fin».

| Perfil | Coinciden | Total p50 / p90 | Verificadas p50 / p90 | Primer evento p50 / p90 | Límites |
| --- | --- | --- | --- | --- | --- |
| Normal (8 núcleos visibles, modelos con 4 hilos) | 36/36 | 3,95 / 4,19 s | 3,97 / 4,09 s | 0,20 / 0,24 s | reranker 2, LLM 4 |
| B2ms (2 CPU) | 36/36 | 5,63 / 6,28 s | 5,67 / 6,05 s | 0,33 / 0,47 s | reranker 1, LLM 4 |

Mediana por nodo (ms):

| Perfil | validar | clasificar | normalizar | recuperar | proteger | generar | verificar |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Normal | 203 | 2 | 8 | 3699 | 5 | 2 | 19 |
| B2ms | 326 | 2 | 7 | 5295 | 5 | 1 | 14 |

- **La recuperación es casi todo el tiempo** (reranker incluido). Los demás nodos suman menos de
  medio segundo: el filtro de dominio de validar (un embedding) y los registros en PostgreSQL.
- **Frente a la parte C:** la recuperación de 8 x 256 medía 3,75 / 3,88 s en el perfil normal y
  5,03 / 5,48 s en B2ms (parte C2); el grafo agrega el filtro de dominio y los registros, unos
  0,2 a 0,3 s. Con el modelo real hay que sumar la llamada a la API: en la corrida real de C2
  (versión 5, 12 de 12), de 3,8 a 8,5 s por intento, con un total de 11,1 a 17,8 s en las
  verificadas. **Riesgo para RNF3** (p90 menor a 10 s en el flujo normal): recuperación más
  llamada al modelo ya lo superan en el perfil normal; la corrida real por el grafo lo confirma
  (ver «Corrida con el modelo real»).
- **Primer evento:** sale al terminar validar (la consulta ya registrada, con su id), a los 0,2 s en
  el perfil normal y 0,3 s en B2ms.
- **El caso j** recorre dos veces recuperar (búsqueda ampliada) y es el máximo de cada perfil
  (8,62 s y 13,71 s).
- **Primera consulta en frío en B2ms** (sin calentamiento, caso b): 13,60 s, de
  los cuales 6,47 s son el filtro de dominio (embeddings de las
  consultas de referencia) y 7,01 s la recuperación (índice BM25
  y primer reranker). Con el calentamiento al arrancar (en segundo plano, con reintentos hasta que
  `modelos` responde; en B2ms terminó en el intento 12, unos 60 s después de arrancar) la primera
  consulta ya no paga ese costo.
- **Concurrencia:** con 4 consultas a la vez en el perfil normal (límite 2 en el servicio modelos)
  hubo 14 eventos «en_cola», una espera máxima de 7,90 s y un total p50 / p90
  de 8,26 / 15,76 s; los 12 casos dieron el estado esperado.
- **Memoria del backend:** 180 MiB después del calentamiento con LangGraph (antes, 80 MiB en reposo),
  dentro de los 512 MiB de `mem_limit`.

Valores por defecto de la concurrencia, confirmados el 13/11/2026: `MAX_CONCURRENCIA_RERANKER`
automático (núcleos visibles / hilos de `modelos`: 2 en el perfil normal y 1 en B2ms) y
`MAX_CONCURRENCIA_LLM` = 4.

Informes en `data/mediciones/d_consulta_falso_normal.md`, `_b2ms.md`, `_b2ms_frio.md` y
`_normal_4a_la_vez.md`.

### Corrida con el modelo real (13/11/2026)

`medir_consulta --llm real --confirmo-datos-sinteticos --repeticiones 1 --entorno normal
--etiqueta v1_real`, ejecutada por el responsable: los 12 casos por el grafo con
`claude-sonnet-5-5`, prompt v1.1, `MAX_TOKENS_SALIDA` 1500, perfil normal (reranker 2, LLM 4),
una consulta a la vez y con el calentamiento previo. Es la referencia del grafo.

| Medida | Resultado |
| --- | --- |
| Casos con el estado esperado | 12 de 12 (9 VERIFICADA, 1 EVIDENCIA_INSUFICIENTE, 1 DATOS_FALTANTES, 1 FUERA_DE_DOMINIO) |
| Intentos enviados al modelo | 11 (uno por caso verificado y dos en el caso j) |
| Primer evento p50 / p90 | 0,23 / 0,27 s |
| Total p50 / p90 (todas) | 11,76 / 12,54 s; máximo 17,54 s (caso j, con reintento) |
| Total de las verificadas | p50 11,79 s, p90 12,54 s; de 11,24 a 12,54 s |
| Costo | 0,24004 USD; 0,024 USD por consulta con llamada al modelo |
| Tokens | 71 881 de entrada y 9 626 de salida; 0 de razonamiento |

Mediana por nodo (ms): validar 222, clasificar 2, normalizar 11, recuperar 3 928, proteger 5,
generar 7 407, verificar 32.

- **Generar** (llamada a la API) es el 63 % del total en la mediana de las verificadas: de 6,80 a
  8,14 s en los 9 casos verificados. **Recuperar** es el 33 %: de 3,78 a 4,09 s. Los demás nodos suman
  menos de 0,4 s.
- **Tokens por intento verificado:** de 5 863 a 7 238 de entrada y de 764 a 1 134 de salida. En el
  caso j, cada intento produjo unos 360 tokens de salida y la llamada tardó 4,0 s.
- **RNF3, flujo normal** (p90 menor a 10 s): p90 de 12,54 s con respuesta completa en el perfil
  normal, 2,54 s por encima. No se cumple. Recuperar (3,9 s) más generar (7,4 s) ya suman 11,3 s.
- **RNF3, con reintento** (máximo 25 s): el caso j, con búsqueda ampliada y dos llamadas, tardó
  17,54 s. Se cumple.
- **Frente a la parte C2** (corrida real con `prueba_punta_a_punta`, sin el grafo): 12 de 12, 12
  intentos enviados, 0,26097 USD y un total de 11,1 a 17,8 s en las verificadas. El grafo no agrega
  tiempo apreciable: validar, clasificar, normalizar, proteger y verificar suman unos 0,27 s.

Informe en `data/mediciones/d_consulta_real_v1_real.md` y `.json`.

### Pendientes para D2

- Probar un prompt compacto v1.2 que acorte la salida (hoy de 764 a 1 134 tokens por respuesta
  verificada), para bajar el tiempo de generar y acercar el p90 al objetivo del RNF3.
- Medir con la API real en el perfil B2ms (`medir_consulta --llm real` con
  `docker-compose.b2ms.yml`), donde recuperar tarda 5,3 s de mediana con el cliente falso.

## Parte C2: grupo etario, versión 5 y bonificación por edad (12/11/2026)

Mediciones sin la API de Anthropic: recuperación real (modelos, ChromaDB y PostgreSQL) y, en la
prueba de punta a punta, el cliente falso del modelo de lenguaje. Reranker ONNX int8, 8
candidatos de 256 tokens, 20 por método, k 60, `UMBRAL_RELEVANCIA` 0,15. El peso de la
bonificación se aplicó en memoria en cada corrida. `BONIFICACION_EDAD` se registró en 0 con la
migración 008; desde el 13/11/2026 vale 0,7 (migración 009, ver «Elección del peso»).

### Versión 5

Reindexación del 12/11/2026 (`cargar --reindexar`, unos 8 minutos). Cambios respecto a la versión 4:

- **Tabla N° 20 de la NTS** (control de hemoglobina en el tratamiento) transcrita y verificada
  contra la imagen (Brii, 12/11/2026). Reemplaza la capa de texto, en la que la etiqueta de la
  fila «6 meses a 35 meses» cortaba la celda (límite 1 del caso c de la parte C).
- **Recuadros «Recommendation» de las guías de la OMS:** el título se separa de la línea
  anterior y abre su propio fragmento, con la sección «Recommendation: …». La recomendación queda
  en los primeros tokens que lee el reranker (límite 3 del caso l de la parte C).
- **Grupo etario de cada fragmento** (migración 008, `grupos_etarios.py` y
  `grupos_etarios.yaml`): edad mínima y máxima en meses, población, origen del rango y marca de
  dudoso. Incluye la revisión de Brii en la página `grupos_etarios.html`: la OMS 2024 entera
  queda GENERAL, 9 fragmentos pasan a GENERAL, uno de la OMS 2016 a 24 a 59 meses y 8 se
  confirman. En la versión 5 quedan 146 fragmentos vigentes GENERAL, 28 NINO, 6 GESTANTE y 3
  ADOLESCENTE, ninguno dudoso y 78 con origen MANUAL.

| Documento | Versión 4: total (vigentes) | Versión 5: total (vigentes) |
| --- | --- | --- |
| NTS 213-MINSA/DGIESP-2024 | 101 (82) | 102 (83) |
| RM 429-2024/MINSA | 14 (14) | 14 (14) |
| OMS 2024 | 60 (60) | 60 (60) |
| OMS 2016 | 27 (27) | 26 (26) |
| **Total** | **202 (183)** | **202 (183)** |

PostgreSQL y ChromaDB coinciden en los cuatro documentos (`data/mediciones/c2_extraccion_v5.md`).
Ninguna transcripción queda sin verificar.

### Antes y después

Recuperación real (`recuperar`). En R y V, la edad del paciente sale del texto de la consulta
(`edad_mencionada_meses`). La columna de la versión 4 es la medición de la parte B2. Intervalos
de Wilson al 95 %.

| Conjunto | Versión 4 | Versión 5, peso 0 | Versión 5, peso 0,7 |
| --- | --- | --- | --- |
| Ajuste (R, 20) | 95 % (19/20) | 90 % (18/20) | 95 % (19/20) |
| Validación (V, 15), con V11 corregida | 67 % (10/15) | 73 % (11/15) | 73 % (11/15) |
| **Desarrollo (35)** | **83 % (29/35), IC 67 a 92 %** | **83 % (29/35), IC 67 a 92 %** | **86 % (30/35), IC 71 a 94 %** |

- **V15 pasa a acertar** con la versión 5: el recuadro de la OMS 2016 de 24 a 59 meses queda en
  el puesto 1. Antes, la frase de la recomendación estaba después de los 256 tokens.
- **R08 falla en la versión 5 sin la bonificación.** El fragmento esperado (NTS 6.1.1 B.4, 24 a
  59 meses, 283 caracteres) queda en el puesto 11 de la fusión, fuera de los 8 candidatos. Con
  la bonificación entra y queda primero.
- **Fallan en todas las variantes** R09 y V06, V09, V12 y V14, por las causas ya descritas en B2:
  fragmentos largos de la RM 429 y de las definiciones, e idioma.
- **R12 se corrigió después de ver el resultado.** Su sección esperada era el literal del OCR
  «Tabla N°20»; la transcripción dice «Tabla N° 20». Con el literal anterior, R12 no tenía
  ningún fragmento esperado en la versión 5, aunque el fragmento de la tabla queda en el puesto 1.
  Con la corrección acierta con todos los pesos.

Con el análisis sin modelos (`variantes_recuperacion`, rankings de `medir_recuperacion
rankings`), contando R12 por contenido:

| Conjunto | Versión 4 | Versión 5, peso 0 | Versión 5, pesos 0,1 a 0,7 |
| --- | --- | --- | --- |
| Ajuste (R, 20) | 90 % (18/20) | 90 % (18/20) | 95 % (19/20) |
| Validación (V, 15) | 67 % (10/15) | 73 % (11/15) | 73 % (11/15) |

### Calibración del peso de la bonificación (solo con R)

Hay 7 consultas con edad en el texto: R01, R02, R04, R07, R08 y R10 en R, y V07 en V. En las
demás, la bonificación no cambia nada.

**Criterio:** el peso con más aciertos en R con la recuperación real; si hay empate, el menor.
V solo se informa.

**Recuperación real** (`medir_recuperacion edad`). Las corridas de 0,1 y 0,3 se hicieron el
12/11/2026 con un script temporal, antes de corregir R12, y se cuenta R12 como acierto: queda en
el puesto 1 con todos los pesos. Las de 0, 0,5 y 0,7 se repitieron el 13/11/2026 con el
subcomando `edad`, ya con R12 corregida, y dan las mismas cifras
(`data/mediciones/c2_edad_pesos_v5.json`).

| Peso | R | Fallan en R | Posición del esperado: R01 / R07 / R08 | V |
| --- | --- | --- | --- | --- |
| 0 | 18/20 | R08, R09 | 5 / 2 / no aparece | 11/15 |
| 0,1 | 18/20 | R01, R09 | 6 / 1 / 2 | 11/15 |
| 0,3 | 18/20 | R01, R09 | 6 / 1 / 2 | 11/15 |
| 0,5 | 18/20 | R01, R09 | 6 / 1 / 1 | 11/15 |
| **0,7** | **19/20** | **R09** | **4 / 2 / 1** | **11/15** |

R02, R04, R10 y V07 tienen el esperado en la misma posición con todos los pesos. En V ninguna
consulta cambia.

**Sin modelos**, todos los pesos de 0,1 a 0,7 dan 19 de 20. La posición en la fusión del
fragmento esperado de R08 marca el margen: 11 con peso 0, 8 con 0,1 y 0,2 (el último de los 8
candidatos), 7 con 0,3, y 5 con 0,5 y 0,7.

**Por qué R01 difiere entre pesos.** Su fragmento esperado (NTS 6.1.1 B.2, Tabla 6, 6 a 11
meses) recibe del reranker 0,165, 0,149 o 0,144 según el lote con que se evalúa. Con 0,1 a 0,5
lo adelanta por 0,02 un fragmento GENERAL de los anexos. Con 0,7 salen de los 8 evaluados las
tablas de 12 a 23 meses y de menores de 6 meses, que no aplican a un lactante de 8 meses, y el
esperado sube al puesto 4.

Con cualquier peso distinto de 0, ese fragmento queda en el top 5 pero bajo
`UMBRAL_RELEVANCIA` (0,15), así que no se enviaría al modelo.

**Propuesta del 12/11/2026: `BONIFICACION_EDAD` = 0,7**, con una migración nueva (versión con
vigencia). Aprobada con la condición de compararla antes con 0,5 (ver «Elección del peso»).

- **Es el único peso que mejora R con la recuperación real**, y también tiene el mayor margen
  sin modelos.
- **Fuerza:** un fragmento cuyo rango incluye la edad pesa 1,7 veces y uno que la excluye, 0,3
  veces (5,7 veces menos). No es un filtro duro, pero se acerca. Por eso depende de que los
  rangos estén bien: hoy no hay dudosos y la revisión manual cubrió todos los que había.
- **Muestra chica:** frente a 0,5, la diferencia es una sola consulta (R01) cuyo esperado está
  en el límite del umbral. Si se prefiere un ajuste más suave, 0,5 da el mismo resultado sin
  modelos y queda 18 de 20 con la recuperación real.

### Fragmentos enviados en la prueba de punta a punta

12 casos de `casos_e2e.yaml` con el cliente falso. Los 12 dan el estado esperado en las tres
corridas: versión 4, versión 5 con peso 0 y versión 5 con peso 0,7. Con 11 intentos enviados
y `control_identificadores` = true en todos. El cliente falso no juzga el contenido; lo que
importa es qué fragmentos llegan al modelo.

| Caso (edad) | Versión 4 | Versión 5, peso 0 | Versión 5, peso 0,7 |
| --- | --- | --- | --- |
| a (9 meses), prevención y control | Prevención 12 a 23 meses (0,99) y 5 a 11 años (0,99); **prevención 6 a 11 meses** (0,98); tratamiento 6 meses a 11 años (0,96) y menores de 6 meses (0,95) | Lo mismo, con otro orden | **Prevención 6 a 11 meses** (0,98); 6.1 intervenciones (0,97); tratamiento 6 meses a 11 años (0,96); 5.7 consideraciones (0,92); RM 429 Tabla 4 (0,75) |
| c (20 meses), tratamiento y control | Tratamiento en menores de 6 meses (0,92); referencia (0,92); seguimiento y Tabla 20 del OCR (0,89); gestantes (0,61 y 0,45). **Sin el tratamiento de 6 meses a 11 años** | Tratamiento en menores de 6 meses (0,93); **tratamiento 6 meses a 11 años** (0,92); referencia (0,90); seguimiento y **Tabla 20 transcrita** (0,85); gestantes (0,66) | **Tratamiento 6 meses a 11 años** (0,94); prevención 12 a 23 meses (0,91); referencia (0,90); seguimiento y **Tabla 20 transcrita** (0,86); recuadro OMS 2016 de 6 a 23 meses (0,66) |
| e (18 meses), altitud y tratamiento | 5 a 11 años (0,94); 5.3.1 ajuste de Hb (0,90); referencia (0,88); RM 429 Tabla 1 (0,79); OMS 2024 (0,71). **Sin tratamiento** | 5 a 11 años (0,94); 5.3.1 (0,91); referencia (0,88); RM 429 Tabla 1 (0,83); OMS 2024 Tabla 4, ajuste por altitud (0,79). **Sin tratamiento** | 5.3.1 (0,90); referencia (0,88); **tratamiento 6 meses a 11 años** (0,87); RM 429 Tabla 1 (0,84); OMS 2024 Tabla 4 (0,78) |
| l (49 meses), recomendación de la OMS | 5 a 11 años (0,95); 12 a 23 meses (0,93); 6 a 11 meses (0,89); dos de tratamiento (0,86 y 0,85). **Sin la OMS ni 24 a 59 meses** | **Recuadro OMS 2016 de 24 a 59 meses** (0,98); 12 a 23 meses (0,95); 5 a 11 años (0,95); 6 a 11 meses (0,89); página de la OMS 2016 (0,89) | **NTS prevención 24 a 59 meses** (0,99); **recuadro OMS 2016 de 24 a 59 meses** (0,99); página de la OMS 2016 (0,91); RM 429 Tabla 8, 24 a 59 meses (0,89); tratamiento 6 meses a 11 años (0,82) |

En los demás casos se ve lo mismo con el peso 0,7: salen las tablas de otras edades y entra la
del grupo del paciente.

- **b (14 meses) y k (18 meses):** entra la prevención de 12 a 23 meses. Salen la de 5 a 11
  años y el tratamiento en menores de 6 meses.
- **d (26 meses):** el tratamiento en menores de 6 meses se reemplaza por el de 6 meses a 11 años.
- **f (31 meses) e i (14 meses):** salen las tablas de 5 a 11 años y de menores de 6 meses.
- **j:** sigue en evidencia insuficiente, como se espera.

Informes en `data/mediciones/c_punta_a_punta_falso_v4.md`, `_v5_b0.md`, `_v5_b0.5.md` y
`_v5_b0.7.md`.

### Elección del peso: 0,5 frente a 0,7 (13/11/2026)

**Criterio acordado:** si con 0,5 llegan al modelo los mismos fragmentos correctos que con 0,7
en los casos a, c, e y l, se elige 0,5; si alguno se pierde, 0,7. Se cuenta como correcto un
fragmento del grupo de edad del paciente o que responde la pregunta del caso.

| Caso (edad) | Con 0,7 y no con 0,5 | Con 0,5 y no con 0,7 |
| --- | --- | --- |
| a (9 meses) | 6.1 intervenciones (0,97); RM 429 Tabla 4 (0,75) | Prevención 5 a 11 años (0,99) y 12 a 23 meses (0,99), de otras edades. La de 6 a 11 meses sigue, pero en el puesto 3 |
| c (20 meses) | **Recuadro OMS 2016 de 6 a 23 meses** (0,66) | Tratamiento en menores de 6 meses (0,94), primero en la lista |
| e (18 meses) | **Tratamiento 6 meses a 11 años** (0,87) | Una página metodológica de la OMS 2024 (0,74) |
| l (49 meses) | Ninguno: los cinco fragmentos son los mismos | Ninguno |

**Elegido: 0,7.** Con 0,5 se pierden dos fragmentos correctos. En e, el tratamiento de 6 meses
a 11 años, que es la indicación del caso (falta desde la versión 4). En c, el recuadro de la OMS
2016 para 6 a 23 meses. Además, en a y c vuelven al primer puesto tablas de otras edades. En R,
0,5 da 18 de 20 (falla R01) y 0,7, 19 de 20; en V, los dos dan 11 de 15. Los 12 casos dan el
estado esperado con 0,5, igual que con 0,7 (`data/mediciones/c_punta_a_punta_falso_v5_b0.5.md`).

Queda aplicado con la migración 009 en la base principal y en la de pruebas: cierra la vigencia
del 0 y registra 0,7.

### Regla de la OMS

No hace falta reservar un lugar para la OMS cuando la consulta la nombra. El caso l, que antes
no recibía ningún fragmento de la OMS, ahora recibe el recuadro de la OMS 2016 de 24 a 59 meses
con y sin la bonificación (0,98 y 0,99). La causa del fallo (la recomendación después de los
256 tokens) la resolvió el corte de los recuadros. Una reserva sumaría código y un parámetro sin
ningún caso que lo necesite. Se vuelve a evaluar si el caso l falla en la corrida real.

### Latencia de la recuperación (30 consultas, 8 x 256, versión 5)

| Perfil | Peso | Recuperación p50 / p90 | Reranker p50 / p90 | Referencia anterior |
| --- | --- | --- | --- | --- |
| Normal | 0 | 3,78 / 3,93 s | 3,44 / 3,56 s | 3,53 / 3,63 s (06/11/2026) |
| Normal | 0,7 | 3,75 / 3,88 s | 3,50 / 3,62 s | |
| B2ms (2 CPU) | 0,7 | 5,03 / 5,48 s | 4,55 / 4,99 s | 5,15 / 5,62 s (07/11/2026) |

- **La bonificación no agrega tiempo:** las dos corridas del entorno normal se hicieron una
  después de otra con los pesos 0 y 0,7, y el ajuste es una multiplicación sobre los candidatos
  ya leídos.
- **El entorno normal varía con la carga del equipo:** una corrida anterior con 0,7 dio 4,11 /
  4,45 s. El perfil B2ms, fijado a 2 CPU, es más estable.
- **Primera consulta en frío en B2ms:** 6,9 s.

## Parte C: confirmación de la API y prueba de punta a punta (07/11/2026)

### Confirmación de la API (paso 0)

Script `app/scripts/confirmar_api.py`, que solo se ejecuta con `--confirmo-datos-sinteticos`
y envía un caso inventado, sin datos de pacientes. Hace tres solicitudes: los datos del
modelo en la Models API (sin contenido), una llamada mínima a la Messages API y una
solicitud con `temperature`, que la API rechaza antes de generar. SDK de Python
`anthropic` 2.6.0, versión de API 2026-10-21. Resultado en
`data/mediciones/c0_confirmacion_api.json`.

| Elemento | Resultado | Fuente |
| --- | --- | --- |
| Modelo | `claude-sonnet-5-5` aceptado y respondido por ese mismo modelo; activo, sin fecha de retiro (no antes del 28/09/2027) | Llamada; https://platform.claude.com/docs/en/models/sonnet-5-5/overview |
| Temperatura | Error 400 «temperature: Extra inputs are not permitted» | Llamada; https://platform.claude.com/docs/en/api/versioning |
| Salida estructurada | `output_config.format` = `{type: json_schema, schema}`; respuesta válida con el esquema de prueba | Llamada; https://platform.claude.com/docs/en/build-with-claude/structured-outputs |
| Razonamiento | Adaptativo por defecto; `disabled` no admitido; `between_tools` es el mínimo y sin herramientas no razona. Se envía `thinking: {type: between_tools}` con `output_config.effort` = `medium` | Models API; https://platform.claude.com/docs/en/build-with-claude/thinking y https://platform.claude.com/docs/en/build-with-claude/effort |
| Uso de tokens | `usage.input_tokens`, `usage.output_tokens` (incluye el razonamiento) y `usage.output_tokens_details.thinking_tokens` | Llamada |
| Rechazo | HTTP 200 con `stop_reason` = `refusal` y `stop_details.category` | https://platform.claude.com/docs/en/build-with-claude/refusals-and-fallback |
| Precios | 2 dólares por millón de tokens de entrada y 10 por millón de salida | https://platform.claude.com/docs/en/about-claude/pricing |
| Retiro de Claude Sonnet 4.5 | `claude-sonnet-4-5-20250929`: obsoleto el 30/09/2026, retiro el 30/11/2026, reemplazo `claude-sonnet-5-5` | https://platform.claude.com/docs/en/about-claude/model-deprecations |

Llamada mínima (un fragmento sintético de 30 palabras y un esquema de 3 campos): 551
tokens de entrada, 126 de salida, 0 de razonamiento, 3,5 s incluida la compilación del
esquema la primera vez, y **0,00236 dólares**. Una consulta real envía 5 fragmentos de
hasta unos 800 tokens y el prompt clínico, así que su costo será varias veces mayor; la
cifra por consulta sale de la corrida real de punta a punta.

### Prueba de punta a punta con el cliente falso

12 casos de `app/scripts/casos_e2e.yaml` con pacientes de `seed_demo`, la recuperación real
(modelos, ChromaDB y guías de la versión 4) y el cliente falso del modelo de lenguaje: **12 de
12 dan el estado esperado** (8 VERIFICADA, 1 DATOS_FALTANTES, 1 FUERA_DE_DOMINIO, 1
EVIDENCIA_INSUFICIENTE con búsqueda ampliada y 1 VERIFICADA con cita de la OMS y traducción
de apoyo), y los 9 intentos enviados tienen `control_identificadores` = true. En el caso i el
texto filtrado queda «¿Qué tratamiento con hierro le doy a [PACIENTE], DNI [DNI], HC [HC]? Su
mamá llama al [TELEFONO].». Sin el modelo de lenguaje, cada consulta tarda unos 3,3 s
(recuperación con el reranker int8) y unos 7 s cuando hace falta la búsqueda ampliada. Los
tokens y el costo del cliente falso son simulados. Informe en
`data/mediciones/c_punta_a_punta_falso.md`.

La primera versión del caso f («¿Qué se recomienda según la hemoglobina registrada…?»)
terminó en evidencia insuficiente: con una consulta tan genérica ningún fragmento alcanzó
el umbral (0,011 con la búsqueda ampliada). Se reformuló como pregunta clínica concreta, igual
que los demás casos.

La corrida con el modelo real la ejecuta el responsable del proyecto (paso 8 de «Cómo
repetir las mediciones»).

### Corrida real completa con la consulta combinada (07/11/2026)

Condiciones: Docker Desktop del equipo de desarrollo (entorno normal, reranker ONNX int8, 8
candidatos de 256 tokens), no el perfil B2ms. `claude-sonnet-5-5`, prompt v1.1,
`MAX_TOKENS_SALIDA` 1500, razonamiento `between_tools`, esfuerzo `medium`. Recuperación con la
consulta estructurada más el texto filtrado y control de dosis con la dosis derivada del peso.
Informe en `data/mediciones/c_punta_a_punta_real.md`.

**Resultado: 10 de 12 casos dan el estado esperado.** Los que no coinciden son c y l, que
terminaron en EVIDENCIA_INSUFICIENTE cuando se esperaba VERIFICADA.

| Caso | Esperado | Obtenido | Intentos |
| --- | --- | --- | --- |
| a, b, d, f, i, k | VERIFICADA | VERIFICADA | 1 (INICIAL, APROBADO) |
| e | VERIFICADA | VERIFICADA | 2 (INICIAL REINTENTO por 6.3; AMPLIADA APROBADO) |
| c | VERIFICADA | EVIDENCIA_INSUFICIENTE | 2 (INICIAL REINTENTO por 6.3; AMPLIADA, falla 6.1 en el extracto de F-04) |
| j | EVIDENCIA_INSUFICIENTE | EVIDENCIA_INSUFICIENTE | 2 (el modelo declaró evidencia insuficiente en los dos) |
| l | VERIFICADA | EVIDENCIA_INSUFICIENTE | 2 (el modelo declaró evidencia insuficiente en los dos) |
| g | DATOS_FALTANTES | DATOS_FALTANTES | sin llamada al modelo |
| h | FUERA_DE_DOMINIO | FUERA_DE_DOMINIO | sin llamada al modelo |

**Tokens y costo.** 14 intentos enviados, todos con `control_identificadores` = true y
`stop_reason` = end_turn (ninguno cortado). 86 717 tokens de entrada (de 5738 a 6943 por
intento, mediana 6128), 10 210 de salida (de 367 a 1015, mediana 863) y 0 de razonamiento.
Costo total 0,276 dólares: de 0,016 a 0,023 por intento y 0,028 por consulta enviada.

**Tiempos por etapa (14 intentos, ms).**

| Etapa | Mínimo | Mediana | Máximo |
| --- | --- | --- | --- |
| Recuperación (búsqueda, fusión y reranker) | 3435 | 3792 | 4998 |
| Llamada al modelo | 3452 | 5713 | 6642 |
| Protección (solicitud, hash y control previo) | 3 | 4 | 5 |
| Verificación | 1 | 2 | 3 |

**Latencia de la etapa de generación frente al RNF3.** Se mide desde la recuperación hasta el
cierre de la consulta; no incluye el filtro de texto, la validación ni el filtro de dominio de la
etapa clínica.

| Flujo | Casos | Mínimo | Mediana | Máximo | Objetivo del RNF3 |
| --- | --- | --- | --- | --- | --- |
| Un intento | 6 | 8,4 s | 10,2 s | 11,4 s | menos de 10 s en el percentil 90 |
| Con reintento | 4 | 14,9 s | 17,0 s | 20,3 s | 25 s como máximo |

Con un intento, 2 de los 6 casos quedan bajo 10 s y el máximo (11,4 s, caso a, con 5,0 s de
recuperación) lo supera: con 6 casos, el percentil 90 es el máximo. Con reintento, los 4 casos
quedan bajo 25 s.

**Límites encontrados.**

1. Caso c, intento 2: el extracto de F-04 (Tabla N° 20 de la NTS, «Al segundo, tercer y sexto
   mes de iniciado tratamiento») no es un texto contiguo del fragmento. En la capa de texto de
   la tabla, la etiqueta de la fila «6 meses a 35 meses» corta la celda: «Al segundo, tercer y
   sexto mes de iniciado / 6 meses a 35 meses tratamiento». El modelo unió la celda quitando la
   etiqueta intercalada; no es solo una diferencia de espacios, saltos de línea, guiones bajos o
   símbolos de tabla, así que se mantiene el rechazo. La comparación ahora normaliza igual los dos
   lados (espacios, saltos de línea, mayúsculas y símbolos de tabla `|`, `_`, `•`, `*`, `·`), sin
   coincidencia aproximada. La Tabla N° 20 no está entre las transcripciones verificadas.
2. Casos c y e, intento 1: la sección NTS 6.1.2 B.3 (tratamiento de 6 meses a 11 años) quedó
   fuera de los 8 candidatos del reranker, mientras que B.2 (menor de 6 meses) entró:

   | Caso (edad) | Fragmento | Fusión RRF | BM25 | Vectorial | Reranker |
   | --- | --- | --- | --- | --- | --- |
   | c (20 meses) | B.3 | 10 | sin resultado | 3 | 0,926, no evaluado |
   | c (20 meses) | B.2 | 1 | 2 | 1 | 0,923, enviado F-01 |
   | e (18 meses) | B.3 | 15 | sin resultado | 4 | 0,853, no evaluado |
   | e (18 meses) | B.2 | 11 | sin resultado | 2 | 0,858, no evaluado |

   Con la búsqueda ampliada, B.3 entra en los dos casos (fusión 6 y 2). El puntaje del reranker
   fuera de los 8 se calculó aparte con el mismo modelo. BM25 no recupera B.3 en la búsqueda
   inicial; la búsqueda vectorial la pone tercera o cuarta.
3. Caso l: el fragmento de la OMS 2016 con la recomendación para niños de 24 a 59 meses existe en
   el índice vigente (orden 9, página 17, sin etiqueta de sección, 657 tokens). Empieza con la
   evidencia sobre ferritina y la frase «Daily iron supplementation is recommended as a public
   health intervention in preschool-age children aged 24-59 months…» está a partir del carácter
   1325, más allá de los 256 tokens que lee el reranker. Con la consulta combinada queda en el
   puesto 3 de la fusión (BM25 1, vectorial 7) y el reranker le da 0,518, bajo los cinco
   fragmentos de la NTS enviados (de 0,847 a 0,948). Con la búsqueda ampliada, fusión 3 y
   reranker 0,508. La sección NTS 6.1.1 B.4 (prevención de 24 a 59 meses) tampoco se envió:
   fusión 10 (BM25 17, vectorial 9), fuera de los 8, con 0,993 en el reranker calculado aparte;
   con la búsqueda ampliada, fusión 40. El modelo declaró evidencia insuficiente porque no recibió
   ningún fragmento de la OMS ni de prevención para 24 a 59 meses.

### Primera corrida con el modelo real (07/11/2026) y diagnóstico

Corrida del responsable del proyecto, con el prompt v1.0 y `MAX_TOKENS_SALIDA` = 1000: **3 de 12**
casos dan el estado esperado (g, h y j). 18 intentos enviados, todos con
`control_identificadores` = true; 95 432 tokens de entrada, 15 100 de salida, 0 de
razonamiento y 0,34 dólares (0,038 por consulta enviada). Cada llamada tardó de 5 a 7,5 s.

- **b, c y d (ERROR):** las respuestas llegaron a los 1000 tokens de salida en los dos intentos,
  con 0 tokens de razonamiento: el corte se debe al largo del JSON (varios extractos largos por
  fragmento, factores y advertencias extensos). Corrección: migración 007 y prompt v1.1 (fila 47
  de `docs/cambios_respecto_al_OE2.md`).
- **a, e, f, i, k y l (EVIDENCIA_INSUFICIENTE):** las respuestas guardadas en
  `intento_generacion.respuesta_borrador` muestran que el modelo declaró la evidencia
  insuficiente por el contenido de los fragmentos, no por un error. En el caso a dijo que los
  fragmentos cubrían de 12 a 23 meses y de 5 a 11 años, pero no a una niña de 9 meses. En el
  caso e respondió la parte del ajuste por altitud con citas, pero declaró insuficiente la
  consulta completa porque faltaba el esquema de tratamiento.
- **Recuperación del caso a:** se enviaron 4 fragmentos, no 5 (el quinto candidato, de la OMS
  2016, tuvo 0,053 en el reranker, bajo el umbral de 0,15): NTS 6.1.1 B.3 (12 a 23 meses, 0,86),
  NTS 6.1.1 A (medición de hemoglobina, 0,68), NTS 6.1.2 B.11 (seguimiento de casos de anemia,
  0,43) y NTS 6.1.1 B.5 (5 a 11 años, 0,39). El fragmento NTS 6.1.1 B.2 «En el niño y la niña de
  6 a 11 meses de edad» quedó en el puesto 21 de la fusión (sin BM25, puesto 11 en la búsqueda
  vectorial), fuera de los 8 que evalúa el reranker; con la búsqueda ampliada, en el puesto 35.
  La consulta libre no menciona la edad, que solo está en los datos estructurados. Con la consulta
  estructurada más el texto filtrado, el mismo fragmento entra en el puesto 3 (reranker 0,97):
  dato para la parte D, donde se combinan ambas.
- **Pendiente para después de la próxima corrida:** en los casos b, c y d el modelo calculó la
  dosis con el peso (por ejemplo «28,8 mg/día» para 9,6 kg). El control de dosis exige que cada
  cifra con unidad figure en el fragmento citado, así que esas respuestas fallarían 6.1 aunque
  ya no se corten.

**Cambios después del diagnóstico (07/11/2026).** La recuperación usa la consulta estructurada
más el texto filtrado (fila 48 de `docs/cambios_respecto_al_OE2.md`) y el control de dosis acepta
la dosis derivada del peso de los datos estructurados (fila 49). Fragmentos enviados con el stack
real, sin llamar a la API:

| Caso | Fragmentos enviados (puntaje del reranker) |
| --- | --- |
| a | NTS 6.1.1 B.3, 12 a 23 meses (0,99); NTS 6.1.1 B.5, 5 a 11 años (0,99); **NTS 6.1.1 B.2, 6 a 11 meses (0,98)**; NTS 6.1.2 B.3, tratamiento de 6 meses a 11 años (0,96); NTS 6.1.2 B.2, tratamiento en menores de 6 meses (0,95) |
| e | NTS 6.1.1 B.5, 5 a 11 años (0,94); NTS 5.3.1 y 5.3.2, ajuste del valor de Hb (0,90); NTS 6.1.2 B.10 y B.11, referencia y seguimiento (0,88); RM 429 5.3.2 Tabla 1, ajuste por altitud (0,79); OMS 2024 (0,71) |
| f | NTS 6.1.2 B.10 y B.11, referencia y seguimiento (0,95); NTS 6.1.1 B.5, 5 a 11 años (0,90); NTS 6.1.2 B.3, tratamiento de 6 meses a 11 años (0,87); NTS 6.1.2 B.2, tratamiento en menores de 6 meses (0,86); OMS 2016 (0,85) |

En el caso e no entra la sección de tratamiento con la dosis (NTS 6.1.2 B.3): el modelo podría
volver a responder el ajuste por altitud y declarar insuficiente la parte del tratamiento. Con el
cliente falso, los 12 casos siguen dando el estado esperado; el caso j ahora llega al modelo
porque sus fragmentos superan el umbral con la consulta combinada.

## Parte B2: etiquetas de sección corregidas y versión 4 (07/11/2026)

**Causa.** La segmentación guardaba el texto de cada segmento sin los saltos de línea de los
extremos, pero con la posición del salto de línea. Cada frase del segmento quedaba un carácter
antes que su título en el mapa de secciones, y un fragmento que empezaba en un título recibía
la sección del anterior. Además, los ítems y literales solo cortaban el fragmento cuando este
tenía la mitad del objetivo, de modo que un ítem corto quedaba al final del contenido de otro
(el ítem 8 «Atención nutricional» dentro del fragmento de hierro intravenoso en gestantes).

**Corrección** (`segmentacion.py` y `chunker.py`):

- El segmento recortado guarda su posición real, y un fragmento que empieza en un título toma
  la sección de ese título por coincidencia con su línea; si empieza con varios títulos
  seguidos («V. ...» y «5.1. ...»), vale el último.
- Los literales e ítems cortan cuando el fragmento tiene un cuarto del objetivo, o el mínimo de
  40 tokens si el fragmento es la continuación de un apartado anterior.
- Al llegar al objetivo, el fragmento no se cierra a mitad de un apartado si lo que falta hasta
  el siguiente título cabe en el máximo.
- La sección nombra también hasta 3 títulos que empiezan dentro del fragmento («... > 7.
  Tratamiento de anemia severa; 8. Atención nutricional; 9. Criterios de alta al tratamiento»),
  dentro de los 200 caracteres de la columna.

Los parámetros siguen en 500/800/80. Con la corrección, de 82 fragmentos vigentes de la NTS
solo 1 (un paso de una receta del Anexo 1) no coincide con el título con el que empieza, frente
a 29 de 78 en la versión 3.

**Fragmentos por documento** (versión 4, PostgreSQL y ChromaDB coinciden en los cuatro):

| Documento | Versión 3: total (vigentes) | Versión 4: total (vigentes) | Tokens por fragmento vigente en la v4 (mediana / máximo) |
| --- | --- | --- | --- |
| NTS 213-MINSA/DGIESP-2024 | 97 (78) | 101 (82) | 171 / 777 |
| RM 429-2024/MINSA | 14 (14) | 14 (14) | 405 / 785 |
| OMS 2024 | 61 (61) | 60 (60) | 515 / 1019 |
| OMS 2016 | 27 (27) | 27 (27) | 516 / 657 |
| **Total** | **199 (180)** | **202 (183)** | |

En ChromaDB solo queda la versión vigente: 202 vectores en `guias_clinicas`. Las 52 pruebas
lentas del indexador pasan con la versión 4.

**Antes y después** con la recuperación real (`recuperar`, pruebas lentas) y la configuración
vigente: int8, 8 candidatos de 256 tokens, 20 por método, k 60. Intervalos de Wilson al 95 %.

| Conjunto | Versión 3 | Versión 4 |
| --- | --- | --- |
| Ajuste (R, 20) | 95 % (19/20) | 95 % (19/20) |
| Validación (V, 15), secciones originales | 47 % (7/15) | 60 % (9/15) |
| Validación (V, 15), con V11 corregida | 53 % (8/15) | 67 % (10/15) |
| **Desarrollo (35)** | **77 % (27/35), IC 61 a 88 %** | **83 % (29/35), IC 67 a 92 %** |
| Prueba (20), solo referencia | 70 % (14/20), IC 48 a 85 % | 80 % (16/20), IC 58 a 92 % |
| Reranker 8 x 256, entorno normal, p50 / p90 | 3,20 / 3,28 s | 3,20 / 3,40 s |

**Experimento de tamaño frente a la versión 4**, con el análisis sin modelos (`variantes_recuperacion`),
que puntúa los candidatos en lotes de 32 y por eso tiene el mismo ruido en ambos lados:

| Conjunto | 500/800/80 (versión 4) | 250/400/40 (experimento) |
| --- | --- | --- |
| Ajuste (R, 20) | 90 % (18/20) | 85 % (17/20) |
| Validación (V, 15), con V11 corregida | 67 % (10/15) | 67 % (10/15) |
| Desarrollo (35) | 80 % (28/35) | 77 % (27/35) |
| Reranker 8 x 256, p50 / p90 | 3,20 / 3,40 s | 3,33 / 3,47 s |

El análisis sin modelos y la recuperación real difieren en dos consultas de la versión 4 (R19 y
P05): con int8 el puntaje de un par cambia hasta 0,07 según el lote en que se evalúa (por el
relleno hasta el par más largo), y eso mueve el fragmento esperado del puesto 5 al 6 (R19) y del
4 al 6 (P05). Las cifras de la recuperación real son las que cuentan; el análisis sin modelos
sirve para comparar variantes entre sí. En la versión 3 ambos daban lo mismo.

- Con la versión 4 aciertan V07 y V10 (antes fallaban por la etiqueta desplazada) y R08, y
  falla R09: la reindexación cambia los fragmentos vecinos y el orden de la fusión. Fallan
  además V06, V09, V12, V14 y V15 por las causas del diagnóstico anterior (fragmentos largos de
  la RM 429 y de las definiciones, e idioma).
- Las secciones esperadas de la NTS para 5.4.2 (V06), 5.4.5 (V09) y el literal E (V11) apuntan
  a texto que sustituyó la RM 429 y que no es vigente. En la versión 3 coincidían solo con otro
  contenido, por la etiqueta desplazada. Las tres consultas tienen además la sección de la RM
  429, que sí existe. No se cambiaron.
- Conjunto de prueba: ya se usó para decidir, así que no es independiente y se informa solo
  como referencia. P08 recibió, después de ver el resultado, el fragmento vigente de la NTS
  sobre menores de 6 meses como sección aceptable. En la versión 4 P08 acierta con y sin esa
  corrección (16 de 20 en ambos casos). En la versión 3 era 14 de 20; con la corrección
  contada por contenido serían 15 de 20, porque ese fragmento estaba en el puesto 3 bajo la
  etiqueta desplazada «A. Medición de hemoglobina». En la versión 4 aciertan además P08 y P19;
  fallan P10, P15, P16 y P20.
- Las secciones esperadas de la NTS del conjunto de prueba que se habían pasado a
  `texto_contiene` volvieron a `seccion_contiene`, porque la sección ya corresponde al
  contenido.

**Experimento de tamaño de fragmento.** Objetivo 250 tokens, máximo 400 y solapamiento 40, para
que el reranker (256 tokens) vea fragmentos casi completos. Se midió con BM25 en memoria y una
colección aparte de ChromaDB (`experimento_250_400`, borrada al terminar), sin tocar
PostgreSQL ni la colección de producción. Da 273 fragmentos vigentes (frente a 183). En el
conjunto de desarrollo acierta 27 de 35, una menos que la versión 4 con el mismo análisis, y la
mejor variante de fusión de la rejilla también queda en 27. La latencia del reranker es casi igual. No mejora
de forma clara, así que no se adopta y no es una desviación respecto al OE2: se mantienen
500/800/80 con la corrección de etiquetas.

## Parte B2: primera etapa de la recuperación (07/11/2026)

Revisión de BM25, la búsqueda vectorial y la fusión RRF después de que el conjunto de
validación acertara 7 de 15. Guías indexadas en la versión 3 (180 fragmentos), reranker ONNX
int8 con 256 tokens. Detalle por consulta en `data/mediciones/b2b_informe.md`.

**Conjuntos.** Desarrollo: las 20 consultas de ajuste (R) y las 15 de validación (V), usadas
juntas para comparar mejoras. Prueba final: `consultas_prueba.yaml`, escrito antes de probar
cualquier mejora, con 10 casos clínicos (la consulta la arma `construir_consulta` con los datos
estructurados del tamizaje; incluye los casos 1 a 6 y 10 de la prueba de punta a punta del plan)
y 10 preguntas libres nuevas. Se midió una sola vez, al final.

**Método.** `medir_recuperacion rankings` guarda por consulta el ranking completo de BM25 (con y
sin la expansión del diccionario) y de la búsqueda vectorial, los fragmentos que cumplen la
sección esperada y el puntaje del reranker de todo lo que alguna variante lleva al reranker.
`variantes_recuperacion` reproduce sin los modelos la fusión y la selección de 162 variantes:
20, 30 o 40 candidatos por método; k de RRF 10, 30 o 60; pesos BM25:vectorial 1:1, 1:2 o 2:1;
8, 10 o 12 candidatos al reranker; BM25 con o sin expansión. La variante actual reproduce lo
medido en B (19 de 20 en ajuste) y las pruebas lentas con `recuperar` dan las mismas cifras en
los tres conjuntos.

### Antes y después

| Conjunto | Actual: 20 por método, k 60, pesos 1:1, 8 al reranker | Mejor alternativa de desarrollo: pesos 1:2 y 12 al reranker |
| --- | --- | --- |
| Ajuste (R, 20) | 95 % (19/20) | 90 % (18/20) |
| Validación (V, 15), secciones originales | 47 % (7/15) | 60 % (9/15) |
| Validación (V, 15), con V11 corregida | 53 % (8/15) | 67 % (10/15) |
| Desarrollo (R y V, 35) | 77 % (27/35), IC 95 % 61 a 88 % | 80 % (28/35), IC 95 % 64 a 90 % |
| **Prueba final (20)** | **70 % (14/20), IC 95 % 48 a 85 %** | 80 % (16/20), IC 95 % 58 a 92 % |
| Prueba: casos clínicos (10) | 80 % (8/10) | 80 % (8/10) |
| Prueba: preguntas libres (10) | 60 % (6/10) | 80 % (8/10) |

V11 se corrigió después de ver el resultado (la modificación 6.1.3 E de la RM 429 reemplaza el
literal E de la NTS): 7 de 15 antes y 8 de 15 después. Los intervalos son de Wilson al 95 %.

**Iteración 1, variantes de la fusión y de candidatos.** Ninguna de las 81 variantes sin
expansión supera a la actual por más de una consulta en desarrollo. Más candidatos no es
mejor de forma uniforme: con 10 o 12 al reranker acierta R08, pero el reranker pierde R01 y R06
ante fragmentos parecidos (tablas de otras edades, la NTS frente a la RM 429). Con 40 por
método baja a 24 de 35.

**Iteración 2, huecos del diccionario y expansión.** Se probaron cinco conceptos nuevos (atención
nutricional, pertinencia cultural, material educativo, disponibilidad de suplementos y
definiciones operativas) y sinónimos para la adherencia y la referencia. No cambian la variante
actual (27 de 35): en la búsqueda inicial los sinónimos en español no entran a BM25, solo los
equivalentes en inglés. Pasarlos a BM25 desde la búsqueda inicial (expansión) empeora a 26 de
35 (pierde R19, R20 y V08 por el ruido de los sinónimos). Los cambios del diccionario se
revirtieron.

Tras dos iteraciones no hay una ganancia clara y el trabajo se detuvo, como se acordó. La mejor
alternativa gana 3 consultas de 55 entre desarrollo y prueba (44 frente a 41), pierde una de
ajuste, necesita pesos en RRF (código nuevo y un parámetro en `parametro_sistema`) y sube la
latencia en B2ms de 5,15 a 7,05 s en p50.

### Latencia en el perfil B2ms (30 consultas, int8, 256 tokens, 20 por método)

| Candidatos al reranker | Reranker p50 / p90 | Recuperación completa p50 / p90 |
| --- | --- | --- |
| 8 (actual) | 4,64 / 4,99 s | 5,15 / 5,62 s |
| 10 | 5,82 / 6,15 s | 6,25 / 6,61 s |
| 12 | 6,62 / 7,07 s | 7,05 / 7,49 s |

Con 8 candidatos la medición del 06/11/2026 dio 4,76 / 5,09 s; la diferencia es variación entre
corridas en el mismo equipo. Cada candidato adicional suma unos 0,5 s.

### Diagnóstico de los fallos

Posición del mejor fragmento esperado en cada paso con la variante actual («-»: no aparece;
la fusión RRF toma los 20 primeros de cada método y el reranker evalúa los 8 primeros de la
fusión). «Si se evaluara»: posición que le daría el reranker si estuviera entre los evaluados.

| Consulta | BM25 | Vectorial | RRF | Reranker | Si se evaluara | Causa probable |
| --- | --- | --- | --- | --- | --- | --- |
| R08 (ajuste) | 47 | 4 | 10 | - | 3 | Vocabulario: la consulta dice «3 años» y el fragmento «24 a 59 meses»; fragmento corto (283 caracteres) que BM25 deja atrás |
| V06 | 13 | 10 | 13 | - | 5 | Etiqueta desplazada (el rotulado 5.4.2 contiene el 5.4.3) y fragmento largo: en la modificación 3 de la RM 429 (2861 caracteres) el cambio de producto queda después de los 256 tokens que lee el reranker |
| V07 | 56 | 73 | - | - | 9 | Etiqueta desplazada y tema mezclado: el ítem 8 «Atención nutricional» está al final de un fragmento sobre hierro intravenoso en gestantes (puntaje 0,008); el rotulado 8 contiene los ítems 9 y 10 |
| V09 | 14 | 5 | 9 | - | 9 | Vocabulario («stock» frente a «no se cuente con»), etiqueta desplazada (el rotulado 5.4.5 contiene el 5.5) y fragmento largo de la RM 429 truncado; el reranker le da 0,000 |
| V10 | - | 123 | - | - | 8 | Etiqueta desplazada: el texto del 5.2.3 está en el fragmento rotulado «5.1 Definiciones», que quedó en el puesto 1. Por contenido, acierta |
| V12 | 89 | 25 | - | - | 4 | Fragmentos largos de definiciones (hasta 2260 caracteres): las de anemia y adherencia quedan después de los 256 tokens; la consulta junta tres términos |
| V14 | 76 | 3 | 13 | - | 1 | Idioma: tabla de la OMS en inglés y «antes» (previous) sin equivalente; la búsqueda vectorial la pone 3.ª, pero como BM25 no la encuentra RRF la baja a 13 |
| V15 | 13 | 2 | 3 | 7 | 4 | Idioma: las páginas de la OMS 2016 (en inglés, sin sección y de 2000 a 2600 caracteres) pierden en el reranker ante la Tabla 8 de la RM 429 en español |
| P08 (caso) | 1 | 14 | 2 | 7 | 7 | Reranker: la Tabla 5 de la RM 429 (0,61) queda detrás de cinco tablas de otras edades o de tratamiento (0,83 a 0,97). El texto de la NTS sobre menores de 6 meses sí está en el top 5, bajo la etiqueta desplazada «A. Medición de hemoglobina» |
| P10 (caso) | 27 | 19 | 28 | - | 2 | Vocabulario: la consulta dice «48 meses» y el fragmento «24 a 59 meses»; fragmento corto. El reranker le daría 0,964, casi igual que a las tablas de otras edades |
| P15 (libre) | 36 | 3 | 10 | - | 3 | Etiqueta desplazada y ítem partido: la atención nutricional está en el fragmento rotulado «7. En la gestante» y el puesto 1 es el ítem siguiente (consejería nutricional), que también responde |
| P16 (libre) | 8 | 10 | 6 | 8 | 8 | Idioma y truncamiento: la tabla de la OMS 2016 con la dosis queda después de los 256 tokens del fragmento; ganan las tablas de la NTS en español |
| P19 (libre) | 1 | 21 | 10 | - | 1 | Fusión: BM25 lo pone 1.º pero la búsqueda vectorial 21.ª; con k 60 un fragmento hallado por un solo método queda detrás de los hallados por ambos. El reranker lo pondría 1.º (etiqueta desplazada «11. Seguimiento») |
| P20 (libre) | 22 | 9 | 18 | - | 1 | Tabla de códigos (CPMS) con poco texto: la consulta dice «HIS» y «registrar»; el reranker la pondría 1.ª |

Resumen de causas (una consulta puede tener varias): en 11 de los 14 fallos el fragmento
esperado no llega a los 8 que evalúa el reranker, y en 8 de esos 11 el reranker lo pondría en el
top 5; la etiqueta de sección desplazada interviene en 6 (V06, V07, V09, V10, P08 y P15); el
idioma o el truncamiento a 256 tokens de fragmentos largos, en 6 (V06, V09, V12, V14, V15 y
P16); el vocabulario de la consulta (edad en años o meses frente a rangos de meses, «stock»,
«HIS»), en 4 (R08, V09, P10 y P20).

### Etiquetas de sección desplazadas

En 29 de los 77 fragmentos de la NTS con sección, `fragmento.seccion` es la del título anterior:
cuando un fragmento empieza justo en un título, el indexador le asigna la sección previa (el
rotulado «8. Atención nutricional» empieza en «9. Criterios de alta»; el rotulado «10.
Referencia» empieza en «11. Seguimiento»). La recuperación no usa la sección, pero sí la
evaluación con `seccion_contiene` y las citas que mostrará la parte C. Las secciones esperadas
del conjunto de prueba se escribieron por contenido (`texto_contiene`) antes de medirlo; las de
ajuste y validación no se cambiaron. Por contenido, V10 también acierta (9 de 15 en
validación con V11 corregida).

### Propuesta

- Mantener los parámetros vigentes: ONNX int8, 8 candidatos de hasta 256 tokens, 20 por
  método y k 60. No se propone ningún cambio en `parametro_sistema`.
- La alternativa con pesos 1:2 y 12 candidatos queda como opción: gana en los dos conjuntos,
  pero por 1 y 2 consultas, con intervalos solapados y 1,9 s más en B2ms.
- Lo que más ayudaría según el diagnóstico: corregir la sección de los fragmentos y reindexar
  (hecho en la versión 4, ver la sección anterior), partir los fragmentos largos de la RM 429 y
  de la OMS para que el reranker lea la parte pertinente, y en la consulta estructurada nombrar
  el grupo de edad de la norma («24 a 59 meses») además de la edad en meses.

## Parte B: recuperación

Mediciones del 05 y 06/11/2026 con las guías indexadas en la versión 3 (180 fragmentos
recuperables). La revisión de la primera etapa (B2) está en la sección anterior. Las dos primeras secciones resumen el motor ONNX int8 ya aplicado y el conjunto
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

# 6. Primera etapa de la recuperación, B2 (07/11/2026)                     (unos 25 min)
docker compose up -d                                                      # entorno normal, int8; esperar healthy
MSYS_NO_PATHCONV=1 docker compose run --rm --no-deps -T -v "$APP" backend $MEDIR rankings --grupo desarrollo > $D/b2b_rankings_desarrollo_it0.json   # 6 min
MSYS_NO_PATHCONV=1 docker compose run --rm --no-deps -T -v "$APP" backend $MEDIR rankings --grupo prueba > $D/b2b_rankings_prueba.json                # 4 min; una sola vez
docker compose $B2MS up -d --force-recreate                               # esperar healthy
MSYS_NO_PATHCONV=1 docker compose $B2MS run --rm --no-deps -T -v "$APP" backend $MEDIR latencia --entorno b2ms-int8 --consultas 30 --configuraciones 8x256,10x256,12x256 > $D/b2b_latencia_b2ms.json   # 10 min
docker compose up -d --force-recreate
cd backend && .venv/Scripts/python -m app.scripts.variantes_recuperacion --desarrollo ../$D/b2b_rankings_desarrollo_it0.json   --prueba ../$D/b2b_rankings_prueba.json --propuesta 20x60x1:2x12 > ../$D/b2b_informe.md; cd ..

# 7. Etiquetas corregidas, versión 4 y experimento de tamaño (07/11/2026)   (unos 50 min)
docker compose build jobs
docker compose run --rm jobs python -m app.indexador cargar --manifiesto fuentes_iniciales.yaml --reindexar      # 8 min
MSYS_NO_PATHCONV=1 docker compose run --rm jobs python -m app.indexador comparar --salida /datos/mediciones/b2c_extraccion_v4.md   # conteos PostgreSQL y ChromaDB
MSYS_NO_PATHCONV=1 docker compose run --rm jobs python -m app.indexador comparar --sin-chroma --parametros 250,400,40   --fragmentos-json /datos/mediciones/b2c_fragmentos_250.json --salida /datos/mediciones/b2c_extraccion_250.md
MSYS_NO_PATHCONV=1 docker compose run --rm --no-deps -T -v "$APP" backend $MEDIR rankings --grupo desarrollo > $D/b2c_rankings_desarrollo_v4.json   # 6 min
MSYS_NO_PATHCONV=1 docker compose run --rm --no-deps -T -v "$APP" -v "$(pwd -W)/data/mediciones:/datos:ro" backend $MEDIR rankings --grupo desarrollo   --fragmentos /datos/b2c_fragmentos_250.json --coleccion experimento_250_400 > $D/b2c_rankings_desarrollo_250.json   # 20 min, llena la colección
MSYS_NO_PATHCONV=1 docker compose run --rm --no-deps -T -v "$APP" backend $MEDIR rankings --grupo prueba > $D/b2c_rankings_prueba_v4.json         # 4 min, solo referencia
cd backend && .venv/Scripts/python -m app.scripts.variantes_recuperacion --desarrollo ../$D/b2c_rankings_desarrollo_v4.json   --prueba ../$D/b2c_rankings_prueba_v4.json --propuesta 20x60x1:1x8 > ../$D/b2c_informe.md; cd ..

# 8. Parte C: migración 006, confirmación de la API y punta a punta (07/11/2026)
docker compose build backend                                              # imagen con el SDK anthropic
MSYS_NO_PATHCONV=1 docker compose exec -T db psql -q -v ON_ERROR_STOP=1 -U postgres -d cdss --single-transaction -f - < db/migraciones/006_parametros_generacion.sql
docker compose up -d backend
DATOS="$(pwd -W)/data/mediciones:/app/data/mediciones"
MSYS_NO_PATHCONV=1 docker compose run --rm --no-deps -T -v "$APP" -v "$DATOS" backend python -m app.scripts.confirmar_api   --confirmo-datos-sinteticos --salida data/mediciones/c0_confirmacion_api.json   # 3 solicitudes, menos de 1 centavo
MSYS_NO_PATHCONV=1 docker compose run --rm --no-deps -T -v "$APP" -v "$DATOS" backend python -m app.scripts.prueba_punta_a_punta   # cliente falso, 1 min
MSYS_NO_PATHCONV=1 docker compose run --rm --no-deps -T -v "$APP" -v "$DATOS" backend python -m app.scripts.prueba_punta_a_punta   --llm real --confirmo-datos-sinteticos                                      # API real, 12 casos; con --casos a,b,e solo esos

# 9. Parte C2: versión 5 y bonificación por edad (12/11/2026)              (unos 50 min)
docker compose up -d                                                      # entorno normal, int8; esperar healthy
MSYS_NO_PATHCONV=1 docker compose run --rm --no-deps -T -v "$APP" backend $MEDIR rankings --grupo desarrollo > $D/c2_rankings_desarrollo_v4.json   # 8 min, antes de reindexar
MSYS_NO_PATHCONV=1 docker compose run --rm --no-deps -T -v "$APP" -v "$DATOS" backend python -m app.scripts.prueba_punta_a_punta --etiqueta v4   # 1 min
docker compose build jobs                                                 # transcripciones y grupos_etarios.yaml van en la imagen
docker compose run --rm jobs python -m app.indexador cargar --manifiesto fuentes_iniciales.yaml --reindexar      # 8 min, versión 5
MSYS_NO_PATHCONV=1 docker compose run --rm jobs python -m app.indexador comparar --salida /datos/mediciones/c2_extraccion_v5.md
MSYS_NO_PATHCONV=1 docker compose run --rm --no-deps -T -v "$APP" backend $MEDIR rankings --grupo desarrollo > $D/c2_rankings_desarrollo_v5.json   # 8 min
cd backend && .venv/Scripts/python -m app.scripts.variantes_recuperacion --desarrollo ../$D/c2_rankings_desarrollo_v5.json --edad; cd ..
MSYS_NO_PATHCONV=1 docker compose run --rm --no-deps -T -v "$APP" backend $MEDIR edad --entorno normal-int8-v5 --pesos 0,0.1,0.3,0.5,0.7 > $D/c2_edad_pesos_v5.json   # 5 min por peso; recuperación real de R y V
for b in 0 0.5 0.7; do MSYS_NO_PATHCONV=1 docker compose run --rm --no-deps -T -v "$APP" -v "$DATOS" backend python -m app.scripts.prueba_punta_a_punta --bonificacion-edad $b --etiqueta v5_b$b; done
for b in 0 0.7; do MSYS_NO_PATHCONV=1 docker compose run --rm --no-deps -T -v "$APP" backend $MEDIR latencia --entorno normal-int8-v5-b$b --consultas 30 --configuraciones 8x256 --bonificacion-edad $b > $D/c2_latencia_normal_b$b.json; done
docker compose $B2MS up -d --force-recreate                               # esperar healthy
MSYS_NO_PATHCONV=1 docker compose $B2MS run --rm --no-deps -T -v "$APP" backend $MEDIR latencia --entorno b2ms-int8-v5 --frio --calentamiento 0 --consultas 30 --configuraciones 8x256 --bonificacion-edad 0.7 > $D/c2_latencia_b2ms.json   # 3 min
docker compose up -d --force-recreate
# Migración 009 (BONIFICACION_EDAD 0,7). Sin mediciones en curso: toma bloqueos sobre las tablas de conocimiento
MSYS_NO_PATHCONV=1 docker compose exec -T db bash /docker-entrypoint-initdb.d/04_migraciones.sh

# 10. Parte D1: consulta de punta a punta por el grafo (13/11/2026)                (unos 15 min)
MSYS_NO_PATHCONV=1 docker compose exec -T db bash /docker-entrypoint-initdb.d/04_migraciones.sh   # migración 010
docker compose build backend && docker compose up -d                       # LangGraph va en la imagen
MSYS_NO_PATHCONV=1 docker compose run --rm --no-deps -T -v "$APP" -v "$DATOS" backend python -m app.scripts.medir_consulta --repeticiones 3 --entorno normal --etiqueta normal
MSYS_NO_PATHCONV=1 docker compose run --rm --no-deps -T -v "$APP" -v "$DATOS" backend python -m app.scripts.medir_consulta --concurrentes 4 --entorno normal --etiqueta normal_4a_la_vez
docker compose $B2MS up -d --force-recreate                               # esperar el calentamiento en los logs del backend
MSYS_NO_PATHCONV=1 docker compose $B2MS run --rm --no-deps -T -v "$APP" -v "$DATOS" backend python -m app.scripts.medir_consulta --casos b --sin-calentar --entorno b2ms --etiqueta b2ms_frio
MSYS_NO_PATHCONV=1 docker compose $B2MS run --rm --no-deps -T -v "$APP" -v "$DATOS" backend python -m app.scripts.medir_consulta --repeticiones 3 --entorno b2ms --etiqueta b2ms
docker compose up -d --force-recreate
# Con el modelo real (solo el responsable): ... medir_consulta --llm real --confirmo-datos-sinteticos --entorno normal --etiqueta real

# 11. Parte D2: API por etapas, prompt v1.2 y B2ms con la API real (PowerShell; los corre el responsable)
docker compose build backend nginx; docker compose up -d                  # nginx.conf y el código van en las imágenes
docker compose run --rm --no-deps -T -v "${PWD}\data\mediciones:/app/data/mediciones" backend python -m app.scripts.comprobar_stream --confirmo-llamada-real
docker compose run --rm --no-deps -T -v "${PWD}\backend\app:/app/app:ro" -v "${PWD}\data\mediciones:/app/data/mediciones" backend python -m app.scripts.medir_consulta --llm real --confirmo-datos-sinteticos --versiones-prompt v1.1,v1.2 --entorno normal --etiqueta prompts_v1_1_v1_2
docker compose run --rm --no-deps -T -v "${PWD}\backend\app:/app/app:ro" -v "${PWD}\data\mediciones:/app/data/mediciones" backend python -m app.scripts.comparar_prompts   # textos v1.1 y v1.2, sin API
docker compose -f docker-compose.yml -f docker-compose.b2ms.yml up -d --force-recreate   # esperar «Calentamiento (intento» en docker compose logs backend
docker compose -f docker-compose.yml -f docker-compose.b2ms.yml run --rm --no-deps -T -v "${PWD}\backend\app:/app/app:ro" -v "${PWD}\data\mediciones:/app/data/mediciones" backend python -m app.scripts.medir_consulta --llm real --confirmo-datos-sinteticos --entorno b2ms --etiqueta b2ms_real
docker compose up -d --force-recreate

# 4. Volver al entorno normal e informe detallado
docker compose up -d
cd backend && .venv/Scripts/python -m app.scripts.informe_recuperacion   --calidad ../$D/b_calidad.json --negativos ../$D/b_calidad_fuera.json --umbral-longitud 384   --base-fp32 ../$D/b_calidad.json ../$D/b_calidad_latencia.json ../$D/b_calidad_fuera.json   --calidad-alternativas ../$D/b_alternativa_onnx-int8.json ../$D/b_alternativa_mmarco.json ../$D/b_alternativa_mmarco-onnx-int8.json   --latencia ../$D/b_latencia_normal.json ../$D/b_latencia_b2ms.json ../$D/b_latencia_b2ms_caras.json ../$D/b_latencia_b2ms_2hilos.json   --dominio ../$D/b_dominio.json > ../$D/b_informe.md
```
