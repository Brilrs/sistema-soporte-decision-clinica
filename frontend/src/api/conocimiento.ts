// Tipos y llamadas de la base de conocimiento (HU12, pantalla M11; retiro de guías, HU17, Sprint 3
// parte F). Contrato en docs/contrato_conocimiento.md. Solo con el permiso ADMINISTRAR_GUIAS; ninguna
// respuesta trae rutas del servidor ni datos clínicos.
import { ErrorApi, api, cabecerasCon, revisarSesion } from "./cliente";

export type EstadoDocumento = "VIGENTE" | "OBSOLETA";
export type EstadoIndexacion = "PENDIENTE" | "EN_PROCESO" | "COMPLETADA" | "ERROR";
export type EstadoTrabajo = "PENDIENTE" | "EN_CURSO" | "COMPLETADO" | "ERROR";
export type EtapaTrabajo = "EXTRACCION" | "FRAGMENTACION" | "NORMALIZACION" | "EMBEDDINGS" | "INDEXACION";

export type TrabajoResumen = {
  id_trabajo: string;
  tipo: "INDEXACION" | "REINDEXACION" | "RETIRO";
  estado: EstadoTrabajo;
  etapa: EtapaTrabajo | null;
  procesados: number;
  total: number | null;
  mensaje_error: string | null;
  fecha_solicitud: string;
  fecha_fin: string | null;
};

export type Trabajo = TrabajoResumen & {
  id_documento: string;
  titulo: string;
  fecha_inicio: string | null;
  solicitado_por: string;
};

export type Documento = {
  id_documento: string;
  titulo: string;
  codigo_documento: string | null;
  entidad_emisora: "MINSA" | "OMS" | "OTRA";
  tipo_documento: string;
  nivel: 1 | 2;
  version: string | null;
  version_indexacion: number | null;
  anio_publicacion: number;
  idioma: "es" | "en";
  estado: EstadoDocumento;
  estado_indexacion: EstadoIndexacion;
  fecha_carga: string;
  fragmentos_vigentes: number;
  citas_30_dias: number;
  // Datos del retiro (solo en una guía OBSOLETA): nombre de quien la retiró, cuándo y por qué.
  retirado_por: string | null;
  fecha_retiro: string | null;
  motivo_retiro: string | null;
  ultimo_trabajo: TrabajoResumen | null;
};

export type VersionIndexacion = { version_indexacion: number; fragmentos: number; vigentes: number; modelo_embedding: string | null };

export type DetalleDocumento = Documento & {
  fecha_publicacion: string | null;
  pagina_inicio_cuerpo: number | null;
  pagina_fin_cuerpo: number | null;
  hash_archivo: string | null;
  total_fragmentos: number;
  cargado_por: string;
  versiones: VersionIndexacion[];
  trabajos: Trabajo[];
};

export type DocumentoCreado = { documento: Documento; trabajo: Trabajo };

// Metadatos del formulario de carga, como texto (el multipart solo lleva texto).
export type MetadatosGuia = {
  titulo: string;
  codigo_documento: string;
  entidad_emisora: string;
  tipo_documento: string;
  anio_publicacion: string;
  idioma: string;
  nivel: string;
  pagina_inicio_cuerpo: string;
  pagina_fin_cuerpo: string;
};

// --- Retiro (HU17) ---------------------------------------------------------------
export type TipoReferencia =
  | "UMBRAL_HEMOGLOBINA" | "AJUSTE_ALTITUD" | "PARAMETRO_SISTEMA" | "MODIFICACION" | "MAPA_MODIFICACIONES" | "PUNTERO";
export type Referencia = { tipo: TipoReferencia; descripcion: string };
export type ReferenciasGuia = {
  id_documento: string;
  nivel: 1 | 2;
  estado: EstadoDocumento;
  codigo_confirmacion: string | null; // nivel 1: lo que hay que escribir para confirmar
  referencias: Referencia[];
  puede_retirarse: boolean;
};
export type RetiroEntrada = { motivo: string; confirmacion?: string };
export type CodigoErrorRetiro =
  | "NO_ENCONTRADA" | "YA_OBSOLETA" | "TRABAJO_ACTIVO" | "REFERENCIAS_VIGENTES" | "MOTIVO_INVALIDO"
  | "CONFIRMACION_INCORRECTA" | "MODO_EVALUACION";
export const MOTIVO_RETIRO_MIN = 10;
export const MOTIVO_RETIRO_MAX = 250;

// Error del POST de retiro con el código del backend y, en REFERENCIAS_VIGENTES, la lista que bloquea.
export class ErrorRetiro extends ErrorApi {
  constructor(estado: number, mensaje: string, public codigo: CodigoErrorRetiro | null, public referencias: Referencia[] = []) {
    super(estado, mensaje);
  }
}

async function retirar(id: string, cuerpo: RetiroEntrada): Promise<DocumentoCreado> {
  const opciones: RequestInit = { method: "POST", body: JSON.stringify(cuerpo), cache: "no-store" };
  const cabeceras = cabecerasCon(opciones);
  const respuesta = await fetch(`/api/conocimiento/documentos/${id}/retiro`, { ...opciones, headers: cabeceras });
  revisarSesion(respuesta, cabeceras);
  if (respuesta.ok) return respuesta.json() as Promise<DocumentoCreado>;
  let datos: Record<string, unknown> = {};
  try {
    datos = await respuesta.json();
  } catch {
    /* sin cuerpo JSON */
  }
  const mensaje = typeof datos.detail === "string" ? datos.detail : "No se pudo completar la operación";
  const codigo = respuesta.status === 423 ? "MODO_EVALUACION"
    : typeof datos.codigo === "string" ? (datos.codigo as CodigoErrorRetiro) : null;
  throw new ErrorRetiro(respuesta.status, mensaje, codigo, Array.isArray(datos.referencias) ? datos.referencias as Referencia[] : []);
}

export const MAX_BYTES_GUIA = 20 * 1024 * 1024;
export const ANIO_MINIMO = 1948;

export const conocimientoApi = {
  listar: () => api<Documento[]>("/api/conocimiento/documentos"),
  detalle: (id: string) => api<DetalleDocumento>(`/api/conocimiento/documentos/${id}`),
  trabajosActivos: () => api<Trabajo[]>("/api/conocimiento/trabajos?activos=true"),
  reintentar: (id: string) => api<{ trabajo: Trabajo }>(`/api/conocimiento/documentos/${id}/reintentar`, { method: "POST" }),
  referencias: (id: string, senal?: AbortSignal) =>
    api<ReferenciasGuia>(`/api/conocimiento/documentos/${id}/referencias`, { signal: senal, cache: "no-store" }),
  retirar,
  // Multipart: el navegador pone el Content-Type con el separador (cliente.ts no lo fija con FormData);
  // los campos vacíos no se envían.
  cargar(archivo: File, datos: MetadatosGuia): Promise<DocumentoCreado> {
    const cuerpo = new FormData();
    cuerpo.append("archivo", archivo);
    for (const [clave, valor] of Object.entries(datos)) if (valor.trim() !== "") cuerpo.append(clave, valor.trim());
    return api<DocumentoCreado>("/api/conocimiento/documentos", { method: "POST", body: cuerpo });
  },
};
