// Pruebas de la parte B del Sprint 3: «Historial de consultas» (/consultas, P10), el buscador de
// «Nueva consulta» (/consultas/nueva) y «Registrada por» en M05 (P12). Fetch simulado con datos
// ficticios; sin API real. Los datos que leen las pantallas (sexo, edades, fechas) van explícitos.
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import { guardarToken } from "../api/cliente";
import type { ConsultaPropia, PaginaConsultas } from "../api/tipos_consulta";
import { AuthProvider } from "../auth/AuthContext";
import { CONSULTA_ANGOSTA } from "../components/Layout";
import {
  FICHA,
  GET_RESULTADO,
  ID_CONSULTA,
  ID_PACIENTE,
  USUARIO,
  respuestaJson,
  resultadoFixture,
  simularBackend,
} from "../pruebas/simulador";
import { fechaHora } from "../utilidades/formato";
import { POR_PAGINA } from "./HistorialConsultas";

function renderizar(ruta: string) {
  guardarToken("token-de-prueba");
  return render(
    <MemoryRouter initialEntries={[ruta]}>
      <AuthProvider>
        <App />
      </AuthProvider>
    </MemoryRouter>,
  );
}

function consulta(cambios: Partial<ConsultaPropia>): ConsultaPropia {
  return {
    id_consulta: "c-0001", id_paciente: ID_PACIENTE, nombres_apellidos: FICHA.nombres_apellidos, numero_hc: FICHA.numero_hc,
    edad_meses: 16, estado: "VERIFICADA", categoria: "ANEMIA_LEVE", nivel_riesgo: "MODERADO",
    fecha_hora_inicio: "2026-11-10T10:42:00-05:00", modo_prueba: false, pregunta: "¿Qué dosis de hierro le corresponde a [PACIENTE]?",
    ...cambios,
  };
}

const CONSULTAS: ConsultaPropia[] = [
  consulta({ id_consulta: ID_CONSULTA, modo_prueba: true }),
  consulta({ id_consulta: "c-0002", nombres_apellidos: "Paciente Ficticio Tres", numero_hc: "HC-PRUEBA-3", edad_meses: 40,
             estado: "EVIDENCIA_INSUFICIENTE", categoria: "SIN_ANEMIA", nivel_riesgo: "BAJO",
             fecha_hora_inicio: "2026-11-09T08:15:00-05:00", pregunta: null }),
  consulta({ id_consulta: "c-0003", estado: "FUERA_DE_DOMINIO", categoria: null, nivel_riesgo: null,
             fecha_hora_inicio: "2026-11-08T16:20:00-05:00" }),
];

function pagina(consultas: ConsultaPropia[], total = consultas.length, desplazamiento = 0): PaginaConsultas {
  return { total, limite: POR_PAGINA, desplazamiento, consultas };
}

// GET /api/consultas con cualquier filtro: guarda las URL pedidas y responde lo que diga la prueba.
function conLista(responder: (url: URL) => Response | Promise<Response>, extra: Parameters<typeof simularBackend>[0] = {}) {
  const pedidas: URL[] = [];
  const f = simularBackend({
    "GET /api/consultas": (_init, url) => {
      pedidas.push(url);
      return responder(url);
    },
    ...extra,
  });
  return { f, pedidas, parametros: () => pedidas.map((u) => u.search) };
}

// matchMedia simulado (jsdom no lo trae): pantalla angosta o ancha.
function simularAncho(angosto: boolean) {
  const lista = { matches: angosto, media: CONSULTA_ANGOSTA, addEventListener: vi.fn(), removeEventListener: vi.fn() };
  Object.defineProperty(window, "matchMedia", { configurable: true, writable: true, value: () => lista });
}

afterEach(() => {
  delete (window as { matchMedia?: unknown }).matchMedia;
});

