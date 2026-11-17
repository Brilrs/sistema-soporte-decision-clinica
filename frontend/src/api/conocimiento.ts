// Tipos y llamadas de la base de conocimiento (HU12, pantalla M11). Contrato en
// docs/contrato_conocimiento.md (parte F2b). Solo con el permiso ADMINISTRAR_GUIAS; ninguna
// respuesta trae rutas del servidor ni datos clínicos.
import { api } from "./cliente";

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

export const MAX_BYTES_GUIA = 20 * 1024 * 1024;
export const ANIO_MINIMO = 1948;

export const conocimientoApi = {
  listar: () => api<Documento[]>("/api/conocimiento/documentos"),
  detalle: (id: string) => api<DetalleDocumento>(`/api/conocimiento/documentos/${id}`),
  trabajosActivos: () => api<Trabajo[]>("/api/conocimiento/trabajos?activos=true"),
  reintentar: (id: string) => api<{ trabajo: Trabajo }>(`/api/conocimiento/documentos/${id}/reintentar`, { method: "POST" }),
  // Multipart: el navegador pone el Content-Type con el separador (cliente.ts no lo fija con FormData);
  // los campos vacíos no se envían.
  cargar(archivo: File, datos: MetadatosGuia): Promise<DocumentoCreado> {
    const cuerpo = new FormData();
    cuerpo.append("archivo", archivo);
    for (const [clave, valor] of Object.entries(datos)) if (valor.trim() !== "") cuerpo.append(clave, valor.trim());
    return api<DocumentoCreado>("/api/conocimiento/documentos", { method: "POST", body: cuerpo });
  },
};
