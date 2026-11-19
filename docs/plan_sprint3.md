# Plan del Sprint 3

Fecha: 18/11/2026 (fase 0, revisado en la parte A). Fuentes:
- `docs/cierre_sprint2.md`;
- `docs/cambios_respecto_al_OE2.md`;
- los contratos de `docs/`;
- `docs/mejoras_despliegue.md`;
- `README.md` y `jobs/README.md`;
- el documento del OE2 (sección 6.2 y matriz de trazabilidad);
- el código de `main` en `d3c58ae`.

El OE2 no trae criterios de aceptación de las historias: solo su nombre, la matriz de
trazabilidad y la descripción de las pantallas. Las decisiones tomadas para este plan están al
final (sección 8).

**Alcance del Sprint 3:** HU10, HU13, HU14 y HU17, las pantallas M09, M12 y M13, los pendientes
asignados al Sprint 3 y la preparación del despliegue en Azure y de la evaluación del OE3. HU16
(«Recibir aviso de evidencia insuficiente», M07) se entregó en el Sprint 2 (decisión 1).

## 1. Inventario de pendientes

| # | Ítem | Fuente | Observación |
| --- | --- | --- | --- |
| 1 | M09 reporte exportable (HU10, P11) | OE2 6.2 y Tabla 5; cierre §1; P11 | Destinos «expediente clínico» y «entrega al cuidador» en lenguaje sencillo; PDF o impresión; número correlativo; firma y sello |
| 2 | P12, nombre de quien registró la decisión | P12 (fila 77) | Va con M09 |
| 3 | M12 parámetros clínicos (HU14) | OE2 6.2; cierre §1 | Puntos de corte, ajuste por altitud, vigencia, riesgo por clasificación y parámetros de búsqueda, con historial de cambios |
| 4 | M13 auditoría y trazabilidad (HU13) | OE2 6.2; cierre §1 | Indicadores de 30 días, tabla de consultas y detalle con la solicitud exacta enviada al proveedor |
| 5 | HU17, retirar guías | OE2 Tabla 4; fila 25; cierre §5 | La guía retirada pasa a «Obsoleta» y se conserva para la trazabilidad |
| 6 | Carga de nivel 1 desde M11 con revisión («Aprobar») | Cierre §5 (nuevos) | No está en el OE2, que solo dice que en M11 se elige el nivel al cargar. Es una decisión del Sprint 2 (filas 95 y 98). Va después del OE3 (decisión 7) |
| 7 | Recorte de márgenes por documento | Cierre §5 (nuevos) | Va con el ítem 6 |
| 8 | P9, consultas de seguimiento encadenadas | P9; transición M05 → M04 del OE2 6.1 | Fuera del Sprint 3 (decisión 8) |
| 9 | P10, lista de consultas del usuario (`GET /api/consultas`) | P10 (fila 80) | Cada profesional ve solo las suyas (decisión 9) |
| 10 | P13, auditoría de desbordes versionada | P13 (fila 84) | Resuelto en la parte A: `frontend/auditoria/` |
| 11 | Cambio obligatorio de contraseña en el primer inicio de sesión | `mejoras_despliegue.md` | Entra al Sprint 3 (decisión 11) |
| 12 | Invalidar las sesiones al restablecer la contraseña | `mejoras_despliegue.md` | Antes de Azure; va con el ítem 11 |
| 13 | Respaldo de ChromaDB (y de las guías) a Blob Storage | `jobs/README.md`; RNF2 del OE2 | |
| 14 | Trabajo de evaluación del OE3 (RAGAS y CUE) | `jobs/README.md`; OE2 3.2 (contenedor Jobs) | No existe en el código. Parte propia (decisión 13) |
| 15 | HTTPS: Nginx en el puerto 443 con un certificado de Let's Encrypt | OE2 3.2 | Hoy `frontend/nginx.conf` solo escucha en el puerto 80 |
| 16 | P14, indexación y consultas a la vez | P14; cierre §3 | Antes de Azure |
| 17 | Despliegue en Azure (B2ms, PostgreSQL B1ms, Key Vault y Blob) | Cierre §5; OE2 3.2 | |
| 18 | P3, P4 (resto), P7, P8, Tabla N° 20 y lote del reranker | Cierre §5 | No se tocan antes del OE3 (decisión 15) |
| 19 | Valores `[VERIFICAR]` de `db/init/02_catalogos.sql` | CLAUDE.md; README | Antes de la validación con usuarios. Interactúa con M12 |

