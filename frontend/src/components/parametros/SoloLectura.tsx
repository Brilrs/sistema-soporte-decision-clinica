// Secciones de solo lectura de M12 (parte E2): riesgo por clasificación (categoria_anemia, sin versionar)
// y los parámetros de recuperación, del modelo y de la indexación, que se cambian solo por migración.
import type { ParametroSistema, RiesgoCategoria } from "../../api/tipos_parametros";
import { fechaHora } from "../../utilidades/formato";
import EstadoVerificacion from "./EstadoVerificacion";
import { NIVELES, NOTA_MIGRACION, categoria } from "./textos";

export function SeccionRiesgo({ riesgo }: { riesgo: RiesgoCategoria[] }) {
  return (
    <section className="tarjeta tarjeta--ancha parametros__seccion" aria-labelledby="riesgo-titulo">
      <h2 id="riesgo-titulo">Riesgo por clasificación</h2>
      <p className="texto-tenue parametros__nota">Nivel de riesgo que se muestra al profesional según la clasificación. Solo lectura.</p>
      <table className="tabla tabla-apilable parametros__tabla">
        <thead>
          <tr><th scope="col">Clasificación</th><th scope="col">Nivel de riesgo</th><th scope="col">Derivación</th></tr>
        </thead>
        <tbody>
          {riesgo.map((r) => (
            <tr key={r.nombre}>
              <th scope="row" data-etiqueta="Clasificación">{categoria(r.nombre)}</th>
              <td data-etiqueta="Nivel de riesgo">
                <span className={`etiqueta etiqueta--riesgo-${r.nivel_riesgo}`}>{NIVELES[r.nivel_riesgo] ?? r.nivel_riesgo}</span>
              </td>
              <td data-etiqueta="Derivación">{r.requiere_derivacion ? "Requiere derivación" : "No requiere"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

export function SeccionParametros({ id, titulo, parametros }: { id: string; titulo: string; parametros: ParametroSistema[] }) {
  return (
    <section className="tarjeta tarjeta--ancha parametros__seccion" aria-labelledby={`${id}-titulo`}>
      <h2 id={`${id}-titulo`}>{titulo}</h2>
      <p className="texto-tenue parametros__nota">{NOTA_MIGRACION}</p>
      <table className="tabla tabla-apilable parametros__tabla">
        <thead>
          <tr><th scope="col">Parámetro</th><th scope="col">Valor</th><th scope="col">Estado</th><th scope="col">Rige desde</th></tr>
        </thead>
        <tbody>
          {parametros.map((p) => (
            <tr key={p.clave}>
              <th scope="row" data-etiqueta="Parámetro" className="parametros__descripcion">{p.descripcion}</th>
              <td data-etiqueta="Valor" className="parametros__valor-texto">{p.valor || "(vacío)"}</td>
              <td data-etiqueta="Estado"><EstadoVerificacion verificado={p.verificado} /></td>
              <td data-etiqueta="Rige desde">{fechaHora(p.vigente_desde)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
