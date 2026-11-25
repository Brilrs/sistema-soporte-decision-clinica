# Mediciones del Sprint 3: la VM de Azure (parte L)

Mediciones de la consulta de punta a punta en la máquina virtual de Azure, el 25/11/2026. Las del
equipo de desarrollo y del perfil B2ms simulado están en `docs/mediciones_sprint2.md`. Las cifras
de las tablas salen de los archivos de `data/mediciones` (sección 8). Lo que se vio durante la sesión
y no está en esos archivos va marcado como **observación en sesión**.

## 1. Objetivo y entorno

Objetivo: medir el tiempo de respuesta, los estados, el costo y la memoria del sistema desplegado en
Azure, con el modelo de lenguaje real, y comprobar si el límite de memoria de `modelos` alcanza.

| Elemento | Valor |
| --- | --- |
| Máquina | VM Standard_B2ms (2 vCPU, 8 GiB, familia B con créditos de CPU), Ubuntu 24.04, región Chile Central |
| Disco | 64 GB StandardSSD_LRS, más 2 GB de swap (`vm.swappiness` 10) |
| Contenedores | Imágenes de producción: `docker-compose.yml` con `docker-compose.prod.yml` (límites de memoria para 8 GiB, `CDSS_ENTORNO=produccion`) |
| Modelos locales | bge-m3 y bge-reranker-v2-m3; reranker en ONNX int8, exportado en la VM con `exportar-onnx` |
| Base de conocimiento | Las 4 guías indexadas con el mismo manifiesto que en desarrollo (`fuentes_iniciales.yaml`). Colección `guias_clinicas` con 202 vectores (183 vigentes) |
| Modelo de lenguaje | `claude-sonnet-5-5` por la API de Anthropic, prompt v1.1 |
| Límites de la consulta | `Limites(reranker=1, llm=4)`, 2 núcleos visibles (del informe) |

## 2. Método

- **Script:** `app.scripts.medir_consulta` (paso 21 de `docs/despliegue_azure.md`) en un contenedor
  `backend` creado con `docker compose run`. `muestrear_memoria.py` tomó en paralelo `docker stats`
  de todos los contenedores (74 y 72 muestras en unos 2,5 minutos).
- **Casos:** los 12 de `backend/app/scripts/casos_e2e.yaml` (9 VERIFICADA, 1 EVIDENCIA_INSUFICIENTE,
  1 DATOS_FALTANTES y 1 FUERA_DE_DOMINIO esperados), con pacientes ficticios de `seed_demo`.
- **Modelo de lenguaje real** (`--llm real --confirmo-datos-sinteticos`): solo datos sintéticos.
- **Fecha de referencia fija:** los casos traen su `fecha_referencia`, así que la vigencia del
  tamizaje no depende del día en que se mide.
- **Una consulta a la vez** (`--concurrentes 1`) y **una repetición** (`--repeticiones 1`).
- **Calentamiento:** el del propio script (modelos, ChromaDB, dominio, BM25 y grafo) y, antes, una
  consulta de calentamiento con el caso `a` que no se reporta.
- **Dos corridas:** con `modelos` limitado a 3072 MiB y, después de subir el límite, a 3584 MiB
  (fila 162 de `docs/cambios_respecto_al_OE2.md`). Antes de la segunda se recreó `modelos`.

**Observación en sesión (no está en los archivos):** la primera consulta después de encender la VM
tardó 38,5 s, y la primera después de reiniciar solo el contenedor `modelos`, 18,8 s. En régimen,
las consultas tardaron de unos 11 a 14 s. Por eso se calienta antes de medir y antes de abrir el
sistema a los usuarios.

## 3. Resultados de latencia

Tiempos en milisegundos, vistos por el cliente del servicio (de la solicitud al evento `fin`).

### Corrida con `modelos` en 3072 MiB

