// Tabla de pacientes de M02 (también se usa en el buscador de «Nueva consulta», /consultas/nueva).
import { useNavigate } from "react-router-dom";
import type { PacienteListado } from "../api/pacientes";
import { VACIO, decimal, edad, fechaRelativa } from "../utilidades/formato";
import { EtiquetaClasificacion, EtiquetaVigencia } from "./Etiquetas";

// «Abrir» lleva a la consulta clínica (M04) si se indica abrirConsulta (panel de pacientes y rol
// que realiza consultas); si no, al historial del paciente (M08). Con verHistorial se agrega además
// «Ver historial» (M08), como en el buscador de «Nueva consulta».
export default function TablaPacientes({ pacientes, puedeRegistrar, vacio, abrirConsulta = false, textoAbrir = "Abrir",
  verHistorial = false }: {
  pacientes: PacienteListado[];
  puedeRegistrar: boolean;
  vacio: string;
  abrirConsulta?: boolean;
  textoAbrir?: string; // «Nueva consulta» en el buscador de /consultas/nueva
  verHistorial?: boolean;
}) {
  const navegar = useNavigate();
  if (pacientes.length === 0) return <p className="vacio">{vacio}</p>;

  return (
    <div className="tabla-contenedor">
      <table className="tabla">
        <thead>
          <tr>
            <th>Paciente</th>
            <th>HC</th>
            <th>Edad</th>
            <th>Última Hb</th>
            <th>Última clasificación</th>
            <th>Último tamizaje</th>
            <th aria-label="Acciones" />
          </tr>
        </thead>
        <tbody>
          {pacientes.map((p) => {
            const t = p.ultimo_tamizaje;
            return (
              <tr key={p.id_paciente}>
                <td><strong>{p.nombres_apellidos}</strong></td>
                <td>{p.numero_hc}</td>
                <td>{edad(p.edad_meses_actual)}</td>
                <td>{t?.hemoglobina_g_dl ? `${decimal(t.hemoglobina_g_dl)} g/dL` : VACIO}</td>
                <td><EtiquetaClasificacion categoria={t?.categoria ?? null} /></td>
                <td>
                  {t ? fechaRelativa(t.fecha_tamizaje, t.fecha_registro) : VACIO}
                  <EtiquetaVigencia vigente={t?.vigente} />
                </td>
                <td>
                  <div className="tabla__acciones">
                    <button className="boton boton--secundario boton--chico"
                            aria-label={`${textoAbrir}: ${p.nombres_apellidos}`}
                            onClick={() => navegar(`/pacientes/${p.id_paciente}/${abrirConsulta ? "consulta" : "historial"}`)}>
                      {textoAbrir}
                    </button>
                    {verHistorial && (
                      <button className="boton boton--neutro boton--chico" aria-label={`Ver historial: ${p.nombres_apellidos}`}
                              onClick={() => navegar(`/pacientes/${p.id_paciente}/historial`)}>Ver historial</button>
                    )}
                    {puedeRegistrar && (
                      <button className="boton boton--neutro boton--chico" aria-label={`Nuevo tamizaje: ${p.nombres_apellidos}`}
                              onClick={() => navegar(`/pacientes/${p.id_paciente}/tamizajes/nuevo`)}>+ Tamizaje</button>
                    )}
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
