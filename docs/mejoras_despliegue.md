# Mejoras pendientes para el despliegue en Azure

Mejoras identificadas durante el desarrollo que no se aplican en el entorno local,
pero que conviene revisar antes del despliegue en Azure.

## Contraseñas de los usuarios de conexión en la línea de comandos

**Situación actual.** `db/aplicar_bd.sh` pasa las contraseñas de `cdss_clinica`,
`cdss_generacion`, `cdss_admin` y `cdss_auditor` a `psql` como argumentos
(`-v pwd_clinica=...`). No se imprimen en pantalla (se cargan con `\gset`), pero
mientras el script se ejecuta cualquier usuario de la misma máquina puede verlas en
la lista de procesos (por ejemplo, con `ps`).

**Por qué se mantiene así.** En desarrollo el equipo no es compartido, y la
alternativa exige psql 15 o superior, lo que complicaría el uso del script.

**Mejora propuesta para Azure.** Ejecutar el script desde un equipo o agente de
despliegue no compartido y leer las contraseñas de las variables de entorno dentro
de psql con `\getenv` (psql 15 o superior), en lugar de pasarlas con `-v`:

```
\getenv pwd_clinica CDSS_DB_PWD_CLINICA
```

Las variables de entorno se cargan desde Azure Key Vault en el agente de despliegue,
sin escribirlas en el código ni en el historial de la terminal.

## Cambio obligatorio de contraseña en el primer inicio de sesión (Sprint 3)

**Situación actual.** Al crear una cuenta o restablecer su contraseña (M10, HU11), el
sistema genera una contraseña temporal aleatoria y la muestra una sola vez al
administrador, que la entrega al usuario. El usuario puede seguir usándola
indefinidamente, y no existe una pantalla para que cambie su propia contraseña.

**Mejora propuesta para el Sprint 3.**

- Agregar a `seguridad.usuario` la columna `debe_cambiar_contrasena` (verdadera al
  crear la cuenta y al restablecer la contraseña).
- Mientras esté activa, el inicio de sesión solo permite ir a la pantalla de cambio
  de contraseña; el resto de las rutas responde 403.
- Pantalla «Cambiar mi contraseña», accesible para todos los roles desde el
  encabezado: pide la contraseña actual y la nueva, aplica la política
  (`CONTRASENA_LONGITUD_MINIMA`, al menos una letra y un número) y registra el evento
  `CONTRASENA_CAMBIADA` en la auditoría, sin la contraseña.
- Dar a `cdss_clinica` el permiso `UPDATE` solo sobre `hash_contrasena` y
  `debe_cambiar_contrasena`, o atender el cambio con la conexión `cdss_admin`.

## Sesiones abiertas después de restablecer la contraseña

**Situación actual.** Desactivar una cuenta o cambiar su rol tiene efecto inmediato,
porque cada petición vuelve a leer la cuenta. En cambio, al restablecer la
contraseña, el token JWT emitido antes sigue siendo válido hasta que vence
(`JWT_MINUTOS`, 480 minutos por defecto). Se aceptó así durante el desarrollo.

**Mejora propuesta para Azure.** Invalidar las sesiones anteriores al restablecer la
contraseña. Por ejemplo, con una columna `fecha_cambio_contrasena` en
`seguridad.usuario`: `usuario_actual` rechaza los tokens cuyo `iat` sea anterior a esa
fecha. Mientras tanto, desactivar la cuenta corta el acceso de inmediato, pero al
reactivarla los tokens anteriores que no hayan vencido vuelven a ser válidos.
