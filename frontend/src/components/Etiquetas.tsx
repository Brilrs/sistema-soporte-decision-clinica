// Etiquetas de clasificación de anemia, de vigencia del tamizaje y de estado de una consulta.
import { CATEGORIAS, ESTADOS_CONSULTA } from "../utilidades/formato";

export function EtiquetaClasificacion({ categoria, sinTexto = "Sin evaluación" }: { categoria: string | null; sinTexto?: string }) {
  if (!categoria) return <span className="etiqueta etiqueta--sin">{sinTexto}</span>;
  return <span className={`etiqueta etiqueta--${categoria}`}>{CATEGORIAS[categoria] ?? categoria}</span>;
}

// La vigencia la calcula el servidor con el parámetro DIAS_VIGENCIA_TAMIZAJE.
export function EtiquetaVigencia({ vigente }: { vigente: boolean | null | undefined }) {
  if (vigente !== false) return null;
  return <span className="etiqueta etiqueta--no-vigente">No vigente</span>;
}

// Estado de una consulta (M08 y lista de consultas previas): texto y color; el color nunca es la
// única señal porque la etiqueta siempre lleva el texto.
export function EtiquetaEstadoConsulta({ estado }: { estado: string }) {
  return <span className={`etiqueta etiqueta--estado-${estado}`}>{ESTADOS_CONSULTA[estado] ?? estado}</span>;
}
