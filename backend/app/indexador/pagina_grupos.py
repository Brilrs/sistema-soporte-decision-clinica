"""Página HTML local (data/mediciones/grupos_etarios.html) para revisar el grupo etario
que el indexador asigna a cada fragmento vigente. Cada fila muestra el documento y sus
páginas, la ruta completa de secciones, los primeros caracteres del texto (con botón
«Ver completo»), el rango, la población, el origen (título, texto o corrección manual),
el motivo si el rango es dudoso y, para los documentos con prefijo_imagen en el
manifiesto (NTS y RM 429), la imagen de cada página al lado, como en verificacion.html.
Los dudosos van primero y un filtro muestra un solo documento. Cada fragmento tiene una
casilla «Rango correcto» y un campo para el rango que corresponde; las marcas se guardan
en el navegador y el botón copia un resumen para pasar las correcciones a
grupos_etarios.yaml (sección manuales)."""
import html
from datetime import date
from pathlib import Path

from app.indexador.grupos_etarios import motivo_dudoso
from app.indexador.pagina_verificacion import ESTILO, SCRIPT

LARGO_INICIO = 400
ESTILO_GRUPOS = ESTILO + """
.grupo { display: flex; flex-wrap: wrap; gap: 8px; margin: 6px 0 10px; }
.etiqueta { font-size: 13px; padding: 2px 8px; border-radius: 10px; border: 1px solid var(--borde); }
.etiqueta.dudoso { border-color: var(--dif); color: var(--dif); font-weight: 600; }
.ruta { font-size: 13px; margin-bottom: 8px; overflow-wrap: anywhere; }
.ruta span { color: var(--suave); }
.motivo { font-size: 13px; border-left: 3px solid var(--dif); padding: 6px 10px; margin: 0 0 10px;
          background: var(--fondo); overflow-wrap: anywhere; }
.texto { font: 13px/1.55 ui-monospace, Consolas, monospace; white-space: pre-wrap; overflow-wrap: anywhere;
         border: 1px solid var(--borde); border-radius: 6px; padding: 10px; max-height: 85vh; overflow: auto; }
button.ver { margin-top: 6px; font-size: 13px; padding: 3px 10px; }
#filtro { font: inherit; padding: 5px 8px; border-radius: 6px; border: 1px solid var(--borde);
          background: var(--panel); color: var(--texto); max-width: 100%; }
.oculto { display: none !important; }
"""
SCRIPT_GRUPOS = (SCRIPT.replace("cdss-verificacion-transcripciones-v1", "cdss-revision-grupos-etarios-v1")
                 .replace("Verificación de transcripciones", "Revisión de grupos etarios")
                 .replace("Coinciden con la imagen", "Rango correcto")) + """
for (const boton of document.querySelectorAll("button.ver")) {
  boton.addEventListener("click", () => {
    const texto = boton.previousElementSibling, abierto = texto.classList.toggle("abierto");
    texto.querySelector(".resto").hidden = !abierto;
    texto.querySelector(".puntos").hidden = abierto;
    boton.textContent = abierto ? "Ver menos" : "Ver completo";
  });
}
const FILTRO = "cdss-revision-grupos-etarios-filtro";
const filtro = document.getElementById("filtro");
function filtrar() {
  const doc = filtro.value;
  for (const el of document.querySelectorAll("section[data-documento], nav a[data-documento]"))
    el.classList.toggle("oculto", !!doc && el.dataset.documento !== doc);
  try { localStorage.setItem(FILTRO, doc); } catch (e) {}
}
try { const guardado = localStorage.getItem(FILTRO);
      if (guardado && filtro.querySelector('option[value="' + guardado + '"]')) filtro.value = guardado; } catch (e) {}
filtro.addEventListener("change", filtrar);
filtrar();
"""


def describir_rango(edad_min: int | None, edad_max: int | None) -> str:
    if edad_min is None and edad_max is None:
        return "sin límite de edad"
    if edad_max is None:
        return f"desde {edad_min} meses"
    return f"{edad_min if edad_min is not None else 0} a {edad_max} meses"


def _paginas(texto: str) -> tuple[int, int]:
    inicio, _, fin = texto.partition("-")
    return int(inicio), int(fin or inicio)


def _imagenes(prefijo: str, inicio: int, fin: int, dir_pagina: Path | None) -> str:
    bloques = []
    for p in range(inicio, fin + 1):
        ruta = f"paginas/{prefijo}-{p:02d}.png"
        if dir_pagina is not None and (dir_pagina / ruta).is_file():
            bloques.append(f'<a href="{ruta}" target="_blank"><img src="{ruta}" alt="Página {p}" loading="lazy"></a>'
                           f'<div class="pie">Página {p} del PDF: {ruta}</div>')
        else:
            bloques.append(f'<div class="falta">Falta la imagen {html.escape(ruta)}. Genérela con el contenedor '
                           'temporal de Poppler (jobs/README.md).</div>')
    return f'<div class="imagenes">{"".join(bloques)}</div>'


def _texto(texto: str) -> str:
    if len(texto) <= LARGO_INICIO:
        return f'<div class="texto">{html.escape(texto)}</div>'
    return (f'<div class="texto">{html.escape(texto[:LARGO_INICIO])}<span class="puntos">…</span>'
            f'<span class="resto" hidden>{html.escape(texto[LARGO_INICIO:])}</span></div>'
            f'<button type="button" class="secundario ver">Ver completo</button>')