**Lo que el OE2 dice de las historias** (Tabla 1 de la sección 7):

| Historia | Nombre | Pantalla | Requisitos | Tablas |
| --- | --- | --- | --- | --- |
| HU10 | Generar reporte clínico | M09 | RF6 | `reporte` |
| HU13 | Consultar registros de auditoría | M13 | RNF3, RNF4 | `evento_auditoria`, `v_auditoria_consulta`, `v_indicadores_operativos` |
| HU14 | Configurar parámetros del sistema | M12 | RF4, RF5, RNF5 | `umbral_hemoglobina`, `ajuste_altitud`, `categoria_anemia`, `parametro_sistema` |
| HU17 | Retirar una guía obsoleta | M11 | RF1, RNF5 | `documento_fuente`, `fragmento`, colección `guias_clinicas` |

## 2. Detalle por ítem

Tamaño relativo a las partes del Sprint 2:
- **S:** como F3 (cierre, un cambio acotado).
- **M:** como F2b (rutas con validaciones, permisos, auditoría y pruebas de mutación).
- **L:** como F2b más F2c (backend y pantalla completos), o más.

Las migraciones se numeran en el orden de las partes. El número es tentativo hasta que la parte
empiece.

### M09 reporte exportable y P12 (HU10): L, riesgo medio

- **Rutas:**
  - `POST /api/consultas/{id}/reportes` (secciones, destino y formato): genera el PDF en el
    servidor con ReportLab (decisión 2) y lo devuelve sin guardarlo;
  - `GET /api/consultas/{id}/reportes` (lista de los generados);
  - el nombre de quien registró la decisión en el GET de la consulta (P12).
- **Pantallas:** M09 en `/consultas/:id/reporte`. Se habilitan «Exportar reporte» en M05 y «Ver»
  en M08. «Reportes» del menú pasa a ser la lista de consultas propias con «Exportar» por fila
  (decisión 16, junto con P10).
- **Migración 013:** secuencia del número correlativo (EV-AAAA-NNNNN). La tabla
  `asistencia.reporte` y su GRANT a `cdss_clinica` ya existen.
- **Permisos:** EXPORTAR_REPORTE ya existe (enfermera, médico, nutricionista y coordinador), solo
  sobre consultas propias (regla de la fila 59).
- **Destino «cuidador»:** frases fijas por clasificación y tipo de paso, revisadas por el asesor y
  el personal de salud, sin el modelo de lenguaje (decisión 3).
- **Pruebas:**
  - 403 y 404 con la consulta de otro usuario;
  - evento REPORTE_GENERADO sin datos personales;
  - `hash_documento` igual al SHA-256 del PDF entregado;
  - respuesta con `Cache-Control: no-store`;
  - secciones incluidas y excluidas;
  - el PDF no queda en el servidor;
  - axe y desbordes con la vista previa.
- **Riesgos:**
  - el PDF lleva el nombre y la historia clínica descifrados;
  - ReportLab en un backend con 512 MB de límite: medir la memoria;
  - las frases del cuidador dependen de una revisión clínica.
