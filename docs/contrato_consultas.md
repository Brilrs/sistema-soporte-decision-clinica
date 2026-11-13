# Contrato de la API de consultas (partes D2 y E0)

Formato de las rutas de consultas clínicas, para la interfaz (parte E). OpenAPI lo refleja en
`/docs` y `/openapi.json`. El NDJSON aparece como `EventoConsulta`, con discriminador `tipo`.
Código: `backend/app/api/routes/consultas.py`. Ejemplos reales de cada estado, generados por las
pruebas con el cliente falso, en `frontend/src/__fixtures__` (`consulta_<estado>.ndjson` y
`resultado_<estado>.json`).

## Reglas comunes

- **Autenticación:** `Authorization: Bearer <token>` (login de Sprint 1). Sin sesión válida: 401.
- **Permiso:** REALIZAR_CONSULTA (Enfermera CRED, Médico, Nutricionista y Coordinador CRED). El
  Administrador no lo tiene: 403 en todas las rutas.
- **Propiedad:** cada profesional ve, completa y decide solo sus consultas. La de otro responde
  404 (la misma respuesta que una consulta inexistente) y queda el evento
  ACCESO_DENEGADO_CONSULTA en la auditoría.
- **Sin identidad:** ninguna respuesta ni evento lleva nombre, DNI, historia clínica, huellas ni
  el texto original de la consulta. `texto_filtrado` es la pregunta con los identificadores ya
  reemplazados por marcas (`[PACIENTE]`, `[DNI]`, `[HC]`, `[TELEFONO]`, `[FECHA]`, `[NOMBRE]`).
- **Errores antes del stream:** `{"detail": "<mensaje en español>"}` con 404, 409 o 422. Los
  errores de validación del cuerpo siguen el formato de Sprint 1 (422).
- **Auditoría** (sin texto clínico; solo ids, estados y tipos): CONSULTA_INICIADA,
  CONSULTA_PROCESADA (al cerrar, desde el grafo), CONSULTA_VISTA, TAMIZAJE_COMPLETADO,
  DECISION_REGISTRADA, CONSULTAS_LISTADAS, ACCESO_DENEGADO_CONSULTA y SOLICITUD_BLOQUEADA.
- **Modo de prueba:** con `CDSS_LLM=falso` (solo se acepta con `CDSS_ENTORNO=desarrollo`; en otro
  entorno el backend no arranca) las consultas usan el cliente falso del modelo de lenguaje, sin
  costo. Toda consulta cuya respuesta generó el cliente falso trae `modo_prueba: true` en el evento
  `fin`, en el resultado guardado y en la lista; la interfaz debe mostrarlo. Una consulta que no
  llegó a generar (por ejemplo DATOS_FALTANTES) trae `false`.

## Estados finales de una consulta

| Estado | Pantalla | Significado | Admite decisión |
| --- | --- | --- | --- |
| VERIFICADA | M05 | Recomendación aprobada por los controles 6.1 a 6.3 | ACEPTA_RECOMENDACION, MODIFICA_RECOMENDACION (nota obligatoria), CRITERIO_CLINICO_PROPIO |
| EVIDENCIA_INSUFICIENTE | M07 | Sin evidencia suficiente tras el reintento | CRITERIO_CLINICO_PROPIO |
| ERROR | M07 | No se pudo evaluar (API, tiempo agotado, respuesta inválida dos veces o falla interna) | CRITERIO_CLINICO_PROPIO |
| DATOS_FALTANTES | M06 | Falta un dato mínimo del tamizaje; se completa con `POST /api/consultas/{id}/datos-faltantes` | No |
| TAMIZAJE_NO_VIGENTE | M15 | El tamizaje superó `DIAS_VIGENCIA_TAMIZAJE`; se reanuda con una consulta nueva con `confirma_tamizaje_no_vigente: true` e `id_consulta_previa` | No |
| FUERA_DE_DOMINIO | Aviso | La consulta no trata de anemia en niños de 0 a 59 meses | No |
| SOLICITUD_BLOQUEADA | Aviso | El control previo encontró datos del paciente en la solicitud; no se envió nada | No |

