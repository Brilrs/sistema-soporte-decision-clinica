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

// Códigos que el backend también envía en la cabecera X-Codigo-Error.
export const SESION_REVOCADA = "SESION_REVOCADA";
export const CAMBIO_CONTRASENA_OBLIGATORIO = "CAMBIO_CONTRASENA_OBLIGATORIO";
export const CABECERA_CODIGO = "X-Codigo-Error";

// Texto para mostrar al usuario a partir de cualquier error de una llamada.
export function mensajeError(err: unknown): string {
  return err instanceof ErrorApi ? err.message : "No se pudo conectar con el servidor";
}

// Cabeceras comunes: JSON si hay cuerpo y el token de la sesión si existe. Con FormData (subida de
// guías, M11) no se pone Content-Type: lo arma el navegador con el separador del multipart.
export function cabecerasCon(opciones: RequestInit = {}): Headers {
  const token = leerToken();
  const cabeceras = new Headers(opciones.headers);
  if (opciones.body && !(opciones.body instanceof FormData) && !cabeceras.has("Content-Type")) {
    cabeceras.set("Content-Type", "application/json");
  }
  if (token) cabeceras.set("Authorization", `Bearer ${token}`);
  return cabeceras;
}

// Sesión vencida o no válida: cualquier llamada que envió el token y recibió 401 lo borra y
// avisa a los suscriptores (AuthContext cierra la sesión en pantalla). Un 401 sin token, como
// el de usuario o contraseña incorrectos en el login, no avisa. El motivo «revocada» es un token
// de una versión de sesión anterior (contraseña cambiada o restablecida, cuenta reactivada).
export type MotivoCierre = "expirada" | "revocada";
type Oyente = (motivo: MotivoCierre) => void;
const oyentesSesion = new Set<Oyente>();
// 403 CAMBIO_CONTRASENA_OBLIGATORIO: la cuenta tiene la marca (por ejemplo, la restableció el
// administrador sin cerrar esta sesión); AuthContext lleva a «Cambiar mi contraseña».
const oyentesCambio = new Set<() => void>();

function suscribir<T>(conjunto: Set<T>, oyente: T): () => void {
  conjunto.add(oyente);
  return () => {
    conjunto.delete(oyente);
  };
}

export const alExpirarSesion = (oyente: Oyente) => suscribir(oyentesSesion, oyente);
export const alExigirCambioContrasena = (oyente: () => void) => suscribir(oyentesCambio, oyente);

export function revisarSesion(respuesta: Response, cabeceras: Headers): void {
  if (!cabeceras.has("Authorization")) return;
  const codigo = respuesta.headers.get(CABECERA_CODIGO);
  if (respuesta.status === 403 && codigo === CAMBIO_CONTRASENA_OBLIGATORIO) {
    oyentesCambio.forEach((o) => o());
    return;
  }
  if (respuesta.status !== 401) return;
  guardarToken(null);
  const motivo: MotivoCierre = codigo === SESION_REVOCADA ? "revocada" : "expirada";
  oyentesSesion.forEach((o) => o(motivo));
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
