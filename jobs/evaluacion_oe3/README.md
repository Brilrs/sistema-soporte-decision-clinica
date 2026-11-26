# Evaluación del OE3 (RAGAS y CUE)

Diseño, métricas y decisiones: [`docs/diseno_evaluacion_oe3.md`](../../docs/diseno_evaluacion_oe3.md).
Código: `backend/app/evaluacion/`. Pruebas: `backend/tests/test_oe3_evaluacion.py` (sin base ni red)
y `backend/tests/test_oe3_ragas.py` (solo en la imagen de evaluación, donde está RAGAS).

| Carpeta | Contenido |
| --- | --- |
| `conjunto/esquema_caso.json` | Esquema de un caso |
| `conjunto/piloto/` | Piloto de 12 casos, sin revisar (`revisado: false`) |
| `conjunto/evaluacion/` | Conjunto definitivo (todavía no existe) |

## Reglas

- Solo datos sintéticos (decisiones 12 y 13). El juez recibe la consulta filtrada, la respuesta, el
  texto de los fragmentos enviados y la referencia del caso, nunca `texto_consulta`.
- **El piloto se prueba solo con el cliente falso** (opción A): `ejecutar --llm real` lo rechaza.
- El sistema se ejecuta una sola vez por carpeta de salida, congelado (sección 8 de
  `docs/cierre_sprint3.md`). El juez sí puede repetirse sobre la misma extracción.
- Las corridas con la API (`--llm real`, `--juez anthropic`) las ejecuta solo el responsable y
  exigen `--confirmo-datos-sinteticos`.

## Imagen y servicio

```bash
docker compose --profile evaluacion build evaluacion
docker compose --profile evaluacion run --rm evaluacion python -m app.evaluacion --help
```

Destino `evaluacion` de `backend/Dockerfile` con `backend/requirements-evaluacion.txt` (RAGAS 0.4.4,
`instructor>=1.10`). El código de `app/evaluacion/` está excluido del contexto principal
(`backend/.dockerignore`) y entra solo en esta imagen, por el contexto adicional `codigo_evaluacion`:
las imágenes `api` y `jobs` no cambian. El conjunto se monta en solo lectura en `/datos/conjunto` y las
salidas quedan en `data/evaluacion_oe3/` (fuera de git).

## Fases

```bash
E="docker compose --profile evaluacion run --rm evaluacion python -m app.evaluacion"
$E validar --grupo piloto --con-base             # esquema, huellas y anclajes contra la base
$E ejecutar --salida /datos/evaluacion/<corrida>  # grafo real, una vez; cliente falso por omisión
$E extraer --salida /datos/evaluacion/<corrida>   # solo lectura (cdss_generacion)
$E juzgar --salida /datos/evaluacion/<corrida> --k 3   # juez falso por omisión
$E informe --salida /datos/evaluacion/<corrida> --git <etiqueta>
$E comparar-jueces --salida /datos/evaluacion/<corrida> --modelos claude-sonnet-5-5,claude-haiku-5-5
$E ensayo --salida /datos/evaluacion/<corrida> --falso-segun-esperado   # las cuatro fases, todo falso
```

Archivos de una corrida: `manifiesto.json` (conjunto, huellas y configuración al ejecutar),
`ejecucion.jsonl`, `extraccion.jsonl`, `juez/<modelo>/llamadas.jsonl`, `resultados.jsonl` y
`configuracion.json`, `cache_juez/`, `informe_<modelo>.md` y `.json`. Si el cliente del modelo de
lenguaje o el juez son falsos, el informe lleva el rótulo «ENSAYO CON CLIENTE FALSO: los números no
tienen valor».

## Ensayo del piloto en una base de pruebas

El ensayo del 26/11/2026 corrió con el cliente y el juez falsos sobre `cdss_ensayo_oe3`, una copia de
la base de pruebas (contenedor `cdss-pruebas-bd`, con `seed_demo`) a la que se le cargaron los
fragmentos de las 4 guías de la base de desarrollo, para que coincidan con los vectores de ChromaDB,
que solo se leen. La imagen corre con las variables de `.env.test`, `CDSS_ENTORNO=pruebas` (el cliente
real no se puede crear) y las conexiones apuntando a `cdss_ensayo_oe3`, en la red de Docker del stack
(ChromaDB y `modelos`). La base de desarrollo y la base `cdss` de pruebas no cambian.

## Antes de la corrida definitiva (responsable)

1. Congelar el sistema (sección 8 de `docs/cierre_sprint3.md`) y crear `conjunto/evaluacion/` con los
   casos revisados por la coordinación CRED.
2. `validar --grupo evaluacion --con-base`: todos los anclajes deben encajar en un solo fragmento.
3. Comparar jueces sobre una extracción del cliente falso y fijar modelo, razonamiento y k.
4. `ejecutar --grupo evaluacion --llm real --confirmo-datos-sinteticos`, luego `extraer`, `juzgar`
   con `--juez anthropic` e `informe --git <etiqueta>`. La huella del informe debe salir «(igual)».
