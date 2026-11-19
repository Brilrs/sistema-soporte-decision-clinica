# Contrato de la API de auditoría (M13, HU13; Sprint 3, parte D1)

Rutas de la pantalla M13 «Auditoría y trazabilidad» (parte D2). OpenAPI lo refleja en `/docs` y
`/openapi.json`. Código: `backend/app/api/routes/auditoria.py` y
`backend/app/services/auditoria_consultas.py`; vistas en la migración 014
(`db/migraciones/014_auditoria.sql`). Ejemplos reales, generados por las pruebas con datos
sintéticos y normalizados, en `frontend/src/__fixtures__` (`auditoria_indicadores.json`,
`auditoria_consultas.json` y `auditoria_detalle.json`); tipos en `frontend/src/api/tipos_auditoria.ts`.

Nada de esta parte usa el modelo de lenguaje.

## Reglas comunes

- **Autenticación:** `Authorization: Bearer <token>`. Sin sesión válida: 401.
- **Permiso:** VER_AUDITORIA (Coordinador CRED y Administrador). Enfermera CRED, Médico y
  Nutricionista no lo tienen: 403 con `{"detail": "Su rol no tiene el permiso VER_AUDITORIA"}`,
  la misma respuesta de permiso que el resto del proyecto.
- **Conexión de solo lectura:** los datos se leen con `cdss_auditor` (`DATABASE_URL_AUDITOR`), que
  solo tiene SELECT sobre `asistencia.v_auditoria_consulta`, `asistencia.v_auditoria_lista`,
  `asistencia.v_indicadores_operativos` y el esquema `auditoria`. No puede leer
  `clinico.paciente_identidad`, `clinico.paciente`, `asistencia.consulta` (incluidos
  `texto_consulta` y `texto_filtrado`), `clinico.tamizaje.observaciones` ni
  `asistencia.decision_clinica.descripcion`, ni escribir en ninguna tabla. Además, cada transacción
  de esa conexión es de solo lectura (`default_transaction_read_only`).
- **Qué se oculta:** ninguna respuesta trae nombre, DNI, historia clínica, dirección, fecha de
  nacimiento, el texto original de la consulta, las observaciones del tamizaje ni la nota de la
  decisión. El usuario que aparece es el profesional que hizo la consulta (`nombre_usuario`, el
  usuario del sistema), como en el mockup.
- **Consultas de prueba:** una consulta es de prueba si alguno de sus intentos lo generó el
  cliente falso (`modelo_llm = 'modelo-falso'`, la regla de P2). Los indicadores nunca las cuentan;
  la lista las oculta por omisión y, con `incluir_pruebas=true`, las muestra con `modo_prueba: true`
  (decisión 5 del plan del Sprint 3).
- **Validación:** filtros no válidos dan 422 con el formato del proyecto:
  `{"detail": "Revise los datos ingresados. <campo>: <mensaje>", "errores": [{"campo", "mensaje"}]}`.
- **Bitácora:** abrir la lista o un detalle deja el evento AUDITORIA_CONSULTADA (ver
  «Auditoría de la auditoría»). Los indicadores no dejan evento.

## GET /api/auditoria/indicadores

Indicadores de los últimos 30 días hasta el momento de la consulta (`desde` y `hasta` los da la
base), sin consultas de prueba. Salen de `asistencia.v_indicadores_operativos`.

