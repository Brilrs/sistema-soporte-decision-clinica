# Auditoría visual de la interfaz

Script `auditar.mjs` (pendiente P13 del Sprint 2). Recorre las pantallas con Chrome sin cabeza y
mide, en cada ancho:

- **Desplazamiento horizontal de la página.**
- **Elementos que se salen de su contenedor:** su padre no recorta ni desplaza, o se salen de la página.
- **Elementos absolutos que escapan de su contenedor con desplazamiento** (P13): un elemento
  `position: absolute` cuyo bloque contenedor está fuera del antepasado con `overflow` no queda
  recortado por él y ensancha la página aunque esté oculto con `clip`. Es el caso de los textos
  solo para lectores de M08 (fila 84 de `docs/cambios_respecto_al_OE2.md`), que la medición de
  desbordes no veía. Lo marca aunque la página todavía no se desplace.
- **Accesibilidad con axe-core** (WCAG 2.0 y 2.1, niveles A y AA), con `--axe`.
- **Aviso de áreas táctiles** de menos de 44 px por debajo de 800 px, solo en el alcance donde
  `src/estilos.test.ts` fija esa regla (menú móvil, M11, ventanas, M09, las acciones de M08 y de
  las listas de consultas y M13). Es un aviso, no una falla.

Está fuera del CI a propósito: necesita el stack levantado, Chrome instalado y unos 7 minutos.

## Antes de ejecutar

1. Stack levantado con los datos de `seed_demo` (`docker compose up -d` y
   `docker compose exec backend python -m app.scripts.seed_demo`). El script lee
   `SEED_CONTRASENA` de `.env` y no la imprime.
2. Dependencias de esta carpeta, una vez: `npm --prefix auditoria ci` desde `frontend/`. Son
   `playwright-core` (sin descarga de navegadores) y `axe-core`, fuera de las dependencias del
   frontend para que el CI no las instale.
3. Compilación nueva servida en el puerto 4173. **Antes, compruebe que no quede un `vite preview`
   viejo en ese puerto:** serviría la compilación anterior y la auditoría mediría otra versión.

   ```bash
   npm run build && npx vite preview --port 4173 --strictPort
   ```

## Uso

Desde `frontend/`:

```bash
npm run auditoria                                # desbordes en 10 anchos (320 a 1920 px)
npm run auditoria -- --axe --capturas            # más axe a 390 y 1280 px y capturas de lo que falle
npm run auditoria -- --pantallas=m08_evaluaciones,m11_lista --anchos=320,390
```

| Opción | Efecto |
| --- | --- |
| `--etiqueta=nombre` | Carpeta de resultados (por omisión, la fecha y hora) |
| `--pantallas=a,b` | Solo esas pantallas. Un nombre desconocido muestra la lista disponible |
| `--anchos=320,1280` | Anchos de los desbordes (por omisión: 320, 360, 390, 600, 768, 800, 1000, 1024, 1280 y 1920) |
| `--axe` | Ejecuta axe-core |
| `--axe-anchos=390,1280` | Anchos de axe (por omisión, 390 y 1280) |
| `--capturas` | Captura de página completa de cada vista con problemas (`--capturas=todas`: de todas) |
| `--css-extra=archivo.css` | Inyecta una hoja de estilos en cada página, sin tocar el código. Sirve para reintroducir un error a propósito y comprobar que la auditoría lo detecta |

Variables opcionales: `CDSS_API` (por omisión `http://localhost:8080`), `CDSS_APP`
(`http://localhost:4173`) y `CHROME_RUTA`, si Chrome no está en su ubicación habitual.

## Datos

- **Lecturas:** van al backend real, con `enf.rojas` y `admin.cdss`.
- **Consultas (M04 a M07, decisión):** se simulan con los fixtures del contrato (`src/__fixtures__`).
- **M11:** se simula con `src/pruebas/conocimiento`, más tres guías ficticias en estados que la
  base real no tiene.
- **Textos largos:** se agregan consultas y notas largas, con una palabra sin espacios, para
  forzar los cortes.
- **M09 y «Reportes» (Sprint 3, parte C2):** la consulta, la vista previa y la lista de reportes
  salen de los fixtures de la parte C1 (`reporte_vista_previa_*.json` y `reportes_lista.json`). Hay
  una consulta real con decisión y el reporte ya generado (`m09_expediente_real`), una de prueba
  (`m09_expediente_prueba`), el destino del cuidador con el aviso de revisión (`m09_cuidador`), el
  error de la vista previa (`m09_vista_error`) y la lista con «Exportar» (`reportes_lista`). El
  POST del reporte se responde aquí con bytes ficticios y las cabeceras del contrato.
- **M13 (Sprint 3, parte D2):** indicadores, lista y detalle salen de los fixtures de la parte D1
  (`auditoria_*.json`), con 45 consultas en total, un modelo de nombre largo y un detalle con la
  solicitud de líneas largas (una palabra sin espacios) y un intento bloqueado. Pantallas
  `m13_lista`, `m13_pruebas` (interruptor activo), `m13_detalle` y `m13_error`.
- **M12 (Sprint 3, parte E2):** lectura y respuestas de los PUT con los fixtures de E1a y E1b
  (`parametros*.json` y `parametros_put_*.json`), con el token de `coord.ortiz` (o de `admin.cdss` en
  `m12_admin`). Pantallas `m12_admin` (solo lectura), `m12_edicion` (puntos de corte en edición),
  `m12_advertencias` (ventana con CONFIRMO), `m12_validacion` (errores) y `m12_evaluacion`. El
  historial lleva 45 versiones y una fila con motivo y referencia largos.
- **Escrituras:** ninguna llega al backend. El script las responde con 409, salvo el POST del
  reporte de M09.

## Resultados

Quedan en `auditoria/resultados/<etiqueta>/`, ignorada por git:
- `desbordes.json`;
- `axe.json`;
- `tactiles.json`, si hay avisos;
- las capturas.

La consola muestra una tabla por pantalla y ancho. Cada celda dice `ok`, o los píxeles de
desplazamiento de la página, los elementos que se salen y los absolutos que escapan. Luego lista
cada problema.

El código de salida es 1 si hay algún problema (desborde, elemento que escapa, infracción de axe o
error al preparar una pantalla) y 0 si no.

## Agregar una pantalla

Agregue una entrada a `PANTALLAS` en `auditar.mjs`, con su ruta y el texto que hay que esperar.
Si la pantalla depende de datos, simúlelos en `simular()`. Si hay que abrir una ventana o pulsar
algo antes de medir, agréguelo en `preparar()`.
