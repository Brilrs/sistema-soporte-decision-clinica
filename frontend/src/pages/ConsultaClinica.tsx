// M04 · Consulta clínica (HU03, HU06): el profesional escribe su pregunta y ve el avance por
// etapas. Con VERIFICADA o EVIDENCIA_INSUFICIENTE pasa al resultado (M05; M07 en la parte E5).
// DATOS_FALTANTES abre la ventana M06 y TAMIZAJE_NO_VIGENTE la M15 (parte E4); los demás estados
// se resumen aquí con la clasificación y la acción para seguir. Al volver de M14 (nuevo tamizaje
// pedido desde la consulta) o desde M05 («Reintentar», «Reformular») llega con la pregunta en
// location.state. No captura datos clínicos: usa el tamizaje registrado más reciente.
import { useCallback, useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { mensajeError } from "../api/cliente";
import { consultasApi } from "../api/consultas";
import { pacientesApi, type Ficha, type Historial } from "../api/pacientes";
import type { ConsultaListada, EstadoFinal } from "../api/tipos_consulta";
import { useAuth } from "../auth/AuthContext";
import AvanceConsulta from "../components/AvanceConsulta";
import AvisoModoPrueba from "../components/AvisoModoPrueba";
import ContextoSesion from "../components/ContextoSesion";
import Migas from "../components/Migas";
import VentanaDatosFaltantes from "../components/consulta/VentanaDatosFaltantes";
import VentanaTamizajeNoVigente from "../components/consulta/VentanaTamizajeNoVigente";
import EstadoSinRecomendacion from "../components/resultado/EstadoSinRecomendacion";
import { useConsulta } from "../consulta/useConsulta";
import { SEXOS, decimal, edad, iniciales } from "../utilidades/formato";

export const LARGO_MAXIMO_CONSULTA = 2000;

// Estados que abren la pantalla de resultado; los demás se informan en M04.
const CON_RESULTADO: EstadoFinal[] = ["VERIFICADA", "EVIDENCIA_INSUFICIENTE"];

export const EJEMPLO_CONSULTA = "Ejemplo: ¿Qué dosis de hierro le corresponde y cada cuánto controlo la hemoglobina?";

// Estado de navegación que recibe M04 (desde M14 y desde M05).
export type EstadoM04 = { pregunta?: string; aviso?: string } | null;

const MENSAJE_CANCELADA =
  "Se canceló la espera. La consulta puede terminar igual en el servidor y quedar registrada en sus consultas previas de este paciente.";

export default function ConsultaClinica() {
  const { id = "" } = useParams();
  const navegar = useNavigate();
  const llegada = useLocation().state as EstadoM04;
  const { tienePermiso } = useAuth();
  const puedeRegistrar = tienePermiso("REGISTRAR_PACIENTE");
  const [ficha, setFicha] = useState<Ficha | null>(null);
  const [historial, setHistorial] = useState<Historial | null>(null);
  const [errorCarga, setErrorCarga] = useState<string | null>(null);
  const [consultas, setConsultas] = useState<ConsultaListada[] | null>(null);
  const [errorConsultas, setErrorConsultas] = useState<string | null>(null);
  const [texto, setTexto] = useState(() => llegada?.pregunta ?? "");
  const [pregunta, setPregunta] = useState<string | null>(null);
  const [ventana, setVentana] = useState<"datos" | "vigencia" | null>(null);
  const campo = useRef<HTMLTextAreaElement>(null);
  const { estado, enviar, cancelar } = useConsulta(id);
  const { fase, desenlace } = estado;
  const enCurso = fase === "en_curso" || fase === "recuperando";

  useEffect(() => {
    Promise.all([pacientesApi.ficha(id), pacientesApi.historial(id)])
      .then(([f, h]) => {
        setFicha(f);
        setHistorial(h);
      })
      .catch((e) => setErrorCarga(mensajeError(e)));
  }, [id]);

  const cargarConsultas = useCallback(() => {
    consultasApi
      .listar(id)
      .then((c) => {
        setConsultas(c);
        setErrorConsultas(null);
      })
      .catch((e) => setErrorConsultas(mensajeError(e)));
  }, [id]);

  useEffect(cargarConsultas, [cargarConsultas]);

  // Al terminar: el resultado se abre en su pantalla; DATOS_FALTANTES y TAMIZAJE_NO_VIGENTE abren
  // su ventana; los demás estados se quedan en M04. La lista de consultas previas se actualiza.
  useEffect(() => {
    if (fase === "cancelada") cargarConsultas();
    if (fase !== "terminada" || !desenlace) return;
    if (desenlace.id_consulta && CON_RESULTADO.includes(desenlace.estado)) {
      // El evento fin permite mostrar M05 de inmediato; M05 completa los datos con el GET.
      navegar(`/consultas/${desenlace.id_consulta}`, { state: { fin: desenlace.fin } });
      return;
    }
    if (desenlace.id_consulta && desenlace.estado === "DATOS_FALTANTES") setVentana("datos");
    if (desenlace.id_consulta && desenlace.estado === "TAMIZAJE_NO_VIGENTE") setVentana("vigencia");
    cargarConsultas();
  }, [fase, desenlace, navegar, cargarConsultas]);

  function consultar(e?: FormEvent) {
    e?.preventDefault();
    const limpio = texto.trim();
    if (!limpio || enCurso) return;
    setPregunta(limpio);
    setTexto("");
    setVentana(null);
    void enviar({ texto_consulta: limpio });
  }

  // «Reintentar» y «Reformular»: deja el texto en el campo para revisarlo y enviarlo.
  function volverAEscribir(textoNuevo: string) {
    setTexto(textoNuevo);
    campo.current?.focus();
  }

  // Enter envía; Mayús + Enter agrega una línea.
  function teclaEnConsulta(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      consultar();
    }
  }

  if (!ficha || !historial) {
    return errorCarga ? <p className="alerta alerta--error" role="alert">{errorCarga}</p> : <p className="cargando">Cargando…</p>;
  }

  const ultimo = historial.tamizajes[0];
  const sinTamizaje = !ultimo;
  const resumen = fase === "terminada" && desenlace && !CON_RESULTADO.includes(desenlace.estado) ? desenlace : null;
  // M14 pedido desde la consulta: al guardar vuelve aquí con la pregunta escrita.
  const irANuevoTamizaje = () =>
    navegar(`/pacientes/${id}/tamizajes/nuevo`, { state: { volverAConsulta: { pregunta: texto.trim() || pregunta || "" } } });

  return (
    <section>
      <Migas items={[{ texto: "Pacientes", ruta: "/pacientes" },
                     { texto: ficha.nombres_apellidos, ruta: `/pacientes/${id}/historial` }, { texto: "Consulta clínica" }]} />

      <div className="tarjeta tarjeta--ancha ficha-cabecera">
        <div className="ficha-cabecera__paciente">
          <span className="avatar avatar--grande" aria-hidden="true">{iniciales(ficha.nombres_apellidos)}</span>
          <div>
            <h1>{ficha.nombres_apellidos}</h1>
            <span className="texto-tenue">
              HC <strong>{ficha.numero_hc}</strong> · <strong>{edad(ficha.edad_meses_actual)}</strong> · {SEXOS[ficha.sexo]}
              {ultimo?.hemoglobina_g_dl && <> · Hb <strong>{decimal(ultimo.hemoglobina_g_dl)} g/dL</strong></>}
              {" "}· Altitud <strong>{ficha.altitud_msnm} m.s.n.m.</strong>
            </span>
          </div>
        </div>
        <div className="acciones" style={{ marginTop: 0 }}>
          {puedeRegistrar && (
            <>
              <button className="boton boton--primario" onClick={irANuevoTamizaje}>+ Nuevo tamizaje</button>
              <button className="boton boton--neutro" onClick={() => navegar(`/pacientes/${id}/editar`)}>Editar datos</button>
            </>
          )}
          <button className="boton boton--neutro" onClick={() => navegar(`/pacientes/${id}/historial`)}>Historial</button>
        </div>
      </div>

      <div className="consulta">
        <div className="tarjeta consulta__chat">
          <h2>Consulta clínica</h2>
          <div className="consulta__mensajes">
            {fase === "inactiva" && llegada?.aviso && <p className="alerta alerta--exito" role="status">{llegada.aviso}</p>}
            {pregunta && <p className="burbuja">{pregunta}</p>}
            {fase !== "inactiva" && (
              <AvanceConsulta avance={estado.avance} activa={enCurso} recuperando={fase === "recuperando"}
                              inicio={estado.inicio} finMs={estado.finMs} cancelar={cancelar} detenida={!!resumen} />
            )}
            {resumen && (
              <>
                {resumen.modo_prueba && <AvisoModoPrueba />}
                <EstadoSinRecomendacion
                  estado={resumen.estado} mensaje={resumen.mensaje} nivel={3}
                  clasificacion={resumen.clasificacion} hbObservada={ultimo?.hemoglobina_g_dl ?? null}
                  acciones={<AccionesEstado estado={resumen.estado} hayId={!!resumen.id_consulta}
                                            decidir={resumen.id_consulta && resumen.opciones_decision.length > 0 &&
                                                     tienePermiso("REALIZAR_CONSULTA")
                                              ? () => navegar(`/consultas/${resumen.id_consulta}`, { state: { abrirDecision: true } })
                                              : null}
                                            reintentar={() => volverAEscribir(pregunta ?? "")}
                                            reformular={() => volverAEscribir("")}
                                            abrirDatos={() => setVentana("datos")}
                                            abrirVigencia={() => setVentana("vigencia")} />} />
              </>
            )}
            {fase === "cancelada" && <p className="alerta alerta--aviso" role="status">{MENSAJE_CANCELADA}</p>}
            {fase === "error" && (
              <div className="alerta alerta--error" role="alert">
                <p className="alerta__texto">{estado.error}</p>
                {estado.puedeVerResultado && estado.idConsulta && (
                  <button type="button" className="boton boton--secundario boton--chico"
                          onClick={() => navegar(`/consultas/${estado.idConsulta}`)}>Ver resultado</button>
                )}
              </div>
            )}
          </div>

          <form className="consulta__formulario" onSubmit={consultar}>
            <p className="consulta__privacidad" id="aviso-privacidad">
              No escriba nombres, DNI, historia clínica ni teléfonos. El sistema ya conoce los datos del paciente:
              pregunte por el tema clínico (hierro, hemoglobina, anemia, derivación o controles).
            </p>
            <div className="consulta__entrada">
              <label htmlFor="texto-consulta" className="solo-lectores">Consulta sobre el paciente</label>
              <textarea id="texto-consulta" ref={campo} rows={2} maxLength={LARGO_MAXIMO_CONSULTA} value={texto}
                        placeholder={EJEMPLO_CONSULTA} aria-describedby="aviso-privacidad"
                        disabled={sinTamizaje} onChange={(e) => setTexto(e.target.value)} onKeyDown={teclaEnConsulta} />
              <button className="boton boton--primario" type="submit" disabled={enCurso || sinTamizaje || !texto.trim()}>
                {enCurso ? "Consultando…" : "Enviar"}
              </button>
            </div>
          </form>
        </div>

        <ContextoSesion tamizajes={historial.tamizajes} consultas={consultas} errorConsultas={errorConsultas} />
      </div>

      {ventana === "datos" && resumen?.id_consulta && (
        <VentanaDatosFaltantes idPaciente={id} idConsulta={resumen.id_consulta} tamizaje={ultimo ?? null}
                               faltantes={resumen.datos_faltantes.map((etiqueta) => ({ etiqueta }))}
                               alCerrar={() => setVentana(null)} focoAlCerrar={campo} />
      )}
      {ventana === "vigencia" && resumen?.id_consulta && (
        <VentanaTamizajeNoVigente idPaciente={id} idConsultaPrevia={resumen.id_consulta} pregunta={pregunta ?? ""}
                                  idTamizaje={ultimo?.id_tamizaje ?? null} tamizaje={ultimo ?? null}
                                  vigencia={resumen.vigencia} puedeRegistrar={puedeRegistrar}
                                  alCerrar={() => setVentana(null)} focoAlCerrar={campo} />
      )}
    </section>
  );
}