La interfaz no repite estas reglas: cada respuesta trae `opciones_decision`, la lista de tipos
admitidos con `nota_obligatoria` para cada uno. La lista viene vacía si el estado no admite
decisión o si la consulta ya tiene una.

## POST /api/pacientes/{id_paciente}/consultas

Cuerpo (JSON):

| Campo | Tipo | Obligatorio | Descripción |
| --- | --- | --- | --- |
| `texto_consulta` | texto, de 1 a 2000 caracteres | Sí | Pregunta del profesional |
| `id_tamizaje` | UUID | No | Por defecto, el tamizaje más reciente del paciente |
| `confirma_tamizaje_no_vigente` | booleano | No (false) | Continuar con un tamizaje vencido |
| `id_consulta_previa` | UUID | No | Consulta TAMIZAJE_NO_VIGENTE que esta reanuda |

Respuestas antes del stream:

| Código | Caso |
| --- | --- |
| 404 | El paciente no existe |
| 422 | El tamizaje no es del paciente, el paciente no tiene tamizajes, la consulta previa no corresponde o el cuerpo no es válido |
| 409 | La consulta previa ya se reanudó |

Con 200, la respuesta es `Content-Type: application/x-ndjson`, con las cabeceras
`Cache-Control: no-store` y `X-Accel-Buffering: no`. Cada línea es un objeto JSON terminado en
`\n`, en UTF-8 sin escapes. El orden es el de ejecución del grafo:

```
validar → (salida) | clasificar → normalizar → recuperar → [proteger → generar] → verificar
       → (recuperar o proteger, una sola vez) → salida
```

Puede aparecer un evento `en_cola` antes de la etapa que espera turno. La última línea es
siempre un evento `fin` o `error`.

### Evento `etapa`

Se emite cuando un nodo termina.

| Campo | Tipo | Descripción |
| --- | --- | --- |
| `tipo` | `"etapa"` | |
| `etapa` | validar, clasificar, normalizar, recuperar, proteger, generar, verificar o salida | Nodo que terminó |
| `intento` | entero o null | 1 o 2 desde normalizar |
| `ms` | entero | Duración del nodo |
| `transcurrido_ms` | entero | Desde que el servidor recibió la consulta |
| `id_consulta` | UUID | Presente desde validar, que registra la consulta |
| `resultado` | texto | validar: VALIDA o el estado final; clasificar: la categoría; verificar: APROBADO, REINTENTO, EVIDENCIA_INSUFICIENTE o ERROR |
| `motivo` | texto o null | Solo clasificar: por qué no se pudo clasificar |
| `terminos`, `edad_meses` | | Solo normalizar |
| `tipo_busqueda`, `relevancia_maxima`, `suficiente`, `seleccionados` | | Solo recuperar |
| `control_identificadores`, `fragmentos` | | Solo proteger |
| `generacion`, `stop_reason` | | Solo generar |
| `siguiente`, `estado_final` | | verificar (REGENERAR o AMPLIADA) y salida |

Los campos que no corresponden al nodo no vienen.

### Evento `en_cola`

| Campo | Tipo | Descripción |
| --- | --- | --- |
| `tipo` | `"en_cola"` | |
| `etapa` | nodo | Etapa que espera turno |
| `recurso` | `"modelos"` o `"llm"` | Servicio de modelos (`MAX_CONCURRENCIA_RERANKER`) o API (`MAX_CONCURRENCIA_LLM`) |
| `transcurrido_ms` | entero | |

### Evento `fin`

