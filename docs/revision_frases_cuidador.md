# Revisión de las frases del reporte para el cuidador

Ficha para que la coordinación CRED (o quien designe el asesor) apruebe las frases fijas del reporte
«Entrega al cuidador» de M09. El reporte no usa el modelo de lenguaje: se arma solo con estas frases,
elegidas por la clasificación, si requiere derivación y el tipo de cada paso que el profesional
aceptó (fila 112 de `docs/cambios_respecto_al_OE2.md`).

**Instrucciones:** marque «Sí» o «No» en cada fila; si marca «No», escriba en «Observación» el texto
que propone o lo que hay que corregir. Al terminar, anote al pie la fecha y el cargo de quien revisó
(sin nombres en este archivo; la ficha firmada se guarda fuera del repositorio).

**Recordatorio:** ninguna frase debe incluir dosis, medicamentos, plazos («de inmediato», «en 30
días») ni cifras. Las frases solo reformulan lo que el personal de salud ya indicó; las indicaciones
concretas las da el profesional en la atención. Por eso el paso de derivación no dice «de inmediato»
aunque la NTS 213 lo indique para la anemia severa: es un plazo y queda a criterio de quien revisa
(fila 166).

Mientras el archivo `backend/app/reportes/lenguaje_sencillo.yaml` tenga `revisado: false`, cada
página del reporte lleva «Texto en revisión clínica: no entregar a pacientes».

## 1. Frases de `lenguaje_sencillo.yaml` (21)

| N.° | Clave | Cuándo aparece | Texto actual | Aprobada (Sí / No) | Observación |
| --- | --- | --- | --- | --- | --- |
| 1 | `titulo` | Título del reporte | Información para la familia |  |  |
| 2 | `introduccion` | Debajo del título | Este documento resume el resultado de la evaluación de anemia de su niña o niño en el servicio CRED. El personal de salud le explicará cada punto. |  |  |
| 3 | `titulos.resultado` | Título del bloque del resultado | Resultado de la evaluación |  |  |
| 4 | `titulos.indicaciones` | Título del bloque de indicaciones | Indicaciones del personal de salud |  |  |
| 5 | `titulos.recuerde` | Título del bloque final | Recuerde |  |  |
| 6 | `clasificacion.SIN_ANEMIA` | Según la clasificación | La prueba de hemoglobina de su niña o niño dio un resultado sin anemia. |  |  |
| 7 | `clasificacion.ANEMIA_LEVE` | Según la clasificación | La prueba de hemoglobina de su niña o niño muestra anemia leve. |  |  |
| 8 | `clasificacion.ANEMIA_MODERADA` | Según la clasificación | La prueba de hemoglobina de su niña o niño muestra anemia moderada. |  |  |
| 9 | `clasificacion.ANEMIA_SEVERA` | Según la clasificación | La prueba de hemoglobina de su niña o niño muestra anemia severa. |  |  |
| 10 | `clasificacion.SIN_CLASIFICACION` | Según la clasificación | Esta evaluación no tiene una clasificación de anemia. El personal de salud le explicará el resultado. |  |  |
| 11 | `que_es_anemia` | Si hay anemia | La anemia significa que la sangre tiene menos hemoglobina de la que necesita. |  |  |
| 12 | `derivacion` | Si requiere derivación y el paso DERIVACION no está entre las indicaciones | El personal de salud indicó que su niña o niño debe ser atendido en otro establecimiento de salud. Siga las indicaciones que le dieron para acudir. |  |  |
| 13 | `pasos.PREVENCION` | Si la recomendación aceptada tiene un paso de ese tipo | Le indicaron medidas para prevenir la anemia. Sígalas tal como se las explicó el personal de salud. |  |  |
| 14 | `pasos.TRATAMIENTO` | Si la recomendación aceptada tiene un paso de ese tipo | Le indicaron un tratamiento. Déselo a su niña o niño tal como se lo explicó el personal de salud. |  |  |
| 15 | `pasos.SEGUIMIENTO` | Si la recomendación aceptada tiene un paso de ese tipo | Le indicaron controles para ver cómo sigue su niña o niño. Acuda en las fechas que le indicaron. |  |  |
| 16 | `pasos.CONSEJERIA` | Si la recomendación aceptada tiene un paso de ese tipo | Le dieron recomendaciones para el cuidado de su niña o niño. Póngalas en práctica como se las explicaron. |  |  |
| 17 | `pasos.DERIVACION` | Si la recomendación aceptada tiene un paso de ese tipo | Le indicaron acudir a otro establecimiento de salud. Hágalo como se lo explicaron. |  |  |
| 18 | `pasos.OTRO` | Si la recomendación aceptada tiene un paso de ese tipo | Le dieron otra indicación. Si tiene dudas sobre ella, pregunte al personal de salud. |  |  |
| 19 | `pasos_no_disponibles` | Si el profesional no aceptó la recomendación o no hay pasos | El personal de salud le explicará las indicaciones para su niña o niño. |  |  |
| 20 | `indicaciones_generales[1]` | Siempre | Acuda a todos los controles de su niña o niño en el establecimiento de salud. |  |  |
| 21 | `indicaciones_generales[2]` | Siempre | Siga las indicaciones del personal de salud. Si tiene dudas, pregúntelas en su próximo control. |  |  |

## 2. Textos fijos del código en el reporte para el cuidador

Están en `backend/app/reportes/contenido.py` y `pdf.py`, no en el YAML. Los marcados «Cambia en la
fila 166» son los que se ajustaron para la familia; los demás se muestran para que la revisión cubra
todo lo que lee el cuidador.

| N.° | Dónde | Texto actual | Nota | Aprobada (Sí / No) | Observación |
| --- | --- | --- | --- | --- | --- |
| 22 | Frase final | Estas indicaciones las revisa y confirma el personal de salud que atiende a su niña o niño. | Cambia en la fila 166 (antes: «La decisión final corresponde al profesional tratante.», que sigue en el reporte del expediente) |  |  |
| 23 | Datos: fecha | Fecha de la evaluación: dd/mm/aaaa | Cambia en la fila 166: sin la hora (el expediente la conserva) |  |  |
| 24 | Título del bloque de datos | Datos de su niña o niño | Sin cambio |  |  |
| 25 | Campos de datos | Nombre, Historia clínica, Edad | Sin cambio |  |  |
| 26 | Subtítulo bajo el título | [Establecimiento] · Reporte N.° EV-AAAA-NNNNN · Emitido el dd/mm/aaaa hh:mm | Sin cambio |  |  |
| 27 | Pie de la frase final | Generado por: [profesional] · dd/mm/aaaa hh:mm | Sin cambio |  |  |
| 28 | Firma | Firma y sello del profesional | Sin cambio; solo si se elige la firma |  |  |
| 29 | Pie de cada página | EV-AAAA-NNNNN · Emitido el dd/mm/aaaa hh:mm · Página N | Sin cambio |  |  |

## 3. Resultado de la revisión

| Dato | Valor |
| --- | --- |
| Fecha de la revisión |  |
| Cargo de quien revisó |  |
| Frases aprobadas sin cambios |  |
| Frases con observaciones |  |

Con todas las frases aprobadas, el equipo del proyecto aplica los cambios pedidos, marca
`revisado: true` con `revisado_por` (cargo, sin nombre) y `fecha_revision`, y actualiza la fila 166.
