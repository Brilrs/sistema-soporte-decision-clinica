# Cierre del Sprint 3: reportes, auditoría, parámetros clínicos y retiro de guías

Fecha de cierre: 19/11/2026 (parte Z). Cierra el desarrollo de las partes A a K, J y Z. Quedan
fuera de este cierre el despliegue en Azure (parte L) y el trabajo de evaluación del OE3, que se
hacen después, con el sistema congelado (sección 8).

Este documento resume, para la revisión con el asesor, qué se entregó en el Sprint 3, cómo se
verificó, qué se midió y qué queda pendiente. Como el cierre del Sprint 2, no repite el detalle
técnico: remite a los documentos del repositorio.

En cada sección se distingue:
- **Medido:** cifras de una medición o de una corrida de pruebas, con su fecha.
- **Decisión:** algo que se resolvió así a propósito, con su motivo en `docs/plan_sprint3.md` o en
  `cambios_respecto_al_OE2.md`.
- **Pendiente:** lo que falta, con su dueño.

| Documento | Qué contiene |
| --- | --- |
| [`plan_sprint3.md`](plan_sprint3.md) | Plan, partes, dependencias y las 16 decisiones, con su estado final (sección 9) |
| [`cambios_respecto_al_OE2.md`](cambios_respecto_al_OE2.md) | Cada diferencia con el OE2 (filas 1 a 153; las del Sprint 3 son de la 104 a la 153) y los pendientes P1 a P14 |
| [`mediciones_sprint2.md`](mediciones_sprint2.md) | Mediciones, incluida la de la parte J del Sprint 3 (al principio del documento) |
| [`contrato_reportes.md`](contrato_reportes.md), [`contrato_auditoria.md`](contrato_auditoria.md), [`contrato_parametros.md`](contrato_parametros.md), [`contrato_conocimiento.md`](contrato_conocimiento.md) y [`contrato_autenticacion.md`](contrato_autenticacion.md) | Contratos de la API de M09, M13, M12, M11 y del inicio de sesión |
| [`respaldo.md`](respaldo.md) | Respaldo, restauración y verificación de ChromaDB y de las guías cargadas |
| [`mejoras_despliegue.md`](mejoras_despliegue.md) | Mejoras para Azure: dos resueltas en la parte I y una asignada a la parte L |
| [`../jobs/README.md`](../jobs/README.md) | Indexador, lote de embeddings (parte J) y medición de la interferencia |

## 1. Qué se entregó

El Sprint 3 abarcaba HU10, HU13, HU14 y HU17, con las pantallas M09, M12 y M13, los pendientes
asignados al Sprint 3 y la preparación del despliegue y del OE3. Se entregaron las cuatro
historias.

**Antes de las partes:**
- HU16 (aviso de evidencia insuficiente, M07) ya se había entregado en el Sprint 2 (decisión 1).
- El registro de la decisión clínica (RF8) se había adelantado al Sprint 2.
- La fase 0 (18/11/2026) dejó el inventario, el plan y las 16 decisiones (`plan_sprint3.md`).

