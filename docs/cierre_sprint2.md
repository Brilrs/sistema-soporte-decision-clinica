# Cierre del Sprint 2: base de conocimiento y motor RAG

Fecha de cierre: 17/11/2026 (parte F3).

Este documento resume, para la revisión con el asesor, qué se entregó en el Sprint 2, cómo se
verificó, qué se midió y qué queda pendiente. No repite el detalle técnico: remite a los
documentos del repositorio donde está cada dato.

| Documento | Qué contiene |
| --- | --- |
| [`cambios_respecto_al_OE2.md`](cambios_respecto_al_OE2.md) | Cada diferencia con el documento de diseño (OE2), con su motivo y estado (filas 1 a 103), las diferencias con los mockups y los pendientes P1 a P14 |
| [`mediciones_sprint2.md`](mediciones_sprint2.md) | Mediciones de latencia, calidad de la recuperación, memoria y costo, con el procedimiento para repetirlas |
| [`contrato_consultas.md`](contrato_consultas.md) y [`contrato_conocimiento.md`](contrato_conocimiento.md) | Contratos de la API de consultas y de la base de conocimiento (M11) |
| [`../jobs/README.md`](../jobs/README.md) | Indexador de guías, transcripciones de las tablas críticas y medición de la indexación |
| [`mejoras_despliegue.md`](mejoras_despliegue.md) | Mejoras pendientes para el despliegue en Azure |

## 1. Qué se entregó

El Sprint 2 abarcaba las historias HU03, HU06 a HU09, HU12, HU15 y HU16 (en el OE2, HU16 es
«Recibir aviso de evidencia insuficiente», la pantalla M07). Se entregaron todas, más el registro
de la decisión clínica, que estaba previsto para el Sprint 3 y se adelantó porque cierra el flujo
de la consulta. El registro de la decisión no tiene historia propia en el OE2: es la acción
«Registrar decisión clínica» de M05 y M07 (RF8).

### Motor RAG (sin pantalla propia)

- **Base de conocimiento:** las 4 guías de nivel 1 (NTS 213-MINSA/DGIESP-2024, su modificatoria RM
  429-2024/MINSA, OMS 2024 y OMS 2016) indexadas en la versión 5: 202 fragmentos de la última
  versión, 183 vigentes. Las tablas con valores clínicos se transcribieron y verificaron contra la
  imagen del PDF en lugar de tomarlas del OCR (filas 27 y 28 de `cambios_respecto_al_OE2.md`).
- **Consulta de punta a punta:** grafo de LangGraph con los 8 nodos de la Tabla 11 (validar,
  clasificar, normalizar, recuperar, proteger, generar, verificar y salida), cada uno con el usuario
  de base de datos que le corresponde. El texto original y los datos del paciente no salen del
  servidor: al modelo de lenguaje solo llega una solicitud mínima desidentificada, y un control
  previo bloquea el envío si aparece un identificador.
- **Indexador permanente:** el servicio `indexador` procesa las guías cargadas desde M11.

### Pantallas

