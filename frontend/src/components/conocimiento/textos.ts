// Textos de M11 y reglas del formulario de carga: etiquetas de estado, validación en el cliente
// (lo evidente; el backend vuelve a validar todo) y ubicación de los errores de la API junto al
// campo que corresponde (docs/contrato_conocimiento.md).
import { ErrorApi } from "../../api/cliente";
import { ANIO_MINIMO, MAX_BYTES_GUIA, type EstadoIndexacion, type EtapaTrabajo, type MetadatosGuia } from "../../api/conocimiento";

export const AVISO_P14 = "Indexar una guía puede demorar las consultas varios minutos. Cargue guías fuera del horario de atención.";
export const NOTA_NIVEL_1 = "Las guías de nivel 1 se cargan por línea de comandos con transcripciones verificadas por el equipo.";
export const NOTA_RETIRAR =
  "«Retirar» solo se aplica a guías vigentes. Una guía retirada queda como obsoleta y no se puede reactivar desde la pantalla.";
export const NOTA_RETIRAR_SIN_PERMISO = "Su rol no tiene permiso para retirar guías.";

// --- Ventana de retiro (HU17) ---------------------------------------------------------
export const TEXTO_RETIRO =
  "La guía dejará de citarse en nuevas consultas. Las consultas anteriores conservan sus citas. Este cambio no se puede deshacer desde la pantalla.";
export const TEXTO_BLOQUEO_REFERENCIAS =
  "No se puede retirar: es una guía de nivel 1 y estos elementos vigentes la usan. Cambie o retire primero esas referencias; mientras existan, «Retirar» queda deshabilitado.";
export const TIPOS_REFERENCIA: Record<string, string> = {
  UMBRAL_HEMOGLOBINA: "Puntos de corte",
  AJUSTE_ALTITUD: "Ajuste por altitud",
  PARAMETRO_SISTEMA: "Parámetro del sistema",
  MODIFICACION: "Modificación de otra guía",
  MAPA_MODIFICACIONES: "Mapa de modificaciones",
  PUNTERO: "Regla de punteros",
};

// «Reintentar» de una guía: una indexación que terminó en error o, en una guía retirada, el retiro
// que terminó en error (el backend crea otro trabajo RETIRO; una obsoleta no se vuelve a indexar).
export function puedeReintentar(d: { estado: string; estado_indexacion: string; ultimo_trabajo: { tipo: string; estado: string } | null }): boolean {
  if (d.estado === "OBSOLETA") return d.ultimo_trabajo?.tipo === "RETIRO" && d.ultimo_trabajo.estado === "ERROR";
  return d.estado_indexacion === "ERROR";
}
export const NOTA_OBSOLETAS =
  "Las guías marcadas como obsoletas dejan de citarse en nuevas consultas, pero se conservan para la trazabilidad de evaluaciones anteriores.";

export const NIVELES: Record<number, { texto: string; clase: string }> = {
  1: { texto: "N1 · citable", clase: "etiqueta--nivel-1" },
  2: { texto: "N2 · metodológico", clase: "etiqueta--nivel-2" },
};

export const ESTADOS_DOCUMENTO: Record<string, { texto: string; clase: string }> = {
  VIGENTE: { texto: "Vigente", clase: "etiqueta--vigente" },
  OBSOLETA: { texto: "Obsoleta", clase: "etiqueta--obsoleta" },
};

export const ESTADOS_INDEXACION: Record<EstadoIndexacion, { texto: string; clase: string }> = {
  COMPLETADA: { texto: "Indexada", clase: "etiqueta--indexacion-COMPLETADA" },
  PENDIENTE: { texto: "En cola", clase: "etiqueta--indexacion-PENDIENTE" },
  EN_PROCESO: { texto: "Indexando", clase: "etiqueta--indexacion-EN_PROCESO" },
  ERROR: { texto: "Error al indexar", clase: "etiqueta--indexacion-ERROR" },
};

export const ESTADOS_TRABAJO: Record<string, string> = {
  PENDIENTE: "En cola", EN_CURSO: "En curso", COMPLETADO: "Completado", ERROR: "Error",
};
export const TIPOS_TRABAJO: Record<string, string> = {
  INDEXACION: "Indexación", REINDEXACION: "Reindexación", RETIRO: "Retiro",
};

export const ETAPAS: { codigo: EtapaTrabajo; texto: string }[] = [
  { codigo: "EXTRACCION", texto: "Extracción" },
  { codigo: "FRAGMENTACION", texto: "Fragmentación" },
  { codigo: "NORMALIZACION", texto: "Normalización" },
  { codigo: "EMBEDDINGS", texto: "Embeddings" },
  { codigo: "INDEXACION", texto: "Indexación" },
];
export const textoEtapa = (codigo: string | null) => ETAPAS.find((e) => e.codigo === codigo)?.texto ?? null;

export const ENTIDADES = [
  { valor: "MINSA", texto: "MINSA" },
  { valor: "OMS", texto: "OMS" },
  { valor: "OTRA", texto: "Otra" },
];
export const TIPOS_DOCUMENTO = [
  { valor: "NORMA_TECNICA", texto: "Norma técnica" },
  { valor: "GUIA", texto: "Guía" },
  { valor: "DIRECTIVA", texto: "Directiva" },
  { valor: "RESOLUCION", texto: "Resolución" },
  { valor: "LITERATURA", texto: "Literatura" },
];
export const IDIOMAS = [
  { valor: "es", texto: "Español" },
  { valor: "en", texto: "Inglés" },
];
export const textoDe = (lista: { valor: string; texto: string }[], valor: string) =>
  lista.find((x) => x.valor === valor)?.texto ?? valor;