| Parte | Entregable | Historias y pendientes | Filas de `cambios` |
| --- | --- | --- | --- |
| A | Auditoría visual versionada en `frontend/auditoria/` (desbordes en 10 anchos, elementos absolutos que escapan y axe-core), el plan y las decisiones | P13 | 104 a 108 |
| B | `GET /api/consultas` y «Historial de consultas» con las consultas propias; nombre de quien registró la decisión | P10, P12 | 109 a 111 |
| C1 | API del reporte: PDF con ReportLab, número EV-AAAA-NNNNN, hash SHA-256 y auditoría; destinos expediente y cuidador | HU10 | 112 y 113 |
| C2 | Pantalla M09, «Exportar reporte» en M05 y M07, «Reporte» en M08 y la lista «Reportes» | HU10, P11 | 114 a 117 |
| D1 | API de auditoría con la conexión de solo lectura `cdss_auditor` y la migración 014 | HU13 | 118 a 120 |
| D2 | Pantalla M13 con indicadores de 30 días, lista con filtros y detalle por consulta | HU13 | 121 |
| E1a | Base de M12: migración 015, historial cerrado, permiso VER_PARAMETROS, huella de la configuración y modo de evaluación | HU14 | 122 a 124 |
| E1b | Edición por grupo con control de versión (409), validaciones, confirmación escrita y «Confirmar contra la norma»; migración 016 | HU14 | 125 a 128 |
| E2 | Pantalla M12 | HU14 | 129 a 133 |
| F | Retiro de guías en M11 con las guardas del nivel 1, trabajo RETIRO del indexador y migración 017 | HU17 | 134 a 139 |
| I | Cambio obligatorio de contraseña e invalidación de sesiones (contador `version_sesion`); migración 018 | `mejoras_despliegue.md` | 140 a 145 |
| K | `python -m app.respaldo`: crear, restaurar, verificar, comparar y descartar colecciones de prueba; destino local y Azure Blob (simulado en las pruebas) | RNF2 | 146 a 149 |
| J | `INDEXADOR_LOTE_EMBEDDINGS` (1 por omisión) y `app.scripts.medir_interferencia` | P14 | 150 y 151 |
| Z | Este cierre; aviso de M11 con lo medido; 409 de un archivo ya cargado como guía retirada; limpieza de «En construcción» | | 152 y 153 |

Las partes G (carga de nivel 1 desde M11 con «Aprobar») y H (P9, consultas encadenadas) quedan
fuera del Sprint 3 (**decisión** 7 y 8).

### Pantallas nuevas o ampliadas

| Pantalla | Historia | Qué hace | Parte |
| --- | --- | --- | --- |
| M09 Reporte exportable | HU10 | Vista previa, PDF para el expediente o para el cuidador, número correlativo, hash y lista de reportes emitidos | C1 y C2 |
| M13 Auditoría y trazabilidad | HU13 | Indicadores de 30 días sin consultas de prueba, lista con filtros y detalle con la solicitud exacta enviada al proveedor, sin identificadores | D1 y D2 |
| M12 Parámetros clínicos | HU14 | Puntos de corte, ajuste por altitud y vigencia editables solo por el Coordinador CRED, con motivo, referencia, historial y huella | E1a, E1b y E2 |
| M11 Base de conocimiento | HU17 | «Retirar» con motivo, referencias que bloquean y código del nivel 1 | F |
| Historial de consultas y Reportes | P10 | Consultas propias con filtros; «Exportar» por fila | B y C2 |
| Cambiar mi contraseña | | Obligatoria con la marca y voluntaria desde el encabezado | I |

## 2. Cómo se verificó

**Medido** el 19/11/2026, en la rama `sprint-3-z-cierre` (desde `main` en `e04b5fe`, más los
cambios de la parte Z):

| Verificación | Resultado | Al cierre del Sprint 2 |
| --- | --- | --- |
| Pruebas del backend (`pytest -q`, base PostgreSQL de pruebas) | 1129 pasan; 63 quedan fuera por las marcas `lenta`, `api_real` y `chroma_real` | 736 |
| Prueba nueva de la parte Z (`tests/test_z_duplicado.py`), 10 corridas seguidas | 8 pasan en las 10 | |
| Pruebas del frontend (`npm test`, Vitest) | 393 pasan, en 20 archivos | 251, en 10 archivos |
| Compilación del frontend (`npm run build`, con `tsc -b`) | Sin errores. El proyecto no tiene un linter configurado: la comprobación de tipos es la única revisión estática | Sin errores |
| Auditoría visual de M11 (11 vistas, 10 anchos de 320 a 1920 px, axe a 390 y 1280 px) | Sin desbordes y 0 infracciones en 22 vistas | |
| Integración continua (GitHub Actions) | Backend, servicio de modelos y frontend en cada push | Igual |

