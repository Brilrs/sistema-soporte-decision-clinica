// M03 · Registro del paciente (HU02, HU05): identificación, datos al nacer y primer tamizaje.
import { useRef, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { mensajeError } from "../api/cliente";
import { pacientesApi } from "../api/pacientes";
import { useCatalogos } from "../api/useCatalogos";
import { CamposIdentificacion, CamposNacimiento, aEntradaPaciente, formPacienteVacio, pacienteCompleto,
  type FormPaciente } from "../components/CamposPaciente";
import FormularioTamizaje, { aEntradaTamizaje, erroresTamizaje, formTamizajeVacio,
  type FormTamizaje } from "../components/FormularioTamizaje";
import Migas from "../components/Migas";
import { useAuth } from "../auth/AuthContext";
import { avisoClasificacion } from "./avisos";
import { useTituloPagina } from "../utilidades/useTituloPagina";

export default function RegistroPaciente() {
  const { tienePermiso } = useAuth();
  useTituloPagina("Registro del paciente");
  const navegar = useNavigate();
  const { distritos, sintomas, error: errorCatalogos } = useCatalogos();
  const [paciente, setPaciente] = useState<FormPaciente>(formPacienteVacio);
  const [tamizaje, setTamizaje] = useState<FormTamizaje>(() => formTamizajeVacio());
  const [error, setError] = useState<string | null>(null);
  const [enviando, setEnviando] = useState(false);
  // «Guardar y evaluar» abre la consulta clínica (M04) del paciente nuevo.
  const evaluar = useRef(false);
  const puedeEvaluar = tienePermiso("REALIZAR_CONSULTA");

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
      const aviso = `Paciente registrado. ${avisoClasificacion(r.tamizaje)}`;
      navegar(`/pacientes/${r.id_paciente}/${evaluar.current && puedeEvaluar ? "consulta" : "historial"}`,
              { replace: true, state: { aviso } });
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
          <BotonesGuardar enviando={enviando} habilitado={completo} cancelar={() => navegar("/pacientes")}
                          alElegir={puedeEvaluar ? (e) => (evaluar.current = e) : undefined} />
        </div>
      </form>
    </section>
  );
}

// Botones de M03 y M14. «Guardar» y «Guardar y evaluar» envían el mismo formulario; el segundo
// avisa antes (alElegirEvaluar) para que, al guardar, se abra la consulta clínica (M04) en lugar
// del historial. Sin evaluar (rol sin REALIZAR_CONSULTA), solo se ofrece «Guardar».
export function BotonesGuardar({ enviando, habilitado, cancelar, alElegir }: {
  enviando: boolean;
  habilitado: boolean;
  cancelar: () => void;
  alElegir?: (evaluar: boolean) => void;
}) {
  return (
    <div className="acciones">
      <button type="button" className="boton boton--neutro" onClick={cancelar} disabled={enviando}>Cancelar</button>
      <button type="submit" className={`boton ${alElegir ? "boton--secundario" : "boton--primario boton--auto"}`}
              disabled={enviando || !habilitado} onClick={() => alElegir?.(false)}>
        {enviando ? "Guardando…" : "Guardar"}
      </button>
      {alElegir && (
        <button type="submit" className="boton boton--primario boton--auto" disabled={enviando || !habilitado}
                onClick={() => alElegir(true)}>
          Guardar y evaluar
        </button>
      )}
    </div>
  );
}