// ---------------------------------------------------------------------------
// Lista
// ---------------------------------------------------------------------------
describe("Historial de consultas · lista", () => {
  it("pide la primera página y muestra cada consulta con paciente, etiquetas de texto y enlace", async () => {
    const { parametros } = conLista(() => respuestaJson(200, pagina(CONSULTAS)));
    renderizar("/consultas");
    expect(await screen.findByRole("heading", { level: 1, name: "Historial de consultas" })).toBeInTheDocument();
    const tabla = await screen.findByRole("region", { name: "Consultas realizadas" });
    const filas = within(tabla).getAllByRole("row").slice(1);
    expect(filas).toHaveLength(3);
    expect(parametros()).toEqual([`?limite=${POR_PAGINA}&desplazamiento=0`]);

    const primera = filas[0];
    expect(primera).toHaveTextContent(fechaHora(CONSULTAS[0].fecha_hora_inicio));
    expect(primera).toHaveTextContent(FICHA.nombres_apellidos);
    expect(primera).toHaveTextContent(`HC ${FICHA.numero_hc} · 16 meses`);
    expect(within(primera).getByText("Anemia leve")).toBeInTheDocument();
    expect(within(primera).getByText("Riesgo moderado")).toBeInTheDocument();
    expect(within(primera).getByText("Verificada")).toBeInTheDocument();
    expect(within(primera).getByText("Prueba")).toHaveClass("etiqueta", "etiqueta--prueba");
    expect(primera).toHaveTextContent("¿Qué dosis de hierro le corresponde a [PACIENTE]?");
    const ver = within(primera).getByRole("link", { name: `Ver la consulta de ${FICHA.nombres_apellidos} del ${fechaHora(CONSULTAS[0].fecha_hora_inicio)}` });
    expect(ver).toHaveAttribute("href", `/consultas/${ID_CONSULTA}`);

    expect(filas[1]).toHaveTextContent("Sin pregunta registrada");
    expect(within(filas[1]).getByText("Riesgo bajo")).toBeInTheDocument();
    expect(within(filas[1]).getByText("Evidencia insuficiente")).toBeInTheDocument();
    expect(within(filas[1]).queryByText("Prueba")).not.toBeInTheDocument();
    expect(within(filas[2]).getByText("Sin clasificación")).toBeInTheDocument();
    expect(within(filas[2]).getByText("Fuera del alcance")).toBeInTheDocument();
    expect(screen.getByText("Mostrando 1 a 3 de 3 consultas")).toBeInTheDocument();
    expect(screen.queryByRole("navigation", { name: "Paginación de las consultas" })).not.toBeInTheDocument();
  });

  it("cada consulta abre su resultado (M05)", async () => {
    conLista(() => respuestaJson(200, pagina(CONSULTAS)), {
      [GET_RESULTADO]: () => respuestaJson(200, resultadoFixture("VERIFICADA")),
    });
    renderizar("/consultas");
    const tabla = await screen.findByRole("region", { name: "Consultas realizadas" });
    fireEvent.click(within(tabla).getAllByRole("link", { name: /^Ver la consulta de/ })[0]);
    expect(await screen.findByText("Pregunta realizada")).toBeInTheDocument();
  });

  it("debajo de 800 px muestra tarjetas apiladas en lugar de la tabla", async () => {
    simularAncho(true);
    conLista(() => respuestaJson(200, pagina(CONSULTAS)));
    renderizar("/consultas");
    const lista = await screen.findByRole("list", { name: "Consultas realizadas" });
    const tarjetas = within(lista).getAllByRole("listitem");
    expect(tarjetas).toHaveLength(3);
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(tarjetas[0]).toHaveTextContent(FICHA.nombres_apellidos);
    expect(within(tarjetas[0]).getByText("Prueba")).toBeInTheDocument();
    expect(within(tarjetas[0]).getByRole("link", { name: /^Ver la consulta de/ })).toHaveTextContent("Ver resultado");
  });
});