Las pruebas `lenta` (PDF reales e índice) y `chroma_real` no se volvieron a correr en el cierre.

Además, en cada parte con interfaz:
- **Accesibilidad y desbordes:** la auditoría de `frontend/auditoria/` (parte A) con las ventanas
  abiertas y cerradas, sin infracciones de axe (WCAG 2.0 y 2.1, A y AA) ni desbordes en 10 anchos.
- **Pruebas de mutación:** en cada parte se quitó cada comportamiento importante, de a uno, para
  comprobar que alguna prueba fallara. En la parte Z: 7 mutaciones del aviso de M11 y del 409 de la
  guía retirada, todas detectadas.
- **Datos sintéticos:** las corridas con el modelo real usaron solo los pacientes de `seed_demo` y
  las ejecutó el responsable.

**Robustez de las pruebas:** una prueba de la parte K (la distancia del respaldo) fallaba a veces
en el CI porque dependía de ids al azar; se hizo determinista con vectores fijos (19/11/2026, 50
corridas seguidas sin fallos).

## 3. Mediciones

**Medido.** Datos completos en `data/mediciones/` (no se versiona).

### Interferencia de la indexación con las consultas (parte J, 19/11/2026)

Carga sintética continua que imita al indexador y las 15 primeras consultas de latencia de la
recuperación, sin carga y con carga (`app.scripts.medir_interferencia`, solo lectura; método en
`mediciones_sprint2.md`, «Sprint 3, parte J»).

**Perfil normal** (equipo de desarrollo, `modelos` con 4 hilos):

| Lote | Sin carga (mediana) | Con carga: mediana / máximo | Llamada más lenta | 100 fragmentos, solos |
| --- | --- | --- | --- | --- |
| 8 (antes) | 3,3 a 3,4 s | 34,4 a 35,1 s / 60,6 a 62,6 s | 32,3 s | 165 a 176 s |
| 4 | 3,4 s | 14,6 s / 21,2 s | 13,6 s | 126 s |
| 2 | 3,4 s | 6,4 s / 9,1 s | 8,4 s | 93 s |
| **1 (vigente)** | 3,3 a 3,4 s | **4,6 a 4,7 s / 6,3 a 6,4 s** | **5,9 s** | **76 s** |

**Perfil B2ms** (`docker-compose.b2ms.yml`, 2 CPU, `modelos` con 2 hilos):

| Lote | Sin carga (mediana) | Con carga: mediana / máximo | Llamada más lenta | 100 fragmentos, solos |
| --- | --- | --- | --- | --- |
| 8 | 7,1 s | 63,4 s / 111,2 s | 57,3 s | 323 s |
| 2 | 6,3 s | 11,9 s / 17,7 s | 11,5 s | 159 s |
| **1** | 6,3 s | **8,4 s / 12,8 s** | **9,2 s** | **133 s** |

- El objetivo, fijado antes de medir para el perfil normal (mediana de 8 s o menos, llamada más
  lenta de 15 s o menos e indexar sin tardar más del doble), se cumple con el lote 1. En B2ms la
  mediana con carga queda en 8,4 s (**pendiente** de validar con el asesor, sección 6).
- Con lote 8 el 57 % de los tokens procesados era relleno; los vectores con lote 1 difieren en
  3e-7 como mucho, así que no hizo falta reindexar.
- La medición del 16/11/2026 (24 s con lote 8, indexación real) no es directamente comparable: no
  quedaron sus datos crudos y la carga era distinta (`mediciones_sprint2.md`).

### Otras mediciones del Sprint 3

| Medida | Valor | Fuente |
| --- | --- | --- |
| Generación del PDF del reporte | 1,2 s y unos 20 MB la primera vez en el proceso (carga de la fuente); de 12 a 26 ms después | `plan_sprint3.md`, parte C1 |
| Página de `GET /api/consultas` con 10 000 consultas de un usuario | unos 17 ms con `ix_consulta_id_usuario` | `plan_sprint3.md`, parte B |