- **Hecho en la parte C1** (contrato en `docs/contrato_reportes.md`, filas 112 y 113 de
  `cambios_respecto_al_OE2.md`):
  - migración 013: secuencia global con el año de emisión como prefijo, en lugar de un contador por
    año;
  - ruta nueva de vista previa en JSON (`GET .../reportes/vista-previa`) para la pantalla de C2;
  - la respuesta del POST es el PDF con `X-Reporte-Numero` y `X-Reporte-Hash`; solo PDF;
  - ReportLab 5.1.0 trae Pillow 13.0.0, con extensiones en C; fuente DejaVu Sans en
    `backend/app/reportes/fuentes/`;
  - en el reporte del cuidador, los pasos solo se reformulan con la decisión ACEPTA_RECOMENDACION;
  - medido: 1,2 s y unos 20 MB la primera vez en el proceso (carga de la fuente) y de 12 a 26 ms
    después;
  - las frases del cuidador siguen con `revisado: false` hasta la revisión clínica.
- **Hecho en la parte C2** (filas 114 a 117 de `cambios_respecto_al_OE2.md`; HU10 y P11
  resueltos):
  - M09 en `pages/ExportarReporte.tsx`, piezas en `components/reporte/` y llamadas en
    `api/reportes.ts`;
  - vista previa con espera de 350 ms, un solo POST y el PDF solo en memoria (se libera al generar
    otro o al salir); los reportes anteriores se listan sin descarga;
  - «Exportar reporte» en M05 y M07, «Reporte» junto a «Ver» en M08 (decisión: «Ver» se mantiene)
    y «Reportes» como la lista de consultas propias con «Exportar» por fila;
  - pruebas en `pages/ExportarReporte.test.tsx` y reglas de M09 en `src/estilos.test.ts`;
    mutaciones de las obligatorias, el permiso, el único POST, la liberación del blob y el aviso de
    prueba;
  - auditoría con las pantallas `m09_expediente_real`, `m09_expediente_prueba`, `m09_cuidador`,
    `m09_vista_error` y `reportes_lista`: sin desbordes en 10 anchos y sin infracciones de axe;
  - pendiente: la revisión clínica de las frases del cuidador (`revisado: false`).

### M13 auditoría (HU13): L, riesgo bajo

- **Conexión nueva:** `cdss_auditor` en el backend (`DATABASE_URL_AUDITOR` en `config.py`,
  `db.py` y `docker-compose.yml`). La contraseña ya existe en `generar_env.sh` y `aplicar_bd.sh`.
- **Rutas:** `GET /api/auditoria/indicadores`, `GET /api/auditoria/consultas` (paginada, con
  filtros) y `GET /api/auditoria/consultas/{id}`.
- **Pantalla:** M13 en `/admin/auditoria`. Las consultas de prueba se ven marcadas y ocultas por
  defecto (decisión 5).
- **Migración 014:** `v_auditoria_consulta` con `modo_prueba` y la latencia; una vista paginable
  si hace falta.
- **Permisos:** VER_AUDITORIA ya existe (coordinador y administrador).
- **Pruebas:**
  - `cdss_auditor` no puede leer la identidad del paciente, `texto_consulta` ni `observaciones`;
  - los indicadores excluyen las consultas de prueba;
  - el detalle no trae identificadores;
  - paginación con orden explícito en Python (nota de la colación en CLAUDE.md);
  - axe y desbordes.
- **Hecho en la parte D1** (API, sin pantalla; contrato en `docs/contrato_auditoria.md`, filas 118
  a 120 de `cambios_respecto_al_OE2.md`):
  - conexión `cdss_auditor` de solo lectura (`DATABASE_URL_AUDITOR`, transacciones de solo
    lectura), usada solo por las rutas de auditoría;
  - migración 014: `v_auditoria_consulta` con `modo_prueba`, prompt, búsqueda y control previo, y la
    solicitud solo si el control la aprobó; `v_auditoria_lista` nueva y paginable;
    `v_indicadores_operativos` con p50, p90, conteos por estado y tokens, sin pruebas y con 30
    días; 011 y 012 no redefinen esas vistas si ya tienen la forma de 014;
  - el orden de la lista se resuelve en SQL (fecha y hora y, con empate, el uuid, que se compara por
    bytes): no depende de la colación y permite paginar con LIMIT y OFFSET;
  - evento AUDITORIA_CONSULTADA al abrir la lista o un detalle;
  - pruebas en `backend/tests/test_d1_auditoria.py` (permisos del rol en la base, 401, 403 y 200,
    indicadores contra la vista, lista, bordes de Lima, desempate, detalle sin identificadores,
    evento) y mutaciones del filtro de pruebas, el permiso, el desempate, el límite y la exclusión
    de la solicitud;
  - tipos y fixtures para D2 en `frontend/src/api/tipos_auditoria.ts` y
    `frontend/src/__fixtures__/auditoria_*.json`;
  - pendiente para D2: la pantalla M13, axe y desbordes.

