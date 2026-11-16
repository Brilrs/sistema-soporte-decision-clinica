// M05 · Resultado de la consulta (HU07, HU08, HU09; RF3, RF6, RF7), ruta /consultas/:id.
// Llega desde M04 con el evento fin (se muestra de inmediato) o al recargar la página; en ambos
// casos el GET /api/consultas/{id} completa los datos (pregunta, fecha, decisión). Si la consulta
// sigue EN_PROCESO (por ejemplo, desde «Ver resultado» de M04), consulta el GET cada 2 s hasta
// 60 s. Los demás estados se resumen en una columna con la clasificación y la acción para seguir;
// DATOS_FALTANTES abre la ventana M06 y TAMIZAJE_NO_VIGENTE la M15 si la consulta aún no se
// reanudó (parte E4). EVIDENCIA_INSUFICIENTE tendrá su pantalla M07 en la parte E5.
import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";
import { ErrorApi, mensajeError } from "../api/cliente";
import { ErrorConsulta, consultasApi, recuperarResultado } from "../api/consultas";
import { pacientesApi, type Ficha, type Historial, type TamizajeHistorial } from "../api/pacientes";
import type { ConsultaListada, EstadoFinal, EventoFin, ResultadoConsulta as Resultado } from "../api/tipos_consulta";
import { useAuth } from "../auth/AuthContext";
import AvisoModoPrueba from "../components/AvisoModoPrueba";
import Migas from "../components/Migas";
import VentanaDatosFaltantes from "../components/consulta/VentanaDatosFaltantes";
import VentanaTamizajeNoVigente from "../components/consulta/VentanaTamizajeNoVigente";
import EstadoSinRecomendacion from "../components/resultado/EstadoSinRecomendacion";
import { idCita } from "../components/resultado/EnlaceCita";
import RecomendacionClinica from "../components/resultado/RecomendacionClinica";
import RiesgoClasificacion from "../components/resultado/RiesgoClasificacion";
import TablaCitas from "../components/resultado/TablaCitas";
import VerificacionRespuesta from "../components/resultado/VerificacionRespuesta";
import { AVISO_DECISION } from "../consulta/textos";
import type { EstadoM04 } from "./ConsultaClinica";
import { SEXOS, edadCabecera, fechaHora, iniciales } from "../utilidades/formato";

// El evento fin no trae la pregunta, la fecha ni la decisión: quedan vacías hasta el GET.
export function desdeFin(fin: EventoFin): Resultado {
  return {
    id_consulta: fin.id_consulta,
    id_paciente: fin.id_paciente,
    id_tamizaje: "",
    id_consulta_previa: fin.id_consulta_previa,
    estado: fin.estado,
    mensaje: fin.mensaje,
    idioma: fin.idioma ?? "es",
    texto_filtrado: null,
    numero_intentos: fin.numero_intentos,
    fecha_hora_inicio: "",
    fecha_hora_fin: null,
    latencia_total_ms: fin.tiempos_ms?.total_ms ?? fin.transcurrido_ms,
    datos_faltantes: fin.datos_faltantes.map((etiqueta) => ({ campo: etiqueta, etiqueta, mensaje: "", completado: false })),
    vigencia: fin.vigencia,
    clasificacion: fin.clasificacion,
    recomendacion: fin.recomendacion,
    citas: fin.citas,
    intentos: fin.intentos,
    verificacion: fin.verificacion,
    modo_prueba: fin.modo_prueba,
    decision: null,
    opciones_decision: fin.opciones_decision,
  };
}

type ErrorCarga = { mensaje: string; codigo: number | null };
type Recuperacion = "no" | "en_curso" | "agotada";

// Una instancia por consulta: al pasar a la consulta reanudada (desde M06 o M15) se vuelve a
// montar con el evento fin de la nueva.
export default function ResultadoConsultaRuta() {
  const { id = "" } = useParams();
  return <ResultadoConsulta key={id} />;
}