Las latencias de la consulta completa, la calidad de la recuperación y la memoria no cambiaron en
el Sprint 3: siguen las de `cierre_sprint2.md`, sección 3.

## 4. Diferencias con el documento OE2

Están en [`cambios_respecto_al_OE2.md`](cambios_respecto_al_OE2.md), filas 104 a 153, con su
motivo. Las de mayor peso para el documento son:
- **Decisión:** solo el Coordinador CRED edita M12, y la recuperación y el riesgo por clasificación
  quedan en solo lectura (filas 104 y 122 a 124);
- **Decisión:** retiro de guías de nivel 1 solo sin referencias vigentes y con el código escrito
  (filas 105 y 134 a 139);
- **Decisión:** la carga de nivel 1 desde M11 sigue por línea de comandos (fila 106);
- **Decisión:** despliegue y OE3 solo con datos sintéticos (fila 107);
- **Decisión:** los PDF quedan en el volumen de la máquina, con respaldo a Blob (filas 108 y 146 a
  149);
- auditoría con un usuario de base de datos de solo lectura (fila 118);
- contador de sesión en lugar de comparar fechas (fila 141);
- lote de embeddings de 1 texto (filas 150 y 151).

## 5. Pendientes

**Dueños** (los mismos del cierre del Sprint 2):
- **Desarrollo:** el responsable del proyecto.
- **Asesor:** decisiones de alcance o de redacción del documento.
- **Asesor y personal de salud:** lo que afecta el trabajo clínico (en M12, la coordinadora CRED).
- **Por asignar:** cuando los documentos no nombran un dueño.

**Fechas:** el repositorio no fija fechas de calendario para la parte L, la evaluación del OE3 ni
las revisiones con el asesor. Donde no hay una, se escribe «por definir».

### Estado de P1 a P14

| N.° | Tema | Estado al cierre del Sprint 3 | Dueño | Fecha |
| --- | --- | --- | --- | --- |
| P1, P2, P5, P6 | Nota filtrada, consultas de prueba, reanudar y cambio de tramo | Resueltos en el Sprint 2 (F1) | Desarrollo | Hecho |
| P3 | Filtro de dominio frente a preguntas genéricas | Abierto; se evalúa como está (decisión 15, sección 7) | Desarrollo | Evaluación del OE3 (por definir) |
| P4 | Tabla N° 4 de la RM 429 | Resuelto en parte (Sprint 2, G); el resto se evalúa como está (sección 7) | Desarrollo | Evaluación del OE3 (por definir) |
| P7 | Códigos internos en el texto del modelo | Abierto; se evalúa como está (sección 7) | Desarrollo | Evaluación del OE3 (por definir) |
| P8 | Preguntas de dos partes | Abierto; se evalúa como está (sección 7) | Desarrollo | Evaluación del OE3 (por definir) |
| P9 | Consultas de seguimiento encadenadas | Fuera del Sprint 3 (decisión 8, parte H) | Desarrollo | Por definir |
| P10, P12 | Consultas propias y quién registró la decisión | Resueltos (parte B) | Desarrollo | Hecho |
| P11 | Exportar reporte (M09) | Resuelto (C1 y C2); falta la revisión de las frases del cuidador (sección 6) | Desarrollo | Hecho |
| P13 | Auditoría de desbordes | Resuelto (parte A) | Desarrollo | Hecho |
| P14 | Indexación y consultas a la vez | Resuelto (parte J); el objetivo en B2ms queda por validar (sección 6) | Desarrollo | Hecho |

### Otros pendientes

