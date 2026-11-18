// Tipos del contrato del reporte exportable (M09, HU10; Sprint 3, parte C1). La pantalla es la parte C2.
// Fuente: docs/contrato_reportes.md y los fixtures de src/__fixtures__ (reporte_vista_previa_*.json y
// reportes_lista.json), que genera el backend (tests/test_c1_reportes.py).

export type DestinoReporte = "EXPEDIENTE" | "CUIDADOR";

export type SeccionReporte =
  | "PACIENTE"
  | "CLASIFICACION"
  | "RECOMENDACION"
  | "EVIDENCIAS"
  | "ADVERTENCIAS"
  | "VERIFICACION"
  | "DECISION"
  | "FIRMA";

// Secciones admitidas por destino, en el orden del reporte; PACIENTE y CLASIFICACION van siempre.
export const SECCIONES_POR_DESTINO: Record<DestinoReporte, SeccionReporte[]> = {
  EXPEDIENTE: ["PACIENTE", "CLASIFICACION", "RECOMENDACION", "EVIDENCIAS", "ADVERTENCIAS", "VERIFICACION", "DECISION", "FIRMA"],
  CUIDADOR: ["PACIENTE", "CLASIFICACION", "RECOMENDACION", "FIRMA"],
};
export const SECCIONES_OBLIGATORIAS: SeccionReporte[] = ["PACIENTE", "CLASIFICACION"];

// POST /api/consultas/{id}/reportes
export type ReporteEntrada = { destino: DestinoReporte; secciones: SeccionReporte[]; formato?: "PDF" };

export type CampoReporte = { etiqueta: string; valor: string };
export type ItemReporte = { texto: string; detalle: string[] };
// RECUERDE: indicaciones generales del reporte para el cuidador (se agrega siempre en ese destino).
export type BloqueReporte = {
  seccion: SeccionReporte | "RECUERDE";
  titulo: string;
  campos: CampoReporte[];
  parrafos: string[];
  items: ItemReporte[];
};

// GET /api/consultas/{id}/reportes/vista-previa: el contenido del PDF, sin número ni fecha de emisión.
export type VistaPreviaReporte = {
  id_consulta: string;
  destino: DestinoReporte;
  secciones: SeccionReporte[];
  modo_prueba: boolean;
  revision_pendiente: boolean; // reporte del cuidador con frases aún no aprobadas
  titulo: string;
  introduccion: string | null;
  establecimiento: string;
  fecha_consulta: string;
  avisos: string[]; // se repiten en cada página del PDF
  bloques: BloqueReporte[];
  frase_final: string;
  firma: boolean;
  generado_por: string;
};

// GET /api/consultas/{id}/reportes: del más reciente al más antiguo, sin el PDF.
export type ReporteListado = {
  numero_reporte: string; // EV-AAAA-NNNNN
  destino: DestinoReporte;
  secciones: SeccionReporte[];
  formato: "PDF" | "IMPRESION";
  fecha_generacion: string;
  hash_documento: string | null; // SHA-256 del PDF entregado
};

// Cabeceras de la respuesta del POST (el cuerpo es el PDF).
export const CABECERA_NUMERO = "X-Reporte-Numero";
export const CABECERA_HASH = "X-Reporte-Hash";