| Caso | Esperado | Obtenido | Total (ms) |
| --- | --- | --- | --- |
| a | VERIFICADA | VERIFICADA | 13093 |
| b | VERIFICADA | VERIFICADA | 11563 |
| c | VERIFICADA | VERIFICADA | 12024 |
| d | VERIFICADA | VERIFICADA | 13385 |
| e | VERIFICADA | VERIFICADA | 13169 |
| f | VERIFICADA | VERIFICADA | 13305 |
| g | DATOS_FALTANTES | DATOS_FALTANTES | 24 |
| h | FUERA_DE_DOMINIO | FUERA_DE_DOMINIO | 192 |
| i | VERIFICADA | VERIFICADA | 11416 |
| j | EVIDENCIA_INSUFICIENTE | EVIDENCIA_INSUFICIENTE | 18542 |
| k | VERIFICADA | VERIFICADA | 12263 |
| l | VERIFICADA | VERIFICADA | 11907 |

### Corrida con `modelos` en 3584 MiB

| Caso | Esperado | Obtenido | Total (ms) |
| --- | --- | --- | --- |
| a | VERIFICADA | VERIFICADA | 12817 |
| b | VERIFICADA | VERIFICADA | 11459 |
| c | VERIFICADA | VERIFICADA | 12113 |
| d | VERIFICADA | VERIFICADA | 11842 |
| e | VERIFICADA | VERIFICADA | 13794 |
| f | VERIFICADA | VERIFICADA | 11918 |
| g | DATOS_FALTANTES | DATOS_FALTANTES | 23 |
| h | FUERA_DE_DOMINIO | FUERA_DE_DOMINIO | 190 |
| i | VERIFICADA | VERIFICADA | 11912 |
| j | EVIDENCIA_INSUFICIENTE | EVIDENCIA_INSUFICIENTE | 19307 |
| k | VERIFICADA | **EVIDENCIA_INSUFICIENTE** | 18443 |
| l | VERIFICADA | VERIFICADA | 11854 |

### Resumen de las dos corridas

| Medida | 3072 MiB | 3584 MiB |
| --- | --- | --- |
| Estados como se esperaba | 12 de 12 | 11 de 12 (caso k, sección 6) |
| Total p50 / p90 / máximo | 12024 / 13385 / 18542 ms | 11912 / 18443 / 19307 ms |
| Verificadas p50 / p90 | 12263 / 13385 ms (9 consultas) | 11912 / 13794 ms (8 consultas) |
| Primer evento p50 / p90 | 186 / 217 ms | 191 / 250 ms |
| Recuperar, mediana | 5051 ms | 5067 ms |
| Generar, mediana | 6721 ms | 6603 ms |
| Intentos enviados al modelo | 11 | 12 |
| Costo | 0,23956 USD | 0,26576 USD |
| Costo por consulta con llamada al modelo (10 de 12) | 0,0240 USD | 0,0266 USD |
| Tokens de entrada / salida | 72801 / 9394 | 79462 / 10682 |
| Tokens de razonamiento | 0 | 0 |
| Espera máxima en cola | 0 ms | 0 ms |

- Los casos g y h no llaman al modelo (terminan en la validación).
- El caso j hace dos intentos en las dos corridas: el segundo con la búsqueda ampliada, por eso
  recuperar tarda 11061 y 11979 ms en ese caso.
- La segunda corrida tiene un intento más y unos 0,026 USD más por el segundo intento del caso k.

## 4. Memoria

| Medida | 3072 MiB | 3584 MiB |
| --- | --- | --- |
| Límite de `modelos` | 3072 MiB | 3584 MiB |
| Pico de `modelos` en el muestreo | 3072,0 MiB (igual al límite) | 2264,1 MiB |
| `memory.events` `max` (veces que llegó al límite) | 2420 | 0 |
| `memory.events` `oom_kill` | 0 | 0 |
| `anon` al final de la corrida | 0,80 GiB (861155328 bytes) | 1,51 GiB (1618296832 bytes) |
| `file` al final de la corrida | 2,14 GiB (2301616128 bytes) | 1,15 GiB (1234137088 bytes) |
| `file_mapped` al final de la corrida | 1,41 GiB (1518669824 bytes) | 0,39 GiB (421523456 bytes) |
| Pico del servicio `backend` | 229,9 MiB de 512 | 214,0 MiB de 512 |
| Pico del contenedor de la medición (`backend-run`) | 172,4 MiB de 512 | 167,0 MiB de 512 |
| Picos de `db`, `chromadb`, `indexador` y `nginx` | 88,4; 110,7; 89,8 y 3,8 MiB | 86,6; 109,7; 91,4 y 3,5 MiB |

