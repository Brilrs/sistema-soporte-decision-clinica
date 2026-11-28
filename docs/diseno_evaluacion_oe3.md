# Diseño de la evaluación del OE3 (RAGAS y CUE)

Fecha: 26/11/2026. Rama `sprint-3-oe3-evaluacion`. Estado: **job implementado y probado solo con
el cliente falso** (`backend/app/evaluacion/`, guía de uso en `jobs/evaluacion_oe3/README.md`). No se
llamó a la API de Claude ni a ningún servicio de pago. La evaluación definitiva no se ejecutó.

Este documento fija qué se mide en el OE3, cómo se mide y con qué conjunto de casos. Completa la
Tabla 2 del OE2 («Métricas de evaluación del sistema») y las decisiones 12, 13 y 15 de
`docs/plan_sprint3.md`.

Cada regla lleva una de estas marcas:
- **OE2:** viene del documento del OE2.
- **RAG-X:** viene del artículo RAG-X (Sivakumar, Sugumaran y Qiang, arXiv 2603.03541), según la
  lectura que nos entregó el responsable. No está en el repositorio y no se volvió a verificar aquí.
- **Decisión:** la tomamos nosotros, con su motivo.
- **Pendiente:** falta información para decidirla (la ficha del CRED, la rúbrica o tu decisión). No
  se inventa una respuesta: queda abierta hasta entonces.

| Documento o carpeta | Qué contiene |
| --- | --- |
| `jobs/evaluacion_oe3/conjunto/esquema_caso.json` | Esquema de un caso (JSON Schema, sección 5) |
| `jobs/evaluacion_oe3/conjunto/evaluacion/` | Conjunto definitivo de 48 casos, uno por archivo YAML, revisados por la coordinación CRED (ficha firmada el 27/11/2026): el piloto (P01 a P12) y los 36 que lo completan (P13 a P48, sección 9). `piloto/` quedó sin casos |
| `docs/revision_casos_oe3.md` | Tabla de los 48 casos para la revisión de la coordinación CRED |
| `jobs/evaluacion_oe3/README.md` | Uso del job, fases, ensayo y pasos de la corrida definitiva |
| `backend/app/evaluacion/` | Código del job (sección 6) |
| `docs/cambios_respecto_al_OE2.md`, fila 170 | Registro de la implementación |
| `docs/cierre_sprint3.md`, sección 8 | Procedimiento para congelar el sistema |
| `docs/cambios_respecto_al_OE2.md`, fila 169 | Registro de este diseño |

## 1. Alcance y reglas

1. **Sistema congelado** (decisión 13). Antes de medir se sigue la sección 8 de
   `docs/cierre_sprint3.md`: sin trabajos de indexación, `VERSION_PROMPT` v1.1, respaldo verificado
   de ChromaDB y `pg_dump`, `CDSS_MODO_EVALUACION=true`, huella de la configuración y etiqueta de git.
   La huella se repite al terminar y debe ser la misma.
2. **Una sola corrida** del sistema sobre el conjunto de evaluación. El juez sí puede repetirse k
   veces sobre las salidas ya registradas (sección 7), sin volver a ejecutar el sistema.
3. **Solo datos sintéticos** (decisiones 12 y 13). Los pacientes son los ficticios de `seed_demo` o
   pacientes ficticios del propio conjunto. El juez recibe solo la consulta filtrada
   (`consulta.texto_filtrado`, nunca `texto_consulta`), la respuesta del sistema, el texto de los
   fragmentos enviados y la referencia del caso.
4. **Sin cambios durante la evaluación.** No se usan M11 (cargar, reintentar o retirar guías) ni la
   edición de M12. El modo de evaluación responde 423 en esas rutas, y la huella detecta cualquier
   otro cambio (por ejemplo, una migración o un cambio de `.env`).
5. **Limitaciones evaluadas como están** (decisión 15). P3, P4, P7 y P8 no se corrigen antes de medir.
6. **Base limpia.** La base de desarrollo ya no coincide con `seed_demo`: tiene 12 pacientes y datos
   completados a mano. La corrida se hace sobre una base nueva con `seed_demo` y los pacientes
   ficticios del conjunto. **Decisión**, porque las clasificaciones esperadas se calcularon con la
   semilla.
7. **Consultas de prueba fuera.** Las consultas con `modelo_llm = 'modelo-falso'` (cliente falso)
   nunca entran en las métricas.

## 2. Métricas

Las seis métricas de la Tabla 2 del OE2. La versión de RAGAS es la que resolvió la simulación de
instalación sin conflictos: 0.4.4, con `instructor>=1.10` fijado. Al construir la imagen apareció un
conflicto que la simulación y `pip check` no muestran: el `pyarrow` que elige el resolvedor (26)
exige NumPy 2 al importarse, y el backend fija NumPy 1.26.4. Se fija `pyarrow==25.0.0`, que funciona
con los dos y cumple lo que pide `datasets`.

| Métrica (OE2) | Implementación | Juez | Respuesta de referencia | Control en línea relacionado (OE2) |
| --- | --- | --- | --- | --- |
| Relevancia del contexto | RAGAS `ContextRelevance` | Sí (2 llamadas) | No | 6.3 |
| Faithfulness | RAGAS `Faithfulness` | Sí (2 llamadas) | No | 6.1 |
| Context Precision | RAGAS `ContextPrecisionWithReference` | Sí (1 llamada por fragmento) | Sí | |
| Context Recall | RAGAS `ContextRecall` | Sí (1 llamada) | Sí | |
| CUE | Propia (sección 3) | Sí; tiene una variante sin juez | Sí (pendiente, sección 3.1) | |
| Coherencia clínica | No la calcula el job | | | 6.2 |

