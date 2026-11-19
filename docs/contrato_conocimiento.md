# Contrato de la API de la base de conocimiento (parte F2b, HU12)

Rutas de la pantalla M11 para listar las guías, cargar un PDF de nivel 2, seguir el avance de la
indexación y reintentar una indexación fallida. OpenAPI lo refleja en `/docs` y `/openapi.json`.
Código: `backend/app/api/routes/conocimiento.py` y `backend/app/services/conocimiento.py`.
Pruebas: `backend/tests/test_conocimiento_api.py`. El trabajador del indexador (servicio
`indexador`, `jobs/README.md`) procesa los trabajos que crean estas rutas.

## Reglas comunes

- **Autenticación:** `Authorization: Bearer <token>`. Sin sesión válida: 401.
- **Permiso:** ADMINISTRAR_GUIAS (rol Administrador). Enfermera CRED, Médico, Nutricionista y
  Coordinador CRED reciben 403 en todas las rutas.
- **Conexión:** `cdss_admin` (lectura y escritura en `conocimiento`, lectura de `seguridad`, sin
  acceso a `clinico`). El administrador no gana acceso a datos clínicos.
- **Sin rutas del servidor:** ninguna respuesta lleva `ruta_blob` ni carpetas. El PDF se guarda
  como `<id_documento>.pdf` en el volumen `datos_guias_cargadas`; el nombre enviado por el usuario
  solo se usa para comprobar la extensión y no se guarda.
- **Errores:** `{"detail": "<mensaje en español>"}`. Un error inesperado responde 500 con el texto
  genérico de FastAPI, sin trazas.
- **Nivel:** desde la API solo se cargan documentos de nivel 2 (metodológicos, no se recuperan ni
  se citan). Los de nivel 1 se cargan por línea de comandos con sus transcripciones verificadas.
- **Trabajos activos:** como máximo 2 trabajos PENDIENTE o EN_CURSO a la vez (subidas y
  reintentos). Indexar satura el servicio `modelos` y retrasa las consultas (pendiente P14 de
  `docs/cambios_respecto_al_OE2.md`).
- **Fechas:** ISO 8601 con zona horaria.

## Objetos

### `Documento` (lista y base del detalle)

| Campo | Tipo | Descripción |
| --- | --- | --- |
| `id_documento` | uuid | |
| `titulo` | texto | |
| `codigo_documento` | texto o null | Código de la norma |
| `entidad_emisora` | texto | MINSA, OMS u OTRA |
| `tipo_documento` | texto | NORMA_TECNICA, GUIA, DIRECTIVA, RESOLUCION o LITERATURA |
| `nivel` | 1 o 2 | 1 citable, 2 metodológico |
| `version` | texto o null | Versión del documento (columna `version`) |
| `version_indexacion` | entero o null | Última versión de indexación (null si nunca se indexó) |
| `anio_publicacion` | entero | |
| `idioma` | `es` o `en` | |
| `estado` | texto | VIGENTE u OBSOLETA |
| `estado_indexacion` | texto | PENDIENTE, EN_PROCESO, COMPLETADA o ERROR |
| `fecha_carga` | fecha y hora | |
| `fragmentos_vigentes` | entero | Fragmentos con `vigente = true` |
| `citas_30_dias` | entero | Citas en recomendaciones de los últimos 30 días (`v_uso_documento`, sin consultas de prueba) |
| `retirado_por` | texto o null | Nombre de quien retiró la guía (solo en OBSOLETA; Sprint 3, parte F) |
| `fecha_retiro` | fecha y hora o null | Cuándo se retiró |
| `motivo_retiro` | texto o null | Motivo del retiro (10 a 250 caracteres) |
| `ultimo_trabajo` | `TrabajoResumen` o null | El trabajo más reciente del documento |

### `TrabajoResumen`

`id_trabajo`, `tipo` (INDEXACION, REINDEXACION o RETIRO), `estado` (PENDIENTE, EN_CURSO,
COMPLETADO o ERROR), `etapa` (EXTRACCION, FRAGMENTACION, NORMALIZACION, EMBEDDINGS, INDEXACION o
null), `procesados`, `total` (null si aún no se conoce), `mensaje_error`, `fecha_solicitud` y
`fecha_fin`.

