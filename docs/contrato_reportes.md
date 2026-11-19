# Contrato de la API del reporte exportable (M09, HU10; Sprint 3, parte C1)

Rutas del reporte de una consulta, para la pantalla M09 (parte C2). OpenAPI lo refleja en `/docs`
y `/openapi.json`. Código: `backend/app/api/routes/reportes.py`, `backend/app/reportes/` y
`backend/app/services/reportes.py`. Ejemplos reales, generados por las pruebas con datos
sintéticos y normalizados, en `frontend/src/__fixtures__` (`reporte_vista_previa_expediente.json`,
`reporte_vista_previa_cuidador.json` y `reportes_lista.json`); tipos en
`frontend/src/api/tipos_reporte.ts`.

Nada de esta parte usa el modelo de lenguaje.

## Reglas comunes

- **Autenticación:** `Authorization: Bearer <token>`. Sin sesión válida: 401.
- **Permiso:** EXPORTAR_REPORTE (Enfermera CRED, Médico, Nutricionista y Coordinador CRED). El
  Administrador no lo tiene: 403.
- **Propiedad:** solo las consultas propias, con la misma regla que las rutas de consultas
  (fila 59 de `cambios_respecto_al_OE2.md`): la de otro responde 404 («La consulta no existe»,
  igual que una inexistente) y queda el evento ACCESO_DENEGADO_CONSULTA con la acción
  `vista_previa_reporte`, `exportar_reporte` o `listar_reportes`.
- **Estado:** solo consultas con resultado, VERIFICADA o EVIDENCIA_INSUFICIENTE. En otro estado,
  409 con `{"detail": "Solo se puede exportar el reporte de una consulta verificada o con
  evidencia insuficiente (estado actual: <ESTADO>)"}`.
- **Validación:** destino, sección o formato no válidos dan 422 con el formato de Sprint 1:
  `{"detail": "Revise los datos ingresados. <campo>: <mensaje>", "errores": [{"campo", "mensaje"}]}`.
- **Consultas de prueba:** si la respuesta la generó el cliente falso (`modo_prueba`), el reporte
  se genera igual, con el aviso «MODO DE PRUEBA, no es un documento clínico» en cada página, y el
  evento lo registra.
- **Datos del paciente:** nombre completo e historia clínica (descifrados en el servidor con
  `cdss_clinica`, como en M02), sexo y edad. Nunca el DNI ni la dirección. Ni el nombre del
  archivo, ni las cabeceras, ni los metadatos del PDF, ni los eventos llevan datos del paciente.

## Destinos y secciones

| Sección | Título en el reporte | EXPEDIENTE | CUIDADOR |
| --- | --- | --- | --- |
| `PACIENTE` | Datos del paciente (Datos de su niña o niño) | Siempre | Siempre |
| `CLASIFICACION` | Clasificación y nivel de riesgo (Resultado de la evaluación) | Siempre | Siempre |
| `RECOMENDACION` | Recomendación clínica (Indicaciones del personal de salud) | Opcional | Opcional |
| `EVIDENCIAS` | Evidencias citadas | Opcional | No se admite (422) |
| `ADVERTENCIAS` | Advertencias | Opcional | No se admite (422) |
| `VERIFICACION` | Verificación de la respuesta | Opcional | No se admite (422) |
| `DECISION` | Decisión del profesional | Opcional | No se admite (422) |
| `FIRMA` | Espacio de firma y sello | Opcional | Opcional |

Las obligatorias se agregan aunque no se envíen. Las secciones se guardan y se devuelven en el
orden de la tabla, sin repetir. Todo reporte termina con «La decisión final corresponde al
profesional tratante.» y «Generado por: <nombre del usuario> · <fecha de emisión>».

### Contenido del reporte EXPEDIENTE

- **Encabezado:** título «Reporte de evaluación de anemia infantil», establecimiento
  (`CDSS_ESTABLECIMIENTO`, por omisión «Centro de Salud San Luis · Servicio CRED»), número y fecha
  de emisión. El número también va en la cabecera de cada página.
- **PACIENTE:** nombre, historia clínica, sexo, edad al tamizaje, fecha del tamizaje, fecha de la
  consulta, Hb observada, Hb ajustada por altitud y altitud.
- **CLASIFICACION:** clasificación, nivel de riesgo, si requiere derivación y factores
  identificados.
- **RECOMENDACION:** resultado de la consulta, pregunta realizada (filtrada), resumen y pasos con
  sus citas (`[F-01, F-02]`). Con EVIDENCIA_INSUFICIENTE, el mensaje de la consulta.
- **EVIDENCIAS:** cada cita con su código, documento, sección, páginas, extracto y, si hay, la
  traducción de apoyo.
- **ADVERTENCIAS** de la respuesta.
- **VERIFICACION:** 6.1 Citas textuales, 6.2 Consistencia y dosis y 6.3 Suficiencia de la
  evidencia (Cumplido, No cumplido o No evaluado, con la relevancia frente al umbral) y el intento
  evaluado.
- **DECISION:** tipo, nota, «Registrada por» y fecha y hora; o «Sin decisión registrada.».
- **FIRMA:** línea de «Firma y sello del profesional».

