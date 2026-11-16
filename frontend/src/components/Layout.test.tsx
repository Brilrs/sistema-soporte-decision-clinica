// Menú en pantalla angosta (E6): «Abrir menú» solo por debajo de 800 px, mismas opciones por rol
// que el menú lateral, cierre con Escape, al elegir una opción, al pulsar fuera, con «Cerrar menú»
// y al pasar a 800 px o más, con el foco de vuelta en el botón. matchMedia se simula (jsdom no
// aplica CSS); los permisos por rol son los de db/init/02_catalogos.sql.
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it } from "vitest";
import App from "../App";
import { guardarToken } from "../api/cliente";
import { AuthProvider } from "../auth/AuthContext";
import { USUARIO, respuestaJson, simularBackend } from "../pruebas/simulador";
import { CONSULTA_ANGOSTA } from "./Layout";

type Oyente = (e: { matches: boolean }) => void;

// matchMedia simulado: devuelve si la ventana es angosta y permite cambiarlo.
function simularAncho(angosto: boolean) {
  const oyentes = new Set<Oyente>();
  const lista = {
    matches: angosto, media: CONSULTA_ANGOSTA,
    addEventListener: (_: string, f: Oyente) => oyentes.add(f),
    removeEventListener: (_: string, f: Oyente) => oyentes.delete(f),
  };
  Object.defineProperty(window, "matchMedia", { configurable: true, writable: true, value: () => lista });
  return {
    cambiar(nuevo: boolean) {
      lista.matches = nuevo;
      act(() => oyentes.forEach((f) => f({ matches: nuevo })));
    },
  };
}

afterEach(() => {
  delete (window as { matchMedia?: unknown }).matchMedia;
});

const PERMISOS_CLINICOS = ["REGISTRAR_PACIENTE", "REALIZAR_CONSULTA", "EXPORTAR_REPORTE"];
const ROLES: [string, string[], string[], string[]][] = [
  // rol, permisos, opciones de Atención, opciones de Administración
  ["Enfermera CRED", PERMISOS_CLINICOS, ["Pacientes", "Historial de consultas", "Reportes"], []],
  ["Médico", PERMISOS_CLINICOS, ["Pacientes", "Historial de consultas", "Reportes"], []],
  ["Nutricionista", PERMISOS_CLINICOS, ["Pacientes", "Historial de consultas", "Reportes"], []],
  ["Coordinador CRED", ["REALIZAR_CONSULTA", "EXPORTAR_REPORTE", "CONFIGURAR_PARAMETROS", "VER_AUDITORIA"],
   ["Pacientes", "Historial de consultas", "Reportes"], ["Parámetros clínicos", "Auditoría"]],
  ["Administrador", ["ADMINISTRAR_USUARIOS", "ADMINISTRAR_GUIAS", "CONFIGURAR_PARAMETROS", "VER_AUDITORIA"],
   [], ["Usuarios", "Base de conocimiento", "Parámetros clínicos", "Auditoría"]],
];

function renderizar(rol = "Enfermera CRED", permisos = PERMISOS_CLINICOS, ruta = "/") {
  simularBackend({ "GET /api/auth/me": () => respuestaJson(200, { ...USUARIO, rol, permisos }) });
  guardarToken("token-de-prueba");
  return render(
    <MemoryRouter initialEntries={[ruta]}>
      <AuthProvider>
        <App />
      </AuthProvider>
    </MemoryRouter>,
  );
}

const botonMenu = () => screen.findByRole("button", { name: "Abrir menú" });
const panel = () => screen.queryByRole("navigation", { name: "Menú principal" });

// Opciones de un menú agrupadas como se ven: el texto de cada grupo seguido de sus enlaces.
function grupos(menu: HTMLElement): Record<string, string[]> {
  const salida: Record<string, string[]> = {};
  let actual = "";
  for (const nodo of menu.querySelectorAll(".menu__grupo, a")) {
    if (nodo.classList.contains("menu__grupo")) salida[(actual = nodo.textContent ?? "")] = [];
    else salida[actual].push(nodo.textContent ?? "");
  }
  return salida;
}

