// M04 · Consulta clínica (HU03, HU06): el profesional escribe su pregunta y ve el avance por
// etapas. Con VERIFICADA o EVIDENCIA_INSUFICIENTE pasa al resultado (M05 o M07, parte E3); los
// demás estados se informan aquí (las ventanas M06 y M15 son de la parte E4).
// No captura datos clínicos: usa el tamizaje registrado más reciente.
import { useCallback, useEffect, useState, type FormEvent, type KeyboardEvent } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { mensajeError } from "../api/cliente";
import { consultasApi } from "../api/consultas";
import { pacientesApi, type Ficha, type Historial } from "../api/pacientes";
import type { ConsultaListada, EstadoFinal } from "../api/tipos_consulta";
import { useAuth } from "../auth/AuthContext";
import AvanceConsulta from "../components/AvanceConsulta";
import AvisoModoPrueba from "../components/AvisoModoPrueba";
import ContextoSesion from "../components/ContextoSesion";
import Migas from "../components/Migas";
import { useConsulta, type Desenlace } from "../consulta/useConsulta";
import { SEXOS, decimal, edad, iniciales } from "../utilidades/formato";

export const LARGO_MAXIMO_CONSULTA = 2000;

// Estados que abren la pantalla de resultado; los demás se informan en M04.
const CON_RESULTADO: EstadoFinal[] = ["VERIFICADA", "EVIDENCIA_INSUFICIENTE"];

const TITULOS: Record<EstadoFinal, string> = {
  VERIFICADA: "Respuesta verificada",
  EVIDENCIA_INSUFICIENTE: "Evidencia insuficiente",
  ERROR: "No se pudo evaluar la consulta",
  DATOS_FALTANTES: "Faltan datos del tamizaje",
  TAMIZAJE_NO_VIGENTE: "El tamizaje no está vigente",
  FUERA_DE_DOMINIO: "Consulta fuera del alcance del sistema",
  SOLICITUD_BLOQUEADA: "Solicitud bloqueada para proteger los datos del paciente",
};

const MENSAJES_POR_DEFECTO: Record<EstadoFinal, string> = {
  VERIFICADA: "",
  EVIDENCIA_INSUFICIENTE: "",
  ERROR: "No se pudo evaluar la consulta. Aplique su criterio clínico.",
  DATOS_FALTANTES: "Complete el registro del tamizaje para continuar.",
  TAMIZAJE_NO_VIGENTE: "Registre un tamizaje nuevo para continuar.",
  FUERA_DE_DOMINIO: "El sistema responde sobre la anemia en niños de 0 a 59 meses.",
  SOLICITUD_BLOQUEADA: "Reformule la consulta sin nombres, documentos ni números de contacto.",
};

// El filtro de dominio evalúa solo la pregunta, sin los datos del paciente: las preguntas
// genéricas («¿Cómo lo manejo?») suelen quedar fuera. Ver docs/cambios_respecto_al_OE2.md.
export const SUGERENCIA_FUERA_DE_DOMINIO =
  "Si su pregunta es sobre este paciente, reformúlela mencionando el tema, por ejemplo hierro, hemoglobina, anemia o derivación.";

export const EJEMPLO_CONSULTA = "Ejemplo: ¿Qué dosis de hierro le corresponde y cada cuánto controlo la hemoglobina?";

const MENSAJE_CANCELADA =
  "Se canceló la espera. La consulta puede terminar igual en el servidor y quedar registrada en sus consultas previas de este paciente.";

function MensajeDesenlace({ desenlace }: { desenlace: Desenlace }) {
  const grave = desenlace.estado === "ERROR" || desenlace.estado === "SOLICITUD_BLOQUEADA";
  return (
    <div className={`desenlace ${grave ? "desenlace--error" : "desenlace--aviso"}`} role="alert">
      <strong>{TITULOS[desenlace.estado]}</strong>
      <p>{desenlace.mensaje || MENSAJES_POR_DEFECTO[desenlace.estado]}</p>
      {desenlace.estado === "FUERA_DE_DOMINIO" && <p className="desenlace__sugerencia">{SUGERENCIA_FUERA_DE_DOMINIO}</p>}
    </div>
  );
}

export default function ConsultaClinica() {
  const { id = "" } = useParams();
  const navegar = useNavigate();
  const { tienePermiso } = useAuth();
  const puedeRegistrar = tienePermiso("REGISTRAR_PACIENTE");
  const [ficha, setFicha] = useState<Ficha | null>(null);
  const [historial, setHistorial] = useState<Historial | null>(null);
  const [errorCarga, setErrorCarga] = useState<string | null>(null);
  const [consultas, setConsultas] = useState<ConsultaListada[] | null>(null);
  const [errorConsultas, setErrorConsultas] = useState<string | null>(null);
  const [texto, setTexto] = useState("");
  const [pregunta, setPregunta] = useState<string | null>(null);
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

  // Al terminar: el resultado se abre en su pantalla; los demás estados se quedan en M04 y la
  // lista de consultas previas se actualiza (la consulta ya quedó registrada).
  useEffect(() => {
    if (fase === "cancelada") cargarConsultas();
    if (fase !== "terminada" || !desenlace) return;
    if (desenlace.id_consulta && CON_RESULTADO.includes(desenlace.estado)) {
      navegar(`/consultas/${desenlace.id_consulta}`, { state: { desenlace } });
      return;
    }
    cargarConsultas();
  }, [fase, desenlace, navegar, cargarConsultas]);

  function consultar(e?: FormEvent) {
    e?.preventDefault();
    const limpio = texto.trim();
    if (!limpio || enCurso) return;
    setPregunta(limpio);
    setTexto("");
    void enviar({ texto_consulta: limpio });
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
              <button className="boton boton--primario" onClick={() => navegar(`/pacientes/${id}/tamizajes/nuevo`)}>
                + Nuevo tamizaje
              </button>
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
            {pregunta && <p className="burbuja">{pregunta}</p>}
            {fase !== "inactiva" && (
              <AvanceConsulta avance={estado.avance} activa={enCurso} recuperando={fase === "recuperando"}
                              inicio={estado.inicio} finMs={estado.finMs} cancelar={cancelar} />
            )}
            {fase === "terminada" && desenlace && !CON_RESULTADO.includes(desenlace.estado) && (
              <>
                {desenlace.modo_prueba && <AvisoModoPrueba />}
                <MensajeDesenlace desenlace={desenlace} />
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
              <textarea id="texto-consulta" rows={2} maxLength={LARGO_MAXIMO_CONSULTA} value={texto}
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
    </section>
  );
}
