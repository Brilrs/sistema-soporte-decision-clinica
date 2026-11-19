// Tipos del contrato de auditoría (M13, HU13; Sprint 3, parte D1). La pantalla es la parte D2.
// Fuente: docs/contrato_auditoria.md y los fixtures de src/__fixtures__ (auditoria_*.json), que genera
// el backend (tests/test_d1_auditoria.py). Ninguna respuesta trae datos que identifiquen al paciente.

export type EstadoAuditado =
  | "EN_PROCESO"
  | "VERIFICADA"
  | "EVIDENCIA_INSUFICIENTE"
  | "ERROR"
  | "DATOS_FALTANTES"
  | "TAMIZAJE_NO_VIGENTE"
  | "FUERA_DE_DOMINIO"
  | "SOLICITUD_BLOQUEADA";

// GET /api/auditoria/indicadores: últimos 30 días, siempre sin consultas de prueba.
export type IndicadoresAuditoria = {
  dias: number;
  desde: string;
  hasta: string;
  consultas: number;
  evaluadas: number; // VERIFICADA más EVIDENCIA_INSUFICIENTE
  por_estado: Record<EstadoAuditado, number>;
  pct_verificadas: number | null; // null sin consultas
  pct_evidencia_insuficiente: number | null;
  con_reintento: number;
  pct_con_reintento: number | null;
  latencia_p50_ms: number | null;
  latencia_p90_ms: number | null;
  latencia_p90_flujo_normal_ms: number | null; // consultas con un intento o sin llamada al modelo
  solicitudes_bloqueadas: number;
  errores: number;
  tokens_entrada: number;
  tokens_salida: number;
  costo_api_usd: number;
};

// GET /api/auditoria/consultas: una fila por consulta, de la más reciente a la más antigua.
export type ConsultaAuditada = {
  id_consulta: string;
  fecha_hora_inicio: string;
  fecha_hora_fin: string | null;
  nombre_usuario: string; // usuario del sistema que consultó, nunca el paciente
  estado: EstadoAuditado;
  numero_intentos: number;
  con_reintento: boolean;
  latencia_total_ms: number | null;
  modo_prueba: boolean;
  modelo_llm: string | null; // del último intento; null sin llamada al modelo
  version_prompt: string | null;
  tokens_entrada: number | null;
  tokens_salida: number | null;
  tokens_total: number | null;
  costo_usd: number | null;
};

export type PaginaAuditoria = {
  total: number;
  limite: number;
  desplazamiento: number;
  incluir_pruebas: boolean;
  consultas: ConsultaAuditada[];
};

// Filtros de la lista (todos opcionales). Fechas AAAA-MM-DD, días de Lima, inclusivos.
export type FiltrosAuditoria = {
  estado?: EstadoAuditado;
  fecha_desde?: string;
  fecha_hasta?: string;
  incluir_pruebas?: boolean; // por omisión false: las de prueba se ocultan
  limite?: number; // 20 por omisión, 100 como máximo
  desplazamiento?: number;
};

// GET /api/auditoria/consultas/{id}
export type VerificacionAuditada = {
  valida_citas: boolean | null; // 6.1 Citas textuales
  valida_consistencia: boolean | null; // 6.2 Consistencia y dosis
  valida_evidencia: boolean | null; // 6.3 Suficiencia de la evidencia
  relevancia_maxima: number | null;
  umbral_relevancia: number | null;
};

export type FragmentoAuditado = {
  etiqueta: string | null; // F-01 a F-05
  puntaje_reranker: number | null; // null en un fragmento agregado por referencia
  origen: "RERANKER" | "PUNTERO" | null;
  posicion_final: number | null;
  documento: string | null;
  seccion: string | null;
  pagina_inicio: number | null;
  pagina_fin: number | null;
};

export type IntentoAuditado = {
  numero_intento: number;
  tipo_busqueda: "INICIAL" | "AMPLIADA" | null;
  resultado: string | null;
  modelo_llm: string | null;
  version_prompt: string | null;
  tokens_entrada: number | null;
  tokens_salida: number | null;
  tokens_razonamiento: number | null;
  costo_usd: number | null;
  latencia_llm_ms: number | null;
  candidatos_evaluados: number | null;
  verificacion: VerificacionAuditada;
  control_identificadores: boolean | null; // false: la solicitud se bloqueó
  hash_solicitud: string | null;
  solicitud_enviada: Record<string, unknown> | null; // null si no se envió o se bloqueó
  fragmentos: FragmentoAuditado[];
};

export type DetalleAuditoria = {
  id_consulta: string;
  fecha_hora_inicio: string;
  fecha_hora_fin: string | null;
  nombre_usuario: string;
  estado: EstadoAuditado;
  numero_intentos: number;
  latencia_total_ms: number | null;
  confirma_tamizaje_no_vigente: boolean;
  modo_prueba: boolean;
  tokens_entrada: number | null;
  tokens_salida: number | null;
  tokens_total: number | null;
  costo_usd: number | null;
  intentos: IntentoAuditado[];
};
