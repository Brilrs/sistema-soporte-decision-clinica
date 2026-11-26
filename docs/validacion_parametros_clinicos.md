# Validación de los parámetros clínicos de M12

Registro de la verificación de los parámetros clínicos que usa la clasificación (puntos de corte de
hemoglobina, ajuste por altitud, vigencia del tamizaje y niveles de riesgo) y de su validación por la
coordinación CRED del Centro de Salud San Luis el 25/11/2026. Este documento no cambia ningún valor:
los valores son los de `db/init/02_catalogos.sql` y `db/init/01_esquema.sql`.

Estado al 26/11/2026: validación del CRED hecha, sin observaciones, y registrada en M12 (sección 6);
huella de control calculada (sección 7). **Falta** la huella definitiva, al congelar el sistema.

## 1. Fuentes normativas

| Norma | Tabla | Página del PDF | Uso en el sistema |
| --- | --- | --- | --- |
| NTS N.° 213-MINSA/DGIESP-2024 (aprobada por la RM 251-2024/MINSA) | Tabla 13, valores normales de hemoglobina y niveles de anemia (hasta 500 msnm) | 17 | Puntos de corte de 6 a 23 y de 24 a 59 meses |
| NTS N.° 213-MINSA/DGIESP-2024 | Tabla 1, ajuste del valor de hemoglobina según altitud | 7 | Ajuste por altitud |
| RM 429-2024/MINSA, Anexo, modificación 9 | Tabla 13 (texto vigente) | 9 | Puntos de corte |
| RM 429-2024/MINSA, Anexo, modificación 2 | Tabla 1 (texto vigente) | 4 | Ajuste por altitud, incluidos los rangos de 4500 a 4999 y de 5000 a 5500 msnm |

Las páginas de la RM 429 coinciden con las transcripciones de la base de conocimiento
(`backend/app/indexador/transcripciones/rm429/mod02_tabla01_ajuste_altitud.md` y
`mod09b_tabla13_hemoglobina.md`) y las de la NTS con el mapa
`backend/app/indexador/modificaciones/rm429_2024.yaml`.

## 2. Valores vigentes en el sistema

Leídos de `db/init/02_catalogos.sql` (puntos de corte, ajuste y vigencia) y de
`db/init/01_esquema.sql` (niveles de riesgo). Hemoglobina en g/dL a nivel del mar, con un decimal
(`NUMERIC(4,1)`); la hemoglobina ajustada se redondea a un decimal antes de clasificar.

### 2.1 Puntos de corte de hemoglobina (8 filas)

| Edad (meses) | Categoría | Hb mínima (g/dL) | Hb máxima (g/dL) |
| --- | --- | --- | --- |
| 6 a 23 | Sin anemia | 10,5 | sin límite |
| 6 a 23 | Anemia leve | 9,5 | 10,4 |
| 6 a 23 | Anemia moderada | 7,0 | 9,4 |
| 6 a 23 | Anemia severa | sin límite | 6,9 |
| 24 a 59 | Sin anemia | 11,0 | sin límite |
| 24 a 59 | Anemia leve | 10,0 | 10,9 |
| 24 a 59 | Anemia moderada | 7,0 | 9,9 |
| 24 a 59 | Anemia severa | sin límite | 6,9 |

La norma expresa la anemia severa como «< 7,0»; con un decimal equivale a un máximo de 6,9.

### 2.2 Ajuste por altitud (11 rangos)

| Altitud (msnm) | Ajuste que se resta (g/dL) |
| --- | --- |
| 0 a 499 | 0,0 |
| 500 a 999 | 0,4 |
| 1000 a 1499 | 0,8 |
| 1500 a 1999 | 1,1 |
| 2000 a 2499 | 1,4 |
| 2500 a 2999 | 1,8 |
| 3000 a 3499 | 2,1 |
| 3500 a 3999 | 2,5 |
| 4000 a 4499 | 2,9 |
| 4500 a 4999 | 3,3 |
| 5000 a 5500 | 4,0 |