### Contenido del reporte CUIDADOR

Solo frases fijas de `backend/app/reportes/lenguaje_sencillo.yaml`, nunca el texto generado:

- **PACIENTE:** nombre, historia clínica, edad y fecha de la evaluación.
- **CLASIFICACION:** la frase de la clasificación. Si es anemia, también la frase que explica qué
  es; si requiere derivación, la frase de la derivación.
- **RECOMENDACION:** una frase por tipo de paso (PREVENCION, TRATAMIENTO, SEGUIMIENTO, CONSEJERIA,
  DERIVACION u OTRO), sin repetir y en el orden de los pasos, **solo si el profesional registró la
  decisión ACEPTA_RECOMENDACION**. Sin decisión, con otra decisión o sin recomendación:
  «El personal de salud le explicará las indicaciones para su niña o niño.».
- **RECUERDE** (siempre): las indicaciones generales de acudir a los controles y seguir las
  indicaciones del personal de salud.
- Mientras el archivo tenga `revisado: false`, cada página lleva «Texto en revisión clínica: no
  entregar a pacientes» y la vista previa trae `revision_pendiente: true`.

## GET /api/consultas/{id_consulta}/reportes/vista-previa

Contenido del reporte para la vista previa de M09, en JSON. No reserva número, no calcula el hash y
no escribe en `asistencia.reporte`. Deja el evento REPORTE_VISTA_PREVIA. Responde con
`Cache-Control: no-store` porque lleva datos del paciente.

| Parámetro | Tipo | Descripción |
| --- | --- | --- |
| `destino` | `EXPEDIENTE` o `CUIDADOR` | Obligatorio |
| `secciones` | texto | Secciones opcionales, repetidas (`secciones=A&secciones=B`) o separadas por comas (`secciones=A,B`) |

| Código | Caso |
| --- | --- |
| 200 | `VistaPrevia` |
| 401, 403, 404, 409, 422 | Ver «Reglas comunes» |

`VistaPrevia`:

| Campo | Tipo | Descripción |
| --- | --- | --- |
| `id_consulta` | UUID | |
| `destino` | texto | |
| `secciones` | lista | Obligatorias y elegidas, en el orden del reporte |
| `modo_prueba` | booleano | Consulta generada por el cliente falso |
| `revision_pendiente` | booleano | Reporte del cuidador con las frases sin aprobar |
| `titulo`, `introduccion` | texto (`introduccion` puede ser null) | |
| `establecimiento` | texto | |
| `fecha_consulta` | fecha y hora | |
| `avisos` | lista de textos | Líneas que se repiten en cada página del PDF |
| `bloques` | lista de `{seccion, titulo, campos: [{etiqueta, valor}], parrafos: [texto], items: [{texto, detalle: [texto]}]}` | El cuerpo del reporte. `seccion` es una de la tabla o `RECUERDE` |
| `frase_final` | texto | «La decisión final corresponde al profesional tratante.» |
| `firma` | booleano | Si lleva el espacio de firma y sello |
| `generado_por` | texto | Nombre visible del usuario |

Ejemplo (datos sintéticos, recortado):

```json
{
  "destino": "CUIDADOR",
  "secciones": ["PACIENTE", "CLASIFICACION", "RECOMENDACION", "FIRMA"],
  "modo_prueba": true,
  "revision_pendiente": true,
  "titulo": "Información para la familia",
  "avisos": ["MODO DE PRUEBA, no es un documento clínico", "Texto en revisión clínica: no entregar a pacientes"],
  "bloques": [
    {"seccion": "PACIENTE", "titulo": "Datos de su niña o niño",
     "campos": [{"etiqueta": "Nombre", "valor": "Paciente Ficticio Dos"}, {"etiqueta": "Historia clínica", "valor": "HC-PRUEBA-2"}],
     "parrafos": [], "items": []},
    {"seccion": "CLASIFICACION", "titulo": "Resultado de la evaluación", "campos": [],
     "parrafos": ["La prueba de hemoglobina de su niña o niño dio un resultado sin anemia."], "items": []}
  ],
  "frase_final": "La decisión final corresponde al profesional tratante.",
  "firma": true
}
```

## POST /api/consultas/{id_consulta}/reportes

Genera el PDF en el servidor con ReportLab, en memoria, y lo entrega como adjunto. Registra una
fila en `asistencia.reporte` con el número, el destino, las secciones, el usuario, la fecha y el
SHA-256 de los bytes entregados. El PDF no se guarda en disco ni en ningún volumen: un reporte
perdido se vuelve a exportar, y cada exportación es un reporte nuevo con su número.

Cuerpo:

```json
{"destino": "EXPEDIENTE", "secciones": ["RECOMENDACION", "EVIDENCIAS", "VERIFICACION", "DECISION", "FIRMA"], "formato": "PDF"}
```

`formato` es opcional y solo admite `PDF`: la impresión se hace desde el PDF. Un campo de más da 422.

| Código | Caso |
| --- | --- |
| 201 | El PDF (`application/pdf`) |
| 401, 403, 404, 409, 422 | Ver «Reglas comunes» |

