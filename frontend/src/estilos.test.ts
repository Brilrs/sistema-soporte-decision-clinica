// Reglas de la hoja de estilos que evitan desbordes horizontales. jsdom no calcula la rejilla ni
// flexbox, así que se revisa el texto de estilos.css (vite.config.ts deja pasar solo este ?raw).
// La auditoría visual con Chrome sin cabeza a 320, 390, 600, 768, 900, 1024, 1280 y 1920 px
// mostró que el contenido nunca debe poder ensanchar la página: estas reglas son las que lo impiden.
import { describe, expect, it } from "vitest";
import estilos from "./estilos.css?raw";

type Regla = { selector: string; cuerpo: string; media: string | null };

// Recorre la hoja (sin comentarios) y devuelve cada regla con su @media, si la hay.
function reglas(css: string): Regla[] {
  const texto = css.replace(/\/\*[\s\S]*?\*\//g, "");
  const salida: Regla[] = [];
  let media: string | null = null;
  let inicio = 0;
  let selector = "";
  for (let i = 0; i < texto.length; i++) {
    const c = texto[i];
    if (c === "{") {
      const previo = texto.slice(inicio, i).trim();
      if (previo.startsWith("@media")) media = previo;
      else selector = previo;
      inicio = i + 1;
    } else if (c === "}") {
      const cuerpo = texto.slice(inicio, i).trim();
      if (selector) salida.push({ selector, cuerpo, media });
      else media = null; // cierre del @media
      selector = "";
      inicio = i + 1;
    }
  }
  return salida;
}

const REGLAS = reglas(estilos);

// Color de un token de :root (#rrggbb) y contraste WCAG entre dos colores.
function token(nombre: string): string {
  const raiz = REGLAS.find((r) => r.selector === ":root" && r.media === null);
  const v = raiz ? propiedad(raiz.cuerpo, nombre) : null;
  if (!v || !/^#[0-9a-f]{6}$/i.test(v)) throw new Error(`Token ${nombre} sin color hexadecimal`);
  return v;
}
function luminancia(hex: string): number {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255)
    .map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}
function contraste(a: string, b: string): number {
  const [l1, l2] = [luminancia(a), luminancia(b)].sort((x, y) => y - x);
  return (l1 + 0.05) / (l2 + 0.05);
}
const selectores = (r: Regla) => r.selector.split(",").map((s) => s.trim());
const propiedad = (cuerpo: string, nombre: string) =>
  cuerpo.split(";").map((d) => d.trim()).find((d) => d.startsWith(`${nombre}:`))?.slice(nombre.length + 1).trim() ?? null;
// Valor de una propiedad para un selector exacto (la última regla gana), opcionalmente dentro de un @media.
function valor(selector: string, nombre: string, media: RegExp | null = null): string | null {
  let v: string | null = null;
  for (const r of REGLAS) {
    if (!selectores(r).includes(selector)) continue;
    if (media ? !(r.media && media.test(r.media)) : r.media !== null) continue;
    v = propiedad(r.cuerpo, nombre) ?? v;
  }
  return v;
}

describe("estilos · desbordes horizontales", () => {
  it("el analizador encuentra las reglas de la hoja", () => {
    expect(REGLAS.length).toBeGreaterThan(100);
    expect(REGLAS.some((r) => r.media?.includes("max-width: 600px"))).toBe(true);
  });

  it("el contenido principal (elemento flex) puede encogerse por debajo del ancho de su contenido", () => {
    expect(valor(".contenido", "min-width")).toBe("0");
  });

  it("ninguna columna de rejilla usa fr sin minmax, en ningún ancho", () => {
    const sinMinmax: string[] = [];
    for (const r of REGLAS) {
      const v = propiedad(r.cuerpo, "grid-template-columns");
      if (!v) continue;
      // Se quitan los minmax(...) (con un nivel de paréntesis anidado) y no debe quedar ningún «fr».
      const resto = v.replace(/minmax\((?:[^()]|\([^()]*\))*\)/g, "");
      if (/\d*\.?\d+fr\b/.test(resto)) sinMinmax.push(`${r.media ?? ""} ${r.selector}: ${v}`.trim());
    }
    expect(sinMinmax).toEqual([]);
  });

  it("M04: la lista de consultas previas no crece con la pregunta y la pregunta se corta", () => {
    expect(valor(".contexto__consultas", "grid-template-columns")).toBe("minmax(0, 1fr)");
    expect(valor(".contexto__consultas > li", "min-width")).toBe("0");
    expect(valor(".contexto", "min-width")).toBe("0");
    expect(valor(".consulta > *", "min-width")).toBe("0");
    expect(valor(".contexto__pregunta", "overflow")).toBe("hidden");
    expect(valor(".contexto__pregunta", "text-overflow")).toBe("ellipsis");
    expect(valor(".avance__etapas", "grid-template-columns")).toBe("minmax(0, 1fr)");
  });

  it("los textos largos se cortan dentro de su caja y las tablas se desplazan en su contenedor", () => {
    expect(valor("body", "overflow-wrap")).toBe("break-word");
    expect(valor(".tabla-contenedor", "overflow-x")).toBe("auto");
    // Sin position: relative, un texto solo para lectores (position: absolute) de la última columna
    // escapa del contenedor con desplazamiento y ensancha la página (M08 en la parte E6).
    expect(valor(".tabla-contenedor", "position")).toBe("relative");
    expect(valor(".ficha-cabecera__paciente", "min-width")).toBe("0");
  });

  it("no se esconde el desborde con overflow-x: hidden en html, body o la raíz", () => {
    for (const r of REGLAS) {
      if (!selectores(r).some((s) => ["html", "body", "#root", ".app", ".cuerpo"].includes(s))) continue;
      expect(propiedad(r.cuerpo, "overflow-x")).not.toBe("hidden");
      expect(propiedad(r.cuerpo, "overflow")).not.toBe("hidden");
    }
  });

  it("la barra superior pasa a dos líneas en pantallas angostas", () => {
    expect(valor(".cabecera__marca", "min-width")).toBe("0");
    expect(valor(".cabecera__usuario", "min-width")).toBe("0");
    expect(valor(".cabecera", "flex-wrap", /max-width: 600px/)).toBe("wrap");
    expect(valor(".cabecera__usuario", "flex-wrap", /max-width: 600px/)).toBe("wrap");
    // A 420 px o menos el nombre queda solo para lectores de pantalla (el avatar muestra las iniciales).
    expect(valor(".cabecera__nombre", "clip", /max-width: 420px/)).toBe("rect(0, 0, 0, 0)");
  });

  // M08 (ajuste posterior a E6): las dos tablas caben sin desplazamiento interno desde unos 1000 px
  // (evaluaciones) y 1100 px (tamizajes); el min-width solo es el respaldo para anchos menores y
  // debe ser menor que el espacio disponible en esos anchos.
  it("M08: tablas compactas que caben desde unos 1000 px, con el desplazamiento interno solo de respaldo", () => {
    const px = (v: string | null) => Number(v?.replace("px", ""));
    // Contenido a 1000 px de ventana: 1000 - menú 230 - márgenes 64 - relleno de la tarjeta 40 - bordes 2.
    expect(px(valor(".evaluaciones__tabla table", "min-width"))).toBeLessThanOrEqual(1000 - 230 - 64 - 40 - 2);
    // Columna derecha de .historial a 1280 px (dos columnas 2:3): (1280 - 230 - 64 - 20) x 3/5 - 42.
    expect(px(valor(".tamizajes__tabla table", "min-width"))).toBeLessThanOrEqual(Math.floor((1280 - 230 - 64 - 20) * 0.6) - 42);
    // Por debajo de 1280 px el gráfico y la tabla de tamizajes van en una columna.
    expect(valor(".historial", "grid-template-columns", /max-width: 1279px/)).toBe("minmax(0, 1fr)");
    // La pregunta se parte en hasta 2 líneas con puntos suspensivos, no en una sola.
    expect(valor(".evaluaciones__pregunta", "-webkit-line-clamp")).toBe("2");
    expect(valor(".evaluaciones__pregunta", "line-clamp")).toBe("2");
    expect(valor(".evaluaciones__pregunta", "overflow")).toBe("hidden");
    expect(valor(".evaluaciones__pregunta", "white-space")).toBeNull();
    expect(valor(".evaluaciones__pregunta-celda", "min-width")).toBe("9rem");
    // Celdas compactas, etiquetas que pueden partirse y el botón «Ver» en una línea.
    expect(valor(".tabla--compacta td", "padding")).toBe(".45rem .3rem");
    expect(valor(".tabla--compacta th", "padding")).toBe(".45rem .3rem");
    expect(valor(".tabla--compacta .etiqueta", "white-space")).toBe("normal");
    expect(valor(".evaluaciones__ver", "white-space")).toBe("nowrap");
  });

  // Menú en pantalla angosta (E6): el mismo corte de 800 px que Layout.tsx (CONSULTA_ANGOSTA).
  it("menú: por debajo de 800 px se oculta el lateral y aparece «Abrir menú»; desde 800 px no cambia", () => {
    expect(valor(".cuerpo > .menu", "display", /max-width: 799px/)).toBe("none");
    expect(valor(".boton-menu", "display")).toBe("none");
    expect(valor(".boton-menu", "display", /max-width: 799px/)).toBe("inline-flex");
    // Ninguna regla oculta el menú lateral a 800 px o más (antes se ocultaba con max-width: 800px).
    const ocultan = REGLAS.filter((r) => selectores(r).some((x) => x === ".menu" || x === ".cuerpo > .menu") &&
                                         propiedad(r.cuerpo, "display") === "none");
    expect(ocultan.map((r) => r.media)).toEqual(["@media (max-width: 799px)"]);
    // Áreas táctiles de al menos 44 px.
    expect(valor(".menu-movil a", "min-height")).toBe("44px");
    expect(valor(".boton-menu", "height", /max-width: 799px/)).toBe("44px");
    expect(valor(".boton-menu", "width", /max-width: 799px/)).toBe("44px");
    expect(valor(".menu-movil__cerrar", "height")).toBe("44px");
    // El icono se ve sobre la cabecera: blanco frente al azul oscuro, con contraste de 3:1 o más
    // (WCAG 1.4.11, componentes de la interfaz), y ninguna regla oculta los span de la marca (así
    // se ocultaba el icono por debajo de 420 px).
    expect(valor(".boton-menu", "color", /max-width: 799px/)).toBe("var(--blanco)");
    expect(valor(".boton-menu__icono", "color", /max-width: 799px/)).toBe("var(--blanco)");
    const fondo = valor(".cabecera", "background");
    expect(fondo).toBe("var(--azul-900)");
    expect(contraste(token("--blanco"), token("--azul-900"))).toBeGreaterThanOrEqual(3);
    expect(REGLAS.some((r) => selectores(r).includes(".cabecera__marca span") && propiedad(r.cuerpo, "display") === "none"))
      .toBe(false);
    expect(valor(".boton-menu", "outline", /max-width: 799px/)).toBeNull(); // el foco va en :focus-visible
    expect(valor(".boton-menu:focus-visible", "outline", /max-width: 799px/)).toBe("3px solid var(--blanco)");
    // El panel no ensancha la página: ancho acotado al de la ventana.
    expect(valor(".menu-movil", "width")).toBe("min(300px, 85vw)");
  });

  // M11 (parte F2c): tabla compacta que cabe desde unos 1000 px, título en 2 líneas, áreas táctiles
  // de 44 px por debajo de 800 px y etiquetas nuevas con contraste AA (4.5:1) sobre su fondo.
  it("M11: tabla de guías que cabe desde 1000 px, áreas táctiles de 44 px y etiquetas legibles", () => {
    const px = (v: string | null) => Number(v?.replace("px", ""));
    // Contenido a 1000 px: 1000 - menú 230 - márgenes 64 - relleno de la tarjeta 32 - bordes 2.
    expect(px(valor(".guias__tabla table", "min-width"))).toBeLessThanOrEqual(1000 - 230 - 64 - 32 - 2);
    expect(valor(".guias__titulo", "-webkit-line-clamp")).toBe("2");
    expect(valor(".guias__titulo", "line-clamp")).toBe("2");
    expect(valor(".guias__titulo", "overflow")).toBe("hidden");
    // El código y la versión se parten solo donde se puede (guiones, barras), no a mitad de palabra.
    expect(valor(".guias__codigo", "overflow-wrap")).toBeNull();
    expect(valor(".guias__acciones", "flex-wrap")).toBe("wrap");
    expect(valor(".indexacion", "grid-template-columns")).toBe("minmax(0, 1fr)");
    expect(valor(".indexacion__etapas", "flex-wrap")).toBe("wrap");
    expect(valor(".modal--amplia", "max-width")).toBe("760px");
    const angosta = /max-width: 799px/;
    expect(valor(".conocimiento .boton", "min-height", angosta)).toBe("44px");
    expect(valor(".modal .boton", "min-height", angosta)).toBe("44px");
    expect(valor(".modal input", "min-height", angosta)).toBe("44px");
    expect(valor(".modal select", "min-height", angosta)).toBe("44px");
    expect(valor(".guia__opcion", "min-height", angosta)).toBe("44px");
    // Tokens de todos los bloques :root.
    const tokens = (nombre: string) => {
      for (const r of REGLAS) if (r.selector === ":root" && r.media === null) { const v = propiedad(r.cuerpo, nombre); if (v) return v; }
      throw new Error(`Token ${nombre} no definido`);
    };
    const color = (v: string | null) => tokens(v!.replace(/^var\((--[\w-]+)\)$/, "$1"));
    for (const clase of [".etiqueta--nivel-1", ".etiqueta--nivel-2", ".etiqueta--obsoleta", ".etiqueta--indexacion-COMPLETADA",
                         ".etiqueta--indexacion-PENDIENTE", ".etiqueta--indexacion-EN_PROCESO", ".etiqueta--indexacion-ERROR"]) {
      expect(contraste(color(valor(clase, "color")), color(valor(clase, "background"))), clase).toBeGreaterThanOrEqual(4.5);
    }
    // «Retirar» deshabilitado (aria-disabled, y también con disabled): gris, sin el rojo de una acción
    // disponible, sin opacidad que baje el contraste del texto y con el cursor de no permitido.
    for (const sel of ['.boton--peligro[aria-disabled="true"]', ".boton--peligro:disabled"]) {
      const texto = valor(sel, "color");
      const fondo = valor(sel, "background");
      expect([texto, fondo, valor(sel, "border-color")], sel).not.toContain("var(--rojo)");
      expect(contraste(color(texto), color(fondo)), sel).toBeGreaterThanOrEqual(4.5);
      expect(valor(sel, "opacity"), sel).toBe("1");
      expect(valor(sel, "cursor"), sel).toBe("not-allowed");
    }
    // La regla del botón de peligro deshabilitado va después de la general, para ganarle a su opacidad.
    const posicion = (s: string) => REGLAS.findIndex((r) => r.media === null && selectores(r).includes(s));
    expect(posicion(".boton--peligro:disabled")).toBeGreaterThan(posicion(".boton:disabled"));
  });

  // «Historial de consultas» (P10, Sprint 3 parte B): tabla desde 800 px y tarjetas por debajo.
  it("Historial de consultas: tabla que cabe desde unos 1000 px, tarjetas sin desborde, 44 px y etiquetas de riesgo legibles", () => {
    const px = (v: string | null) => Number(v?.replace("px", ""));
    // Contenido a 1000 px de ventana, como M08: 1000 - menú 230 - márgenes 64 - relleno de la tarjeta 40 - bordes 2.
    expect(px(valor(".consultas-propias__tabla table", "min-width"))).toBeLessThanOrEqual(1000 - 230 - 64 - 40 - 2);
    expect(valor(".consultas-propias__pregunta", "-webkit-line-clamp")).toBe("2");
    expect(valor(".consultas-propias__pregunta", "line-clamp")).toBe("2");
    expect(valor(".consultas-propias__pregunta", "overflow")).toBe("hidden");
    expect(valor(".consultas-propias__pregunta", "overflow-wrap")).toBe("anywhere");
    expect(valor(".consultas-propias__paciente", "overflow-wrap")).toBe("anywhere");
    expect(valor(".consultas-propias__tarjeta-pregunta", "overflow-wrap")).toBe("anywhere");
    // Las tarjetas y los filtros pueden encogerse y pasar a otra línea.
    expect(valor(".consultas-propias__tarjetas", "grid-template-columns")).toBe("minmax(0, 1fr)");
    expect(valor(".consultas-propias__tarjeta", "min-width")).toBe("0");
    expect(valor(".consultas-propias__campo", "min-width")).toBe("0");
    for (const sel of [".consultas-propias__filtros", ".consultas-propias__botones", ".consultas-propias__etiquetas",
                       ".consultas-propias__tarjeta-cabecera", ".consultas-propias__paginacion", ".tabla__acciones"]) {
      expect(valor(sel, "flex-wrap"), sel).toBe("wrap");
    }
    const angosta = /max-width: 799px/;
    expect(valor(".consultas-propias .boton", "min-height", angosta)).toBe("44px");
    expect(valor(".consultas-propias__campo select", "min-height", angosta)).toBe("44px");
    expect(valor(".consultas-propias__campo input", "min-height", angosta)).toBe("44px");
    const tokens = (nombre: string) => {
      for (const r of REGLAS) if (r.selector === ":root" && r.media === null) { const v = propiedad(r.cuerpo, nombre); if (v) return v; }
      throw new Error(`Token ${nombre} no definido`);
    };
    const color = (v: string | null) => tokens(v!.replace(/^var\((--[\w-]+)\)$/, "$1"));
    for (const nivel of ["BAJO", "MODERADO", "ALTO", "MUY_ALTO"]) {
      const clase = `.etiqueta--riesgo-${nivel}`;
      expect(contraste(color(valor(clase, "color")), color(valor(clase, "background"))), clase).toBeGreaterThanOrEqual(4.5);
    }
  });

  it("M09: dos columnas que se apilan por debajo de 1101 px, 44 px en lo nuevo y etiquetas de destino legibles", () => {
    expect(valor(".reporte__cuerpo", "grid-template-columns")).toBe("minmax(0, 21rem) minmax(0, 1fr)");
    expect(valor(".reporte__cuerpo", "grid-template-columns", /max-width: 1100px/)).toBe("minmax(0, 1fr)");
    expect(valor(".reporte__cuerpo > *", "min-width")).toBe("0");
    for (const sel of [".reporte__datos", ".reporte__huella", ".reporte__huella code", ".hoja", ".reporte__opcion"]) {
      expect(valor(sel, "overflow-wrap"), sel).toBe("anywhere");
    }
    for (const sel of [".reporte__acciones", ".reporte__emitido-cabecera", ".hoja__cabecera"]) {
      expect(valor(sel, "flex-wrap"), sel).toBe("wrap");
    }
    // «Ver» y «Exportar» o «Reporte» alineados a la derecha en todas las filas; en una línea desde 1101 px.
    for (const sel of [".evaluaciones__acciones", ".consultas-propias__acciones"]) {
      expect(valor(sel, "flex-wrap"), sel).toBe("wrap");
      expect(valor(sel, "justify-content"), sel).toBe("flex-end");
      expect(valor(sel, "flex-wrap", /min-width: 1101px/), sel).toBe("nowrap");
    }
    expect(valor(".reporte__opciones .boton--primario", "min-height")).toBe("44px");
    expect(valor(".reporte__acciones .boton", "min-height")).toBe("44px");
    const angosta = /max-width: 799px/;
    expect(valor(".reporte .boton", "min-height", angosta)).toBe("44px");
    expect(valor(".evaluaciones__acciones .boton", "min-height", angosta)).toBe("44px");
    expect(valor(".reporte__opcion", "min-height", angosta)).toBe("44px");
    expect(valor(".hoja__campos div", "grid-template-columns", angosta)).toBe("minmax(0, 1fr)");
    // Los tokens están repartidos en varios bloques :root.
    const color = (v: string | null) => {
      const nombre = v!.replace(/^var\((--[\w-]+)\)$/, "$1");
      for (const r of REGLAS) if (r.selector === ":root" && r.media === null) { const x = propiedad(r.cuerpo, nombre); if (x) return x; }
      throw new Error(`Token ${nombre} no definido`);
    };
    for (const destino of ["EXPEDIENTE", "CUIDADOR"]) {
      const clase = `.etiqueta--destino-${destino}`;
      expect(contraste(color(valor(clase, "color")), color(valor(clase, "background"))), clase).toBeGreaterThanOrEqual(4.5);
    }
  });

  // Un grid-area global sobre una tarjeta compartida (la de riesgo también se usa en
  // .estado-consulta) crea filas y columnas implícitas en la rejilla de una columna.
  it("M05: las áreas de la rejilla de dos columnas solo se aplican a los hijos de .resultado__cuerpo", () => {
    const conArea = REGLAS.filter((r) => propiedad(r.cuerpo, "grid-area") !== null);
    expect(conArea.length).toBeGreaterThan(0);
    for (const r of conArea) for (const s of selectores(r)) expect(s).toMatch(/^\.resultado__cuerpo > /);
    expect(valor(".resultado__cuerpo", "grid-template-columns", /max-width: 1100px/)).toBe("minmax(0, 1fr)");
  });
});