type PropsAcciones = {
  estado: EstadoFinal;
  hayId: boolean;
  reintentar: () => void;
  reformular: () => void;
  abrirDatos: () => void;
  abrirVigencia: () => void;
  decidir: (() => void) | null; // ERROR: «Registrar decisión clínica» abre M05 con la ventana
};

// Acción para seguir según el estado. ERROR y FUERA_DE_DOMINIO devuelven la pregunta al campo;
// tras un bloqueo el campo queda vacío, porque la pregunta tenía un dato del paciente.
function AccionesEstado({ estado, hayId, reintentar, reformular, abrirDatos, abrirVigencia, decidir }: PropsAcciones) {
  const boton = (texto: string, accion: () => void) => (
    <button type="button" className="boton boton--secundario boton--auto" onClick={accion}>{texto}</button>
  );
  switch (estado) {
    case "ERROR":
      return (
        <>
          {boton("Reintentar", reintentar)}
          {decidir && boton("Registrar decisión clínica", decidir)}
        </>
      );
    case "FUERA_DE_DOMINIO":
      return boton("Reformular la pregunta", reintentar);
    case "SOLICITUD_BLOQUEADA":
      return boton("Reformular la consulta", reformular);
    case "DATOS_FALTANTES":
      return hayId ? boton("Completar datos", abrirDatos) : null;
    case "TAMIZAJE_NO_VIGENTE":
      return hayId ? boton("Revisar el tamizaje", abrirVigencia) : null;
    default:
      return null;
  }
}