### `Trabajo` (cola y detalle)

Los campos de `TrabajoResumen` más `id_documento`, `titulo` (del documento), `fecha_inicio` y
`solicitado_por` (nombre completo).

## Rutas

### `GET /api/conocimiento/documentos`

Lista de `Documento`. Orden estable: nivel 1 antes que nivel 2; dentro de cada nivel, vigentes
antes que obsoletas, año descendente, título e id.

### `GET /api/conocimiento/documentos/{id_documento}`

`Documento` más:

| Campo | Descripción |
| --- | --- |
| `fecha_publicacion` | Fecha o null |
| `pagina_inicio_cuerpo`, `pagina_fin_cuerpo` | Páginas que se indexan (null: todas) |
| `hash_archivo` | SHA-256 del PDF |
| `total_fragmentos` | Fragmentos de la última indexación completada |
| `cargado_por` | Nombre completo de quien cargó el documento |
| `versiones` | Lista de `{version_indexacion, fragmentos, vigentes, modelo_embedding}`, la más reciente primero |
| `trabajos` | Historial de `Trabajo`, el más reciente primero |

404 si no existe; 422 si el id no es un uuid.

### `POST /api/conocimiento/documentos` (multipart)

Campos del formulario:

| Campo | Obligatorio | Valores |
| --- | --- | --- |
| `archivo` | sí | PDF, extensión `.pdf`, hasta 20 MB (`CDSS_MAX_BYTES_GUIA`) |
| `titulo` | sí | 3 a 255 caracteres |
| `codigo_documento` | no | Hasta 80 caracteres (vacío equivale a null) |
| `entidad_emisora` | sí | MINSA, OMS u OTRA |
| `tipo_documento` | sí | NORMA_TECNICA, GUIA, DIRECTIVA, RESOLUCION o LITERATURA |
| `anio_publicacion` | sí | Desde 1948 hasta el año actual |
| `idioma` | sí | `es` o `en` |
| `nivel` | sí | 2 (1 se rechaza, ver abajo) |
| `pagina_inicio_cuerpo`, `pagina_fin_cuerpo` | no | Las dos o ninguna; 1 o más e inicio menor o igual que fin |

Respuesta 201: `{"documento": Documento, "trabajo": Trabajo}`, con el documento en PENDIENTE y
un trabajo INDEXACION en PENDIENTE.

Validaciones, en este orden (la primera que falla responde):

| Código | Causa | Auditoría |
| --- | --- | --- |
| 409 | Ya hay 2 trabajos activos (se comprueba antes de leer el archivo y otra vez al insertar) | |
| 422 | Falta el campo `archivo` | |
| 415 | La extensión no es `.pdf` | GUIA_CARGA_RECHAZADA, motivo `no_es_pdf` |
| 415 | El archivo no empieza con `%PDF-` | GUIA_CARGA_RECHAZADA, motivo `no_es_pdf` |
| 413 | Supera el máximo; se corta mientras se copia | GUIA_CARGA_RECHAZADA, motivo `tamano` y `max_bytes` |
| 409 | El SHA-256 ya existe; el mensaje trae el título del documento existente | GUIA_CARGA_RECHAZADA, motivo `duplicado` e `id_documento_existente` |
| 422 | Metadatos no válidos; `detail` empieza con «Metadatos no válidos» y nombra los campos | |
| 422 | `nivel` es 1 | GUIA_CARGA_RECHAZADA, motivo `nivel` |

Nginx admite hasta 25 MB solo en esta ruta (413 de Nginx por encima). El archivo se copia por
partes a un temporal del volumen mientras se calcula el SHA-256. En una sola transacción se
insertan el documento (PENDIENTE, `cargado_por`, `ruta_blob local://guias_cargadas/<id>.pdf` y el
hash), el trabajo y el evento GUIA_CARGADA; el temporal se renombra a `<id>.pdf` antes del commit.
Si algo falla, se borran el temporal y el archivo renombrado, y no queda ninguna fila.