| Pantalla | Historia | Qué hace | Sprint |
| --- | --- | --- | --- |
| M01 Inicio de sesión | HU01 | Acceso con bloqueo tras 5 intentos fallidos | 0 y 1 |
| M02 Panel de pacientes | HU02, HU04, HU18 | Búsqueda de pacientes; en el Sprint 2 se agregaron los indicadores del día («Evaluaciones hoy», «Tiempo medio de respuesta»), sin las consultas de prueba | 1, ampliada en el 2 |
| M03 Registro del paciente | HU02, HU05 | Registro con el primer tamizaje; en el Sprint 2, «Guardar y evaluar» abre la consulta | 1, ampliada en el 2 |
| M04 Consulta clínica | HU03, HU06 | El profesional escribe su pregunta y ve el avance por etapas mientras se procesa | 2 |
| M05 Resultado de la consulta | HU07, HU08, HU09 | Recomendación con nivel de riesgo, evidencias citadas de las guías, verificación y aviso si el niño cambió de grupo de edad desde el tamizaje | 2 |
| M06 Datos faltantes | HU15 | Ventana que pide solo el dato que falta (la hemoglobina) y reanuda la consulta | 2 |
| M07 Evidencia insuficiente | HU16 | Resultado sin recomendación cuando las guías no bastan, con el detalle de la búsqueda | 2 |
| Registrar decisión clínica | Sin historia propia (RF8) | Ventana en dos pasos; la nota se guarda con los datos personales reemplazados por marcas | 2 (adelantada) |
| M08 Historial del paciente | HU04 | Evolución de la hemoglobina y tamizajes; en el Sprint 2 se agregaron las «Evaluaciones realizadas» | 1, ampliada en el 2 |
| M10 Gestión de usuarios | HU11 | Altas, cambios de rol, desactivación y restablecimiento de contraseña | 1 |
| M11 Base de conocimiento | HU12 | Lista de guías, carga de guías de nivel 2, avance de la indexación cada 3 s y detalle de cada guía | 2 |
| M14 Nuevo tamizaje | HU18 | Nuevo tamizaje de un paciente registrado; si se abrió desde la consulta, vuelve a ella | 1, ampliada en el 2 |
| M15 Tamizaje no vigente | HU15, HU18 | Ventana cuando el tamizaje pasó los 30 días: registrar uno nuevo o continuar con cautela | 2 |

### Lo que quedó para el Sprint 3

- **HU17 en M11:** retirar guías («Retirar» se ve deshabilitado, con la nota del Sprint 3) y cargar
  guías de nivel 1 desde la pantalla con revisión («Aprobar»).
  - Actualización del Sprint 3: el retiro (HU17) quedó resuelto en la parte F. La carga de nivel 1
    con revisión sigue pendiente.
- **M09** reporte exportable (y «Exportar reporte» en M05), **M12** parámetros clínicos y **M13**
  auditoría y trazabilidad: hoy muestran «En construcción».
  - Actualización del Sprint 3: M09 y HU10 quedaron resueltos en las partes C1 (API) y C2
    (pantalla), con «Exportar reporte» en M05 (P11). Queda la revisión clínica de las frases del
    reporte para el cuidador.
  - Actualización del Sprint 3: la API de M13 (HU13) quedó en la parte D1 (`docs/contrato_auditoria.md`,
    conexión de solo lectura `cdss_auditor`, migración 014) y la pantalla M13 en la parte D2: HU13
    resuelta.
- Las historias HU10, HU13 y HU14, y los pendientes de la sección 5 asignados al Sprint 3.
  - Actualización del Sprint 3: HU14 (M12) en curso. La parte E1a dejó la base (migración 015,
    rutas de lectura, huella de la configuración y modo de evaluación; `docs/contrato_parametros.md`)
    y la parte E1b, la edición por grupo (migración 016, control optimista, validaciones,
    confirmación escrita y confirmar contra la norma) y la parte E2, la pantalla M12. HU14 resuelta;
    quedan las verificaciones de abajo.
  - **Verificaciones pendientes antes del OE3** (ninguno de estos valores está confirmado contra su
    fuente; M12 muestra `verificado = false` en los tres primeros):
    - puntos de corte de Hb (NTS 213 y OMS 2024): la coordinadora CRED, con el asesor;
    - ajuste por altitud (mezcla OMS 2024 y la Tabla 1 de la RM 429): la coordinadora CRED, con el
      asesor;
    - vigencia del tamizaje (30 días): la coordinadora CRED;
    - altitudes de los distritos (INEI), fuera de M12: el equipo de tesis, por migración;
    - descriptores MeSH de los síntomas, fuera de M12: el equipo de tesis, por migración;
    - precios por millón de tokens del modelo (costo en M13): el equipo de tesis, por migración.
    - Desde la parte E1b, los tres primeros se confirman desde M12 con «Confirmar contra la norma»
      (un PUT con los mismos valores, `verificado` verdadero y la referencia), que deja su propia
      versión en el historial. También quedan por validar con el asesor los rangos de plausibilidad y
      los umbrales de advertencia de la edición (`backend/app/services/parametros_reglas.py`).

## 2. Cómo se verificó

