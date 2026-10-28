# Pruebas manuales del Sprint 1

Lista ordenada para validar a mano lo construido en el Sprint 1: inicio de sesión y acceso por rol
(HU01), panel de pacientes (M02), registro (M03), historial (M08), nuevo tamizaje (M14), corrección
de datos (HU04) y gestión de usuarios (M10, HU11). Al final se revisa la auditoría.

Los pasos se basan en lo que hacen las pantallas (`frontend/src/pages`) y los endpoints
(`backend/app/api/routes`). Todos los datos son ficticios.

## Antes de empezar

- **Contraseña:** todos los usuarios del seed usan el valor de `SEED_CONTRASENA` del archivo `.env`.
  En este documento se llama «la contraseña del seed».
- **Fecha de referencia:** las edades, la vigencia de los tamizajes y los indicadores esperados se
  calcularon para el **28/10/2026**, con la base recién sembrada. Si se prueba otro día, o con datos
  de pruebas anteriores, los números pueden cambiar (la vigencia es de 30 días,
  `DIAS_VIGENCIA_TAMIZAJE`).
- **Dos navegadores:** algunos pasos necesitan dos sesiones a la vez. Use una ventana normal y otra
  privada (la sesión se guarda en `sessionStorage`, una por pestaña).
- **Columna OK:** marque cada fila al comprobarla y anote en «Observaciones» lo que no coincida.

### Datos de referencia del seed

Todos los pacientes viven en San Luis (160 m.s.n.m., sin ajuste por altitud) salvo los indicados.

| Paciente | DNI | HC | Último tamizaje | Hb | Hb ajustada | Clasificación esperada |
| --- | --- | --- | --- | --- | --- | --- |
| Mateo Quispe Huamán | 81234567 | 00452 | 26/09/2026 (no vigente) | 9,8 | 9,8 | Anemia leve (3 tamizajes) |
| Valentina Ccori Mamani | 81345678 | 00391 | 19/10/2026 | 11,6 | 11,6 | Sin anemia |
| Thiago Huanca Flores | 81456789 | 00517 | 18/10/2026 | 8,9 | 8,9 | Anemia moderada |
| Luana Paucar Ríos | 81567890 | 00288 | 28/07/2026 (no vigente) | 10,4 | 10,4 | Anemia leve |
| Gael Torres Condori | 81678901 | 00602 | 19/10/2026 | sin dato | sin dato | Sin evaluación (falta la hemoglobina) |
| Camila Mamani Choque (Puno, 3827 m) | 81789012 | 00733 | 10/10/2026 | 11,9 | 9,4 | Anemia moderada |
| Sebastián Rojas Lazo (Huancayo, 3259 m) | 81890123 | 00811 | 12/10/2026 | 12,5 | 10,4 | Anemia leve |
| Isabella Flores Cárdenas | 81901234 | 00845 | 16/10/2026 | 6,8 | 6,8 | Anemia severa |
| Diego Ramos Paredes (Ate, 355 m) | 82012345 | 00902 | 14/10/2026 | 11,4 | 11,4 | Sin anemia |
| Sofía Gutiérrez Huamán | 82123456 | 00955 | 15/10/2026 | 11,2 | sin dato | Sin evaluación (4 meses, fuera del rango de 6 a 59 meses) |

---

## Paso 1. Preparar el entorno

**Usuario:** ninguno (terminal Git Bash en la raíz del repositorio).

| # | Acción | Resultado esperado | OK |
| --- | --- | --- | --- |
| 1.1 | Opcional, para partir de cero (borra la base de datos y la base vectorial): `docker compose down -v` | Contenedores y volúmenes eliminados | |
| 1.2 | `docker compose up --build -d` | Los servicios `db`, `chromadb`, `backend` y `nginx` quedan en estado `Up` (`docker compose ps`) | |
| 1.3 | `docker compose exec backend python -m app.scripts.seed_demo` | Imprime los 5 usuarios de prueba, «Pacientes ficticios creados: 10» (0 si ya existían) y los tamizajes clasificados | |
| 1.4 | Abrir http://localhost:8080/api/salud | `{"bd_clinica":"ok","bd_generacion":"ok","bd_admin":"ok","chromadb":"ok","estado":"ok"}` | |

