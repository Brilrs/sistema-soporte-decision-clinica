# CDSS Anemia Infantil

Sistema de soporte a la decisión clínica para la evaluación del riesgo de anemia infantil en el servicio CRED del Centro de Salud San Luis. Usa IA generativa con arquitectura RAG y desidentifica los datos del paciente antes de enviarlos al modelo de lenguaje.

| Capa | Tecnología |
| --- | --- |
| Interfaz | React + Vite (TypeScript) servida por Nginx |
| API y orquestación | FastAPI + LangGraph (Python 3.12) |
| Datos | PostgreSQL 16 (Azure Database for PostgreSQL en producción) |
| Base vectorial | ChromaDB |
| Modelos locales | bge-m3 (embeddings) y bge-reranker-v2-m3, PyTorch solo CPU, en el contenedor interno `modelos` |
| Modelo de lenguaje | Claude Sonnet 5.5 (`claude-sonnet-5-5`) vía API de Anthropic (Sprint 2) |

## Estado por Sprint

| Sprint | Contenido | Estado |
| --- | --- | --- |
| 0 | Repositorio, Docker Compose, base de datos con catálogos, login y control de acceso por rol | Completado |
| 1 | Gestión de pacientes y tamizajes (HU01, HU02, HU04, HU05, HU11, HU18), pantallas M02, M03, M08, M10 y M14 | Completado |
| 2 | Base de conocimiento y motor RAG (HU03, HU06 a HU09, HU12, HU15) | Pendiente |
| 3 | Verificación, reportes y administración (HU10, HU13, HU14, HU16, HU17) | Pendiente |

## Arranque rápido con Docker