| Campo | Tipo | Descripción |
| --- | --- | --- |
| `tipo` | `"fin"` | |
| `id_consulta`, `id_paciente` | UUID | |
| `id_consulta_previa` | UUID o null | Consulta que esta reanuda |
| `estado` | estado final | Ver la tabla de estados |
| `mensaje` | texto o null | Mensaje para el profesional (null en VERIFICADA) |
| `idioma` | `"es"` o `"en"` | Idioma de la recomendación |
| `datos_faltantes` | lista de textos | Etiquetas (por ejemplo `"hemoglobina"`), solo en DATOS_FALTANTES |
| `vigencia` | objeto | `dias_transcurridos`, `dias_vigencia`, `continua_con_tamizaje_no_vigente` |
| `clasificacion` | objeto o null | `categoria`, `nivel_riesgo`, `hb_ajustada_g_dl`, `ajuste_hb_g_dl`, `altitud_msnm`, `requiere_derivacion` |
| `recomendacion` | objeto o null | Solo VERIFICADA: `resumen`, `recomendacion` (pasos con `tipo`, `texto` y `citas`, una lista de etiquetas F-xx), `advertencias`, `factores_identificados` |
| `citas` | lista | Ver «Cita» |
| `numero_intentos` | entero | Intentos registrados (0 a 2) |
| `intentos` | lista | Ver «Intento»; vacía si no hubo búsqueda (DATOS_FALTANTES, TAMIZAJE_NO_VIGENTE, FUERA_DE_DOMINIO) |
| `verificacion` | objeto o null | Ver «Verificación»; null si no hubo intentos |
| `modo_prueba` | booleano | Respuesta generada por el cliente falso (ver «Reglas comunes») |
| `opciones_decision` | lista | `{tipo, nota_obligatoria}` |
| `tiempos_ms` | objeto | `total_ms`, `primer_evento_ms`, `por_nodo`, `etapas`, `espera_ms` |
| `transcurrido_ms` | entero | |

### Evento `error`

Se emite ante una falla inesperada. La consulta queda en ERROR.

| Campo | Tipo |
| --- | --- |
| `tipo` | `"error"` |
| `id_consulta` | UUID o null (null si falló antes de registrarse) |
| `id_paciente` | UUID |
| `estado` | `"ERROR"` |
| `mensaje` | «No se pudo evaluar la consulta. Aplique su criterio clínico.» |
| `opciones_decision` | lista |
| `transcurrido_ms` | entero |

### Cita

| Campo | Tipo | Descripción |
| --- | --- | --- |
| `etiqueta` | texto | F-01 a F-05 |
| `extracto` | texto | Literal, en el idioma original del fragmento |
| `extracto_traducido` | texto o null | Traducción de apoyo si el fragmento está en otro idioma |
| `etiqueta_traduccion` | texto o null | «Traducción de apoyo, no oficial» cuando hay traducción |
| `fuente` | texto | Código del documento (por ejemplo, NTS 213-MINSA/DGIESP-2024) |
| `documento` | texto | Título |
| `seccion` | texto o null | Ruta de secciones |
| `pagina_inicio`, `pagina_fin` | entero o null | Páginas del PDF |
| `idioma` | `"es"` o `"en"` | Idioma del fragmento |
| `puntaje_reranker` | decimal o null | Relevancia del fragmento según el reranker, de 0 a 1, con 3 decimales (columna «Relevancia» de M05) |

### Intento

Detalle de la búsqueda de cada intento (M07), en orden.

| Campo | Tipo | Descripción |
| --- | --- | --- |
| `numero` | 1 o 2 | |
| `tipo_busqueda` | `"INICIAL"` o `"AMPLIADA"` | La ampliada usa sinónimos y equivalentes en inglés |
| `candidatos_evaluados` | entero | Fragmentos que evaluó el reranker (`CANDIDATOS_RERANKER`, hoy 8) |
| `relevancia_maxima` | decimal o null | Mayor puntaje del reranker en el intento, con 3 decimales |
| `umbral_relevancia` | decimal | `UMBRAL_RELEVANCIA` aplicado (hoy 0,15) |
| `resultado` | APROBADO, REINTENTO, EVIDENCIA_INSUFICIENTE o ERROR | Decisión de la Tabla 10 para ese intento |

### Verificación

