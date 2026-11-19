// Vista previa del reporte (M09): el contenido estructurado de GET .../reportes/vista-previa
// dibujado como una hoja, en el mismo orden que el PDF. El número se asigna al generar.
import type { BloqueReporte, VistaPreviaReporte } from "../../api/tipos_reporte";
import { fechaHora } from "../../utilidades/formato";

function Bloque({ b }: { b: BloqueReporte }) {
  return (
    <section className="hoja__bloque" aria-label={b.titulo}>
      <h3 className="hoja__titulo-bloque">{b.titulo}</h3>
      {b.campos.length > 0 && (
        <dl className="hoja__campos">
          {b.campos.map((c, i) => (
            <div key={i}>
              <dt>{c.etiqueta}</dt>
              <dd>{c.valor}</dd>
            </div>
          ))}
        </dl>
      )}
      {b.parrafos.map((p, i) => <p key={i} className="hoja__parrafo">{p}</p>)}
      {b.items.length > 0 && (
        <ul className="hoja__items">
          {b.items.map((item, i) => (
            <li key={i}>
              {item.texto}
              {item.detalle.length > 0 && (
                <ul className="hoja__detalle">
                  {item.detalle.map((d, j) => <li key={j}>{d}</li>)}
                </ul>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

export default function DocumentoReporte({ vista, numero }: { vista: VistaPreviaReporte; numero?: string }) {
  return (
    <article className="hoja" aria-label="Vista previa del documento">
      <header className="hoja__cabecera">
        <div>
          <p className="hoja__titulo">{vista.titulo}</p>
          <p className="hoja__establecimiento">{vista.establecimiento}</p>
        </div>
        <p className="hoja__numero">{numero ? `N.° ${numero}` : "N.° se asigna al generar"}</p>
      </header>
      {vista.avisos.length > 0 && (
        <ul className="hoja__avisos">
          {vista.avisos.map((a) => <li key={a}>{a}</li>)}
        </ul>
      )}
      {vista.introduccion && <p className="hoja__parrafo">{vista.introduccion}</p>}
      {vista.bloques.map((b, i) => <Bloque key={`${b.seccion}-${i}`} b={b} />)}
      <p className="hoja__final">{vista.frase_final}</p>
      <p className="hoja__pie">Generado por: {vista.generado_por} · Consulta del {fechaHora(vista.fecha_consulta)}</p>
      {vista.firma && (
        <div className="hoja__firma">
          <span className="hoja__linea" aria-hidden="true" />
          <span>Firma y sello del profesional</span>
        </div>
      )}
    </article>
  );
}
