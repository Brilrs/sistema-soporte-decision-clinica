// Fixtures de M11 (parte F2c): respuestas reales de la API de la base de conocimiento
// (docs/contrato_conocimiento.md), tomadas del stack de desarrollo el 16/11/2026 con admin.cdss:
// la lista de las 4 guías indexadas (conocimiento/documentos.json) y el detalle de la NTS 213
// (conocimiento/detalle_nts213.json, con sus 3 trabajos más recientes). No traen datos clínicos.
// Las variantes (guía en error, obsoleta, trabajos activos) se arman a partir de ellas.
import type { DetalleDocumento, Documento, Trabajo, TrabajoResumen } from "../api/conocimiento";

const JSON_ = import.meta.glob<unknown>("./conocimiento/*.json", { import: "default", eager: true });

export const DOCUMENTOS = () => structuredClone(JSON_["./conocimiento/documentos.json"]) as Documento[];
export const DETALLE_NTS213 = () => structuredClone(JSON_["./conocimiento/detalle_nts213.json"]) as DetalleDocumento;

export const ADMIN = {
  id_usuario: "u-admin",
  nombre_usuario: "admin.prueba",
  nombre_completo: "Administración de prueba",
  rol: "Administrador",
  permisos: ["ADMINISTRAR_USUARIOS", "ADMINISTRAR_GUIAS", "VER_PARAMETROS", "VER_AUDITORIA"],
};

export const ID_NUEVA = "20000000-0000-4000-8000-000000000001";
export const TITULO_NUEVA = "Revisión sistemática de suplementación con hierro en lactantes";

export function trabajoResumen(cambios: Partial<TrabajoResumen> = {}): TrabajoResumen {
  return { id_trabajo: "t-0001", tipo: "INDEXACION", estado: "PENDIENTE", etapa: null, procesados: 0, total: null,
           mensaje_error: null, fecha_solicitud: "2026-11-16T15:00:00Z", fecha_fin: null, ...cambios };
}

export function trabajo(cambios: Partial<Trabajo> = {}): Trabajo {
  return { ...trabajoResumen(), id_documento: ID_NUEVA, titulo: TITULO_NUEVA, fecha_inicio: null,
           solicitado_por: "Administración de prueba", ...cambios };
}

// Guía de nivel 2 recién cargada desde M11, en el estado de indexación que se indique.
export function guiaNueva(cambios: Partial<Documento> = {}): Documento {
  return {
    id_documento: ID_NUEVA, titulo: TITULO_NUEVA, codigo_documento: null, entidad_emisora: "OTRA", tipo_documento: "LITERATURA",
    nivel: 2, version: null, version_indexacion: null, anio_publicacion: 2025, idioma: "en", estado: "VIGENTE",
    estado_indexacion: "PENDIENTE", fecha_carga: "2026-11-16T15:00:00Z", fragmentos_vigentes: 0, citas_30_dias: 0,
    retirado_por: null, fecha_retiro: null, motivo_retiro: null, ultimo_trabajo: trabajoResumen(), ...cambios,
  };
}

export const MENSAJE_ERROR_INDEXADOR = "ErrorIndexacion: el PDF no tiene capa de texto";
export const guiaEnError = () => guiaNueva({
  estado_indexacion: "ERROR",
  ultimo_trabajo: trabajoResumen({ estado: "ERROR", etapa: "EXTRACCION", mensaje_error: MENSAJE_ERROR_INDEXADOR,
                                   fecha_fin: "2026-11-16T15:01:00Z" }),
});
