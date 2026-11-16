// M08 · «Evaluaciones realizadas»: consultas clínicas del paciente hechas por el usuario
// autenticado (GET /api/pacientes/{id}/historial, campo consultas; el backend no lista las de
// otros profesionales), de la más reciente a la más antigua. Cada fila enlaza a /consultas/:id.
// La Hb sale del tamizaje de la consulta (por id_tamizaje); la decisión, de tipo_decision.
import { useId, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import type { TamizajeHistorial } from "../api/pacientes";
import type { ConsultaListada } from "../api/tipos_consulta";
import { TIPOS_DECISION } from "../consulta/textos";
import { VACIO, decimal, fechaHora } from "../utilidades/formato";
import { EtiquetaClasificacion, EtiquetaEstadoConsulta } from "./Etiquetas";

// Fecha local (aaaa-mm-dd) de una fecha y hora ISO, para compararla con <input type="date">.
export function fechaLocal(iso: string): string {
  const f = new Date(iso);
  return `${f.getFullYear()}-${String(f.getMonth() + 1).padStart(2, "0")}-${String(f.getDate()).padStart(2, "0")}`;
}

export function ordenarConsultas(consultas: ConsultaListada[]): ConsultaListada[] {
  return [...consultas].sort((a, b) => Date.parse(b.fecha_hora_inicio) - Date.parse(a.fecha_hora_inicio));
}

type Props = {
  consultas: ConsultaListada[];
  tamizajes: TamizajeHistorial[];
  realizaConsultas: boolean; // rol con REALIZAR_CONSULTA: si no, la lista viene vacía por diseño
};

export default function EvaluacionesRealizadas({ consultas, tamizajes, realizaConsultas }: Props) {
  const [dia, setDia] = useState("");
  const idFiltro = useId();
  const ordenadas = useMemo(() => ordenarConsultas(consultas), [consultas]);
  const visibles = dia ? ordenadas.filter((c) => fechaLocal(c.fecha_hora_inicio) === dia) : ordenadas;
  const hbDe = (c: ConsultaListada) => {
    const t = tamizajes.find((x) => x.id_tamizaje === c.id_tamizaje);
    return t?.hemoglobina_g_dl ? decimal(t.hemoglobina_g_dl) : VACIO;
  };

  return (
    <section className="tarjeta tarjeta--ancha evaluaciones" aria-labelledby="titulo-evaluaciones">
      <div className="encabezado-pagina">
        <div>
          <h2 id="titulo-evaluaciones">Evaluaciones realizadas</h2>
          {realizaConsultas && (
            <p className="texto-tenue evaluaciones__nota">Solo se muestran las consultas que usted realizó.</p>
          )}
        </div>
        {ordenadas.length > 0 && (
          <div className="evaluaciones__filtro">
            <label htmlFor={idFiltro}>Filtrar por fecha</label>
            <div className="evaluaciones__filtro-campos">
              <input id={idFiltro} type="date" value={dia} onChange={(e) => setDia(e.target.value)} />
              {dia && <button type="button" className="boton boton--neutro boton--chico" onClick={() => setDia("")}>Ver todas</button>}
            </div>
          </div>
        )}
      </div>

      {!realizaConsultas ? (
        <p className="vacio">Su rol no realiza consultas clínicas: aquí se listan las consultas de quien las realiza.</p>
      ) : ordenadas.length === 0 ? (
        <p className="vacio">Aún no realizó consultas clínicas para este paciente. Use «Nueva consulta» para iniciar una.</p>
      ) : visibles.length === 0 ? (
        <p className="vacio" role="status">No hay consultas en la fecha elegida.</p>
      ) : (
        <div className="tabla-contenedor evaluaciones__tabla" tabIndex={0} role="region" aria-label="Consultas del paciente">
          <table className="tabla tabla--compacta">
            <thead>
              <tr>
                <th scope="col">Fecha</th>
                <th scope="col">Hb</th>
                <th scope="col">Clasificación</th>
                <th scope="col">Consulta</th>
                <th scope="col">Resultado</th>
                <th scope="col">Decisión</th>
                <th scope="col"><span className="solo-lectores">Acciones</span></th>
              </tr>
            </thead>
            <tbody>
              {visibles.map((c) => {
                const cuando = fechaHora(c.fecha_hora_inicio);
                return (
                  <tr key={c.id_consulta}>
                    <td>{cuando}</td>
                    <td>{hbDe(c)}</td>
                    <td><EtiquetaClasificacion categoria={c.categoria} sinTexto="Sin clasificación" /></td>
                    <td className="evaluaciones__pregunta-celda">
                      <span className="evaluaciones__pregunta" title={c.texto_filtrado ?? undefined}>
                        {c.texto_filtrado || <span className="texto-tenue">Sin pregunta registrada</span>}
                      </span>
                    </td>
                    <td>
                      <EtiquetaEstadoConsulta estado={c.estado} />
                      {c.modo_prueba && <span className="etiqueta etiqueta--prueba">Prueba</span>}
                    </td>
                    <td>{c.tipo_decision ? TIPOS_DECISION[c.tipo_decision]?.etiqueta ?? c.tipo_decision : <span className="texto-tenue">Sin decisión</span>}</td>
                    <td className="evaluaciones__ver">
                      <Link className="boton boton--secundario boton--chico" to={`/consultas/${c.id_consulta}`}
                            aria-label={`Ver la consulta del ${cuando}`}>
                        Ver
                      </Link>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
