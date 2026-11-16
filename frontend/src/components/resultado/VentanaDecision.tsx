// «Registrar decisión clínica» (M07 mínimo del contrato; HU16, RF8). Ventana modal en dos pasos:
// el profesional elige una de las opciones_decision del resultado y escribe la nota (obligatoria
// solo si la opción lo indica), y luego confirma, porque la decisión no se puede modificar ni
// repetir. POST /api/consultas/{id}/decision: 201 devuelve la decisión registrada; 409, 404 y 422
// muestran el mensaje del backend; 401 cierra la sesión como en el resto de la aplicación.
import { useEffect, useRef, useState, type FormEvent, type RefObject } from "react";
import { ErrorApi, mensajeError } from "../../api/cliente";
import { consultasApi } from "../../api/consultas";
import type { Decision, OpcionDecision, TipoDecision } from "../../api/tipos_consulta";
import {
  AVISO_DECISION_DEFINITIVA,
  AVISO_NOTA_PRIVACIDAD,
  LARGO_MAXIMO_NOTA,
  TIPOS_DECISION,
} from "../../consulta/textos";
import Modal from "../Modal";

// Caracteres como los cuenta el backend (puntos de código, no unidades UTF-16).
export const largoNota = (texto: string) => [...texto.trim()].length;

export function validarNota(texto: string, obligatoria: boolean): string | null {
  const largo = largoNota(texto);
  if (obligatoria && largo === 0) return "Escriba la conducta adoptada: con esta opción la nota es obligatoria.";
  if (largo > LARGO_MAXIMO_NOTA) return `La nota admite hasta ${LARGO_MAXIMO_NOTA} caracteres; tiene ${largo}.`;
  return null;
}

type Paso = "formulario" | "confirmacion";

type Props = {
  idConsulta: string;
  opciones: OpcionDecision[];
  alRegistrar: (decision: Decision, notaEnviada: string | null) => void;
  // 409: otra pestaña ya la registró o el estado cambió; la pantalla vuelve a pedir el resultado.
  alConflicto: () => void;
  alCerrar: () => void;
  focoAlCerrar?: RefObject<HTMLElement | null>;
};

