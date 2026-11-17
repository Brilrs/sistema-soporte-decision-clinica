// Textos de los estados finales de una consulta, compartidos por M04 (consulta) y M05 (resultado).
import type { EstadoFinal, TipoDecision } from "../api/tipos_consulta";

export const TITULOS_ESTADO: Record<EstadoFinal, string> = {
  VERIFICADA: "Respuesta verificada",
  EVIDENCIA_INSUFICIENTE: "Evidencia insuficiente",
  ERROR: "Problema técnico al procesar la consulta",
  DATOS_FALTANTES: "Faltan datos del tamizaje",
  TAMIZAJE_NO_VIGENTE: "El tamizaje no está vigente",
  FUERA_DE_DOMINIO: "Consulta fuera del alcance del sistema",
  SOLICITUD_BLOQUEADA: "Solicitud bloqueada para proteger los datos del paciente",
};

// Solo si el backend no envía mensaje.
export const MENSAJES_POR_DEFECTO: Record<EstadoFinal, string> = {
  VERIFICADA: "",
  EVIDENCIA_INSUFICIENTE: "Evidencia insuficiente: aplicar criterio clínico.",
  ERROR: "No se pudo evaluar la consulta. Aplique su criterio clínico.",
  DATOS_FALTANTES: "Complete el registro del tamizaje para continuar.",
  TAMIZAJE_NO_VIGENTE: "Registre un tamizaje nuevo para continuar.",
  FUERA_DE_DOMINIO: "El sistema responde sobre la anemia en niños de 0 a 59 meses.",
  SOLICITUD_BLOQUEADA: "Reformule la consulta sin nombres, documentos ni números de contacto.",
};

// ERROR y SOLICITUD_BLOQUEADA usan siempre estos textos (el del backend es genérico o no explica
// cómo seguir); los demás estados muestran el mensaje del backend.
export const MENSAJE_ERROR =
  "La consulta no pudo completarse. Puede volver a intentarlo; si el problema continúa, aplique su criterio clínico.";

// No repite el dato bloqueado: el backend tampoco lo devuelve.
export const MENSAJE_BLOQUEADA =
  "La solicitud contenía un dato que coincide con la identidad del paciente, como su nombre, DNI, historia clínica o " +
  "teléfono. Para protegerlo, el sistema detuvo la consulta y no envió nada al modelo de lenguaje.";
export const COMO_REFORMULAR_BLOQUEADA =
  "Escriba la pregunta de nuevo sin datos personales. El sistema ya conoce los datos del paciente; por ejemplo: " +
  "«¿Qué dosis de hierro le corresponde?».";

// M07: el mensaje del backend («Evidencia insuficiente: aplicar criterio clínico.») repite el título.
export const MENSAJE_EVIDENCIA_INSUFICIENTE =
  "El sistema no encontró evidencia suficiente en las guías clínicas vigentes para responder esta consulta con " +
  "respaldo documental, por eso no genera una recomendación. Aplique su criterio clínico.";

export const MENSAJES_PROPIOS: Partial<Record<EstadoFinal, string>> = {
  ERROR: MENSAJE_ERROR,
  SOLICITUD_BLOQUEADA: MENSAJE_BLOQUEADA,
  EVIDENCIA_INSUFICIENTE: MENSAJE_EVIDENCIA_INSUFICIENTE,
};

// M07, «Qué puede hacer» (panel derecho del mockup, aquí dentro de la tarjeta del estado).
export const QUE_PUEDE_HACER_EVIDENCIA = [
  "Reformular la pregunta con términos más específicos.",
  "Consultar otras fuentes, como la ficha técnica del medicamento o el servicio de farmacia.",
  "Registrar su decisión clínica; quedará en el historial del paciente.",
];
// asistencia.v_consultas_sin_evidencia reúne estas consultas para el administrador (M11).
export const NOTA_EVIDENCIA_ADMINISTRADOR =
  "Esta consulta queda registrada para que el administrador evalúe incorporar nuevas guías a la base de conocimiento.";