### M12 parámetros clínicos (HU14): L, riesgo alto

- **Rutas:**
  - `GET /api/parametros`;
  - `PUT` por grupo, en una transacción que cierra `vigente_hasta` e inserta el valor nuevo;
  - `GET /api/parametros/historial`.
- **Pantalla:** M12 en `/admin/parametros`.
- **Migración 015:** `motivo_cambio` en `umbral_hemoglobina`, `ajuste_altitud` y
  `parametro_sistema`.
- **Permisos** (decisión 4):
  - **Coordinador:** edita los puntos de corte, el ajuste por altitud y la vigencia del tamizaje,
    con motivo obligatorio y su documento de referencia.
  - **Solo lectura para todos:** el riesgo por clasificación (`categoria_anemia` no está
    versionada) y los parámetros de recuperación y del modelo, que se cambian solo por migración
    con medición.
  - **Administrador:** solo lee. Hoy tiene CONFIGURAR_PARAMETROS en el catálogo, así que hay que
    separar lectura y edición (permiso nuevo o regla en el servicio).
- **Pruebas:**
  - rangos `valor_minimo` y `valor_maximo`;
  - sin traslape (restricciones EXCLUDE);
  - dos ediciones a la vez: la segunda recibe 409, con el id vigente como control optimista;
  - la clasificación siguiente usa el valor nuevo (no hay caché: `clasificacion.py` y
    `leer_parametros` leen en cada llamada);
  - evento PARAMETRO_CAMBIADO;
  - el Administrador recibe 403 al editar.
- **Riesgos:**
  - un cambio de punto de corte aplica a la consulta siguiente;
  - los valores `[VERIFICAR]`;
  - el mockup muestra `UMBRAL_RELEVANCIA` 0,60 (el vigente es 0,15).

### HU17 retirar guías: M, riesgo medio (alto en nivel 1)

- **Ruta:** `POST /api/conocimiento/documentos/{id}/retiro`, con motivo. Llena `estado` OBSOLETA,
  `retirado_por`, `fecha_retiro` y `motivo_retiro`, columnas que ya existen.
- **Indexador:** un trabajo RETIRO (ya previsto en el contrato) actualiza los metadatos de
  ChromaDB, sin borrar (`cdss_indexador` no tiene DELETE). La recuperación ya filtra
  `estado = 'VIGENTE'` en PostgreSQL y la caché de BM25 se reconstruye sola porque cambia su huella.
- **Pantalla:** «Retirar» habilitado en M11, con una ventana de motivo y confirmación.
- **Reglas** (decisión 6):
  - **nivel 2:** sin restricción;
  - **nivel 1:** solo sin referencias vigentes (`umbral_hemoglobina` o `ajuste_altitud` con su
    `id_documento`, la RM 429 sobre la NTS, `punteros.yaml`) y escribiendo el código del
    documento para confirmar.
- **Migración:** ninguna prevista.
- **Pruebas:**
  - una guía retirada no se recupera (BM25, vector y comprobación final);
  - las consultas anteriores conservan sus citas;
  - cada guarda bloquea con 409;
  - evento GUIA_RETIRADA;
  - mutación del permiso ADMINISTRAR_GUIAS.

### P10 lista de consultas del usuario y menú «Reportes»: M, riesgo bajo

- **Ruta:** `GET /api/consultas` con las consultas propias, paginadas, con filtros de estado y
  fecha y orden explícito.