Controles del intento que decide: el aprobado o, si no hay, el último.

| Campo | Tipo | Descripción |
| --- | --- | --- |
| `numero_intento` | 1 o 2 | Intento al que corresponden los controles |
| `valida_citas` | booleano o null | 6.1: etiquetas y extractos de las citas |
| `valida_consistencia` | booleano o null | 6.2: clasificación, derivación y dosis |
| `valida_evidencia` | booleano o null | 6.3: suficiencia de la evidencia |
| `relevancia_maxima` | decimal o null | |
| `umbral_relevancia` | decimal | |

Un control vale null si no se llegó a ejecutar: por ejemplo, 6.1 y 6.2 cuando ningún fragmento
alcanzó el umbral, o los tres cuando la solicitud se bloqueó o la API falló. Las advertencias del
modelo no se verifican contra las fuentes; solo las citas (ver `docs/mediciones_sprint2.md`, D2).

### Ejemplo (consulta verificada, recortado)

```
{"tipo":"etapa","etapa":"validar","intento":null,"ms":214,"id_consulta":"7c1e…","resultado":"VALIDA","transcurrido_ms":218}
{"tipo":"etapa","etapa":"clasificar","intento":null,"ms":2,"id_consulta":"7c1e…","resultado":"SIN_ANEMIA","motivo":null,"transcurrido_ms":221}
{"tipo":"etapa","etapa":"normalizar","intento":1,"ms":11,"id_consulta":"7c1e…","terminos":4,"edad_meses":9,"transcurrido_ms":233}
{"tipo":"etapa","etapa":"recuperar","intento":1,"ms":3928,"id_consulta":"7c1e…","tipo_busqueda":"INICIAL","relevancia_maxima":0.977,"suficiente":true,"seleccionados":5,"transcurrido_ms":4161}
{"tipo":"etapa","etapa":"proteger","intento":1,"ms":5,"id_consulta":"7c1e…","control_identificadores":true,"fragmentos":5,"transcurrido_ms":4167}
{"tipo":"etapa","etapa":"generar","intento":1,"ms":7407,"id_consulta":"7c1e…","generacion":"RESPUESTA","stop_reason":"end_turn","transcurrido_ms":11575}
{"tipo":"etapa","etapa":"verificar","intento":1,"ms":32,"id_consulta":"7c1e…","resultado":"APROBADO","siguiente":null,"estado_final":"VERIFICADA","transcurrido_ms":11608}
{"tipo":"etapa","etapa":"salida","intento":1,"ms":9,"id_consulta":"7c1e…","estado_final":"VERIFICADA","transcurrido_ms":11618}
{"tipo":"fin","id_consulta":"7c1e…","estado":"VERIFICADA","idioma":"es","recomendacion":{…},"citas":[…],"numero_intentos":1,"intentos":[…],"verificacion":{…},"modo_prueba":false,"opciones_decision":[…],"transcurrido_ms":11619}
```

Si el cliente cierra la conexión a mitad del stream, la consulta sigue en el servidor hasta su
estado final. Ese resultado se obtiene después con `GET /api/consultas/{id_consulta}`, usando
el `id_consulta` del primer evento.

## GET /api/consultas/{id_consulta}

Devuelve el resultado guardado (`ResultadoConsulta`, JSON).

| Código | Caso |
| --- | --- |
| 200 | La consulta es propia |
| 404 | No existe o es de otro profesional |

Campos:
- **Identificación y estado:** `id_consulta`, `id_paciente`, `id_tamizaje`,
  `id_consulta_previa`, `estado` (los estados finales o EN_PROCESO), `mensaje` e `idioma`.
- **Pregunta:** `texto_filtrado`.
- **Tiempos:** `numero_intentos`, `fecha_hora_inicio`, `fecha_hora_fin` y `latencia_total_ms`.
- **Contexto clínico:** `datos_faltantes` (lista de `{campo, etiqueta, mensaje, completado}`),
  `vigencia` y `clasificacion`.
