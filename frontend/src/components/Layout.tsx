// Marco común de las pantallas autenticadas: encabezado y menú según los permisos del rol.
// Desde 800 px el menú va fijo a la izquierda. Por debajo, la cabecera muestra «Abrir menú» y las
// mismas opciones se abren en un panel lateral con fondo oscuro; se cierra al elegir una opción,
// con Escape, al pulsar fuera, al salir del panel con Tab o al pasar a 800 px o más.
import { useCallback, useEffect, useRef, useState, type KeyboardEvent } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
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

// Mismo corte que estilos.css (.menu oculto y .boton-menu visible por debajo de 800 px).
export const CONSULTA_ANGOSTA = "(max-width: 799px)";

function iniciales(nombre: string): string {
  return nombre.replace(/^(Lic\.|Dr\.|Dra\.)\s*/, "").split(" ").slice(0, 2).map((p) => p[0]).join("").toUpperCase();
}

// true por debajo de 800 px. Sin matchMedia (pruebas sin simularlo) se comporta como pantalla ancha.
export function useAnchoAngosto(): boolean {
  const consulta = typeof window !== "undefined" && typeof window.matchMedia === "function"
    ? window.matchMedia(CONSULTA_ANGOSTA) : null;
  const [angosto, setAngosto] = useState(() => consulta?.matches ?? false);
  useEffect(() => {
    if (!consulta) return;
    const cambiar = (e: MediaQueryListEvent) => setAngosto(e.matches);
    setAngosto(consulta.matches);
    consulta.addEventListener("change", cambiar);
    return () => consulta.removeEventListener("change", cambiar);
    // La consulta se crea una vez por montaje.
  }, []);
  return angosto;
}

function Opciones({ atencion, admin, alElegir }: { atencion: Opcion[]; admin: Opcion[]; alElegir?: () => void }) {
  return (
    <>
      {atencion.length > 0 && <p className="menu__grupo">Atención</p>}
      {atencion.map((o) => <NavLink key={o.ruta} to={o.ruta} onClick={alElegir}>{o.texto}</NavLink>)}
      {admin.length > 0 && <p className="menu__grupo">Administración</p>}
      {admin.map((o) => <NavLink key={o.ruta} to={o.ruta} onClick={alElegir}>{o.texto}</NavLink>)}
    </>
  );
}

export default function Layout() {
  const { usuario, cerrarSesion, tienePermiso } = useAuth();
  const angosto = useAnchoAngosto();
  const [abierto, setAbierto] = useState(false);
  const boton = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLElement>(null);
  const ubicacion = useLocation();

  // Cierra y devuelve el foco al botón (si sigue en pantalla).
  const cerrar = useCallback((devolverFoco = true) => {
    setAbierto(false);
    if (devolverFoco) setTimeout(() => boton.current?.focus(), 0);
  }, []);

  // Al pasar a 800 px o más el panel se cierra (el botón deja de existir).
  useEffect(() => {
    if (!angosto) setAbierto(false);
  }, [angosto]);

  // Al cambiar de pantalla por otro camino (por ejemplo, «Atrás») el panel no queda abierto.
  useEffect(() => {
    setAbierto(false);
  }, [ubicacion.pathname]);

  // Con el panel abierto: foco en la primera opción y la página de fondo sin desplazamiento.
  useEffect(() => {
    if (!abierto) return;
    panel.current?.querySelector<HTMLElement>("a, button")?.focus();
    const anterior = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = anterior;
    };
  }, [abierto]);

  if (!usuario) return null;
  const atencion = ATENCION.filter((o) => o.permisos.some(tienePermiso));
  const admin = ADMINISTRACION.filter((o) => o.permisos.some(tienePermiso));
  const panelAbierto = angosto && abierto;

  function teclaPanel(e: KeyboardEvent<HTMLElement>) {
    if (e.key === "Escape") {
      e.stopPropagation();
      cerrar();
    }
  }

  return (
    <div className="app">
      <header className="cabecera">
        <div className="cabecera__marca">
          {angosto && (
            <button ref={boton} type="button" className="boton-menu" aria-label="Abrir menú" aria-expanded={panelAbierto}
                    aria-controls="menu-movil" onClick={() => (panelAbierto ? cerrar() : setAbierto(true))}>
              {/* Tres rayas en SVG con el color del botón (blanco); decorativo, el nombre lo da aria-label. */}
              <svg className="boton-menu__icono" width="24" height="24" viewBox="0 0 24 24" aria-hidden="true" focusable="false"
                   fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
                <line x1="4" y1="6" x2="20" y2="6" />
                <line x1="4" y1="12" x2="20" y2="12" />
                <line x1="4" y1="18" x2="20" y2="18" />
              </svg>
            </button>
          )}
          <div className="logo logo--chico">CD</div>
          <div>
            <strong>CDSS Anemia Infantil</strong>
            <span className="cabecera__subtitulo">Centro de Salud San Luis · CRED</span>
          </div>
        </div>
        <div className="cabecera__usuario">
          <span className="insignia">{usuario.rol}</span>
          <span className="cabecera__nombre">{usuario.nombre_completo}</span>
          <span className="avatar">{iniciales(usuario.nombre_completo)}</span>
          <button className="boton boton--enlace" onClick={cerrarSesion}>Cerrar sesión</button>
        </div>
      </header>

      {panelAbierto && (
        <>
          <div className="menu-movil__fondo" aria-hidden="true" onClick={() => cerrar()} />
          <nav id="menu-movil" ref={panel} className="menu menu-movil" aria-label="Menú principal" onKeyDown={teclaPanel}
               onBlur={(e) => {
                 // Salir del panel con Tab lo cierra, sin mover el foco que el usuario eligió.
                 const destino = e.relatedTarget as Node | null;
                 if (destino && !panel.current?.contains(destino) && destino !== boton.current) cerrar(false);
               }}>
            <div className="menu-movil__cabecera">
              <span className="menu-movil__titulo">Menú</span>
              <button type="button" className="menu-movil__cerrar" aria-label="Cerrar menú" onClick={() => cerrar()}>
                <span aria-hidden="true">×</span>
              </button>
            </div>
            <Opciones atencion={atencion} admin={admin} alElegir={() => cerrar()} />
          </nav>
        </>
      )}

      <div className="cuerpo">
        {!angosto && (
          <nav className="menu" aria-label="Menú principal">
            <Opciones atencion={atencion} admin={admin} />
          </nav>
        )}
        <main className="contenido">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