## Paso 2. Inicio de sesión (HU01, M01)

**Usuarios:** `enf.rojas`, un usuario inexistente y `nut.vilca` (para el bloqueo).

| # | Acción | Resultado esperado | OK |
| --- | --- | --- | --- |
| 2.1 | Abrir http://localhost:8080 | Redirige a la pantalla «Iniciar sesión». El botón «Ingresar» está deshabilitado mientras falte el usuario o la contraseña | |
| 2.2 | Ingresar `enf.rojas` con una contraseña incorrecta | Mensaje «Usuario o contraseña incorrectos» | |
| 2.3 | Ingresar `noexiste.prueba` con cualquier contraseña | El mismo mensaje genérico «Usuario o contraseña incorrectos» (no revela si el usuario existe) | |
| 2.4 | Ingresar `ENF.ROJAS` (en mayúsculas) con la contraseña del seed | Ingresa: el usuario no distingue mayúsculas | |
| 2.5 | Revisar la pantalla de inicio | «Hola, Lic. Rosa Rojas», rol Enfermera CRED, permisos `EXPORTAR_REPORTE, REALIZAR_CONSULTA, REGISTRAR_PACIENTE` y los 4 servicios en «ok» | |
| 2.6 | Recargar la página (F5) | La sesión se mantiene | |
| 2.7 | Copiar la dirección y abrirla en una pestaña nueva | Pide iniciar sesión de nuevo (el token vive solo en la pestaña) | |
| 2.8 | Pulsar «Cerrar sesión» | Vuelve a la pantalla de inicio de sesión | |
| 2.9 | Ingresar `nut.vilca` con una contraseña incorrecta **5 veces** | Las 5 veces: «Usuario o contraseña incorrectos» | |
| 2.10 | Ingresar `nut.vilca` una sexta vez, ahora **con la contraseña correcta** | «La cuenta está bloqueada por intentos fallidos. Solicite el desbloqueo al administrador.» La cuenta queda bloqueada para el paso 10 | |

## Paso 3. Menú y acceso por rol

**Usuarios:** los cinco del seed, uno por vez.

| # | Acción | Resultado esperado | OK |
| --- | --- | --- | --- |
| 3.1 | Ingresar con `enf.rojas`, `med.salazar` y `nut.vilca`* | Menú «Atención»: Pacientes, Historial de consultas, Reportes. Sin grupo «Administración» | |
| 3.2 | Con `enf.rojas`, escribir en la barra http://localhost:8080/admin/usuarios | Redirige a la pantalla de inicio | |
| 3.3 | Ingresar con `coord.ortiz` | «Atención»: Pacientes, Historial de consultas, Reportes. «Administración»: Parámetros clínicos, Auditoría | |
| 3.4 | Con `coord.ortiz`, abrir http://localhost:8080/pacientes/nuevo | Redirige a la pantalla de inicio (no tiene `REGISTRAR_PACIENTE`) | |
| 3.5 | Ingresar con `admin.cdss` | Solo «Administración»: Usuarios, Base de conocimiento, Parámetros clínicos, Auditoría | |
| 3.6 | Con `admin.cdss`, abrir http://localhost:8080/pacientes | Redirige a la pantalla de inicio | |
| 3.7 | Abrir Reportes, Base de conocimiento, Parámetros clínicos y Auditoría con un rol que las tenga | Pantalla «En construcción» con el Sprint en que se construye | |

\* `nut.vilca` queda bloqueada en el paso 2. Pruébela después del paso 10.3, o haga este paso antes del 2.9.

## Paso 4. Panel de pacientes y búsqueda (M02)

**Usuario:** `enf.rojas`. Menú «Pacientes».

