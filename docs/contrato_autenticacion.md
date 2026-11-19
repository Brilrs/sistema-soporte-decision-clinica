# Contrato de la autenticación (M01, HU01; cambio de contraseña, Sprint 3 parte I)

Inicio de sesión, sesión actual y cambio de la propia contraseña, con la marca de cambio obligatorio
y el contador de sesiones. OpenAPI lo refleja en `/docs` y `/openapi.json`. Código:
`backend/app/api/routes/auth.py`, `backend/app/api/deps.py` (dependencias comunes),
`backend/app/core/seguridad.py` (hash, política y token) y `backend/app/core/errores.py`
(`ErrorConCodigo`); esquema en la migración 018. Frontend: `frontend/src/api/auth.ts`,
`frontend/src/api/cliente.ts` (cierre de sesión), `frontend/src/auth/AuthContext.tsx` y
`frontend/src/pages/CambiarContrasena.tsx`. La gestión de cuentas (M10) está en
`backend/app/api/routes/usuarios.py`; aquí solo se describe lo que cambia en ella.

## Reglas comunes

- **Token:** JWT HS256 firmado con `JWT_SECRETO`, vigente `JWT_MINUTOS` (480 por omisión). Campos:
  `sub` (id del usuario), `rol`, `sv` (versión de sesión), `iat` y `exp`. Se envía como
  `Authorization: Bearer <token>`.
- **Conexión:** todo lo de este contrato usa `cdss_clinica`, que sobre `seguridad.usuario` tiene SELECT
  y UPDATE solo de `intentos_fallidos`, `ultimo_acceso`, `hash_contrasena`, `debe_cambiar_contrasena`,
  `version_sesion` y `fecha_cambio_contrasena` (no puede cambiar nombre, correo, rol ni estado).
- **Cada petición relee la cuenta:** desactivarla o cambiar su rol tiene efecto inmediato.
- **Errores con código:** algunos errores responden `{"detail": "<texto>", "codigo": "<CÓDIGO>"}` (y a
  veces `"campo"`), con el mismo código en la cabecera `X-Codigo-Error`, para que la interfaz lo lea
  sin consumir el cuerpo. Los 403 por permiso y los 422 de validación conservan su formato anterior.
- **Política de contraseñas:** al menos `CONTRASENA_LONGITUD_MINIMA` caracteres (10 por omisión), con
  al menos una letra y un número (cualquier alfabeto). El inicio de sesión y `/me` devuelven el valor
  vigente en `contrasena_longitud_minima`.

## Versión de sesión (`version_sesion`)

En lugar de comparar fechas (`iat` frente a `fecha_cambio_contrasena`), cada cuenta tiene un contador
y el token lleva su valor en `sv`. Un token solo vale si `sv` es exactamente el entero de la cuenta.

| Acción | Sube el contador | Efecto |
| --- | --- | --- |
| El usuario cambia su contraseña | Sí | Sus sesiones anteriores (todos los equipos) dejan de valer; la respuesta trae un token nuevo |
| El administrador restablece la contraseña (M10) | Sí | Las sesiones abiertas del usuario dejan de valer |
| El administrador reactiva la cuenta (M10) | Sí | Los tokens emitidos antes de desactivarla no vuelven a valer |
| El administrador desactiva la cuenta | No hace falta | Cada petición relee la cuenta: el token deja de valer de inmediato |

- Un token emitido antes de la migración 018 no tiene `sv`: cuenta como 0, que es el valor de las
  cuentas existentes. Así las sesiones abiertas al aplicar la migración siguen funcionando.
- `sv` con otro tipo (texto, decimal, booleano o nulo) no vale.
- Un token rechazado por la versión responde **401** con
  `{"detail": "Sesión no válida o expirada", "codigo": "SESION_REVOCADA"}`. Los demás 401 de sesión
  (sin token, firma o vencimiento inválidos, cuenta inexistente o inactiva) usan
  `"codigo": "SESION_NO_VALIDA"` con el mismo texto. La interfaz cierra la sesión en los dos casos;
  con SESION_REVOCADA el login muestra «Su sesión terminó porque la contraseña cambió. Ingrese de
  nuevo.».

