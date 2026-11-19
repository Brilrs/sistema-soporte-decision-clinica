import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { cambiarContrasena as cambiarContrasenaApi, type RespuestaLogin, type UsuarioSesion } from "../api/auth";
import { alExigirCambioContrasena, alExpirarSesion, api, ErrorApi, guardarToken, leerToken } from "../api/cliente";

// debe_cambiar_contrasena: la cuenta es nueva o su contraseña fue restablecida; mientras sea
// verdadera, App solo deja ver «Cambiar mi contraseña» (el backend responde 403 en el resto).
export type Usuario = UsuarioSesion;

export const AVISO_SESION_EXPIRADA = "Su sesión expiró o ya no es válida. Inicie sesión nuevamente.";
export const AVISO_CONTRASENA_CAMBIADA = "Su sesión terminó porque la contraseña cambió. Ingrese de nuevo.";

type EstadoAuth = {
  usuario: Usuario | null;
  cargando: boolean;
  iniciarSesion: (usuario: string, contrasena: string) => Promise<void>;
  cerrarSesion: () => void;
  // Cambia la contraseña propia; guarda el token nuevo que devuelve el backend (la sesión sigue).
  cambiarContrasena: (actual: string, nueva: string) => Promise<void>;
  // Motivo del último cierre automático (sesión vencida); lo muestra el login.
  avisoSesion: string | null;
  tienePermiso: (codigo: string) => boolean;
};

const AuthContext = createContext<EstadoAuth | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [usuario, setUsuario] = useState<Usuario | null>(null);
  const [cargando, setCargando] = useState(true);
  const [avisoSesion, setAvisoSesion] = useState<string | null>(null);

  // Cualquier llamada que envió el token y recibe 401 (incluido el lector NDJSON) cierra la
  // sesión en pantalla: Protegida redirige al login, que muestra el aviso.
  useEffect(
    () =>
      alExpirarSesion((motivo) => {
        setAvisoSesion(motivo === "revocada" ? AVISO_CONTRASENA_CAMBIADA : AVISO_SESION_EXPIRADA);
        setUsuario(null);
      }),
    [],
  );

  // 403 CAMBIO_CONTRASENA_OBLIGATORIO en cualquier llamada: la cuenta tiene la marca.
  useEffect(
    () => alExigirCambioContrasena(() => setUsuario((u) => (u ? { ...u, debe_cambiar_contrasena: true } : u))),
    [],
  );

  // Al recargar la página se recupera la sesión si el token sigue vigente.
  useEffect(() => {
    if (!leerToken()) {
      setCargando(false);
      return;
    }
    api<Usuario>("/api/auth/me")
      .then(setUsuario)
      .catch(() => guardarToken(null))
      .finally(() => setCargando(false));
  }, []);

  const iniciarSesion = useCallback(async (nombreUsuario: string, contrasena: string) => {
    const datos = await api<RespuestaLogin>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ usuario: nombreUsuario, contrasena }),
    });
    guardarToken(datos.token);
    setAvisoSesion(null);
    setUsuario(datos.usuario);
  }, []);

  const cambiarContrasena = useCallback(async (actual: string, nueva: string) => {
    const datos = await cambiarContrasenaApi(actual, nueva);
    guardarToken(datos.token);
    setUsuario(datos.usuario);
  }, []);

  const cerrarSesion = useCallback(() => {
    guardarToken(null);
    setAvisoSesion(null);
    setUsuario(null);
  }, []);

  const tienePermiso = useCallback((codigo: string) => !!usuario?.permisos.includes(codigo), [usuario]);

  return (
    <AuthContext.Provider
      value={{ usuario, cargando, iniciarSesion, cerrarSesion, cambiarContrasena, avisoSesion, tienePermiso }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): EstadoAuth {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth debe usarse dentro de AuthProvider");
  return ctx;
}

export { ErrorApi };
