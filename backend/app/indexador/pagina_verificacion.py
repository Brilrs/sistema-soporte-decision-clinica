"""Página HTML local (data/mediciones/verificacion.html) para verificar cada
transcripción contra la imagen de su página: imagen a la izquierda, texto a la
derecha, valores críticos resaltados, casilla de conformidad y notas guardadas
en el navegador. Las imágenes se enlazan con ruta relativa (paginas/...)."""
import html
import json
import re
from datetime import date
from pathlib import Path

from app.indexador.config import FuenteDocumento
from app.indexador.informes import BANDERAS, ValorCritico, cargar_valores
from app.indexador.transcripciones import cargar_transcripciones

ESTILO = """
:root { --fondo: #f6f7f9; --panel: #ffffff; --texto: #1d2330; --suave: #5b6475; --borde: #d9dde5;
        --marca: #ffe58a; --ok: #1f7a4d; --dif: #b4471f; --acento: #2457c5; }
@media (prefers-color-scheme: dark) {
  :root { --fondo: #14171d; --panel: #1d2129; --texto: #e6e8ee; --suave: #a3abba; --borde: #343a46;
          --marca: #6b5a12; --ok: #4fbf87; --dif: #f08a5d; --acento: #7aa2ff; }
}
* { box-sizing: border-box; }
body { margin: 0; font: 15px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; background: var(--fondo);
       color: var(--texto); }
header { position: sticky; top: 0; z-index: 2; background: var(--panel); border-bottom: 1px solid var(--borde);
         padding: 12px 16px; display: flex; flex-wrap: wrap; gap: 12px; align-items: center; }
header h1 { font-size: 18px; margin: 0; flex: 1 1 260px; }
#progreso { color: var(--suave); }
button { font: inherit; padding: 6px 14px; border-radius: 6px; border: 1px solid var(--borde);
         background: var(--acento); color: #fff; cursor: pointer; }
button.secundario { background: transparent; color: var(--texto); }
#aviso { color: var(--ok); min-width: 120px; }
nav { padding: 8px 16px; display: flex; flex-wrap: wrap; gap: 6px; }
nav a { font-size: 13px; padding: 2px 8px; border-radius: 10px; border: 1px solid var(--borde);
        color: var(--texto); text-decoration: none; }
nav a.coincide { border-color: var(--ok); color: var(--ok); }
nav a.diferencia { border-color: var(--dif); color: var(--dif); }
main { padding: 0 16px 40px; }
section { background: var(--panel); border: 1px solid var(--borde); border-radius: 8px; margin: 16px 0; padding: 16px; }
section h2 { font-size: 16px; margin: 0 0 4px; }
.meta { color: var(--suave); font-size: 13px; margin-bottom: 12px; overflow-wrap: anywhere; }
.columnas { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 16px; }
@media (max-width: 900px) { .columnas { grid-template-columns: minmax(0, 1fr); } }
.imagenes { max-height: 85vh; overflow: auto; border: 1px solid var(--borde); border-radius: 6px; background: #fff; }
.imagenes img { display: block; width: 100%; height: auto; }
.imagenes .pie { font-size: 12px; color: #444; padding: 4px 8px; border-top: 1px solid #ddd; }
.falta { padding: 12px; color: var(--dif); font-size: 13px; }
pre { margin: 0; white-space: pre-wrap; overflow-wrap: anywhere; font: 13px/1.55 ui-monospace, Consolas, monospace;
      max-height: 85vh; overflow: auto; border: 1px solid var(--borde); border-radius: 6px; padding: 12px; }
mark { background: var(--marca); color: inherit; border-radius: 2px; }
.valores { margin-top: 12px; }
.valores h3 { font-size: 14px; margin: 0 0 6px; }
.valores li { margin-bottom: 4px; }
.valores .no { color: var(--dif); font-weight: 600; }
.control { margin-top: 12px; display: grid; gap: 8px; }
.control label { display: flex; gap: 8px; align-items: center; font-weight: 600; }
textarea { width: 100%; min-height: 60px; font: inherit; padding: 8px; border-radius: 6px;
           border: 1px solid var(--borde); background: var(--fondo); color: var(--texto); }
section.coincide { border-color: var(--ok); }
section.diferencia { border-color: var(--dif); }
"""

