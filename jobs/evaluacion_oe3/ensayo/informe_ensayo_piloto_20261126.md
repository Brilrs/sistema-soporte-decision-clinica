# ENSAYO CON CLIENTE FALSO: los números no tienen valor

> **ENSAYO CON CLIENTE FALSO: los números no tienen valor.** Este informe prueba el job de punta a punta con el cliente falso del modelo de lenguaje y el juez falso. No es una medición del sistema y no se cita en la tesis.

# Informe de la evaluación del OE3 (piloto)

Casos: 12. Juez: `juez-falso`, k = 3. Huella del conjunto: `88c9c5da54c3bfc85fbdc666533826fc26b8005cba23e150f531480ea3232651`.

## Resultados principales

| Indicador | n | Valor | IC 95 % | Método |
| --- | --- | --- | --- | --- |
| Estado igual al esperado | 12 | 100.0 % | 75.8 % a 100.0 % | Wilson |
| Éxito de recuperación | 10 | 90.0 % | 59.6 % a 98.2 % | Wilson |
| Respuesta correcta | 11 | 0.0 % | 0.0 % a 25.9 % | Wilson |
| CUE del OE2 (B, cifra principal) | 11 | 0.164 | 0.000 a 0.327 | bootstrap |
| CUE variante A (todas las afirmaciones) | 11 | 0.164 | 0.000 a 0.327 | bootstrap |
| CUE sin juez (citados / enviados) | 11 | 0.182 | 0.145 a 0.200 | bootstrap |
| Adherencia (juez, umbral 0,7) | 11 | 0.090 | 0.000 a 0.180 | bootstrap |
| Relevancia del contexto (RAGAS) | 11 | 0.250 | 0.136 a 0.364 | bootstrap |
| Faithfulness (RAGAS) | 11 | 0.500 | 0.227 a 0.727 | bootstrap |
| Context Precision (RAGAS) | 10 | 0.817 | 0.710 a 0.912 | bootstrap |
| Context Recall (RAGAS) | 10 | 0.450 | 0.250 a 0.650 | bootstrap |
| Cobertura de criterios obligatorios | 10 | 0.950 | 0.850 a 1.000 | bootstrap |

Las proporciones de recuperación y corrección cuentan solo los casos con generación (VERIFICADA o EVIDENCIA_INSUFICIENTE); el éxito de recuperación, además, solo los casos con criterios. Consultas con generación y sin fragmentos enviados (sin CUE): 0. Éxitos que dependen de una equivalencia pendiente de la ficha del CRED: 0. Casos con el criterio entre los candidatos pero no entre los enviados: 1.

## Cuadrantes (RAG-X) y categoría propia

| Categoría | Casos |
| --- | --- |
| uso_efectivo | 0 |
| ceguera_de_informacion | 9 |
| acierto_por_suerte_o_alucinacion | 0 |
| rechazo_correcto | 2 |
| incorrecta_con_contexto_fallido | 0 |
| no_aplica | 1 |
| sin_juicio | 0 |

Los cuatro primeros son los cuadrantes del artículo RAG-X. `incorrecta_con_contexto_fallido` es una categoría propia del proyecto (recuperación fallida, respuesta incorrecta y adherencia de 0,7 o más), que el artículo no define. `no_aplica`: sin generación.

## Estabilidad del juez (desviación media entre repeticiones)

| Métrica | Desviación media |
| --- | --- |
| CUE del OE2 (B, cifra principal) | 0.000 |
| Adherencia (juez, umbral 0,7) | 0.000 |
| Relevancia del contexto (RAGAS) | 0.000 |
| Faithfulness (RAGAS) | 0.000 |
| Context Precision (RAGAS) | 0.000 |
| Context Recall (RAGAS) | 0.000 |

## Desglose por tipo de consulta

| Grupo | n | Estado igual | Éxito de recuperación | Correcta | CUE B | Adherencia |
| --- | --- | --- | --- | --- | --- | --- |
| altitud | 3 | 100.0 % | 100.0 % | 0.0 % | 0.200 | 0.110 |
| anemia_leve | 2 | 100.0 % | 100.0 % | 0.0 % | 0.000 | 0.000 |
| anemia_moderada | 3 | 100.0 % | 100.0 % | 0.0 % | 0.000 | 0.000 |
| anemia_severa | 3 | 100.0 % | 100.0 % | 0.0 % | 0.600 | 0.330 |
| calendario_hb | 1 | 100.0 % | 100.0 % | 0.0 % | 0.000 | 0.000 |
| control_tratamiento | 4 | 100.0 % | 100.0 % | 0.0 % | 0.300 | 0.165 |
| derivacion | 3 | 100.0 % | 100.0 % | 0.0 % | 0.600 | 0.330 |
| evidencia_insuficiente | 1 | 100.0 % |  | 0.0 % | 0.000 | 0.000 |
| fragmento_en_ingles | 2 | 100.0 % | 100.0 % | 0.0 % | 0.000 | 0.000 |
| fuera_de_dominio | 1 | 100.0 % |  |  |  |  |
| sin_anemia | 3 | 100.0 % | 66.7 % | 0.0 % | 0.000 | 0.000 |
| suplementacion_preventiva | 3 | 100.0 % | 66.7 % | 0.0 % | 0.000 | 0.000 |
| tratamiento | 6 | 100.0 % | 100.0 % | 0.0 % | 0.200 | 0.110 |

## Desglose por origen

| Grupo | n | Estado igual | Éxito de recuperación | Correcta | CUE B | Adherencia |
| --- | --- | --- | --- | --- | --- | --- |
| desarrollo_reutilizado | 8 | 100.0 % | 100.0 % | 0.0 % | 0.086 | 0.047 |
| nuevo | 4 | 100.0 % | 75.0 % | 0.0 % | 0.300 | 0.165 |