- **Pantallas:** `/consultas` («Historial de consultas») deja de ser el buscador de pacientes. La
  misma lista con «Exportar» por fila es «Reportes» (decisión 16; activado en C2).
- **Permisos:** REALIZAR_CONSULTA. Sin migración.
- **Pruebas:** no ve las de otro, filtros, orden estable sin depender de la colación.
- **Hecho en la parte B** (filas 109 a 111 de `cambios_respecto_al_OE2.md`):
  - el buscador de pacientes pasó a `/consultas/nueva` («Nueva consulta»), con sus flujos;
  - P12 (`registrada_por`) se adelantó a esta parte;
  - la lista trae el nombre y la historia clínica del paciente, única excepción a la regla «Sin
    identidad» del contrato;
  - sin migración: con 10 000 consultas de un usuario, la página tarda unos 17 ms con
    `ix_consulta_id_usuario`.

### P13 auditoría visual versionada: S, riesgo bajo (parte A)

`frontend/auditoria/`: desbordes en 10 anchos, elementos absolutos que escapan de su contenedor
con desplazamiento, aviso de áreas táctiles y axe-core. Fuera del CI (decisión 10). Uso en
`frontend/auditoria/README.md`.

### Cambio obligatorio de contraseña e invalidación de sesiones: M, riesgo medio

- **Migración 016:** `debe_cambiar_contrasena` y `fecha_cambio_contrasena` en
  `seguridad.usuario`, con GRANT por columna o mediante la conexión `cdss_admin`.
- **Ruta y pantalla:** «Cambiar mi contraseña», para todos los roles, desde el encabezado.
- **Comportamiento:**
  - con la marca activa, toda ruta responde 403 salvo la del cambio;
  - `usuario_actual` rechaza los tokens con `iat` anterior al último cambio;
  - evento CONTRASENA_CAMBIADA sin la contraseña.
- **Riesgo:** un error deja fuera a todos. Hay que actualizar `seed_demo`, los fixtures y el
  script de la auditoría.

### P14 prioridad de las consultas frente a la indexación: M, riesgo medio

Medir antes de programar. Opciones:
- **base:** horario del trabajador del indexador;
- **ampliación:** lotes de embeddings más chicos o una cola con prioridad en `modelos`.

Sin migración.

### Respaldo: S, riesgo bajo

- **Trabajo:** `python -m app.respaldo` copia ChromaDB y las guías cargadas a una carpeta local y,
  en Azure, a Blob (decisión 14).
- **PostgreSQL:** en Azure tiene respaldo automático y restauración a un punto en el tiempo.
- **Prueba:** restaurar, no solo copiar.

### Despliegue en Azure: L, riesgo alto

- Compose de producción;
- HTTPS en el puerto 443;
- secretos en Key Vault;
- `aplicar_bd.sh` con `\getenv`;
- medición en B2ms;
- solo datos sintéticos (decisión 12).

### Evaluación del OE3: L, riesgo medio

- **Cuándo:** después de congelar el sistema (decisión 13).
- **Métricas:** RAGAS y CUE, con el juez solo sobre datos sintéticos.
- **Conjunto de prueba:** se mide una sola vez.

### Fuera del Sprint 3

- **Carga de nivel 1 con «Aprobar» y recorte por documento** (parte G: L, riesgo alto): después
  del OE3 (decisión 7).
- **P9, seguimiento encadenado** (parte H: M, riesgo medio): fuera del Sprint 3. Si se hace,
  solo el vínculo `id_consulta_origen`, sin pasar la respuesta anterior al modelo (decisión 8).

## 3. Dependencias

- **A (P13)** primero: abarata la verificación de cada parte con interfaz.
- **B (P10 y P12)** antes de C1 y C2: el reporte muestra quién registró la decisión, y «Reportes»
  es la lista de B.
- **D** necesita la conexión `cdss_auditor`, que crea la misma parte.
- **E1** antes de E2. **F** no depende de las anteriores.
- **I, K, J y HTTPS** antes de **L** (Azure).
- **M12 (E1 y E2) y HU17 (F)** antes de congelar el sistema para el **OE3**.