function ResultadoConsulta() {
  const { id = "" } = useParams();
  const ubicacion = useLocation();
  const fin = (ubicacion.state as { fin?: EventoFin | null } | null)?.fin;
  const [resultado, setResultado] = useState<Resultado | null>(() => (fin && fin.id_consulta === id ? desdeFin(fin) : null));
  const [error, setError] = useState<ErrorCarga | null>(null);
  const [recuperacion, setRecuperacion] = useState<Recuperacion>("no");
  const [reintento, setReintento] = useState(0);
  const [ficha, setFicha] = useState<Ficha | null>(null);
  const [historial, setHistorial] = useState<Historial | null>(null);
  const [resaltada, setResaltada] = useState<string | null>(null);

  useEffect(() => {
    const control = new AbortController();
    const fallar = (e: unknown) => {
      if (control.signal.aborted) return;
      setError({ mensaje: mensajeError(e), codigo: e instanceof ErrorApi ? e.estado : null });
    };
    setError(null);
    consultasApi
      .resultado(id, control.signal)
      .then(async (r) => {
        if (control.signal.aborted) return;
        setResultado(r);
        if (r.estado !== "EN_PROCESO") return;
        setRecuperacion("en_curso");
        try {
          const final = await recuperarResultado(id, { senal: control.signal });
          if (control.signal.aborted) return;
          setResultado(final);
          setRecuperacion("no");
        } catch (e) {
          if (control.signal.aborted) return;
          if (e instanceof ErrorConsulta && e.codigo === "recuperacion_agotada") setRecuperacion("agotada");
          else fallar(e);
        }
      })
      .catch(fallar);
    return () => control.abort();
  }, [id, reintento]);

  const idPaciente = resultado?.id_paciente;
  useEffect(() => {
    if (!idPaciente) return;
    // Sin la ficha, la cabecera muestra solo los datos de la consulta.
    pacientesApi.ficha(idPaciente).then(setFicha).catch(() => setFicha(null));
    pacientesApi.historial(idPaciente).then(setHistorial).catch(() => setHistorial(null));
  }, [idPaciente]);

  const irACita = useCallback((etiqueta: string) => {
    const fila = document.getElementById(idCita(etiqueta));
    if (!fila) return;
    fila.scrollIntoView?.({ behavior: "smooth", block: "center" });
    fila.focus({ preventScroll: true });
    setResaltada(etiqueta);
  }, []);

  if (!resultado) {
    if (!error) return <p className="cargando">Cargando…</p>;
    return (
      <section>
        <h1>Resultado de la consulta</h1>
        <div className="alerta alerta--error" role="alert">
          <p className="alerta__texto">{error.mensaje}</p>
          {error.codigo === 404 && <Link to="/pacientes">Ir al panel de pacientes</Link>}
        </div>
      </section>
    );
  }

  const tamizaje = historial?.tamizajes.find((t) => t.id_tamizaje === resultado.id_tamizaje) ?? null;
  return (
    <section className="resultado">
      <Migas items={[
        { texto: "Pacientes", ruta: "/pacientes" },
        ...(ficha ? [{ texto: ficha.nombres_apellidos, ruta: `/pacientes/${ficha.id_paciente}/historial` }] : []),
        { texto: "Resultado de la consulta" },
      ]} />
      {resultado.modo_prueba && <AvisoModoPrueba />}
      {error && <p className="alerta alerta--aviso" role="status">No se pudo actualizar el resultado: {error.mensaje}</p>}

      <Cabecera resultado={resultado} ficha={ficha} edadTamizaje={tamizaje?.edad_meses ?? null} />

      {resultado.estado === "EN_PROCESO" ? (
        <EnProceso recuperacion={recuperacion} reintentar={() => setReintento((n) => n + 1)} />
      ) : resultado.estado === "VERIFICADA" ? (
        <Verificada resultado={resultado} hbObservada={tamizaje?.hemoglobina_g_dl ?? null}
                    resaltada={resaltada} irACita={irACita} />
      ) : (
        <OtroEstado resultado={resultado} estado={resultado.estado} tamizaje={tamizaje}
                    ultimoTamizaje={historial?.tamizajes[0] ?? null} />
      )}
    </section>
  );
}

type PropsCabecera = { resultado: Resultado; ficha: Ficha | null; edadTamizaje: number | null };

