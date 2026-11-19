// Tipos del contrato de parámetros (M12, HU14; Sprint 3, parte E1a). La pantalla es la parte E2 y la
// edición (PUT por grupo) la parte E1b. Fuente: docs/contrato_parametros.md y los fixtures de
// src/__fixtures__ (parametros*.json), que genera el backend (tests/test_e1a_parametros.py).

export type DocumentoNorma = { id_documento: string; codigo: string | null; titulo: string };

// Campos comunes de cada versión de un parámetro.
export type DatosVersion = {
  documento: DocumentoNorma | null;
  referencia: string | null; // tabla y página de la norma
  motivo_cambio: string | null; // null en la carga inicial
  verificado: boolean; // false: pendiente de verificación contra la norma
  vigente_desde: string;
  modificado_por: string; // nombre del usuario que registró la versión
};

export type CategoriaAnemia = "SIN_ANEMIA" | "ANEMIA_LEVE" | "ANEMIA_MODERADA" | "ANEMIA_SEVERA";
export type NivelRiesgo = "BAJO" | "MODERADO" | "ALTO" | "MUY_ALTO";

export type PuntoCorte = DatosVersion & {
  id_umbral: number;
  categoria: CategoriaAnemia;
  nivel_riesgo: NivelRiesgo;
  hb_min_g_dl: number | null; // null en la categoría más severa
  hb_max_g_dl: number | null; // null en «sin anemia»
};

// Tramos fijos: 6 a 23 y 24 a 59 meses.
export type TramoEdad = { edad_min_meses: number; edad_max_meses: number; categorias: PuntoCorte[] };

// version: SHA-256 de los ids vigentes del grupo; la edición (E1b) la envía para el control optimista.
export type GrupoPuntosCorte = { version: string; tramos: TramoEdad[] };

export type RangoAltitud = DatosVersion & {
  id_ajuste: number;
  altitud_min_msnm: number;
  altitud_max_msnm: number;
  ajuste_g_dl: number;
};

export type GrupoAjusteAltitud = { version: string; rangos: RangoAltitud[] };

export type ParametroSistema = DatosVersion & {
  id_parametro: number;
  clave: string;
  valor: string;
  tipo_dato: "ENTERO" | "DECIMAL" | "TEXTO";
  valor_minimo: number | null;
  valor_maximo: number | null;
  descripcion: string;
};

export type GrupoVigencia = ParametroSistema & { version: string };

export type RiesgoCategoria = { nombre: CategoriaAnemia; nivel_riesgo: NivelRiesgo; requiere_derivacion: boolean; orden: number };

// GET /api/parametros
export type Parametros = {
  puede_editar: boolean; // CONFIGURAR_PARAMETROS (solo el Coordinador CRED)
  modo_evaluacion: boolean; // CDSS_MODO_EVALUACION: la edición responde 423
  puntos_corte: GrupoPuntosCorte;
  ajuste_altitud: GrupoAjusteAltitud;
  vigencia_tamizaje: GrupoVigencia;
  // Solo lectura (decisión 4): se cambian por migración con medición.
  riesgo: RiesgoCategoria[];
  recuperacion: ParametroSistema[];
  modelo: ParametroSistema[];
  indexacion: ParametroSistema[];
};

export type GrupoHistorial = "puntos_corte" | "ajuste_altitud" | "vigencia_tamizaje" | "recuperacion" | "modelo" | "indexacion";

export type VersionHistorial = DatosVersion & {
  grupo: GrupoHistorial;
  tabla: "umbral_hemoglobina" | "ajuste_altitud" | "parametro_sistema";
  id: number;
  elemento: string; // «6 a 23 meses · ANEMIA_LEVE», «0 a 499 m.s.n.m.» o la clave
  valores: Record<string, number | string | null>;
  vigente_hasta: string | null;
  vigente: boolean;
};

// GET /api/parametros/historial
export type PaginaHistorial = {
  total: number;
  limite: number;
  desplazamiento: number;
  grupo: GrupoHistorial | null;
  versiones: VersionHistorial[];
};

// ---------------------------------------------------------------------------
// Edición (parte E1b): PUT por grupo con la tabla completa, solo CONFIGURAR_PARAMETROS
// ---------------------------------------------------------------------------
export const CONFIRMACION_ESCRITA = "CONFIRMO";

// Lo común a los tres PUT. Las filas se reenvían tal como llegaron del GET (el backend ignora los
// campos de más, como id, documento o motivo).
export type EdicionComun = {
  version: string; // la del GET; si cambió, 409
  motivo_cambio: string; // de 10 a 500 caracteres
  referencia?: string | null; // norma, tabla y página; obligatoria si algún valor queda verificado
  id_documento?: string | null; // la norma; sin ella se conserva la de cada versión anterior
  confirmacion_escrita?: string | null; // CONFIRMACION_ESCRITA cuando hay advertencias
};

export type CategoriaEntrada = Pick<PuntoCorte, "categoria" | "hb_min_g_dl" | "hb_max_g_dl" | "verificado">;
export type TramoEntrada = { edad_min_meses: number; edad_max_meses: number; categorias: CategoriaEntrada[] };
export type RangoEntrada = Pick<RangoAltitud, "altitud_min_msnm" | "altitud_max_msnm" | "ajuste_g_dl" | "verificado">;

// PUT /api/parametros/puntos-corte
export type PuntosCorteEntrada = EdicionComun & { tramos: TramoEntrada[] };
// PUT /api/parametros/ajuste-altitud (de menor a mayor altitud, desde 0)
export type AjusteAltitudEntrada = EdicionComun & { rangos: RangoEntrada[] };
// PUT /api/parametros/vigencia-tamizaje
export type VigenciaEntrada = EdicionComun & { valor: number | string; verificado?: boolean };

export type CambioParametro = {
  elemento: string;
  antes: Record<string, number | string | boolean | null> | null; // null: rango nuevo
  despues: Record<string, number | string | boolean | null> | null; // null: rango que se quitó
};

export type ResumenEdicion = {
  grupo: "puntos_corte" | "ajuste_altitud" | "vigencia_tamizaje";
  cerrados: number[];
  creados: number[];
  cambios: CambioParametro[];
  advertencias_confirmadas: string[];
};

// Respuesta 200: el grupo como en el GET (con la versión nueva) y el resumen.
export type EdicionPuntosCorte = { grupo: GrupoPuntosCorte; resumen: ResumenEdicion };
export type EdicionAjusteAltitud = { grupo: GrupoAjusteAltitud; resumen: ResumenEdicion };
export type EdicionVigencia = { grupo: GrupoVigencia; resumen: ResumenEdicion };

export type CampoMensaje = { campo: string; mensaje: string };

// Errores de los PUT (además de 401 y 403, con solo detail).
export type ErrorEdicionCuerpo =
  | { codigo: "VALIDACION"; detail: string; errores: CampoMensaje[] } // 422
  | { codigo: "REQUIERE_CONFIRMACION"; detail: string; advertencias: CampoMensaje[] } // 422
  | { codigo: "SIN_CAMBIOS"; detail: string } // 422
  | { codigo: "VERSION_DESACTUALIZADA"; detail: string; version_actual: string } // 409
  | { codigo: "MODO_EVALUACION"; detail: string }; // 423 (el backend solo envía detail)

// GET /api/parametros/huella
export type HuellaConfiguracion = {
  huella: string; // SHA-256
  algoritmo: "SHA-256";
  calculada_en: string;
  version_prompt: string | null;
  componentes: { nombre: string; huella: string; elementos: number }[];
  indexacion: { id_documento: string; codigo: string | null; version_indexacion: number }[];
};