SCRIPT = """
const CLAVE = "cdss-verificacion-transcripciones-v1";
let estado = {};
try { estado = JSON.parse(localStorage.getItem(CLAVE) || "{}"); } catch (e) { estado = {}; }
function guardar() { try { localStorage.setItem(CLAVE, JSON.stringify(estado)); } catch (e) {} }
function pintar(id) {
  const s = estado[id] || {};
  const seccion = document.getElementById(id);
  const enlace = document.querySelector('nav a[href="#' + id + '"]');
  const clase = s.notas && s.notas.trim() ? "diferencia" : (s.coincide ? "coincide" : "");
  for (const el of [seccion, enlace]) { el.classList.remove("coincide", "diferencia"); if (clase) el.classList.add(clase); }
}
function progreso() {
  const ids = [...document.querySelectorAll("section[id]")].map(s => s.id);
  const ok = ids.filter(id => estado[id] && estado[id].coincide && !(estado[id].notas || "").trim()).length;
  const dif = ids.filter(id => estado[id] && (estado[id].notas || "").trim()).length;
  document.getElementById("progreso").textContent =
    ok + " coinciden, " + dif + " con diferencias, " + (ids.length - ok - dif) + " pendientes de " + ids.length;
}
for (const seccion of document.querySelectorAll("section[id]")) {
  const id = seccion.id, s = estado[id] || {};
  const casilla = seccion.querySelector("input[type=checkbox]"), notas = seccion.querySelector("textarea");
  casilla.checked = !!s.coincide; notas.value = s.notas || "";
  casilla.addEventListener("change", () => { estado[id] = { ...(estado[id] || {}), coincide: casilla.checked }; guardar(); pintar(id); progreso(); });
  notas.addEventListener("input", () => { estado[id] = { ...(estado[id] || {}), notas: notas.value }; guardar(); pintar(id); progreso(); });
  pintar(id);
}
progreso();
function resumen() {
  const filas = [...document.querySelectorAll("section[id]")].map(s => ({ id: s.id, clave: s.dataset.clave, ...(estado[s.id] || {}) }));
  const dif = filas.filter(f => (f.notas || "").trim());
  const ok = filas.filter(f => f.coincide && !(f.notas || "").trim());
  const pend = filas.filter(f => !f.coincide && !(f.notas || "").trim());
  const l = ["Verificación de transcripciones (" + new Date().toLocaleDateString("es-PE") + ")", "",
             "Coinciden con la imagen (" + ok.length + "):"];
  ok.forEach(f => l.push("- " + f.clave));
  l.push("", "Con diferencias (" + dif.length + "):");
  dif.forEach(f => l.push("- " + f.clave + (f.coincide ? " (marcada como coincide)" : "") + ": " + f.notas.trim().replace(/\\s*\\n\\s*/g, " / ")));
  l.push("", "Pendientes (" + pend.length + "):");
  pend.forEach(f => l.push("- " + f.clave));
  return l.join("\\n");
}
function avisar(t) { const a = document.getElementById("aviso"); a.textContent = t; setTimeout(() => a.textContent = "", 3000); }
document.getElementById("copiar").addEventListener("click", async () => {
  const texto = resumen();
  try { await navigator.clipboard.writeText(texto); avisar("Resumen copiado"); }
  catch (e) {
    const area = document.createElement("textarea"); area.value = texto; document.body.appendChild(area);
    area.select(); try { document.execCommand("copy"); avisar("Resumen copiado"); } catch (e2) { prompt("Copie el resumen:", texto); }
    area.remove();
  }
});
document.getElementById("borrar").addEventListener("click", () => {
  if (!confirm("¿Borrar todas las marcas y notas guardadas en este navegador?")) return;
  estado = {}; guardar(); location.reload();
});
"""


def _resaltar(texto: str, valores: list[ValorCritico]) -> tuple[str, dict[str, str | None]]:
    tramos, encontrados = [], {}
    for v in valores:
        m = re.search(v.regex, texto, BANDERAS)
        encontrados[v.id] = m.group(0) if m else None
        if m and m.end() > m.start():
            tramos.append((m.start(), m.end()))
    unidos: list[list[int]] = []
    for a, b in sorted(tramos):
        if unidos and a <= unidos[-1][1]:
            unidos[-1][1] = max(unidos[-1][1], b)
        else:
            unidos.append([a, b])
    partes, pos = [], 0
    for a, b in unidos:
        partes += [html.escape(texto[pos:a]), "<mark>", html.escape(texto[a:b]), "</mark>"]
        pos = b
    partes.append(html.escape(texto[pos:]))
    return "".join(partes), encontrados