// ---------------------------------------------------------------------------
// Filtros y paginación
// ---------------------------------------------------------------------------
describe("Historial de consultas · filtros y paginación", () => {
  it("aplica estado y fechas, vuelve a la primera página y los limpia", async () => {
    const { parametros } = conLista((u) =>
      respuestaJson(200, u.searchParams.get("estado") ? pagina([CONSULTAS[1]]) : pagina(CONSULTAS)));
    renderizar("/consultas");
    await screen.findByRole("region", { name: "Consultas realizadas" });
    fireEvent.change(screen.getByLabelText("Estado"), { target: { value: "EVIDENCIA_INSUFICIENTE" } });
    fireEvent.change(screen.getByLabelText("Desde"), { target: { value: "2026-11-01" } });
    fireEvent.change(screen.getByLabelText("Hasta"), { target: { value: "2026-11-15" } });
    fireEvent.click(screen.getByRole("button", { name: "Filtrar" }));
    await waitFor(() => expect(parametros()).toHaveLength(2));
    expect(parametros()[1]).toBe(`?estado=EVIDENCIA_INSUFICIENTE&fecha_desde=2026-11-01&fecha_hasta=2026-11-15&limite=${POR_PAGINA}&desplazamiento=0`);
    await waitFor(() => expect(screen.getAllByRole("row")).toHaveLength(2));
    fireEvent.click(screen.getByRole("button", { name: "Limpiar filtros" }));
    await waitFor(() => expect(parametros()).toHaveLength(3));
    expect(parametros()[2]).toBe(`?limite=${POR_PAGINA}&desplazamiento=0`);
    expect(screen.getByLabelText("Estado")).toHaveValue("");
    expect(screen.getByLabelText("Desde")).toHaveValue("");
  });

  it("no envía un rango con «Hasta» anterior a «Desde» y lo explica junto a los campos", async () => {
    const { parametros } = conLista(() => respuestaJson(200, pagina(CONSULTAS)));
    renderizar("/consultas");
    await screen.findByRole("region", { name: "Consultas realizadas" });
    fireEvent.change(screen.getByLabelText("Desde"), { target: { value: "2026-11-15" } });
    fireEvent.change(screen.getByLabelText("Hasta"), { target: { value: "2026-11-01" } });
    fireEvent.click(screen.getByRole("button", { name: "Filtrar" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("La fecha «Hasta» no puede ser anterior a «Desde».");
    expect(screen.getByLabelText("Hasta")).toHaveAttribute("aria-invalid", "true");
    expect(parametros()).toHaveLength(1);
  });

  it("pagina de a 20 con «Anterior» y «Siguiente» y el total", async () => {
    const total = 45;
    const { parametros } = conLista((u) => {
      const desde = Number(u.searchParams.get("desplazamiento"));
      const n = Math.min(POR_PAGINA, total - desde);
      return respuestaJson(200, pagina(Array.from({ length: n }, (_, i) => consulta({ id_consulta: `c-${desde + i}` })), total, desde));
    });
    renderizar("/consultas");
    expect(await screen.findByText(`Mostrando 1 a 20 de ${total} consultas`)).toBeInTheDocument();
    const nav = screen.getByRole("navigation", { name: "Paginación de las consultas" });
    expect(within(nav).getByText("Página 1 de 3")).toBeInTheDocument();
    expect(within(nav).getByRole("button", { name: "Anterior" })).toBeDisabled();
    fireEvent.click(within(nav).getByRole("button", { name: "Siguiente" }));
    expect(await screen.findByText(`Mostrando 21 a 40 de ${total} consultas`)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Siguiente" }));
    expect(await screen.findByText(`Mostrando 41 a 45 de ${total} consultas`)).toBeInTheDocument();
    expect(screen.getByText("Página 3 de 3")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Siguiente" })).toBeDisabled();
    expect(parametros().map((p) => new URLSearchParams(p).get("desplazamiento"))).toEqual(["0", "20", "40"]);
    fireEvent.click(screen.getByRole("button", { name: "Anterior" }));
    expect(await screen.findByText(`Mostrando 21 a 40 de ${total} consultas`)).toBeInTheDocument();
  });

  it("los filtros y la página de la dirección se respetan al llegar (por ejemplo, al volver del resultado)", async () => {
    const { parametros } = conLista(() => respuestaJson(200, pagina([CONSULTAS[1]], 41, 20)));
    renderizar("/consultas?estado=VERIFICADA&desde=2026-11-01&pagina=2&otro=x");
    expect(await screen.findByText("Mostrando 21 a 21 de 41 consultas")).toBeInTheDocument();
    expect(parametros()).toEqual([`?estado=VERIFICADA&fecha_desde=2026-11-01&limite=${POR_PAGINA}&desplazamiento=20`]);
    expect(screen.getByLabelText("Estado")).toHaveValue("VERIFICADA");
    expect(screen.getByLabelText("Desde")).toHaveValue("2026-11-01");
  });
});

// ---------------------------------------------------------------------------
// Estados de carga, vacío y error
// ---------------------------------------------------------------------------
describe("Historial de consultas · carga, vacío y error", () => {
  it("muestra «Cargando consultas…» mientras espera", async () => {
    let responder!: (r: Response) => void;
    conLista(() => new Promise<Response>((r) => { responder = r; }));
    renderizar("/consultas");
    expect(await screen.findByText("Cargando consultas…")).toBeInTheDocument();
    responder(respuestaJson(200, pagina(CONSULTAS)));
    expect(await screen.findByRole("region", { name: "Consultas realizadas" })).toBeInTheDocument();
    expect(screen.queryByText("Cargando consultas…")).not.toBeInTheDocument();
  });

  it("sin consultas invita a «Nueva consulta»; con filtros dice que no hay coincidencias", async () => {
    conLista(() => respuestaJson(200, pagina([])));
    const vista = renderizar("/consultas");
    expect(await screen.findByText("Aún no realizó consultas clínicas. Use «Nueva consulta» para iniciar una.")).toBeInTheDocument();
    vista.unmount();
    conLista(() => respuestaJson(200, pagina([])));
    renderizar("/consultas?estado=ERROR");
    expect(await screen.findByText("No hay consultas con esos filtros.")).toBeInTheDocument();
  });

  it("una página fuera de rango ofrece volver a la primera", async () => {
    const { parametros } = conLista((u) => respuestaJson(200, u.searchParams.get("desplazamiento") === "0"
      ? pagina(CONSULTAS) : pagina([], 3, 40)));
    renderizar("/consultas?pagina=3");
    fireEvent.click(await screen.findByRole("button", { name: "Ir a la primera página" }));
    expect(await screen.findByRole("region", { name: "Consultas realizadas" })).toBeInTheDocument();
    expect(parametros().map((p) => new URLSearchParams(p).get("desplazamiento"))).toEqual(["40", "0"]);
  });

  it("si falla, muestra el error y «Reintentar» vuelve a pedir la lista", async () => {
    let fallar = true;
    const { parametros } = conLista(() => (fallar
      ? respuestaJson(500, { detail: "Error interno del servidor" })
      : respuestaJson(200, pagina(CONSULTAS))));
    renderizar("/consultas");
    const alerta = await screen.findByRole("alert");
    expect(alerta).toHaveTextContent("No se pudieron cargar las consultas.");
    fallar = false;
    fireEvent.click(within(alerta).getByRole("button", { name: "Reintentar" }));
    expect(await screen.findByRole("region", { name: "Consultas realizadas" })).toBeInTheDocument();
    expect(parametros()).toHaveLength(2);
  });
});

// ---------------------------------------------------------------------------
// «Nueva consulta»: el buscador que estaba en /consultas, con sus flujos
// ---------------------------------------------------------------------------
describe("Nueva consulta (/consultas/nueva)", () => {
  const RECIENTES = {
    "GET /api/pacientes": () => respuestaJson(200, [{ id_paciente: ID_PACIENTE, nombres_apellidos: FICHA.nombres_apellidos,
      numero_hc: FICHA.numero_hc, sexo: "M", edad_meses_actual: 16, ultimo_tamizaje: null }]),
  };

  it("«Nueva consulta» lleva al buscador, que abre la consulta clínica (M04) del paciente", async () => {
    conLista(() => respuestaJson(200, pagina(CONSULTAS)), RECIENTES);
    renderizar("/consultas");
    fireEvent.click(await screen.findByRole("link", { name: "Nueva consulta" }));
    expect(await screen.findByRole("heading", { level: 1, name: "Nueva consulta" })).toBeInTheDocument();
    const migas = screen.getByRole("navigation", { name: "Ruta de navegación" });
    expect(within(migas).getByRole("link", { name: "Historial de consultas" })).toHaveAttribute("href", "/consultas");
    fireEvent.click(await screen.findByRole("button", { name: `Nueva consulta: ${FICHA.nombres_apellidos}` }));
    // M04: el título es el nombre del paciente y está el formulario de la pregunta.
    expect(await screen.findByRole("heading", { level: 1, name: FICHA.nombres_apellidos })).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "Enviar" })).toBeInTheDocument();
  });

  it("conserva la búsqueda y «Ver historial» (M08)", async () => {
    const f = conLista(() => respuestaJson(200, pagina([])), {
      ...RECIENTES,
      "POST /api/pacientes/buscar": () => respuestaJson(200, [{ id_paciente: ID_PACIENTE, nombres_apellidos: FICHA.nombres_apellidos,
        numero_hc: FICHA.numero_hc, sexo: "M", edad_meses_actual: 16, ultimo_tamizaje: null }]),
    }).f;
    renderizar("/consultas/nueva");
    fireEvent.change(await screen.findByRole("textbox", { name: "Buscar paciente" }), { target: { value: "Ficticio" } });
    fireEvent.click(screen.getByRole("button", { name: "Buscar" }));
    expect(await screen.findByRole("heading", { name: "Resultados de la búsqueda (1)" })).toBeInTheDocument();
    expect(f.mock.calls.some(([r, i]) => r === "/api/pacientes/buscar" && i?.method === "POST")).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: `Ver historial: ${FICHA.nombres_apellidos}` }));
    expect(await screen.findByRole("heading", { name: "Evaluaciones realizadas" })).toBeInTheDocument();
  });

  it("un rol sin REALIZAR_CONSULTA no entra a /consultas ni a /consultas/nueva", async () => {
    for (const ruta of ["/consultas", "/consultas/nueva"]) {
      const admin = { ...USUARIO, nombre_completo: "Administrador Ficticio", rol: "Administrador", permisos: ["ADMINISTRAR_USUARIOS"] };
      const f = simularBackend({ "GET /api/auth/me": () => respuestaJson(200, admin) });
      const vista = renderizar(ruta);
      // Vuelve al inicio, sin pedir la lista ni mostrar la pantalla.
      expect(await screen.findByRole("heading", { level: 1, name: "Hola, Administrador Ficticio" })).toBeInTheDocument();
      expect(screen.queryByRole("heading", { level: 1, name: /Historial de consultas|Nueva consulta/ })).not.toBeInTheDocument();
      expect(f.mock.calls.some(([r]) => String(r).startsWith("/api/consultas"))).toBe(false);
      vista.unmount();
    }
  });
});

