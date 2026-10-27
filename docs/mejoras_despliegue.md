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
