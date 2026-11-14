// Panel «Contexto de la sesión» de M04: los datos que el sistema considera en la consulta y las
// consultas previas del usuario para este paciente. Solo lectura: M04 no captura datos clínicos.
import { Link } from "react-router-dom";
import type { TamizajeHistorial } from "../api/pacientes";
import type { ConsultaListada } from "../api/tipos_consulta";
import { CATEGORIAS, ESTADOS_CONSULTA, decimal, fecha, fechaHora } from "../utilidades/formato";
import { EtiquetaClasificacion } from "./Etiquetas";

function antecedentes(t: TamizajeHistorial): string {
  const partes: string[] = [];
  if (t.lactancia_materna_actual !== null) partes.push(t.lactancia_materna_actual ? "Lactancia materna actual" : "Sin lactancia materna");
  if (t.recibe_suplementacion_hierro !== null)
    partes.push(t.recibe_suplementacion_hierro ? "Recibe suplementación con hierro" : "Sin suplementación con hierro");
  if (t.parasitosis_reciente) partes.push("Parasitosis reciente");
  return partes.length ? partes.join(" · ") : "No registrados";
}

export default function ContextoSesion({ tamizajes, consultas, errorConsultas }: {
  tamizajes: TamizajeHistorial[];
  consultas: ConsultaListada[] | null;
  errorConsultas: string | null;
}) {
  const [actual, anterior] = tamizajes;
  return (
    <aside className="tarjeta contexto" aria-labelledby="titulo-contexto">
      <h2 id="titulo-contexto">Contexto de la sesión</h2>
      <p className="texto-tenue">El sistema considera estos datos en la consulta</p>
      {!actual ? (
        <p className="alerta alerta--aviso">El paciente aún no tiene tamizajes. Registre uno para hacer la consulta.</p>
      ) : (
        <dl className="contexto__datos">
          <dt>Tamizaje en uso</dt>
          <dd>
            <strong>{fecha(actual.fecha_tamizaje)}</strong>{" "}
            {actual.vigente
              ? <span className="etiqueta etiqueta--vigente">Vigente</span>
              : <span className="etiqueta etiqueta--no-vigente">No vigente</span>}
          </dd>
          <dt>Clasificación calculada</dt>
          <dd>
            <EtiquetaClasificacion categoria={actual.clasificacion?.categoria ?? null} sinTexto="Sin clasificación" />
            {actual.clasificacion && <> Hb ajustada {decimal(actual.clasificacion.hb_ajustada_g_dl)} g/dL</>}
          </dd>
          <dt>Síntomas</dt>
          <dd>{actual.sintomas.length ? actual.sintomas.map((s) => s.nombre).join(", ") : "Ninguno"}</dd>
          <dt>Antecedentes</dt>
          <dd>{antecedentes(actual)}</dd>
          <dt>Tamizaje anterior</dt>
          <dd>
            {anterior
              ? [
                  fecha(anterior.fecha_tamizaje),
                  anterior.hemoglobina_g_dl ? `Hb ${decimal(anterior.hemoglobina_g_dl)} g/dL` : null,
                  anterior.clasificacion ? CATEGORIAS[anterior.clasificacion.categoria] ?? anterior.clasificacion.categoria : null,
                ].filter(Boolean).join(" · ")
              : "Ninguno"}
          </dd>
        </dl>
      )}
      <h3 className="contexto__subtitulo">Sus consultas previas de este paciente</h3>
      {errorConsultas ? (
        <p className="texto-tenue">{errorConsultas}</p>
      ) : consultas === null ? (
        <p className="texto-tenue">Cargando…</p>
      ) : consultas.length === 0 ? (
        <p className="contexto__vacio">Ninguna</p>
      ) : (
        <ul className="contexto__consultas">
          {consultas.slice(0, 5).map((c) => (
            <li key={c.id_consulta}>
              <Link to={`/consultas/${c.id_consulta}`}>{fechaHora(c.fecha_hora_inicio)}</Link>
              {" · "}{ESTADOS_CONSULTA[c.estado] ?? c.estado}
              {c.modo_prueba && <span className="etiqueta etiqueta--prueba">Prueba</span>}
              {c.texto_filtrado && <span className="contexto__pregunta">{c.texto_filtrado}</span>}
            </li>
          ))}
        </ul>
      )}
      <p className="contexto__nota">Nombre, DNI e historia clínica no se envían al servicio de generación.</p>
    </aside>
  );
}
