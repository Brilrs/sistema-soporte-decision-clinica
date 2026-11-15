// M05: tabla de evidencias citadas. El extracto se muestra literal, sin reformatear (pre-wrap),
// porque debe coincidir carácter a carácter con la fuente, incluidas las filas de tabla con «|».
// Una cita en inglés lleva lang="en" y, debajo, la traducción de apoyo rotulada.
import type { Cita } from "../../api/tipos_consulta";
import { ETIQUETA_TRADUCCION } from "../../consulta/textos";
import { VACIO, decimal } from "../../utilidades/formato";
import { idCita } from "./EnlaceCita";

function paginas(c: Cita): string | null {
  if (c.pagina_inicio === null) return null;
  return c.pagina_fin === null || c.pagina_fin === c.pagina_inicio ? `pág. ${c.pagina_inicio}` : `págs. ${c.pagina_inicio} a ${c.pagina_fin}`;
}

// Número de la etiqueta F-xx; una etiqueta sin número va al final.
function numeroEtiqueta(etiqueta: string): number {
  const m = /(\d+)$/.exec(etiqueta);
  return m ? Number(m[1]) : Number.POSITIVE_INFINITY;
}

// El backend entrega las citas en el orden del reranker; la tabla las muestra por etiqueta
// (F-01, F-02, F-03...) para que sea fácil ubicar la que menciona la recomendación.
export function ordenarPorEtiqueta(citas: Cita[]): Cita[] {
  return [...citas].sort((a, b) => numeroEtiqueta(a.etiqueta) - numeroEtiqueta(b.etiqueta)
    || a.etiqueta.localeCompare(b.etiqueta));
}

type Props = { citas: Cita[]; resaltada: string | null };

export default function TablaCitas({ citas, resaltada }: Props) {
  if (citas.length === 0) return <p className="texto-tenue">La respuesta no tiene citas.</p>;
  const ordenadas = ordenarPorEtiqueta(citas);
  return (
    <div className="tabla-contenedor tabla-citas__contenedor" tabIndex={0} role="region" aria-label="Tabla de evidencias citadas">
      <table className="tabla tabla-citas">
        <thead>
          <tr>
            <th scope="col">Cita</th>
            <th scope="col">Fragmento</th>
            <th scope="col">Fuente</th>
            <th scope="col">Relevancia</th>
          </tr>
        </thead>
        <tbody>
          {ordenadas.map((c) => {
            const pags = paginas(c);
            return (
              <tr key={c.etiqueta} id={idCita(c.etiqueta)} tabIndex={-1}
                  className={resaltada === c.etiqueta ? "tabla-citas__fila--resaltada" : undefined}>
                <th scope="row"><span className="cita-enlace cita-enlace--fija">{c.etiqueta}</span></th>
                <td>
                  <blockquote className="cita__extracto" lang={c.idioma}>{c.extracto}</blockquote>
                  {c.extracto_traducido && (
                    <div className="cita__traduccion" lang="es">
                      <span className="cita__traduccion-etiqueta">{c.etiqueta_traduccion || ETIQUETA_TRADUCCION}</span>
                      <p className="cita__traduccion-texto">{c.extracto_traducido}</p>
                    </div>
                  )}
                </td>
                <td className="tabla-citas__fuente">
                  <strong>{c.fuente ?? c.documento}</strong>
                  {c.fuente && c.fuente !== c.documento && <span className="texto-tenue">{c.documento}</span>}
                  {c.seccion && <span>{c.seccion}</span>}
                  {pags && <span className="texto-tenue">{pags}</span>}
                </td>
                <td className="tabla-citas__relevancia">{c.puntaje_reranker === null ? VACIO : decimal(c.puntaje_reranker, 3)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