| Campo | Tipo | Descripción |
| --- | --- | --- |
| `dias` | entero | 30 |
| `desde`, `hasta` | fecha y hora | Ventana de los indicadores |
| `consultas` | entero | Consultas iniciadas en la ventana |
| `evaluadas` | entero | VERIFICADA más EVIDENCIA_INSUFICIENTE |
| `por_estado` | objeto | Conteo de cada estado (los 8, también en 0); la suma es `consultas` |
| `pct_verificadas`, `pct_evidencia_insuficiente` | número o null | Porcentaje sobre `consultas`, con un decimal; null sin consultas |
| `con_reintento`, `pct_con_reintento` | entero, número o null | Consultas con dos intentos |
| `latencia_p50_ms`, `latencia_p90_ms` | entero o null | Percentiles de `latencia_total_ms` de todas las consultas |
| `latencia_p90_flujo_normal_ms` | entero o null | p90 de las consultas con un intento o sin llamada al modelo («Tiempo p90 · flujo normal» del mockup) |
| `solicitudes_bloqueadas`, `errores` | entero | Consultas SOLICITUD_BLOQUEADA y ERROR |
| `tokens_entrada`, `tokens_salida` | entero | Suma de los intentos reales de la ventana |
| `costo_api_usd` | número | Costo de los intentos reales de la ventana |

| Código | Caso |
| --- | --- |
| 200 | `Indicadores` |
| 401, 403 | Ver «Reglas comunes» |

## GET /api/auditoria/consultas

Todas las consultas (de todos los profesionales), de la más reciente a la más antigua. Con la
misma fecha y hora de inicio, por `id_consulta` descendente (uuid comparado por bytes): el orden
no depende de la colación de la base y nunca se ordena por un texto.

| Parámetro | Tipo | Descripción |
| --- | --- | --- |
| `estado` | uno de los 8 estados | Opcional |
| `fecha_desde`, `fecha_hasta` | fecha (AAAA-MM-DD) | Días calendario de Lima, inclusivos: desde las 00:00 del primero hasta antes de las 00:00 del día siguiente al último. `fecha_hasta` anterior a `fecha_desde`: 422 |
| `incluir_pruebas` | booleano | Por omisión `false` |
| `limite` | entero de 1 a 100 | Por omisión 20 |
| `desplazamiento` | entero mayor o igual a 0 | Por omisión 0 |

Respuesta: `{"total", "limite", "desplazamiento", "incluir_pruebas", "consultas": [...]}`. `total`
cuenta las consultas con los mismos filtros. Cada consulta:

| Campo | Tipo | Descripción |
| --- | --- | --- |
| `id_consulta` | UUID | |
| `fecha_hora_inicio`, `fecha_hora_fin` | fecha y hora (`fin` puede ser null) | |
| `nombre_usuario` | texto | Usuario del sistema que hizo la consulta |
| `estado` | texto | |
| `numero_intentos`, `con_reintento` | entero, booleano | `con_reintento` es `numero_intentos = 2` |
| `latencia_total_ms` | entero o null | «Tiempo» del mockup |
| `modo_prueba` | booleano | |
| `modelo_llm`, `version_prompt` | texto o null | Del último intento; null si no hubo llamada al modelo |
| `tokens_entrada`, `tokens_salida`, `tokens_total` | entero o null | Suma de los intentos; null sin intentos con tokens |
| `costo_usd` | número o null | Suma de los intentos |

| Código | Caso |
| --- | --- |
| 200 | Página |
| 401, 403, 422 | Ver «Reglas comunes» |

## GET /api/auditoria/consultas/{id_consulta}

Detalle de una consulta con sus intentos, de `asistencia.v_auditoria_consulta`.

| Campo | Tipo | Descripción |
| --- | --- | --- |
| Datos de la consulta | | `id_consulta`, `fecha_hora_inicio`, `fecha_hora_fin`, `nombre_usuario`, `estado`, `numero_intentos`, `latencia_total_ms`, `confirma_tamizaje_no_vigente`, `modo_prueba` |
| `tokens_entrada`, `tokens_salida`, `tokens_total`, `costo_usd` | | Totales de los intentos |
| `intentos` | lista | Uno por intento, en orden; vacía si la consulta no llegó a la búsqueda (por ejemplo, FUERA_DE_DOMINIO) |

Cada intento:

| Campo | Descripción |
| --- | --- |
| `numero_intento`, `tipo_busqueda`, `resultado` | INICIAL o AMPLIADA; APROBADO, REINTENTO, EVIDENCIA_INSUFICIENTE o ERROR |
| `modelo_llm`, `version_prompt` | Modelo efectivo y versión del prompt |
| `tokens_entrada`, `tokens_salida`, `tokens_razonamiento`, `costo_usd`, `latencia_llm_ms` | |
| `candidatos_evaluados` | Candidatos que evaluó el reranker |
| `verificacion` | `valida_citas` (6.1 Citas textuales), `valida_consistencia` (6.2 Consistencia y dosis), `valida_evidencia` (6.3 Suficiencia de la evidencia), `relevancia_maxima` y `umbral_relevancia`, con el mismo formato que en `docs/contrato_consultas.md` |
| `control_identificadores` | Resultado del control previo al envío; `false` si la solicitud se bloqueó |
| `hash_solicitud` | SHA-256 de la solicitud serializada |
| `solicitud_enviada` | La solicitud tal como quedó registrada (ya pasó por la lista blanca de `proteccion.py`). La vista solo la muestra si `control_identificadores` es `true`; una bloqueada nunca se guarda y, aunque quedara una, aquí sería null. Se guarda como JSONB: el contenido es el enviado, pero el orden de las claves y los espacios no son los bytes del hash |
| `fragmentos` | Los enviados al modelo, por etiqueta: `etiqueta`, `puntaje_reranker` (null en un fragmento agregado por referencia), `origen` (RERANKER o PUNTERO), `posicion_final`, `documento` (código o título de la guía), `seccion`, `pagina_inicio` y `pagina_fin` |

| Código | Caso |
| --- | --- |
| 200 | `DetalleAuditoria` |
| 401, 403 | Ver «Reglas comunes» |
| 404 | `{"detail": "La consulta no existe"}` |
| 422 | El id no es un UUID |

## Auditoría de la auditoría

Evento AUDITORIA_CONSULTADA, con la conexión clínica (como los demás eventos; la del auditor no
escribe), el usuario que consultó, la entidad `asistencia.consulta` y nunca datos personales:

| Ruta | `id_entidad` | `detalle` |
| --- | --- | --- |
| Lista | null | `vista: "lista"`, `estado`, `fecha_desde`, `fecha_hasta`, `incluir_pruebas`, `limite`, `desplazamiento`, `total` y `consultas` (cantidad devuelta) |
| Detalle | id de la consulta | `vista: "detalle"` y `encontrada` (false en un 404) |

## Uso desde la interfaz (M13, parte D2)

- `/admin/auditoria` pide los indicadores y la primera página de la lista al abrirse. Los filtros
  (`estado`, `desde`, `hasta`), el interruptor (`pruebas=1`) y la página (`pagina`) van en la
  dirección; la pantalla los traduce a `estado`, `fecha_desde`, `fecha_hasta`, `incluir_pruebas=true`,
  `limite=20` y `desplazamiento`. Sin el interruptor no se envía `incluir_pruebas`.
- Cada fila abre `/admin/auditoria/{id}`, que pide el detalle; «Volver a la auditoría» regresa con
  los mismos filtros y la misma página.
- La pantalla solo llama a estas tres rutas (además de la sesión), no guarda nada en localStorage
  ni sessionStorage y reduce cada respuesta a los campos de este contrato: un campo nuevo que
  enviara el servidor no se muestra.
- La solicitud se muestra con `JSON.stringify(solicitud, null, 2)`. Si es null, la pantalla explica
  si el control previo la bloqueó (`control_identificadores` false) o si el intento no llegó a
  enviarla.

## Configuración

- `DATABASE_URL_AUDITOR`: en `docker-compose.yml` se arma con `CDSS_DB_PWD_AUDITOR` (que ya crean
  `generar_env.sh` y `db/aplicar_bd.sh`); en las pruebas está en `backend/.env.test.example`; en
  Azure, la contraseña va a Key Vault.
- Las vistas `v_auditoria_consulta` y `v_indicadores_operativos` agregaron columnas al final en la
  migración 014. Las migraciones 011 y 012 no las vuelven a definir si ya tienen esa forma, porque
  `CREATE OR REPLACE VIEW` no admite quitar columnas.
