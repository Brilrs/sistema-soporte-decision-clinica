// Tabla de pacientes de M02 (también se usa en el historial de consultas).
import { useNavigate } from "react-router-dom";
import type { PacienteListado } from "../api/pacientes";
import { VACIO, decimal, edad, fechaRelativa } from "../utilidades/formato";
import { EtiquetaClasificacion, EtiquetaVigencia } from "./Etiquetas";

export default function TablaPacientes({ pacientes, puedeRegistrar, vacio }: {
  pacientes: PacienteListado[];
  puedeRegistrar: boolean;
  vacio: string;
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
                            onClick={() => navegar(`/pacientes/${p.id_paciente}/historial`)}>Abrir</button>
                    {puedeRegistrar && (
                      <button className="boton boton--neutro boton--chico"
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