| Verificación | Resultado al cierre (17/11/2026) |
| --- | --- |
| Pruebas automáticas del backend (`pytest -q`, base PostgreSQL real) | 736 pasan |
| Pruebas lentas (`pytest -m lenta`, PDF reales e índice) | 5 pasan; 57 se saltan fuera de la red de Docker (necesitan los modelos o los fragmentos indexados; ver `jobs/README.md`) |
| Pruebas del frontend (Vitest) | 251 pasan, en 10 archivos |
| Compilación del frontend (`npm run build`, con comprobación de tipos) | Sin errores |
| Integración continua (GitHub Actions) | Backend, servicio de modelos y frontend en cada push |

Además de las pruebas automáticas, cada parte con interfaz se revisó así:

- **Revisión manual con capturas:** cada pantalla se capturó en varios anchos y se revisó a ojo
  contra su mockup. Las diferencias que quedaron son intencionales y están en la tabla
  «Diferencias con los mockups» de `cambios_respecto_al_OE2.md`.
- **Accesibilidad:** revisión con axe-core (WCAG 2.0 y 2.1, niveles A y AA) con las ventanas
  abiertas y cerradas. Se corrigieron contrastes, listas mal formadas, tablas sin foco de
  teclado y botones sin nombre accesible (fila 84). Las etiquetas de estado tienen un contraste de
  4,5:1 o más, comprobado por las pruebas de estilos. Las áreas táctiles miden al menos 44 px en
  pantallas angostas. Al cierre, M11 no tiene infracciones a ningún ancho.
- **Desbordes:** auditoría automática en 10 anchos (320, 360, 390, 600, 768, 800, 1000, 1024,
  1280 y 1920 px) para que ninguna página se desplace en horizontal. Las tablas anchas se
  desplazan dentro de su contenedor. La prueba `estilos.test.ts` fija las reglas que lo evitan.
- **Pruebas de mutación:** en las rutas y la pantalla de M11 (partes F2b y F2c) y en los arreglos
  del cierre, se quitó cada comportamiento importante, de a uno, para comprobar que alguna prueba
  fallara. Por ejemplo, el sondeo con la pestaña oculta, el permiso de la ruta, la ubicación de
  cada error o el aspecto deshabilitado de «Retirar».
- **Datos sintéticos:** todas las corridas con el modelo de lenguaje real usaron los pacientes
  ficticios de `seed_demo` y las ejecutó el responsable.

**Robustez de las pruebas (cierre F2b):** dos pruebas fallaban solo en GitHub y se hicieron
deterministas.
- **Orden alfabético:** la base local (`postgres:16-alpine`) y la del CI (`postgres:16` de
  Debian) ordenan el texto de forma distinta. La lista de M11 ahora se ordena con una clave
  explícita en el servicio.
- **Carrera de tiempos:** una prueba del frontend dependía de qué respuesta llegaba primero.

En el cierre se revisó que ninguna otra prueba dependa del orden alfabético de la base ni de
tiempos de espera ajustados. Se encontró una más y se hizo determinista:
- **Prueba:** la de concurrencia del grafo (`test_una_consulta_sin_turno_emite_en_cola_y_cuenta_la_espera`).
- **Fragilidad:** suponía que la segunda consulta llegaba mientras la primera dormía 0,4 s.
- **Arreglo:** ahora la primera retiene el turno hasta que la otra está en cola.

Las demás esperas del frontend usan temporizadores falsos, y la del backend tiene un límite
holgado de 30 s.

**Un fallo intermitente del frontend:** una corrida de la suite tuvo 2 fallos.
- **Cuándo:** justo después de reiniciar el stack, con el servicio `modelos` calentando.
- **Reproducción:** no se repitió en más de 40 corridas, ni con la CPU cargada, ni en cuatro zonas
  horarias (incluidas UTC+14 y UTC-11, para descartar el cambio de fecha).
- **Medida preventiva:** `findBy` y `waitFor` esperan hasta 5 s en lugar de 1 s
  (`src/pruebas/configuracion.ts`). La duración de la suite no cambió.

## 3. Mediciones

