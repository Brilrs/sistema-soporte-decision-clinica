// Tipos y llamadas a los endpoints de pacientes y tamizajes (backend, parte A del Sprint 1).
// Los valores decimales llegan como texto ("9.8") para no perder precisión.
import { api } from "./cliente";

export type Decimal = string;
export type Sexo = "M" | "F";
export type EdadGestacional = "A_TERMINO" | "PRETERMINO" | "NO_REGISTRADO";
export type MetodoMedicion = "HEMOGLOBINOMETRO" | "LABORATORIO";

export type Distrito = { ubigeo: string; nombre: string; provincia: string; departamento: string; altitud_msnm: number };
export type Sintoma = { id_sintoma: number; nombre: string };

export type Clasificacion = {
  categoria: string;
  nivel_riesgo: string;
  requiere_derivacion: boolean;
  altitud_msnm: number;
  ajuste_hb_g_dl: Decimal;
  hb_ajustada_g_dl: Decimal;
};

export type Evaluacion = {
  edad_meses: number;
  clasificacion: Clasificacion | null;
  motivo_sin_clasificacion: string | null;
};

export type UltimoTamizaje = {
  fecha_tamizaje: string;
  fecha_registro: string;
  hemoglobina_g_dl: Decimal | null;
  hb_ajustada_g_dl: Decimal | null;
  categoria: string | null;
  nivel_riesgo: string | null;
  vigente: boolean;
};

export type PacienteListado = {
  id_paciente: string;
  nombres_apellidos: string;
  numero_hc: string;
  sexo: Sexo;
  edad_meses_actual: number;
  ultimo_tamizaje: UltimoTamizaje | null;
};

export type Indicadores = {
  evaluaciones_hoy: number | null;
  con_anemia_detectada: number;
  controles_pendientes: number;
  tiempo_medio_respuesta_s: number | null;
  dias_vigencia_tamizaje: number;
};

export type Ficha = {
  id_paciente: string;
  nombres_apellidos: string;
  dni: string;
  numero_hc: string;
  direccion: string | null;
  fecha_nacimiento: string;
  edad_meses_actual: number;
  sexo: Sexo;
  ubigeo_residencia: string;
  distrito: string;
  provincia: string;
  departamento: string;
  altitud_msnm: number;
  edad_gestacional_nacer: EdadGestacional;
  bajo_peso_nacer: boolean | null;
  registrado_por: string;
  fecha_registro: string;
};

export type SintomaRegistrado = { id_sintoma: number; nombre: string; detalle: string | null };

export type TamizajeHistorial = {
  id_tamizaje: string;
  fecha_tamizaje: string;
  fecha_registro: string;
  edad_meses: number;
  hemoglobina_g_dl: Decimal | null;
  metodo_medicion: MetodoMedicion | null;
  peso_kg: Decimal | null;
  talla_cm: Decimal | null;
  recibe_suplementacion_hierro: boolean | null;
  lactancia_materna_actual: boolean | null;
  parasitosis_reciente: boolean | null;
  observaciones: string | null;
  profesional: string;
  sintomas: SintomaRegistrado[];
  vigente: boolean;
  clasificacion: Clasificacion | null;
  motivo_sin_clasificacion: string | null;
};

export type Franja = {
  edad_min_meses: number;
  edad_max_meses: number;
  categoria: string;
  nivel_riesgo: string;
  hb_min_g_dl: Decimal | null;
  hb_max_g_dl: Decimal | null;
};

export type Historial = { id_paciente: string; tamizajes: TamizajeHistorial[]; franjas: Franja[] };

export type TamizajeEntrada = {
  fecha_tamizaje: string;
  hemoglobina_g_dl: number | null;
  metodo_medicion: MetodoMedicion | null;
  peso_kg: number | null;
  talla_cm: number | null;
  recibe_suplementacion_hierro: boolean;
  lactancia_materna_actual: boolean;
  parasitosis_reciente: boolean;
  observaciones: string | null;
  sintomas: { id_sintoma: number; detalle?: string | null }[];
};

export type PacienteEntrada = {
  nombres_apellidos: string;
  dni: string;
  numero_hc: string;
  direccion: string | null;
  ubigeo_residencia: string;
  fecha_nacimiento: string;
  sexo: Sexo;
  edad_gestacional_nacer: EdadGestacional;
  bajo_peso_nacer: boolean;
};

export type TamizajeRegistrado = Evaluacion & { id_tamizaje: string };
export type VistaPrevia = Evaluacion & { anterior: TamizajeHistorial | null };

const json = (cuerpo: unknown) => ({ body: JSON.stringify(cuerpo) });

export const pacientesApi = {
  distritos: () => api<Distrito[]>("/api/catalogos/distritos"),
  sintomas: () => api<Sintoma[]>("/api/catalogos/sintomas"),
  indicadores: () => api<Indicadores>("/api/pacientes/indicadores"),
  recientes: () => api<PacienteListado[]>("/api/pacientes"),
  // El texto va en el cuerpo (POST) para que el DNI o el nombre no queden en la URL ni en los registros de acceso.
  buscar: (texto: string) => api<PacienteListado[]>("/api/pacientes/buscar", { method: "POST", ...json({ texto }) }),
  ficha: (id: string) => api<Ficha>(`/api/pacientes/${id}`),
  historial: (id: string) => api<Historial>(`/api/pacientes/${id}/historial`),
  registrar: (datos: PacienteEntrada & { tamizaje: TamizajeEntrada | null }) =>
    api<{ id_paciente: string; tamizaje: TamizajeRegistrado | null }>("/api/pacientes", { method: "POST", ...json(datos) }),
  actualizar: (id: string, cambios: Partial<PacienteEntrada>) =>
    api<Ficha>(`/api/pacientes/${id}`, { method: "PATCH", ...json(cambios) }),
  nuevoTamizaje: (id: string, datos: TamizajeEntrada) =>
    api<TamizajeRegistrado>(`/api/pacientes/${id}/tamizajes`, { method: "POST", ...json(datos) }),
  vistaPrevia: (id: string, datos: TamizajeEntrada, senal?: AbortSignal) =>
    api<VistaPrevia>(`/api/pacientes/${id}/tamizajes/vista-previa`, { method: "POST", signal: senal, ...json(datos) }),
};