## 4. Partes

Cada parte en su rama desde `main`. El usuario la fusiona con un pull request.

Verificación común a las partes con interfaz:
- suites completas del backend y del frontend;
- `npm run build`;
- `npm run auditoria -- --axe` (desbordes en 10 anchos y axe con las ventanas abiertas y
  cerradas);
- capturas revisadas a ojo;
- pruebas de mutación.

| Orden | Parte | Rama | Entregable | Verificación manual | Criterio de cierre | Versión |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | A | `sprint-3-a-auditoria-visual` | P13 en `frontend/auditoria/`, este plan, correcciones de documentos y filas de las decisiones en `cambios` | Auditoría completa una vez; el caso de M08 de la fila 84 reintroducido con `--css-extra` | Detecta la fila 84 y M08 y M11 pasan limpios | Base |
| 2 | B | `sprint-3-b-consultas-usuario` | P10 y P12 (backend y `/consultas`) | Tres usuarios de `seed_demo`: cada uno ve solo lo suyo | Común, más la mutación del filtro por usuario | Base |
| 3 | C1 | `sprint-3-c1-reporte-api` | Migración 013, rutas, PDF con ReportLab y auditoría | Descargar dos reportes y comprobar número, hash y que no queda copia | Contrato `docs/contrato_reportes.md` y fixtures | Base |
| 4 | C2 | `sprint-3-c2-reporte-ui` | M09, botones en M05 y M08, «Exportar» en «Reportes» | Descargar e imprimir a 320 y 1920 px | Común | Base (el destino «cuidador», ampliación) |
| 5 | D | `sprint-3-d-auditoria` | Conexión `cdss_auditor`, migración 014, rutas y M13 | La solicitud exacta de una consulta de `seed_demo` sin identificadores | Común, más los permisos por columna del auditor y los indicadores iguales a la vista | Base |
| 6 | E1 | `sprint-3-e1-parametros-api` | Migración 015, versionado, permisos y control de concurrencia | Cambiar la vigencia a 15 días y ver M15 en una consulta | Historial correcto; la clasificación usa el valor nuevo; el Administrador recibe 403 al editar | Base |
| 7 | E2 | `sprint-3-e2-parametros-ui` | M12 | Cambiar un valor, «Descartar» y ver el historial | Común, más la mutación de solo lectura | Base |
| 8 | F | `sprint-3-f-retiro-guias` | HU17 con guardas | Retirar una guía de nivel 2 de prueba, solo en la base de pruebas | La retirada no se recupera; las consultas anteriores conservan sus citas; ChromaDB coherente con PostgreSQL | Base |
| 9 | I | `sprint-3-i-contrasena` | Cambio obligatorio e invalidación de sesiones | Crear una cuenta, entrar y cambiar la contraseña | Ninguna ruta pasa con la marca activa; los tokens anteriores se rechazan | Base |
| 10 | K | `sprint-3-k-respaldo` | Trabajo de respaldo y restauración | Restaurar en una ChromaDB vacía | Vectores iguales a los fragmentos de la última versión, con la misma vigencia | Base |
| 11 | J | `sprint-3-j-indexacion-prioridad` | P14 | Medir la recuperación mientras se indexa, en el perfil normal y en B2ms | Objetivo fijado antes de medir | Base: horario del trabajador; ampliación: prioridad en `modelos` |
| 12 | L | `sprint-3-l-despliegue` | Compose de producción, HTTPS, Key Vault y guía de despliegue | Despliegue de prueba con datos sintéticos | `mejoras_despliegue.md` resuelto o aceptado | Base |
| 13 | OE3 | `sprint-3-oe3-evaluacion` | Trabajo de evaluación RAGAS y CUE sobre el sistema congelado | Una corrida completa con datos sintéticos | Resultados reproducibles con la versión etiquetada | Base |
| 14 | Z | `sprint-3-z-cierre` | `docs/cierre_sprint3.md`, README y CLAUDE.md | | Pendientes con dueño y fecha | Base |

