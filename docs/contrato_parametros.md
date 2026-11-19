# Contrato de la API de parámetros (M12, HU14; Sprint 3, parte E1a)

Rutas de solo lectura de la pantalla M12 «Parámetros clínicos» (parte E2). La edición (un PUT por
grupo con la tabla completa) es la parte E1b y se agregará a este contrato. OpenAPI lo refleja en
`/docs` y `/openapi.json`. Código: `backend/app/api/routes/parametros.py` y
`backend/app/services/parametros.py`; esquema en la migración 015 (`db/migraciones/015_parametros.sql`).
Ejemplos reales, generados por las pruebas con la base de pruebas, en `frontend/src/__fixtures__`
(`parametros.json` del Coordinador, `parametros_solo_lectura.json` del Administrador,
`parametros_historial.json` y `parametros_huella.json`); tipos en `frontend/src/api/tipos_parametros.ts`.

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
cambian lo que el sistema responde: hoy la carga y el reintento de guías de M11, y la edición de M12
desde la parte E1b. Cada intento responde **423** con `{"detail": "El sistema está en modo de
evaluación: los cambios de parámetros y de la base de conocimiento están bloqueados hasta que termine
la evaluación."}` y deja el evento PARAMETRO_CAMBIO_BLOQUEADO con `{"accion": "CARGAR_GUIA"}` o
`{"accion": "REINTENTAR_INDEXACION"}` (y el id del documento en el reintento), sin datos personales.
Las lecturas no cambian. Función reutilizable: `app.core.evaluacion.bloquear_en_evaluacion`.
