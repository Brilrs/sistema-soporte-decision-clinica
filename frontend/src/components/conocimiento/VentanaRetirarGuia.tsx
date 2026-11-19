// «Retirar» de M11 (HU17, Sprint 3 parte F). Al abrirse carga las referencias que bloquean el retiro
// de una guía de nivel 1 (GET .../referencias). Nivel 2: basta el motivo. Nivel 1 con referencias: la
// lista y «Retirar» deshabilitado con la explicación. Nivel 1 sin referencias: además del motivo, el
// código del documento escrito exactamente. Errores del POST: 409 (la guía cambió, con «Recargar», o
// la lista de referencias nueva), 422 junto al campo, 423 (modo de evaluación) y 403.
import { useEffect, useId, useRef, useState, type RefObject } from "react";
import { ErrorApi, mensajeError } from "../../api/cliente";
import {
  ErrorRetiro, MOTIVO_RETIRO_MAX, MOTIVO_RETIRO_MIN, conocimientoApi, type Documento, type DocumentoCreado,
  type ReferenciasGuia,
} from "../../api/conocimiento";
import Modal from "../Modal";
import { nombreGuia } from "./TablaGuias";
import { TEXTO_BLOQUEO_REFERENCIAS, TEXTO_RETIRO, TIPOS_REFERENCIA } from "./textos";

type Props = {
  documento: Documento;
  alCerrar: () => void;
  alRetirar: (creado: DocumentoCreado) => void;
  alRecargar: () => void;
  focoAlCerrar?: RefObject<HTMLElement | null>;
};

type Carga = { estado: "cargando" } | { estado: "error"; mensaje: string } | { estado: "listo"; r: ReferenciasGuia };
type Problema = { tipo: "conflicto" | "bloqueo" | "error"; texto: string } | null;

