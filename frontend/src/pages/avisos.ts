// Mensajes de confirmación tras guardar. Solo contienen la clasificación, nunca datos de identidad.
import type { Evaluacion } from "../api/pacientes";
import { CATEGORIAS, decimal } from "../utilidades/formato";

export function avisoClasificacion(evaluacion: Evaluacion | null): string {
  if (!evaluacion) return "No se registró tamizaje.";
  const c = evaluacion.clasificacion;
  if (!c) return `Tamizaje guardado sin clasificación: ${evaluacion.motivo_sin_clasificacion ?? "faltan datos"}.`;
  return `Clasificación: ${CATEGORIAS[c.categoria] ?? c.categoria} (Hb ajustada ${decimal(c.hb_ajustada_g_dl)} g/dL).`;
}