// Campos del formulario que pueden mostrar un error: los metadatos, el archivo y las páginas
// (inicio y fin juntos cuando el error es de la pareja).
export type CampoGuia = keyof MetadatosGuia | "archivo" | "paginas";
export type ErroresGuia = Partial<Record<CampoGuia, string>> & { general?: string };

const entero = (v: string) => (/^\d+$/.test(v.trim()) ? Number(v.trim()) : null);

export function validarGuia(archivo: File | null, d: MetadatosGuia, anioActual = new Date().getFullYear()): ErroresGuia {
  const e: ErroresGuia = {};
  if (!archivo) e.archivo = "Elija el archivo PDF de la guía.";
  else if (!archivo.name.toLowerCase().endsWith(".pdf")) e.archivo = "El archivo debe tener la extensión .pdf.";
  else if (archivo.size > MAX_BYTES_GUIA) e.archivo = "El archivo supera el máximo de 20 MB.";
  else if (archivo.size === 0) e.archivo = "El archivo está vacío.";
  const titulo = d.titulo.trim();
  if (titulo.length < 3) e.titulo = "Escriba el título de la guía (al menos 3 caracteres).";
  else if (titulo.length > 255) e.titulo = "El título admite hasta 255 caracteres.";
  if (d.codigo_documento.trim().length > 80) e.codigo_documento = "El código admite hasta 80 caracteres.";
  if (!d.entidad_emisora) e.entidad_emisora = "Elija la entidad emisora.";
  if (!d.tipo_documento) e.tipo_documento = "Elija el tipo de documento.";
  const anio = entero(d.anio_publicacion);
  if (anio === null) e.anio_publicacion = "Escriba el año de publicación con cuatro cifras.";
  else if (anio < ANIO_MINIMO || anio > anioActual) e.anio_publicacion = `El año debe estar entre ${ANIO_MINIMO} y ${anioActual}.`;
  if (!d.idioma) e.idioma = "Elija el idioma.";
  if (d.nivel !== "2") e.nivel = NOTA_NIVEL_1;
  const [ini, fin] = [d.pagina_inicio_cuerpo.trim(), d.pagina_fin_cuerpo.trim()];
  if (ini || fin) {
    const [a, b] = [entero(ini), entero(fin)];
    if (!ini || !fin) e.paginas = "Indique la página de inicio y la de fin del cuerpo, o deje las dos vacías.";
    else if (a === null || b === null || a < 1 || b < 1) e.paginas = "Las páginas deben ser números enteros desde 1.";
    else if (a > b) e.paginas = "La página de inicio no puede ser mayor que la de fin.";
  }
  return e;
}

// Campos del 422 de metadatos («Metadatos no válidos. campo: mensaje; campo: mensaje») y a qué
// control del formulario corresponden. El error de la pareja de páginas llega como «datos».
const CAMPO_DEL_SERVIDOR: Record<string, CampoGuia> = {
  titulo: "titulo", codigo_documento: "codigo_documento", entidad_emisora: "entidad_emisora",
  tipo_documento: "tipo_documento", anio_publicacion: "anio_publicacion", idioma: "idioma", nivel: "nivel",
  pagina_inicio_cuerpo: "paginas", pagina_fin_cuerpo: "paginas", datos: "paginas",
};
// Los mensajes propios del backend están en español; los de Pydantic (Input should..., String
// should...) llegan en inglés y se reemplazan por un texto en español.
const EN_INGLES = /^(Input|String|Value|Field|Extra|List|Dictionary|Object)\b/;
const GENERICO_CAMPO = "El servidor no aceptó este valor. Revíselo.";

export function erroresDeLaApi(err: unknown): ErroresGuia {
  if (!(err instanceof ErrorApi)) return { general: "No se pudo conectar con el servidor. Intente de nuevo." };
  const texto = err.message;
  switch (err.estado) {
    case 413:
      return { archivo: "El archivo supera el máximo de 20 MB." };
    case 415:
      return { archivo: texto };
    case 409:
      // Duplicado («Este archivo ya está cargado como «Título»») o cupo de trabajos lleno.
      return /ya está cargado/.test(texto) ? { archivo: texto } : { general: texto };
    case 422: {
      if (/^Falta el archivo/.test(texto)) return { archivo: "Elija el archivo PDF de la guía." };
      if (!texto.startsWith("Metadatos no válidos")) return /nivel/i.test(texto) ? { nivel: texto } : { general: texto };
      const errores: ErroresGuia = {};
      for (const parte of texto.replace(/^Metadatos no válidos\.\s*/, "").split(";")) {
        const i = parte.indexOf(":");
        if (i < 0) continue;
        const campo = CAMPO_DEL_SERVIDOR[parte.slice(0, i).trim()];
        const mensaje = parte.slice(i + 1).trim();
        const visible = EN_INGLES.test(mensaje) || !mensaje ? GENERICO_CAMPO : mensaje.charAt(0).toUpperCase() + mensaje.slice(1) + ".";
        if (campo) errores[campo] ??= visible;
        else errores.general ??= "El servidor rechazó los datos del formulario. Revíselos e intente de nuevo.";
      }
      return Object.keys(errores).length ? errores : { general: texto };
    }
    default:
      return { general: texto };
  }
}

// Orden de los campos en el formulario, para llevar el foco al primero con error.
export const ORDEN_CAMPOS: CampoGuia[] = [
  "archivo", "nivel", "titulo", "codigo_documento", "entidad_emisora", "tipo_documento", "anio_publicacion", "idioma", "paginas",
];
