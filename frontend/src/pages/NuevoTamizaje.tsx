// M14 · Nuevo tamizaje de un paciente registrado (HU18). Los datos permanentes se muestran
// en solo lectura; el tamizaje anterior se conserva en el historial y no se reemplaza.
import { useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { mensajeError } from "../api/cliente";
import { pacientesApi, type Ficha, type TamizajeHistorial, type VistaPrevia } from "../api/pacientes";
import { useCatalogos } from "../api/useCatalogos";
import { useAuth } from "../auth/AuthContext";
import { EtiquetaClasificacion } from "../components/Etiquetas";
import FormularioTamizaje, { aEntradaTamizaje, erroresTamizaje, formTamizajeVacio,
  type FormTamizaje } from "../components/FormularioTamizaje";
import Migas from "../components/Migas";
import { EDADES_GESTACIONALES, SEXOS, decimal, fecha, fechaHora, leerDecimal, siNo } from "../utilidades/formato";
import { avisoClasificacion } from "./avisos";
import { BotonesGuardar } from "./RegistroPaciente";

const ESPERA_VISTA_PREVIA_MS = 500;

export default function NuevoTamizaje() {
  const { id = "" } = useParams();
  const navegar = useNavigate();
  const { tienePermiso } = useAuth();
  const { sintomas, error: errorCatalogos } = useCatalogos();
  const [ficha, setFicha] = useState<Ficha | null>(null);
  const [anterior, setAnterior] = useState<TamizajeHistorial | null>(null);
  const [tamizaje, setTamizaje] = useState<FormTamizaje | null>(null);
  const [previa, setPrevia] = useState<VistaPrevia | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [enviando, setEnviando] = useState(false);

  useEffect(() => {
    Promise.all([pacientesApi.ficha(id), pacientesApi.historial(id)])
      .then(([f, h]) => {
        setFicha(f);
        setAnterior(h.tamizajes[0] ?? null);
        setTamizaje(formTamizajeVacio(h.tamizajes[0]));
      })
      .catch((e) => setError(mensajeError(e)));
  }, [id]);

  // Vista previa del cálculo: se pide al servidor medio segundo después de dejar de escribir.
  useEffect(() => {
    setPrevia(null);
    if (!tamizaje?.fecha_tamizaje || leerDecimal(tamizaje.hemoglobina_g_dl) === null || erroresTamizaje(tamizaje)) return;
    const control = new AbortController();
    const espera = setTimeout(() => {
      pacientesApi.vistaPrevia(id, aEntradaTamizaje(tamizaje), control.signal).then(setPrevia).catch(() => setPrevia(null));
    }, ESPERA_VISTA_PREVIA_MS);
    return () => {
      clearTimeout(espera);
      control.abort();
    };
  }, [id, tamizaje]);

  async function guardar(e: FormEvent) {
    e.preventDefault();
    if (!tamizaje) return;
    const invalido = erroresTamizaje(tamizaje);
    if (invalido) {
      setError(invalido);
      return;
    }
    setError(null);
    setEnviando(true);
    try {
      const r = await pacientesApi.nuevoTamizaje(id, aEntradaTamizaje(tamizaje));
      navegar(`/pacientes/${id}/historial`, { replace: true, state: { aviso: `Tamizaje registrado. ${avisoClasificacion(r)}` } });
    } catch (err) {
      setError(mensajeError(err));
      setEnviando(false);
    }
  }

  if (!ficha || !tamizaje) {
    return error ? <p className="alerta alerta--error" role="alert">{error}</p> : <p className="cargando">Cargando…</p>;
  }

  return (
    <section>
      <Migas items={[{ texto: "Pacientes", ruta: "/pacientes" },
                     { texto: ficha.nombres_apellidos, ruta: `/pacientes/${id}/historial` }, { texto: "Nuevo tamizaje" }]} />
      <h1>Nuevo tamizaje</h1>
      <p className="texto-tenue">Registre los datos del control actual. El tamizaje anterior se conserva en el historial y no se reemplaza.</p>
      {errorCatalogos && <p className="alerta alerta--error" role="alert">{errorCatalogos}</p>}

      <form className="formulario" onSubmit={guardar} noValidate style={{ marginTop: "1.25rem" }}>
        <div className="tarjeta">
          <h2>Datos permanentes<span className="etiqueta etiqueta--privado">solo lectura</span></h2>
          <dl className="solo-lectura">
            <dt>Paciente</dt><dd>{ficha.nombres_apellidos}</dd>
            <div className="rejilla rejilla--2">
              <div><dt>HC</dt><dd>{ficha.numero_hc}</dd></div>
              <div><dt>Sexo</dt><dd>{SEXOS[ficha.sexo]}</dd></div>
              <div><dt>Fecha de nacimiento</dt><dd>{fecha(ficha.fecha_nacimiento)}</dd></div>
              <div><dt>Edad gestacional</dt><dd>{EDADES_GESTACIONALES[ficha.edad_gestacional_nacer]}</dd></div>
              <div><dt>Distrito</dt><dd>{ficha.distrito}, {ficha.provincia}</dd></div>
              <div><dt>Altitud (m.s.n.m.)</dt><dd>{ficha.altitud_msnm}</dd></div>
            </div>
            <dt>Bajo peso al nacer</dt><dd>{siNo(ficha.bajo_peso_nacer)}</dd>
          </dl>
          <p className="anterior" style={{ marginTop: "1rem" }}>
            Registrados el {fechaHora(ficha.fecha_registro)}.
            {tienePermiso("REGISTRAR_PACIENTE") && <> Para corregirlos use <Link to={`/pacientes/${id}/editar`}>«Editar datos»</Link>.</>}
          </p>
        </div>

        <div className="tarjeta">
          <h2>Datos del control actual</h2>
          <FormularioTamizaje valor={tamizaje} sintomas={sintomas} fechaNacimiento={ficha.fecha_nacimiento} anterior={anterior}
                              cambiar={(c) => setTamizaje((t) => (t ? { ...t, ...c } : t))} />

          <div className="vista-previa" aria-live="polite">
            <strong>Vista previa del cálculo</strong>
            {previa?.clasificacion ? (
              <>
                <span>Hb ajustada {decimal(previa.clasificacion.hb_ajustada_g_dl)} g/dL</span>
                <EtiquetaClasificacion categoria={previa.clasificacion.categoria} />
              </>
            ) : (
              <span className="texto-tenue" style={{ margin: 0 }}>
                {previa ? previa.motivo_sin_clasificacion : "Ingrese la fecha y la hemoglobina para ver la clasificación"}
              </span>
            )}
            {anterior && (
              <>
                <span>· control anterior:</span>
                <EtiquetaClasificacion categoria={anterior.clasificacion?.categoria ?? null} />
                {anterior.hemoglobina_g_dl && <span>{decimal(anterior.hemoglobina_g_dl)} g/dL</span>}
              </>
            )}
          </div>

          {error && <p className="alerta alerta--error" role="alert">{error}</p>}
          <BotonesGuardar enviando={enviando} habilitado={!!tamizaje.fecha_tamizaje}
                          cancelar={() => navegar(`/pacientes/${id}/historial`)} />
        </div>
      </form>
    </section>
  );
}
