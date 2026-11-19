// Los fixtures de parámetros (generados por el backend, tests/test_e1a_parametros.py) cumplen los tipos de
// tipos_parametros.ts: tsc los comprueba al compilar y aquí se revisa su contenido mínimo.
import { describe, expect, it } from "vitest";
import historial from "../__fixtures__/parametros_historial.json";
import huella from "../__fixtures__/parametros_huella.json";
import parametros from "../__fixtures__/parametros.json";
import soloLectura from "../__fixtures__/parametros_solo_lectura.json";
import type { HuellaConfiguracion, PaginaHistorial, Parametros } from "./tipos_parametros";

const P = parametros as Parametros;
const ADMIN = soloLectura as Parametros;
const H = historial as PaginaHistorial;
const HUELLA = huella as HuellaConfiguracion;

describe("fixtures de parámetros", () => {
  it("solo el Coordinador puede editar; tramos fijos y valores pendientes de verificación", () => {
    expect(P.puede_editar).toBe(true);
    expect(ADMIN.puede_editar).toBe(false);
    expect(P.puntos_corte.tramos.map((t) => [t.edad_min_meses, t.edad_max_meses])).toEqual([[6, 23], [24, 59]]);
    expect(P.puntos_corte.tramos.every((t) => t.categorias.every((c) => !c.verificado))).toBe(true);
    expect(P.vigencia_tamizaje.clave).toBe("DIAS_VIGENCIA_TAMIZAJE");
  });

  it("los grupos de solo lectura no traen los parámetros sin uso", () => {
    const claves = [...P.recuperacion, ...P.modelo, ...P.indexacion].map((p) => p.clave);
    for (const sinUso of ["EDAD_MIN_CLASIFICACION", "EDAD_MAX_CLASIFICACION", "REINTENTOS_MAXIMOS", "MODELO_RESPALDO"]) {
      expect(claves).not.toContain(sinUso);
    }
    expect(P.recuperacion.find((p) => p.clave === "UMBRAL_RELEVANCIA")?.valor).toBe("0.15");
  });

  it("historial paginado y huella con sus componentes", () => {
    expect(H.versiones.length).toBeLessThanOrEqual(H.limite);
    expect(HUELLA.huella).toMatch(/^[0-9a-f]{64}$/);
    expect(HUELLA.componentes.map((c) => c.nombre)).toContain("puntos_corte");
  });
});
