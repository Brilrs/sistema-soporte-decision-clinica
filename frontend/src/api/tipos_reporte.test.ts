// Los fixtures del reporte (generados por el backend, tests/test_c1_reportes.py) cumplen los tipos de
// tipos_reporte.ts: tsc los comprueba al compilar y aquí se revisa su contenido mínimo.
import { describe, expect, it } from "vitest";
import cuidador from "../__fixtures__/reporte_vista_previa_cuidador.json";
import expediente from "../__fixtures__/reporte_vista_previa_expediente.json";
import lista from "../__fixtures__/reportes_lista.json";
import { FRASES_FINALES } from "../components/reporte/textos";
import { SECCIONES_OBLIGATORIAS, SECCIONES_POR_DESTINO, type ReporteListado, type VistaPreviaReporte } from "./tipos_reporte";

const VISTAS: VistaPreviaReporte[] = [expediente as VistaPreviaReporte, cuidador as VistaPreviaReporte];
const LISTA: ReporteListado[] = lista as ReporteListado[];

describe("fixtures del reporte", () => {
  it("cada vista previa incluye las secciones obligatorias y solo secciones de su destino", () => {
    for (const v of VISTAS) {
      for (const s of SECCIONES_OBLIGATORIAS) expect(v.secciones).toContain(s);
      for (const s of v.secciones) expect(SECCIONES_POR_DESTINO[v.destino]).toContain(s);
    }
    expect(expediente.frase_final).toBe(FRASES_FINALES.EXPEDIENTE);
    expect(cuidador.frase_final).toBe(FRASES_FINALES.CUIDADOR);
    expect(cuidador.revision_pendiente).toBe(true);
    expect(cuidador.avisos).toContain("Texto en revisión clínica: no entregar a pacientes");
  });

  it("la lista trae número, destino y hash, del más reciente al más antiguo", () => {
    expect(LISTA.map((r) => r.numero_reporte)).toEqual(["EV-2026-00002", "EV-2026-00001"]);
    expect(LISTA.map((r) => r.destino)).toEqual(["CUIDADOR", "EXPEDIENTE"]);
    for (const r of LISTA) expect(r.hash_documento).toMatch(/^[0-9a-f]{64}$/);
  });
});