| Tema | Detalle | Dueño | Fecha |
| --- | --- | --- | --- |
| Despliegue en Azure (parte L) | Compose de producción, HTTPS en el puerto 443, secretos en Key Vault, `aplicar_bd.sh` con `\getenv` (`mejoras_despliegue.md`), prueba real del respaldo a Blob y medición en la máquina B2ms | Desarrollo | Por definir |
| Trabajo de evaluación del OE3 | RAGAS y CUE sobre el sistema congelado, con el juez solo sobre datos sintéticos (decisión 13) | Desarrollo | Por definir |
| Carga de nivel 1 desde M11 con «Aprobar» y recorte por documento (parte G) | Después del OE3 (decisión 7) | Desarrollo | Por definir |
| Inicio de sesión con una cuenta desactivada | Corregido (fila 168): primero se comprueba la contraseña. Con la contraseña equivocada, una cuenta desactivada recibe el 401 genérico «Usuario o contraseña incorrectos», igual que un usuario inexistente (que pasa por un hash ficticio para tardar lo mismo); solo con la contraseña correcta sale el 403 de cuenta desactivada. Queda como está el 423 de una cuenta activa bloqueada, que sí indica que la cuenta existe | Desarrollo | Hecho (26/11/2026) |
| Reactivar una cuenta no reinicia los intentos fallidos | Corregido (fila 168): `reactivar` (`backend/app/services/usuarios.py`) pone `intentos_fallidos` en 0, así que la cuenta no vuelve bloqueada; el evento USUARIO_REACTIVADO registra si estaba bloqueada (`desbloqueada`), sin contraseñas | Desarrollo | Hecho (26/11/2026) |

### Restos de la base de desarrollo que no se pueden borrar

**Medido** con consultas de solo lectura el 19/11/2026. La bitácora de auditoría no admite cambios
ni eliminaciones y referencia estas filas, así que se conservan:

| Resto | Estado | Efecto |
| --- | --- | --- |
| Cuentas `prueba.nueva` y `prueba.clave` | Inactivas, creadas y desactivadas el 19/11/2026; `prueba.nueva` conserva la marca de cambio obligatorio | No pueden iniciar sesión; aparecen en M10 como desactivadas |
| Guía «Guía de prueba del retiro» | Nivel 2, OBSOLETA desde el 19/11/2026, 2 fragmentos | No se recupera ni se cita. Por ella ChromaDB tiene 204 vectores y la última versión 185 fragmentos vigentes (183 de las 4 guías de nivel 1) |

## 6. Validaciones pendientes con el asesor o con clínicos

Todas son **pendientes**, salvo los valores clínicos `[VERIFICAR]`, ya validados y registrados en M12. Ninguna cambia el código hasta que se decida.