### `GET /api/conocimiento/trabajos?activos=true`

Lista de `Trabajo`, del más reciente al más antiguo. Con `activos=true`, solo PENDIENTE y
EN_CURSO (para refrescar el avance en M11); sin el parámetro, los 50 más recientes.

### `POST /api/conocimiento/documentos/{id_documento}/reintentar`

Respuesta 201: `{"trabajo": Trabajo}`. Crea un trabajo REINDEXACION si el documento ya tiene
fragmentos de una versión anterior, o INDEXACION si nunca se indexó, y deja el documento en
PENDIENTE.

| Código | Causa |
| --- | --- |
| 404 | El documento no existe |
| 409 | El documento ya tiene un trabajo PENDIENTE o EN_CURSO |
| 409 | El documento no está en ERROR |
| 409 | Ya hay 2 trabajos activos |
| 409 | La guía está retirada (OBSOLETA) y su último trabajo no es un RETIRO en ERROR: una obsoleta no se vuelve a indexar |

Con una guía OBSOLETA cuyo último trabajo es un RETIRO en ERROR, crea otro trabajo **RETIRO** (no una
reindexación) y no cambia `estado_indexacion`; el evento es GUIA_RETIRO_REINTENTADO.

## Retiro de guías (HU17, Sprint 3 parte F)

Reglas (decisión 6 del plan): la guía retirada pasa a OBSOLETA y se conserva (nunca se borra). Nivel 2:
sin restricción. Nivel 1: solo sin referencias vigentes y escribiendo su código para confirmar. No hay
«reactivar»: el retiro no se deshace desde la pantalla ni desde la API.

### `GET /api/conocimiento/documentos/{id_documento}/referencias`

Permiso ADMINISTRAR_GUIAS. Respuesta 200; 404 si la guía no existe.

```json
{"id_documento": "...", "nivel": 1, "estado": "VIGENTE", "codigo_confirmacion": "NTS 213-MINSA/DGIESP-2024",
 "referencias": [{"tipo": "PUNTERO", "descripcion": "La regla de punteros «nts213-tabla4» (punteros.yaml) la usa como documento de origen"}],
 "puede_retirarse": false}
```

`codigo_confirmacion` es lo que hay que escribir para confirmar el retiro de una guía de nivel 1 (su
código o, si no tiene, su título); null en el nivel 2. En el nivel 2 `referencias` es siempre `[]`. En
el nivel 1, en este orden:

| `tipo` | Qué la bloquea |
| --- | --- |
| UMBRAL_HEMOGLOBINA | Puntos de corte vigentes (`vigente_hasta` nulo) con su `id_documento` |
| AJUSTE_ALTITUD | Ajustes por altitud vigentes con su `id_documento` |
| PARAMETRO_SISTEMA | Cada parámetro vigente con su `id_documento` |
| MODIFICACION | Fragmentos de la última versión de otra guía vigente cuyo `id_documento_modificatorio` es ella (es una norma que modifica a otra) |
| MAPA_MODIFICACIONES | Es la norma modificatoria o la guía base de un mapa del indexador (`app/indexador/modificaciones/*.yaml`; hoy la RM 429 sobre la NTS 213) |
| PUNTERO | Una regla de `app/rag/punteros.yaml` la usa como documento de origen o de destino |

### `POST /api/conocimiento/documentos/{id_documento}/retiro`

Permiso ADMINISTRAR_GUIAS. Cuerpo: `{"motivo": "...", "confirmacion": "..."}` (`confirmacion` solo en
el nivel 1; comparación exacta). Respuesta 201: `{"documento": Documento, "trabajo": Trabajo}`, como la
subida, con el documento ya OBSOLETA y el trabajo RETIRO en PENDIENTE.