function Cabecera({ resultado, ficha, edadTamizaje }: PropsCabecera) {
  const navegar = useNavigate();
  const idPaciente = resultado.id_paciente;
  return (
    <div className="tarjeta tarjeta--ancha ficha-cabecera resultado__cabecera">
      <div className="ficha-cabecera__paciente">
        {ficha && <span className="avatar avatar--grande" aria-hidden="true">{iniciales(ficha.nombres_apellidos)}</span>}
        <div>
          <h1>{ficha ? ficha.nombres_apellidos : "Resultado de la consulta"}</h1>
          <span className="texto-tenue">
            {ficha && <>HC <strong>{ficha.numero_hc}</strong> · <strong>{edadCabecera(edadTamizaje, ficha.edad_meses_actual)}</strong> · {SEXOS[ficha.sexo]} · </>}
            {resultado.fecha_hora_inicio ? <>Consulta del <strong>{fechaHora(resultado.fecha_hora_inicio)}</strong></> : "Consulta"}
          </span>
        </div>
      </div>
      <div className="acciones" style={{ marginTop: 0 }}>
        <button className="boton boton--neutro" onClick={() => navegar(`/pacientes/${idPaciente}/historial`)}>Volver al paciente</button>
        <button className="boton boton--primario" onClick={() => navegar(`/pacientes/${idPaciente}/consulta`)}>Nueva consulta</button>
      </div>
      <p className="resultado__pregunta">
        <span className="resultado__pregunta-rotulo">Pregunta realizada</span>
        {resultado.texto_filtrado ?? <span className="texto-tenue">Cargando…</span>}
      </p>
    </div>
  );
}

function EnProceso({ recuperacion, reintentar }: { recuperacion: Recuperacion; reintentar: () => void }) {
  return (
    <div className="tarjeta tarjeta--ancha" role="status">
      <h2>En proceso</h2>
      {recuperacion === "agotada" ? (
        <>
          <p>La consulta sigue en proceso en el servidor después de 60 s. Vuelva a revisar en unos minutos.</p>
          <button type="button" className="boton boton--secundario boton--chico" onClick={reintentar}>Volver a revisar</button>
        </>
      ) : (
        <p>La consulta aún se está procesando. El resultado aparecerá aquí cuando termine.</p>
      )}
    </div>
  );
}

type PropsVerificada = {
  resultado: Resultado;
  hbObservada: string | number | null;
  resaltada: string | null;
  irACita: (etiqueta: string) => void;
};

function Verificada({ resultado, hbObservada, resaltada, irACita }: PropsVerificada) {
  const r = resultado.recomendacion;
  const factores = r?.factores_identificados ?? [];
  return (
    <div className="resultado__cuerpo">
      <RiesgoClasificacion clasificacion={resultado.clasificacion} hbObservada={hbObservada} />

      <section className="tarjeta resultado__recomendacion" aria-labelledby="titulo-recomendacion">
        <h2 id="titulo-recomendacion">Recomendación clínica</h2>
        {r ? <RecomendacionClinica recomendacion={r} citas={resultado.citas} irACita={irACita} />
           : <p className="texto-tenue">La respuesta no trae recomendación.</p>}
        <p className="resultado__aviso-decision" role="note">{AVISO_DECISION}</p>
        <h3>Evidencias citadas</h3>
        <TablaCitas citas={resultado.citas} resaltada={resaltada} />
        <Decisiones />
      </section>

      <VerificacionRespuesta verificacion={resultado.verificacion} intentos={resultado.intentos}
                             citas={resultado.citas.length} latenciaMs={resultado.latencia_total_ms} />

      <section className="tarjeta resultado__factores" aria-labelledby="titulo-factores">
        <h2 id="titulo-factores">Factores identificados</h2>
        {factores.length > 0 ? (
          <ul>{factores.map((f, i) => <li key={i}>{f}</li>)}</ul>
        ) : (
          <p className="texto-tenue">La respuesta no señala factores adicionales.</p>
        )}
      </section>
    </div>
  );
}

// «Registrar decisión clínica» se construye en la parte E5; «Exportar reporte» en el Sprint 3.
function Decisiones() {
  return (
    <div className="resultado__decisiones">
      <div>
        <button type="button" className="boton boton--secundario boton--auto" disabled aria-describedby="nota-decision">
          Registrar decisión clínica
        </button>
        <span id="nota-decision" className="resultado__nota">disponible en la siguiente parte</span>
      </div>
      <div>
        <button type="button" className="boton boton--neutro boton--auto" disabled aria-describedby="nota-exportar">
          Exportar reporte
        </button>
        <span id="nota-exportar" className="resultado__nota">disponible en el Sprint 3</span>
      </div>
    </div>
  );
}

type PropsOtro = {
  resultado: Resultado;
  estado: EstadoFinal;
  tamizaje: TamizajeHistorial | null; // el de la consulta, cuando ya cargó el historial
  ultimoTamizaje: TamizajeHistorial | null;
};

// Estados con ventana: se abre sola una vez si la consulta todavía se puede reanudar.
const CON_VENTANA: EstadoFinal[] = ["DATOS_FALTANTES", "TAMIZAJE_NO_VIGENTE"];