Todas las cifras salen de `mediciones_sprint2.md` (MS) o de `jobs/README.md` (JR); cada fila indica
la sección. «Perfil normal» es el equipo de desarrollo; «B2ms» simula la máquina virtual de Azure
prevista, con 2 CPU.

### Latencia

| Medida | Perfil normal | B2ms | Fuente |
| --- | --- | --- | --- |
| Recuperación (8 candidatos de 256 tokens), p50 / p90 | 3,75 / 3,88 s | 5,03 / 5,48 s | MS, C2 «Latencia de la recuperación» |
| Consulta completa sin el modelo de lenguaje (cliente falso), p50 / p90 | 3,95 / 4,19 s | 5,63 / 6,28 s | MS, D1 |
| Primer evento en pantalla, p50 / p90 | 0,23 / 0,27 s | 0,35 / 0,48 s | MS, D1 y D2 |
| Consulta completa con el modelo real, verificadas, p50 / p90 | 11,79 / 12,54 s | 12,66 / 18,92 s | MS, D1 «Corrida con el modelo real» y D2 |
| Con reintento (búsqueda ampliada y dos llamadas), máximo | 17,54 s | 18,25 s | MS, D1 y D2 |
| Prompt compacto v1.2 (no adoptado), p90 total | 11,71 s | sin medir | MS, D2 «Prompt v1.2 frente a v1.1» |
| Costo por consulta con llamada al modelo | 0,024 USD | | MS, D1 |

En la consulta completa, la llamada al modelo (generar) es el 63 % del tiempo y la recuperación
el 33 % (MS, D1).

**RNF3 no se cumple en el flujo normal.** El OE2 pide un p90 menor a 10 s con la respuesta
completa. Las mediciones con el modelo real dan un p90 de 11,7 s (prompt v1.2) a 18,9 s (B2ms).
Con reintento sí se cumple el máximo de 25 s. La fila 61 de `cambios_respecto_al_OE2.md` propone
una redacción nueva para revisar con el asesor:
- primer indicio en menos de 1 s (hoy 0,27 s de p90);
- respuesta completa con un p90 de 15 s o menos.

### Calidad de la recuperación

Con las 35 consultas de desarrollo (ajuste y validación), el fragmento esperado queda entre los 5
primeros en el 86 % (30 de 35; intervalo de confianza del 95 %: 71 a 94 %), con la versión 5 y la
bonificación por edad de 0,7 (MS, C2 «Antes y después»). El conjunto de prueba final se mide una
sola vez en la evaluación del OE3.

Calendario de control de hemoglobina (parte G, pendiente P4): con un conjunto de aceptación nuevo
de 16 consultas (A), congelado antes del cambio, la Tabla N° 4 llega al modelo en 7 de 12 consultas
del calendario con la regla del puntero (antes 3 de 12) y en 10 de 12 con la regla y d1 (el
reranker lee el cuerpo de los fragmentos de la RM 429). En un segundo conjunto de 20 (B), con d1,
en 9 de 13 (antes 7). La Tabla N° 20 sigue en 2 de 4 de tratamiento de A y 1 de 7 de B con el
criterio estricto (3 de 4 y 6 de 7 con el aceptado). Las 20 de referencia siguen en 18 (MS,
parte G).

### Memoria

| Servicio | Uso medido | Límite | Fuente |
| --- | --- | --- | --- |
| `modelos` | pico de 1766 MiB en las mediciones de la recuperación; de 1955 a 2356 MiB mientras se indexa | 5632 MiB | MS, B «Memoria pico»; JR, medición |
| `backend` | 180 MiB después del calentamiento con LangGraph | 512 MiB | MS, D1 |
| `indexador` | 86 MiB en espera; pico de 311 MiB al indexar | 768 MiB | JR, medición |
| `chromadb`, `db`, `nginx` | 66, 33 y 6 MiB | 768, 768 y 64 MiB | MS, B «Memoria pico» |

En todos los casos el uso queda muy por debajo del límite.

### Interferencia de la indexación con las consultas (pendiente P14)

Medición del 16/11/2026 con el PDF completo de la RM 251 (38 páginas, 98 fragmentos), en el
equipo de desarrollo (JR, «Medición»):