// ---------------------------------------------------------------------------
// M05 · «Registrada por» (P12)
// ---------------------------------------------------------------------------
describe("M05 · Registrada por", () => {
  it("muestra el nombre que devuelve el backend, aunque no sea el usuario de la sesión", async () => {
    const resultado = resultadoFixture("VERIFICADA");
    resultado.decision = { id_decision: "d-1", id_usuario: "u-otra", tipo_decision: "ACEPTA_RECOMENDACION", nota: null,
                           fecha_registro: "2026-11-10T11:00:00-05:00", registrada_por: "Dr. Profesional Ficticio" };
    resultado.opciones_decision = [];
    simularBackend({ [GET_RESULTADO]: () => respuestaJson(200, resultado) });
    renderizar(`/consultas/${ID_CONSULTA}`);
    const seccion = await screen.findByRole("region", { name: "Decisión clínica registrada" });
    const fila = within(seccion).getByText("Registrada por").closest("div")!;
    expect(fila).toHaveTextContent("Dr. Profesional Ficticio");
    expect(seccion).not.toHaveTextContent(USUARIO.nombre_completo);
  });

  it("sin registrada_por (datos anteriores) sigue mostrando al usuario de la sesión", async () => {
    const resultado = resultadoFixture("VERIFICADA");
    resultado.decision = { id_decision: "d-1", id_usuario: USUARIO.id_usuario, tipo_decision: "ACEPTA_RECOMENDACION", nota: null,
                           fecha_registro: "2026-11-10T11:00:00-05:00" };
    resultado.opciones_decision = [];
    simularBackend({ [GET_RESULTADO]: () => respuestaJson(200, resultado) });
    renderizar(`/consultas/${ID_CONSULTA}`);
    const seccion = await screen.findByRole("region", { name: "Decisión clínica registrada" });
    expect(within(seccion).getByText("Registrada por").closest("div")).toHaveTextContent(USUARIO.nombre_completo);
  });
});
