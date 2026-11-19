# CDSS Anemia Infantil

Sistema de soporte a la decisión clínica para la evaluación del riesgo de anemia infantil en el servicio CRED del Centro de Salud San Luis. Usa IA generativa con arquitectura RAG (recuperación de evidencia de las guías clínicas y generación con un modelo de lenguaje) y desidentifica los datos del paciente antes de enviarlos al modelo.

| Capa | Tecnología |
| --- | --- |
| Interfaz | React + Vite (TypeScript) servida por Nginx |
| API y orquestación | FastAPI + LangGraph (Python 3.12) |
| Datos | PostgreSQL 16 (Azure Database for PostgreSQL en producción) |
| Base vectorial | ChromaDB 0.6.3 |
| Modelos locales | bge-m3 (embeddings) y bge-reranker-v2-m3 (ONNX int8), solo CPU, en el contenedor interno `modelos` |
| Modelo de lenguaje | Claude Sonnet 5.5 (`claude-sonnet-5-5`) vía API de Anthropic; el ID está en el parámetro `MODELO_LLM` |
| Procesos fuera de línea | Indexador de guías (permanente desde el Sprint 2) y línea de comandos `jobs` |

## Estado por Sprint

| Sprint | Contenido | Estado |
| --- | --- | --- |
| 0 | Repositorio, Docker Compose, base de datos con catálogos, login y control de acceso por rol | Completado |
| 1 | Gestión de pacientes y tamizajes (HU01, HU02, HU04, HU05, HU11, HU18), pantallas M02, M03, M08, M10 y M14 | Completado |
| 2 | Base de conocimiento y motor RAG (HU03, HU06 a HU09, HU12, HU15 y HU16), pantallas M04 a M07, M11 y M15 | Completado (cierre del 17/11/2026, con pendientes) |
| 3 | Reportes, auditoría, parámetros clínicos y retiro de guías (HU10, HU13, HU14 y HU17), con la preparación del despliegue en Azure y de la evaluación del OE3; plan en `docs/plan_sprint3.md` | En curso |

Lo entregado en el Sprint 2, cómo se verificó, las mediciones y los pendientes están en [`docs/cierre_sprint2.md`](docs/cierre_sprint2.md). Las diferencias con el documento de diseño (OE2) se registran en [`docs/cambios_respecto_al_OE2.md`](docs/cambios_respecto_al_OE2.md).

## Arquitectura y servicios

Nginx es el único punto de entrada (puerto 8080): sirve la interfaz y reenvía `/api` al backend. El backend y el indexador usan los modelos locales y ChromaDB por la red interna de Docker; solo el componente de generación llama a la API de Anthropic.

| Servicio | Qué hace | Puerto | Memoria (`mem_limit`) |
| --- | --- | --- | --- |
| `nginx` | Interfaz compilada y proxy de `/api` (sin búfer en las rutas que transmiten la consulta por etapas) | 8080 | 64 MB |
| `backend` | API FastAPI y grafo de la consulta (LangGraph) | interno (8000) | 512 MB |
| `db` | PostgreSQL 16 con el esquema, los catálogos y un usuario de conexión por componente | 5432 | 768 MB |
| `chromadb` | Colección `guias_clinicas` con los vectores de los fragmentos | 8001 | 768 MB |
| `modelos` | bge-m3 y bge-reranker-v2-m3, sin conexión a internet; responde en `/salud` cuando los dos modelos están calientes | interno, sin puerto publicado | 5,5 GB |
| `indexador` | Trabajador permanente: toma los trabajos de indexación pendientes (las guías cargadas desde M11) cada 5 s | sin puerto | 768 MB |

Bajo demanda (perfiles de Docker Compose, no arrancan con el resto):

| Servicio | Perfil | Uso |
| --- | --- | --- |
| `jobs` | `jobs` | Línea de comandos del indexador y otros procesos: `docker compose run --rm jobs python -m app.<módulo>` (768 MB) |
| `descargar-modelos` | `descarga` | Descarga única de los pesos de los modelos (1 GB) |
| `exportar-onnx` | `descarga` | Exportación única del reranker a ONNX int8 (6 GB) |

