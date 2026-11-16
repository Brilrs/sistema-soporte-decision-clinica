// M06 · Datos faltantes (HU15, RF5). Ventana sobre la consulta cuando termina en DATOS_FALTANTES:
// muestra los datos mínimos disponibles y pide solo los que faltan. Desde la consulta solo se
// completa la hemoglobina (con su método) del mismo tamizaje: POST /api/consultas/{id}/datos-faltantes
// reanuda como consulta nueva y su avance se muestra aquí. Los demás datos (edad, sexo, altitud,
// fecha) se corrigen en la ficha, en un tamizaje nuevo o en el catálogo, como indica la ventana.
import { useRef, useState, type FormEvent, type RefObject } from "react";
import type { TamizajeHistorial } from "../../api/pacientes";
import { DATOS_MINIMOS } from "../../consulta/textos";
import { METODOS, fecha, leerDecimal } from "../../utilidades/formato";
import Modal from "../Modal";
import AvanceReanudacion from "./AvanceReanudacion";
import { useReanudacion } from "./useReanudacion";

export type DatoPendiente = { etiqueta: string; mensaje?: string | null };

// Mismos límites que el tamizaje (M14) y que el backend: de 3.0 a 20.0 g/dL, con un decimal.
export const HB_MINIMA = 3;
export const HB_MAXIMA = 20;

export function validarHemoglobina(texto: string): string | null {
  const limpio = texto.trim();
  if (!limpio) return "Ingrese la hemoglobina.";
  const valor = leerDecimal(limpio);
  if (valor === null) return "La hemoglobina debe ser un número, por ejemplo 10.6.";
  if (/[.,]\d{2,}$/.test(limpio)) return "Use un solo decimal, por ejemplo 10.6.";
  if (valor < HB_MINIMA || valor > HB_MAXIMA) return "La hemoglobina debe estar entre 3.0 y 20.0 g/dL.";
  return null;
}

const COMO_CORREGIR: Record<string, string> = {
  altitud: "La altitud sale del distrito de residencia: la corrige el administrador en el catálogo de distritos.",
};
const CORREGIR_EN_FICHA = "Se corrige con «Editar datos» del paciente o registrando un nuevo tamizaje.";

type Props = {
  idPaciente: string;
  idConsulta: string;
  faltantes: DatoPendiente[];
  tamizaje: TamizajeHistorial | null;
  alCerrar: () => void;
  focoAlCerrar?: RefObject<HTMLElement | null>;
};

export default function VentanaDatosFaltantes({ idPaciente, idConsulta, faltantes, tamizaje, alCerrar, focoAlCerrar }: Props) {
  const { estado, completarDatos, cancelar, enCurso, sinResultado } = useReanudacion(idPaciente);
  const [hb, setHb] = useState("");
  const [metodo, setMetodo] = useState<string>(tamizaje?.metodo_medicion ?? "");
  const [error, setError] = useState<string | null>(null);
  const campoHb = useRef<HTMLInputElement>(null);

  const etiquetas = faltantes.map((f) => f.etiqueta);
  const pideHb = etiquetas.includes("hemoglobina");
  const otros = faltantes.filter((f) => f.etiqueta !== "hemoglobina");
  const completable = pideHb && otros.length === 0;
  const bloqueado = enCurso || estado.fase === "terminada" || estado.fase === "cancelada";

  function enviar(e: FormEvent) {
    e.preventDefault();
    if (bloqueado) return;
    const problema = validarHemoglobina(hb);
    setError(problema);
    if (problema) {
      campoHb.current?.focus();
      return;
    }
    void completarDatos(idConsulta, {
      hemoglobina_g_dl: leerDecimal(hb) as number,
      metodo_medicion: (metodo || null) as "HEMOGLOBINOMETRO" | "LABORATORIO" | null,
    });
  }

  const mensajeDe = (f: DatoPendiente) =>
    f.mensaje || DATOS_MINIMOS.find((d) => d.etiqueta === f.etiqueta)?.mensaje || "";

  return (
    <Modal id="m06" titulo="Falta información para evaluar" alCerrar={alCerrar} cerrable={!enCurso}
           focoInicial={completable ? campoHb : undefined} focoAlCerrar={focoAlCerrar}
           descripcion={<p>Para calcular la clasificación de anemia se {faltantes.length === 1 ? "necesita el siguiente dato" : "necesitan los siguientes datos"}:</p>}>
      <form onSubmit={enviar} noValidate>
        {pideHb && (
          <fieldset className="modal__campos" disabled={bloqueado || !completable}>
            <legend className="solo-lectores">Datos que faltan</legend>
            <label htmlFor="m06-hb">Hemoglobina (g/dL)<span className="obligatorio" aria-hidden="true"> *</span></label>
            <input id="m06-hb" ref={campoHb} inputMode="decimal" autoComplete="off" placeholder="Ej.: 10.6" value={hb}
                   aria-required="true" aria-invalid={error ? true : undefined}
                   aria-describedby={`m06-hb-ayuda${error ? " m06-hb-error" : ""}`}
                   onChange={(e) => setHb(e.target.value)} />
            <p id="m06-hb-ayuda" className="campo__ayuda">
              {mensajeDe({ etiqueta: "hemoglobina" })} Valor del tamizaje
              {tamizaje ? ` del ${fecha(tamizaje.fecha_tamizaje)}` : " más reciente"}, entre 3.0 y 20.0 g/dL con un decimal.
            </p>
            {error && <p id="m06-hb-error" className="campo__error" role="alert">{error}</p>}
            <label htmlFor="m06-metodo">Método de medición</label>
            <select id="m06-metodo" value={metodo} onChange={(e) => setMetodo(e.target.value)}>
              <option value="">No registrado</option>
              {Object.entries(METODOS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
          </fieldset>
        )}

        {otros.length > 0 && (
          <div className="alerta alerta--aviso modal__no-completables">
            <p className="alerta__texto">
              {otros.length === 1 ? "Este dato no se puede completar" : "Estos datos no se pueden completar"} desde la consulta:
            </p>
            <ul>
              {otros.map((f) => (
                <li key={f.etiqueta}><strong>{f.etiqueta}</strong>: {mensajeDe(f)} {COMO_CORREGIR[f.etiqueta] ?? CORREGIR_EN_FICHA}</li>
              ))}
            </ul>
          </div>
        )}

        <div className="modal__disponibles">
          <span>Datos disponibles:</span>
          <ul>
            {DATOS_MINIMOS.map((d) => {
              const falta = etiquetas.includes(d.etiqueta);
              return (
                <li key={d.etiqueta} className={falta ? "modal__dato--falta" : undefined}>
                  {d.etiqueta} <span aria-hidden="true">{falta ? "✗" : "✓"}</span>
                  <span className="solo-lectores">{falta ? " (falta)" : " (disponible)"}</span>
                </li>
              );
            })}
          </ul>
        </div>

        <AvanceReanudacion estado={estado} enCurso={enCurso} sinResultado={sinResultado} cancelar={cancelar} />

        <div className="acciones">
          <button type="button" className="boton boton--neutro" onClick={alCerrar} disabled={enCurso}>
            {completable ? "Cancelar" : "Cerrar"}
          </button>
          {completable && (
            <button type="submit" className="boton boton--primario" disabled={bloqueado}>
              {enCurso ? "Evaluando…" : "Completar y evaluar"}
            </button>
          )}
        </div>
      </form>
    </Modal>
  );
}