Requisitos: [Docker Desktop](https://www.docker.com/products/docker-desktop/) y Git. En Windows, use la terminal **Git Bash** para los comandos `.sh`.

```bash
# 1. Crear el archivo .env con secretos aleatorios (si ya existe, solo agrega las variables que falten)
./generar_env.sh

# 2. Levantar todo (la primera vez crea la base de datos y sus catálogos)
docker compose up --build -d

# 3. Cargar los usuarios de prueba y los 10 pacientes ficticios
docker compose exec backend python -m app.scripts.seed_demo
```

Abra **http://localhost:8080** e inicie sesión con cualquiera de estas cuentas (contraseña: el valor de `SEED_CONTRASENA` en `.env`, por defecto `Cdss2026!`):

| Usuario | Rol | Qué ve |
| --- | --- | --- |
| `enf.rojas` | Enfermera CRED | Pacientes, consultas y reportes |
| `med.salazar` | Médico | Pacientes, consultas y reportes |
| `nut.vilca` | Nutricionista | Pacientes, consultas y reportes |
| `coord.ortiz` | Coordinador CRED | Consultas, reportes, parámetros y auditoría |
| `admin.cdss` | Administrador | Usuarios, base de conocimiento, parámetros y auditoría |

Estado de los servicios: http://localhost:8080/api/salud. La documentación interactiva de la API está en http://localhost:8000/docs cuando el backend corre en modo desarrollo (abajo).

Para empezar de cero (borra la base de datos y la base vectorial): `docker compose down -v`.

### Modelos locales

El servicio `modelos` necesita los pesos de bge-m3 y bge-reranker-v2-m3 (unos 4,6 GB), fijados a una revisión exacta en `modelos/revisiones.json`. Se descargan una sola vez:

```bash
docker compose run --rm descargar-modelos
```

Quedan en `./data/modelos` (carpeta del equipo, no un volumen de Docker), así que `docker compose down -v` no los borra. En ejecución el servicio los lee en solo lectura y sin conexión a internet.

El reranker corre en ONNX con pesos int8 (`MODELOS_RERANKER=onnx-int8`, valor por defecto). Después de la descarga se exporta y cuantiza una sola vez, desde la misma revisión fijada (unos 10 minutos; el servicio `exportar-onnx` tiene un límite de 6 GB porque carga el modelo fp32 completo):

```bash
docker compose run --rm exportar-onnx
```

El resultado queda en `./data/modelos/onnx/bge-reranker-v2-m3-int8` (0,54 GB) con un `manifiesto.json` que guarda la revisión de origen, las versiones de las librerías (fijadas en `modelos/requirements-ml.txt`) y el SHA-256 del modelo; el servicio no arranca si no coinciden. Con `MODELOS_RERANKER=fp32` usa el modelo original con PyTorch. Al iniciar, `modelos` hace una inferencia de calentamiento de cada modelo y solo entonces responde en `/salud` (y Docker lo marca healthy); `/salud` informa los tiempos de carga y de calentamiento.

### Procesos fuera de línea

El servicio `jobs` (indexador de guías) no arranca con el resto: se ejecuta bajo demanda con `docker compose run --rm jobs python -m app.<módulo>`.

### Indexador y carga de las guías

Copie los 4 PDF a `./data/guias` (ver `data/README.md`) y, con el sistema levantado y los modelos descargados:

```bash
docker compose build jobs
docker compose run --rm jobs python -m app.indexador cargar --manifiesto fuentes_iniciales.yaml --permitir-no-verificadas
docker compose run --rm jobs python -m app.indexador comparar             # informe en data/mediciones/a2_extraccion.md
docker compose run --rm jobs python -m app.indexador verificar-valores    # lista de comprobación de los valores críticos
```

`--permitir-no-verificadas` es solo para desarrollo: las normas MINSA (nivel 1) solo quedan listas para producción cuando todas sus transcripciones están verificadas, y sin esa opción el indexador las rechaza. Volver a cargar el mismo archivo no duplica nada; `--reindexar` crea una versión nueva. Los comandos, las transcripciones y el mapa de modificaciones de la RM 429-2024/MINSA se explican en [`jobs/README.md`](jobs/README.md).

### Procesamiento de la consulta y recuperación

El código está en `backend/app/rag/` (secciones 4.2 y 4.3 de la guía OE2). Cada módulo recibe la sesión de base de datos como parámetro, para que el orquestador use la conexión que corresponde en cada nodo:

| Módulo | Qué hace | Conexión |
| --- | --- | --- |
| `dominio.py` | Filtro de dominio (2.1): reglas contra intentos de cambiar las instrucciones y similitud con 40 consultas de referencia (`dominio_referencia.yaml`) usando `UMBRAL_DOMINIO`, y regla de población fuera del alcance (incluidos los niños de 5 años o más). Resultado `FUERA_DE_DOMINIO` si no corresponde. | ninguna |
| `validacion.py` | Datos mínimos (edad, sexo, altitud, hemoglobina y fecha del tamizaje) y vigencia del tamizaje con `DIAS_VIGENCIA_TAMIZAJE` (30 días se acepta, 31 no, salvo confirmación). Si falta `resultado_clasificacion`, lo calcula con `app/services/clasificacion.py` y lo guarda. Una edad fuera de 0 a 59 meses da `FUERA_DE_ALCANCE`. | `cdss_clinica` |
| `consulta_estructurada.py` | `construir_consulta(contexto)`: consulta de recuperación armada con los datos estructurados del tamizaje (edad, clasificación y nivel de riesgo, altitud, antecedentes y síntomas). La usa el grafo de la parte D. | `cdss_generacion` |
| `normalizacion.py` | Abreviaturas, sinónimos, descriptores MeSH y DeCS y equivalentes en inglés desde `diccionario_normalizacion.yaml`, sin UMLS (CUI vacío). | ninguna |
| `bm25.py` | Índice léxico con los fragmentos recuperables (vigentes, nivel 1, documento VIGENTE, última versión), sin tildes, sin palabras vacías y con raíces en español e inglés. Se reconstruye cuando cambia la huella de la base de conocimiento. | `cdss_generacion` |
| `recuperacion.py` | BM25 y ChromaDB, fusión RRF, comprobación en PostgreSQL, reranker, selección con `UMBRAL_RELEVANCIA` y búsqueda ampliada si no se alcanza. | `cdss_generacion` |
| `parametros.py` | Parámetros vigentes de `parametro_sistema`, incluidos `CANDIDATOS_RERANKER` y `MAX_LONGITUD_RERANKER` (migración 004). Los valores definitivos (8 candidatos, 256 tokens, `UMBRAL_RELEVANCIA` 0,15 y `UMBRAL_DOMINIO` 0,65) se aplican con la migración 005 como versiones nuevas. | la del nodo |

Ningún módulo lee `asistencia.consulta.texto_consulta` ni `clinico.tamizaje.observaciones`: la recuperación usa `texto_filtrado` y datos estructurados. El alcance es el niño de 0 a 59 meses del CRED: las consultas sobre gestantes, puérperas, adolescentes y adultos quedan fuera del dominio. `consultas_validacion.yaml` es un conjunto de validación separado (15 consultas de recuperación y 30 del filtro de dominio) que no se usa para ajustar reglas ni umbrales, y `consultas_prueba.yaml` es el conjunto de prueba final (10 casos clínicos con la consulta de `construir_consulta` y 10 preguntas libres), que se mide una sola vez. La configuración del reranker y las mediciones de latencia están en [`docs/mediciones_sprint2.md`](docs/mediciones_sprint2.md).

### Memoria

Cada servicio tiene un límite (`mem_limit` en `docker-compose.yml`): `modelos` 5,5 GB, `db` y `chromadb` 0,75 GB cada uno, `backend` 0,5 GB, `nginx` 64 MB y `jobs` 0,75 GB. En total, 8,31 GB con el indexador en marcha; Docker necesita al menos 8,5 GB asignados. La exportación única del reranker a ONNX (`exportar-onnx`, bajo demanda) tiene un límite propio de 6 GB.

## Desarrollo sin reconstruir contenedores

Con la base de datos y ChromaDB en Docker (`docker compose up -d db chromadb`):

```bash
# Backend con recarga automática (http://localhost:8000/docs)
cd backend
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
cp .env.test.example .env      # ajuste usuario, contraseña y host 127.0.0.1:5432 con los valores de ../.env
uvicorn app.main:app --reload

# Frontend con recarga automática (http://localhost:5173, /api va al backend)
cd frontend
npm install
npm run dev
```

## Pruebas

```bash
cd backend
cp .env.test.example .env.test   # conexiones a la base de pruebas
python -m app.scripts.seed_demo
pytest -q

# Pruebas lentas: PDF reales de data/guias y fragmentos indexados (no corren en CI)
pytest -q -m lenta
# Las de la recuperación necesitan los modelos reales y corren dentro de la red de Docker (ver jobs/README.md)

# Servicio de modelos, con el motor falso (sin PyTorch ni pesos descargados)
cd modelos
pip install -r requirements-dev.txt
python -m pytest -q
```

Las pruebas cubren: login correcto, mensaje genérico ante usuario o contraseña incorrectos, bloqueo tras 5 intentos fallidos, cuentas inactivas, permisos por rol, registro en la auditoría, separación de privilegios entre componentes, cifrado de la identidad del paciente, bitácora inmutable, unicidad de parámetros vigentes, cálculo de la edad en meses, idempotencia de las migraciones, permisos por columna de los componentes de generación e indexación, `generar_env.sh` y los endpoints del servicio de modelos, y del indexador: limpieza de páginas, tokens sospechosos del OCR, fragmentación 500/800/80, anclas de las modificaciones de la RM 429, transcripciones y valores críticos, consistencia entre PostgreSQL y ChromaDB, idempotencia por SHA-256 y reindexación por versiones, y de la recuperación: filtro de dominio e intentos de saltarse las instrucciones, datos mínimos y vigencia de 30 días, normalización, BM25 por idioma, fusión RRF, exclusión de fragmentos no vigentes, recomprobación en PostgreSQL, búsqueda ampliada y que ningún módulo lea el texto libre sin filtrar. El flujo de GitHub Actions (`.github/workflows/ci.yml`) las ejecuta en cada push.

## Estructura del repositorio

```
backend/        API FastAPI
  app/core/       configuración, conexiones por rol, seguridad, auditoría
  app/api/        rutas (auth, salud, catálogos, pacientes, usuarios) y dependencias de permisos
  app/services/   reglas del negocio (pacientes, clasificación, usuarios)
  app/rag/        filtro de dominio, validación, normalización y recuperación híbrida (Sprint 2)
  app/scripts/    seed_demo (usuarios y pacientes ficticios) y mediciones de la recuperación
  tests/          pruebas automáticas
frontend/       React + Vite; Dockerfile con Nginx (único punto de entrada)
db/
  init/           01 esquema (27 tablas), 02 catálogos, 03 usuarios de conexión, 04 migraciones
  migraciones/    cambios idempotentes para bases existentes (001 a 004: Sprint 2)
  sql/            usuarios de conexión con mínimo privilegio
  aplicar_bd.sh   aplica todo sobre una base nueva, o solo las migraciones (--solo-migraciones)
modelos/        servicio interno de modelos locales (bge-m3 y bge-reranker-v2-m3); experimentos/ mide rerankers alternativos
backend/app/indexador/  indexador de guías: extracción, transcripciones, mapa de modificaciones, fragmentación e indexación
jobs/           documentación de los procesos fuera de línea (indexador, evaluación OE3 y respaldo)
data/           guías en PDF, pesos de los modelos y mediciones (no se versiona, ver data/README.md)
docs/           documentación del desarrollo
```

## Base de datos

- **Esquema:** 27 tablas en 6 esquemas (`seguridad`, `clinico`, `asistencia`, `conocimiento`, `configuracion`, `auditoria`), triggers de integridad y vistas.
- **Usuarios de conexión:** el backend usa un usuario por componente (`cdss_clinica`, `cdss_generacion`, `cdss_admin`, `cdss_auditor`) y el indexador usa `cdss_indexador`. El de generación no puede leer la identidad de los pacientes, el texto original de la consulta ni las observaciones del tamizaje; el indexador solo accede a la base de conocimiento.
- **Identidad del paciente:** nombre, DNI, historia clínica y dirección se cifran con pgcrypto (AES-256) usando `CDSS_CLAVE_PII`. El DNI y la historia clínica se guardan además como HMAC para buscarlos sin descifrar. **Guarde `CDSS_CLAVE_PII`: sin ella no se puede recuperar la identidad.**
- **Catálogos iniciales:** roles y permisos, síntomas, distritos con altitud, puntos de corte de hemoglobina, ajuste por altitud y 21 parámetros del sistema vigentes.
- **Migraciones:** `db/migraciones/` lleva una base existente al estado actual sin perder datos. Son idempotentes: se pueden aplicar varias veces.

```bash
# Base local en Docker (PowerShell; en Git Bash anteponga MSYS_NO_PATHCONV=1 a cada comando)
docker compose up -d db                                                         # recrea el contenedor con los montajes nuevos; el volumen de datos se conserva
docker compose exec db bash /docker-entrypoint-initdb.d/04_migraciones.sh     # aplica las migraciones
docker compose exec db bash /docker-entrypoint-initdb.d/03_usuarios_bd.sh     # crea los usuarios nuevos (cdss_indexador)
```

> Los valores clínicos marcados con `[VERIFICAR]` en `db/init/02_catalogos.sql` (puntos de corte, ajuste por altitud, descriptores MeSH y altitud de distritos) deben contrastarse con el texto oficial de la NTS N.° 213-MINSA/DGIESP-2024 y la guía OMS 2024 antes de la validación con usuarios. Todos se pueden cambiar desde la pantalla de parámetros clínicos (M12).

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

## Seguridad en desarrollo

- `.env` nunca se sube al repositorio (está en `.gitignore`). En Azure, los secretos van en Key Vault.
- Las contraseñas se guardan con Argon2id y los tokens JWT duran 8 horas.
- Todos los inicios de sesión, exitosos o no, quedan en `auditoria.evento_auditoria`, que no admite cambios ni eliminaciones.
- Durante el desarrollo, el modelo de lenguaje solo recibe datos sintéticos.