- **Relevancia del contexto. Decisión:** se usa `ContextRelevance` de
  `ragas.metrics.collections`. Recibe la consulta y los fragmentos enviados, los califica con dos
  prompts de juez (escala 0, 1 o 2, promediada y llevada a 0 a 1), y no necesita referencia ni
  embeddings. Es la que corresponde a «si los fragmentos recuperados son pertinentes para la consulta».
  Por omisión, RAGAS repite cada juicio fallido hasta 5 veces y, si uno de los dos falla, promedia
  el que queda. El job la usa con `max_retries=1` (el juez ya reintenta una vez) y deja la métrica
  sin valor si el juez falló en cualquiera de sus llamadas. Lo mismo vale para las demás métricas: un
  `NaN` o un juicio fallido nunca entra como número.
- **Answer Relevancy no está en la Tabla 2. Decisión: se omite.** Necesita embeddings: habría que
  conectar bge-m3 del servicio `modelos` como embedder de RAGAS o usar un servicio externo. Además
  suma 3 llamadas al juez por consulta y mide otra cosa (si la respuesta responde a la pregunta). Si
  el asesor la pide, se agrega como métrica complementaria con bge-m3, nunca con un servicio externo.
- **Coherencia clínica:** sale de la validación con usuarios (OE3-B), no del job. El job solo
  informa como apoyo la exactitud de los campos deterministas (clasificación, derivación y estado) y
  el resultado del control 6.2 registrado.
- **Qué se le pasa a RAGAS. Decisión:**
  - Contextos: el texto exacto de los fragmentos enviados (`solicitud_enviada -> 'evidencia'`), en el
    orden F-01 a F-05. Context Precision depende de ese orden.
  - Respuesta: `resumen` más el texto de cada `recomendacion` de `respuesta_borrador` del intento que
    cuenta (sección 3.2), sin las etiquetas de cita.
  - Referencia: `respuesta_referencia` del caso.
- **Casos sin generación** (fuera de dominio, datos faltantes, tamizaje no vigente, solicitud
  bloqueada): no entran en RAGAS ni en CUE. Se informa aparte si el estado coincide con el esperado.
  Las consultas con EVIDENCIA_INSUFICIENTE que sí tienen respuesta del modelo entran en
  Faithfulness y en relevancia del contexto. No entran en Context Precision, Context Recall ni CUE
  cuando el caso no tiene referencia de evidencia (sin criterios).

## 3. CUE en detalle

### 3.1 CUE del OE2 (cifra principal)

**OE2:** «qué proporción del contexto enviado se aprovecha en la respuesta». La Tabla 2 la marca
como «Métrica propuesta» que requiere respuesta de referencia.

Definición por consulta (**decisión**, con la definición que fijaste):

```
CUE = fragmentos enviados que sustentan al menos una afirmación clave de la respuesta
      / fragmentos enviados
```

- «Enviados» son los fragmentos con `enviado_al_llm` del intento que cuenta, incluidos los de origen
  PUNTERO.
- Para cada fragmento enviado, el juez decide si sustenta alguna afirmación de la respuesta. Recibe
  solo datos sintéticos: consulta filtrada, respuesta y texto del fragmento.
- Agregado: el promedio por consulta (macro) es la cifra principal. Se informa también el cociente
  total (micro) y el número de consultas que quedan fuera por no tener fragmentos enviados.
- **Decisión (tomada): opción B.** Solo cuentan las afirmaciones de la respuesta que el juez
  empareja con una `afirmaciones_clave` del caso. Así se cumple el «requiere respuesta de referencia»
  de la Tabla 2, y un fragmento que solo sustenta una afirmación equivocada o ajena a la pregunta no
  cuenta como aprovechado. La opción A (todas las afirmaciones de la respuesta) se calcula y se
  informa al lado, sin reemplazar a la B.
- Una sola llamada del juez por consulta y repetición produce las dos: divide la respuesta en
  afirmaciones, empareja cada una con una afirmación clave (o con ninguna) e indica qué fragmentos
  la sustentan. La misma salida dice qué afirmaciones clave están presentes o contradichas, que es lo
  que usa la corrección (sección 3.3). Prompt y esquema en `backend/app/evaluacion/prompts_juez.py`.
- **Variante sin juez (decisión):** fragmentos enviados que aparecen en `cita_evidencia` del intento
  que cuenta, divididos por los enviados. Es reproducible y no cuesta, pero mide lo que el modelo
  citó, no lo que usó. Se informa al lado, sin reemplazar a la principal.

### 3.2 Intento y fragmentos que cuentan

**Decisión:** cuenta el intento de `recomendacion.id_intento`. Si la consulta no quedó verificada,
cuenta el último intento de la consulta. Los candidatos que no se enviaron (hasta 20 en
`fragmento_recuperado`) solo se usan para un diagnóstico aparte: si un criterio estaba entre los
candidatos y no se envió, la pérdida fue del reranker o de la selección, no de la búsqueda.

### 3.3 Diagnóstico de cuatro cuadrantes (RAG-X, complementario)

**RAG-X.** El artículo no da una fórmula para CUE. Define en prosa cuatro situaciones a partir del
éxito del recuperador, la adherencia del generador al contexto y la corrección de la respuesta.
Evalúa la adherencia con un juez LLM y un umbral de 0,7, y mide el éxito de recuperación con una
función binaria contra la respuesta correcta.

| Cuadrante (RAG-X) | Condición en el artículo | Cómo lo calculamos (decisión) |
| --- | --- | --- |
| Uso efectivo | El recuperador acertó y el generador usó el contexto | Recuperación exitosa y adherencia de 0,7 o más |
| Ceguera de información | Acertó y no lo usó | Recuperación exitosa y adherencia menor a 0,7, o estado EVIDENCIA_INSUFICIENTE |
| Acierto por suerte o alucinación | Falló, pero la respuesta fue correcta | Recuperación fallida y respuesta correcta |
| Rechazo correcto | Falló y el generador mostró baja adherencia | Recuperación fallida y adherencia menor a 0,7, o estado EVIDENCIA_INSUFICIENTE |

