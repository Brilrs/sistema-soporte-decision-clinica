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

  // Un grid-area global sobre una tarjeta compartida (la de riesgo también se usa en
  // .estado-consulta) crea filas y columnas implícitas en la rejilla de una columna.
  it("M05: las áreas de la rejilla de dos columnas solo se aplican a los hijos de .resultado__cuerpo", () => {
    const conArea = REGLAS.filter((r) => propiedad(r.cuerpo, "grid-area") !== null);
    expect(conArea.length).toBeGreaterThan(0);
    for (const r of conArea) for (const s of selectores(r)) expect(s).toMatch(/^\.resultado__cuerpo > /);
    expect(valor(".resultado__cuerpo", "grid-template-columns", /max-width: 1100px/)).toBe("minmax(0, 1fr)");
  });
});
