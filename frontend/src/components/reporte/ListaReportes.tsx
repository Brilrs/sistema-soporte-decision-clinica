// «Reportes generados de esta consulta» (M09): número, destino, fecha y huella de cada reporte
// emitido (GET .../reportes). Los PDF no se guardan, así que no hay descarga de los anteriores.
import type { ReporteListado } from "../../api/tipos_reporte";
import { fechaHora } from "../../utilidades/formato";
import { AYUDA_REPORTES_ANTERIORES, DESTINOS } from "./textos";

type Props = {
  reportes: ReporteListado[] | null; // null: cargando
  error: string | null;
  reintentar: () => void;
};

export default function ListaReportes({ reportes, error, reintentar }: Props) {
  return (
    <section className="tarjeta tarjeta--ancha reporte__lista" aria-labelledby="titulo-reportes-generados">
      <h2 id="titulo-reportes-generados">Reportes generados de esta consulta</h2>
      <p className="texto-tenue reporte__ayuda">{AYUDA_REPORTES_ANTERIORES}</p>
      {error ? (
        <div className="alerta alerta--error" role="alert">
          <p className="alerta__texto">No se pudo cargar la lista de reportes. {error}</p>
          <button type="button" className="boton boton--secundario boton--chico" onClick={reintentar}>Reintentar</button>
        </div>
      ) : reportes === null ? (
        <p className="vacio" role="status">Cargando reportes…</p>
      ) : reportes.length === 0 ? (
        <p className="vacio">Aún no se generó ningún reporte de esta consulta.</p>
      ) : (
        <ul className="reporte__emitidos" aria-label="Reportes emitidos">
          {reportes.map((r) => (
            <li key={r.numero_reporte} className="reporte__emitido">
              <p className="reporte__emitido-cabecera">
                <strong>{r.numero_reporte}</strong>
                <span className={`etiqueta etiqueta--destino-${r.destino}`}>{DESTINOS[r.destino]?.etiqueta ?? r.destino}</span>
                <span className="texto-tenue">{fechaHora(r.fecha_generacion)}</span>
              </p>
              <p className="reporte__huella">
                <span className="texto-tenue">SHA-256: </span>
                <code>{r.hash_documento ?? "sin dato"}</code>
              </p>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