- **Respuesta:** `recomendacion`, `citas`, `intentos`, `verificacion` y `modo_prueba`, con el
  mismo formato que el evento `fin` (los decimales coinciden: 3 decimales en ambos).
- **Decisión:** `decision` (`{id_decision, id_usuario, tipo_decision, nota, fecha_registro}` o
  null) y `opciones_decision`.

## GET /api/pacientes/{id_paciente}/consultas

Consultas del paciente hechas por el usuario autenticado, de la más reciente a la más antigua
(M04, «Consultas previas»; M08, evaluaciones). Las de otros profesionales no se listan. El
historial del paciente (`GET /api/pacientes/{id}/historial`) trae la misma lista en `consultas`
(vacía si el rol no tiene REALIZAR_CONSULTA).

| Código | Caso |
| --- | --- |
| 200 | Lista (puede estar vacía) |
| 403 | Rol sin REALIZAR_CONSULTA (Administrador) |
| 404 | El paciente no existe |

Cada elemento (`ConsultaListada`):

| Campo | Tipo | Descripción |
| --- | --- | --- |
| `id_consulta`, `id_tamizaje` | UUID | |
| `fecha_tamizaje` | fecha | Tamizaje usado |
| `id_consulta_previa` | UUID o null | Consulta que esta reanuda |
| `estado` | estado final o EN_PROCESO | |
| `texto_filtrado` | texto o null | Pregunta tras el filtro de identificadores |
| `idioma` | `"es"` o `"en"` | |
| `fecha_hora_inicio`, `fecha_hora_fin` | fecha y hora | |
| `numero_intentos` | entero | |
| `latencia_total_ms` | entero o null | |
| `confirma_tamizaje_no_vigente` | booleano | |
| `categoria` | texto o null | Clasificación del tamizaje |
| `tipo_decision` | tipo o null | Decisión registrada, si la hay |
| `modo_prueba` | booleano | |

## POST /api/consultas/{id_consulta}/datos-faltantes

Completa la hemoglobina del mismo tamizaje (solo si está vacía, nunca sobrescribe), marca los
datos faltantes como completados y reanuda como consulta nueva, con `id_consulta_previa` igual
a la consulta original. Usa la pregunta original guardada en el servidor y responde con el
mismo NDJSON que la ruta anterior.

| Campo | Tipo | Obligatorio |
| --- | --- | --- |
| `hemoglobina_g_dl` | decimal de 3.0 a 20.0, con un decimal | Sí |
| `metodo_medicion` | HEMOGLOBINOMETRO o LABORATORIO | No |

| Código | Caso |
| --- | --- |
| 404 | No existe o es de otro profesional |
| 409 | La consulta no está en DATOS_FALTANTES, sus datos ya se completaron o ya se reanudó |
| 422 | Falta la altitud del distrito en el catálogo (lo corrige el administrador), falta otro dato que no se completa desde la consulta, o el cuerpo no es válido |

## POST /api/consultas/{id_consulta}/decision

M07 mínimo, «Registrar decisión clínica». Solo el profesional de la consulta, y una sola
decisión por consulta.

| Campo | Tipo | Obligatorio | Descripción |
| --- | --- | --- | --- |
| `tipo_decision` | ACEPTA_RECOMENDACION, MODIFICA_RECOMENDACION o CRITERIO_CLINICO_PROPIO | Sí | Debe estar en `opciones_decision` |
| `nota` | texto, hasta 1000 caracteres | Según `nota_obligatoria` (hoy, solo con MODIFICA_RECOMENDACION) | Conducta adoptada |

| Código | Caso |
| --- | --- |
| 201 | `{id_decision, id_usuario, tipo_decision, nota, fecha_registro}` |
| 404 | No existe o es de otro profesional |
| 409 | El estado no admite el tipo, o ya hay una decisión |
| 422 | Falta la nota obligatoria o el cuerpo no es válido |

La auditoría (DECISION_REGISTRADA) guarda el tipo y si hubo nota, nunca su texto.
