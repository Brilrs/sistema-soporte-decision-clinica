// Tipos y llamadas a los endpoints de gestión de usuarios (HU11, pantalla M10).
// La contraseña temporal solo llega en la respuesta de creación o restablecimiento:
// no se guarda en ningún almacenamiento del navegador.
import { api } from "./cliente";

export type EstadoCuenta = "ACTIVO" | "INACTIVO" | "BLOQUEADO";

export type UsuarioCuenta = {
  id_usuario: string;
  nombre_completo: string;
  nombre_usuario: string;
  correo_institucional: string | null;
  id_rol: number;
  rol: string;
  activo: boolean;
  bloqueado: boolean;
  estado: EstadoCuenta;
  ultimo_acceso: string | null;
  fecha_creacion: string;
  fecha_desactivacion: string | null;
};

export type Permiso = { codigo: string; descripcion: string };
export type Rol = { id_rol: number; nombre: string; descripcion: string | null; activo: boolean; permisos: string[] };
export type RolesYPermisos = { permisos: Permiso[]; roles: Rol[] };

export type UsuarioNuevo = {
  nombre_completo: string;
  nombre_usuario: string;
  correo_institucional: string | null;
  id_rol: number;
};

export type UsuarioCambios = Partial<Pick<UsuarioNuevo, "nombre_completo" | "correo_institucional" | "id_rol">>;

export type UsuarioConContrasena = { usuario: UsuarioCuenta; contrasena_temporal: string };

const accion = (id: string, nombre: string) => api<UsuarioCuenta>(`/api/usuarios/${id}/${nombre}`, { method: "POST" });

export const usuariosApi = {
  listar: () => api<UsuarioCuenta[]>("/api/usuarios"),
  roles: () => api<RolesYPermisos>("/api/usuarios/roles"),
  crear: (datos: UsuarioNuevo) =>
    api<UsuarioConContrasena>("/api/usuarios", { method: "POST", body: JSON.stringify(datos), cache: "no-store" }),
  actualizar: (id: string, cambios: UsuarioCambios) =>
    api<UsuarioCuenta>(`/api/usuarios/${id}`, { method: "PATCH", body: JSON.stringify(cambios) }),
  desactivar: (id: string) => accion(id, "desactivar"),
  reactivar: (id: string) => accion(id, "reactivar"),
  desbloquear: (id: string) => accion(id, "desbloquear"),
  restablecerContrasena: (id: string) =>
    api<UsuarioConContrasena>(`/api/usuarios/${id}/restablecer-contrasena`, { method: "POST", cache: "no-store" }),
};