| # | Acción | Resultado esperado | OK |
| --- | --- | --- | --- |
| 4.1 | Abrir «Pacientes» | Título «Pacientes», buscador, botón «+ Nuevo paciente» y la tabla «Pacientes atendidos recientemente» con los 10 pacientes | |
| 4.2 | Revisar los indicadores | «Evaluaciones hoy» y «Tiempo medio de respuesta»: «Sin datos». «Con anemia detectada»: **6**. «Controles pendientes»: **2**, con la nota «Último tamizaje con más de 30 días» | |
| 4.3 | Revisar la tabla | Mateo y Luana con la etiqueta «No vigente». Gael con Hb «-» y «Sin evaluación». Sofía con Hb 11,2 y «Sin evaluación». Cada fila con «Abrir» y «+ Tamizaje» | |
| 4.4 | Buscar `81234567` (DNI completo) | «Resultados de la búsqueda (1)»: Mateo Quispe Huamán | |
| 4.5 | Buscar `00845` (historia clínica) | 1 resultado: Isabella Flores Cárdenas | |
| 4.6 | Buscar `huaman` (sin tilde ni mayúscula) | 2 resultados: Mateo Quispe Huamán y Sofía Gutiérrez Huamán | |
| 4.7 | Buscar `8123` (DNI parcial) | «No se encontró ningún paciente…»: el DNI y la HC solo coinciden completos | |
| 4.8 | Buscar `Ma` (menos de 3 letras) | Sin resultados: el nombre se busca desde 3 caracteres | |
| 4.9 | Pulsar «Ver recientes» | Vuelve la lista de recientes | |
| 4.10 | Después de buscar, revisar la barra de direcciones | La URL sigue siendo `/pacientes`: el texto buscado no aparece en ella | |

## Paso 5. Historial del paciente (M08)

**Usuario:** `enf.rojas`.

| # | Acción | Resultado esperado | OK |
| --- | --- | --- | --- |
| 5.1 | En M02, pulsar «Abrir» en Mateo Quispe Huamán | Encabezado con nombre, «HC 00452», edad «15 meses», Masculino. Botones «Editar datos», «+ Nuevo tamizaje» y «Nueva consulta» (deshabilitado, Sprint 2) | |
| 5.2 | Revisar los datos | DNI 81234567, nacimiento 12/07/2025, San Luis, Lima, 160 m.s.n.m., A término, bajo peso «No» | |
| 5.3 | Revisar «Evolución de la hemoglobina» | Gráfico con 3 puntos (11,0, 10,1 y 9,8) sobre las franjas de los puntos de corte | |
| 5.4 | Revisar «Tamizajes registrados» | 3 filas, la más reciente primero: 26/09/2026 «No vigente», Anemia leve, síntomas «Palidez, Hiporexia», profesional Lic. Rosa Rojas; 12/05/2026 Anemia leve; 15/01/2026 Sin anemia | |
| 5.5 | Abrir el historial de Camila Mamani Choque | Puno, 3827 m.s.n.m. Hb 11,9 y Hb ajustada 9,4: Anemia moderada | |
| 5.6 | Abrir el historial de Gael Torres Condori y pasar el mouse sobre «Sin evaluación» | Muestra el motivo «Falta la hemoglobina» | |
| 5.7 | Abrir el historial de Sofía Gutiérrez Huamán y pasar el mouse sobre «Sin evaluación» | «Fuera del rango de edad de los puntos de corte (6 a 59 meses)» | |
| 5.8 | Revisar «Evaluaciones realizadas» | «Las evaluaciones de las consultas clínicas estarán disponibles en el Sprint 2.» | |

## Paso 6. Registro de un paciente nuevo (M03, HU02, HU05)

**Usuario:** `enf.rojas`. En M02, «+ Nuevo paciente».

