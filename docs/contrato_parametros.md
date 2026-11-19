# Contrato de la API de parámetros (M12, HU14; Sprint 3, partes E1a y E1b)

Rutas de la pantalla M12 «Parámetros clínicos» (parte E2): lectura (E1a) y edición por grupo (E1b).
OpenAPI lo refleja en `/docs` y `/openapi.json`. Código: `backend/app/api/routes/parametros.py`,
`backend/app/services/parametros.py` (lectura), `backend/app/services/parametros_edicion.py` y
`backend/app/services/parametros_reglas.py` (edición y reglas); esquema en las migraciones 015 y 016.
Ejemplos reales, generados por las pruebas con la base de pruebas, en `frontend/src/__fixtures__`
(`parametros.json` del Coordinador, `parametros_solo_lectura.json` del Administrador,
`parametros_historial.json`, `parametros_huella.json` y `parametros_put_*.json`); tipos en
`frontend/src/api/tipos_parametros.ts` y llamadas en `frontend/src/api/parametros.ts`.

## Reglas comunes

- **Autenticación:** `Authorization: Bearer <token>`. Sin sesión válida: 401.
- **Permisos:**
  - VER_PARAMETROS (Coordinador CRED y Administrador) para las tres rutas. Enfermera CRED, Médico y
    Nutricionista: 403 con `{"detail": "Su rol no tiene el permiso VER_PARAMETROS"}`.
  - CONFIGURAR_PARAMETROS (solo el Coordinador CRED) para editar en la parte E1b. `puede_editar` lo
    indica.
- **Conexión:** las lecturas usan `cdss_clinica`, que solo tiene SELECT sobre `configuracion`.
- **Qué se edita (decisión 4 del plan del Sprint 3):** solo los puntos de corte (tramos fijos de 6 a
  23 y de 24 a 59 meses), el ajuste por altitud y la vigencia del tamizaje. El riesgo por
  clasificación (`categoria_anemia`, sin versionar) y los parámetros de recuperación, del modelo y de
  la indexación son de solo lectura: se cambian solo por migración, con medición.
- **Parámetros sin uso:** `EDAD_MIN_CLASIFICACION`, `EDAD_MAX_CLASIFICACION`, `REINTENTOS_MAXIMOS` y
  `MODELO_RESPALDO` no se muestran (no los usa el código).
- **Efecto de un cambio (E1b):** un punto de corte o un ajuste nuevo se aplica a los **tamizajes
  nuevos**. Un tamizaje ya clasificado conserva su clasificación (`resultado_clasificacion` guarda los
  ids y valores aplicados), también en sus consultas posteriores. La vigencia del tamizaje se aplica
  en la consulta siguiente.

## Versionado e historial cerrado

- Cada valor es una fila con `vigente_desde` y `vigente_hasta` (nulo mientras está vigente). Cambiar un
  valor es cerrar la fila vigente e insertar otra; nunca se edita ni se borra.
- El trigger `configuracion.fn_historial_solo_cierre` solo admite, para las conexiones de la
  aplicación, el cambio de `vigente_hasta` de NULL a una fecha no anterior a `vigente_desde`. El
  propietario de la tabla o un superusuario (migraciones, carga inicial y desmontaje de las pruebas)
  no tiene esa restricción.
- `rol_app_admin` solo tiene `UPDATE (vigente_hasta)` e INSERT en las tres tablas versionadas, y solo
  SELECT en `categoria_anemia`.
- `ex_umbral_hb_sin_traslape`: en edades que se superponen, los rangos de Hb vigentes de categorías
  distintas no se superponen.
- Columnas de cada versión: `motivo_cambio`, `referencia` (tabla y página de la norma), `verificado`
  (falso en la carga inicial: valores pendientes de verificación contra la norma) e `id_documento`
  (la norma; nulo permitido en `parametro_sistema`).
- Migración 016 (`fn_version_nueva_vigente`, BEFORE INSERT): para las conexiones de la aplicación,
  una versión nueva entra vigente (`vigente_hasta` nulo) y con `vigente_desde` en el día de hoy en
  Lima; no se puede insertar una versión cerrada ni con fecha pasada o futura. Mismo criterio de
  exención que la 015 (propietario o superusuario).
- La edición usa `now()` de la transacción para cerrar la versión anterior y abrir la nueva: las dos
  quedan con la misma marca de tiempo (historial contiguo y exacto dentro del día) y esa marca cae en
  el día de hoy en Lima. Dos cambios el mismo día sobre la misma fila funcionan: la versión creada
  hoy se cierra con una marca posterior.

## GET /api/parametros

