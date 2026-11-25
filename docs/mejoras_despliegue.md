# Mejoras pendientes para el despliegue en Azure

Mejoras identificadas durante el desarrollo que no se aplican en el entorno local,
pero que conviene revisar antes del despliegue en Azure.

**Estado (Sprint 3, parte L, primera mitad, 25/11/2026):**

| Ítem | Estado |
| --- | --- |
| Contraseñas de los usuarios de conexión en la línea de comandos | Resuelto en la parte L: `\getenv` en `db/aplicar_bd.sh` y `db/init/03_usuarios_bd.sh`, y `deploy/aplicar_bd_vm.sh` en la VM |
| Cambio obligatorio de contraseña en el primer inicio de sesión | Resuelto en la parte I |
| Sesiones abiertas después de restablecer la contraseña | Resuelto en la parte I |

## Contraseñas de los usuarios de conexión en la línea de comandos (resuelto en el Sprint 3, parte L)

**Situación anterior.** `db/aplicar_bd.sh` pasaba las contraseñas de `cdss_clinica`,
`cdss_generacion`, `cdss_admin` y `cdss_auditor` a `psql` como argumentos
(`-v pwd_clinica=...`). No se imprimen en pantalla (se cargan con `\gset`), pero
mientras el script se ejecuta cualquier usuario de la misma máquina puede verlas en
la lista de procesos (por ejemplo, con `ps`).

**Por qué se mantenía así.** En desarrollo el equipo no es compartido, y la
alternativa exige psql 15 o superior, lo que complicaría el uso del script.

**Mejora propuesta para Azure.** Ejecutar el script desde un equipo o agente de
despliegue no compartido y leer las contraseñas de las variables de entorno dentro
de psql con `\getenv` (psql 15 o superior), en lugar de pasarlas con `-v`:

```
\getenv pwd_clinica CDSS_DB_PWD_CLINICA
```

Las variables de entorno se cargan desde Azure Key Vault en el agente de despliegue,
sin escribirlas en el código ni en el historial de la terminal.

**Resuelto en la parte L.** `db/aplicar_bd.sh` y `db/init/03_usuarios_bd.sh` ya no usan `-v`: psql
lee las cinco contraseñas con `\getenv` (y el script se detiene con un mensaje si falta alguna). psql 15
o superior: el equipo de desarrollo tiene psql 17, el CI psql 16 y el contenedor `db` psql 16. En la VM
no hace falta instalar psql: `deploy/aplicar_bd_vm.sh` ejecuta `aplicar_bd.sh` con el cliente de
`postgres:16-alpine` en un contenedor conectado a la red del stack, y le pasa las contraseñas como
variables de entorno por nombre (`-e NOMBRE`, sin el valor en la línea de comandos). Los secretos no
llegan desde un agente de despliegue sino desde Key Vault a la VM, con su identidad administrada
(`deploy/cargar_secretos.sh`, `docs/despliegue_azure.md`). Una prueba
(`backend/tests/test_l_despliegue.py`) comprueba que ningún valor llega a los argumentos de psql.

## Cambio obligatorio de contraseña en el primer inicio de sesión (resuelto en el Sprint 3, parte I)

**Situación anterior.** Al crear una cuenta o restablecer su contraseña (M10, HU11), el
sistema generaba una contraseña temporal que el usuario podía seguir usando indefinidamente, y
no existía una pantalla para cambiar la propia contraseña.

**Resuelto.** Migración 018 y `docs/contrato_autenticacion.md`:

- `seguridad.usuario.debe_cambiar_contrasena`, verdadera al crear la cuenta y al restablecer la
  contraseña. Mientras esté activa, todas las rutas responden 403 con el código
  `CAMBIO_CONTRASENA_OBLIGATORIO`, salvo el inicio de sesión, la salud, `GET /api/auth/me` y
  `POST /api/auth/cambiar-contrasena` (el bloqueo está en la dependencia común, así que una ruta
  nueva queda protegida por omisión).
- Pantalla «Cambiar mi contraseña» (`/cambiar-contrasena`): obligatoria con la marca, sin menú;
  voluntaria para todos los roles desde el encabezado. Aplica la política
  (`CONTRASENA_LONGITUD_MINIMA`, al menos una letra y un número), exige la contraseña actual (un
  error cuenta como intento fallido, con el mismo bloqueo del inicio de sesión) y registra
  CONTRASENA_CAMBIADA sin la contraseña.
- `cdss_clinica` recibe UPDATE solo sobre `hash_contrasena`, `debe_cambiar_contrasena`,
  `version_sesion` y `fecha_cambio_contrasena`, además de las dos columnas que ya tenía.

**Para el despliegue.** Las cuentas existentes y las de `seed_demo` quedan sin la marca, para no
cambiar los flujos de desarrollo ni las pruebas. Si en Azure se cargan cuentas con `seed_demo`
(por ejemplo, para la validación con usuarios), ejecutarlo con `CDSS_SEED_EXIGIR_CAMBIO=true`: cada
cuenta queda con la marca y su contraseña conocida (`SEED_CONTRASENA`) deja de servir después del
primer ingreso. La opción está apagada por omisión (`docker-compose.yml` la pasa como `false`) y
nunca quita una marca ya puesta.

## Sesiones abiertas después de restablecer la contraseña (resuelto en el Sprint 3, parte I)

**Situación anterior.** Desactivar una cuenta o cambiar su rol tenía efecto inmediato, porque cada
petición vuelve a leer la cuenta. En cambio, al restablecer la contraseña, el token JWT emitido
antes seguía siendo válido hasta que vencía (`JWT_MINUTOS`, 480 minutos por defecto), y al
reactivar una cuenta desactivada sus tokens anteriores sin vencer volvían a valer.

**Resuelto.** En lugar de comparar el `iat` del token con una fecha, cada cuenta tiene un contador
`version_sesion` y el token lleva su valor (campo `sv`). `usuario_actual` rechaza con 401 (código
`SESION_REVOCADA`) un token cuyo `sv` no coincide. Cambiar la contraseña, restablecerla y reactivar
la cuenta suben el contador; desactivarla ya cortaba el acceso. Un token emitido antes de la
migración 018 no tiene `sv` y cuenta como 0, el valor de las cuentas existentes, así que las
sesiones abiertas al aplicar la migración siguen funcionando. El contador evita depender de la
precisión del reloj (dos eventos en el mismo segundo) y de comparar zonas horarias.
