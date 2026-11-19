// Parámetros clínicos (M12, HU14; Sprint 3, partes E1a y E1b): llamadas a las rutas de lectura y de
// edición. Contrato: docs/contrato_parametros.md. Tipos: ./tipos_parametros.ts. La pantalla es la
// parte E2. Los PUT devuelven un ErrorEdicion con el código del backend (VALIDACION,
// REQUIERE_CONFIRMACION, SIN_CAMBIOS, VERSION_DESACTUALIZADA o MODO_EVALUACION) para que la pantalla
// muestre los campos, las advertencias o el aviso de recargar.
import { ErrorApi, api, cabecerasCon, revisarSesion } from "./cliente";
import type {
  AjusteAltitudEntrada,
  CampoMensaje,
  EdicionAjusteAltitud,
  EdicionPuntosCorte,
  EdicionVigencia,
  ErrorEdicionCuerpo,
  GrupoHistorial,
  HuellaConfiguracion,
  PaginaHistorial,
  Parametros,
  PuntosCorteEntrada,
  VigenciaEntrada,
} from "./tipos_parametros";

export class ErrorEdicion extends ErrorApi {
  constructor(estado: number, public cuerpo: ErrorEdicionCuerpo) {
    super(estado, cuerpo.detail);
  }

  get errores(): CampoMensaje[] {
    return this.cuerpo.codigo === "VALIDACION" ? this.cuerpo.errores : [];
  }

  get advertencias(): CampoMensaje[] {
    return this.cuerpo.codigo === "REQUIERE_CONFIRMACION" ? this.cuerpo.advertencias : [];
  }
}

// Traduce una respuesta de error de un PUT a ErrorEdicion (o ErrorApi si no trae el formato esperado).
export async function errorDeEdicion(respuesta: Response): Promise<ErrorApi> {
  let datos: Record<string, unknown> = {};
  try {
    datos = await respuesta.json();
  } catch {
    /* sin cuerpo JSON */
  }
  const detail = typeof datos.detail === "string" ? datos.detail : "No se pudo completar la operación";
  if (respuesta.status === 423) return new ErrorEdicion(423, { codigo: "MODO_EVALUACION", detail });
  if (typeof datos.codigo === "string") return new ErrorEdicion(respuesta.status, { ...datos, detail } as ErrorEdicionCuerpo);
  if (respuesta.status === 422 && Array.isArray(datos.errores)) {
    return new ErrorEdicion(422, { codigo: "VALIDACION", detail, errores: datos.errores as CampoMensaje[] });
  }
  return new ErrorApi(respuesta.status, detail);
}

async function guardar<T>(ruta: string, cuerpo: unknown): Promise<T> {
  const opciones: RequestInit = { method: "PUT", body: JSON.stringify(cuerpo), cache: "no-store" };
  const cabeceras = cabecerasCon(opciones);
  const respuesta = await fetch(ruta, { ...opciones, headers: cabeceras });
  revisarSesion(respuesta, cabeceras);
  if (!respuesta.ok) throw await errorDeEdicion(respuesta);
  return respuesta.json() as Promise<T>;
}

export function parametrosHistorial(grupo: GrupoHistorial | null, limite = 20, desplazamiento = 0): string {
  const p = new URLSearchParams({ limite: String(limite), desplazamiento: String(desplazamiento) });
  if (grupo) p.set("grupo", grupo);
  return `?${p.toString()}`;
}

export const parametrosApi = {
  leer: (senal?: AbortSignal) => api<Parametros>("/api/parametros", { signal: senal, cache: "no-store" }),
  historial: (grupo: GrupoHistorial | null, limite = 20, desplazamiento = 0, senal?: AbortSignal) =>
    api<PaginaHistorial>(`/api/parametros/historial${parametrosHistorial(grupo, limite, desplazamiento)}`,
                         { signal: senal, cache: "no-store" }),
  huella: (senal?: AbortSignal) => api<HuellaConfiguracion>("/api/parametros/huella", { signal: senal, cache: "no-store" }),
  guardarPuntosCorte: (cuerpo: PuntosCorteEntrada) => guardar<EdicionPuntosCorte>("/api/parametros/puntos-corte", cuerpo),
  guardarAjusteAltitud: (cuerpo: AjusteAltitudEntrada) =>
    guardar<EdicionAjusteAltitud>("/api/parametros/ajuste-altitud", cuerpo),
  guardarVigencia: (cuerpo: VigenciaEntrada) => guardar<EdicionVigencia>("/api/parametros/vigencia-tamizaje", cuerpo),
};