function OtroEstado({ resultado, estado, tamizaje, ultimoTamizaje }: PropsOtro) {
  const navegar = useNavigate();
  const { tienePermiso } = useAuth();
  // undefined: aún no se sabe; null: no se reanudó.
  const [reanudacion, setReanudacion] = useState<ConsultaListada | null | undefined>(undefined);
  const [ventana, setVentana] = useState(false);
  const abierta = useRef(false);
  const boton = useRef<HTMLButtonElement>(null);
  const faltantes = resultado.datos_faltantes.filter((d) => !d.completado);
  const conVentana = CON_VENTANA.includes(estado);
  const pregunta = resultado.texto_filtrado ?? "";

  // ¿Ya se reanudó? La consulta nueva lleva id_consulta_previa igual a esta.
  useEffect(() => {
    if (!conVentana) return;
    let vigente = true;
    consultasApi
      .listar(resultado.id_paciente)
      .then((lista) => vigente && setReanudacion(lista.find((c) => c.id_consulta_previa === resultado.id_consulta) ?? null))
      .catch(() => vigente && setReanudacion(null));
    return () => {
      vigente = false;
    };
  }, [conVentana, resultado.id_paciente, resultado.id_consulta]);

  // M15 reenvía la pregunta guardada: espera al GET si se llegó solo con el evento fin.
  const pendiente =
    conVentana && reanudacion === null &&
    (estado === "DATOS_FALTANTES" ? faltantes.length > 0 : !!pregunta);
  useEffect(() => {
    if (pendiente && !abierta.current) {
      abierta.current = true;
      setVentana(true);
    }
  }, [pendiente]);

  const aM04 = (state: EstadoM04) => navegar(`/pacientes/${resultado.id_paciente}/consulta`, { state });
  const accion = (texto: string, alPulsar: () => void) => (
    <button ref={boton} type="button" className="boton boton--secundario boton--auto" onClick={alPulsar}>{texto}</button>
  );
  let acciones;
  if (estado === "ERROR") acciones = accion("Reintentar", () => aM04({ pregunta }));
  else if (estado === "FUERA_DE_DOMINIO") acciones = accion("Reformular la pregunta", () => aM04({ pregunta }));
  else if (estado === "SOLICITUD_BLOQUEADA") acciones = accion("Reformular la consulta", () => aM04(null));
  else if (pendiente && estado === "DATOS_FALTANTES") acciones = accion("Completar datos", () => setVentana(true));
  else if (pendiente && estado === "TAMIZAJE_NO_VIGENTE") acciones = accion("Revisar el tamizaje", () => setVentana(true));

  return (
    <>
      <EstadoSinRecomendacion estado={estado} mensaje={resultado.mensaje} clasificacion={resultado.clasificacion}
                              hbObservada={tamizaje?.hemoglobina_g_dl ?? null} acciones={acciones}>
        {estado === "DATOS_FALTANTES" && faltantes.length > 0 && (
          <ul className="resultado__faltantes">
            {faltantes.map((d) => <li key={d.campo}>{d.mensaje || d.etiqueta}</li>)}
          </ul>
        )}
        {reanudacion && (
          <p className="resultado__reanudada">
            Esta consulta ya se reanudó. <Link to={`/consultas/${reanudacion.id_consulta}`}>Ver la consulta reanudada</Link>
          </p>
        )}
      </EstadoSinRecomendacion>

      {ventana && estado === "DATOS_FALTANTES" && (
        <VentanaDatosFaltantes idPaciente={resultado.id_paciente} idConsulta={resultado.id_consulta}
                               faltantes={faltantes} tamizaje={tamizaje ?? ultimoTamizaje}
                               alCerrar={() => setVentana(false)} focoAlCerrar={boton} />
      )}
      {ventana && estado === "TAMIZAJE_NO_VIGENTE" && (
        <VentanaTamizajeNoVigente idPaciente={resultado.id_paciente} idConsultaPrevia={resultado.id_consulta}
                                  pregunta={pregunta} idTamizaje={resultado.id_tamizaje || null}
                                  tamizaje={tamizaje ?? ultimoTamizaje} vigencia={resultado.vigencia}
                                  puedeRegistrar={tienePermiso("REGISTRAR_PACIENTE")}
                                  alCerrar={() => setVentana(false)} focoAlCerrar={boton} />
      )}
    </>
  );
}