## Marca de cambio obligatorio (`debe_cambiar_contrasena`)

- **Quién la pone:** crear una cuenta y restablecer su contraseña (M10). Las cuentas existentes al
  aplicar la migración 018 y las de `seed_demo` quedan en falso. Con `CDSS_SEED_EXIGIR_CAMBIO=true`
  (pensada para el despliegue; apagada por omisión, `docker-compose.yml` la pasa como `false`),
  `seed_demo` crea sus cuentas con la marca y la pone a las que ya existen; nunca la quita.
- **Quién la quita:** solo el cambio de contraseña del propio usuario.
- **Mientras está activa**, todas las rutas responden **403** con
  `{"detail": "Debe cambiar su contraseña antes de continuar.", "codigo": "CAMBIO_CONTRASENA_OBLIGATORIO"}`,
  salvo:
  - `POST /api/auth/login` y `GET /api/salud` (sin sesión);
  - `GET /api/auth/me` y `POST /api/auth/cambiar-contrasena`.
- **Implementación:** la dependencia común `usuario_actual` aplica el bloqueo; solo las dos rutas de
  la lista usan `usuario_actual_sin_bloqueo`. Una ruta nueva queda protegida por omisión, y
  `tests/test_i_contrasena.py` recorre todas las rutas de la aplicación y falla si aparece una sin el
  bloqueo.
- La interfaz, con la marca activa, solo muestra «Cambiar mi contraseña» (sin menú ni «Cancelar»; el
  encabezado deja «Cerrar sesión») y redirige ahí cualquier otra dirección. Si otra llamada recibe el
  403 con ese código, la interfaz pone la marca y lleva a la misma pantalla.

## `POST /api/auth/login`

Cuerpo: `{"usuario": "enf.rojas", "contrasena": "..."}` (1 a 50 y 1 a 200 caracteres).

| Estado | Cuándo |
| --- | --- |
| 200 | Credenciales correctas, también con la marca activa |
| 401 | Usuario inexistente o contraseña incorrecta: `{"detail": "Usuario o contraseña incorrectos"}` (cuenta el intento) |
| 403 | Cuenta desactivada |
| 423 | Cuenta bloqueada (`intentos_fallidos` llegó a `MAX_INTENTOS_FALLIDOS`, 5 por omisión) |

Respuesta 200:

```json
{
  "token": "eyJ...",
  "tipo": "bearer",
  "expira_en_segundos": 28800,
  "usuario": {
    "id_usuario": "6f1c...",
    "nombre_usuario": "prueba.clave",
    "nombre_completo": "Lic. Cuenta de Prueba",
    "rol": "Enfermera CRED",
    "permisos": ["EXPORTAR_REPORTE", "REALIZAR_CONSULTA", "REGISTRAR_PACIENTE"],
    "debe_cambiar_contrasena": true,
    "contrasena_longitud_minima": 10
  }
}
```

## `GET /api/auth/me`

Devuelve el objeto `usuario` de la respuesta anterior. Responde aunque la marca esté activa.

## `POST /api/auth/cambiar-contrasena`

Cualquier rol autenticado, con la marca activa o no. Cuerpo (los dos de 1 a 200 caracteres):

```json
{"contrasena_actual": "...", "contrasena_nueva": "..."}
```

Orden de las comprobaciones (la fila de la cuenta queda bloqueada con `FOR UPDATE` durante la
transacción):

1. Token válido y de la versión vigente (si no, 401 SESION_NO_VALIDA o SESION_REVOCADA). Si otro
   cambio terminó mientras esta solicitud esperaba la fila, también 401 SESION_REVOCADA.
2. Cuenta bloqueada por intentos: **423** `CUENTA_BLOQUEADA` (evento CAMBIO_CONTRASENA_FALLIDO con
   `motivo: cuenta_bloqueada`).