- **Duración:** la indexación tardó 254,8 s.
- **Recuperación de una consulta:** pasó de 3,7 s (mediana antes) a 24,0 s durante la
  indexación, y volvió a 4,2 s después.
- **Llamada más lenta:** 30,2 s (reranker).

El servicio `modelos` atiende una petición a la vez. Hasta resolver P14, se indica cargar guías
fuera del horario de atención (aviso visible en M11).

## 4. Diferencias con el documento OE2

Están todas en [`cambios_respecto_al_OE2.md`](cambios_respecto_al_OE2.md), con su motivo. Las de
mayor peso para el documento son:
- el servicio interno de modelos locales (fila 1);
- el modelo `claude-sonnet-5-5` sin temperatura (filas 5 y 6);
- la RM 429 como documento propio (fila 10);
- las transcripciones de tablas críticas (fila 27);
- el grafo de LangGraph (fila 53);
- la propuesta de redacción del RNF3 (fila 61);
- el modo de prueba con el modelo falso (fila 65);
- la carga solo de nivel 2 desde M11 (filas 95 y 98).

## 5. Pendientes

**Dueños:**
- **Desarrollo:** el responsable del proyecto.
- **Asesor:** las decisiones de alcance o de redacción del documento.
- **Asesor y personal de salud:** las que afectan el trabajo clínico.

Las fechas son hitos del proyecto. El repositorio no fija fechas de calendario para el Sprint 3,
la evaluación del OE3 ni el despliegue.

### P1 a P14 (de `cambios_respecto_al_OE2.md`)