Cabeceras de la respuesta 201:

| Cabecera | Valor |
| --- | --- |
| `Content-Type` | `application/pdf` |
| `Content-Disposition` | `attachment; filename="EV-2026-00918.pdf"` (el número, sin datos del paciente) |
| `Cache-Control` | `no-store` |
| `X-Reporte-Numero` | `EV-2026-00918` |
| `X-Reporte-Hash` | SHA-256 del cuerpo, en hexadecimal (64 caracteres) |

El CORS expone `Content-Disposition`, `X-Reporte-Numero` y `X-Reporte-Hash`; Nginx las deja pasar.

**Número:** `EV-AAAA-NNNNN` (migración 013). AAAA es el año de emisión en hora de Perú; NNNNN, una
secuencia global (`asistencia.reporte_numero_seq`) de 5 cifras o más, sin truncar. Es único y
creciente, también con exportaciones simultáneas (nextval es atómico). Al cambiar de año el
correlativo sigue (no vuelve a 00001), y una exportación que falla deja un hueco.

**PDF:**
- Tamaño A4, con la fuente DejaVu Sans incrustada (cubre ≥, ¿, N°, «» y las tildes; el texto se
  puede copiar y buscar).
- Cada página repite el establecimiento, el número, los avisos, la fecha de emisión y el número de
  página.
- Los metadatos llevan solo el número.
- El mismo contenido da los mismos bytes: el PDF se genera en modo `invariant`, sin fecha de
  creación aleatoria.

## GET /api/consultas/{id_consulta}/reportes

Reportes emitidos de la consulta, del más reciente al más antiguo (por el correlativo), sin el PDF.

| Código | Caso |
| --- | --- |
| 200 | Lista (puede estar vacía) |
| 401, 403, 404 | Ver «Reglas comunes» (sin la regla del estado) |

Cada elemento:

| Campo | Tipo | Descripción |
| --- | --- | --- |
| `numero_reporte` | texto | `EV-AAAA-NNNNN` |
| `destino` | `EXPEDIENTE` o `CUIDADOR` | |
| `secciones` | lista | Secciones incluidas |
| `formato` | `PDF` | |
| `fecha_generacion` | fecha y hora | |
| `hash_documento` | texto | SHA-256 del PDF entregado |

```json
[
  {"numero_reporte": "EV-2026-00002", "destino": "CUIDADOR", "secciones": ["PACIENTE", "CLASIFICACION", "RECOMENDACION", "FIRMA"],
   "formato": "PDF", "fecha_generacion": "2026-10-20T10:00:00-05:00", "hash_documento": "aaaa…"},
  {"numero_reporte": "EV-2026-00001", "destino": "EXPEDIENTE", "secciones": ["PACIENTE", "CLASIFICACION", "RECOMENDACION", "EVIDENCIAS", "ADVERTENCIAS", "VERIFICACION", "DECISION", "FIRMA"],
   "formato": "PDF", "fecha_generacion": "2026-10-20T10:00:00-05:00", "hash_documento": "aaaa…"}
]
```

## Uso desde la interfaz (M09, parte C2)

- La vista previa se pide al cambiar el destino o las secciones, 350 ms después del último cambio,
  con `secciones` separadas por comas y las obligatorias incluidas.
- «Generar reporte (PDF)» hace un solo POST por clic y no admite un segundo mientras el primero
  está en curso. El número y el hash se leen de `X-Reporte-Numero` y `X-Reporte-Hash`.
- «Descargar PDF» y «Abrir para imprimir» usan el mismo PDF recibido, guardado como blob en la
  memoria de la página, sin otro POST. El blob se libera al generar otro o al salir de M09; nada
  se guarda en localStorage, sessionStorage ni en la caché del navegador.
- Un reporte perdido no se vuelve a descargar desde la lista: se genera otro, con otro número.
- Un 409 deshabilita «Generar»; un 401 cierra la sesión como en el resto de la aplicación.

## Auditoría

Sin datos del paciente; entidad `asistencia.consulta` con el id de la consulta:

| Evento | Detalle |
| --- | --- |
| REPORTE_GENERADO | `numero_reporte`, `destino`, `secciones` (cantidad), `hash_prefijo` (12 primeros caracteres del SHA-256) y `modo_prueba` |
| REPORTE_VISTA_PREVIA | `destino`, `secciones` (cantidad) y `modo_prueba` |
| ACCESO_DENEGADO_CONSULTA | `accion`: `vista_previa_reporte`, `exportar_reporte` o `listar_reportes` |

## Memoria y tiempo (18/11/2026, contenedor `backend` con 512 MB)

| Medida | Resultado |
| --- | --- |
| Primera generación en el proceso, con la carga de ReportLab y de la fuente | 1,2 s y unos 20 MB de memoria, una sola vez |
| Siguientes, EXPEDIENTE con todas las secciones (2 páginas, 5 citas) | 26 ms, sin aumento de memoria |
| Siguientes, CUIDADOR (1 página) | 12 ms, sin aumento de memoria |
| Tamaño del PDF | unos 45 a 50 KB (la fuente va recortada a los caracteres usados) |