La Tabla 1 empieza en 1 msnm; el sistema empieza en 0 para cubrir el nivel del mar, con el mismo
ajuste. Por encima de 5500 msnm no hay ajuste y el tamizaje no se clasifica.

### 2.3 Vigencia del tamizaje

| Parámetro | Valor | Límites admitidos |
| --- | --- | --- |
| `DIAS_VIGENCIA_TAMIZAJE` | 30 días | 1 a 365 |

### 2.4 Niveles de riesgo por clasificación

| Clasificación | Nivel de riesgo | Requiere derivación |
| --- | --- | --- |
| Sin anemia | Bajo | No |
| Anemia leve | Moderado | No |
| Anemia moderada | Alto | No |
| Anemia severa | Muy alto | Sí |

Los niveles de riesgo están en `configuracion.categoria_anemia`, que M12 no edita: solo cambian por
migración.

## 3. Verificación normativa y validación del CRED

Son dos revisiones distintas:

- **Verificación normativa (autoras del sistema).** Contraste de cada punto de corte y de cada rango
  de altitud con las tablas de la NTS 213 y de la RM 429 (sección 1). Responde a la pregunta «¿el
  valor es el de la norma?». Solo aplica a los puntos de corte y al ajuste por altitud, que tienen
  fuente normativa.
- **Validación del CRED (coordinación CRED del Centro de Salud San Luis, 25/11/2026).** Revisión, en
  la ficha de verificación, de los puntos de corte, el ajuste por altitud, la vigencia de 30 días y
  los niveles de riesgo, sin observaciones. Responde a la pregunta «¿el servicio los acepta para su
  práctica?». Para la vigencia y los niveles de riesgo es la única validación posible, porque no
  vienen de una tabla de la norma (sección 5).

La identidad de quien validó está reservada y no se registra en el repositorio.

## 4. Evidencia

| Dato | Valor |
| --- | --- |
| Archivo | `data/evidencia/Ficha de verificación de parámetros clínicos del CDSS de anemia infantil.docx` |
| SHA-256 | `7f512e51bdda14c2b3ae46734893b2399643dd57aece0f5c3b1867a880a88b5f` |
| En git | No: `data/*` está en `.gitignore` |

El hash se calculó con `sha256sum` (solo lectura). Para comprobar la copia que se conserve:

```bash
sha256sum "data/evidencia/Ficha de verificación de parámetros clínicos del CDSS de anemia infantil.docx"
```

## 5. Limitaciones

- **Menores de 6 meses fuera del alcance de la clasificación.** El sistema registra tamizajes de 0
  a 59 meses, pero solo hay puntos de corte de 6 a 59 meses: un tamizaje de 0 a 5 meses no se
  clasifica. La Tabla 13 trae valores para menores de 6 meses (sin grados de anemia); incorporarlos es
  una mejora futura (fila 34 de `docs/cambios_respecto_al_OE2.md`).
- **Residencia de los últimos 4 meses no registrada.** La modificación 9 de la RM 429 pide el lugar
  de residencia habitual de los últimos 4 meses; el sistema usa la altitud del distrito del paciente y
  no registra cambios de residencia.
- **Vigencia y niveles de riesgo son criterios de diseño.** Los 30 días y la correspondencia entre
  clasificación y riesgo vienen del diseño del sistema (OE2), no de una tabla de la norma;
  la validación del CRED los acepta como criterio operativo, no normativo.
- **La ficha es la evidencia de la validación.** El original con firma y sello del CRED está
  pendiente de entrega y se resguardará aparte, fuera del repositorio, cuando se reciba; si trae
  observaciones o cambios, se ajustará el valor, se generará una huella nueva y se repetirá la
  evaluación.
- **Cuenta de demostración.** La cuenta coord.ortiz es ficticia, como las demás cuentas de
  demostración; el registro en M12 lo ejecutó el equipo del proyecto sobre la validación de la ficha
  del CRED.