| N.° | Tema | Estado al cierre | Dueño | Fecha prevista |
| --- | --- | --- | --- | --- |
| P1 | Filtro de privacidad de la nota de la decisión | Resuelto en F1 (fila 86) | Desarrollo | Hecho |
| P2 | Consultas de prueba fuera de las métricas | Resuelto en F1 (fila 87); las métricas del OE3 deben usar la misma regla | Desarrollo | Hecho; regla a aplicar en el OE3 |
| P3 | Filtro de dominio frente a preguntas genéricas («¿Cómo lo manejo?») | Abierto: idea a medir con un conjunto de validación nuevo | Desarrollo | Evaluación del OE3 |
| P4 | Recuperación de la Tabla N° 4 de la RM 429 (calendario de control de Hb) | En parte resuelto (parte G, 17/11/2026). La medición corrigió el diagnóstico: en las consultas de diagnóstico la tabla llegaba en 5 de 7, y el fallo real era el puntero «según Tabla N° 4» sin la tabla. Con la regla del puntero (fila 101), en el conjunto de aceptación del calendario la tabla llega en 7 de 12 (antes 3) y no queda ningún puntero sin tabla (antes 4). Con d1 (fila 103, 18/11/2026), 10 de 12 en A y 9 de 13 en un segundo conjunto (B, antes 7), sin perder aciertos ni cambiar ningún estado antes del modelo. El paso c1 (preguntas nuevas de `construir_consulta`) se midió y se revirtió porque perdía B11 (`mediciones_sprint2.md`, parte G, fase 8). Queda abierto: en el calendario, A01, A12, B01, B04, B06 y B08 sin la tabla; en el tratamiento, B15 (pregunta libre) sin la Tabla N° 20 ni el fragmento que la cita, y la métrica estricta de la Tabla N° 20 (2 de 4 en A, 1 de 7 en B: en la mayoría llega el fragmento de seguimiento que la cita, no la tabla). Como c1 no se integró, `construir_consulta` no cambia y las mediciones anteriores con consultas estructuradas no pierden comparabilidad por eso; d1 sí cambia el puntaje de 12 fragmentos de la RM 429, y el 86 % de las 35 consultas de desarrollo se midió antes de d1. El puntaje del reranker depende de la composición del lote (fila de limitaciones) | Desarrollo | Antes de la evaluación del OE3 |
| P5 | Reanudar con la pregunta guardada | Resuelto en F1 (fila 88) | Desarrollo | Hecho |
| P6 | Aviso de cambio de grupo de edad | Resuelto en F1 (fila 89) | Desarrollo | Hecho |
| P7 | Códigos internos (SIN_ANEMIA) en el texto del modelo | Abierto | Desarrollo | Evaluación del OE3 (versión del prompt) |
| P8 | Preguntas de dos partes con una parte sin evidencia | Abierto | Desarrollo | Evaluación del OE3 |
| P9 | Consultas de seguimiento encadenadas | Abierto | Desarrollo | Sprint 3 |
| P10 | Lista de todas las consultas del usuario | Abierto al cierre. Resuelto en la parte B del Sprint 3: `GET /api/consultas` y «Historial de consultas» en `/consultas` (filas 109 y 110 de `cambios_respecto_al_OE2.md`) | Desarrollo | Sprint 3, parte B |
| P11 | «Exportar reporte» (M09) | Abierto al cierre. Resuelto en el Sprint 3: API en la parte C1 (vista previa, PDF con número y hash, lista; `docs/contrato_reportes.md`, filas 112 y 113) y pantalla M09 en la parte C2, con «Exportar reporte» en M05 y M07, «Reporte» en M08 y «Exportar» en «Reportes» (filas 114 a 117). Queda la revisión clínica de las frases del cuidador: mientras `revisado` sea false, el reporte lleva «Texto en revisión clínica: no entregar a pacientes» | Desarrollo (revisión de frases: asesor y personal de salud) | Sprint 3, parte C2 |
| P12 | Nombre de quien registró la decisión | Abierto al cierre. Resuelto en la parte B del Sprint 3: `registrada_por` en la decisión y «Registrada por» en M05 (fila 111) | Desarrollo | Sprint 3, parte B |
| P13 | La auditoría de desbordes no mide los elementos absolutos que escapan de su contenedor | Abierto al cierre. Resuelto en la parte A del Sprint 3: la auditoría pasa a `frontend/auditoria/` y mide esos elementos | Desarrollo | Sprint 3, parte A |
| P14 | Indexación y consultas a la vez (la recuperación pasa de unos 4 s a unos 24 s) | Abierto al cierre, con aviso en M11 y como máximo 2 trabajos activos. Resuelto en la parte J del Sprint 3: el indexador envía 1 texto por petición de embeddings (`INDEXADOR_LOTE_EMBEDDINGS`) y, con una indexación en curso, la recuperación queda en unos 4,7 s de mediana en el perfil normal y 8,4 s en B2ms (filas 150 y 151 de `cambios_respecto_al_OE2.md`, `mediciones_sprint2.md`) | Desarrollo | Sprint 3, parte J |

### Nuevos al cierre del Sprint 2

