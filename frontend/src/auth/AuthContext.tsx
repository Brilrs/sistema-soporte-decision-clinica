import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { api, ErrorApi, guardarToken, leerToken } from "../api/cliente";

export type Usuario = {
  id_usuario: string;
  nombre_usuario: string;
  nombre_completo: string;
  rol: string;
  permisos: string[];
};

type RespuestaLogin = { token: string; expira_en_segundos: number; usuario: Usuario };

type EstadoAuth = {
  usuario: Usuario | null;
  cargando: boolean;
  iniciarSesion: (usuario: string, contrasena: string) => Promise<void>;
  cerrarSesion: () => void;
  tienePermiso: (codigo: string) => boolean;
};

const AuthContext = createContext<EstadoAuth | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [usuario, setUsuario] = useState<Usuario | null>(null);
  const [cargando, setCargando] = useState(true);

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
    setUsuario(datos.usuario);
  }, []);

  const cerrarSesion = useCallback(() => {
    guardarToken(null);
    setUsuario(null);
  }, []);

  const tienePermiso = useCallback((codigo: string) => !!usuario?.permisos.includes(codigo), [usuario]);

  return (
    <AuthContext.Provider value={{ usuario, cargando, iniciarSesion, cerrarSesion, tienePermiso }}>
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
