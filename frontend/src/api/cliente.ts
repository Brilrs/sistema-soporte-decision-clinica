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

// Texto para mostrar al usuario a partir de cualquier error de una llamada.
export function mensajeError(err: unknown): string {
  return err instanceof ErrorApi ? err.message : "No se pudo conectar con el servidor";
}

// Cabeceras comunes: JSON si hay cuerpo y el token de la sesión si existe.
export function cabecerasCon(opciones: RequestInit = {}): Headers {
  const token = leerToken();
  const cabeceras = new Headers(opciones.headers);
  if (opciones.body && !cabeceras.has("Content-Type")) cabeceras.set("Content-Type", "application/json");
  if (token) cabeceras.set("Authorization", `Bearer ${token}`);
  return cabeceras;
}

// Sesión vencida o no válida: cualquier llamada que envió el token y recibió 401 lo borra y
// avisa a los suscriptores (AuthContext cierra la sesión en pantalla). Un 401 sin token, como
// el de usuario o contraseña incorrectos en el login, no avisa.
type Oyente = () => void;
const oyentesSesion = new Set<Oyente>();

export function alExpirarSesion(oyente: Oyente): () => void {
  oyentesSesion.add(oyente);
  return () => {
    oyentesSesion.delete(oyente);
  };
}

export function revisarSesion(respuesta: Response, cabeceras: Headers): void {
  if (respuesta.status !== 401 || !cabeceras.has("Authorization")) return;
  guardarToken(null);
  oyentesSesion.forEach((o) => o());
}

// ErrorApi con el «detail» del backend (texto en español) o un mensaje genérico.
export async function errorDeRespuesta(respuesta: Response): Promise<ErrorApi> {
  let mensaje = "No se pudo completar la operación";
  try {
    const datos = await respuesta.json();
    if (typeof datos.detail === "string") mensaje = datos.detail;
  } catch {
    /* respuesta sin cuerpo JSON */
  }
  return new ErrorApi(respuesta.status, mensaje);
}

export async function api<T>(ruta: string, opciones: RequestInit = {}): Promise<T> {
  const cabeceras = cabecerasCon(opciones);
  const respuesta = await fetch(ruta, { ...opciones, headers: cabeceras });
  revisarSesion(respuesta, cabeceras);
  if (!respuesta.ok) throw await errorDeRespuesta(respuesta);
  return respuesta.json() as Promise<T>;
}
