// HU04 · Corregir los datos permanentes y de identidad del paciente.
// Solo se envían los campos modificados; los tamizajes y sus clasificaciones no cambian.
import { useEffect, useState, type FormEvent } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { mensajeError } from "../api/cliente";
import { pacientesApi, type Ficha, type PacienteEntrada } from "../api/pacientes";
import { useCatalogos } from "../api/useCatalogos";
import { CamposIdentificacion, CamposNacimiento, aEntradaPaciente, formPacienteDesdeFicha, pacienteCompleto,
  type FormPaciente } from "../components/CamposPaciente";
import Migas from "../components/Migas";

export default function EditarPaciente() {
  const { id = "" } = useParams();
  const navegar = useNavigate();
  const { distritos, error: errorCatalogos } = useCatalogos();
  const [ficha, setFicha] = useState<Ficha | null>(null);
  const [form, setForm] = useState<FormPaciente | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [enviando, setEnviando] = useState(false);

  useEffect(() => {
    pacientesApi.ficha(id)
      .then((f) => {
        setFicha(f);
        setForm(formPacienteDesdeFicha(f));
      })
      .catch((e) => setError(mensajeError(e)));
  }, [id]);

  if (!ficha || !form) {
    return error ? <p className="alerta alerta--error" role="alert">{error}</p> : <p className="cargando">Cargando…</p>;
  }

  const original = aEntradaPaciente(formPacienteDesdeFicha(ficha));
  const actual = aEntradaPaciente(form);
  const cambios = Object.fromEntries(
    (Object.keys(actual) as (keyof PacienteEntrada)[])
      .filter((k) => actual[k] !== original[k])
      .map((k) => [k, actual[k]]),
  ) as Partial<PacienteEntrada>;
  const hayCambios = Object.keys(cambios).length > 0;

  async function guardar(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setEnviando(true);
    try {
      await pacientesApi.actualizar(id, cambios);
      navegar(`/pacientes/${id}/historial`, { replace: true, state: { aviso: "Datos del paciente actualizados." } });
    } catch (err) {
      setError(mensajeError(err));
      setEnviando(false);
    }
  }

  const cambiar = (c: Partial<FormPaciente>) => setForm((f) => (f ? { ...f, ...c } : f));

  return (
    <section>
      <Migas items={[{ texto: "Pacientes", ruta: "/pacientes" },
                     { texto: ficha.nombres_apellidos, ruta: `/pacientes/${id}/historial` }, { texto: "Editar datos" }]} />
      <h1>Editar datos del paciente</h1>
      <p className="texto-tenue">
        Corrija los datos permanentes. Los tamizajes ya registrados y sus clasificaciones no se modifican.
      </p>
      {errorCatalogos && <p className="alerta alerta--error" role="alert">{errorCatalogos}</p>}

      <form className="formulario" onSubmit={guardar} noValidate style={{ marginTop: "1.25rem" }}>
        <div className="tarjeta">
          <CamposIdentificacion valor={form} distritos={distritos} cambiar={cambiar} />
        </div>
        <div className="tarjeta">
          <h2>Datos al nacer</h2>
          <CamposNacimiento valor={form} cambiar={cambiar} />
          {error && <p className="alerta alerta--error" role="alert">{error}</p>}
          <div className="acciones">
            <button type="button" className="boton boton--neutro" disabled={enviando}
                    onClick={() => navegar(`/pacientes/${id}/historial`)}>Cancelar</button>
            <button type="submit" className="boton boton--primario" disabled={enviando || !hayCambios || !pacienteCompleto(form)}>
              {enviando ? "Guardando…" : "Guardar cambios"}
            </button>
          </div>
        </div>
      </form>
    </section>
  );
}