Las tres variables, como las definimos nosotros (**decisión**):

- **Éxito de recuperación:** están **todos** los criterios obligatorios del caso entre los
  fragmentos realmente enviados (`enviado_al_llm`), según la regla de la sección 4. Un criterio
  presente solo entre los candidatos no enviados no cuenta. Es la versión concreta de la «función
  binaria contra la respuesta correcta» del artículo: la respuesta correcta está representada por
  los criterios de evidencia del caso.
- **Corrección:** coinciden los campos deterministas (estado, `clasificacion_confirmada`,
  derivación) y la respuesta contiene todas las `afirmaciones_clave` sin contradecir ninguna (lo
  decide el juez). La cobertura parcial de las afirmaciones se informa aparte como fracción.
  Exigir todas es estricto a propósito, por simetría con el éxito de recuperación.
- **Adherencia:** puntaje de 0 a 1 que da el juez sobre cuánto se apoya la respuesta en los
  fragmentos enviados, con el umbral 0,7 del artículo. La faithfulness de RAGAS se informa al lado,
  pero **no es equivalente**: Faithfulness mide qué fracción de las afirmaciones de la respuesta se
  puede inferir del contexto, aunque la afirmación también sea de conocimiento general. La
  adherencia de RAG-X pregunta si el generador usó el contexto en vez de su conocimiento propio.
  La rúbrica está en la sección 3.4. **Propuesta, pendiente de tu revisión.**

Casos especiales (**decisión**):

- **EVIDENCIA_INSUFICIENTE con recuperación fallida:** cuenta como **rechazo correcto**, como
  pediste. Un caso sin criterios (no hay evidencia en las guías, como P07) se trata como
  recuperación fallida por definición.
- **EVIDENCIA_INSUFICIENTE con recuperación exitosa:** cuenta como **ceguera de información**: la
  evidencia llegó y el sistema no la usó. Es la lectura directa de la definición del artículo.
- **Recuperación fallida, respuesta incorrecta y adherencia de 0,7 o más:** el artículo define
  cuatro cuadrantes, y esta combinación no es ninguno de ellos. **Por decisión del proyecto** se
  informa aparte, como categoría propia (`incorrecta_con_contexto_fallido`: respuesta incorrecta
  apoyada en un contexto que no traía la evidencia), y no se reparte entre los cuatro.
- **Sin juicio** (`sin_juicio`): el juez no devolvió un JSON válido después de un reintento. El caso
  queda fuera de los cuadrantes y se cuenta en el informe.
- **Fuera de dominio** y otros estados sin generación: no entran en los cuadrantes. Se informa la
  exactitud del filtro de dominio (estado obtenido frente a esperado), con P3 como limitación
  conocida.
- **Fragmentos en inglés de la OMS:**
  - El juez recibe el texto original que recibió el modelo, no `extracto_traducido` (la traducción
    es para el usuario y no estaba en el contexto).
  - Los textos de anclaje en inglés se copian del fragmento y se comparan con la misma
    normalización que los demás.
  - Las afirmaciones clave van en español.
  - El informe desglosa por separado los casos con al menos un fragmento en inglés, porque el juez
    compara entre idiomas y los prompts de RAGAS están en inglés (sección 8).

**Agregado de las k repeticiones (decisión):** cada valor del juez se promedia entre las
repeticiones y se informa su desviación como medida de estabilidad. La respuesta cuenta como
correcta si lo es en más de la mitad de las repeticiones, y el cuadrante se calcula con la
adherencia media. Los cuadrantes de cada repetición quedan en el JSON.

### 3.4 Rúbrica del juez de adherencia (propuesta, pendiente de tu revisión)

Texto completo en `SISTEMA_ADHERENCIA` de `backend/app/evaluacion/prompts_juez.py`. El juez recibe
la consulta filtrada, la respuesta y los fragmentos enviados, y nada más.

- **Qué se le pregunta:** «¿En qué medida el contenido clínico de la respuesta proviene de los
  fragmentos enviados, y no del conocimiento propio del modelo?». No juzga si la respuesta es
  correcta, sino de dónde sale. Eso la separa de la corrección y de Faithfulness.
- **Escala de 0 a 1, con dos decimales, anclada en cuatro puntos:**

| Puntaje | Significado |
| --- | --- |
| 1,0 | Todas las indicaciones clínicas (dosis, plazos, controles, criterios, derivación) se apoyan en los fragmentos, y la respuesta usa la información pertinente que traen |
| 0,7 | Casi todas se apoyan; lo que no se apoya es general y no cambia la conducta clínica |
| 0,4 | Mezcla: alguna indicación clínica importante no está en los fragmentos, o la respuesta ignora un fragmento pertinente |
| 0,0 | La respuesta no usa los fragmentos, o los contradice |

- **Umbral 0,7** (del artículo RAG-X), inclusivo: 0,7 o más es adherencia alta.
- **Abstención:** si la respuesta solo declara evidencia insuficiente, el puntaje es alto si de
  verdad los fragmentos no traían la información y bajo si la traían. En los cuadrantes, el estado
  EVIDENCIA_INSUFICIENTE se decide por el éxito de recuperación (sección 3.3), así que este puntaje
  solo se informa.
- **Salida:** `puntaje`, `indicaciones_sin_respaldo` (lista) y una `justificacion` breve.
- Al revisarla, lo que conviene mirar es si el punto 0,7 coincide con lo que el equipo clínico
  consideraría «usar el contexto». Si la rúbrica cambia, cambia su SHA-256 en el informe y hay que
  repetir el ensayo con el cliente falso antes de congelar.

## 4. Equivalencia de evidencia

**Decisión:** la evidencia esperada de cada caso se divide en **criterios atómicos**, una sola idea
clínica por criterio. Por ejemplo, para un tratamiento: dosis, duración y control de Hb.

- Cada criterio es **obligatorio u opcional**. El éxito de recuperación solo mira los obligatorios.
  Los opcionales completan la cobertura informada.