`memory.events` cuenta desde que se creó el contenedor: el `max` de 3072 MiB (2420) acumula también
el tiempo anterior a la medición, y el de 3584 MiB empieza en 0 porque `modelos` se recreó con el
límite nuevo.

Lectura, con prudencia:
- Con 3072 MiB, `modelos` quedó pegado al límite durante toda la medición y llegó al tope 2420
  veces, sin que el kernel lo matara (`oom_kill` 0) ni se reiniciara. La mayor parte de lo que
  ocupaba eran archivos de los modelos en caché (`file` 2,14 GiB), que el kernel puede expulsar y
  volver a leer del disco. No fue falta de memoria, pero sí trabajo extra de expulsar y releer.
- Con 3584 MiB, el pico fue de 2264 MiB y el contador `max` quedó en 0: no volvió a tocar el límite.
  Por eso se subió el límite (fila 162 de `docs/cambios_respecto_al_OE2.md`).
- `anon` fue mayor con 3584 MiB (1,51 frente a 0,80 GiB). Con estos datos no se puede saber por qué:
  puede deberse a la presión del límite en la primera corrida (que obliga a liberar memoria) o al
  momento de la lectura. No se leyó el uso de swap del contenedor.
- La latencia de las consultas verificadas casi no cambió entre las dos corridas (recuperar 5051 y
  5067 ms de mediana). Con 12 consultas no se ve un efecto del límite de memoria sobre el tiempo.

## 5. CPU

| Medida | 3072 MiB | 3584 MiB |
| --- | --- | --- |
| Pico de CPU de `modelos` | 199,5 % | 200,33 % |
| Pico de CPU del contenedor de la medición | 108,73 % | 109,1 % |

`modelos` llegó al 200 % (los 2 núcleos de la VM) durante la recuperación. Ese nodo (unos 5 s de
mediana) depende del cómputo del reranker, no de la memoria: con más memoria, la mediana de
recuperar quedó igual.

**Observación en sesión (no está en los archivos):** en las métricas de Azure de la VM, los créditos
de CPU de la B2ms («CPU Credits Remaining») subieron de 60,6 a 158,8 entre las 17:30 y las 21:15 UTC,
lapso que incluye la primera medición. No se agotaron, así que no hubo estrangulamiento de la CPU. La
segunda medición (hacia las 21:50 UTC) no tiene lectura de créditos.

## 6. Caso k (consulta en inglés)

El caso k es una consulta en inglés que debe responderse en inglés (VERIFICADA esperada).

- **Corrida de 3072 MiB:** VERIFICADA en 12263 ms, con un intento.
- **Corrida de 3584 MiB:** EVIDENCIA_INSUFICIENTE en 18443 ms. Los eventos muestran dos generaciones
  con la misma recuperación (un solo `recuperar`, de 4972 ms y relevancia máxima 0,891): `verificar`
  del intento 1 dio REINTENTO (siguiente: REGENERAR) y `verificar` del intento 2 dio
  EVIDENCIA_INSUFICIENTE. En el registro de los dos intentos, `valida_citas` es falso y
  `valida_consistencia` y `valida_evidencia` son verdaderos; el registro no dice qué cita falló ni
  por qué, así que aquí no se interpreta más.
- **Observación en sesión (no está en `data/mediciones`; se corrió con la salida en `/tmp` del
  contenedor):** una repetición posterior de 3 consultas del caso k dio 3 de 3 VERIFICADA, con 4
  intentos de generación; una de ellas (18430 ms) necesitó un reintento.

