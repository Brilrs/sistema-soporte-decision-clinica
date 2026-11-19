// Ventana de confirmación de M12 (parte E2), común a los tres grupos editables: la tabla de cambios
// antes y después (solo las filas que cambian, con su estado de verificación), el motivo (10 a 500
// caracteres, con contador) y la referencia (obligatoria si alguna fila queda verificada). Maneja
// las respuestas del PUT (docs/contrato_parametros.md):
// - VALIDACION: resumen con role alert y los errores junto a su campo (también en la tabla del grupo);
// - REQUIERE_CONFIRMACION: las advertencias y «Escriba CONFIRMO para continuar»; Guardar solo se
//   habilita con el texto exacto y el reenvío lleva confirmacion_escrita;
// - SIN_CAMBIOS, 409 (con «Recargar valores»), 423 y 403: un mensaje claro, sin perder lo escrito.
import { useId, useRef, useState, type FormEvent } from "react";
import { ErrorApi } from "../../api/cliente";
import { ErrorEdicion } from "../../api/parametros";
import { CONFIRMACION_ESCRITA, type CampoMensaje, type EdicionComun } from "../../api/tipos_parametros";
import Modal from "../Modal";
import EstadoVerificacion from "./EstadoVerificacion";
import { MOTIVO_MAX, MOTIVO_MIN } from "./textos";

export type FilaCambio = {
  clave: string;
  elemento: string;
  antes: string;
  despues: string;
  verificadoAntes: boolean;
  verificadoDespues: boolean;
};

type Problema = { tipo: "conflicto" | "bloqueo" | "permiso" | "otro"; mensaje: string } | null;

type Props<R> = {
  id: string;
  titulo: string;
  cambios: FilaCambio[];
  enviar: (comun: Omit<EdicionComun, "version">) => Promise<R>;
  etiquetaCampo: (ruta: string) => string;
  alGuardado: (resultado: R) => void;
  alCerrar: () => void;
  alRecargar: () => void;
  alBloquear: () => void;
  alErroresCampo: (errores: CampoMensaje[]) => void;
};