// Decisión clínica (POST /api/consultas/{id}/decision). Las opciones de cada estado y si la nota
// es obligatoria vienen en opciones_decision; aquí solo los textos.
export const TIPOS_DECISION: Record<TipoDecision, { etiqueta: string; ayuda: string }> = {
  ACEPTA_RECOMENDACION: {
    etiqueta: "Acepta la recomendación",
    ayuda: "Aplicará la recomendación tal como la propone el sistema.",
  },
  MODIFICA_RECOMENDACION: {
    etiqueta: "Modifica la recomendación",
    ayuda: "Aplicará la recomendación con cambios; describa en la nota la conducta que adoptará.",
  },
  CRITERIO_CLINICO_PROPIO: {
    etiqueta: "Aplica su criterio clínico",
    ayuda: "Decide la conducta sin seguir una recomendación del sistema.",
  },
};
// Mismo límite que el backend (app/services/decisiones.py, LARGO_MAXIMO_NOTA).
export const LARGO_MAXIMO_NOTA = 1000;
export const AVISO_NOTA_PRIVACIDAD =
  "No escriba nombres, DNI, historia clínica ni teléfonos en la nota: describa solo la conducta clínica.";
export const AVISO_DECISION_DEFINITIVA = "Esta decisión no se puede modificar ni registrar de nuevo.";
export const SIN_PERMISO_DECISION =
  "Su rol no permite registrar decisiones clínicas. La registra el profesional que realizó la consulta.";

export const ROTULO_CLASIFICACION = "Calculada por reglas a partir del tamizaje, no por el modelo.";

// Datos mínimos de la validación (backend: app/rag/validacion.py, DATOS_MINIMOS), en su orden.
// El mensaje se usa si el evento fin solo trae la etiqueta.
export const DATOS_MINIMOS: { etiqueta: string; mensaje: string }[] = [
  { etiqueta: "edad", mensaje: "La edad en meses define el punto de corte de hemoglobina." },
  { etiqueta: "sexo", mensaje: "El sexo forma parte del contexto clínico mínimo de la consulta." },
  { etiqueta: "altitud", mensaje: "La altitud de residencia ajusta la hemoglobina antes de clasificar." },
  { etiqueta: "hemoglobina", mensaje: "La hemoglobina es necesaria para calcular la clasificación de anemia." },
  { etiqueta: "fecha del tamizaje", mensaje: "La fecha del tamizaje permite comprobar su vigencia." },
];

// El filtro de dominio evalúa solo la pregunta, sin los datos del paciente: las preguntas
// genéricas («¿Cómo lo manejo?») suelen quedar fuera. Ver docs/cambios_respecto_al_OE2.md.
export const SUGERENCIA_FUERA_DE_DOMINIO =
  "Si su pregunta es sobre este paciente, reformúlela mencionando el tema, por ejemplo hierro, hemoglobina, anemia o derivación.";

export const AVISO_DECISION = "La decisión final corresponde al profesional tratante.";

// P6 (F1): el niño cambió de grupo de edad entre el tamizaje y la consulta. Breve y sin alarma.
export function avisoCambioDeTramo(sexo: string | null | undefined, edadTamizaje: number, edadConsulta: number): string {
  const sujeto = sexo === "F" ? "La niña" : sexo === "M" ? "El niño" : "El niño o la niña";
  const meses = (n: number) => `${n} ${n === 1 ? "mes" : "meses"}`;
  return `${sujeto} pasó a otro grupo de edad desde el tamizaje (${meses(edadTamizaje)} entonces, ` +
    `${meses(edadConsulta)} en esta consulta). Verifique que la recomendación aplique a su edad actual.`;
}

export const ETIQUETA_TRADUCCION = "Traducción de apoyo, no oficial";

// Estados graves: se muestran en rojo.
export const ESTADOS_GRAVES: EstadoFinal[] = ["ERROR", "SOLICITUD_BLOQUEADA"];
