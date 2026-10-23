// Cliente HTTP del backend. El token se guarda solo en sessionStorage:
// se pierde al cerrar la pestaña, lo que reduce el riesgo en equipos compartidos.
const CLAVE_TOKEN = "cdss.token";

export function leerToken(): string | null {
  try {
    return sessionStorage.getItem(CLAVE_TOKEN);
  } catch {
    return null;
  }
}

export function guardarToken(token: string | null): void {
  try {
    if (token) sessionStorage.setItem(CLAVE_TOKEN, token);
    else sessionStorage.removeItem(CLAVE_TOKEN);
  } catch {
    /* almacenamiento no disponible: la sesión dura lo que la pestaña */
  }
}

export class ErrorApi extends Error {
  constructor(public estado: number, mensaje: string) {
    super(mensaje);
  }
}

export async function api<T>(ruta: string, opciones: RequestInit = {}): Promise<T> {
  const token = leerToken();
  const cabeceras = new Headers(opciones.headers);
  if (opciones.body && !cabeceras.has("Content-Type")) cabeceras.set("Content-Type", "application/json");
  if (token) cabeceras.set("Authorization", `Bearer ${token}`);

  const respuesta = await fetch(ruta, { ...opciones, headers: cabeceras });
  if (!respuesta.ok) {
    let mensaje = "No se pudo completar la operación";
    try {
      const datos = await respuesta.json();
      if (typeof datos.detail === "string") mensaje = datos.detail;
    } catch {
      /* respuesta sin cuerpo JSON */
    }
    throw new ErrorApi(respuesta.status, mensaje);
  }
  return respuesta.json() as Promise<T>;
}