| Tema | Detalle | Dueño | Fecha prevista |
| --- | --- | --- | --- |
| Carga de guías de nivel 1 desde M11, con revisión | Hoy las de nivel 1 se cargan por línea de comandos con transcripciones verificadas. Falta un flujo de revisión en pantalla («Aprobar») antes de que una guía se pueda citar | Desarrollo | Sprint 3 |
| Retiro de guías (HU17) | Resuelto en el Sprint 3, parte F: «Retirar» en M11 con las guardas del nivel 1 y el trabajo RETIRO del indexador | Desarrollo | Hecho (Sprint 3) |
| Recorte de márgenes por documento | Las guías del manifiesto tienen su recorte de la zona del cuerpo (`fuentes_iniciales.yaml`); las cargadas desde M11 se extraen a página completa | Desarrollo | Sprint 3, junto con la carga de nivel 1 |
| Recuperación de la Tabla N° 4 de la RM 429 | Es el resto del pendiente P4. Con la regla del puntero y d1 (el reranker puntúa el cuerpo sin el preámbulo de la RM 429, fila 103 de `cambios_respecto_al_OE2.md`) siguen sin la tabla A01 y A12 (conjunto A) y B01, B04, B06 y B08 (conjunto B). Las preguntas nuevas de `construir_consulta` (c1) resolvían A12, B06 y B08 pero perdían B11 y se revirtieron (`mediciones_sprint2.md`, parte G, fase 8). Opción medida en memoria y no aplicada: partir la tabla en dos bloques por edad, reindexando solo la RM 429 | Desarrollo | Antes de la evaluación del OE3 |
| Tabla N° 20 en las consultas de tratamiento | Hallazgo de la parte G: en las consultas estructuradas de tratamiento, y en algunas libres y combinadas, no llega la Tabla N° 20 (control de hemoglobina en el tratamiento), sino el fragmento «Seguimiento de casos de anemia» que la cita. Con d1, criterio estricto: 2 de 4 en A (fallan A15 y A16) y 1 de 7 en B (fallan B14 a B18 y B20); criterio aceptado: 3 de 4 y 6 de 7 (fallan A15 y B15). c1 llevaba el estricto a 3 de 4 y 3 de 7, pero se revirtió (`mediciones_sprint2.md`, parte G, fase 8). B15, una pregunta libre, no recibe ni la tabla ni el fragmento que la cita | Desarrollo | Antes de la evaluación del OE3 |
| El puntaje del reranker depende de la composición del lote | Hallazgo de la parte G (18/11/2026). El reranker int8 puntúa los 8 candidatos en un solo lote, y el puntaje del mismo par consulta y fragmento cambia según los otros 7 textos del lote: en un experimento con 3 fragmentos fijos y 2 consultas, hasta 0,119 (0,363 a 0,481), y un fragmento pasó de 0,140 a 0,187 cruzando el umbral. Solo y repetido da siempre el mismo valor, y con el mismo contenido en otro orden tampoco cambia. Es compatible con la cuantización dinámica de las activaciones, cuya escala se calcula sobre todo el lote (no se comparó con fp32). El umbral de 0,15 y la parte de 6.3 anterior al modelo heredan esta dependencia: un cambio en otro candidato puede mover la relevancia de un fragmento que no cambió. Detalle en `mediciones_sprint2.md` (parte G) | Desarrollo | Evaluación del OE3 (no se cambia el código por esto) |
| Prioridad de las consultas frente a la indexación | Es el pendiente P14: resuelto en la parte J del Sprint 3 con lotes de embeddings de 1 texto, sin cambiar `modelos` ni el horario del trabajador | Desarrollo | Hecho (Sprint 3) |
| Fechas completas en la nota de la decisión | El filtro de privacidad reemplaza también las fechas completas de la nota por [FECHA] (por ejemplo «control el 20/12/2026»), igual que en la consulta (fila 86). Puede quitarle información útil a la nota | Asesor y personal de salud | A conversar antes de la validación con usuarios |
| RNF3 no cumplido | p90 de 11,7 a 18,9 s frente al objetivo de menos de 10 s (sección 3). La redacción propuesta está en la fila 61 | Asesor | Revisión del documento OE2 |
| Despliegue en Azure | Máquina B2ms, Azure Database for PostgreSQL y secretos en Key Vault, con las mejoras de `mejoras_despliegue.md` | Desarrollo | Sprint 3 |

## Anexo A. Retiro de la «Guía de prueba N2» (17/11/2026)

**Motivo:** la «Guía de prueba N2» era un documento de prueba subido desde M11 para verificar la
carga. Era de nivel 2, con 2 fragmentos, y la cargó `admin.cdss` el 17/11/2026. No debía quedar en
la base de conocimiento para la evaluación del OE3.

Como M11 todavía no puede retirar guías (HU17, Sprint 3), se retiró con una limpieza puntual. No
se creó ninguna ruta ni script permanente de borrado.

### Procedimiento

Se ejecutó desde la raíz del repositorio en Git Bash, con el stack levantado.

1. **Respaldo** en `data/respaldos/` (ignorada por git: `data/*` en `.gitignore`):
   ```bash
   mkdir -p data/respaldos
   docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc -n conocimiento -n auditoria' \
     > data/respaldos/f3_20261117_conocimiento_auditoria.dump
   ```
   Además, en la misma carpeta:
   - el PDF (`f3_guia_de_prueba_n2.pdf`, con el mismo SHA-256 que la base);
   - sus 2 vectores de ChromaDB, con embeddings y metadatos (`f3_vectores_guia_de_prueba_n2.json`).

   Para restaurar el respaldo: `pg_restore` del archivo `.dump`. Desde la parte K del Sprint 3, la
   colección de ChromaDB y las guías cargadas se respaldan con `python -m app.respaldo` y el
   `pg_dump` completo de desarrollo está en `docs/respaldo.md`.