| # | Acción | Resultado esperado | OK |
| --- | --- | --- | --- |
| 6.1 | Abrir el formulario sin llenar nada | «Guardar» deshabilitado. «Guardar y evaluar» deshabilitado con la nota «Disponible en el Sprint 2». La fecha del tamizaje viene con la de hoy | |
| 6.2 | Escribir letras en el DNI | El campo solo acepta dígitos (máximo 8) | |
| 6.3 | Llenar: nombre `Ana Prueba Manual`, DNI `89990001`, HC `PM7731`, distrito Cusco | El campo «Altitud» muestra «3399 · calculada por distrito» | |
| 6.4 | Fecha de nacimiento `15/01/2025`, sexo Femenino | El campo «Edad» muestra «21 meses». «Guardar» se habilita | |
| 6.5 | Hemoglobina `9,8,1` y pulsar «Guardar» | «La hemoglobina debe ser un número» (no se envía) | |
| 6.6 | Hemoglobina `25` y pulsar «Guardar» | Error del servidor «Revise los datos ingresados. tamizaje.hemoglobina_g_dl: debe ser menor o igual que 20…». No se registra nada | |
| 6.7 | Hemoglobina `11,5`. Marcar el síntoma «Otro» sin especificarlo y pulsar «Guardar» | Aparece el campo «Especifique el síntoma». Al guardar: «Especifique el síntoma cuando marque «Otro»» | |
| 6.8 | Cambiar el DNI a `81234567` y pulsar «Guardar» | «Ya existe un paciente registrado con ese DNI» | |
| 6.9 | Volver al DNI `89990001`, cambiar la HC a `00452` y pulsar «Guardar» | «Ya existe un paciente registrado con ese número de historia clínica» | |
| 6.10 | Volver a la HC `PM7731`. Cambiar la fecha de nacimiento a `01/01/2021` y pulsar «Guardar» | «El sistema atiende a niños de 0 a 59 meses; a la fecha del tamizaje el niño tiene 69 meses» | |
| 6.11 | Volver a `15/01/2025`. En «Otro» escribir `Prueba manual`, marcar «Palidez» y pulsar «Guardar» | Abre el historial de la paciente con el aviso «Paciente registrado. Clasificación: Anemia moderada (Hb ajustada 9,4 g/dL).» (11,5 menos el ajuste de 2,1 por altitud) | |
| 6.12 | Revisar el tamizaje en el historial | 1 fila, fecha de hoy, sin «No vigente», síntomas «Palidez, Otro (Prueba manual)» | |
| 6.13 | Registrar otro paciente sin hemoglobina: nombre `Luis Prueba Manual`, DNI `89990002`, HC `PM7732`, San Luis, nacimiento `01/03/2025`, sexo Masculino, Hb vacía | «Paciente registrado. Tamizaje guardado sin clasificación: Falta la hemoglobina.» | |

## Paso 7. Nuevo tamizaje de un paciente registrado (M14, HU18)

**Usuario:** `enf.rojas`.

| # | Acción | Resultado esperado | OK |
| --- | --- | --- | --- |
| 7.1 | En M02, pulsar «+ Tamizaje» en Mateo Quispe Huamán | Pantalla «Nuevo tamizaje». «Datos permanentes» en solo lectura con el enlace «Editar datos» | |
| 7.2 | Revisar los valores del control anterior | Debajo de la hemoglobina: «Anterior: 9,8 · 26/09/2026». Peso 9,6 y talla 76,5. Síntomas «(anterior: palidez, hiporexia)» | |
| 7.3 | Revisar los antecedentes | Vienen marcados como en el control anterior: «Lactancia materna actual» marcada; suplementación y parasitosis sin marcar | |
| 7.4 | Revisar «Vista previa del cálculo» sin hemoglobina | «Ingrese la fecha y la hemoglobina para ver la clasificación» y «control anterior: Anemia leve 9,8 g/dL» | |
| 7.5 | Escribir la hemoglobina `9,0` y esperar medio segundo | «Hb ajustada 9,0 g/dL» con la etiqueta Anemia moderada. Todavía no se guarda nada | |
| 7.6 | Desmarcar «Lactancia materna actual» | Aparece la etiqueta «cambió» junto al antecedente | |
| 7.7 | Peso `9,9`, talla `77`, pulsar «Guardar» | Vuelve al historial con «Tamizaje registrado. Clasificación: Anemia moderada (Hb ajustada 9,0 g/dL).» | |
| 7.8 | Revisar el historial | 4 tamizajes. El nuevo (fecha de hoy) va primero, sin «No vigente». Los 3 anteriores se conservan sin cambios | |
| 7.9 | Volver a M02 | Mateo ya no aparece como «No vigente». «Controles pendientes» baja a **1** | |
| 7.10 | «+ Tamizaje» en Camila Mamani Choque, Hb `12,0` (no guardar) | Vista previa: «Hb ajustada 9,5 g/dL», Anemia leve (12,0 menos 2,5 por altitud). Pulsar «Cancelar» | |
| 7.11 | «+ Tamizaje» en Sofía Gutiérrez Huamán, Hb `11,0` (no guardar) | Vista previa: «Fuera del rango de edad de los puntos de corte (6 a 59 meses)». Pulsar «Cancelar» | |

