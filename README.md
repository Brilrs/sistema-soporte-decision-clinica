# CDSS Anemia Infantil

Sistema de soporte a la decisión clínica para la evaluación del riesgo de anemia infantil en el servicio CRED del Centro de Salud San Luis. Usa IA generativa con arquitectura RAG y desidentifica los datos del paciente antes de enviarlos al modelo de lenguaje.

| Capa | Tecnología |
| --- | --- |
| Interfaz | React + Vite (TypeScript) servida por Nginx |
| API y orquestación | FastAPI + LangGraph (Python 3.12) |
| Datos | PostgreSQL 16 (Azure Database for PostgreSQL en producción) |
| Base vectorial | ChromaDB |
| Modelo de lenguaje | Claude Sonnet 4.5 vía API de Anthropic (Sprint 2) |

## Estado por Sprint

| Sprint | Contenido | Estado |
| --- | --- | --- |
| 0 | Repositorio, Docker Compose, base de datos con catálogos, login y control de acceso por rol | Completado |
| 1 | Gestión de pacientes y tamizajes (HU01, HU02, HU04, HU05, HU11, HU18), pantallas M02, M03, M08, M10 y M14 | Pendiente |
| 2 | Base de conocimiento y motor RAG (HU03, HU06 a HU09, HU12, HU15) | Pendiente |
| 3 | Verificación, reportes y administración (HU10, HU13, HU14, HU16, HU17) | Pendiente |

## Arranque rápido con Docker

Requisitos: [Docker Desktop](https://www.docker.com/products/docker-desktop/) y Git. En Windows, use la terminal **Git Bash** para los comandos `.sh`.

```bash
# 1. Crear el archivo .env con secretos aleatorios
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
```

Las pruebas cubren: login correcto, mensaje genérico ante usuario o contraseña incorrectos, bloqueo tras 5 intentos fallidos, cuentas inactivas, permisos por rol, registro en la auditoría, separación de privilegios entre componentes, cifrado de la identidad del paciente, bitácora inmutable, unicidad de parámetros vigentes y cálculo de la edad en meses. El flujo de GitHub Actions (`.github/workflows/ci.yml`) las ejecuta en cada push.

## Estructura del repositorio

```
backend/        API FastAPI
  app/core/       configuración, conexiones por rol, seguridad, auditoría
  app/api/        rutas (auth, salud) y dependencias de permisos
  app/scripts/    seed_demo (usuarios y pacientes ficticios)
  tests/          pruebas automáticas
frontend/       React + Vite; Dockerfile con Nginx (único punto de entrada)
db/
  init/           01 esquema (26 tablas), 02 catálogos, 03 usuarios de conexión
  sql/            usuarios de conexión con mínimo privilegio
  aplicar_bd.sh   aplica todo sobre una base existente (Azure)
jobs/           indexador, evaluación OE3 y respaldo (Sprint 2)
docs/           documentación del desarrollo
```

## Base de datos

- **Esquema:** 26 tablas en 6 esquemas (`seguridad`, `clinico`, `asistencia`, `conocimiento`, `configuracion`, `auditoria`), triggers de integridad y vistas.
- **Usuarios de conexión:** el backend usa un usuario por componente (`cdss_clinica`, `cdss_generacion`, `cdss_admin`, `cdss_auditor`). El de generación no puede leer la identidad de los pacientes.
- **Identidad del paciente:** nombre, DNI, historia clínica y dirección se cifran con pgcrypto (AES-256) usando `CDSS_CLAVE_PII`. El DNI y la historia clínica se guardan además como HMAC para buscarlos sin descifrar. **Guarde `CDSS_CLAVE_PII`: sin ella no se puede recuperar la identidad.**
- **Catálogos iniciales:** roles y permisos, síntomas, distritos con altitud, puntos de corte de hemoglobina, ajuste por altitud y 17 parámetros del sistema.

> Los valores clínicos marcados con `[VERIFICAR]` en `db/init/02_catalogos.sql` (puntos de corte, ajuste por altitud, descriptores MeSH y altitud de distritos) deben contrastarse con el texto oficial de la NTS N.° 213-MINSA/DGIESP-2024 y la guía OMS 2024 antes de la validación con usuarios. Todos se pueden cambiar desde la pantalla de parámetros clínicos (M12).

### En Azure Database for PostgreSQL - Servidor flexible

1. En el servidor, parámetro `azure.extensions`: agregue `PGCRYPTO` y `BTREE_GIST`.
2. Cree la base `cdss` y ejecute:

```bash
export PGHOST=<servidor>.postgres.database.azure.com PGUSER=<admin> PGPASSWORD=<...> PGDATABASE=cdss PGSSLMODE=require
export CDSS_DB_PWD_CLINICA=<...> CDSS_DB_PWD_GENERACION=<...> CDSS_DB_PWD_ADMIN=<...> CDSS_DB_PWD_AUDITOR=<...>
./db/aplicar_bd.sh
```

## Seguridad en desarrollo

- `.env` nunca se sube al repositorio (está en `.gitignore`). En Azure, los secretos van en Key Vault.
- Las contraseñas se guardan con Argon2id y los tokens JWT duran 8 horas.
- Todos los inicios de sesión, exitosos o no, quedan en `auditoria.evento_auditoria`, que no admite cambios ni eliminaciones.
- Durante el desarrollo, el modelo de lenguaje solo recibe datos sintéticos.
