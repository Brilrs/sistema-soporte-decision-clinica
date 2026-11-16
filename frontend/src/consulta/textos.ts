// Textos de los estados finales de una consulta, compartidos por M04 (consulta) y M05 (resultado).
import type { EstadoFinal } from "../api/tipos_consulta";

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

export const MENSAJES_PROPIOS: Partial<Record<EstadoFinal, string>> = {
  ERROR: MENSAJE_ERROR,
  SOLICITUD_BLOQUEADA: MENSAJE_BLOQUEADA,
};

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

export const ETIQUETA_TRADUCCION = "Traducción de apoyo, no oficial";

// Estados graves: se muestran en rojo.
export const ESTADOS_GRAVES: EstadoFinal[] = ["ERROR", "SOLICITUD_BLOQUEADA"];