| Tema | Qué hay que validar | Dueño | Fecha |
| --- | --- | --- | --- |
| Frases del reporte para el cuidador | `backend/app/reportes/lenguaje_sencillo.yaml` sigue con `revisado: false` y cada página lleva «Texto en revisión clínica: no entregar a pacientes». Las frases pendientes de aprobación (las 21 del YAML y los textos fijos del código) están en `docs/revision_frases_cuidador.md`; la derivación repetida, la frase final y la fecha con hora ya se corrigieron (fila 166) | Coordinación CRED y asesor | Por definir |
| Rangos de plausibilidad y avisos de M12 | `backend/app/services/parametros_reglas.py`: Hb de 2,0 a 20,0 g/dL; vigencia de 7 a 90 días, con aviso por encima de 60; cobertura de altitud de al menos 4380 m; ajuste de 0 a 6,0 g/dL; aviso si un límite de Hb cambia más de 1,0 g/dL (también si «sin anemia» queda fuera de 10,0 a 12,0 o un ajuste cambia más de 0,5) | Asesor | Por definir |
| Valores clínicos `[VERIFICAR]` | Puntos de corte de Hb, ajuste por altitud, vigencia de 30 días y niveles de riesgo: validados por la coordinación CRED el 25/11/2026, sin observaciones (`docs/validacion_parametros_clinicos.md`, fila 164). Confirmados en M12 el 26/11/2026 y huella de control calculada (la definitiva se calcula al congelar) | Equipo del proyecto (registro hecho en M12 con la cuenta de demostración coord.ortiz, sobre la ficha del CRED) | Hecho el 26/11/2026; el congelamiento sigue pendiente |
| Altitudes de los distritos `[VERIFICAR]` | Catálogo de `db/init/02_catalogos.sql` contra el INEI; fuera de M12, por migración | Desarrollo | Antes del OE3 (por definir) |
| Descriptores MeSH y DeCS `[VERIFICAR]` | Los de `clinico.sintoma` (`02_catalogos.sql`) y los de `diccionario_normalizacion.yaml`, tomados de memoria. **Hallazgo de la parte Z:** ningún código de recuperación, reescritura de la consulta ni filtro los usa; solo existen como datos (detalle abajo). Conviene corregir el documento de tesis | Desarrollo | Por definir |
| Revisión de las guías de nivel 1 (N1) | Las tablas críticas transcritas están verificadas (en la última versión, 22 fragmentos de transcripción con `verificado` verdadero: 8 de la NTS 213 y 14 de la RM 429); el resto del texto de nivel 1 viene de la capa de texto del PDF (180 fragmentos de la última versión) sin una revisión clínica fragmento por fragmento | Asesor y personal de salud | Por definir |
| Objetivo de la parte J | En B2ms la mediana de la recuperación con una indexación en curso es 8,4 s, frente al objetivo de 8 s fijado para el perfil normal | Asesor | Por definir |
| Filtro [FECHA] de la nota de la decisión | Corregido el error de los rangos decimales («Hb entre 9.5-10.4» ya no se marca) y agregados los formatos que no se filtraban (fila 167). Las fechas completas de la nota (por ejemplo «control el 20/12/2026») se siguen reemplazando por [FECHA]: conservar las fechas de control queda como limitación declarada por privacidad | Asesor y personal de salud | Limitación declarada |
| Prompt v1.1 frente a v1.2 | `VERSION_PROMPT` sigue en v1.1; la v1.2 compacta bajó el p90 a 11,71 s en el perfil normal y no se adoptó (fila 58) | Asesor | Antes de congelar el sistema (por definir) |
| Redacción del RNF3 | Propuesta de la fila 61 (sección 7) | Asesor | Revisión del documento OE2 (por definir) |

**Descriptores MeSH en el código (revisado en la parte Z):**
- `backend/app/rag/normalizacion.py`: `normalizar()` copia `mesh_id`, `mesh_termino` y
  `decs_termino` del diccionario en cada `TerminoNormalizado`, y `ConsultaNormalizada.descriptores_mesh`
  los lista, pero esa propiedad no se llama en ningún sitio.
- `backend/app/rag/recuperacion.py`, `buscar_candidatos()`: BM25 y ChromaDB usan
  `texto_normalizado` (abreviaturas expandidas) y, en la búsqueda ampliada, `texto_ampliado()`
  (sinónimos en español y los equivalentes en inglés del campo `ingles` del diccionario), sin MeSH.
- `backend/app/rag/registro.py`: `intento_generacion.terminos_normalizados` guarda los términos
  preferidos en español, no los MeSH, aunque el comentario de la columna diga «MeSH/UMLS».
- `backend/app/indexador/repositorio.py`, `insertar_fragmentos()`: `fragmento.terminos_mesh` y
  `conceptos_umls` se guardan vacíos (`'{}'`).
- `clinico.sintoma.descriptor_mesh`: ninguna consulta del backend lo lee (`catalogos.py`,
  `pacientes.py`, `consulta_estructurada.py` y `proteccion.py` leen solo el nombre del síntoma).
- `backend/app/rag/dominio.py` usa los conceptos del diccionario marcados `dominio`, no sus MeSH.

## 7. Limitaciones conocidas que se evalúan tal como están (decisión 15)

**Decisión:** no se tocan antes del OE3, para evaluar el sistema que se entrega.

