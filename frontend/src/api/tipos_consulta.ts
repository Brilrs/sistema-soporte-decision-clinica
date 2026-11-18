// Tipos del contrato de consultas clínicas (Sprint 2, partes D2 y E0).
// Fuente: docs/contrato_consultas.md y los fixtures de src/__fixtures__, que genera el backend
// (tests/test_e0_fixtures.py). A diferencia de Sprint 1, aquí los decimales llegan como número.

export const ESTADOS_FINALES = [
  "VERIFICADA",
  "EVIDENCIA_INSUFICIENTE",
  "ERROR",
  "DATOS_FALTANTES",
  "TAMIZAJE_NO_VIGENTE",
  "FUERA_DE_DOMINIO",
  "SOLICITUD_BLOQUEADA",
] as const;

export type EstadoFinal = (typeof ESTADOS_FINALES)[number];
// Un resultado guardado o listado puede seguir en proceso (por ejemplo, tras un corte del stream).
export type EstadoConsulta = EstadoFinal | "EN_PROCESO";

export type TipoDecision = "ACEPTA_RECOMENDACION" | "MODIFICA_RECOMENDACION" | "CRITERIO_CLINICO_PROPIO";

export type Nodo = "validar" | "clasificar" | "normalizar" | "recuperar" | "proteger" | "generar" | "verificar" | "salida";

export type Idioma = "es" | "en";

export type OpcionDecision = { tipo: TipoDecision; nota_obligatoria: boolean };

export type Paso = { tipo: string; texto: string; citas: string[] };

export type Recomendacion = {
  resumen: string;
  recomendacion: Paso[];
  advertencias: string[];
  factores_identificados: string[];
};

export type Cita = {
  etiqueta: string;
  extracto: string;
  extracto_traducido: string | null;
  etiqueta_traduccion: string | null;
  fuente: string | null;
  documento: string;
  seccion: string | null;
  pagina_inicio: number | null;
  pagina_fin: number | null;
  idioma: Idioma;
  // Relevancia según el reranker, de 0 a 1 con 3 decimales (columna «Relevancia» de M05).
  puntaje_reranker: number | null;
  // RERANKER: seleccionado por la recuperación. PUNTERO: agregado porque otro fragmento enviado
  // remite a esta tabla («según Tabla N° 4»); agregado_por_referencia_de es la etiqueta de ese fragmento.
  origen: OrigenCita;
  agregado_por_referencia_de: string | null;
};

export type OrigenCita = "RERANKER" | "PUNTERO";

export type ResultadoIntento = "APROBADO" | "REINTENTO" | "EVIDENCIA_INSUFICIENTE" | "ERROR";

export type Intento = {
  numero: number;
  tipo_busqueda: "INICIAL" | "AMPLIADA";
  candidatos_evaluados: number;
  relevancia_maxima: number | null;
  umbral_relevancia: number;
  resultado: ResultadoIntento;
};

// Controles del intento que decide. null: el control no se llegó a ejecutar.
export type Verificacion = {
  numero_intento: number;
  valida_citas: boolean | null;
  valida_consistencia: boolean | null;
  valida_evidencia: boolean | null;
  relevancia_maxima: number | null;
  umbral_relevancia: number;
};

// Tramo de edad de los puntos de corte de Hb en el tamizaje y en la fecha de la consulta (P6, F1).
// Un tramo null: los puntos de corte no cubren esa edad (por ejemplo, menos de 6 meses).
export type TramoMeses = { edad_min_meses: number; edad_max_meses: number };
export type TramoEdad = {
  edad_meses_tamizaje: number;
  edad_meses_consulta: number;
  tramo_tamizaje: TramoMeses | null;
  tramo_consulta: TramoMeses | null;
  cambio: boolean;
};

export type Vigencia = {
  dias_transcurridos: number | null;
  dias_vigencia: number | null;
  continua_con_tamizaje_no_vigente: boolean | null;
};

export type ClasificacionConsulta = {
  categoria: string;
  nivel_riesgo: string;
  hb_ajustada_g_dl: number;
  ajuste_hb_g_dl: number;
  altitud_msnm: number | null;
  requiere_derivacion: boolean;
  calculada_ahora?: boolean;
};

export type TiemposConsulta = {
  total_ms?: number;
  primer_evento_ms?: number;
  por_nodo?: Partial<Record<Nodo, number>>;
  etapas?: { nodo: Nodo; intento: number | null; ms: number }[];
  espera_ms?: Record<string, number>;
};

// ---------------------------------------------------------------------------
// Eventos del NDJSON (unión discriminada por «tipo»)
// ---------------------------------------------------------------------------
// Los campos opcionales dependen del nodo; los que no corresponden no vienen.
export type EventoEtapa = {
  tipo: "etapa";
  etapa: Nodo;
  intento: number | null;
  ms: number;
  transcurrido_ms: number;
  id_consulta?: string | null;
  resultado?: string | null;
  motivo?: string | null;
  terminos?: number;
  edad_meses?: number;
  tipo_busqueda?: "INICIAL" | "AMPLIADA";
  relevancia_maxima?: number | null;
  suficiente?: boolean;
  seleccionados?: number;
  control_identificadores?: boolean;
  fragmentos?: number;
  generacion?: string | null;
  stop_reason?: string | null;
  siguiente?: string | null;
  estado_final?: EstadoFinal | null;
};

export type EventoEnCola = {
  tipo: "en_cola";
  etapa: Nodo;
  recurso: "modelos" | "llm";
  transcurrido_ms: number;
};