- Cada criterio tiene una o más **alternativas equivalentes**. Cada alternativa tiene el documento
  (`codigo_documento`), las páginas, el numeral o la tabla, y un **texto de anclaje copiado del
  fragmento indexado**.
- **Regla:** «y» entre los criterios obligatorios, «o» entre las alternativas de un mismo criterio.
  Así una recuperación parcial (por ejemplo, la dosis sin los controles) no cuenta como éxito, como
  sí ocurría con el criterio de los conjuntos de desarrollo, que aceptaba un solo fragmento con
  alguna alternativa.
- **Cobertura parcial:** criterios obligatorios cumplidos divididos por los obligatorios del caso.
  Se informa aparte como fracción y nunca se suma al éxito.
- **Solo fragmentos vigentes:** el fragmento debe estar vigente, ser de la última
  `version_indexacion` de su documento, y el documento debe estar VIGENTE. Un texto de la NTS
  reemplazado por la RM 429 no cuenta aunque diga lo mismo. Por ejemplo, la Tabla N° 4 original de
  la NTS (página 11) o la Tabla N° 8 original (página 13): los dos fragmentos existen en la base con
  `vigente = false`.
- **La equivalencia clínica la confirma la ficha del CRED.** Hasta entonces, las alternativas son
  una propuesta. Ejemplos de equivalencias pendientes:
  - la Tabla N° 20 frente al texto que la resume;
  - el ajuste de la OMS en g/L frente al de la RM en g/dL;
  - la Table B de la OMS 2016 frente a la Tabla N° 8 de la RM 429.
- **Marca `equivalencia_pendiente` (decisión):** una alternativa puede llevar
  `equivalencia_pendiente: true` (campo opcional del esquema). El cruce sigue siendo textual y no
  convierte unidades. Si un criterio obligatorio solo se cumple con alternativas marcadas, el éxito
  cuenta, pero el informe lo separa como «éxito que depende de una equivalencia pendiente». En el
  piloto están marcadas las tres alternativas de la OMS 2024 en g/L (P04, P10 y P12, que pasaron a
  `version_caso: 2`). La ficha del CRED del 27/11/2026 confirmó la equivalencia de la Table 4 de la
  OMS 2024 con la Tabla N° 1 de la RM 429 en los seis casos de altitud (P04, P10, P12, P17, P26 y
  P32): la marca se quitó y hoy ninguna alternativa del conjunto la lleva.

### 4.1 Cómo se hace el cruce sin columna de numeral

La base no guarda el numeral, y 74 de los 185 fragmentos vigentes no tienen sección (casi todos de
la OMS). Por eso el emparejamiento no puede depender de la sección. **Decisión:** un fragmento
enviado cumple una alternativa si se cumplen las tres condiciones:

1. su documento es el de la alternativa;
2. su rango de páginas (`pagina_inicio` a `pagina_fin`) se superpone con el de la alternativa;
3. su texto normalizado **contiene** el texto de anclaje normalizado.

La normalización aplica NFKC de Unicode, lleva a «-» todos los guiones y rayas (puntos de código
U+2010 a U+2015 y U+2212), lleva las comillas tipográficas a las rectas, colapsa los espacios y
saltos de línea, y no distingue mayúsculas. El numeral se guarda como dato informativo y para la
ficha del CRED, no para el cruce.

Riesgos de este emparejamiento y cómo se mitigan:

| Riesgo | Mitigación |
| --- | --- |
| Errores de OCR en el texto indexado («Tabla N” 18», «Fénico») | Copiar el anclaje del fragmento indexado, no del PDF, y elegir tramos sin errores |
| Un anclaje que cruza el límite entre dos fragmentos, o una tabla partida («parte 1 de 2») | Anclajes cortos: una oración o una fila de tabla |
| El mismo texto en dos lugares (por ejemplo, «Concluido el tratamiento...» en B.2 y B.3 de la misma página) | Incluir lo que los distingue, como el punto final en P02, y comprobar que el anclaje encaje en un solo fragmento |
| Duración o dosis repetidas en tablas vecinas (OMS 2016, Tables A, B y C) | Anclar desde el dato que identifica la fila (P09, criterio C3) |
| Reindexar cambia los límites de los fragmentos | Volver a comprobar todos los anclajes contra el índice congelado antes de la corrida; un anclaje que no encaja detiene la evaluación |
| Las tablas transcritas no se parecen al PDF (filas con «\|») | Es el texto que recibió el modelo; la ficha muestra la tabla del PDF al lado |
| Falso negativo si el modelo recibió el contenido con otra redacción | Agregar la otra redacción como alternativa, con la confirmación de la ficha |

La comprobación de los 45 anclajes del piloto se hizo con un script fuera del repositorio, con
consultas de solo lectura: cada uno encaja en exactamente un fragmento vigente del documento y las
páginas indicadas, y en ningún fragmento no vigente. Esa comprobación pasa a ser el primer paso de
`dataset.py` (sección 6).

## 5. Estructura del conjunto

**Ubicación (decisión):** `jobs/evaluacion_oe3/conjunto/`. Va fuera de `backend/app/` porque el
Dockerfile copia `app` en la imagen: revisar el conjunto después de la ficha no debe cambiar la
imagen congelada. `jobs/` ya es la carpeta de los trabajos bajo demanda (indexador, respaldo y
evaluación), y `data/` no está en git. El job monta la carpeta en solo lectura, como `data/guias`.

Un archivo YAML por caso, validado contra `esquema_caso.json`:

| Campo | Contenido |
| --- | --- |
| `id`, `version_caso`, `conjunto` | `OE3-P01` a `OE3-P48`: los casos nacieron en el piloto y conservan el prefijo P en `evaluacion/`, porque la ficha firmada usa esos ids (`OE3-E001` queda para casos agregados después); la versión sube con cada cambio |
| `origen`, `origen_detalle` | `desarrollo_reutilizado` o `nuevo`, con el archivo de origen |
| `tipos` | Etiquetas para el desglose (clasificación, derivación, calendario, altitud, inglés, etc.) |
| `paciente` | `seed_demo` con DNI ficticio y fecha de tamizaje, o `ficticio` con sus datos (sin nombre) |
| `fecha_referencia`, `consulta` | Fecha contra la que se evalúa la vigencia y texto sintético de la consulta |
| `estado_esperado`, `clasificacion_esperada`, `requiere_derivacion`, `evidencia_suficiente_esperada` | Campos deterministas; `null` si no se evalúan |
| `criterios` | Criterios atómicos con `obligatorio` y sus alternativas (sección 4) |
| `respuesta_referencia`, `afirmaciones_clave` | Redactadas solo con lo que dicen las guías indexadas |
| `revisado`, `revisado_por`, `fecha_revision`, `observaciones_revision` | `false` y `null` hasta la ficha; desde la ficha del 27/11/2026, `true`, «Coordinador CRED, Centro de Salud San Luis» y `2026-11-27`. `revisado_por` es el cargo, no el nombre; con `revisado: true` el cargo y la fecha son obligatorios |
| `notas` | Vigencia, equivalencias y riesgos del caso |

- **SHA-256 del conjunto (decisión):** no va dentro de cada caso, porque cambiaría al escribirlo. Se
  calcula al congelar el conjunto y se guarda en el informe y junto a la etiqueta de git. Algoritmo
  exacto (`dataset.huella_archivo` y `dataset.huella_conjunto`):
  1. Para cada archivo `*.yaml` de la carpeta del grupo (todos, aunque se elija un subconjunto de
     ids), se leen sus bytes y se normaliza el fin de línea: primero cada CRLF (bytes 0D 0A) pasa a
     LF (0A) y después cada CR suelto (0D) pasa a LF. Ningún otro byte cambia: no se toca la
     codificación, los espacios finales ni la última línea.
  2. La huella del archivo es el SHA-256 en hexadecimal (minúsculas) de esos bytes normalizados.
  3. Se arma una línea por archivo, «nombre del archivo (sin carpeta), dos espacios, huella, LF»,
     y las líneas se ordenan por nombre (orden de los puntos de código).
  4. La huella del conjunto es el SHA-256 en hexadecimal del texto de todas las líneas unidas,
     codificado en UTF-8.

  El esquema (`esquema_caso.json`) tiene su propia huella, con la misma normalización del paso 1.
  Con un archivo en LF su huella es el SHA-256 de sus bytes tal cual, así que la huella coincide con
  la de una copia de git; con CRLF o una mezcla da la misma. `.gitattributes` además fuerza LF en
  `jobs/evaluacion_oe3/conjunto/**`. Las pruebas comprueban que LF, CRLF y una mezcla dan la misma
  huella y que un cambio de contenido da otra.
- **Los casos reutilizados del desarrollo no son independientes.** Las 35 consultas R y V ajustaron
  y validaron la recuperación, y `casos_e2e.yaml` se usó en las pruebas de punta a punta. Cada caso
  lo declara en `origen`, y el informe da las cifras por separado para reutilizados y nuevos. P06
  es nuevo, pero la regla de la fila 165 se creó para ese tipo de pregunta.
- **Todo se mide con el sistema congelado**, una sola vez.
- **Revisión (decisión):** la hace la coordinación CRED con una ficha por caso. La ficha muestra la
  consulta, el paciente, los campos esperados, cada criterio con el texto del PDF y la respuesta de
  referencia, y la coordinación marca «de acuerdo» o propone un cambio. **Hecha:** la coordinación
  CRED del Centro de Salud San Luis firmó la ficha el 27/11/2026 sobre la tabla de
  `docs/revision_casos_oe3.md`: los 48 casos quedaron «De acuerdo», sin cambios. Cada caso lleva
  `revisado: true`, `revisado_por` con el cargo y `fecha_revision: 2026-11-27`.

### 5.1 Piloto (12 casos)

Todos los pacientes son ficticios. Hay 11 casos sobre pacientes de `seed_demo` y 1 con un paciente
ficticio nuevo (DNI ficticio con prefijo 89). Fecha de referencia: 20/10/2026.

| Caso | Clasificación | Qué prueba | Origen |
| --- | --- | --- | --- |
| P01 | Sin anemia, 9 meses | Preventiva de 6 a 11 meses y Tabla N° 4 vigente | `casos_e2e` a |
| P02 | Leve, 14 meses | Dosis de tratamiento (Tabla N° 17) | `casos_e2e` b |
| P03 | Moderada, 20 meses | Tratamiento y controles (Tabla N° 20 o su texto) | `casos_e2e` c |
| P04 | Moderada por altitud (Puno), 18 meses | Ajuste RM 429 u OMS 2024 (inglés) y tratamiento | `casos_e2e` e |
| P05 | Severa con derivación, 26 meses | Referencia inmediata | `casos_e2e` d |
| P06 | Severa con derivación, 26 meses | Controles en un caso severo: la derivación debe aparecer | Nuevo |
| P07 | Moderada, 20 meses | EVIDENCIA_INSUFICIENTE (sin criterios) | `casos_e2e` j |
| P08 | No se evalúa | FUERA_DE_DOMINIO | `casos_e2e` h |
| P09 | Sin anemia, 49 meses | Recomendación de la OMS 2016 en inglés | `casos_e2e` l |
| P10 | Leve por altitud (Huancayo), 40 meses | Dosis y controles de 36 a 59 meses | Nuevo |
| P11 | Sin anemia, 49 meses | Preventiva con la Tabla N° 8 de la RM 429 (vigencia) | Nuevo |
| P12 | Severa por altitud (Puno), 11 meses, ficticio | Derivación, dosis, controles y ajuste | Nuevo |

