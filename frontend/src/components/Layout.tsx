// Marco común de las pantallas autenticadas: encabezado y menú según los permisos del rol.
import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";

// Cada opción se muestra si el rol tiene alguno de sus permisos.
type Opcion = { ruta: string; texto: string; permisos: string[] };

const ATENCION: Opcion[] = [
  { ruta: "/pacientes", texto: "Pacientes", permisos: ["REGISTRAR_PACIENTE", "REALIZAR_CONSULTA"] },
  { ruta: "/consultas", texto: "Historial de consultas", permisos: ["REALIZAR_CONSULTA"] },
  { ruta: "/reportes", texto: "Reportes", permisos: ["EXPORTAR_REPORTE"] },
];

const ADMINISTRACION: Opcion[] = [
  { ruta: "/admin/usuarios", texto: "Usuarios", permisos: ["ADMINISTRAR_USUARIOS"] },
  { ruta: "/admin/conocimiento", texto: "Base de conocimiento", permisos: ["ADMINISTRAR_GUIAS"] },
  { ruta: "/admin/parametros", texto: "Parámetros clínicos", permisos: ["CONFIGURAR_PARAMETROS"] },
  { ruta: "/admin/auditoria", texto: "Auditoría", permisos: ["VER_AUDITORIA"] },
];

function iniciales(nombre: string): string {
  return nombre.replace(/^(Lic\.|Dr\.|Dra\.)\s*/, "").split(" ").slice(0, 2).map((p) => p[0]).join("").toUpperCase();
}

export default function Layout() {
  const { usuario, cerrarSesion, tienePermiso } = useAuth();
  if (!usuario) return null;
  const atencion = ATENCION.filter((o) => o.permisos.some(tienePermiso));
  const admin = ADMINISTRACION.filter((o) => o.permisos.some(tienePermiso));

  return (
    <div className="app">
      <header className="cabecera">
        <div className="cabecera__marca">
          <div className="logo logo--chico">CD</div>
          <div>
            <strong>CDSS Anemia Infantil</strong>
            <span>Centro de Salud San Luis · CRED</span>
          </div>
        </div>
        <div className="cabecera__usuario">
          <span className="insignia">{usuario.rol}</span>
          <span>{usuario.nombre_completo}</span>
          <span className="avatar">{iniciales(usuario.nombre_completo)}</span>
          <button className="boton boton--enlace" onClick={cerrarSesion}>Cerrar sesión</button>
        </div>
      </header>

      <div className="cuerpo">
        <nav className="menu">
          {atencion.length > 0 && <p className="menu__grupo">Atención</p>}
          {atencion.map((o) => <NavLink key={o.ruta} to={o.ruta}>{o.texto}</NavLink>)}
          {admin.length > 0 && <p className="menu__grupo">Administración</p>}
          {admin.map((o) => <NavLink key={o.ruta} to={o.ruta}>{o.texto}</NavLink>)}
        </nav>
        <main className="contenido">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