## Desglose por idioma de los fragmentos

| Grupo | n | Estado igual | Éxito de recuperación | Correcta | CUE B | Adherencia |
| --- | --- | --- | --- | --- | --- | --- |
| con fragmento en inglés | 3 | 100.0 % | 100.0 % | 0.0 % | 0.000 | 0.000 |
| sin fragmento en inglés | 9 | 100.0 % | 85.7 % | 0.0 % | 0.225 | 0.124 |

## Desglose por cuadrante

| Grupo | n | Estado igual | Éxito de recuperación | Correcta | CUE B | Adherencia |
| --- | --- | --- | --- | --- | --- | --- |
| ceguera_de_informacion | 9 | 100.0 % | 100.0 % | 0.0 % | 0.200 | 0.110 |
| no_aplica | 1 | 100.0 % |  |  |  |  |
| rechazo_correcto | 2 | 100.0 % | 0.0 % | 0.0 % | 0.000 | 0.000 |

## Por caso

| Caso | Estado | Esperado | Clasificación | Enviados | Recuperación | Cobertura | CUE B | CUE citas | Adherencia | Correcta | Cuadrante |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| OE3-P01 | VERIFICADA | VERIFICADA | SIN_ANEMIA | 5 | sí | 100.0 % | 0.000 | 0.200 | 0.000 | no | ceguera_de_informacion |
| OE3-P02 | VERIFICADA | VERIFICADA | ANEMIA_LEVE | 5 | sí | 100.0 % | 0.000 | 0.200 | 0.000 | no | ceguera_de_informacion |
| OE3-P03 | VERIFICADA | VERIFICADA | ANEMIA_MODERADA | 5 | sí | 100.0 % | 0.000 | 0.200 | 0.000 | no | ceguera_de_informacion |
| OE3-P04 | VERIFICADA | VERIFICADA | ANEMIA_MODERADA | 5 | sí | 100.0 % | 0.000 | 0.200 | 0.000 | no | ceguera_de_informacion |
| OE3-P05 | VERIFICADA | VERIFICADA | ANEMIA_SEVERA | 5 | sí | 100.0 % | 0.600 | 0.200 | 0.330 | no | ceguera_de_informacion |
| OE3-P06 | VERIFICADA | VERIFICADA | ANEMIA_SEVERA | 5 | sí | 100.0 % | 0.600 | 0.200 | 0.330 | no | ceguera_de_informacion |
| OE3-P07 | EVIDENCIA_INSUFICIENTE | EVIDENCIA_INSUFICIENTE | ANEMIA_MODERADA | 5 | no |  | 0.000 | 0.000 | 0.000 | no | rechazo_correcto |
| OE3-P08 | FUERA_DE_DOMINIO | FUERA_DE_DOMINIO | SIN_ANEMIA | 0 | no |  |  |  |  | sí | no_aplica |
| OE3-P09 | VERIFICADA | VERIFICADA | SIN_ANEMIA | 5 | sí | 100.0 % | 0.000 | 0.200 | 0.000 | no | ceguera_de_informacion |
| OE3-P10 | VERIFICADA | VERIFICADA | ANEMIA_LEVE | 5 | sí | 100.0 % | 0.000 | 0.200 | 0.000 | no | ceguera_de_informacion |
| OE3-P11 | VERIFICADA | VERIFICADA | SIN_ANEMIA | 5 | no | 50.0 % | 0.000 | 0.200 | 0.000 | no | rechazo_correcto |
| OE3-P12 | VERIFICADA | VERIFICADA | ANEMIA_SEVERA | 5 | sí | 100.0 % | 0.600 | 0.200 | 0.330 | no | ceguera_de_informacion |

## Costos

| Componente | Llamadas o intentos | Tokens de entrada | Tokens de salida | Costo (USD) |
| --- | --- | --- | --- | --- |
| Sistema (modelo-falso) | 12 | 14400 | 1483 | 0.04363 (simulado: cliente falso) |
| Juez (juez-falso; 0 desde caché, 0 fallidas) | 378 | 641436 | 9687 | 0.0 |

## Reproducibilidad

- Etiqueta o commit de git: `dc5b5de+cambios-sin-commit`
- Huella de la configuración al ejecutar: `3cc378e73c38fc6d0ddbc64951be255fdea313e10fa19c8f9b03c67008dd3c49`
- Huella de la configuración al informar: `3cc378e73c38fc6d0ddbc64951be255fdea313e10fa19c8f9b03c67008dd3c49` (igual)
- Conjunto: `piloto`, 12 casos, SHA-256 `88c9c5da54c3bfc85fbdc666533826fc26b8005cba23e150f531480ea3232651`; esquema `6dcf90c4dbbd4eb534b980379fa17bf2952d01d0ac23bce0ce19d95ca0c5d2fd`
- Cliente del modelo de lenguaje: `falso`
- Juez: `juez-falso`, razonamiento `None`, esfuerzo `None`, máximo 4000 tokens, sin temperatura, k = 3
- Prompts propios (versión 1): sistema_afirmaciones `f1daad51486a`, sistema_adherencia `2f68218c0e98`, sistema_ragas `c0635c7f37ae`, esquema_afirmaciones `18671ee261f1`, esquema_adherencia `dc2d39e30700`
- RAGAS: 0.4.4; telemetría apagada: True
- Paquetes: 128 en `pip freeze` (lista completa en el JSON)
- Bootstrap: 10000 remuestreos, semilla 20261126
- Generado: 2026-11-26 20:37:42