export type EventoFin = {
  tipo: "fin";
  id_consulta: string;
  id_paciente: string;
  id_consulta_previa: string | null;
  estado: EstadoFinal;
  mensaje: string | null;
  idioma: Idioma | null;
  datos_faltantes: string[];
  vigencia: Vigencia;
  clasificacion: ClasificacionConsulta | null;
  recomendacion: Recomendacion | null;
  citas: Cita[];
  numero_intentos: number;
  intentos: Intento[];
  verificacion: Verificacion | null;
  modo_prueba: boolean;
  opciones_decision: OpcionDecision[];
  tiempos_ms: TiemposConsulta | null;
  transcurrido_ms: number;
};

// Falla inesperada: la consulta queda en ERROR. id_consulta es null si falló antes de registrarse.
export type EventoError = {
  tipo: "error";
  id_consulta: string | null;
  id_paciente: string;
  estado: "ERROR";
  mensaje: string;
  opciones_decision: OpcionDecision[];
  transcurrido_ms: number;
};

export type EventoConsulta = EventoEtapa | EventoEnCola | EventoFin | EventoError;
export type EventoFinal = EventoFin | EventoError;

const TIPOS_EVENTO: ReadonlySet<string> = new Set(["etapa", "en_cola", "fin", "error"]);

// Un evento de tipo desconocido (de una versión futura del backend) no es un EventoConsulta: el
// lector lo ignora sin romper.
export function esEventoConocido(valor: unknown): valor is EventoConsulta {
  return (
    typeof valor === "object" &&
    valor !== null &&
    typeof (valor as { tipo?: unknown }).tipo === "string" &&
    TIPOS_EVENTO.has((valor as { tipo: string }).tipo)
  );
}

export function esEventoFinal(evento: EventoConsulta): evento is EventoFinal {
  return evento.tipo === "fin" || evento.tipo === "error";
}

// ---------------------------------------------------------------------------
// Respuestas JSON
// ---------------------------------------------------------------------------
export type DatoFaltante = { campo: string; etiqueta: string; mensaje: string; completado: boolean };

export type Decision = {
  id_decision: string;
  id_usuario: string;
  tipo_decision: TipoDecision;
  nota: string | null;
  fecha_registro: string;
  // Nombre visible de quien la registró (P12, Sprint 3 parte B). Opcional para los datos anteriores.
  registrada_por?: string | null;
};

// GET /api/consultas/{id}
export type ResultadoConsulta = {
  id_consulta: string;
  id_paciente: string;
  id_tamizaje: string;
  id_consulta_previa: string | null;
  estado: EstadoConsulta;
  mensaje: string | null;
  idioma: Idioma;
  texto_filtrado: string | null;
  numero_intentos: number;
  fecha_hora_inicio: string;
  fecha_hora_fin: string | null;
  latencia_total_ms: number | null;
  datos_faltantes: DatoFaltante[];
  vigencia: Vigencia;
  clasificacion: ClasificacionConsulta | null;
  recomendacion: Recomendacion | null;
  citas: Cita[];
  intentos: Intento[];
  verificacion: Verificacion | null;
  modo_prueba: boolean;
  // Solo en el GET (el evento fin no lo trae): null hasta que llega.
  tramo_edad: TramoEdad | null;
  decision: Decision | null;
  opciones_decision: OpcionDecision[];
};

// GET /api/consultas: consultas del usuario de todos sus pacientes (P10, Sprint 3 parte B). Del
// paciente solo trae el nombre y la historia clínica, los mismos datos que muestra M02.
export type ConsultaPropia = {
  id_consulta: string;
  id_paciente: string;
  nombres_apellidos: string;
  numero_hc: string;
  edad_meses: number; // en la fecha de la consulta
  estado: EstadoConsulta;
  categoria: string | null;
  nivel_riesgo: string | null;
  fecha_hora_inicio: string;
  modo_prueba: boolean;
  pregunta: string | null; // pregunta filtrada, recortada a unos 100 caracteres
};

export type PaginaConsultas = { total: number; limite: number; desplazamiento: number; consultas: ConsultaPropia[] };

// Filtros de GET /api/consultas: fechas AAAA-MM-DD (días de Lima, inclusivos).
export type FiltrosConsultas = {
  estado?: EstadoConsulta | "";
  fecha_desde?: string;
  fecha_hasta?: string;
  limite?: number;
  desplazamiento?: number;
};

// GET /api/pacientes/{id}/consultas (y «consultas» del historial)
export type ConsultaListada = {
  id_consulta: string;
  id_tamizaje: string;
  fecha_tamizaje: string;
  id_consulta_previa: string | null;
  estado: EstadoConsulta;
  texto_filtrado: string | null;
  idioma: Idioma;
  fecha_hora_inicio: string;
  fecha_hora_fin: string | null;
  numero_intentos: number;
  latencia_total_ms: number | null;
  confirma_tamizaje_no_vigente: boolean;
  categoria: string | null;
  tipo_decision: TipoDecision | null;
  modo_prueba: boolean;
};

// ---------------------------------------------------------------------------
// Entradas
// ---------------------------------------------------------------------------
export type ConsultaEntrada = {
  texto_consulta: string;
  id_tamizaje?: string | null;
  confirma_tamizaje_no_vigente?: boolean;
  id_consulta_previa?: string | null;
};

export type DatosFaltantesEntrada = {
  hemoglobina_g_dl: number;
  metodo_medicion?: "HEMOGLOBINOMETRO" | "LABORATORIO" | null;
};

export type DecisionEntrada = { tipo_decision: TipoDecision; nota?: string | null };
