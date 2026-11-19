// Auditoría y trazabilidad (M13, HU13; Sprint 3, parte D2): llamadas a las rutas de la parte D1.
// Contrato: docs/contrato_auditoria.md. Tipos: ./tipos_auditoria.ts.
// Cada respuesta se reduce a los campos que la pantalla conoce (soloConocidos): si el servidor
// agregara un campo nuevo (por ejemplo, uno de identidad del paciente), no llega al estado de la
// pantalla ni se muestra. Nada se guarda en localStorage ni sessionStorage.
import { api } from "./cliente";
import type {
  ConsultaAuditada,
  DetalleAuditoria,
  FiltrosAuditoria,
  FragmentoAuditado,
  IndicadoresAuditoria,
  IntentoAuditado,
  PaginaAuditoria,
  VerificacionAuditada,
} from "./tipos_auditoria";

const CAMPOS_INDICADORES: (keyof IndicadoresAuditoria)[] = [
  "dias", "desde", "hasta", "consultas", "evaluadas", "por_estado", "pct_verificadas", "pct_evidencia_insuficiente",
  "con_reintento", "pct_con_reintento", "latencia_p50_ms", "latencia_p90_ms", "latencia_p90_flujo_normal_ms",
  "solicitudes_bloqueadas", "errores", "tokens_entrada", "tokens_salida", "costo_api_usd",
];
const ESTADOS: (keyof IndicadoresAuditoria["por_estado"])[] = [
  "VERIFICADA", "EVIDENCIA_INSUFICIENTE", "ERROR", "SOLICITUD_BLOQUEADA", "FUERA_DE_DOMINIO", "DATOS_FALTANTES",
  "TAMIZAJE_NO_VIGENTE", "EN_PROCESO",
];
const CAMPOS_CONSULTA: (keyof ConsultaAuditada)[] = [
  "id_consulta", "fecha_hora_inicio", "fecha_hora_fin", "nombre_usuario", "estado", "numero_intentos", "con_reintento",
  "latencia_total_ms", "modo_prueba", "modelo_llm", "version_prompt", "tokens_entrada", "tokens_salida", "tokens_total",
  "costo_usd",
];
const CAMPOS_DETALLE: (keyof DetalleAuditoria)[] = [
  "id_consulta", "fecha_hora_inicio", "fecha_hora_fin", "nombre_usuario", "estado", "numero_intentos", "latencia_total_ms",
  "confirma_tamizaje_no_vigente", "modo_prueba", "tokens_entrada", "tokens_salida", "tokens_total", "costo_usd",
];
const CAMPOS_INTENTO: (keyof IntentoAuditado)[] = [
  "numero_intento", "tipo_busqueda", "resultado", "modelo_llm", "version_prompt", "tokens_entrada", "tokens_salida",
  "tokens_razonamiento", "costo_usd", "latencia_llm_ms", "candidatos_evaluados", "control_identificadores",
  "hash_solicitud", "solicitud_enviada",
];
const CAMPOS_VERIFICACION: (keyof VerificacionAuditada)[] = [
  "valida_citas", "valida_consistencia", "valida_evidencia", "relevancia_maxima", "umbral_relevancia",
];
const CAMPOS_FRAGMENTO: (keyof FragmentoAuditado)[] = [
  "etiqueta", "puntaje_reranker", "origen", "posicion_final", "documento", "seccion", "pagina_inicio", "pagina_fin",
];

// Copia solo las claves indicadas (las que faltan quedan en null).
export function soloConocidos<T>(origen: unknown, campos: (keyof T)[]): T {
  const datos = (origen ?? {}) as Record<string, unknown>;
  const salida: Record<string, unknown> = {};
  for (const c of campos) salida[c as string] = datos[c as string] ?? null;
  return salida as T;
}

export function limpiarIndicadores(d: unknown): IndicadoresAuditoria {
  const i = soloConocidos<IndicadoresAuditoria>(d, CAMPOS_INDICADORES);
  return { ...i, por_estado: soloConocidos(i.por_estado, ESTADOS) };
}

export function limpiarPagina(d: unknown): PaginaAuditoria {
  const p = soloConocidos<PaginaAuditoria>(d, ["total", "limite", "desplazamiento", "incluir_pruebas", "consultas"]);
  return { ...p, consultas: (p.consultas ?? []).map((c) => soloConocidos<ConsultaAuditada>(c, CAMPOS_CONSULTA)) };
}

export function limpiarDetalle(d: unknown): DetalleAuditoria {
  const det = soloConocidos<DetalleAuditoria>(d, [...CAMPOS_DETALLE, "intentos"]);
  return {
    ...det,
    intentos: (det.intentos ?? []).map((i) => {
      const intento = soloConocidos<IntentoAuditado>(i, [...CAMPOS_INTENTO, "verificacion", "fragmentos"]);
      return {
        ...intento,
        verificacion: soloConocidos<VerificacionAuditada>(intento.verificacion, CAMPOS_VERIFICACION),
        fragmentos: (intento.fragmentos ?? []).map((f) => soloConocidos<FragmentoAuditado>(f, CAMPOS_FRAGMENTO)),
      };
    }),
  };
}

export function parametrosAuditoria(f: FiltrosAuditoria): string {
  const p = new URLSearchParams();
  if (f.estado) p.set("estado", f.estado);
  if (f.fecha_desde) p.set("fecha_desde", f.fecha_desde);
  if (f.fecha_hasta) p.set("fecha_hasta", f.fecha_hasta);
  if (f.incluir_pruebas) p.set("incluir_pruebas", "true");
  if (f.limite !== undefined) p.set("limite", String(f.limite));
  if (f.desplazamiento !== undefined) p.set("desplazamiento", String(f.desplazamiento));
  const texto = p.toString();
  return texto ? `?${texto}` : "";
}

export const auditoriaApi = {
  indicadores: async (senal?: AbortSignal) =>
    limpiarIndicadores(await api<unknown>("/api/auditoria/indicadores", { signal: senal, cache: "no-store" })),
  consultas: async (filtros: FiltrosAuditoria, senal?: AbortSignal) =>
    limpiarPagina(await api<unknown>(`/api/auditoria/consultas${parametrosAuditoria(filtros)}`,
                                     { signal: senal, cache: "no-store" })),
  detalle: async (idConsulta: string, senal?: AbortSignal) =>
    limpiarDetalle(await api<unknown>(`/api/auditoria/consultas/${encodeURIComponent(idConsulta)}`,
                                      { signal: senal, cache: "no-store" })),
};