export default function VentanaDecision({ idConsulta, opciones, alRegistrar, alConflicto, alCerrar, focoAlCerrar }: Props) {
  const [tipo, setTipo] = useState<TipoDecision | null>(opciones.length === 1 ? opciones[0].tipo : null);
  const [nota, setNota] = useState("");
  const [paso, setPaso] = useState<Paso>("formulario");
  const [errores, setErrores] = useState<{ tipo?: string; nota?: string }>({});
  const [errorEnvio, setErrorEnvio] = useState<string | null>(null);
  const [guardando, setGuardando] = useState(false);
  // 409 o 404: no tiene sentido reintentar desde esta ventana; solo queda cerrarla.
  const [sinReintento, setSinReintento] = useState(false);
  const tituloConfirmacion = useRef<HTMLHeadingElement>(null);
  const campoNota = useRef<HTMLTextAreaElement>(null);
  const primerTipo = useRef<HTMLInputElement>(null);
  const alerta = useRef<HTMLDivElement>(null);
  const montado = useRef(true);
  useEffect(() => () => {
    montado.current = false;
  }, []);

  const opcion = opciones.find((o) => o.tipo === tipo) ?? null;
  const obligatoria = !!opcion?.nota_obligatoria;
  const largo = largoNota(nota);

  // Al cambiar de paso, el foco va al título del paso (confirmación) o al campo con el problema.
  useEffect(() => {
    if (paso === "confirmacion") tituloConfirmacion.current?.focus();
  }, [paso]);

  function continuar(e: FormEvent) {
    e.preventDefault();
    const problemas = {
      tipo: tipo ? undefined : "Elija el tipo de decisión.",
      nota: validarNota(nota, obligatoria) ?? undefined,
    };
    setErrores(problemas);
    setErrorEnvio(null);
    if (problemas.tipo) return primerTipo.current?.focus();
    if (problemas.nota) return campoNota.current?.focus();
    setPaso("confirmacion");
  }

  async function registrar() {
    if (!tipo || guardando) return;
    const enviada = nota.trim() || null;
    setGuardando(true);
    setErrorEnvio(null);
    try {
      const decision = await consultasApi.registrarDecision(idConsulta, { tipo_decision: tipo, nota: enviada });
      if (montado.current) alRegistrar(decision, enviada);
    } catch (e) {
      if (!montado.current) return;
      setGuardando(false);
      const codigo = e instanceof ErrorApi ? e.estado : null;
      if (codigo === 401) return; // la sesión se cierra (AuthContext) y la aplicación vuelve al inicio de sesión
      setErrorEnvio(mensajeError(e));
      if (codigo === 422) {
        // Nota u otro dato inválido: se vuelve al formulario con el mensaje del backend.
        setPaso("formulario");
        setTimeout(() => campoNota.current?.focus(), 0);
      } else {
        if (codigo === 409) alConflicto();
        if (codigo === 409 || codigo === 404) setSinReintento(true);
        setTimeout(() => alerta.current?.focus(), 0);
      }
    }
  }

  const errorAlerta = errorEnvio && (
    <div ref={alerta} tabIndex={-1} className="alerta alerta--error decision__error" role="alert">
      <p className="alerta__texto">{errorEnvio}</p>
    </div>
  );

  return (
    <Modal id="decision" titulo="Registrar decisión clínica" icono="✓" alCerrar={alCerrar} cerrable={!guardando}
           focoAlCerrar={focoAlCerrar}
           descripcion={<p>Registre la conducta que adoptará con el paciente. La decisión final es suya y queda en el historial del paciente.</p>}>
      {paso === "formulario" ? (
        <form onSubmit={continuar} noValidate>
          <fieldset className="decision__opciones" aria-describedby={errores.tipo ? "decision-tipo-error" : undefined}>
            <legend>Tipo de decisión<span className="obligatorio" aria-hidden="true"> *</span></legend>
            {opciones.map((o, i) => (
              <label key={o.tipo} className="decision__opcion">
                <input type="radio" name="tipo_decision" value={o.tipo} ref={i === 0 ? primerTipo : undefined}
                       checked={tipo === o.tipo} aria-describedby={`decision-ayuda-${o.tipo}`}
                       onChange={() => setTipo(o.tipo)} />
                <span>
                  <strong>{TIPOS_DECISION[o.tipo]?.etiqueta ?? o.tipo}</strong>
                  <span id={`decision-ayuda-${o.tipo}`} className="campo__ayuda">
                    {TIPOS_DECISION[o.tipo]?.ayuda}{o.nota_obligatoria ? " La nota es obligatoria." : ""}
                  </span>
                </span>
              </label>
            ))}
            {errores.tipo && <p id="decision-tipo-error" className="campo__error" role="alert">{errores.tipo}</p>}
          </fieldset>

          <label htmlFor="decision-nota">
            Nota: conducta adoptada{" "}
            {obligatoria ? <span className="obligatorio">(obligatoria)</span> : <span className="texto-tenue">(opcional)</span>}
          </label>
          <p id="decision-nota-privacidad" className="decision__privacidad">{AVISO_NOTA_PRIVACIDAD}</p>
          <textarea id="decision-nota" ref={campoNota} rows={4} value={nota}
                    aria-required={obligatoria || undefined} aria-invalid={errores.nota ? true : undefined}
                    aria-describedby={`decision-nota-privacidad decision-nota-contador${errores.nota ? " decision-nota-error" : ""}`}
                    onChange={(e) => setNota(e.target.value)} />
          <p id="decision-nota-contador"
             className={`decision__contador${largo > LARGO_MAXIMO_NOTA ? " decision__contador--excedido" : ""}`}>
            {largo} de {LARGO_MAXIMO_NOTA} caracteres
          </p>
          {errores.nota && <p id="decision-nota-error" className="campo__error" role="alert">{errores.nota}</p>}
          {errorAlerta}

          <div className="acciones">
            <button type="button" className="boton boton--neutro" onClick={alCerrar}>Cancelar</button>
            <button type="submit" className="boton boton--primario">Continuar</button>
          </div>
        </form>
      ) : (
        <div className="decision__confirmacion">
          <h3 ref={tituloConfirmacion} tabIndex={-1}>Confirme la decisión</h3>
          <dl className="decision__resumen">
            <div><dt>Tipo de decisión</dt><dd>{tipo ? TIPOS_DECISION[tipo]?.etiqueta ?? tipo : ""}</dd></div>
            <div><dt>Nota</dt><dd className="decision__nota">{nota.trim() || "Sin nota"}</dd></div>
          </dl>
          <p className="alerta alerta--aviso decision__definitiva" role="note"><strong>{AVISO_DECISION_DEFINITIVA}</strong></p>
          {errorAlerta}
          <div className="acciones">
            {sinReintento ? (
              <button type="button" className="boton boton--neutro" onClick={alCerrar}>Cerrar</button>
            ) : (
              <>
                <button type="button" className="boton boton--neutro" disabled={guardando}
                        onClick={() => { setErrorEnvio(null); setPaso("formulario"); }}>
                  Volver y corregir
                </button>
                <button type="button" className="boton boton--primario" disabled={guardando} onClick={() => void registrar()}>
                  {guardando ? "Registrando…" : "Confirmar y registrar"}
                </button>
              </>
            )}
          </div>
        </div>
      )}
    </Modal>
  );
}
