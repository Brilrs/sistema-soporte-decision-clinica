// Sprint 3, parte I: «Cambiar mi contraseña» en modo obligatorio y voluntario, redirección con la
// marca activa, errores por campo y del backend, cierre de sesión por contraseña cambiada (401
// SESION_REVOCADA) y la marca en M10. El backend es el simulador; los usuarios son ficticios.
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import App from "../App";
import { guardarToken, leerToken } from "../api/cliente";
import type { UsuarioCuenta } from "../api/usuarios";
import { AuthProvider } from "../auth/AuthContext";
import { USUARIO, respuestaJson, simularBackend } from "../pruebas/simulador";

const CAMBIO = "POST /api/auth/cambiar-contrasena";
const SALUD = "GET /api/salud";
const TEMPORAL = "TemporalAb12cd";
const NUEVA = "ClaveNueva2026x";

const usuario = (debe: boolean, cambios: Record<string, unknown> = {}) => ({
  ...USUARIO, debe_cambiar_contrasena: debe, contrasena_longitud_minima: 12, ...cambios,
});

// Respuesta con el código también en la cabecera X-Codigo-Error, como la envía el backend.
function conCodigo(estado: number, cuerpo: { detail: string; codigo: string; campo?: string }): Response {
  return new Response(JSON.stringify(cuerpo), {
    status: estado, headers: { "Content-Type": "application/json", "X-Codigo-Error": cuerpo.codigo },
  });
}

type Rutas = Parameters<typeof simularBackend>[0];

function renderizar(debe: boolean, ruta = "/", rutas: Rutas = {}) {
  const fetch = simularBackend({
    "GET /api/auth/me": () => respuestaJson(200, usuario(debe)),
    [SALUD]: () => respuestaJson(200, { estado: "ok" }),
    ...rutas,
  });
  guardarToken("token-de-prueba");
  render(
    <MemoryRouter initialEntries={[ruta]}>
      <AuthProvider>
        <App />
      </AuthProvider>
    </MemoryRouter>,
  );
  return fetch;
}

const titulo = () => screen.findByRole("heading", { name: "Cambiar mi contraseña", level: 1 });
const campo = (nombre: string) => screen.getByLabelText(new RegExp(`^${nombre}`)) as HTMLInputElement;

function escribir(actual: string, nueva: string, confirmacion = nueva) {
  fireEvent.change(campo("Contraseña actual"), { target: { value: actual } });
  fireEvent.change(campo("Nueva contraseña"), { target: { value: nueva } });
  fireEvent.change(campo("Confirme la nueva contraseña"), { target: { value: confirmacion } });
}

const enviar = () => fireEvent.click(screen.getByRole("button", { name: "Cambiar contraseña" }));

describe("modo obligatorio", () => {
  it("sin menú ni «Cancelar»; solo «Cerrar sesión»", async () => {
    renderizar(true);
    await titulo();
    expect(screen.getByText(/debe cambiar la contraseña temporal antes de usar el sistema/)).toBeInTheDocument();
    expect(screen.queryByRole("navigation", { name: "Menú principal" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Abrir menú" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Cancelar" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Cambiar contraseña" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cerrar sesión" })).toBeInTheDocument();
  });

  it.each(["/pacientes", "/consultas", "/admin/usuarios", "/no-existe", "/"])(
    "cualquier otra dirección (%s) vuelve a «Cambiar mi contraseña»", async (ruta) => {
      const fetch = renderizar(true, ruta);
      await titulo();
      // No llegó a cargar la otra pantalla
      expect(fetch.mock.calls.map(([r]) => String(r)).filter((r) => !r.startsWith("/api/auth"))).toEqual([]);
    });

  it("«Cerrar sesión» vuelve al login", async () => {
    renderizar(true);
    await titulo();
    fireEvent.click(screen.getByRole("button", { name: "Cerrar sesión" }));
    expect(await screen.findByRole("heading", { name: "Iniciar sesión" })).toBeInTheDocument();
    expect(leerToken()).toBeNull();
  });

  it("un cambio correcto guarda el token nuevo, quita la marca y va al inicio con un aviso", async () => {
    const fetch = renderizar(true, "/", {
      [CAMBIO]: () => respuestaJson(200, { token: "token-nuevo", tipo: "bearer", expira_en_segundos: 60, usuario: usuario(false) }),
    });
    await titulo();
    escribir(TEMPORAL, NUEVA);
    enviar();
    expect(await screen.findByText("Su contraseña se cambió correctamente.")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /^Hola,/ })).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "Menú principal" })).toBeInTheDocument();
    expect(leerToken()).toBe("token-nuevo");
    const llamada = fetch.mock.calls.find(([r, i]) => r === "/api/auth/cambiar-contrasena" && i?.method === "POST")!;
    expect(JSON.parse(String(llamada[1]!.body))).toEqual({ contrasena_actual: TEMPORAL, contrasena_nueva: NUEVA });
    expect(new Headers(llamada[1]!.headers).get("Authorization")).toBe("Bearer token-de-prueba");
  });

  it("un 403 CAMBIO_CONTRASENA_OBLIGATORIO de otra llamada lleva a la pantalla obligatoria", async () => {
    renderizar(false, "/", {
      [SALUD]: () => conCodigo(403, { detail: "Debe cambiar su contraseña antes de continuar.", codigo: "CAMBIO_CONTRASENA_OBLIGATORIO" }),
    });
    await titulo();
    expect(screen.queryByRole("button", { name: "Cancelar" })).not.toBeInTheDocument();
  });
});