| Campo | Descripción |
| --- | --- |
| `puede_editar` | El usuario tiene CONFIGURAR_PARAMETROS |
| `modo_evaluacion` | `CDSS_MODO_EVALUACION` activo: la edición responde 423 |
| `puntos_corte` | `{version, tramos: [{edad_min_meses, edad_max_meses, categorias: [...]}]}`; cada categoría con `id_umbral`, `categoria`, `nivel_riesgo`, `hb_min_g_dl` (null en la severa), `hb_max_g_dl` (null en «sin anemia») y los datos de la versión |
| `ajuste_altitud` | `{version, rangos: [{id_ajuste, altitud_min_msnm, altitud_max_msnm, ajuste_g_dl, ...}]}`, por altitud ascendente |
| `vigencia_tamizaje` | `DIAS_VIGENCIA_TAMIZAJE` con `version`, `id_parametro`, `valor` (texto), `tipo_dato`, `valor_minimo`, `valor_maximo`, `descripcion` y los datos de la versión |
| `riesgo` | `[{nombre, nivel_riesgo, requiere_derivacion, orden}]`, por `orden` |
| `recuperacion`, `modelo`, `indexacion` | Parámetros de solo lectura con el mismo formato que la vigencia, sin `version` |

Datos de la versión: `documento` (`{id_documento, codigo, titulo}` o null), `referencia`,
`motivo_cambio`, `verificado`, `vigente_desde` y `modificado_por` (nombre del usuario).

**Versión de un grupo:** SHA-256 (hexadecimal, 64 caracteres) de `"<grupo>:<ids vigentes ordenados
como enteros, separados por comas>"`. Cambia si alguien cerró o creó una fila del grupo. La parte E1b
la exige en el PUT y responde 409 si no coincide (control optimista).

| Código | Caso |
| --- | --- |
| 200 | `Parametros` |
| 401, 403 | Ver «Reglas comunes» |

## GET /api/parametros/historial

| Parámetro | Descripción |
| --- | --- |
| `grupo` | `puntos_corte`, `ajuste_altitud`, `vigencia_tamizaje`, `recuperacion`, `modelo` o `indexacion`; sin él, todos |
| `limite` | 1 a 100, por omisión 20 |
| `desplazamiento` | 0 o más |

Respuesta: `{total, limite, desplazamiento, grupo, versiones: [...]}`. Cada versión: `grupo`, `tabla`,
`id`, `elemento` («6 a 23 meses · ANEMIA_LEVE», «0 a 499 m.s.n.m.» o la clave), `valores`,
`vigente_hasta`, `vigente` y los datos de la versión.

Orden: `vigente_desde` descendente, luego el grupo (en el orden de la tabla de arriba) y el id
descendente. Se ordena en Python con esa clave: no depende de la colación de la base.

| Código | Caso |
| --- | --- |
| 200 | Página |
| 401, 403 | Ver «Reglas comunes» |
| 422 | Filtros no válidos (formato del proyecto) |

## GET /api/parametros/huella

SHA-256 de la configuración vigente, para registrar con qué configuración se hizo cada medición del
OE3. Componentes, cada uno con su propio SHA-256 sobre un JSON canónico (claves ordenadas, sin
espacios, decimales como texto) y en listas ordenadas en Python:

| Componente | Contenido |
| --- | --- |
| `puntos_corte` | Tramo, categoría, límites de Hb y norma de cada punto de corte vigente |
| `ajuste_altitud` | Rango, ajuste y norma de cada rango vigente |
| `categorias` | Riesgo y derivación de cada categoría de anemia |
| `parametros_sistema` | Clave, valor y tipo de cada parámetro vigente (todos, también los sin uso) |
| `indexacion` | Para cada guía vigente e indexada: id, código y versión de indexación |
| `version_prompt` | `VERSION_PROMPT` |

`huella` es el SHA-256 del JSON canónico de las huellas de los componentes. Respuesta:
`{huella, algoritmo: "SHA-256", calculada_en, version_prompt, componentes: [{nombre, huella,
elementos}], indexacion: [{id_documento, codigo, version_indexacion}]}`. La misma huella en dos
mediciones indica la misma configuración. Desde la línea de comandos:
`docker compose exec backend python -m app.scripts.huella_configuracion` (o `--json`).

## Modo de evaluación (OE3)