**Decisión (tomada): opción A.** El piloto se prueba solo con el cliente falso del modelo de
lenguaje y con el juez falso, y **nunca se corre con el modelo real**: así puede entrar al conjunto
final. El job lo impide: `ejecutar --llm real` rechaza el grupo `piloto`. El ensayo deja un informe
rotulado «ENSAYO CON CLIENTE FALSO: los números no tienen valor».

## 6. Arquitectura del job

Paquete `backend/app/evaluacion/` (implementado). Sigue el patrón de `app/indexador` y
`app/respaldo`: `python -m app.evaluacion <fase>`. Uso en `jobs/evaluacion_oe3/README.md`.

| Módulo | Función |
| --- | --- |
| `dataset.py` | Lee y valida los YAML contra el esquema (validador propio del subconjunto de JSON Schema que usa el esquema, para no agregar `jsonschema` al sistema) y calcula las huellas SHA-256. `validar --con-base` comprueba que cada anclaje encaje en un solo fragmento vigente |
| `ejecutar.py` | Crea los pacientes ficticios y ejecuta cada caso **con el grafo real** (`eventos_de` de `app/services/consultas.py`), una sola vez: si la carpeta ya tiene `ejecucion.jsonl`, no vuelve a ejecutar. Cliente falso del proyecto por omisión; el real exige confirmar datos sintéticos y nunca acepta el piloto |
| `extraer.py` | **Solo lectura** con `cdss_generacion` en transacciones READ ONLY: consulta filtrada, estado, clasificación, intento que cuenta, `respuesta_borrador`, fragmentos enviados y candidatos con su vigencia y el texto de `solicitud_enviada`, citas, verificadores 6.1 a 6.3, tokens y costo |
| `juez.py` | Cliente intercambiable: `JuezFalso` (determinista, sin red) y `JuezAnthropic` (preparado, no usado). Caché en disco por SHA-256 de (modelo, tarea, sistema, esquema, entrada, repetición, razonamiento, esfuerzo); registro JSONL de cada llamada con tokens y costo; un reintento si la respuesta no es JSON; solo acepta casos del conjunto cargado |
| `prompts_juez.py` | Prompts y esquemas de los juicios propios (afirmaciones y adherencia), con su SHA-256 |
| `ragas_metricas.py` | Las cuatro métricas de RAGAS de la sección 2. Cada llamada de RAGAS pasa por el juez anterior (`AdaptadorRagas`), así usa la misma caché, registro y cliente |
| `cue.py` | Normalización, cruce de criterios, éxito de recuperación, CUE (B, A y por citas), corrección y cuadrantes |
| `juzgar.py` | Lo determinista una vez por caso y lo del juez k veces, con el agregado |
| `informe.py` | Informe reproducible (sección 7) |

- **Fases separadas (decisión):** validar, ejecutar, extraer, juzgar e informe, más
  `comparar-jueces` y `ensayo` (las cuatro fases con el cliente y el juez falsos). La ejecución del
  sistema ocurre una vez; juzgar se puede repetir sobre la misma extracción sin tocar el sistema.
- **Extracción con `cdss_generacion` y no con el auditor (decisión):** la vista
  `v_auditoria_consulta` no trae la respuesta del modelo ni los ids de los fragmentos, que el cruce
  de criterios necesita. `cdss_generacion` ya puede leer esas tablas, no puede leer la identidad del
  paciente ni `texto_consulta`, y se usa en transacciones de solo lectura.
- **Imagen propia (decisión):** destino `evaluacion` en `backend/Dockerfile` (a partir de `base`)
  con `backend/requirements-evaluacion.txt` (`ragas==0.4.4`, `instructor>=1.10` y `pytest` para las
  pruebas de RAGAS), y servicio `evaluacion` con el perfil `evaluacion` en `docker-compose.yml`. El
  código de `app/evaluacion/` está excluido del contexto principal en `backend/.dockerignore` y entra
  solo en ese destino, por el contexto adicional `codigo_evaluacion`. Así las imágenes `api` y `jobs`
  no cambian: reconstruidas, dan el mismo id de imagen.
- **Variables del servicio:** `RAGAS_DO_NOT_TRACK=true` (también en la imagen; `ragas_metricas.py` se
  niega a calcular si la telemetría no está apagada), la clave de Anthropic solo ahí, las conexiones
  del backend y el conjunto montado en solo lectura. Salidas en `data/evaluacion_oe3/`.
- **Juez configurable (decisión):** `--modelo`, `--razonamiento` (valor de `thinking.type`; sin la
  opción no se envía), `--esfuerzo`, `--max-tokens` y `--k` (3 por omisión). **Sin temperatura
  fija:** Sonnet 5.5 rechaza valores distintos del predeterminado (fila 6), y el juez nunca la envía.
  Los precios por modelo están en `PRECIOS_USD_MTOK` de `juez.py` y van en el informe.
- **Comparación Sonnet frente a Haiku:** `comparar-jueces --modelos claude-sonnet-5-5,claude-haiku-5-5`
  juzga la misma extracción con cada modelo y compara medias y cuadrantes. Está preparada y probada
  solo con el juez falso; con la API la ejecuta el responsable.
- **Pendiente:** el modelo del juez, si razona y el valor final de k, que se deciden con esa
  comparación.

## 7. Informe reproducible

El informe guarda:
- **Versión:** etiqueta de git del commit evaluado, huella de la configuración al empezar y al
  terminar (deben coincidir), SHA-256 de cada caso y la huella global del conjunto, y `pip freeze`
  de la imagen de evaluación.
- **Juez:** modelo, parámetros (razonamiento, esfuerzo, máximo de tokens, sin temperatura), versión
  de RAGAS y SHA-256 de los prompts propios.
- **Salidas crudas en JSONL:** por caso, la ejecución del sistema, la extracción y cada llamada del
  juez con su repetición, tokens y costo.
- **k repeticiones del juez:** la media por caso, más la dispersión entre repeticiones como medida
  de estabilidad.
