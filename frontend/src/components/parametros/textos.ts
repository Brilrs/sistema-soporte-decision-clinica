// Textos y cálculos de M12 «Parámetros clínicos» (Sprint 3, parte E2).
// Los valores de Hb y de ajuste se manejan en décimas enteras (10,9 g/dL = 109) para que la suma de
// 0,1 y las comparaciones sean exactas: nunca 10.900000001. Se escribe con coma o punto y se muestra
// con decimal() (punto, como en el resto de la aplicación).
import { CATEGORIAS, decimal } from "../../utilidades/formato";

export const NOTA_EFECTO =
  "Los tamizajes ya registrados conservan su clasificación. Un cambio de puntos de corte o de ajuste por altitud se aplica a los tamizajes nuevos. Un cambio de la vigencia del tamizaje se aplica desde la consulta siguiente.";
export const AVISO_EVALUACION =
  "El sistema está en modo de evaluación: los parámetros no se pueden modificar hasta que termine la evaluación";
export const AVISO_SOLO_LECTURA = "Solo lectura: su rol puede consultar los parámetros pero no modificarlos";
export const AVISO_PENDIENTES = "Valores pendientes de verificar contra la norma";
export const NOTA_MIGRACION = "Se cambian solo por migración, con medición.";
export const SIN_LIMITE = "sin límite";
export const MOTIVO_MIN = 10;
export const MOTIVO_MAX = 500;
// Reglas de la vigencia en el servidor (docs/contrato_parametros.md): de 7 a 90 días, con confirmación
// escrita por encima de 60. Se combinan con valor_minimo y valor_maximo del GET.
export const VIGENCIA_MIN = 7;
export const VIGENCIA_MAX = 90;
export const VIGENCIA_ADVERTENCIA = 60;

export type GrupoEditable = "puntos_corte" | "ajuste_altitud" | "vigencia_tamizaje";
export const TITULOS: Record<GrupoEditable, string> = {
  puntos_corte: "Puntos de corte de hemoglobina",
  ajuste_altitud: "Ajuste por altitud",
  vigencia_tamizaje: "Vigencia del tamizaje",
};
export const GRUPOS_HISTORIAL: Record<string, string> = {
  puntos_corte: "Puntos de corte",
  ajuste_altitud: "Ajuste por altitud",
  vigencia_tamizaje: "Vigencia del tamizaje",
  recuperacion: "Recuperación",
  modelo: "Modelo",
  indexacion: "Indexación",
};
export const COMPONENTES_HUELLA: Record<string, string> = {
  puntos_corte: "Puntos de corte",
  ajuste_altitud: "Ajuste por altitud",
  categorias: "Riesgo por clasificación",
  parametros_sistema: "Parámetros del sistema",
  indexacion: "Guías indexadas",
  version_prompt: "Versión del prompt",
};
export const NIVELES: Record<string, string> = { BAJO: "Bajo", MODERADO: "Moderado", ALTO: "Alto", MUY_ALTO: "Muy alto" };

export const categoria = (c: string) => CATEGORIAS[c] ?? c;

// --- Décimas -------------------------------------------------------------------
export function aDecimas(v: number | null): number | null {
  return v === null ? null : Math.round(v * 10);
}

export function deDecimas(d: number | null): number | null {
  return d === null ? null : d / 10;
}

// «9,4», «9.4» o «9» en décimas; null si no es un número con un decimal como máximo.
export function leerDecimas(texto: string): number | null {
  const limpio = texto.trim().replace(",", ".");
  const m = /^(\d{1,3})(?:\.(\d))?$/.exec(limpio);
  if (!m) return null;
  return Number(m[1]) * 10 + (m[2] ? Number(m[2]) : 0);
}

export function mostrarDecimas(d: number | null): string {
  return d === null ? SIN_LIMITE : decimal(d / 10);
}

export function textoDecimas(d: number | null): string {
  return d === null ? "" : decimal(d / 10);
}

// Etiqueta legible de un elemento del historial («6 a 23 meses · ANEMIA_LEVE» → «6 a 23 meses · Anemia leve»).
export function elementoLegible(elemento: string, descripciones: Record<string, string>): string {
  if (descripciones[elemento]) return descripciones[elemento];
  return elemento.replace(/\b(SIN_ANEMIA|ANEMIA_LEVE|ANEMIA_MODERADA|ANEMIA_SEVERA)\b/, (c) => categoria(c));
}