## Paso 8. Corrección de los datos del paciente (HU04)

**Usuario:** `enf.rojas`.

| # | Acción | Resultado esperado | OK |
| --- | --- | --- | --- |
| 8.1 | En el historial de Ana Prueba Manual, pulsar «Editar datos» | Formulario con los datos actuales. «Guardar cambios» deshabilitado mientras no haya cambios | |
| 8.2 | Cambiar la dirección a `Calle ficticia 123` y el distrito a San Luis. Pulsar «Guardar cambios» | Vuelve al historial con «Datos del paciente actualizados.». Distrito San Luis, 160 m.s.n.m. | |
| 8.3 | Revisar el tamizaje de la paciente | Sigue en Anemia moderada con Hb ajustada 9,4: la clasificación guardada no se recalcula al cambiar el distrito | |
| 8.4 | «Editar datos» otra vez, cambiar el DNI a `81234567` y guardar | «Ya existe un paciente registrado con ese DNI». No se guarda | |
| 8.5 | Abrir «Editar datos» de Mateo Quispe Huamán, cambiar la fecha de nacimiento a `01/02/2026` y guardar | «La fecha de nacimiento no puede ser posterior a un tamizaje ya registrado». Pulsar «Cancelar» | |

## Paso 9. Acceso de solo lectura a pacientes

**Usuario:** `coord.ortiz`.

| # | Acción | Resultado esperado | OK |
| --- | --- | --- | --- |
| 9.1 | Abrir «Pacientes» | Indicadores y tabla visibles, sin «+ Nuevo paciente» ni «+ Tamizaje» (solo «Abrir») | |
| 9.2 | Abrir el historial de Mateo Quispe Huamán | Ficha y tamizajes visibles. Sin «Editar datos» ni «+ Nuevo tamizaje»; solo «Nueva consulta» deshabilitado | |
| 9.3 | Escribir en la barra `/pacientes/<id>/editar` con el id del paciente abierto | Redirige a la pantalla de inicio | |
| 9.4 | Abrir «Historial de consultas» y buscar `00452` | Título «Historial de consultas», sin indicadores; «Abrir» lleva al historial de Mateo | |

## Paso 10. Gestión de usuarios (M10, HU11)

**Usuario:** `admin.cdss` en la ventana normal. Para los inicios de sesión de prueba, use la ventana privada.

