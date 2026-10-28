// M08 · Historial del paciente (HU04): evolución de la hemoglobina y tamizajes registrados.
// Las evaluaciones de consultas clínicas se agregan en el Sprint 2.
import { useEffect, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { mensajeError } from "../api/cliente";
import { pacientesApi, type Ficha, type Historial } from "../api/pacientes";
import { useAuth } from "../auth/AuthContext";
import { EtiquetaClasificacion, EtiquetaVigencia } from "../components/Etiquetas";
import GraficoHemoglobina from "../components/GraficoHemoglobina";
import Migas from "../components/Migas";
import { EDADES_GESTACIONALES, METODOS, SEXOS, decimal, edad, fecha, iniciales, siNo } from "../utilidades/formato";

export default function HistorialPaciente() {
  const { id = "" } = useParams();
  const navegar = useNavigate();
  const ubicacion = useLocation();
  const { tienePermiso } = useAuth();
  const puedeRegistrar = tienePermiso("REGISTRAR_PACIENTE");
  const [ficha, setFicha] = useState<Ficha | null>(null);
  const [historial, setHistorial] = useState<Historial | null>(null);
  const [error, setError] = useState<string | null>(null);
  const aviso = (ubicacion.state as { aviso?: string } | null)?.aviso;

  useEffect(() => {
    Promise.all([pacientesApi.ficha(id), pacientesApi.historial(id)])
      .then(([f, h]) => {
        setFicha(f);
        setHistorial(h);
      })
      .catch((e) => setError(mensajeError(e)));
  }, [id]);

  if (!ficha || !historial) {
    return error ? <p className="alerta alerta--error" role="alert">{error}</p> : <p className="cargando">Cargando…</p>;
  }

  return (
    <section>
      <Migas items={[{ texto: "Pacientes", ruta: "/pacientes" }, { texto: ficha.nombres_apellidos }]} />
      {aviso && <p className="alerta alerta--exito" role="status">{aviso}</p>}

      <div className="tarjeta tarjeta--ancha ficha-cabecera">
        <div className="ficha-cabecera__paciente">
          <span className="avatar avatar--grande">{iniciales(ficha.nombres_apellidos)}</span>
          <div>
            <h1>{ficha.nombres_apellidos}</h1>
            <span className="texto-tenue">
              HC <strong>{ficha.numero_hc}</strong> · <strong>{edad(ficha.edad_meses_actual)}</strong> · {SEXOS[ficha.sexo]}
            </span>
          </div>
        </div>
        <div className="acciones" style={{ marginTop: 0 }}>
          {puedeRegistrar && (
            <>
              <button className="boton boton--neutro" onClick={() => navegar(`/pacientes/${id}/editar`)}>Editar datos</button>
              <button className="boton boton--primario" onClick={() => navegar(`/pacientes/${id}/tamizajes/nuevo`)}>
                + Nuevo tamizaje
              </button>
            </>
          )}
          <button className="boton boton--secundario" disabled title="Disponible en el Sprint 2">Nueva consulta</button>
        </div>
      </div>

      <div className="tarjeta tarjeta--ancha">
        <dl className="datos-paciente">
          <div><dt>DNI</dt><dd>{ficha.dni}</dd></div>
          <div><dt>Fecha de nacimiento</dt><dd>{fecha(ficha.fecha_nacimiento)}</dd></div>
          <div><dt>Distrito</dt><dd>{ficha.distrito}, {ficha.provincia}</dd></div>
          <div><dt>Altitud</dt><dd>{ficha.altitud_msnm} m.s.n.m.</dd></div>
          <div><dt>Edad gestacional</dt><dd>{EDADES_GESTACIONALES[ficha.edad_gestacional_nacer]}</dd></div>
          <div><dt>Bajo peso al nacer</dt><dd>{siNo(ficha.bajo_peso_nacer)}</dd></div>
        </dl>
      </div>

      <div className="historial" style={{ marginTop: "1.25rem" }}>
        <div className="tarjeta">
          <h2>Evolución de la hemoglobina</h2>
          <GraficoHemoglobina tamizajes={historial.tamizajes} franjas={historial.franjas} />
        </div>

        <div className="tarjeta">
          <h2>Tamizajes registrados</h2>
          {historial.tamizajes.length === 0
            ? <p className="vacio">El paciente aún no tiene tamizajes.</p>
            : (
              <div className="tabla-contenedor">
                <table className="tabla">
                  <thead>
                    <tr><th>Fecha</th><th>Edad</th><th>Hb</th><th>Hb ajustada</th><th>Clasificación</th><th>Síntomas</th><th>Profesional</th></tr>
                  </thead>
                  <tbody>
                    {historial.tamizajes.map((t) => (
                      <tr key={t.id_tamizaje}>
                        <td>{fecha(t.fecha_tamizaje)}<EtiquetaVigencia vigente={t.vigente} /></td>
                        <td>{edad(t.edad_meses)}</td>
                        <td title={t.metodo_medicion ? METODOS[t.metodo_medicion] : undefined}>{decimal(t.hemoglobina_g_dl)}</td>
                        <td>{decimal(t.clasificacion?.hb_ajustada_g_dl)}</td>
                        <td title={t.motivo_sin_clasificacion ?? undefined}>
                          <EtiquetaClasificacion categoria={t.clasificacion?.categoria ?? null} />
                        </td>
                        <td>{t.sintomas.length ? t.sintomas.map((s) => s.detalle ? `${s.nombre} (${s.detalle})` : s.nombre).join(", ") : "Ninguno"}</td>
                        <td>{t.profesional}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          <h2 style={{ marginTop: "1.5rem" }}>Evaluaciones realizadas</h2>
          <p className="vacio">Las evaluaciones de las consultas clínicas estarán disponibles en el Sprint 2.</p>
        </div>
      </div>
    </section>
  );
}
