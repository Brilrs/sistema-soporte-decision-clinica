// Textos de los estados finales de una consulta, compartidos por M04 (consulta) y M05 (resultado).
import type { EstadoFinal } from "../api/tipos_consulta";

export const TITULOS_ESTADO: Record<EstadoFinal, string> = {
  VERIFICADA: "Respuesta verificada",
  EVIDENCIA_INSUFICIENTE: "Evidencia insuficiente",
  ERROR: "No se pudo evaluar la consulta",
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

// El filtro de dominio evalúa solo la pregunta, sin los datos del paciente: las preguntas
// genéricas («¿Cómo lo manejo?») suelen quedar fuera. Ver docs/cambios_respecto_al_OE2.md.
export const SUGERENCIA_FUERA_DE_DOMINIO =
  "Si su pregunta es sobre este paciente, reformúlela mencionando el tema, por ejemplo hierro, hemoglobina, anemia o derivación.";

export const AVISO_DECISION = "La decisión final corresponde al profesional tratante.";

export const ETIQUETA_TRADUCCION = "Traducción de apoyo, no oficial";

// Estados graves: se muestran en rojo.
export const ESTADOS_GRAVES: EstadoFinal[] = ["ERROR", "SOLICITUD_BLOQUEADA"];