2. **Identificación sin ambigüedad:** una sola fila de `conocimiento.documento_fuente` con:
   - título exacto «Guía de prueba N2»;
   - nivel 2;
   - SHA-256 `1e5617f5ac1a55e00869084b9c50531d2a6ede2c914d9bfb1cf2fe3cdec7e72b`;
   - id `c5860d2d-396e-4b8d-99e6-72aea15ca400`.

   Antes de borrar se comprobó que ninguna consulta la había recuperado (`asistencia.fragmento_recuperado`). Tampoco la referenciaban otros documentos, fragmentos modificatorios, puntos de corte ni ajustes por altitud.
3. **Transacción única con el superusuario** (`psql` dentro del contenedor `db`, con el SQL en un archivo pasado por la entrada estándar):
   - **Comprobaciones:** se repiten las del paso 2, y la transacción aborta si no hay exactamente una coincidencia.
   - **Borrado:** `DELETE` de sus fragmentos (2), de sus trabajos de indexación (1) y del documento (1).
   - **Auditoría:** se agrega el evento `GUIA_ELIMINADA` (sin usuario, porque fue una limpieza manual). Su detalle lleva el motivo, el SHA-256, el nivel, los conteos y la referencia a este anexo, sin el título ni el contenido del documento.
   - **Comprobación final:** la transacción aborta si no quedan 4 documentos y 183 fragmentos vigentes.

   Los eventos GUIA_CARGADA (1801) y GUIA_INDEXADA (1802) se conservan: la bitácora no admite
   eliminaciones, y la trazabilidad de la carga y del retiro queda completa.
4. **ChromaDB:** desde el contenedor `backend`, se borraron de la colección `guias_clinicas` los
   2 vectores con `id_documento` igual al del documento, después de comprobar que fueran
   exactamente esos 2 ids.
5. **PDF:** se borró `/datos/guias_cargadas/c5860d2d-396e-4b8d-99e6-72aea15ca400.pdf` del volumen
   `datos_guias_cargadas`, que quedó vacío.

### Resultados

| Medida | Antes | Después |
| --- | --- | --- |
| Documentos | 5 | 4 |
| Fragmentos (todas las versiones) | 1125 | 1123 |
| Fragmentos vigentes | 185 | 183 |
| Trabajos de indexación | 28 | 27 |
| Eventos de auditoría | 1815 | 1816 (el de la limpieza) |
| Vectores en ChromaDB | 204 | 202 |
| PDF en `datos_guias_cargadas` | 1 | 0 |

Comprobaciones posteriores:

- **M11** (`GET /api/conocimiento/documentos` a través de Nginx, con `admin.cdss`): muestra solo
  las 4 guías, con 183 fragmentos vigentes y sin trabajos activos.
- **ChromaDB frente a PostgreSQL:** 0 vectores sin fragmento y 0 fragmentos vigentes sin vector;
  la vigencia coincide en los 202.
  - **Por qué 202 vectores y no 183:** ChromaDB guarda todos los fragmentos de la última versión
    de cada documento. Son 202; 19 de ellos son fragmentos de la NTS 213 reemplazados por la RM
    429, con `vigente = falso` en sus metadatos.
  - Esto coincide con la versión 5 («202 (183)» en `mediciones_sprint2.md`, parte C2). La
    recuperación solo usa los vigentes.
- **Recuperación sin el modelo de lenguaje:** las 20 consultas de referencia (BM25, ChromaDB,
  reranker y búsqueda ampliada, con `cdss_generacion`) dan resultados idénticos antes y después.
  Coinciden el orden, los puntajes del reranker, los fragmentos seleccionados y las pasadas. Los
  fragmentos de la guía de prueba no aparecían en ningún ranking, porque las guías de nivel 2 no
  se recuperan.
