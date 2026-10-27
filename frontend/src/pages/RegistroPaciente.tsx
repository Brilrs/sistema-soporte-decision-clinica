// M03 · Registro del paciente (HU02, HU05): identificación, datos al nacer y primer tamizaje.
import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { mensajeError } from "../api/cliente";
import { pacientesApi } from "../api/pacientes";
import { useCatalogos } from "../api/useCatalogos";
import { CamposIdentificacion, CamposNacimiento, aEntradaPaciente, formPacienteVacio, pacienteCompleto,
  type FormPaciente } from "../components/CamposPaciente";
import FormularioTamizaje, { aEntradaTamizaje, erroresTamizaje, formTamizajeVacio,
  type FormTamizaje } from "../components/FormularioTamizaje";
import Migas from "../components/Migas";
import { avisoClasificacion } from "./avisos";

export default function RegistroPaciente() {
  const navegar = useNavigate();
  const { distritos, sintomas, error: errorCatalogos } = useCatalogos();
  const [paciente, setPaciente] = useState<FormPaciente>(formPacienteVacio);
  const [tamizaje, setTamizaje] = useState<FormTamizaje>(() => formTamizajeVacio());
  const [error, setError] = useState<string | null>(null);
  const [enviando, setEnviando] = useState(false);

  const completo = pacienteCompleto(paciente) && !!tamizaje.fecha_tamizaje;

  async function guardar(e: FormEvent) {
    e.preventDefault();
    const invalido = erroresTamizaje(tamizaje);
    if (invalido) {
      setError(invalido);
      return;
    }
    setError(null);
    setEnviando(true);
    try {
      const r = await pacientesApi.registrar({ ...aEntradaPaciente(paciente), tamizaje: aEntradaTamizaje(tamizaje) });
      navegar(`/pacientes/${r.id_paciente}/historial`, {
        replace: true,
        state: { aviso: `Paciente registrado. ${avisoClasificacion(r.tamizaje)}` },
      });
    } catch (err) {
      setError(mensajeError(err));
      setEnviando(false);
    }
  }

  return (
    <section>
      <Migas items={[{ texto: "Pacientes", ruta: "/pacientes" }, { texto: "Registro" }]} />
      <h1>Datos del paciente</h1>
      <p className="texto-tenue">Los campos con <span className="obligatorio">*</span> son necesarios para la evaluación</p>
      {errorCatalogos && <p className="alerta alerta--error" role="alert">{errorCatalogos}</p>}

      <form className="formulario" onSubmit={guardar} noValidate style={{ marginTop: "1.25rem" }}>
        <div className="tarjeta">
          <CamposIdentificacion valor={paciente} distritos={distritos}
                                cambiar={(c) => setPaciente((p) => ({ ...p, ...c }))} />
        </div>
        <div className="tarjeta">
          <h2>Datos clínicos y antropométricos</h2>
          <CamposNacimiento valor={paciente} fechaReferencia={tamizaje.fecha_tamizaje}
                            cambiar={(c) => setPaciente((p) => ({ ...p, ...c }))} />
          <FormularioTamizaje valor={tamizaje} sintomas={sintomas} fechaNacimiento={paciente.fecha_nacimiento}
                              mostrarEdad={false} cambiar={(c) => setTamizaje((t) => ({ ...t, ...c }))} />

          {error && <p className="alerta alerta--error" role="alert">{error}</p>}
          <BotonesGuardar enviando={enviando} habilitado={completo} cancelar={() => navegar("/pacientes")} />
        </div>
      </form>
    </section>
  );
}

// «Guardar y evaluar» abre la consulta clínica (M04), que se construye en el Sprint 2.
export function BotonesGuardar({ enviando, habilitado, cancelar }: { enviando: boolean; habilitado: boolean; cancelar: () => void }) {
  return (
    <div className="acciones">
      <button type="button" className="boton boton--neutro" onClick={cancelar} disabled={enviando}>Cancelar</button>
      <button type="submit" className="boton boton--secundario" disabled={enviando || !habilitado}>
        {enviando ? "Guardando…" : "Guardar"}
      </button>
      <span>
        <button type="button" className="boton boton--primario" disabled title="Disponible en el Sprint 2">
          Guardar y evaluar
        </button>
        <span className="nota-sprint" style={{ display: "block", textAlign: "right" }}>Disponible en el Sprint 2</span>
      </span>
    </div>
  );
}