| # | Acción | Resultado esperado | OK |
| --- | --- | --- | --- |
| 10.1 | Abrir «Usuarios» | Tabla con los 5 usuarios del seed (sin la cuenta técnica «sistema»): nombre, usuario, rol, estado y último acceso («Nunca» si no ha ingresado). `nut.vilca` en estado «Bloqueado» | |
| 10.2 | Pulsar «Editar» en `nut.vilca` | Panel «Editar usuario». El campo usuario es de solo lectura. Estado «Bloqueado por intentos fallidos de inicio de sesión» y botón «Desbloquear» | |
| 10.3 | Pulsar «Desbloquear» | «Cuenta desbloqueada.» y estado «Activo». En la ventana privada, `nut.vilca` ingresa con la contraseña del seed | |
| 10.4 | Pulsar «+ Nuevo usuario» | Panel «Nuevo usuario». «Crear usuario» deshabilitado hasta completar nombre (3 caracteres o más), usuario y rol | |
| 10.5 | Elegir el rol «Enfermera CRED» | Las casillas de permisos (solo lectura) marcan Registrar pacientes, Realizar consultas y Exportar reportes | |
| 10.6 | Usuario `enf.rojas` (repetido), nombre `Lic. Lucía Prueba`, rol Enfermera CRED. «Crear usuario» | «Ya existe una cuenta con el usuario enf.rojas» | |
| 10.7 | Usuario `enf prueba` (con espacio). «Crear usuario» | «Revise los datos ingresados. nombre_usuario: El usuario solo admite letras minúsculas sin tildes, números y puntos…» | |
| 10.8 | Usuario `enf.prueba`, correo `rosa.rojas@example.org`. «Crear usuario» | «Ya existe una cuenta con ese correo institucional» | |
| 10.9 | Correo `correo@`. «Crear usuario» | «…correo_institucional: El correo institucional no tiene un formato válido» | |
| 10.10 | Correo `lucia.prueba@example.org`. «Crear usuario» | Diálogo «Usuario creado» con la contraseña temporal de `enf.prueba` (16 caracteres), botón «Copiar» y el aviso «Esta es la única vez que se muestra…». Copie la contraseña | |
| 10.11 | Cerrar el diálogo (botón «Cerrar» o tecla Esc) | El diálogo desaparece y la contraseña no se puede volver a ver. El panel queda en «Editar usuario» con «Usuario creado.» | |
| 10.12 | En la ventana privada, ingresar con `enf.prueba` y la contraseña temporal | Ingresa con el menú de Enfermera CRED | |
| 10.13 | En `admin.cdss`, recargar «Usuarios» | El último acceso de `enf.prueba` muestra «Hoy HH:MM» | |
| 10.14 | Editar `enf.prueba`: rol Coordinador CRED. «Guardar» | «Cambios guardados.». El botón «Guardar» se deshabilita de nuevo al no haber cambios pendientes | |
| 10.15 | En la ventana privada (`enf.prueba`), recargar la página | El menú cambia al de Coordinador CRED: el cambio de rol tiene efecto inmediato | |
| 10.16 | En `admin.cdss`, pulsar «Restablecer contraseña» en `enf.prueba` y confirmar | Diálogo «Contraseña restablecida» con una contraseña nueva. Cópiela | |
| 10.17 | En la ventana privada, cerrar sesión e ingresar con la contraseña **anterior** | «Usuario o contraseña incorrectos». Con la nueva, ingresa | |
| 10.18 | En `admin.cdss`, pulsar «Desactivar» en `enf.prueba` | Pide confirmar. Luego «Cuenta desactivada.», estado «Inactivo» y la cuenta pasa al final de la lista | |
| 10.19 | En la ventana privada, recargar la página | Vuelve a la pantalla de inicio de sesión. Al ingresar: «La cuenta está desactivada. Comuníquese con el administrador.» | |
| 10.20 | En `admin.cdss`, pulsar «Reactivar» en `enf.prueba` | «Cuenta reactivada.» y estado «Activo». En la ventana privada vuelve a ingresar | |
| 10.21 | Pulsar «Editar» en la propia cuenta `admin.cdss` | El rol está deshabilitado con «No puede cambiar el rol de su propia cuenta». No aparece el botón «Desactivar». **No pulse** «Restablecer contraseña» en su propia cuenta | |

## Paso 11. Revisar la auditoría

**Usuario:** ninguno (terminal Git Bash en la raíz del repositorio). Se usa `psql` dentro del
contenedor `db` con el usuario de administración de PostgreSQL. Esto es solo para la revisión
manual; la aplicación nunca usa ese usuario.

### 11.1 Últimos eventos

```bash
docker compose exec -T db psql -U postgres -d cdss -P pager=off -c "SELECT e.id_evento, to_char(e.fecha_hora AT TIME ZONE 'America/Lima', 'DD/MM HH24:MI:SS') AS hora, coalesce(u.nombre_usuario, '(sin usuario)') AS usuario, e.tipo_evento, e.entidad, e.detalle FROM auditoria.evento_auditoria e LEFT JOIN seguridad.usuario u ON u.id_usuario = e.id_usuario ORDER BY e.id_evento DESC LIMIT 80;"
```

### 11.2 Resumen por tipo de evento

```bash
docker compose exec -T db psql -U postgres -d cdss -P pager=off -c "SELECT tipo_evento, count(*) AS eventos FROM auditoria.evento_auditoria GROUP BY tipo_evento ORDER BY tipo_evento;"
```

### 11.3 Ningún dato identificatorio en el detalle