export default function VentanaGuardar<R>({ id, titulo, cambios, enviar, etiquetaCampo, alGuardado, alCerrar, alRecargar,
                                            alBloquear, alErroresCampo }: Props<R>) {
  const [motivo, setMotivo] = useState("");
  const [referencia, setReferencia] = useState("");
  const [confirmacion, setConfirmacion] = useState("");
  const [enviando, setEnviando] = useState(false);
  const [errores, setErrores] = useState<CampoMensaje[]>([]);
  const [advertencias, setAdvertencias] = useState<CampoMensaje[] | null>(null);
  const [problema, setProblema] = useState<Problema>(null);
  const resumen = useRef<HTMLDivElement>(null);
  const campoMotivo = useRef<HTMLTextAreaElement>(null);
  const ids = { motivo: useId(), referencia: useId(), confirmacion: useId(), contador: useId() };

  const exigeReferencia = cambios.some((c) => c.verificadoDespues);
  const largo = motivo.trim().length;
  const motivoValido = largo >= MOTIVO_MIN && largo <= MOTIVO_MAX;
  const referenciaValida = !exigeReferencia || referencia.trim().length > 0;
  const confirmado = advertencias === null || confirmacion === CONFIRMACION_ESCRITA;
  const bloqueante = problema !== null && problema.tipo !== "otro";
  const puedeGuardar = !enviando && motivoValido && referenciaValida && confirmado && !bloqueante;
  const errorDe = (campo: string) => errores.filter((e) => e.campo === campo);

  async function guardar(e: FormEvent) {
    e.preventDefault();
    if (!puedeGuardar) return;
    setEnviando(true);
    setProblema(null);
    try {
      const resultado = await enviar({
        motivo_cambio: motivo.trim(), referencia: referencia.trim() || null,
        ...(advertencias !== null ? { confirmacion_escrita: confirmacion } : {}),
      });
      alErroresCampo([]);
      alGuardado(resultado);
    } catch (error) {
      tratarError(error);
      setEnviando(false);
      requestAnimationFrame(() => resumen.current?.focus());
    }
  }

  function tratarError(error: unknown) {
    if (error instanceof ErrorEdicion) {
      const c = error.cuerpo;
      if (c.codigo === "VALIDACION") {
        setErrores(c.errores);
        alErroresCampo(c.errores);
        return;
      }
      setErrores([]);
      if (c.codigo === "REQUIERE_CONFIRMACION") {
        setAdvertencias(c.advertencias);
        setConfirmacion("");
        return;
      }
      if (c.codigo === "VERSION_DESACTUALIZADA") {
        setProblema({ tipo: "conflicto", mensaje: c.detail });
        return;
      }
      if (c.codigo === "MODO_EVALUACION") {
        alBloquear();
        setProblema({ tipo: "bloqueo", mensaje: c.detail });
        return;
      }
      setProblema({ tipo: "otro", mensaje: c.detail });
      return;
    }
    if (error instanceof ErrorApi && error.estado === 403) {
      setProblema({ tipo: "permiso", mensaje: error.message });
      return;
    }
    setProblema({ tipo: "otro", mensaje: error instanceof Error && error.message ? error.message
      : "No se pudo guardar. Revise su conexión e intente de nuevo." });
  }

  const hayResumen = errores.length > 0 || advertencias !== null || problema !== null;

  return (
    <Modal id={id} titulo={`Guardar cambios: ${titulo}`} icono="✓" amplia alCerrar={alCerrar} cerrable={!enviando} focoInicial={campoMotivo}
           descripcion={<p>Revise los cambios. Cada valor nuevo rige desde ahora; los anteriores quedan en el historial.</p>}>
      <form onSubmit={guardar} noValidate>
        {hayResumen && (
          <div ref={resumen} tabIndex={-1} className="parametros__resumen-ventana">
            {errores.length > 0 && (
              <div className="alerta alerta--error" role="alert">
                <p className="alerta__texto">Revise los datos: el cambio no se guardó.</p>
                <ul>{errores.map((x) => <li key={x.campo + x.mensaje}>{etiquetaCampo(x.campo)}: {x.mensaje}</li>)}</ul>
              </div>
            )}
            {advertencias !== null && (
              <div className="alerta alerta--aviso" role="alert">
                <p className="alerta__texto">El cambio tiene advertencias. Revíselas antes de guardar:</p>
                <ul>{advertencias.map((x) => <li key={x.campo + x.mensaje}>{x.mensaje}</li>)}</ul>
              </div>
            )}
            {problema !== null && (
              <div className="alerta alerta--error" role="alert">
                <p className="alerta__texto">{problema.mensaje}</p>
                {problema.tipo === "conflicto" && (
                  <button type="button" className="boton boton--secundario boton--auto" onClick={alRecargar}>
                    Recargar valores
                  </button>
                )}
              </div>
            )}
          </div>
        )}

        <h3 className="parametros__subtitulo">Cambios</h3>
        <div className="tabla-contenedor" tabIndex={0} role="region" aria-label="Cambios antes y después">
          <table className="tabla tabla--compacta parametros__cambios">
            <thead>
              <tr>
                <th scope="col">Elemento</th>
                <th scope="col">Antes</th>
                <th scope="col">Después</th>
              </tr>
            </thead>
            <tbody>
              {cambios.map((c) => (
                <tr key={c.clave}>
                  <th scope="row">{c.elemento}</th>
                  <td>{c.antes} <EstadoVerificacion verificado={c.verificadoAntes} /></td>
                  <td>{c.despues} <EstadoVerificacion verificado={c.verificadoDespues} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <fieldset className="modal__campos" disabled={enviando}>
          <label htmlFor={ids.motivo}>Motivo del cambio <span className="obligatorio" aria-hidden="true">*</span></label>
          <textarea ref={campoMotivo} id={ids.motivo} value={motivo} rows={3} maxLength={MOTIVO_MAX} required
                    aria-invalid={errorDe("motivo_cambio").length > 0 || undefined}
                    aria-describedby={[ids.contador, errorDe("motivo_cambio").length ? `${ids.motivo}-error` : ""].join(" ").trim()}
                    onChange={(e) => setMotivo(e.target.value)} />
          <p className="campo__ayuda" id={ids.contador} aria-live="polite">
            {largo} de {MOTIVO_MAX} caracteres{largo < MOTIVO_MIN ? ` (mínimo ${MOTIVO_MIN})` : ""}
          </p>
          {errorDe("motivo_cambio").length > 0 && (
            <p className="campo__error" id={`${ids.motivo}-error`}>{errorDe("motivo_cambio").map((x) => x.mensaje).join(". ")}</p>
          )}

          <label htmlFor={ids.referencia}>
            Referencia (norma, tabla y página){" "}
            {exigeReferencia ? <span className="obligatorio" aria-hidden="true">*</span> : <span className="texto-tenue">(opcional)</span>}
          </label>
          <input id={ids.referencia} value={referencia} maxLength={200} autoComplete="off" required={exigeReferencia}
                 aria-invalid={errorDe("referencia").length > 0 || undefined}
                 aria-describedby={`${ids.referencia}-ayuda${errorDe("referencia").length ? ` ${ids.referencia}-error` : ""}`}
                 placeholder="p. ej., NTS 213-MINSA/DGIESP-2024, Tabla 4, p. 12"
                 onChange={(e) => setReferencia(e.target.value)} />
          <p className="campo__ayuda" id={`${ids.referencia}-ayuda`}>
            {exigeReferencia ? "Obligatoria: algún valor queda verificado contra la norma." : "Obligatoria solo si algún valor queda verificado."}
          </p>
          {errorDe("referencia").length > 0 && (
            <p className="campo__error" id={`${ids.referencia}-error`}>{errorDe("referencia").map((x) => x.mensaje).join(". ")}</p>
          )}

          {advertencias !== null && (
            <>
              <label htmlFor={ids.confirmacion}>Escriba {CONFIRMACION_ESCRITA} para continuar</label>
              <input id={ids.confirmacion} value={confirmacion} autoComplete="off" spellCheck={false}
                     aria-describedby={`${ids.confirmacion}-ayuda`} onChange={(e) => setConfirmacion(e.target.value)} />
              <p className="campo__ayuda" id={`${ids.confirmacion}-ayuda`}>
                En mayúsculas, exactamente {CONFIRMACION_ESCRITA}. Guardar se habilita al escribirlo.
              </p>
            </>
          )}
        </fieldset>

        <div className="acciones">
          <button type="button" className="boton boton--neutro" onClick={alCerrar} disabled={enviando}>Cancelar</button>
          <button type="submit" className="boton boton--primario" disabled={!puedeGuardar}>
            {enviando ? "Guardando…" : "Guardar"}
          </button>
        </div>
      </form>
    </Modal>
  );
}