describe("modo voluntario", () => {
  it("se abre desde el encabezado, con «Cancelar» y con el menú", async () => {
    renderizar(false);
    fireEvent.click(await screen.findByRole("link", { name: "Cambiar contraseña" }));
    await titulo();
    expect(screen.getByText(/se cerrarán las sesiones que tenga abiertas en otros equipos/)).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "Menú principal" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Cancelar" }));
    expect(await screen.findByRole("heading", { name: /^Hola,/ })).toBeInTheDocument();
  });

  it("todos los roles ven el enlace", async () => {
    for (const [rol, permisos] of [["Administrador", ["ADMINISTRAR_USUARIOS"]], ["Coordinador CRED", ["VER_AUDITORIA"]],
                                   ["Médico", ["REALIZAR_CONSULTA"]]] as const) {
      renderizar(false, "/", { "GET /api/auth/me": () => respuestaJson(200, usuario(false, { rol, permisos })) });
      expect(await screen.findByRole("link", { name: "Cambiar contraseña" })).toHaveAttribute("href", "/cambiar-contrasena");
      fireEvent.click(screen.getByRole("button", { name: "Cerrar sesión" }));
      await screen.findByRole("heading", { name: "Iniciar sesión" });
      cleanup();
    }
  });
});

describe("formulario", () => {
  it("autocompletado, política escrita y mostrar u ocultar", async () => {
    renderizar(false, "/cambiar-contrasena");
    await titulo();
    expect(campo("Contraseña actual")).toHaveAttribute("autocomplete", "current-password");
    expect(campo("Nueva contraseña")).toHaveAttribute("autocomplete", "new-password");
    expect(campo("Confirme la nueva contraseña")).toHaveAttribute("autocomplete", "new-password");
    const politica = screen.getByText("Mínimo 12 caracteres, con al menos una letra y un número.");
    expect(campo("Nueva contraseña").getAttribute("aria-describedby")).toContain(politica.id);

    expect(campo("Contraseña actual")).toHaveAttribute("type", "password");
    fireEvent.click(screen.getByRole("button", { name: "Mostrar contraseña actual" }));
    expect(campo("Contraseña actual")).toHaveAttribute("type", "text");
    expect(campo("Nueva contraseña")).toHaveAttribute("type", "password");
    fireEvent.click(screen.getByRole("button", { name: "Ocultar contraseña actual" }));
    expect(campo("Contraseña actual")).toHaveAttribute("type", "password");
  });

  it("vacío: un error por campo y el resumen recibe el foco", async () => {
    const fetch = renderizar(true);
    await titulo();
    enviar();
    const resumen = await screen.findByRole("alert");
    await waitFor(() => expect(resumen).toHaveFocus());
    expect(within(resumen).getAllByRole("link").map((a) => a.textContent)).toEqual([
      "Contraseña actual: Escriba su contraseña actual.",
      "Nueva contraseña: Escriba la nueva contraseña.",
      "Confirme la nueva contraseña: Repita la nueva contraseña.",
    ]);
    for (const nombre of ["Contraseña actual", "Nueva contraseña", "Confirme la nueva contraseña"]) {
      expect(campo(nombre)).toHaveAttribute("aria-invalid", "true");
    }
    fireEvent.click(within(resumen).getAllByRole("link")[1]);
    expect(campo("Nueva contraseña")).toHaveFocus();
    expect(fetch.mock.calls.some(([r]) => r === "/api/auth/cambiar-contrasena")).toBe(false);
  });

  it.each([
    ["muy corta", TEMPORAL, "Corta1", "Corta1",
     "Nueva contraseña", "La nueva contraseña no cumple la política: mínimo 12 caracteres, con al menos una letra y un número."],
    ["sin número", TEMPORAL, "SoloLetrasLargas", "SoloLetrasLargas",
     "Nueva contraseña", "La nueva contraseña no cumple la política: mínimo 12 caracteres, con al menos una letra y un número."],
    ["igual a la actual", NUEVA, NUEVA, NUEVA, "Nueva contraseña", "La nueva contraseña debe ser distinta de la actual."],
    ["confirmación distinta", TEMPORAL, NUEVA, NUEVA + "z",
     "Confirme la nueva contraseña", "La confirmación no coincide con la nueva contraseña."],
  ])("%s: error junto al campo, sin llamar al backend", async (_, actual, nueva, confirmacion, nombre, mensaje) => {
    const fetch = renderizar(true);
    await titulo();
    escribir(actual, nueva, confirmacion);
    enviar();
    const error = await screen.findByText(mensaje, { selector: ".campo__error" });
    expect(campo(nombre).getAttribute("aria-describedby")).toContain(error.id);
    expect(within(screen.getByRole("alert")).getByRole("link")).toHaveTextContent(`${nombre}: ${mensaje}`);
    expect(fetch.mock.calls.some(([r]) => r === "/api/auth/cambiar-contrasena")).toBe(false);
  });

  it("contraseña actual equivocada (401 del backend): error en el campo y la sesión sigue", async () => {
    renderizar(true, "/", {
      [CAMBIO]: () => conCodigo(401, { detail: "La contraseña actual no es correcta.", codigo: "CONTRASENA_ACTUAL_INCORRECTA",
                                       campo: "contrasena_actual" }),
    });
    await titulo();
    escribir("Equivocada123", NUEVA);
    enviar();
    expect(await screen.findByText("La contraseña actual no es correcta.", { selector: ".campo__error" })).toBeInTheDocument();
    expect(campo("Contraseña actual")).toHaveAttribute("aria-invalid", "true");
    expect(screen.queryByRole("heading", { name: "Iniciar sesión" })).not.toBeInTheDocument();
    expect(leerToken()).toBe("token-de-prueba");
    expect(screen.getByRole("button", { name: "Cambiar contraseña" })).toBeEnabled();
  });

  it("política rechazada por el backend (422): error en la nueva contraseña", async () => {
    renderizar(true, "/", {
      [CAMBIO]: () => conCodigo(422, { detail: "La nueva contraseña no cumple la política: mínimo 14 caracteres.",
                                       codigo: "POLITICA_CONTRASENA", campo: "contrasena_nueva" }),
    });
    await titulo();
    escribir(TEMPORAL, NUEVA);
    enviar();
    expect(await screen.findByText("La nueva contraseña no cumple la política: mínimo 14 caracteres.",
                                   { selector: ".campo__error" })).toBeInTheDocument();
    expect(campo("Nueva contraseña")).toHaveAttribute("aria-invalid", "true");
  });

  it("cuenta bloqueada (423): mensaje general en el resumen", async () => {
    renderizar(true, "/", {
      [CAMBIO]: () => conCodigo(423, { detail: "La cuenta está bloqueada por intentos fallidos. Solicite el desbloqueo al administrador.",
                                       codigo: "CUENTA_BLOQUEADA" }),
    });
    await titulo();
    escribir(TEMPORAL, NUEVA);
    enviar();
    const resumen = await screen.findByRole("alert");
    expect(resumen).toHaveTextContent("La cuenta está bloqueada por intentos fallidos.");
    expect(within(resumen).queryByRole("link")).not.toBeInTheDocument();
  });
});

