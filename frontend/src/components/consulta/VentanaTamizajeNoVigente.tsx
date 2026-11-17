// M15 · Tamizaje no vigente (HU15, HU18, RF5). Ventana sobre la consulta cuando termina en
// TAMIZAJE_NO_VIGENTE: días transcurridos frente al plazo de vigencia y resumen del tamizaje.
// «Registrar nuevo tamizaje» (recomendada) lleva a M14, que al guardar vuelve a la consulta con la
// pregunta. «Continuar con este tamizaje» llama a POST /api/consultas/{id}/continuar, que reanuda
// en el servidor con la pregunta original guardada (el cliente ya no la reenvía, P5) y muestra el
// avance aquí. La pregunta solo se usa para dejarla escrita en M04 al volver de M14.
import { type RefObject } from "react";
import { useNavigate } from "react-router-dom";
import type { TamizajeHistorial } from "../../api/pacientes";
import type { Vigencia } from "../../api/tipos_consulta";
import { decimal, fecha } from "../../utilidades/formato";
import { EtiquetaClasificacion } from "../Etiquetas";
import Modal from "../Modal";
import AvanceReanudacion from "./AvanceReanudacion";
import { useReanudacion } from "./useReanudacion";

export const AVISO_CONTINUAR =
  "Si continúa, la evaluación usará un tamizaje vencido: la clasificación y la recomendación pueden no reflejar el " +
  "estado actual del niño o la niña y deben interpretarse con cautela. La consulta quedará registrada como realizada " +
  "con un tamizaje no vigente.";

const dias = (n: number) => `${n} ${n === 1 ? "día" : "días"}`;

type Props = {
  idPaciente: string;
  idConsultaPrevia: string;
  pregunta: string; // solo para dejarla escrita en M04 al volver de «Registrar nuevo tamizaje»
  tamizaje: TamizajeHistorial | null;
  vigencia: Vigencia | null;
  puedeRegistrar: boolean;
  alCerrar: () => void;
  focoAlCerrar?: RefObject<HTMLElement | null>;
};

export default function VentanaTamizajeNoVigente({
  idPaciente, idConsultaPrevia, pregunta, tamizaje, vigencia, puedeRegistrar, alCerrar, focoAlCerrar,
}: Props) {
  const navegar = useNavigate();
  const { estado, continuarTamizajeNoVigente, cancelar, enCurso, sinResultado } = useReanudacion(idPaciente);
  const bloqueado = enCurso || estado.fase === "terminada" || estado.fase === "cancelada";
  const transcurridos = vigencia?.dias_transcurridos ?? null;
  const plazo = vigencia?.dias_vigencia ?? null;

  function continuar() {
    if (bloqueado) return;
    void continuarTamizajeNoVigente(idConsultaPrevia);
  }

  function registrarNuevo() {
    navegar(`/pacientes/${idPaciente}/tamizajes/nuevo`, { state: { volverAConsulta: { pregunta } } });
  }

  return (
    <Modal id="m15" titulo="El tamizaje no está vigente" alCerrar={alCerrar} cerrable={!enCurso} focoAlCerrar={focoAlCerrar}
           descripcion={
             <p>
               La evaluación usaría el tamizaje registrado hace{" "}
               <strong>{transcurridos !== null ? dias(transcurridos) : "más días de los permitidos"}</strong>.
               {plazo !== null && <> El plazo de vigencia configurado es de {dias(plazo)}.</>}
             </p>
           }>
      {tamizaje && (
        <div className="modal__tamizaje">
          <span className="modal__tamizaje-rotulo">Tamizaje disponible</span>
          <p>
            <strong>{fecha(tamizaje.fecha_tamizaje)}</strong>
            {tamizaje.hemoglobina_g_dl !== null && <> · Hb {decimal(tamizaje.hemoglobina_g_dl)} g/dL</>}
            {" "}<EtiquetaClasificacion categoria={tamizaje.clasificacion?.categoria ?? null} />
            {tamizaje.peso_kg !== null && <> · Peso {decimal(tamizaje.peso_kg)} kg</>}
            {tamizaje.talla_cm !== null && <> · Talla {decimal(tamizaje.talla_cm)} cm</>}
          </p>
        </div>
      )}
      <p className="modal__texto">
        Para evaluar el estado actual se recomienda registrar el tamizaje del control de hoy.
      </p>
      <p className="alerta alerta--aviso modal__cautela" id="m15-cautela">{AVISO_CONTINUAR}</p>

      <AvanceReanudacion estado={estado} enCurso={enCurso} sinResultado={sinResultado} cancelar={cancelar} />

      <div className="acciones">
        <button type="button" className="boton boton--neutro" onClick={alCerrar} disabled={enCurso}>Cancelar</button>
        <button type="button" className="boton boton--secundario boton--auto" onClick={continuar}
                disabled={bloqueado} aria-describedby="m15-cautela">
          {enCurso ? "Evaluando…" : "Continuar con este tamizaje"}
        </button>
        {puedeRegistrar && (
          <button type="button" className="boton boton--primario" onClick={registrarNuevo} disabled={enCurso}>
            Registrar nuevo tamizaje
          </button>
        )}
      </div>
      {!puedeRegistrar && (
        <p className="texto-tenue modal__nota">Su rol no registra tamizajes: solicite el registro del control de hoy al personal de enfermería.</p>
      )}
    </Modal>
  );
}
