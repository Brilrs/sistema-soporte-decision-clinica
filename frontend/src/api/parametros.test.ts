// Capa de API de M12 (parte E1b): el PUT y la traducción de los errores del backend, con los fixtures
// que generan las pruebas del backend (tests/test_e1b_parametros.py). Sin API real.
import { afterEach, describe, expect, it, vi } from "vitest";
import confirmacion from "../__fixtures__/parametros_put_confirmacion.json";
import conflicto from "../__fixtures__/parametros_put_conflicto.json";
import cuerpo from "../__fixtures__/parametros_put_cuerpo.json";
import respuesta from "../__fixtures__/parametros_put_respuesta.json";
import sinCambios from "../__fixtures__/parametros_put_sin_cambios.json";
import validacion from "../__fixtures__/parametros_put_validacion.json";
import { guardarToken } from "./cliente";
import { ErrorEdicion, errorDeEdicion, parametrosApi } from "./parametros";
import type { EdicionVigencia, VigenciaEntrada } from "./tipos_parametros";

const json = (estado: number, datos: unknown) =>
  new Response(JSON.stringify(datos), { status: estado, headers: { "Content-Type": "application/json" } });

afterEach(() => vi.unstubAllGlobals());

describe("errores de la edición de parámetros", () => {
  it.each([
    [422, validacion, "VALIDACION"],
    [422, confirmacion, "REQUIERE_CONFIRMACION"],
    [422, sinCambios, "SIN_CAMBIOS"],
    [409, conflicto, "VERSION_DESACTUALIZADA"],
  ])("%i con %s se traduce a ErrorEdicion", async (estado, datos, codigo) => {
    const e = await errorDeEdicion(json(estado, datos));
    expect(e).toBeInstanceOf(ErrorEdicion);
    expect((e as ErrorEdicion).cuerpo.codigo).toBe(codigo);
    expect(e.message).toBe(datos.detail);
  });

  it("los campos con error y las advertencias quedan a mano", async () => {
    const v = (await errorDeEdicion(json(422, validacion))) as ErrorEdicion;
    expect(v.errores.map((x) => x.campo)).toEqual(["valor"]);
    const c = (await errorDeEdicion(json(422, confirmacion))) as ErrorEdicion;
    expect(c.advertencias[0].mensaje).toContain("60 días");
    expect(c.errores).toEqual([]);
  });

  it("423 del modo de evaluación", async () => {
    const e = (await errorDeEdicion(json(423, { detail: "El sistema está en modo de evaluación" }))) as ErrorEdicion;
    expect(e.cuerpo.codigo).toBe("MODO_EVALUACION");
    expect(e.estado).toBe(423);
  });
});

describe("PUT de la vigencia", () => {
  it("envía el cuerpo una vez y devuelve el grupo con la versión nueva", async () => {
    guardarToken("token-de-prueba");
    const f = vi.fn(async () => json(200, respuesta));
    vi.stubGlobal("fetch", f);
    const r: EdicionVigencia = await parametrosApi.guardarVigencia(cuerpo as VigenciaEntrada);
    expect(f).toHaveBeenCalledTimes(1);
    const [ruta, init] = f.mock.calls[0] as unknown as [string, RequestInit];
    expect(ruta).toBe("/api/parametros/vigencia-tamizaje");
    expect(init.method).toBe("PUT");
    expect(JSON.parse(String(init.body))).toEqual(cuerpo);
    expect(r.grupo.valor).toBe("45");
    expect(r.resumen.cambios[0].despues).toEqual({ valor: "45", verificado: false });
  });

  it("un 409 llega como ErrorEdicion con la versión actual", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => json(409, conflicto)));
    const e = await parametrosApi.guardarVigencia(cuerpo as VigenciaEntrada).catch((x) => x);
    expect(e).toBeInstanceOf(ErrorEdicion);
    expect(e.cuerpo).toEqual(conflicto);
  });
});
