# Cambios respecto al documento del OE2

Registro de las desviaciones de la implementación respecto al Documento del Objetivo
Específico 2 (diseño), con su motivo. Sirve para actualizar el documento y revisarlo con
el asesor. La columna "Estado" indica si el cambio ya está en el código o en qué parte
del Sprint 2 se aplicará.

Fecha de la última revisión: 04/11/2026.

## Arquitectura y despliegue

| N.° | Sección del OE2 | Cambio | Motivo | Estado |
| --- | --- | --- | --- | --- |
| 1 | 3.2 Arquitectura física; 3.4 Diagrama de componentes | Nuevo contenedor interno `modelos` (sin puerto publicado) que carga bge-m3 y bge-reranker-v2-m3 una sola vez y los expone por HTTP (`/embeddings`, `/reranquear`, `/tokens`, `/salud`) al backend y al indexador | Una sola copia de los modelos en memoria (unos 5 GB) compartida por el backend y el indexador; el backend no necesita PyTorch y las pruebas automáticas no descargan modelos | Aplicado (Sprint 2, A1) |
| 2 | 3.2 Arquitectura física (contenedor Jobs) | El contenedor `jobs` usa la misma imagen del backend (destino `jobs` del Dockerfile) y arranca solo bajo demanda (`docker compose run --rm jobs`) | Reutiliza la configuración, las conexiones y la normalización de texto del backend; no consume memoria cuando no se indexa | Aplicado (A1); el indexador se agrega en A2 |
| 3 | 3.2 Arquitectura física | Los pesos de los modelos se guardan en una carpeta del equipo (`./data/modelos`) fijados a una revisión exacta de Hugging Face, y los contenedores trabajan sin conexión (`HF_HUB_OFFLINE=1`) | Reproducibilidad; `docker compose down -v` no los borra; los modelos no se descargan en cada despliegue | Aplicado (A1) |
| 4 | 3.2 Arquitectura física | Límites de memoria por contenedor (`mem_limit`): modelos 5,5 GB, base de datos 0,75 GB, ChromaDB 0,75 GB, backend 0,5 GB, Nginx 64 MB, jobs 0,75 GB | Caber en 8,5 GB (Docker local con 8,7 GB y VM B2ms de Azure con 8 GB) | Aplicado (A1); valores a ajustar con mediciones |

## Modelo de lenguaje (4.5, Tabla 8)

| N.° | Elemento | Cambio | Motivo | Estado |
| --- | --- | --- | --- | --- |
| 5 | Modelo | Claude Sonnet 4.5 se reemplaza por su sucesor, `claude-sonnet-5-5` (parámetro `MODELO_LLM`, versionado) | Sonnet 4.5 se retira el 30/11/2026. **Pendiente de confirmar en la página oficial de modelos y retiros de Anthropic** | Aplicado en parámetros (A1) |
| 6 | Temperatura | Se elimina la temperatura 0: el parámetro `TEMPERATURA_LLM` se cierra con vigencia (queda en el historial) | Según la referencia de la API consultada, Claude Sonnet 5.5 rechaza valores de temperatura distintos del predeterminado, y desde la versión de API 2026-10-21 ningún modelo acepta el parámetro. La consistencia se buscará con salida estructurada (esquema JSON). **En la parte C se citará la documentación oficial y se confirmará con una llamada real mínima; si el parámetro se acepta, se reabre la decisión** | Aplicado en parámetros (A1); confirmación en C |
| 7 | Modelo de respaldo | Desactivado: `MODELO_RESPALDO` queda vacío | Decisión del Sprint 2; evita enviar la solicitud a un segundo modelo sin evaluarlo | Aplicado (A1) |
| 8 | Costo | Precios en parámetros: `PRECIO_ENTRADA_USD_MTOK` = 2,00 y `PRECIO_SALIDA_USD_MTOK` = 10,00 (dólares por millón de tokens) | El costo por llamada (`costo_usd`) se calcula sin valores fijos en el código. **Verificar en la página oficial de precios de Anthropic** | Aplicado (A1) |
| 9 | Idioma de la respuesta | La recomendación se genera en español aunque la guía esté en inglés, salvo que la consulta esté en inglés o se pida otro idioma (`IDIOMA_RESPUESTA_DEFECTO`, `consulta.idioma_respuesta`). Las citas de la OMS muestran el texto original con la etiqueta "texto original en inglés" y debajo una traducción de apoyo marcada como no oficial (`cita_evidencia.extracto_traducido`); un control verifica que cifras y unidades coincidan con el original | Las guías OMS están en inglés y el personal del servicio CRED trabaja en español; la traducción no reemplaza la evidencia original | Columnas y parámetro en A1; lógica en C y pantallas en E |

## Base de conocimiento (4.1, Tabla 2)