def pagina_verificacion(fuentes: list[FuenteDocumento], dir_mediciones: Path) -> str:
    valores = cargar_valores()
    secciones, indice = [], []
    for fuente in fuentes:
        if not fuente.transcripciones:
            continue
        for t in cargar_transcripciones(fuente.transcripciones):
            ident = re.sub(r"[^a-z0-9]+", "-", t.clave.lower())
            propios = [v for v in valores if v.transcripcion == t.clave]
            texto_html, encontrados = _resaltar(t.texto, propios)
            imagenes = []
            for p in range(t.pagina, t.pagina_fin + 1):
                ruta = f"paginas/{fuente.prefijo_imagen}-{p:02d}.png"
                if (dir_mediciones / ruta).is_file():
                    imagenes.append(f'<a href="{ruta}" target="_blank"><img src="{ruta}" alt="Página {p}" '
                                    f'loading="lazy"></a><div class="pie">Página {p} del PDF: {ruta}</div>')
                else:
                    imagenes.append(f'<div class="falta">Falta la imagen {html.escape(ruta)}. Genérela con el '
                                    'contenedor temporal de Poppler (jobs/README.md).</div>')
            if propios:
                items = []
                for v in propios:
                    hallado = encontrados[v.id]
                    if hallado:
                        detalle = f"«<mark>{html.escape(' '.join(hallado.split()))}</mark>»"
                    else:
                        detalle = '<span class="no">no se encontró en la transcripción</span>'
                    items.append(f"<li><strong>{html.escape(v.id)}</strong>: {html.escape(v.descripcion)}<br>{detalle}</li>")
                lista = f'<div class="valores"><h3>Valores críticos ({len(propios)})</h3><ul>{"".join(items)}</ul></div>'
            else:
                lista = '<div class="valores"><h3>Valores críticos</h3><p>Este archivo no tiene reglas propias.</p></div>'
            paginas = str(t.pagina) if t.pagina == t.pagina_fin else f"{t.pagina} a {t.pagina_fin}"
            estado = "verificada en el encabezado" if t.verificada else "sin verificar en el encabezado"
            indice.append(f'<a href="#{ident}">{html.escape(t.clave)}</a>')
            secciones.append(f"""
<section id="{ident}" data-clave="{html.escape(t.clave)}">
  <h2>{html.escape(t.clave)}</h2>
  <div class="meta">{html.escape(t.documento)}, pág. {paginas} · {html.escape(t.tabla)} · {estado}<br>
    backend/app/indexador/transcripciones/{html.escape(t.clave)}.md</div>
  <div class="columnas">
    <div class="imagenes">{"".join(imagenes)}</div>
    <pre>{texto_html}</pre>
  </div>
  {lista}
  <div class="control">
    <label><input type="checkbox"> Coincide con la imagen</label>
    <textarea placeholder="Diferencias encontradas (valor, fila o palabra y lo que dice la imagen)"></textarea>
  </div>
</section>""")
    total = len(secciones)
    return f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Verificación de transcripciones</title>
<style>{ESTILO}</style>
</head>
<body>
<header>
  <h1>Verificación de transcripciones ({total})</h1>
  <span id="progreso"></span>
  <button id="copiar">Copiar resumen</button>
  <button id="borrar" class="secundario">Borrar marcas</button>
  <span id="aviso" role="status"></span>
</header>
<nav>{"".join(indice)}</nav>
<main>
<p class="meta">Generado el {date.today():%d/%m/%Y} con <code>python -m app.indexador verificar-valores</code>.
Las marcas y notas se guardan solo en este navegador. Al terminar, use «Copiar resumen» y complete
<code>verificado_por</code> y <code>fecha_verificacion</code> en cada transcripción conforme.</p>
{"".join(secciones)}
</main>
<script>{SCRIPT}</script>
</body>
</html>
"""
