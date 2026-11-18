// Decisión clínica de una consulta (M05 y M07): el botón «Registrar decisión clínica» si el
// resultado trae opciones_decision, la decisión ya registrada (tipo, nota, fecha y hora, quién)
// o, para un rol sin REALIZAR_CONSULTA (el permiso que exige el backend), una nota. Los estados sin
// opciones y sin decisión (DATOS_FALTANTES, TAMIZAJE_NO_VIGENTE, FUERA_DE_DOMINIO,
// SOLICITUD_BLOQUEADA) no muestran nada. La decisión registrada viene del 201 y, al recargar, del
// GET /api/consultas/{id} (campo decision); no se completa ningún dato que la API no devuelva.
import { useEffect, useRef, useState } from "react";
import type { Decision, OpcionDecision } from "../../api/tipos_consulta";
import { useAuth } from "../../auth/AuthContext";
import { SIN_PERMISO_DECISION, TIPOS_DECISION } from "../../consulta/textos";
import { fechaHora } from "../../utilidades/formato";
import VentanaDecision from "./VentanaDecision";

type Props = {
  idConsulta: string;
  decision: Decision | null;
  opciones: OpcionDecision[];
  alRegistrar: (decision: Decision) => void;
  alConflicto: () => void;
  abrirAlCargar?: boolean; // llega desde M04 (ERROR) con «Registrar decisión clínica»
};

export default function DecisionClinica({ idConsulta, decision, opciones, alRegistrar, alConflicto, abrirAlCargar }: Props) {
  const { usuario, tienePermiso } = useAuth();
  const [ventana, setVentana] = useState(false);
  // Nota que se envió en esta sesión, para avisar si el backend la guardó distinta.
  const [notaEnviada, setNotaEnviada] = useState<string | null | undefined>(undefined);
  const boton = useRef<HTMLButtonElement>(null);
  const titulo = useRef<HTMLHeadingElement>(null);
  const recienRegistrada = useRef(false);
  const recargarAlCerrar = useRef(false);
  const puede = tienePermiso("REALIZAR_CONSULTA");
  const disponible = !decision && opciones.length > 0 && puede;

  const abiertaAlCargar = useRef(false);
  useEffect(() => {
    if (abrirAlCargar && disponible && !abiertaAlCargar.current) {
      abiertaAlCargar.current = true;
      setVentana(true);
    }
  }, [abrirAlCargar, disponible]);

  // Tras registrarla, el foco pasa a la decisión registrada (el botón ya no está).
  useEffect(() => {
    if (decision && recienRegistrada.current) {
      recienRegistrada.current = false;
      titulo.current?.focus();
    }
  }, [decision]);

  if (decision) {
    const etiqueta = TIPOS_DECISION[decision.tipo_decision]?.etiqueta ?? decision.tipo_decision;
    // El nombre de quien la registró viene del backend (registrada_por, P12). Sin ese dato, como antes:
    // solo el profesional de la consulta la ve (404 para los demás) y solo él decide, así que es el usuario actual.
    const quien = decision.registrada_por
      ?? (usuario && usuario.id_usuario === decision.id_usuario ? usuario.nombre_completo : "Profesional que realizó la consulta");
    const cambiada = notaEnviada !== undefined && (notaEnviada ?? null) !== (decision.nota ?? null);
    return (
      <section className="decision-registrada" aria-labelledby={`decision-registrada-${idConsulta}`}>
        <h3 id={`decision-registrada-${idConsulta}`} ref={titulo} tabIndex={-1}>Decisión clínica registrada</h3>
        <dl className="decision__resumen">
          <div><dt>Tipo de decisión</dt><dd>{etiqueta}</dd></div>
          <div><dt>Nota</dt><dd className="decision__nota">{decision.nota ?? "Sin nota"}</dd></div>
          <div><dt>Fecha y hora</dt><dd>{fechaHora(decision.fecha_registro)}</dd></div>
          <div><dt>Registrada por</dt><dd>{quien}</dd></div>
        </dl>
        {cambiada && (
          <p className="alerta alerta--aviso" role="status">
            Por privacidad, el sistema guardó la nota con los datos personales reemplazados por marcas como [PACIENTE] o
            [DNI]. Revise el texto registrado.
          </p>
        )}
        <div className="decision__boton">
          <button type="button" className="boton boton--secundario boton--auto" disabled
                  aria-describedby={`decision-registrada-nota-${idConsulta}`}>
            Registrar decisión clínica
          </button>
          <span id={`decision-registrada-nota-${idConsulta}`} className="resultado__nota">
            Ya registrada: no se puede modificar ni registrar de nuevo.
          </span>
        </div>
      </section>
    );
  }

  if (opciones.length === 0) return null;

  if (!puede) {
    return <p className="decision__sin-permiso" role="note">{SIN_PERMISO_DECISION}</p>;
  }

  return (
    <>
      <button ref={boton} type="button" className="boton boton--secundario boton--auto" onClick={() => setVentana(true)}>
        Registrar decisión clínica
      </button>
      {ventana && (
        <VentanaDecision idConsulta={idConsulta} opciones={opciones} focoAlCerrar={boton}
                         alCerrar={() => {
                           setVentana(false);
                           // Tras un 409 (ya registrada o estado no permitido) se vuelve a pedir el resultado.
                           if (recargarAlCerrar.current) {
                             recargarAlCerrar.current = false;
                             alConflicto();
                           }
                         }}
                         alConflicto={() => (recargarAlCerrar.current = true)}
                         alRegistrar={(d, enviada) => {
                           recienRegistrada.current = true;
                           setNotaEnviada(enviada);
                           setVentana(false);
                           alRegistrar(d);
                         }} />
      )}
    </>
  );
}