| Consultas del caso k | Intentos de generación | Rechazados por el verificador | VERIFICADA | EVIDENCIA_INSUFICIENTE |
| --- | --- | --- | --- | --- |
| Corrida de 3072 MiB (1) | 1 | 0 | 1 | 0 |
| Corrida de 3584 MiB (1) | 2 | 2 | 0 | 1 |
| Repetición en sesión (3) | 4 | 1 | 3 | 0 |
| **Total (5)** | **7** | **3** | **4** | **1** |

Conclusión: la variación del caso k viene de la generación del modelo de lenguaje y del
verificador, no de la memoria (la recuperación fue la misma y `modelos` no tocó el límite en esa
corrida). Debe medirse con más repeticiones en la evaluación del OE3 (OE3-A).

## 7. Lectura para la tesis

- **RNF3** (propuesta de la fila 61 de `docs/cambios_respecto_al_OE2.md`: p90 de 15 s o menos con
  la respuesta completa en el flujo normal): sobre las consultas verificadas **se cumple en las dos
  corridas**, con p90 de 13,4 s (3072 MiB) y 13,8 s (3584 MiB). El primer evento llega en menos de
  1 s (p90 de 0,22 y 0,25 s).
- Las consultas con un segundo intento tardan de 18 a 19 s: el caso j (18,5 y 19,3 s) repite la
  recuperación con la búsqueda ampliada y la generación; el caso k de la segunda corrida (18,4 s)
  repite solo la generación. Ambos quedan dentro de los 25 s propuestos para el flujo con reintento.
- Con 12 consultas, un solo caso con reintento mueve el p90 del total: 13,4 s en la primera corrida
  y 18,4 s en la segunda, por el caso k. La cifra formal del RNF3 debe salir de la evaluación OE3-A,
  con más consultas.
- Frente al equipo de desarrollo (perfil normal, 13/11/2026: p90 de las verificadas 12,54 s) la VM
  es algo más lenta, sobre todo en recuperar (unos 5,1 s frente a 3,9 s). Frente al perfil B2ms
  simulado (18,92 s) queda mejor, porque allí el p90 lo fijó una llamada a la API de 13,5 s.
- **Limitaciones:** una sola VM, un solo usuario a la vez (sin concurrencia), 12 casos y una
  repetición por corrida. Las observaciones en sesión (primera consulta, créditos de CPU y la
  repetición del caso k) no tienen archivo de respaldo.

## 8. Evidencia

Archivos en `data/mediciones/`. No se versionan en git (la carpeta `data/` está en `.gitignore`,
salvo `data/README.md`); se copiaron desde la VM con `scp` (paso 21 de `docs/despliegue_azure.md`).

| Archivo | Contenido |
| --- | --- |
| `d_consulta_real_azure_chilecentral.json` | Corrida con 3072 MiB: metadatos, resumen y cada consulta con eventos, tiempos por nodo, intentos, tokens y costo |
| `d_consulta_real_azure_chilecentral.md` | El mismo informe de 3072 MiB en Markdown |
| `l_memoria_azure_chilecentral.json` | Muestreo de `docker stats` durante la corrida de 3072 MiB: pico de memoria y de CPU por contenedor |
| `l_memoria_cgroup_modelos_3072.txt` | Contadores del cgroup de `modelos` al final de la corrida de 3072 MiB (`memory.stat` y `memory.events`) |
| `d_consulta_real_azure_chilecentral_3584.json` | Corrida con 3584 MiB, con la misma estructura |
| `d_consulta_real_azure_chilecentral_3584.md` | El mismo informe de 3584 MiB en Markdown |
| `l_memoria_azure_chilecentral_3584.json` | Muestreo de `docker stats` durante la corrida de 3584 MiB |
| `l_memoria_cgroup_modelos_3584.txt` | Contadores del cgroup de `modelos` al final de la corrida de 3584 MiB |