- **Intervalos de confianza al 95 %:** Wilson para las proporciones (éxito de recuperación,
  corrección, estado esperado) y bootstrap por casos (10 000 remuestreos, semilla fija) para las
  medias (RAGAS y CUE).
- **Desgloses:** por tipo de consulta (etiquetas `tipos`), por origen (reutilizado o nuevo), con o
  sin fragmento en inglés, y por cuadrante. La tabla de cuadrantes incluye la quinta categoría.
- **Costos reales** del sistema y del juez frente a la estimación, y cualquier desviación del
  procedimiento.

## 8. Riesgos y limitaciones que se declaran

| Riesgo | Efecto | Cómo se declara o mitiga |
| --- | --- | --- |
| Sonnet juzga a Sonnet | Sesgo a favor de las respuestas del mismo modelo | Declararlo; comparar con Haiku en el piloto; variante de CUE sin juez |
| Tamaño muestral | Con 48 casos y un acierto del 85 %, el intervalo de Wilson es de unos ±10 puntos (±12 con 35, ±9 con 60) | Informar siempre el intervalo, no solo la cifra |
| Juez no determinista y sin temperatura fija | Dos corridas del juez pueden diferir | k repeticiones, dispersión informada y caché |
| Prompts de RAGAS en inglés | Juicio entre idiomas con contenido en español (y fragmentos en inglés) | Desglose de los casos con inglés; no se traducen los prompts para no apartarse de RAGAS |
| Base de pacientes pequeña | 10 pacientes en la semilla y un solo caso severo | Pacientes ficticios nuevos para los casos severos y de derivación |
| Esperados sin revisión clínica externa | Criterios y referencias propuestos por el equipo | Revisados por la coordinación CRED (ficha del 27/11/2026, los 48 «De acuerdo»); se informa la fecha de la revisión. Es una revisión del propio establecimiento, no un panel externo |
| Casos reutilizados del desarrollo | Sobreestiman el desempeño | Cifras por separado para reutilizados y nuevos |
| Puntaje del reranker según el lote | El umbral de 0,15 hereda esa dependencia | Limitación conocida (cierre, sección 7) |
| P3, P4, P7 y P8 | Errores conocidos que se miden como están (decisión 15) | Se citan al interpretar los fallos |

## 9. Tamaño objetivo del conjunto

**Propuesta: 48 casos.** Con 48, el intervalo de Wilson queda cerca de ±10 puntos. Con unas 13
llamadas al juez por caso, cada pasada cuesta del orden de US$ 4,5 con Sonnet 5.5 (unos US$ 13,5
con k = 3) o US$ 0,2 con Haiku 5.5. A eso se suma la generación del sistema, unos US$ 1,3. Son
estimaciones de los tokens ya registrados, más un 20 a 30 % por reintentos.

| Grupo | Casos | De las 35 de desarrollo | De `casos_e2e` | Nuevos |
| --- | --- | --- | --- | --- |
| Sin anemia (preventiva por tramo de edad, menor de 6 meses) | 8 | 3 | 2 | 3 |
| Anemia leve | 8 | 2 | 1 | 5 |
| Anemia moderada (2 por altitud) | 8 | 2 | 2 | 4 |
| Anemia severa con derivación | 8 | 1 | 1 | 6 |
| Calendario de Hb (Tabla N° 4 y Tabla N° 20) | 6 | 2 | 0 | 4 |
| Evidencia insuficiente | 6 | 1 | 1 | 4 |
| Fuera de dominio | 4 | 1 | 1 | 2 |
| **Total** | **48** | **12** | **8** | **28** |

- Las 35 de desarrollo no tienen paciente: al reutilizarlas se les asigna un paciente de la semilla
  compatible con la pregunta.
- Al menos 4 casos, repartidos entre los grupos, deben depender de un fragmento en inglés de la OMS.
- Los 6 casos severos nuevos usan pacientes ficticios (la semilla tiene uno solo). Combinan los
  tramos de 6 a 23 y de 24 a 59 meses, y la anemia severa por ajuste de altitud.
- Con la opción A del piloto (sección 5.1), los 8 casos del piloto que vienen de `casos_e2e` y los
  4 nuevos se cuentan dentro de estos 48.
- **Composición definida (26/11/2026, fila 172):** los 36 casos que faltaban son P13 a P48, con el
  mismo esquema que el piloto. Dependen de un fragmento en inglés de la OMS P09, P14, P21 y P30. Los
  130 anclajes encajan cada uno en exactamente un fragmento vigente de la base del ensayo y en
  ninguno no vigente (`validar --con-base`). Las preguntas de evidencia insuficiente se comprobaron
  con búsquedas en el texto de las guías; cada caso anota cómo. Tabla para la ficha en
  `docs/revision_casos_oe3.md`. Huella del conjunto al 27/11/2026:
  `9cae4f53cd1f012adbd3c49de398410a8c3826514ab52fef88be3ec85e6302a0`.
- **Decisión (fin de línea, 27/11/2026):** la huella se calculaba sobre los bytes de cada archivo, y
  en una copia de Windows con `core.autocrlf=true` el mismo contenido daba otra huella (en CRLF,
  `613f3349...`; con los 12 del piloto en CRLF y los 36 nuevos en LF, `091e7e5b...`). Ahora el job
  normaliza el fin de línea antes de calcular (sección 5) y `.gitattributes` fuerza LF en
  `jobs/evaluacion_oe3/conjunto/**`. La huella normalizada es la de todo en LF, `9cae4f53...`, en
  cualquier copia.
- **Decisión (desglose por origen):** 20 reutilizados del desarrollo y 28 nuevos, como en la tabla.
  Los 20 reutilizados son 12 consultas de desarrollo y los 8 casos del piloto que vienen de
  `casos_e2e`. El informe da las cifras de cada origen por separado.