`CDSS_MODO_EVALUACION=true` (solo en el entorno; ninguna ruta lo cambia) bloquea las escrituras que
cambian lo que el sistema responde: la carga y el reintento de guías de M11 y los tres PUT de M12.
Cada intento responde **423** con `{"detail": "El sistema está en modo de evaluación: los cambios de
parámetros y de la base de conocimiento están bloqueados hasta que termine la evaluación."}` y deja el
evento PARAMETRO_CAMBIO_BLOQUEADO con `{"accion": ...}`: `CARGAR_GUIA`, `REINTENTAR_INDEXACION` (con el
id del documento), `EDITAR_PUNTOS_CORTE`, `EDITAR_AJUSTE_ALTITUD` o `EDITAR_VIGENCIA_TAMIZAJE`, sin datos
personales. En los PUT el bloqueo va antes de cualquier validación. Las lecturas no cambian. Función
reutilizable: `app.core.evaluacion.bloquear_en_evaluacion`.

## Edición (parte E1b)

Tres rutas, una por grupo, con permiso **CONFIGURAR_PARAMETROS** (solo el Coordinador CRED; el
Administrador y los roles clínicos reciben 403 con `{"detail": "Su rol no tiene el permiso
CONFIGURAR_PARAMETROS"}`). Se escribe con la conexión de `cdss_admin`.

| Ruta | Cuerpo propio |
| --- | --- |
| `PUT /api/parametros/puntos-corte` | `tramos`: los dos tramos con sus cuatro categorías (`categoria`, `hb_min_g_dl`, `hb_max_g_dl`, `verificado`) |
| `PUT /api/parametros/ajuste-altitud` | `rangos` de menor a mayor altitud (`altitud_min_msnm`, `altitud_max_msnm`, `ajuste_g_dl`, `verificado`) |
| `PUT /api/parametros/vigencia-tamizaje` | `valor` (días, entero o texto) y `verificado` |

Cuerpo común:

| Campo | Descripción |
| --- | --- |
| `version` | La versión del grupo leída en el GET (64 caracteres hexadecimales): control optimista |
| `motivo_cambio` | Obligatorio, de 10 a 500 caracteres (sin espacios al inicio ni al final); se guarda en cada versión nueva |
| `referencia` | Norma, tabla y página. Obligatoria cuando algún valor queda verificado; se guarda en cada versión nueva |
| `id_documento` | Opcional: la norma. Sin él, cada versión nueva conserva el documento de la anterior (un rango de altitud nuevo fuera de los vigentes lo exige) |
| `confirmacion_escrita` | `CONFIRMO` cuando el cambio tiene advertencias |

Las filas tienen el mismo formato que el GET: el frontend puede reenviar lo que leyó (los campos de
más, como ids, documento o motivo, se ignoran).

**Transacción:**
1. Bloqueo del grupo (`pg_advisory_xact_lock`) y comparación de la versión: si no coincide, **409**.
2. Validación: errores duros, advertencias y cambios.
3. Se **cierran primero** las versiones que cambian (`vigente_hasta = now()`) y **después** se insertan
   las nuevas (`vigente_desde = now()`): las restricciones EXCLUDE y el índice único de los
   parámetros vigentes no son diferibles. Las filas sin cambio conservan su id. En altitud, un rango
   que ya no está en la tabla se cierra y uno nuevo se inserta.
4. Evento **PARAMETRO_CAMBIADO** (entidad: la tabla del grupo) con `grupo`, `cerrados`, `creados`,
   `cambios` (elemento, antes y después), `advertencias_confirmadas`, `motivo_cambio`, `referencia` e
   `id_documento`. Sin datos personales.

Si algo falla a mitad de camino, la transacción se deshace entera: nunca queda una versión cerrada sin
su reemplazo.

**Respuesta 200:** `{grupo, resumen}`. `grupo` tiene el mismo formato que en el GET, con la versión
nueva; `resumen` es `{grupo, cerrados, creados, cambios, advertencias_confirmadas}`.

### Errores duros (422, `codigo: "VALIDACION"`)

Formato del proyecto, con la ruta del campo (por ejemplo `tramos.0.categorias.1.hb_max_g_dl`):
`{"detail": "Revise los datos ingresados. <campo>: <mensaje>; ...", "codigo": "VALIDACION", "errores":
[{"campo", "mensaje"}]}`. Los errores de tipo del cuerpo (por ejemplo, `motivo_cambio` corto o una
`version` mal formada) tienen el mismo formato, sin `codigo`.

