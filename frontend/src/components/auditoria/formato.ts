// Formatos y textos de M13 (auditoría y trazabilidad). Números con el criterio es-PE de la aplicación.
import type { IntentoAuditado } from "../../api/tipos_auditoria";
import { VACIO, decimal, segundos } from "../../utilidades/formato";

export const NOTA_SIN_PRUEBAS = "No incluye consultas de prueba";
export const NOTA_SIN_IDENTIFICADORES = "Sin datos que identifiquen al paciente";

export function entero(n: number | null | undefined): string {
  return n === null || n === undefined ? VACIO : n.toLocaleString("es-PE");
}

export function consultas(n: number): string {
  return `${entero(n)} ${n === 1 ? "consulta" : "consultas"}`;
}

export function usd(n: number | null | undefined, decimales = 2): string {
  return n === null || n === undefined ? VACIO : `US$ ${decimal(n, decimales)}`;
}

export function latencia(ms: number | null | undefined): string {
  return ms === null || ms === undefined ? VACIO : segundos(ms);
}

export function porcentaje(n: number | null | undefined): string | null {
  return n === null || n === undefined ? null : `${decimal(n)} %`;
}

// Resultado de un control de la verificación: true, false o null (no se llegó a evaluar).
export function resultadoControl(v: boolean | null): { texto: string; clase: string } {
  if (v === true) return { texto: "Cumplido", clase: "cumplido" };
  if (v === false) return { texto: "No cumplido", clase: "no-cumplido" };
  return { texto: "No evaluado", clase: "no-evaluado" };
}

export const VERIFICACIONES: { clave: "valida_citas" | "valida_consistencia" | "valida_evidencia"; nombre: string }[] = [
  { clave: "valida_citas", nombre: "6.1 Citas textuales" },
  { clave: "valida_consistencia", nombre: "6.2 Consistencia y dosis" },
  { clave: "valida_evidencia", nombre: "6.3 Suficiencia de la evidencia" },
];

export const BUSQUEDAS: Record<string, string> = { INICIAL: "Búsqueda inicial", AMPLIADA: "Búsqueda ampliada" };

export const RESULTADOS_INTENTO: Record<string, string> = {
  APROBADO: "Aprobado",
  REINTENTO: "Reintento",
  EVIDENCIA_INSUFICIENTE: "Evidencia insuficiente",
  ERROR: "Error",
};

export function controlPrevio(i: IntentoAuditado): string {
  if (i.control_identificadores === true) return "Aprobado: la solicitud no tenía identificadores";
  if (i.control_identificadores === false) return "Bloqueado: la solicitud no se envió";
  return "Sin control (no se armó una solicitud)";
}

export function modeloYPrompt(modelo: string | null, prompt: string | null): string {
  if (!modelo) return "Sin llamada al modelo";
  return prompt ? `${modelo} · prompt ${prompt}` : modelo;
}

export function paginas(inicio: number | null, fin: number | null): string {
  if (inicio === null) return VACIO;
  return fin === null || fin === inicio ? `p. ${inicio}` : `pp. ${inicio} a ${fin}`;
}