| Limitación | Situación | Fuente |
| --- | --- | --- |
| RNF3 | p90 de la respuesta completa de 11,7 s (v1.2) a 18,9 s (B2ms) frente a menos de 10 s; con reintento se cumple el máximo de 25 s. Redacción propuesta en la fila 61 | `cierre_sprint2.md`, sección 3 |
| P3 | El filtro de dominio rechaza preguntas genéricas sin términos del dominio («¿Cómo lo manejo?») | Fila 66 |
| P7 | La respuesta a veces trae códigos internos como SIN_ANEMIA | Fila 47 |
| P8 | En preguntas de dos partes, si falta la evidencia de una, la respuesta no lo distingue de una ausencia real | Fila 48 |
| Resto de P4 | En el calendario de control de Hb siguen sin la Tabla N° 4 A01 y A12 (conjunto A) y B01, B04, B06 y B08 (conjunto B) | `cierre_sprint2.md`, sección 5 |
| Tabla N° 20 | En las consultas de tratamiento suele llegar el fragmento que la cita y no la tabla: criterio estricto 2 de 4 (A) y 1 de 7 (B) | `cierre_sprint2.md`, sección 5 |
| Lote del reranker | El puntaje del reranker int8 de un par cambia según los otros candidatos del lote (hasta 0,119); el umbral de 0,15 hereda esta dependencia | `cierre_sprint2.md`, sección 5 |

## 8. Antes de la evaluación OE3 (congelar el sistema)

Procedimiento propuesto (**decisión** 13; lo ejecuta el responsable). Los comandos van en Git Bash,
desde la raíz del repositorio y con el stack levantado.

1. **Sin cambios en curso:** que no haya trabajos de indexación pendientes ni en curso (M11), y no
   cargar ni retirar guías desde aquí.
2. **Mismo prompt:** comprobar que `VERSION_PROMPT` sea el decidido (hoy v1.1; sección 6). La huella
   del paso 5 lo muestra.
3. **Verificar y respaldar la base de conocimiento:**
   ```bash
   docker compose run --rm respaldo python -m app.respaldo verificar   # debe decir «Coincide con PostgreSQL»
   docker compose run --rm respaldo python -m app.respaldo crear
   ```
   Además, el `pg_dump` de PostgreSQL de `docs/respaldo.md`.
4. **Modo de evaluación:** agregar `CDSS_MODO_EVALUACION=true` a `.env` y recrear el backend
   (`docker compose up -d backend`). M11 (cargar, reintentar y retirar) y M12 (editar) responden 423.
5. **Huella de la configuración:**
   ```bash
   docker compose exec backend python -m app.scripts.huella_configuracion --json
   ```
   o «Copiar» en M12 (`GET /api/parametros/huella`). Guardarla junto a la etiqueta y repetirla al
   terminar: debe ser la misma.
6. **Etiqueta de versión:** el responsable etiqueta en git el commit evaluado.
7. **Durante la evaluación:** solo datos sintéticos (decisión 12); el conjunto de prueba se mide una
   sola vez; las consultas de prueba (`CDSS_LLM=falso`) quedan fuera de las métricas (P2).

**Pendiente:** hoy nada impide, salvo el procedimiento, cambiar `VERSION_PROMPT` por migración o
cambiar `.env` durante la evaluación; la huella del paso 5 lo detecta.

**Diseño de la evaluación (26/11/2026):** está en [`diseno_evaluacion_oe3.md`](diseno_evaluacion_oe3.md)
(fila 169). CUE se reporta con la definición del OE2 (proporción de los fragmentos enviados que
sustentan la respuesta) como cifra principal, más el diagnóstico de cuatro cuadrantes del artículo
RAG-X como análisis complementario. La revisión clínica de los casos queda en manos de la
coordinación CRED, con una ficha. El conjunto, con su esquema y un piloto de 12 casos en
`jobs/evaluacion_oe3/conjunto/`, **sigue sin revisar** (`revisado: false`). El job de evaluación
(`backend/app/evaluacion/`, imagen y perfil `evaluacion`, fila 170) está implementado y probado solo
con el cliente falso; la evaluación definitiva no se ejecutó.