3. Contraseña actual incorrecta: **401**
   `{"detail": "La contraseña actual no es correcta.", "codigo": "CONTRASENA_ACTUAL_INCORRECTA", "campo": "contrasena_actual"}`.
   Cuenta como intento fallido (el mismo contador y el mismo máximo del inicio de sesión), con el
   evento CAMBIO_CONTRASENA_FALLIDO (`motivo: contrasena_actual_incorrecta` e `intento`). Al llegar al
   máximo, el siguiente intento (de cambio o de inicio de sesión) responde 423 y solo el
   administrador la desbloquea (desbloquear o restablecer). La interfaz no cierra la sesión con este
   401: lo muestra junto al campo.
4. La nueva no cumple la política: **422**
   `{"detail": "La nueva contraseña no cumple la política: mínimo 10 caracteres, con al menos una letra y un número.", "codigo": "POLITICA_CONTRASENA", "campo": "contrasena_nueva"}`.
5. La nueva es igual a la actual: **422**
   `{"detail": "La nueva contraseña debe ser distinta de la actual.", "codigo": "CONTRASENA_IGUAL", "campo": "contrasena_nueva"}`.
6. Un campo falta o supera 200 caracteres: 422 con el formato de validación del proyecto
   (`detail` y `errores`).

Los casos 4 a 6 no cambian nada (ni el contador de intentos).

Si todo es correcto, en una transacción: guarda el hash Argon2id nuevo, pone
`debe_cambiar_contrasena` en falso, sube `version_sesion`, fija `fecha_cambio_contrasena = now()` y
deja `intentos_fallidos` en 0; registra CONTRASENA_CAMBIADA con `{"obligatorio": true|false}` (sin
contraseñas ni hash). Responde **200** con la misma forma del inicio de sesión: un token nuevo (con el
`sv` nuevo) y el usuario sin la marca, con `Cache-Control: no-store`. Todas las sesiones anteriores del
usuario quedan inválidas, incluida la que hizo el cambio; la interfaz guarda el token nuevo y sigue.

## Cambios en M10 (`/api/usuarios`)

- La salida de cada cuenta suma `debe_cambiar_contrasena` (booleano). Nunca incluye el hash ni
  `version_sesion`.
- `POST /api/usuarios` crea la cuenta con la marca.
- `POST /api/usuarios/{id}/restablecer-contrasena` pone la marca, sube `version_sesion` y sigue
  desbloqueando la cuenta (`intentos_fallidos = 0`).
- `POST /api/usuarios/{id}/reactivar` sube `version_sesion`.
- La interfaz muestra la etiqueta «Debe cambiar su contraseña» (con texto) en la lista y en el panel,
  y el aviso de la contraseña temporal dice que el usuario deberá cambiarla al ingresar.

## Eventos de auditoría

| Evento | Quién | Detalle |
| --- | --- | --- |
| CONTRASENA_CAMBIADA | El propio usuario | `{"obligatorio": true}` o `false` |
| CAMBIO_CONTRASENA_FALLIDO | El propio usuario | `{"motivo": "contrasena_actual_incorrecta", "intento": n}` o `{"motivo": "cuenta_bloqueada"}` |
| CONTRASENA_RESTABLECIDA | El administrador (M10) | Sin cambios: nombre de usuario y si estaba bloqueada |

Ninguno guarda contraseñas ni hashes.

## Permisos en la base (migración 018)

| Rol | Sobre `seguridad.usuario` |
| --- | --- |
| `rol_app_clinica` | SELECT de la tabla; UPDATE solo de `intentos_fallidos`, `ultimo_acceso`, `hash_contrasena`, `debe_cambiar_contrasena`, `version_sesion` y `fecha_cambio_contrasena` |
| `rol_app_admin` | SELECT, INSERT y UPDATE de la tabla (sin cambios: las columnas nuevas quedan incluidas) |
| `rol_auditor`, `rol_app_generacion`, `rol_app_indexador` | Ninguno (no ven el hash, la marca ni la versión) |

Antes de la migración 018, `rol_app_clinica` tenía UPDATE solo de `intentos_fallidos` y
`ultimo_acceso`. La restricción `ck_usuario_version_sesion` impide un contador negativo.