- **Documento asociado en la base.** M12 no envía `id_documento`, así que cada versión nueva conserva
  el documento de la anterior: los puntos de corte y los rangos de 0 a 4499 msnm siguen asociados a
  la guía OMS 2024 y los dos últimos rangos a la RM 429. La norma aplicada queda en la referencia de
  cada versión (sección 6).

## 6. Registro en M12

Registrado el 26/11/2026 (UTC). Se hizo con «Editar», marcando cada valor como verificado (en la
vigencia, «Validado por el CRED (criterio operativo, no normativo)») y guardando sin cambiar ningún
valor; la columna «Quién» muestra la cuenta de demostración coord.ortiz («Dra. Carmen Ortiz»).

El registro en M12 lo ejecutó el equipo del proyecto con la cuenta de demostración coord.ortiz, sobre la validación de la ficha del CRED.

El motivo admite de 10 a 500 caracteres y la referencia hasta 200; ninguno llevó nombres reales de
personas.

| Grupo | Motivo | Referencia |
| --- | --- | --- |
| Puntos de corte | Validado por la coordinación CRED del Centro de Salud de San Luis según ficha del 25/11/2026. Valores contrastados con la NTS 213 y la RM 429-2024. | NTS 213-MINSA/DGIESP-2024, Tabla 13, p. 17; RM 429-2024/MINSA, modificación 9, Tabla 13, p. 9 |
| Ajuste por altitud | Validado por la coordinación CRED del Centro de Salud de San Luis según ficha del 25/11/2026. Valores contrastados con la NTS 213 y la RM 429-2024. | NTS 213-MINSA/DGIESP-2024, Tabla 1, p. 7; RM 429-2024/MINSA, modificación 2, Tabla 1, p. 4 |
| Vigencia del tamizaje | Criterio operativo validado por la coordinación CRED del Centro de Salud de San Luis según ficha del 25/11/2026. | Criterio operativo del CRED; la norma no fija este plazo |

Los niveles de riesgo no se registran en M12 (sección 2.4): su validación queda en este documento y en
la ficha.

## 7. Huella de la configuración

Huella de control, calculada después del registro en M12 y antes del congelamiento; no es la
definitiva, que se calcula al congelar el sistema para el OE3 (`docs/cierre_sprint3.md`, paso 5):

```bash
docker compose exec backend python -m app.scripts.huella_configuracion --json
```

| Dato | Valor |
| --- | --- |
| Fecha | 2026-11-26 02:59:12 UTC (25/11/2026, 21:59 hora de Perú) |
| Etiqueta de git | Se asigna al congelar el sistema |
| Huella (SHA-256) | `a3e653743e5ec2ab411dc0680e596a55d99312c3059c70eb172fcb8f650f1449` |

| Componente | Elementos | SHA-256 |
| --- | --- | --- |
| `puntos_corte` | 8 | `28c36bd21419e7398c610b360a4228eacd95ac0bac4ccbb64ccbbba68941acaf` |
| `ajuste_altitud` | 11 | `d583324e0be8372686c5011d2b6b96683d2f36ae40f4795d9e1f8c66fb8a2c94` |
| `categorias` | 4 | `02624915bfff4226246a5189df147c0f7606baf0e24e185debd088cff445f762` |
| `parametros_sistema` | 26 | `1f132b7e60f3e2823170f701f66b7f4d46152e18b329d4ca17883554e83c440b` |
| `indexacion` | 4 | `ac698ac4280649229009a4802e2bf88d5a320760062941cdc9d2c4d12ad7f5c1` |
| `version_prompt` (v1.1) | 1 | `ca7948f56d353a9eac81c773591c36f6a4eb6532979a117a5e162be730a3ed23` |

En `indexacion`, las cuatro guías (NTS 213, RM 429, OMS 2016 y OMS 2024) tienen la versión de
indexación 1.

Esta huella es un punto de control. La definitiva se calcula y se registra al congelar el sistema; si algún valor cambia después, se genera una huella nueva y se repite la evaluación.