Las partes G y H quedan fuera por ahora.

## 5. Despliegue en Azure y evaluación del OE3

### Antes de Azure

- **Secretos:** la conexión de `cdss_auditor` (parte D) suma un secreto a Key Vault.
- **Migraciones:**
  - de la 013 en adelante, idempotentes y replicadas en `01_esquema.sql` y `02_catalogos.sql`;
  - se aplican con `aplicar_bd.sh --solo-migraciones`;
  - las contraseñas, con `\getenv` (`mejoras_despliegue.md`).
- **Lo que debe estar hecho:**
  - el cambio obligatorio de contraseña y la invalidación de sesiones (parte I);
  - P14 (parte J);
  - el respaldo (parte K);
  - HTTPS.
- **Datos de prueba:** `seed_demo` no corre en producción, porque crea usuarios con una
  contraseña conocida.
- **Modo de prueba:** con `CDSS_ENTORNO` distinto de `desarrollo`, el backend no arranca con el
  modelo falso.
- **Guías:** quedan en el volumen de la máquina, con respaldo a Blob (decisión 14).
- **Latencia:** el RNF3 en B2ms es el peor caso medido (p90 de 18,9 s). La redacción propuesta
  (fila 61) sigue pendiente con el asesor.
- **Datos reales:** el despliegue usa solo datos sintéticos. El uso con pacientes reales requiere
  la autorización del asesor y de la institución (decisión 12).

### Antes del OE3

- **Congelar el sistema:**
  - una etiqueta de versión;
  - sin cambios en M12;
  - sin cargar ni retirar guías;
  - el mismo `VERSION_PROMPT`.

  Hoy nada en el código lo impide: se hace por procedimiento, o con un parámetro que bloquee las
  escrituras de M12 y M11 durante la evaluación.
- **Consultas de prueba:** la regla de P2 ya las excluye de las vistas agregadas. M13 las marca.
- **Juez de RAGAS:** si usa un modelo de lenguaje, solo con datos sintéticos (decisión 13).
- **Conjunto de prueba:** ya no es independiente (CLAUDE.md). Además, d1 cambió el puntaje de 12
  fragmentos de la RM 429 después de medirse el 86 % de las 35 consultas de desarrollo: conviene
  volver a medirlas con el sistema congelado.
- **P3, P4, P7 y P8:** no se tocan. Se evalúa como está (decisión 15).

## 6. Versiones del plan

**Base (reducida, lo mínimo defendible):**
- A, B, C1, C2 (solo el destino «expediente»), D, E1, E2, F, I y K;
- J con el horario del trabajador;
- L, OE3 y Z.

**Ampliación, según el tiempo:**

| Ampliación | Si no se hace |
| --- | --- |
| Destino «cuidador» de M09, con frases fijas revisadas (decisión 3) | RF6 queda parcial: solo el reporte para el expediente. Es lo menos defendible del recorte: conviene recuperarlo apenas estén revisadas las frases |
| J completo: prioridad de las consultas en `modelos` o lotes más chicos | El riesgo de P14 sigue, mitigado por el horario, el aviso de M11 y el máximo de 2 trabajos activos |

**Fuera del Sprint 3:**

| Parte | Costo |
| --- | --- |
| G, carga de nivel 1 desde M11 con «Aprobar» y recorte por documento | El nivel 1 se sigue cargando por línea de comandos, con transcripciones verificadas (fila 106). A cambio, protege la base de conocimiento del OE3 |
| H, P9 | Sigue la diferencia con el mockup de M05 y con la transición M05 → M04 del OE2: «Nueva consulta» abre una consulta suelta |

## 7. Desajustes encontrados en la fase 0

- **HU16:** es el aviso de evidencia insuficiente (M07) en el OE2. README, CLAUDE.md y el cierre
  la usaban para el registro de la decisión y la ponían en el Sprint 3. Corregido en la parte A.
