// Los fixtures de auditoría (generados por el backend, tests/test_d1_auditoria.py) cumplen los tipos de
// tipos_auditoria.ts: tsc los comprueba al compilar y aquí se revisa su contenido mínimo.
import { describe, expect, it } from "vitest";
import consultas from "../__fixtures__/auditoria_consultas.json";
import detalle from "../__fixtures__/auditoria_detalle.json";
import indicadores from "../__fixtures__/auditoria_indicadores.json";
import type { DetalleAuditoria, IndicadoresAuditoria, PaginaAuditoria } from "./tipos_auditoria";

const INDICADORES: IndicadoresAuditoria = indicadores;
const PAGINA: PaginaAuditoria = consultas as PaginaAuditoria;
const DETALLE: DetalleAuditoria = detalle as DetalleAuditoria;

describe("fixtures de auditoría", () => {
  it("los indicadores suman por estado el total de consultas", () => {
    expect(Object.values(INDICADORES.por_estado).reduce((a, b) => a + b, 0)).toBe(INDICADORES.consultas);
    expect(INDICADORES.dias).toBe(30);
  });

  it("la lista incluye la consulta de prueba marcada y va de la más reciente a la más antigua", () => {
    expect(PAGINA.incluir_pruebas).toBe(true);
    expect(PAGINA.consultas.filter((c) => c.modo_prueba)).toHaveLength(1);
    const fechas = PAGINA.consultas.map((c) => c.fecha_hora_inicio);
    expect([...fechas].sort().reverse()).toEqual(fechas);
  });

  it("el detalle trae la solicitud, la verificación y los fragmentos con su origen", () => {
    const aprobado = DETALLE.intentos[DETALLE.intentos.length - 1];
    expect(aprobado.solicitud_enviada).not.toBeNull();
    expect(aprobado.verificacion.valida_citas).toBe(true);
    expect(aprobado.fragmentos.map((f) => f.origen)).toContain("PUNTERO");
    expect(JSON.stringify(DETALLE)).not.toMatch(/nombres_apellidos|numero_hc|dni|fecha_nacimiento/);
  });
});