export default function VentanaRetirarGuia({ documento, alCerrar, alRetirar, alRecargar, focoAlCerrar }: Props) {
  const [carga, setCarga] = useState<Carga>({ estado: "cargando" });
  const [intento, setIntento] = useState(0);
  const [motivo, setMotivo] = useState("");
  const [confirmacion, setConfirmacion] = useState("");
  const [enviando, setEnviando] = useState(false);
  const [problema, setProblema] = useState<Problema>(null);
  const [errorMotivo, setErrorMotivo] = useState<string | null>(null);
  const [errorConfirmacion, setErrorConfirmacion] = useState<string | null>(null);
  const campoMotivo = useRef<HTMLTextAreaElement>(null);
  const ids = { motivo: useId(), contador: useId(), confirmacion: useId(), ayuda: useId(), razon: useId(), lista: useId() };

  useEffect(() => {
    const control = new AbortController();
    setCarga({ estado: "cargando" });
    conocimientoApi.referencias(documento.id_documento, control.signal)
      .then((r) => setCarga({ estado: "listo", r }))
      .catch((e) => !control.signal.aborted && setCarga({ estado: "error", mensaje: mensajeError(e) }));
    return () => control.abort();
  }, [documento.id_documento, intento]);

  const r = carga.estado === "listo" ? carga.r : null;
  const bloqueadaPorReferencias = !!r && r.referencias.length > 0;
  const pideCodigo = !!r && r.nivel === 1 && !bloqueadaPorReferencias;
  const largo = motivo.trim().length;
  const motivoValido = largo >= MOTIVO_RETIRO_MIN && largo <= MOTIVO_RETIRO_MAX;
  const confirmado = !pideCodigo || confirmacion === r?.codigo_confirmacion;
  const bloqueo = problema?.tipo === "bloqueo" || problema?.tipo === "conflicto";
  const puedeRetirar = !!r && !bloqueadaPorReferencias && motivoValido && confirmado && !enviando && !bloqueo;

  // Por qué «Retirar» sigue deshabilitado (descripción accesible del botón).
  const razon = !r ? null
    : bloqueadaPorReferencias ? "No se puede retirar mientras existan las referencias de la lista."
    : bloqueo ? null
    : !motivoValido ? `Escriba un motivo de ${MOTIVO_RETIRO_MIN} a ${MOTIVO_RETIRO_MAX} caracteres.`
    : !confirmado ? "Escriba el código del documento exactamente para confirmar."
    : null;

  async function retirar() {
    if (!puedeRetirar || !r) return;
    setEnviando(true);
    setProblema(null);
    setErrorMotivo(null);
    setErrorConfirmacion(null);
    try {
      const cuerpo = pideCodigo ? { motivo: motivo.trim(), confirmacion } : { motivo: motivo.trim() };
      alRetirar(await conocimientoApi.retirar(documento.id_documento, cuerpo));
    } catch (e) {
      if (e instanceof ErrorRetiro && e.codigo === "REFERENCIAS_VIGENTES") {
        setCarga({ estado: "listo", r: { ...r, referencias: e.referencias, puede_retirarse: false } });
      } else if (e instanceof ErrorRetiro && e.codigo === "MOTIVO_INVALIDO") {
        setErrorMotivo(e.message);
      } else if (e instanceof ErrorRetiro && e.codigo === "CONFIRMACION_INCORRECTA") {
        setErrorConfirmacion(e.message);
      } else if (e instanceof ErrorApi && e.estado === 409) {
        setProblema({ tipo: "conflicto", texto: `La guía cambió mientras se revisaba: ${e.message}.` });
      } else if (e instanceof ErrorApi && e.estado === 423) {
        setProblema({ tipo: "bloqueo", texto: e.message });
      } else if (e instanceof ErrorApi && e.estado === 403) {
        setProblema({ tipo: "error", texto: "Su rol no tiene permiso para retirar guías." });
      } else {
        setProblema({ tipo: "error", texto: `No se pudo retirar la guía: ${mensajeError(e)}` });
      }
    } finally {
      setEnviando(false);
    }
  }

  const nombre = nombreGuia(documento);
  return (
    <Modal id="m11-retiro" titulo={`Retirar «${nombre}»`} icono="!" alCerrar={alCerrar} focoAlCerrar={focoAlCerrar}
           focoInicial={campoMotivo} descripcion={<p>{TEXTO_RETIRO}</p>}>
      {carga.estado === "cargando" ? (
        <p className="vacio" role="status">Revisando si otras partes del sistema usan esta guía…</p>
      ) : carga.estado === "error" ? (
        <div className="alerta alerta--error" role="alert">
          <p className="alerta__texto">No se pudieron revisar las referencias de la guía: {carga.mensaje}</p>
          <button type="button" className="boton boton--neutro boton--chico" onClick={() => setIntento((n) => n + 1)}>
            Reintentar
          </button>
        </div>
      ) : bloqueadaPorReferencias ? (
        <div className="alerta alerta--aviso retiro__referencias" role="alert">
          <p className="alerta__texto" id={ids.lista}>{TEXTO_BLOQUEO_REFERENCIAS}</p>
          <ul aria-labelledby={ids.lista}>
            {carga.r.referencias.map((x, i) => (
              <li key={`${x.tipo}-${i}`}><strong>{TIPOS_REFERENCIA[x.tipo] ?? x.tipo}:</strong> {x.descripcion}</li>
            ))}
          </ul>
        </div>
      ) : (
        <div className="modal__campos retiro__formulario">
          <p className="texto-tenue">
            {carga.r.nivel === 2
              ? "Guía de nivel 2 (metodológica): se retira con el motivo."
              : "Guía de nivel 1 (citable): no tiene referencias vigentes; confirme escribiendo su código."}
          </p>
          <div className="retiro__campo">
            <label htmlFor={ids.motivo}>Motivo del retiro <span className="obligatorio" aria-hidden="true">*</span></label>
            <textarea id={ids.motivo} ref={campoMotivo} rows={3} value={motivo} maxLength={MOTIVO_RETIRO_MAX + 50} required
                      aria-invalid={errorMotivo ? true : undefined}
                      aria-describedby={[ids.contador, errorMotivo ? `${ids.motivo}-error` : ""].filter(Boolean).join(" ")}
                      onChange={(e) => { setMotivo(e.target.value); setErrorMotivo(null); }} />
            <p className="campo__ayuda" id={ids.contador}>
              {largo} de {MOTIVO_RETIRO_MAX} caracteres (mínimo {MOTIVO_RETIRO_MIN})
            </p>
            {errorMotivo && <p className="campo__error" id={`${ids.motivo}-error`}>{errorMotivo}</p>}
          </div>
          {pideCodigo && (
            <div className="retiro__campo">
              <label htmlFor={ids.confirmacion}>
                Escriba el código del documento (<span className="retiro__codigo">{carga.r.codigo_confirmacion}</span>) para confirmar
              </label>
              <input id={ids.confirmacion} type="text" value={confirmacion} autoComplete="off" spellCheck={false}
                     aria-invalid={errorConfirmacion ? true : undefined}
                     aria-describedby={[ids.ayuda, errorConfirmacion ? `${ids.confirmacion}-error` : ""].filter(Boolean).join(" ")}
                     onChange={(e) => { setConfirmacion(e.target.value); setErrorConfirmacion(null); }} />
              <p className="campo__ayuda" id={ids.ayuda}>Debe coincidir exactamente, con mayúsculas, espacios y signos.</p>
              {errorConfirmacion && <p className="campo__error" id={`${ids.confirmacion}-error`}>{errorConfirmacion}</p>}
            </div>
          )}
        </div>
      )}

      {problema && (
        <div className={`alerta ${problema.tipo === "error" ? "alerta--error" : "alerta--aviso"}`} role="alert">
          <p className="alerta__texto">{problema.texto}</p>
          {problema.tipo === "conflicto" && (
            <button type="button" className="boton boton--neutro boton--chico" onClick={alRecargar}>Recargar</button>
          )}
        </div>
      )}

      <div className="acciones">
        <button type="button" className="boton boton--neutro" onClick={alCerrar}>Cancelar</button>
        <button type="button" className="boton boton--peligro" disabled={!puedeRetirar}
                aria-describedby={razon ? ids.razon : undefined} onClick={() => void retirar()}>
          {enviando ? "Retirando…" : "Retirar"}
        </button>
      </div>
      {razon && <p className="campo__ayuda retiro__razon" id={ids.razon}>{razon}</p>}
    </Modal>
  );
}