- **Decisión (P41 y P46):** ninguna de las 35 consultas R y V es de evidencia insuficiente ni de
  fuera de dominio. Por eso P41 (evidencia insuficiente) y P46 (fuera de dominio) salen de las
  listas `dominio.dentro` y `dominio.fuera` de `consultas_validacion.yaml`, que se usaron para
  calibrar el filtro de dominio: cuentan como `desarrollo_reutilizado`. Las otras 10 son consultas R
  o V.
- **Decisión (pacientes de los reutilizados):** 9 de las 12 consultas de desarrollo reutilizadas
  (P13, P14, P18, P19, P24, P25, P30, P35 y P36) usan pacientes ficticios, porque la semilla no tiene
  uno compatible con la pregunta (edad o clasificación); P15, P41 y P46 usan pacientes de la semilla.
  La consulta original se mantiene sin cambios. Los 8 casos de `casos_e2e` usan los pacientes de la
  semilla de origen.
- **Decisión (carpeta y etiqueta, aplicada el 27/11/2026):** los 48 casos permanecieron en
  `jobs/evaluacion_oe3/conjunto/piloto/` hasta la revisión del CRED. Después pasaron a
  `jobs/evaluacion_oe3/conjunto/evaluacion/` (con `git mv`) con los mismos ids (solo cambia el campo `conjunto` a `evaluacion`, que el cargador exige igual a la
  carpeta) y una etiqueta de git propia que registra el SHA-256 final del conjunto. El job no
  ejecuta el grupo `piloto` con el modelo real, así que la corrida única de OE3-A se hace sobre
  `evaluacion/`.
- **Revisión del CRED (27/11/2026):** los 48 «De acuerdo», sin cambios de contenido. En cada caso
  solo cambiaron `conjunto` (`evaluacion`), `revisado` (`true`), `revisado_por` (el cargo) y
  `fecha_revision` (`2026-11-27`). El grupo por omisión del job pasó a ser `evaluacion`; `piloto`
  sigue siendo un grupo válido (y nunca se corre con `--llm real`), pero no tiene casos y cargarlo
  da «No hay casos». El punto 1 de la ficha (la Table 4 de la OMS 2024 equivale a la Tabla N° 1 de
  la RM 429 en el ajuste por altitud de P04, P10, P12, P17, P26 y P32) quedó aprobado con el
  «De acuerdo»: en esos seis casos se quitó la línea `equivalencia_pendiente: true`, sin otro
  cambio. Huella del conjunto `evaluacion` (48 casos):
  `49628174086e9ce69cdf1096de1b9e3bab6b99284ff3d41f326f78363ed214ac`. Las anteriores eran
  `eb8c9502...` (`evaluacion/` revisado, con la marca) y `9cae4f53...` (`piloto/` sin revisar).
- **Pendiente:** la etiqueta de git propia que registra esta huella, antes de la corrida única de
  OE3-A.

## 10. Resumen de decisiones

| Decisión | Estado |
| --- | --- |
| CUE del OE2 como cifra principal y cuadrantes RAG-X como diagnóstico | Tomada (responsable) |
| Revisión clínica por la coordinación CRED con una ficha | Hecha: ficha firmada el 27/11/2026, los 48 casos «De acuerdo» sin cambios |
| Relevancia del contexto con `ContextRelevance`; Answer Relevancy omitida | Adoptada |
| Éxito de recuperación con todos los obligatorios entre los enviados; «y» entre criterios y «o» entre alternativas | Adoptada |
| Cruce por documento, páginas y texto de anclaje normalizado | Adoptada |
| Corrección con campos deterministas más todas las afirmaciones clave | Adoptada |
| EVIDENCIA_INSUFICIENTE: rechazo correcto si falló la recuperación, ceguera si acertó | Adoptada |
| Categoría propia `incorrecta_con_contexto_fallido`: el artículo define cuatro cuadrantes y esta combinación se informa aparte | Tomada (responsable), por decisión del proyecto |
| Fragmentos en inglés en su texto original, con desglose propio | Adoptada |
| Conjunto en `jobs/evaluacion_oe3/conjunto/`, imagen y perfil `evaluacion` propios | Adoptada e implementada |
| CUE del OE2 con la opción B; A y la variante por citas al lado | Tomada (responsable) |
| Piloto solo con el cliente falso, nunca con el modelo real (opción A) | Tomada (responsable); el job lo impide |
| Juez con modelo, razonamiento y k configurables (k = 3 por omisión), sin temperatura | Tomada (responsable) |
| Extracción con `cdss_generacion` en solo lectura | Adoptada |
| Agregado de las k repeticiones (media, mayoría para la corrección, cuadrante con la adherencia media) | Adoptada |
| Marca `equivalencia_pendiente` en las alternativas, con el éxito que depende de ella informado aparte | Adoptada |
| Rúbrica del juez de adherencia (sección 3.4) | Propuesta en uso; pendiente de tu revisión |
| Modelo juez, razonamiento y valor final de k | Pendiente (comparación Sonnet frente a Haiku, preparada, sin ejecutar) |
| Equivalencias entre guías (OMS y norma nacional, tabla y texto, g/L y g/dL) | Confirmada por el CRED el 27/11/2026 |
| Composición final de los 48 casos | Definida (26/11/2026, P01 a P48, fila 172) y revisada por el CRED (27/11/2026) |
| Carpeta del conjunto: `piloto/` hasta la revisión del CRED y después `evaluacion/` con los mismos ids y una etiqueta con el SHA-256 final | Tomada (responsable); movida a `evaluacion/` el 27/11/2026, etiqueta pendiente |
| P41 y P46 de las listas de dominio de `consultas_validacion.yaml`; 9 de las 12 consultas reutilizadas con pacientes ficticios; 20 reutilizados y 28 nuevos | Tomada (responsable) |
| Huella del conjunto con el fin de línea normalizado (CRLF y CR a LF) y LF forzado en `.gitattributes` | Adoptada e implementada (27/11/2026) |
