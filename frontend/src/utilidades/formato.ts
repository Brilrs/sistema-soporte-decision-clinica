// Formato de fechas, números y textos de dominio para la interfaz (es-PE).

// Celda o valor sin dato (guion corto: el proyecto no usa rayas en los textos).
export const VACIO = "-";

// Fechas sin hora (AAAA-MM-DD) se tratan como texto para que la zona horaria no las mueva un día.
export function fecha(iso: string | null | undefined): string {
  if (!iso) return VACIO;
  const [a, m, d] = iso.slice(0, 10).split("-");
  return `${d}/${m}/${a}`;
}

// «Hoy 10:42», «Ayer 16:20» o «28/07/2026», como en la tabla de M02.
export function fechaRelativa(isoFecha: string, isoRegistro?: string | null): string {
  const hoyLocal = hoyIso();
  const ayer = new Date();
  ayer.setDate(ayer.getDate() - 1);
  const hora = isoRegistro
    ? new Date(isoRegistro).toLocaleTimeString("es-PE", { hour: "2-digit", minute: "2-digit", hour12: false })
    : "";
  if (isoFecha === hoyLocal) return hora ? `Hoy ${hora}` : "Hoy";
  if (isoFecha === aIso(ayer)) return hora ? `Ayer ${hora}` : "Ayer";
  return fecha(isoFecha);
}

export function fechaHora(iso: string): string {
  const f = new Date(iso);
  return `${fecha(aIso(f))} ${f.toLocaleTimeString("es-PE", { hour: "2-digit", minute: "2-digit", hour12: false })}`;
}

function aIso(f: Date): string {
  const m = String(f.getMonth() + 1).padStart(2, "0");
  const d = String(f.getDate()).padStart(2, "0");
  return `${f.getFullYear()}-${m}-${d}`;
}

export function hoyIso(): string {
  return aIso(new Date());
}

// Mismo criterio que el backend: el mes se cumple el mismo día del mes siguiente.
// Solo se usa para mostrar la edad mientras se llena el formulario; el valor oficial lo calcula el servidor.
export function edadEnMeses(nacimiento: string, referencia: string): number | null {
  if (!nacimiento || !referencia) return null;
  const [an, mn, dn] = nacimiento.split("-").map(Number);
  const [ar, mr, dr] = referencia.split("-").map(Number);
  let meses = (ar - an) * 12 + (mr - mn);
  if (dr < dn) meses -= 1;
  return meses < 0 ? null : meses;
}

export function edad(meses: number | null | undefined): string {
  if (meses === null || meses === undefined) return VACIO;
  return `${meses} ${meses === 1 ? "mes" : "meses"}`;
}

// Decimales con coma, como se escriben en Perú.
export function decimal(valor: string | number | null | undefined, decimales = 1): string {
  if (valor === null || valor === undefined || valor === "") return VACIO;
  return Number(valor).toLocaleString("es-PE", { minimumFractionDigits: decimales, maximumFractionDigits: decimales });
}

// Convierte lo escrito por el usuario ("9,8" o "9.8") en número; vacío o no numérico da null.
export function leerDecimal(texto: string): number | null {
  const limpio = texto.trim().replace(",", ".");
  if (limpio === "") return null;
  const n = Number(limpio);
  return Number.isFinite(n) ? n : null;
}

export const SEXOS: Record<string, string> = { M: "Masculino", F: "Femenino" };

export const EDADES_GESTACIONALES: Record<string, string> = {
  A_TERMINO: "A término",
  PRETERMINO: "Pretérmino",
  NO_REGISTRADO: "No registrado",
};

export const METODOS: Record<string, string> = { HEMOGLOBINOMETRO: "Hemoglobinómetro", LABORATORIO: "Laboratorio" };

export const CATEGORIAS: Record<string, string> = {
  SIN_ANEMIA: "Sin anemia",
  ANEMIA_LEVE: "Anemia leve",
  ANEMIA_MODERADA: "Anemia moderada",
  ANEMIA_SEVERA: "Anemia severa",
};

export function siNo(valor: boolean | null | undefined): string {
  return valor === null || valor === undefined ? "No registrado" : valor ? "Sí" : "No";
}

export function iniciales(nombre: string): string {
  return nombre.split(/\s+/).filter(Boolean).slice(0, 2).map((p) => p[0]).join("").toUpperCase();
}