Con el stack levantado, los límites suman 8,31 GB (más 0,75 GB si se usa `jobs` a la vez); Docker necesita al menos 8,5 GB asignados. Son topes, no reservas: el uso medido está en [`docs/mediciones_sprint2.md`](docs/mediciones_sprint2.md) y [`jobs/README.md`](jobs/README.md).

## Arranque rápido con Docker

Requisitos: [Docker Desktop](https://www.docker.com/products/docker-desktop/) y Git. En Windows, use la terminal **Git Bash** para los comandos `.sh`.

```bash
# 1. Crear el archivo .env con secretos aleatorios (si ya existe, solo agrega las variables que falten)
./generar_env.sh

# 2. Descargar los modelos locales (una sola vez, unos 4,6 GB) y exportar el reranker a ONNX (unos 10 minutos)
docker compose run --rm descargar-modelos
docker compose run --rm exportar-onnx

# 3. Levantar todo (la primera vez crea la base de datos, sus catálogos y los usuarios de conexión)
docker compose up --build -d

# 4. Cargar los usuarios de prueba y los 10 pacientes ficticios
docker compose exec backend python -m app.scripts.seed_demo

# 5. Indexar las 4 guías clínicas (ver «Indexador de guías»)
```

Abra **http://localhost:8080**. Estado de los servicios: http://localhost:8080/api/salud. `docker compose ps` debe mostrar `db`, `backend`, `modelos` e `indexador` como `healthy` (el primer arranque de `modelos` tarda en cargar y calentar los modelos).

Para empezar de cero (borra la base de datos, la base vectorial y las guías cargadas desde M11): `docker compose down -v`. No borra `./data/modelos` ni `./data/guias`.

### Modelos locales

Los pesos de bge-m3 y bge-reranker-v2-m3 están fijados a una revisión exacta en `modelos/revisiones.json` y quedan en `./data/modelos` (carpeta del equipo, no un volumen). El reranker corre en ONNX int8 (`MODELOS_RERANKER=onnx-int8`, valor por defecto); la exportación deja `./data/modelos/onnx/bge-reranker-v2-m3-int8` con un `manifiesto.json` (revisión de origen, versiones de las librerías y SHA-256), y el servicio no arranca si no coinciden. Con `MODELOS_RERANKER=fp32` usa el modelo original con PyTorch.

### Modo de prueba con el modelo de lenguaje falso

Para revisar la interfaz sin costo ni llamadas externas, agregue a `.env` y recree el backend (`docker compose up -d backend`):

```bash
CDSS_LLM=falso                    # cliente falso en lugar de la API de Anthropic
CDSS_LLM_FALSO_MODO=normal        # normal, evidencia_insuficiente o error: el estado que se quiere ver
```

- Solo se acepta con `CDSS_ENTORNO=desarrollo` (el valor de `docker-compose.yml`); en otro entorno el backend no arranca.
- Las consultas generadas así traen `modo_prueba: true`, se reconocen por `intento_generacion.modelo_llm = modelo-falso` y quedan fuera de los indicadores de M02 y de las métricas.
- Con `CDSS_LLM=real` (valor por defecto) se necesita `ANTHROPIC_API_KEY` en `.env`. **Al modelo de lenguaje solo se le envían datos sintéticos** (los pacientes ficticios de `seed_demo`).

## Usuarios, roles y pantallas

Contraseña de todas las cuentas de prueba: el valor de `SEED_CONTRASENA` en `.env`.

| Usuario | Rol | Menú |
| --- | --- | --- |
| `enf.rojas` | Enfermera CRED | Pacientes, Historial de consultas, Reportes |
| `med.salazar` | Médico | Pacientes, Historial de consultas, Reportes |
| `nut.vilca` | Nutricionista | Pacientes, Historial de consultas, Reportes |
| `coord.ortiz` | Coordinador CRED | Pacientes, Historial de consultas, Reportes, Parámetros clínicos, Auditoría |
| `admin.cdss` | Administrador | Usuarios, Base de conocimiento, Parámetros clínicos, Auditoría |

El administrador no tiene acceso a los datos clínicos. El coordinador puede consultar y ver los pacientes, pero no registrarlos.

| Pantalla | Ruta | Permiso | Estado |
| --- | --- | --- | --- |
| M01 Inicio de sesión | `/login` | ninguno | Disponible |
| M02 Panel de pacientes (indicadores del día) | `/pacientes` | registrar paciente o realizar consulta | Disponible |
| M03 Registro del paciente | `/pacientes/nuevo` | REGISTRAR_PACIENTE | Disponible |
| M08 Historial del paciente y evaluaciones realizadas | `/pacientes/:id/historial` | registrar paciente o realizar consulta | Disponible |
| M14 Nuevo tamizaje | `/pacientes/:id/tamizajes/nuevo` | REGISTRAR_PACIENTE | Disponible |
| M04 Consulta clínica, con avance por etapas | `/pacientes/:id/consulta` | REALIZAR_CONSULTA | Disponible |
| M05 Resultado y M07 Evidencia insuficiente | `/consultas/:id` | REALIZAR_CONSULTA | Disponible |
| M06 Datos faltantes y M15 Tamizaje no vigente | ventanas sobre M04 y M05 | REALIZAR_CONSULTA | Disponible |
| Registrar decisión clínica | ventana sobre M05 y M07 | REALIZAR_CONSULTA | Disponible |
| M10 Gestión de usuarios | `/admin/usuarios` | ADMINISTRAR_USUARIOS | Disponible (con la marca «Debe cambiar su contraseña» desde el Sprint 3, parte I) |
| Cambiar mi contraseña | `/cambiar-contrasena` (desde el encabezado) | cualquier rol | Disponible (Sprint 3, parte I; obligatoria para las cuentas nuevas y las restablecidas: `docs/contrato_autenticacion.md`) |
| M11 Base de conocimiento | `/admin/conocimiento` | ADMINISTRAR_GUIAS | Disponible (con «Retirar» desde el Sprint 3, parte F: `docs/contrato_conocimiento.md`) |
| M09 Reporte exportable | `/consultas/:id/reporte` y la lista `/reportes` | EXPORTAR_REPORTE | Disponible (Sprint 3, parte C2) |
| M12 Parámetros clínicos | `/admin/parametros` | VER_PARAMETROS (editar: CONFIGURAR_PARAMETROS, solo el Coordinador CRED) | Disponible (Sprint 3, partes E1a, E1b y E2; `docs/contrato_parametros.md`) |
| M13 Auditoría y trazabilidad | `/admin/auditoria` y el detalle `/admin/auditoria/:id` | VER_AUDITORIA | Disponible (Sprint 3, partes D1 y D2; `docs/contrato_auditoria.md`) |

Quien no tiene el permiso de una pantalla vuelve al inicio. Los contratos de la API están en [`docs/contrato_consultas.md`](docs/contrato_consultas.md) (consultas), [`docs/contrato_conocimiento.md`](docs/contrato_conocimiento.md) (M11) y [`docs/contrato_autenticacion.md`](docs/contrato_autenticacion.md) (inicio de sesión y cambio de contraseña).

## Indexador de guías y M11

Copie los 4 PDF a `./data/guias` (ver `data/README.md`) y, con el sistema levantado y los modelos descargados:

```bash
docker compose build jobs
docker compose run --rm jobs python -m app.indexador cargar --manifiesto fuentes_iniciales.yaml --permitir-no-verificadas
docker compose run --rm jobs python -m app.indexador comparar             # informe en data/mediciones/a2_extraccion.md
docker compose run --rm jobs python -m app.indexador verificar-valores    # lista de comprobación de los valores críticos
```

- `--permitir-no-verificadas` es solo para desarrollo: sin esa opción, un documento de nivel 1 con transcripciones sin verificar queda en ERROR.
- Volver a cargar el mismo archivo no duplica nada; `--reindexar` crea una versión de indexación nueva. `cdss_indexador` no tiene permiso de eliminación.
- Las transcripciones de las tablas críticas van dentro de la imagen: después de editarlas, `docker compose build jobs` antes de indexar.
- Estado actual: 4 guías de nivel 1 (NTS 213, RM 429, OMS 2024 y OMS 2016), versión 5, 202 fragmentos de la última versión y 183 vigentes. ChromaDB guarda los 202 vectores con su vigencia; la recuperación usa solo los vigentes.

**M11 (Base de conocimiento, `admin.cdss`):** lista las guías con su nivel, versión, fragmentos vigentes, citas de los últimos 30 días y estado; «Cargar guía» sube un PDF de **nivel 2** (metodológico: no se recupera ni se cita) y crea un trabajo que el servicio `indexador` procesa solo; la tarjeta de avance muestra las cinco etapas y se actualiza cada 3 s. Las guías de nivel 1 se cargan solo por línea de comandos, con transcripciones verificadas. Hay como máximo 2 trabajos activos a la vez.

> **Indexar retrasa las consultas** (pendiente P14): mientras se indexa, la recuperación de una consulta pasa de unos 4 s a unos 24 s. Cargue guías fuera del horario de atención.

Comandos, transcripciones, el mapa de modificaciones de la RM 429-2024/MINSA y la medición del indexador: [`jobs/README.md`](jobs/README.md).

## Cómo funciona una consulta

El grafo de LangGraph (`backend/app/rag/grafo.py`) recorre 8 nodos y transmite su avance por etapas (NDJSON) hasta M04:

1. **Validar** (con `cdss_clinica`): filtro de dominio, datos mínimos del tamizaje y vigencia de 30 días.
2. **Clasificar:** clasificación de la hemoglobina ajustada por altitud y nivel de riesgo.
3. **Normalizar:** abreviaturas, sinónimos y descriptores MeSH y DeCS, desde un diccionario local.
4. **Recuperar** (con `cdss_generacion`): BM25 y ChromaDB, fusión RRF, bonificación por edad, reranker y umbral de relevancia; búsqueda ampliada si nada lo alcanza.
5. **Proteger:** solicitud mínima con lista blanca, marcas en lugar de identificadores y control previo que bloquea el envío si aparece un dato del paciente.
6. **Generar:** llamada al modelo con salida estructurada y el prompt versionado (`VERSION_PROMPT` v1.1).
7. **Verificar:** citas, dosis, clasificación y umbral; un reintento si la respuesta no es válida.
8. **Salida:** resultado guardado y eventos de auditoría.

El texto original de la consulta y las huellas del paciente solo viven en memoria. `cdss_generacion` no puede leer la identidad del paciente, el texto original ni las observaciones del tamizaje. El detalle por módulo está en `CLAUDE.md` (notas de trabajo) y en el código de `backend/app/rag/`.

## Desarrollo sin reconstruir contenedores

Con la base de datos y ChromaDB en Docker (`docker compose up -d db chromadb`):

```bash
# Backend con recarga automática (http://localhost:8000/docs)
cd backend
python -m venv .venv && source .venv/Scripts/activate   # Linux o macOS: .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.test.example .env      # ajuste usuario, contraseña y host 127.0.0.1:5432 con los valores de ../.env
uvicorn app.main:app --reload

# Frontend con recarga automática (http://localhost:5173, /api va al backend)
cd frontend
npm ci
npm run dev
```

## Pruebas

**Backend** (necesita una base PostgreSQL de pruebas aparte, con el esquema aplicado por `db/aplicar_bd.sh`; en el equipo de desarrollo es el contenedor `cdss-pruebas-bd`, puerto 5433, que se arranca con `docker start cdss-pruebas-bd`):

```bash
cd backend
cp .env.test.example .env.test   # conexiones a la base de pruebas (incluidas TEST_DATABASE_URL_SUPER, DATABASE_URL_INDEXADOR y DATABASE_URL_AUDITOR)
python -m app.scripts.seed_demo
pytest -q                        # 772 pruebas; excluye las marcas lenta y api_real
pytest -q -m lenta               # PDF reales de data/guias y fragmentos indexados (no corren en CI)
```

Las pruebas de la recuperación con los modelos reales corren dentro de la red de Docker (ver [`jobs/README.md`](jobs/README.md)). Ninguna prueba automática llama a la API de Anthropic (marca `api_real`, nunca en CI).

**Servicio de modelos** (motor falso, sin PyTorch ni pesos):

```bash
cd modelos && pip install -r requirements-dev.txt && python -m pytest -q
```

**Frontend** (Vitest 4 con jsdom, sin backend: fetch simulado):

```bash
cd frontend
npm ci
npm test                 # 252 pruebas (vitest run)
npm run build            # también comprueba los tipos de las pruebas
```

- Los fixtures del contrato de consultas (`frontend/src/__fixtures__`) los genera `backend/tests/test_e0_fixtures.py`; si el contrato cambia, se regeneran con `pytest tests/test_e0_fixtures.py` y luego se corre `npm test`.
- `src/estilos.test.ts` comprueba reglas de la hoja de estilos contra desbordes horizontales, áreas táctiles de 44 px y contraste AA de las etiquetas.
- Para cambiar dependencias del frontend use `npx -y npm@11.21.1 install` (npm 10.9.2 falla al resolver Vitest 4); `npm ci` funciona con npm 10.

GitHub Actions (`.github/workflows/ci.yml`) ejecuta el backend, el servicio de modelos y el frontend en cada push, con una base `postgres:16` (Debian).

## Estructura del repositorio

```
backend/        API FastAPI
  app/core/       configuración, conexiones por rol, seguridad, auditoría, cliente de modelos y almacén vectorial
  app/api/        rutas (auth, salud, catálogos, pacientes, usuarios, consultas, conocimiento) y permisos
  app/services/   reglas del negocio (pacientes, clasificación, usuarios, consultas, decisiones, conocimiento)
  app/rag/        filtro de dominio, validación, normalización, recuperación híbrida, protección de datos,
                  generación, verificación y grafo de la consulta
  app/indexador/  indexador de guías: extracción, transcripciones, mapa de modificaciones, fragmentación,
                  grupos etarios, indexación y trabajador
  app/scripts/    seed_demo, mediciones, confirmación de la API y prueba de punta a punta
  tests/          pruebas automáticas
frontend/       React + Vite; Dockerfile con Nginx (único punto de entrada)
db/
  init/           01 esquema (27 tablas), 02 catálogos, 03 usuarios de conexión, 04 migraciones
  migraciones/    cambios idempotentes para bases existentes (001 a 012: Sprint 2)
  sql/            usuarios de conexión con mínimo privilegio
  aplicar_bd.sh   aplica todo sobre una base nueva, o solo las migraciones (--solo-migraciones)
modelos/        servicio interno de modelos locales; experimentos/ mide rerankers alternativos
jobs/           documentación de los procesos fuera de línea
data/           guías en PDF, pesos de los modelos, mediciones y respaldos (no se versiona, ver data/README.md)
docs/           documentación del desarrollo (contratos, mediciones, cambios respecto al OE2, cierre del Sprint 2)
```

## Base de datos

- **Esquema:** 27 tablas en 6 esquemas (`seguridad`, `clinico`, `asistencia`, `conocimiento`, `configuracion`, `auditoria`), triggers de integridad y vistas.
- **Usuarios de conexión:** un usuario por componente (`cdss_clinica`, `cdss_generacion`, `cdss_admin`, `cdss_auditor` y `cdss_indexador`). El de generación no puede leer la identidad de los pacientes, el texto original de la consulta ni las observaciones del tamizaje; el indexador y el administrador no acceden a los datos clínicos. El auditor solo lee las vistas de auditoría (sin identidad, texto original, observaciones ni la nota de la decisión) y su conexión es de solo lectura.
- **Identidad del paciente:** nombre, DNI, historia clínica y dirección se cifran con pgcrypto (AES-256) usando `CDSS_CLAVE_PII`. El DNI y la historia clínica se guardan además como HMAC para buscarlos sin descifrar. **Guarde `CDSS_CLAVE_PII`: sin ella no se puede recuperar la identidad.**
- **Auditoría:** `auditoria.evento_auditoria` no admite cambios ni eliminaciones.
- **Catálogos iniciales:** roles y permisos, síntomas, distritos con altitud, puntos de corte de hemoglobina, ajuste por altitud y parámetros del sistema versionados.
- **Migraciones:** `db/migraciones/` lleva una base existente al estado actual sin perder datos. Son idempotentes y se replican en `01_esquema.sql` y `02_catalogos.sql`.

```bash
# Base local en Docker (PowerShell; en Git Bash anteponga MSYS_NO_PATHCONV=1 a cada comando)
docker compose up -d db
docker compose exec db bash /docker-entrypoint-initdb.d/04_migraciones.sh     # aplica las migraciones
docker compose exec db bash /docker-entrypoint-initdb.d/03_usuarios_bd.sh     # crea los usuarios nuevos
```

> Los valores clínicos marcados con `[VERIFICAR]` en `db/init/02_catalogos.sql` (puntos de corte, ajuste por altitud, descriptores MeSH y altitud de distritos) deben contrastarse con el texto oficial de la NTS N.° 213-MINSA/DGIESP-2024 y la guía OMS 2024 antes de la validación con usuarios.

### En Azure Database for PostgreSQL - Servidor flexible

1. En el servidor, parámetro `azure.extensions`: agregue `PGCRYPTO` y `BTREE_GIST`.
2. Cree la base `cdss` y ejecute:

```bash
export PGHOST=<servidor>.postgres.database.azure.com PGUSER=<admin> PGPASSWORD=<...> PGDATABASE=cdss PGSSLMODE=require
export CDSS_DB_PWD_CLINICA=<...> CDSS_DB_PWD_GENERACION=<...> CDSS_DB_PWD_ADMIN=<...> CDSS_DB_PWD_AUDITOR=<...>
export CDSS_DB_PWD_INDEXADOR=<...>
./db/aplicar_bd.sh                       # base nueva
./db/aplicar_bd.sh --solo-migraciones    # base existente: aplica las migraciones y crea los usuarios nuevos
```

Las mejoras pendientes para el despliegue en Azure están en [`docs/mejoras_despliegue.md`](docs/mejoras_despliegue.md).

## Sprint 3

El plan, con sus partes, dependencias y decisiones, está en [`docs/plan_sprint3.md`](docs/plan_sprint3.md). En resumen:

- **M09** reporte exportable (HU10, incluido «Exportar reporte» en M05), **M13** auditoría y trazabilidad (HU13) y **M12** parámetros clínicos (HU14).
- **HU17:** retirar guías desde M11 (hecho en la parte F). La carga de guías de nivel 1 desde la pantalla, con revisión («Aprobar») y recorte de márgenes por documento, queda para después de la evaluación del OE3.
- Lista de las consultas propias (P10), cambio obligatorio de contraseña e invalidación de sesiones (hecho en la parte I), prioridad de las consultas frente a la indexación (P14), respaldo y despliegue en Azure.
- Trabajo de evaluación del OE3, con el sistema congelado y solo datos sintéticos. P3, P4, P7 y P8 no se tocan antes del OE3.

La auditoría visual de la interfaz (desbordes, elementos que escapan de su contenedor y axe-core) está en [`frontend/auditoria/`](frontend/auditoria/README.md) y se ejecuta con `npm run auditoria`, fuera del CI. Los pendientes del Sprint 2, con su dueño, están en [`docs/cierre_sprint2.md`](docs/cierre_sprint2.md).

## Seguridad en desarrollo

- `.env` nunca se sube al repositorio (está en `.gitignore`); solo `.env.example`. En Azure, los secretos van en Key Vault.
- Las contraseñas se guardan con Argon2id y los tokens JWT duran 8 horas.
- Las cuentas nuevas y las de contraseña restablecida deben cambiarla al ingresar; cambiar o restablecer la contraseña y reactivar la cuenta invalidan las sesiones anteriores (contador `version_sesion`). Las cuentas de `seed_demo` no tienen esa marca, salvo con `CDSS_SEED_EXIGIR_CAMBIO=true` (para el despliegue).
- Todos los inicios de sesión, exitosos o no, quedan en `auditoria.evento_auditoria`.
- Durante el desarrollo, el modelo de lenguaje solo recibe datos sintéticos.
