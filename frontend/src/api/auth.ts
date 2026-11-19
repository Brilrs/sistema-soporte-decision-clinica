// Cambio de la propia contraseña (Sprint 3, parte I). Contrato en docs/contrato_autenticacion.md.
// La contraseña actual equivocada responde 401 con el código CONTRASENA_ACTUAL_INCORRECTA: es un
// error del formulario y no cierra la sesión. Cualquier otro 401 (token vencido o revocado) sí la
// cierra, como en el resto de las llamadas (revisarSesion).
import { CABECERA_CODIGO, ErrorApi, cabecerasCon, revisarSesion } from "./cliente";

export type UsuarioSesion = {
  id_usuario: string;
  nombre_usuario: string;
  nombre_completo: string;
  rol: string;
  permisos: string[];
  debe_cambiar_contrasena: boolean;
  contrasena_longitud_minima: number;
};

export type RespuestaLogin = { token: string; expira_en_segundos: number; usuario: UsuarioSesion };

export type CodigoCambio =
  | "CONTRASENA_ACTUAL_INCORRECTA"
  | "POLITICA_CONTRASENA"
  | "CONTRASENA_IGUAL"
  | "CUENTA_BLOQUEADA";

export type CampoCambio = "contrasena_actual" | "contrasena_nueva";

export class ErrorCambioContrasena extends ErrorApi {
  constructor(estado: number, mensaje: string, public codigoCambio: CodigoCambio | null, public campo: CampoCambio | null) {
    super(estado, mensaje);
  }
}

const CAMPOS: CampoCambio[] = ["contrasena_actual", "contrasena_nueva"];

export async function cambiarContrasena(contrasenaActual: string, contrasenaNueva: string): Promise<RespuestaLogin> {
  const opciones: RequestInit = {
    method: "POST",
    body: JSON.stringify({ contrasena_actual: contrasenaActual, contrasena_nueva: contrasenaNueva }),
    cache: "no-store",
  };
  const cabeceras = cabecerasCon(opciones);
  const respuesta = await fetch("/api/auth/cambiar-contrasena", { ...opciones, headers: cabeceras });
  if (respuesta.headers.get(CABECERA_CODIGO) !== "CONTRASENA_ACTUAL_INCORRECTA") revisarSesion(respuesta, cabeceras);
  if (respuesta.ok) return respuesta.json() as Promise<RespuestaLogin>;

  let mensaje = "No se pudo cambiar la contraseña";
  let codigo: CodigoCambio | null = null;
  let campo: CampoCambio | null = null;
  try {
    const datos = await respuesta.json();
    if (typeof datos.detail === "string") mensaje = datos.detail;
    if (typeof datos.codigo === "string") codigo = datos.codigo as CodigoCambio;
    if (CAMPOS.includes(datos.campo)) campo = datos.campo;
  } catch {
    /* respuesta sin cuerpo JSON */
  }
  throw new ErrorCambioContrasena(respuesta.status, mensaje, codigo, campo);
}