| N.° | Elemento | Cambio | Motivo | Estado |
| --- | --- | --- | --- | --- |
| 10 | Fuentes de nivel 1 (Tabla 2) | Se agrega la RM 429-2024/MINSA como documento propio (tipo RESOLUCION, nivel 1). Cita: "NTS 213-MINSA/DGIESP-2024, aprobada por RM 251-2024/MINSA (08/04/2024) y modificada por RM 429-2024/MINSA (18/06/2024)". Fecha de consulta: 04/11/2026; las fechas se verificaron en la primera página de cada resolución | La RM 429 modifica 12 puntos de la norma (Anexo), entre ellos la tabla de ajuste por altitud, las tablas de suplementación y la de valores de hemoglobina | Aplicado (A1) |
| 11 | Páginas indexadas | Solo se indexa el cuerpo de la norma (RM 251, págs. 4 a 36) y el Anexo de la modificatoria (RM 429, págs. 4 a 11), no las páginas de la resolución | El texto de la resolución no contiene evidencia clínica | Páginas registradas en A1; indexación en A2 |
| 12 | Vigencia de fragmentos | Los fragmentos de la RM 251 sustituidos por la RM 429 se conservan con `vigente = falso` y no se recuperan. Además se excluye la oración del literal B.1 "termina a los 5 meses 29 días", que contradice la Tabla 5 modificada | El OE2 solo prevé la obsolescencia de documentos completos; la RM 429 sustituye partes de un documento que sigue vigente | Columnas en A1; regla en A2 |
| 13 | Extracción de texto | pdfplumber en lugar de PyMuPDF, con comparación contra OCR en español y transcripción manual verificada de las tablas críticas | Licencia AGPL de PyMuPDF; los PDF de la NTS son escaneos con lectura óptica defectuosa | Previsto en A2 |
| 14 | Normalización (4.1 y 4.2) | Sin UMLS: diccionario MeSH/DeCS curado y marcado `[VERIFICAR]`; `fragmento.conceptos_umls` queda vacío | El acceso a UMLS requiere licencia UTS | Previsto en A2 y B |

## Base de datos (5.1)

| N.° | Elemento | Cambio | Motivo | Estado |
| --- | --- | --- | --- | --- |
| 15 | Organización en esquemas (Tabla 2) | 27 tablas en lugar de 26: nueva `conocimiento.trabajo_indexacion` (documento, tipo, estado, etapa, procesados, total, error, usuario y fechas) | Cola de trabajos del indexador y avance que muestra la pantalla M11 | Aplicado (A1) |
| 16 | `conocimiento.documento_fuente` (Tabla 22) | Nuevas columnas `fecha_publicacion`, `idioma`, `pagina_inicio_cuerpo` y `pagina_fin_cuerpo`. `ruta_blob` y `hash_archivo` pasan a admitir nulos hasta que se carga el PDF (con una restricción que los exige cuando la indexación está COMPLETADA) | Registrar la fecha exacta de la norma, el idioma para la búsqueda léxica y las páginas indexables; evitar hashes inventados para documentos aún no cargados | Aplicado (A1) |
| 17 | `conocimiento.fragmento` (Tabla 23) | Nuevas columnas `vigente`, `id_documento_modificatorio`, `motivo_exclusion`, `tipo_contenido` (TEXTO o TABLA), `fuente_texto` (CAPA_TEXTO, OCR o TRANSCRIPCION), `verificado` y `fecha_verificacion` | Vigencia por fragmento (fila 12) y trazabilidad del origen y la verificación del texto | Aplicado (A1) |
| 18 | `asistencia.consulta` (Tabla 14) | Nuevas columnas `texto_filtrado` (consulta tras el filtro de texto libre) e `idioma_respuesta` | El componente de generación solo lee el texto filtrado, nunca el original | Aplicado (A1) |
| 19 | `asistencia.cita_evidencia` (Tabla 19) | Nueva columna `extracto_traducido` | Traducción de apoyo de las citas en inglés (fila 9) | Aplicado (A1) |
| 20 | `configuracion.parametro_sistema` (Tabla 27) | Nuevos parámetros `UMBRAL_DOMINIO` (provisional, 0,50, se calibra en B), `PRECIO_ENTRADA_USD_MTOK`, `PRECIO_SALIDA_USD_MTOK`, `MODELO_RESPALDO` e `IDIOMA_RESPUESTA_DEFECTO` | Filas 6 a 9 y filtro de dominio (4.2) | Aplicado (A1) |
| 21 | `configuracion.ajuste_altitud` (Tabla 26) | El rango 4500 a 5500 m (3,3) se divide en 4500 a 4999 m (3,3) y 5000 a 5500 m (4,0), atribuidos a la RM 429-2024/MINSA. La fila anterior se cierra con vigencia | Tabla 1 del Anexo de la RM 429-2024/MINSA (modificación 2) | Aplicado (A1) |
| 22 | Roles de base de datos (Tabla 31) | Nuevo rol `rol_app_indexador` con el usuario `cdss_indexador`: lee la base de conocimiento y los parámetros del sistema, escribe fragmentos y trabajos, solo actualiza ruta, hash, estado de indexación y total de fragmentos de los documentos, inserta en la auditoría; sin acceso a datos clínicos ni a cuentas y sin permiso de eliminación | Mínimo privilegio para el contenedor Jobs | Aplicado (A1) |
| 23 | Roles de base de datos (Tabla 31) | `rol_app_generacion` pasa a permisos por columna: no lee `consulta.texto_consulta` ni `tamizaje.observaciones`, y en la consulta solo actualiza estado, número de intentos, fecha de fin y latencia | El texto libre sin filtrar puede contener identificadores (4.4) | Aplicado (A1) |

## Protección de datos (4.4, Tabla 7)

| N.° | Elemento | Cambio | Motivo | Estado |
| --- | --- | --- | --- | --- |
| 24 | Datos enviados | Se envía `peso_kg`; no se envían la talla ni las observaciones del tamizaje | El peso es necesario para las dosis en mg/kg; la talla no se usa en la recomendación y las observaciones son texto libre | Permisos en A1; solicitud en C |

## Alcance por Sprint y pantallas

| N.° | Elemento | Cambio | Motivo | Estado |
| --- | --- | --- | --- | --- |
| 25 | HU17 (retirar guía, M11) | Pasa al Sprint 3; en M11 el botón "Retirar" se muestra deshabilitado | Priorizar el flujo de consulta del Sprint 2 | Previsto en F |
| 26 | M07 (evidencia insuficiente) | Se implementa en el Sprint 2 con un "Registrar decisión clínica" mínimo | Cerrar el flujo de la consulta cuando no hay evidencia | Previsto en D y E |
