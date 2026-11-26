// Textos de M09 (reporte exportable). Los avisos son los mismos que el backend imprime en el PDF.
import type { DestinoReporte, SeccionReporte } from "../../api/tipos_reporte";

export const AVISO_PRUEBA = "MODO DE PRUEBA, no es un documento clínico";
export const AVISO_REVISION = "Texto en revisión clínica: no entregar a pacientes";
export const FRASE_FINAL = "La decisión final corresponde al profesional tratante.";
// En el reporte para el cuidador, una frase para la familia (fila 166); la imprime el backend.
export const FRASE_FINAL_CUIDADOR = "Estas indicaciones las revisa y confirma el personal de salud que atiende a su niña o niño.";
export const FRASES_FINALES: Record<DestinoReporte, string> = { EXPEDIENTE: FRASE_FINAL, CUIDADOR: FRASE_FINAL_CUIDADOR };

export const DESTINOS: Record<DestinoReporte, { etiqueta: string; ayuda: string }> = {
  EXPEDIENTE: { etiqueta: "Expediente clínico", ayuda: "Reporte completo para la historia clínica." },
  CUIDADOR: { etiqueta: "Entrega al cuidador", ayuda: "Lenguaje sencillo, con frases fijas revisadas por el personal de salud." },
};

export const SECCIONES: Record<DestinoReporte, Partial<Record<SeccionReporte, string>>> = {
  EXPEDIENTE: {
    PACIENTE: "Datos del paciente",
    CLASIFICACION: "Clasificación y nivel de riesgo",
    RECOMENDACION: "Recomendación clínica",
    EVIDENCIAS: "Evidencias citadas",
    ADVERTENCIAS: "Advertencias",
    VERIFICACION: "Verificación de la respuesta",
    DECISION: "Decisión del profesional",
    FIRMA: "Espacio de firma y sello",
  },
  CUIDADOR: {
    PACIENTE: "Datos de la niña o el niño",
    CLASIFICACION: "Resultado de la evaluación",
    RECOMENDACION: "Indicaciones del personal de salud",
    FIRMA: "Espacio de firma y sello",
  },
};

export const AYUDA_REPORTES_ANTERIORES =
  "El sistema no guarda los PDF: solo su número y su huella (SHA-256). Para otra copia, genere un reporte nuevo, que tendrá otro número.";
export const AYUDA_GENERADO =
  "Descárguelo o ábralo para imprimir ahora: el PDF solo queda en esta página y se borra al salir de ella.";