| Grupo | Regla |
| --- | --- |
| Puntos de corte | Los tramos de edad son fijos (6 a 23 y 24 a 59 meses) y cada uno tiene las cuatro categorías existentes, una vez cada una |
| Puntos de corte | Un solo decimal y entre 2,0 y 20,0 g/dL |
| Puntos de corte | La categoría más severa sin límite inferior, «sin anemia» sin límite superior, las demás con los dos, y el mínimo no mayor que el máximo |
| Puntos de corte | De la más severa a «sin anemia», el mínimo de cada categoría es el máximo de la anterior más 0,1: contiguos, sin huecos ni traslapes y en orden de riesgo |
| Ajuste por altitud | El primer rango empieza en 0 y cada uno empieza en el máximo del anterior más 1 (sin huecos ni traslapes); el mínimo no mayor que el máximo |
| Ajuste por altitud | La tabla cubre al menos hasta 4380 m.s.n.m. (la altitud máxima del catálogo de distritos) |
| Ajuste por altitud | Ajuste de 0,0 a 6,0 g/dL con un decimal, no decreciente con la altitud |
| Vigencia | Entero dentro de `valor_minimo` y `valor_maximo` de la fila y de 7 a 90 días |
| Todos | `id_documento` debe existir; `referencia` es obligatoria si algún valor queda verificado; no se puede quitar `verificado` sin cambiar el valor |

### Advertencias (422, `codigo: "REQUIERE_CONFIRMACION"`)

Si hay advertencias y `confirmacion_escrita` no es `CONFIRMO`: `{"detail": "El cambio tiene
advertencias: revíselas y escriba CONFIRMO para guardarlo", "codigo": "REQUIERE_CONFIRMACION",
"advertencias": [{"campo", "mensaje"}]}`. Con `CONFIRMO`, se guarda y las advertencias quedan en el
resumen y en el evento. Umbrales en `parametros_reglas.py` (**por validar con el asesor**):

| Advertencia | Umbral |
| --- | --- |
| Un límite de Hb cambia respecto del vigente | Más de 1,0 g/dL |
| El punto de corte de «sin anemia» cambia y queda fuera del rango | Fuera de 10,0 a 12,0 g/dL |
| Un ajuste cambia respecto del vigente (o del rango vigente que cubría esa altitud) | Más de 0,5 g/dL |
| La vigencia del tamizaje | Mayor de 60 días |

Los errores duros se informan antes que las advertencias. La configuración sembrada pasa la
validación completa de sí misma.

### Sin cambios (422, `codigo: "SIN_CAMBIOS"`)

`{"detail": "No hay cambios: los valores y su estado de verificación son los vigentes", "codigo":
"SIN_CAMBIOS"}` cuando ningún valor cambia y ninguna fila pasa de no verificada a verificada.

### Confirmar contra la norma

Un PUT con los mismos valores es válido si alguna fila pasa de `verificado: false` a `true` y trae
`referencia`. Crea una versión nueva con los mismos valores, `verificado` verdadero, la referencia,
el motivo y el documento. No se puede volver a falso sin cambiar el valor. No hay «restaurar una
versión anterior»: volver a un valor es un cambio nuevo con su motivo.

### Conflicto (409, `codigo: "VERSION_DESACTUALIZADA"`)

`{"detail": "Los parámetros cambiaron desde que los abrió: recargue la página para ver los valores
vigentes", "codigo": "VERSION_DESACTUALIZADA", "version_actual": "<versión vigente>"}`. Con dos PUT
seguidos con la misma versión, solo el primero pasa.

### Efecto

- Un punto de corte o un ajuste nuevo se aplica a los **tamizajes nuevos** (clasificación con el
  `id_umbral` y el `id_ajuste` nuevos); un tamizaje ya clasificado conserva su clasificación y sus
  ids, también en sus consultas posteriores.
- Un cambio de vigencia se aplica en la consulta siguiente y en las marcas de vigencia de M02 y M08.
- La versión del grupo, la huella y el historial cambian con cada PUT.

## Uso desde la interfaz (M12, parte E2)

- `/admin/parametros` pide `GET /api/parametros`, la huella y la primera página del historial. Los
  botones de edición dependen de `puede_editar`; con `modo_evaluacion` (o tras un 423) quedan
  deshabilitados con el motivo.
- Cada grupo se edita por separado. Al guardar, la pantalla reenvía las filas tal como las leyó, con
  los valores nuevos, su `verificado` y la `version` del grupo; el motivo y la referencia se escriben
  en la ventana de confirmación. En los puntos de corte solo se escribe el límite superior y el inferior
  se calcula; en la altitud solo se escribe el ajuste.
- Errores: VALIDACION se muestra junto a cada campo (por la ruta) y en un resumen; REQUIERE_CONFIRMACION
  pide escribir CONFIRMO exacto y reenvía `confirmacion_escrita`; 409 ofrece «Recargar valores», que
  descarta la edición y vuelve a leer; SIN_CAMBIOS, 423 y 403 muestran el mensaje sin perder lo escrito.
- Después de guardar se recargan la huella y el historial.