```bash
docker compose exec -T db psql -U postgres -d cdss -P pager=off -c "SELECT count(*) AS eventos_con_identidad FROM auditoria.evento_auditoria WHERE detalle::text ILIKE ANY (ARRAY['%81234567%', '%89990001%', '%PM7731%', '%Prueba Manual%', '%huaman%', '%Calle ficticia%']);"
```

### 11.4 La bitácora no admite cambios

Se ejecuta dentro de una transacción que se revierte, para no alterar nada si la protección fallara.

```bash
docker compose exec -T db psql -U postgres -d cdss -P pager=off -c "BEGIN; UPDATE auditoria.evento_auditoria SET tipo_evento = 'PRUEBA' WHERE id_evento = (SELECT max(id_evento) FROM auditoria.evento_auditoria); ROLLBACK;"
```

| # | Comprobación | Resultado esperado | OK |
| --- | --- | --- | --- |
| 11.5 | Inicios de sesión (paso 2) | `INICIO_SESION` por cada ingreso. `INICIO_SESION_FALLIDO` con `detalle` `{"motivo": "contrasena_incorrecta", "intento": n}`, `{"motivo": "usuario_inexistente"}` (usuario «(sin usuario)»), `{"motivo": "cuenta_bloqueada"}` y `{"motivo": "cuenta_inactiva"}` | |
| 11.6 | Búsquedas (paso 4) | `PACIENTE_BUSCADO` con solo `{"coincidencias": [...], "resultados": n}`, por ejemplo `["DNI"]`, `["HC"]` o `["NOMBRE"]`. Nunca el texto buscado | |
| 11.7 | Ficha del paciente (pasos 5, 7, 8 y 9) | `IDENTIDAD_CONSULTADA` (entidad `paciente_identidad`, sin detalle) cada vez que se abrió una ficha, también con `coord.ortiz` | |
| 11.8 | Registro (paso 6) | `PACIENTE_REGISTRADO` con `{"con_tamizaje": true}` seguido de `TAMIZAJE_REGISTRADO` con `id_paciente`, `categoria` y `nivel_riesgo` (`ANEMIA_MODERADA`, `ALTO`). El de Luis Prueba Manual con `categoria` y `nivel_riesgo` en `null` | |
| 11.9 | Nuevo tamizaje (paso 7) | Un solo `TAMIZAJE_REGISTRADO` nuevo (Mateo). Las vistas previas y los tamizajes cancelados no dejan `TAMIZAJE_REGISTRADO` (abrir la pantalla sí deja `IDENTIDAD_CONSULTADA`) | |
| 11.10 | Corrección (paso 8) | `PACIENTE_ACTUALIZADO` con solo los nombres de los campos: `{"campos": ["direccion", "ubigeo_residencia"]}`. Los intentos rechazados no dejan `PACIENTE_ACTUALIZADO` | |
| 11.11 | Usuarios (paso 10) | `USUARIO_DESBLOQUEADO` (nut.vilca), `USUARIO_CREADO` con `{"nombre_usuario": "enf.prueba", "rol": "Enfermera CRED"}`, `USUARIO_MODIFICADO` con `{"campos": ["id_rol"], "rol_anterior": "Enfermera CRED", "rol_nuevo": "Coordinador CRED"}`, `CONTRASENA_RESTABLECIDA` con `{"nombre_usuario": "enf.prueba", "estaba_bloqueada": false}`, `USUARIO_DESACTIVADO` y `USUARIO_REACTIVADO`. Ninguno contiene contraseñas | |
| 11.12 | Comando 11.3 | `eventos_con_identidad` igual a **0** | |
| 11.13 | Comando 11.4 | `ERROR: La bitácora de auditoría no admite modificaciones ni eliminaciones` | |

## Paso 12. Pruebas automáticas y compilación

**Usuario:** ninguno (terminal Git Bash).

| # | Acción | Resultado esperado | OK |
| --- | --- | --- | --- |
| 12.1 | `cd backend && pytest -q` (con `.env.test` configurado y la base de pruebas sembrada) | Todas las pruebas pasan, incluidas las de `test_usuarios.py` | |
| 12.2 | `cd frontend && npm run build` | Compila sin errores de TypeScript | |

## Observaciones

| Paso | Qué se observó | Acción |
| --- | --- | --- |
| | | |
