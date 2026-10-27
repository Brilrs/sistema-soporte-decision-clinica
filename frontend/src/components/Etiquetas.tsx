// Etiquetas de clasificación de anemia y de vigencia del tamizaje.
import { CATEGORIAS } from "../utilidades/formato";

export function EtiquetaClasificacion({ categoria, sinTexto = "Sin evaluación" }: { categoria: string | null; sinTexto?: string }) {
  if (!categoria) return <span className="etiqueta etiqueta--sin">{sinTexto}</span>;
  return <span className={`etiqueta etiqueta--${categoria}`}>{CATEGORIAS[categoria] ?? categoria}</span>;
}

// La vigencia la calcula el servidor con el parámetro DIAS_VIGENCIA_TAMIZAJE.
export function EtiquetaVigencia({ vigente }: { vigente: boolean | null | undefined }) {
  if (vigente !== false) return null;
  return <span className="etiqueta etiqueta--no-vigente">No vigente</span>;
}