Comprobaciones en orden: permiso (401, 403), modo de evaluación (423, acción RETIRAR_GUIA, evento
PARAMETRO_CAMBIO_BLOQUEADO), motivo, candado de la cola, guía existente, ya obsoleta, trabajo activo,
referencias del nivel 1 y confirmación del nivel 1. Después, en una sola transacción: `estado`
OBSOLETA, `retirado_por`, `fecha_retiro`, `motivo_retiro` (sin espacios en los extremos), el trabajo
RETIRO y el evento GUIA_RETIRADA. El retiro no cuenta para el límite de 2 trabajos activos (no usa el
servicio de modelos).

Los errores propios del retiro llevan `{"detail": "...", "codigo": "..."}`:

| Código HTTP | `codigo` | Causa |
| --- | --- | --- |
| 404 | NO_ENCONTRADA | La guía no existe |
| 409 | YA_OBSOLETA | La guía ya está retirada |
| 409 | TRABAJO_ACTIVO | La guía tiene un trabajo PENDIENTE o EN_CURSO |
| 409 | REFERENCIAS_VIGENTES | Nivel 1 con referencias; el cuerpo trae además `referencias` (la misma lista del GET) |
| 422 | MOTIVO_INVALIDO | El motivo, sin espacios en los extremos, no tiene de 10 a 250 caracteres |
| 422 | CONFIRMACION_INCORRECTA | Nivel 1 sin `confirmacion` o distinta del código |
| 423 | (sin código) | Modo de evaluación |

### Trabajo RETIRO (indexador)

El trabajador (`cdss_indexador`) pone `estado_documento` = OBSOLETA en los metadatos de todos los
vectores de la guía en ChromaDB, por lotes con `update`, sin borrar nada (`cdss_indexador` no tiene
DELETE) y sin tocar los fragmentos de PostgreSQL. Comprueba al final que no quede ningún vector sin el
estado nuevo. Es idempotente: repetirlo deja lo mismo, y una guía sin vectores termina igual. Si
falla, el trabajo queda en ERROR con el mensaje «No se pudieron actualizar los vectores de la guía en
ChromaDB (...)» y el evento GUIA_RETIRO_ERROR; al terminar bien, GUIA_RETIRO_APLICADO con el número de
vectores. Un trabajo RETIRO interrumpido por un reinicio del trabajador pasa a ERROR con su propio
mensaje. Una indexación de una guía OBSOLETA que llegue a la cola termina en ERROR sin indexar.

Mientras el RETIRO no termina (o si falla), la guía ya no se recupera: BM25 y la comprobación final
filtran `d.estado = 'VIGENTE'` en PostgreSQL (`CONDICION_RECUPERABLE`), la caché de BM25 cambia de
huella y se reconstruye sola, y los punteros buscan su destino con la misma condición. Las consultas
ya registradas conservan sus citas: M05, M08, M09 y M13 no filtran por el estado del documento.

## Auditoría

Entidad `documento_fuente`. El detalle no lleva el título, el nombre del archivo, el texto del
documento ni datos clínicos.

| Evento | Detalle |
| --- | --- |
| GUIA_CARGADA | `id_documento`, `nivel`, `tipo_documento`, `entidad_emisora`, `anio_publicacion`, `idioma`, `tamano_bytes`, `sha256` |
| GUIA_CARGA_RECHAZADA | `motivo` (`no_es_pdf`, `tamano`, `duplicado` o `nivel`) y, según el motivo, `max_bytes`, `id_documento_existente` o `nivel` |
| GUIA_REINDEXACION_SOLICITADA | `id_trabajo`, `tipo` |
| GUIA_RETIRADA | `id_documento`, `codigo_documento`, `nivel`, `motivo`, `id_trabajo` (sin el título ni el nombre de quien retira, que va en `id_usuario`) |
| GUIA_RETIRO_REINTENTADO | `id_trabajo`, `tipo` (RETIRO) |

El trabajador registra además GUIA_INDEXADA, GUIA_INDEXACION_ERROR, GUIA_RETIRO_APLICADO (`id_trabajo`,
`vectores`) y GUIA_RETIRO_ERROR (`id_trabajo`, `error`) (`jobs/README.md`).