def pagina_grupos(filas: list[dict], dir_pagina: Path | None = None, prefijos: dict[str, str] | None = None) -> str:
    """filas: documento (clave), codigo, titulo (opcional), orden, paginas («inicio-fin»),
    seccion, texto, edad_min_meses, edad_max_meses, poblacion, origen_rango y rango_dudoso
    de cada fragmento vigente. dir_pagina: carpeta donde se escribe la página (las
    imágenes se buscan en dir_pagina/paginas). prefijos: prefijo_imagen por documento;
    los documentos sin prefijo (OMS) se muestran solo con el texto."""
    prefijos = prefijos or {}
    filas = sorted(filas, key=lambda f: (not f["rango_dudoso"], f["documento"], f["orden"]))
    dudosos = sum(f["rango_dudoso"] for f in filas)
    enlaces, secciones, documentos = [], [], {}
    for f in filas:
        doc = f["documento"]
        conteo = documentos.setdefault(doc, {"codigo": f["codigo"], "total": 0, "dudosos": 0})
        conteo["total"] += 1
        conteo["dudosos"] += bool(f["rango_dudoso"])
        ident = f"{doc}-{f['orden']:03d}"
        inicio, fin = _paginas(f["paginas"])
        paginas = f"pág. {inicio}" if inicio == fin else f"págs. {inicio} a {fin}"
        rango = describir_rango(f["edad_min_meses"], f["edad_max_meses"])
        clave = f"{f['codigo']} fragmento {f['orden']} ({paginas})"
        etiquetas = [f'<span class="etiqueta">{html.escape(rango)}</span>',
                     f'<span class="etiqueta">{html.escape(f["poblacion"])}</span>',
                     f'<span class="etiqueta">origen: {html.escape(f["origen_rango"])}</span>']
        motivo = ""
        if f["rango_dudoso"]:
            etiquetas.append('<span class="etiqueta dudoso">dudoso</span>')
            explicacion = motivo_dudoso(doc, f["seccion"], f["texto"], orden=f["orden"]) or (
                "No se pudo reconstruir el motivo con las reglas actuales (¿cambiaron después de generar los datos?).")
            motivo = f'<div class="motivo"><strong>Motivo:</strong> {html.escape(explicacion)}</div>'
        ruta = " › ".join(html.escape(p.strip()) for p in (f["seccion"] or "").split(" > ")) or "sin sección"
        enlaces.append(f'<a href="#{ident}" data-documento="{html.escape(doc)}">'
                       f'{html.escape(f["codigo"])} {f["orden"]}{" (dudoso)" if f["rango_dudoso"] else ""}</a>')
        texto = _texto(f["texto"])
        if doc in prefijos:
            cuerpo = (f'<div class="columnas">{_imagenes(prefijos[doc], inicio, fin, dir_pagina)}'
                      f'<div>{texto}</div></div>')
        else:
            cuerpo = texto
        secciones.append(f"""
<section id="{ident}" data-documento="{html.escape(doc)}" data-clave="{html.escape(clave)}: {html.escape(rango)}, {html.escape(f['poblacion'])}">
  <h2>{html.escape(f['codigo'])} · fragmento {f['orden']}</h2>
  <div class="meta">{html.escape(f.get('titulo') or f['codigo'])} · {paginas} del PDF</div>
  <div class="ruta"><span>Sección:</span> {ruta}</div>
  <div class="grupo">{"".join(etiquetas)}</div>
  {motivo}
  {cuerpo}
  <div class="control">
    <label><input type="checkbox"> Rango correcto</label>
    <textarea placeholder="Si no es correcto: rango y población que corresponden (por ejemplo, 24 a 59 meses, NINO; o GENERAL)"></textarea>
  </div>
</section>""")
    opciones = [f'<option value="">Todos los documentos ({len(filas)}, {dudosos} dudosos)</option>']
    opciones += [f'<option value="{html.escape(d)}">{html.escape(c["codigo"])} ({c["total"]}, {c["dudosos"]} dudosos)</option>'
                 for d, c in documentos.items()]
    return f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Revisión de grupos etarios</title>
<style>{ESTILO_GRUPOS}</style>
</head>
<body>
<header>
  <h1>Grupos etarios de los fragmentos ({len(filas)} vigentes, {dudosos} dudosos; {date.today():%d/%m/%Y})</h1>
  <select id="filtro" aria-label="Filtrar por documento">{"".join(opciones)}</select>
  <span id="progreso"></span>
  <button id="copiar">Copiar resumen</button>
  <button id="borrar" class="secundario">Borrar marcas</button>
  <span id="aviso" role="status"></span>
</header>
<nav>{"".join(enlaces)}</nav>
<main>
<p class="meta">Generado con <code>python -m app.indexador grupos-etarios</code>. Los dudosos van primero. Las marcas
se guardan solo en este navegador; «Copiar resumen» incluye todos los documentos aunque haya un filtro.
Las correcciones van a la sección <code>manuales</code> de <code>grupos_etarios.yaml</code>.</p>
{"".join(secciones)}
</main>
<script>{SCRIPT_GRUPOS}</script>
</body>
</html>
"""