- **Título del Sprint 3:** era «Verificación, reportes y administración», pero la verificación
  (RF7) se entregó en el Sprint 2. Corregido en la parte A.
- **Trabajo de evaluación del OE3:** `jobs/README.md` lo marcaba «Sprint 2, parte posterior» y no
  existe. Corregido en la parte A.
- **Cifras del README:** 736 pruebas y migraciones 001 a 011. El cierre decía «filas 1 a 102».
  Corregido en la parte A.
- **P13:** `cambios` decía «Parte F» y el cierre «Sprint 3». Resuelto en la parte A.
- **Conexión `cdss_auditor`:** existe en la base y en `generar_env.sh`, pero no en el backend
  (parte D).
- **Historial de M12:** `categoria_anemia` no está versionada, aunque el OE2 promete historial de
  todo cambio. Queda en solo lectura (decisión 4).
- **Permiso de parámetros:** el Administrador tiene CONFIGURAR_PARAMETROS y el mockup se lo da a
  la coordinadora (decisión 4, parte E1).
- **Nombre del rol:** «Coordinador CRED» en el catálogo y «Coordinadora CRED» en los mockups.
- **Mockups desactualizados:** M12 muestra `UMBRAL_RELEVANCIA` 0,60 (el vigente es 0,15) y M13
  muestra `claude-sonnet-4-5` (el vigente es `claude-sonnet-5-5`).
- **HTTPS:** el OE2 lo exige, y Nginx solo escucha en el puerto 80 (parte L).
- **Datos personales en M09:** el mockup muestra el nombre y la historia clínica del paciente. El
  reporte nunca va al modelo, pero obliga a descifrarlos con `cdss_clinica` y a auditar la
  generación sin esos datos.
- **Tarjetas de M08:** el pedido de la parte B decía «tarjetas apiladas debajo de 800 px, como
  M08», pero M08 es una tabla compacta con desplazamiento interno de respaldo. La lista de la parte
  B es la primera pantalla con tarjetas por debajo de 800 px.
- **Botones de las pantallas clínicas:** miden 42 px de alto por debajo de 800 px. La regla de 44
  px solo se fijó para el menú móvil, M11 y las ventanas (`estilos.test.ts`). Lo detectó la
  auditoría de la parte A; queda como observación, no como pendiente.

## 8. Decisiones

1. HU16 es M07 (entregada); el Sprint 3 cubre HU10, HU13, HU14 y HU17.
2. PDF de M09 en el servidor con ReportLab.
3. Reporte para el cuidador con frases fijas revisadas, sin modelo.
4. M12: solo el Coordinador edita puntos de corte, altitud y vigencia, con motivo obligatorio;
   riesgo por clasificación y parámetros de recuperación en solo lectura; el Administrador solo
   lee.
5. M13 muestra las consultas de prueba marcadas y ocultas por defecto.
6. Retiro de nivel 1 solo sin referencias vigentes y con confirmación escribiendo el código;
   nivel 2 sin restricción.
7. La carga de nivel 1 desde la pantalla (parte G) va después del OE3.
8. P9 fuera del Sprint 3 (si se hace, solo el vínculo).
9. P10: cada profesional ve solo sus consultas.
10. P13 en el repositorio y fuera del CI.
11. El cambio obligatorio de contraseña entra al Sprint 3.
12. Despliegue y OE3 solo con datos sintéticos; el uso con pacientes reales requiere autorización
    del asesor y de la institución.
13. El trabajo de evaluación del OE3 es una parte propia, después de congelar el sistema, con juez
    solo sobre datos sintéticos.
14. Guías en el volumen de la máquina con respaldo a Blob (fila en cambios).
15. No se toca P3, P4, P7 ni P8 antes del OE3; se evalúa como está.
16. «Reportes» pasa a ser la lista de consultas propias con «Exportar» por fila.

Las decisiones 4, 6, 7, 12 y 14 se apartan del OE2 y tienen su fila en
`docs/cambios_respecto_al_OE2.md` (filas 104 a 108).