describe("menú en pantalla angosta", () => {
  it("desde 800 px no hay botón y el menú lateral sigue fijo", async () => {
    simularAncho(false);
    renderizar();
    expect(await screen.findByRole("navigation", { name: "Menú principal" })).toHaveClass("menu");
    expect(panel()).not.toHaveClass("menu-movil");
    expect(screen.queryByRole("button", { name: "Abrir menú" })).not.toBeInTheDocument();
  });

  it("sin matchMedia (navegador antiguo o pruebas) se comporta como pantalla ancha", async () => {
    renderizar();
    expect(await screen.findByRole("navigation", { name: "Menú principal" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Abrir menú" })).not.toBeInTheDocument();
  });

  it("por debajo de 800 px, «Abrir menú» abre el panel con aria-expanded y el foco en la primera opción", async () => {
    simularAncho(true);
    renderizar();
    const boton = await botonMenu();
    expect(boton).toHaveAttribute("aria-expanded", "false");
    expect(boton).toHaveAttribute("aria-controls", "menu-movil");
    expect(panel()).not.toBeInTheDocument(); // el menú lateral no se renderiza
    fireEvent.click(boton);
    expect(boton).toHaveAttribute("aria-expanded", "true");
    const menu = panel() as HTMLElement;
    expect(menu).toHaveAttribute("id", "menu-movil");
    expect(menu).toHaveClass("menu-movil");
    expect(within(menu).getByRole("button", { name: "Cerrar menú" })).toHaveFocus();
    expect(within(menu).getByRole("link", { name: "Pacientes" })).toHaveAttribute("href", "/pacientes");
  });

  it("el botón contiene el icono de tres rayas (SVG decorativo con el color del botón)", async () => {
    simularAncho(true);
    renderizar();
    const boton = await botonMenu();
    const icono = boton.querySelector("svg") as SVGSVGElement;
    expect(icono).not.toBeNull();
    expect(icono).toHaveAttribute("aria-hidden", "true");
    expect(icono).toHaveAttribute("stroke", "currentColor");
    expect(Number(icono.getAttribute("stroke-width"))).toBeGreaterThanOrEqual(2);
    expect(icono.querySelectorAll("line")).toHaveLength(3);
    // El nombre accesible sigue siendo el aria-label, no el icono.
    expect(boton).toHaveAccessibleName("Abrir menú");
  });

  it.each(ROLES)("%s: el panel muestra las mismas opciones y grupos que el menú lateral", async (rol, permisos, atencion, admin) => {
    const ancho = simularAncho(false);
    renderizar(rol, permisos);
    const esperado = { ...(atencion.length ? { Atención: atencion } : {}), ...(admin.length ? { Administración: admin } : {}) };
    expect(grupos(await screen.findByRole("navigation", { name: "Menú principal" }))).toEqual(esperado);
    ancho.cambiar(true);
    fireEvent.click(await botonMenu());
    expect(grupos(panel() as HTMLElement)).toEqual(esperado);
  });

  it("Escape cierra el panel y devuelve el foco al botón", async () => {
    simularAncho(true);
    renderizar();
    const boton = await botonMenu();
    fireEvent.click(boton);
    fireEvent.keyDown(panel() as HTMLElement, { key: "Escape" });
    expect(panel()).not.toBeInTheDocument();
    expect(boton).toHaveAttribute("aria-expanded", "false");
    await waitFor(() => expect(boton).toHaveFocus());
  });

  it("elegir una opción navega, cierra el panel y devuelve el foco al botón", async () => {
    simularAncho(true);
    renderizar();
    const boton = await botonMenu();
    fireEvent.click(boton);
    fireEvent.click(within(panel() as HTMLElement).getByRole("link", { name: "Reportes" }));
    expect(await screen.findByRole("heading", { level: 1, name: "Reportes" })).toBeInTheDocument();
    expect(panel()).not.toBeInTheDocument();
    expect(boton).toHaveAttribute("aria-expanded", "false");
    await waitFor(() => expect(boton).toHaveFocus());
  });

  it("el administrador llega a Administración desde el panel", async () => {
    simularAncho(true);
    renderizar("Administrador", ROLES[4][1]);
    fireEvent.click(await botonMenu());
    fireEvent.click(within(panel() as HTMLElement).getByRole("link", { name: "Auditoría" }));
    expect(await screen.findByRole("heading", { level: 1, name: "Auditoría" })).toBeInTheDocument();
  });

  it("pulsar fuera (el fondo oscuro) o «Cerrar menú» lo cierra", async () => {
    simularAncho(true);
    renderizar();
    const boton = await botonMenu();
    fireEvent.click(boton);
    fireEvent.click(document.querySelector(".menu-movil__fondo") as HTMLElement);
    expect(panel()).not.toBeInTheDocument();
    await waitFor(() => expect(boton).toHaveFocus());
    fireEvent.click(boton);
    fireEvent.click(screen.getByRole("button", { name: "Cerrar menú" }));
    expect(panel()).not.toBeInTheDocument();
    expect(boton).toHaveAttribute("aria-expanded", "false");
  });

  it("pulsar de nuevo el botón también lo cierra", async () => {
    simularAncho(true);
    renderizar();
    const boton = await botonMenu();
    fireEvent.click(boton);
    fireEvent.click(boton);
    expect(panel()).not.toBeInTheDocument();
    expect(boton).toHaveAttribute("aria-expanded", "false");
  });

  it("al pasar a 800 px o más el panel se cierra, el botón desaparece y vuelve el menú lateral", async () => {
    const ancho = simularAncho(true);
    renderizar();
    fireEvent.click(await botonMenu());
    expect(panel()).toHaveClass("menu-movil");
    ancho.cambiar(false);
    expect(screen.queryByRole("button", { name: "Abrir menú" })).not.toBeInTheDocument();
    expect(panel()).not.toHaveClass("menu-movil");
    expect(document.body.style.overflow).not.toBe("hidden");
    // Y al volver a angosto, el panel no reaparece abierto.
    ancho.cambiar(true);
    expect(await botonMenu()).toHaveAttribute("aria-expanded", "false");
    expect(panel()).not.toBeInTheDocument();
  });

  it("con el panel abierto la página de fondo no se desplaza", async () => {
    simularAncho(true);
    renderizar();
    const boton = await botonMenu();
    fireEvent.click(boton);
    expect(document.body.style.overflow).toBe("hidden");
    fireEvent.keyDown(panel() as HTMLElement, { key: "Escape" });
    expect(document.body.style.overflow).not.toBe("hidden");
  });
});