describe("sesión invalidada por un cambio de contraseña", () => {
  it("401 SESION_REVOCADA al cambiar: vuelve al login con el motivo", async () => {
    renderizar(false, "/cambiar-contrasena", {
      [CAMBIO]: () => conCodigo(401, { detail: "Sesión no válida o expirada", codigo: "SESION_REVOCADA" }),
    });
    await titulo();
    escribir(TEMPORAL, NUEVA);
    enviar();
    expect(await screen.findByRole("heading", { name: "Iniciar sesión" })).toBeInTheDocument();
    expect(screen.getByText("Su sesión terminó porque la contraseña cambió. Ingrese de nuevo.")).toBeInTheDocument();
    expect(leerToken()).toBeNull();
  });

  it("401 SESION_REVOCADA en cualquier otra llamada: el mismo mensaje", async () => {
    renderizar(false, "/", {
      [SALUD]: () => conCodigo(401, { detail: "Sesión no válida o expirada", codigo: "SESION_REVOCADA" }),
    });
    expect(await screen.findByRole("heading", { name: "Iniciar sesión" })).toBeInTheDocument();
    expect(screen.getByText("Su sesión terminó porque la contraseña cambió. Ingrese de nuevo.")).toBeInTheDocument();
  });

  it("un 401 sin ese código conserva el mensaje de sesión vencida", async () => {
    renderizar(false, "/", { [SALUD]: () => respuestaJson(401, { detail: "Sesión no válida o expirada" }) });
    expect(await screen.findByText("Su sesión expiró o ya no es válida. Inicie sesión nuevamente.")).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// M10: la marca en la lista y el aviso de la contraseña temporal
// ---------------------------------------------------------------------------
const ADMINISTRADOR = usuario(false, { rol: "Administrador", permisos: ["ADMINISTRAR_USUARIOS"], id_usuario: "u-admin" });

function cuenta(id: string, nombre: string, debe: boolean): UsuarioCuenta {
  return {
    id_usuario: id, nombre_completo: nombre, nombre_usuario: `prueba.${id}`, correo_institucional: null, id_rol: 2,
    rol: "Médico", activo: true, bloqueado: false, estado: "ACTIVO", ultimo_acceso: null,
    fecha_creacion: "2026-11-01T10:00:00-05:00", fecha_desactivacion: null, debe_cambiar_contrasena: debe,
  };
}

const ROLES = {
  permisos: [{ codigo: "REALIZAR_CONSULTA", descripcion: "Realizar consultas" }],
  roles: [{ id_rol: 2, nombre: "Médico", descripcion: null, activo: true, permisos: ["REALIZAR_CONSULTA"] }],
};

describe("M10", () => {
  function renderizarM10(rutas: Rutas = {}) {
    return renderizar(false, "/admin/usuarios", {
      "GET /api/auth/me": () => respuestaJson(200, ADMINISTRADOR),
      "GET /api/usuarios": () => respuestaJson(200, [cuenta("a", "Cuenta Con Marca", true), cuenta("b", "Cuenta Sin Marca", false)]),
      "GET /api/usuarios/roles": () => respuestaJson(200, ROLES),
      ...rutas,
    });
  }

  it("la lista muestra «Debe cambiar su contraseña» con texto solo en la cuenta con la marca", async () => {
    renderizarM10();
    const fila = (await screen.findByText("Cuenta Con Marca")).closest("tr")!;
    expect(within(fila).getByText("Debe cambiar su contraseña")).toBeInTheDocument();
    const otra = screen.getByText("Cuenta Sin Marca").closest("tr")!;
    expect(within(otra).queryByText("Debe cambiar su contraseña")).not.toBeInTheDocument();
    expect(screen.getAllByText("Debe cambiar su contraseña")).toHaveLength(1);
  });

  it("al crear, el aviso dice que deberá cambiarla al ingresar y la fila nueva lleva la marca", async () => {
    const nueva = cuenta("c", "Cuenta Recién Creada", true);
    renderizarM10({ "POST /api/usuarios": () => respuestaJson(201, { usuario: nueva, contrasena_temporal: TEMPORAL }) });
    fireEvent.click(await screen.findByRole("button", { name: "+ Nuevo usuario" }));
    fireEvent.change(screen.getByLabelText(/^Nombre completo/), { target: { value: "Cuenta Recién Creada" } });
    fireEvent.change(screen.getByLabelText(/^Usuario/), { target: { value: "prueba.c" } });
    fireEvent.change(screen.getByLabelText(/^Rol/), { target: { value: "2" } });
    fireEvent.click(screen.getByRole("button", { name: "Crear usuario" }));
    const aviso = await screen.findByRole("dialog", { name: "Usuario creado" });
    expect(aviso).toHaveTextContent("deberá cambiarla por una contraseña propia al ingresar al sistema");
    fireEvent.click(within(aviso).getByRole("button", { name: "Cerrar" }));
    const fila = screen.getAllByText("Cuenta Recién Creada").map((n) => n.closest("tr")).find(Boolean)!;
    expect(within(fila).getByText("Debe cambiar su contraseña")).toBeInTheDocument();
  });
});
