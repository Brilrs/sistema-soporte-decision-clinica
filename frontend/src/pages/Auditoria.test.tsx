// Pruebas de la parte D2 del Sprint 3: M13 «Auditoría y trazabilidad» (/admin/auditoria) y el detalle
// de una consulta (/admin/auditoria/:id). Fetch simulado con los fixtures de la parte D1
// (src/__fixtures__/auditoria_*.json, generados por el backend); sin API real ni modelo de lenguaje.
// Las respuestas no traen pacientes: el sexo y la edad solo aparecen dentro de la solicitud del fixture.
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import { limpiarDetalle, limpiarIndicadores, limpiarPagina } from "../api/auditoria";
import { guardarToken } from "../api/cliente";
import type { ConsultaAuditada, DetalleAuditoria, PaginaAuditoria } from "../api/tipos_auditoria";
import { AuthProvider } from "../auth/AuthContext";
import { CONSULTA_ANGOSTA } from "../components/Layout";
import { NOTA_SIN_IDENTIFICADORES, NOTA_SIN_PRUEBAS } from "../components/auditoria/formato";
import {
  GET_AUDITORIA_CONSULTAS,
  GET_AUDITORIA_INDICADORES,
  USUARIO,
  USUARIO_AUDITOR,
  detalleAuditoriaFixture,
  indicadoresAuditoriaFixture,
  paginaAuditoriaFixture,
  respuestaJson,
  simularBackend,
} from "../pruebas/simulador";
import { fechaHora } from "../utilidades/formato";

const ID_DETALLE = "00000000-0000-4000-8000-000000000001";
const GET_DETALLE = `GET /api/auditoria/consultas/${ID_DETALLE}`;
// Campos de identidad que el servidor nunca debería enviar: si llegaran, la pantalla no los muestra.
const IDENTIDAD = { nombres_apellidos: "Nombre Secreto Paciente", dni: "99887766", numero_hc: "HC-SECRETA-77",
                    fecha_nacimiento: "2024-01-31" };

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

type Rutas = Parameters<typeof simularBackend>[0];

// Backend de M13 con el usuario auditor; guarda las URL de la lista pedidas.
function backend({ pagina = paginaAuditoriaFixture() as PaginaAuditoria | (() => Response), extra = {} as Rutas,
                   usuario = USUARIO_AUDITOR as object } = {}) {
  const pedidas: URL[] = [];
  const f = simularBackend({
    "GET /api/auth/me": () => respuestaJson(200, usuario),
    [GET_AUDITORIA_INDICADORES]: () => respuestaJson(200, indicadoresAuditoriaFixture()),
    [GET_AUDITORIA_CONSULTAS]: (_i, url) => {
      pedidas.push(url);
      return typeof pagina === "function" ? pagina() : respuestaJson(200, pagina);
    },
    [GET_DETALLE]: () => respuestaJson(200, detalleAuditoriaFixture()),
    ...extra,
  });
  return { f, pedidas, ultima: () => pedidas[pedidas.length - 1].searchParams };
}

function simularAncho(angosto: boolean) {
  const lista = { matches: angosto, media: CONSULTA_ANGOSTA, addEventListener: vi.fn(), removeEventListener: vi.fn() };
  Object.defineProperty(window, "matchMedia", { configurable: true, writable: true, value: () => lista });
}

afterEach(() => {
  delete (window as { matchMedia?: unknown }).matchMedia;
});

async function tablaLista() {
  return screen.findByRole("region", { name: "Consultas auditadas" });
}

// ---------------------------------------------------------------------------
// Indicadores
// ---------------------------------------------------------------------------
describe("M13 · indicadores", () => {
  it("muestra los indicadores de 30 días, el periodo y que no incluyen consultas de prueba", async () => {
    backend();
    renderizar("/admin/auditoria");
    expect(await screen.findByRole("heading", { level: 1, name: "Auditoría y trazabilidad" })).toBeInTheDocument();
    const ind = indicadoresAuditoriaFixture();
    expect(await screen.findByText(NOTA_SIN_PRUEBAS)).toBeInTheDocument();
    expect(screen.getByText(new RegExp(`Del ${fechaHora(ind.desde)} al ${fechaHora(ind.hasta)}`))).toBeInTheDocument();
    const seccion = screen.getByRole("region", { name: "Últimos 30 días" });
    const tarjeta = (s: HTMLElement, titulo: string) => within(s).getByText(titulo, { selector: ".indicador__titulo" }).parentElement;
    expect(tarjeta(seccion, "Consultas (30 días)")).toHaveTextContent(`${ind.consultas}`);
    expect(tarjeta(seccion, "Verificadas")).toHaveTextContent("33.3 %");
    expect(tarjeta(seccion, "Evidencia insuficiente")).toHaveTextContent("16.7 %");
    expect(tarjeta(seccion, "Con reintento")).toHaveTextContent("16.7 %");
    expect(tarjeta(seccion, "Tiempo p50")).toHaveTextContent("6.7 s");
    expect(tarjeta(seccion, "Tiempo p90")).toHaveTextContent("23.2 s");
    expect(tarjeta(seccion, "Bloqueadas y errores")).toHaveTextContent("1 · 1");
    expect(tarjeta(seccion, "Costo de API")).toHaveTextContent("US$ 0.08");
    // Desglose por estado con texto, no solo color.
    const estados = within(seccion).getByRole("list", { name: "Consultas por estado" });
    expect(within(estados).getByText("Verificada")).toBeInTheDocument();
    expect(within(estados).getByLabelText("Solicitud bloqueada: 1")).toBeInTheDocument();
  });

  it("carga, error con «Reintentar» y «Sin datos» sin consultas", async () => {
    let fallar = true;
    let soltar!: () => void;
    backend({ extra: { [GET_AUDITORIA_INDICADORES]: () => fallar
      ? new Promise<Response>((r) => { soltar = () => r(respuestaJson(500, { detail: "Error interno del servidor" })); })
      : respuestaJson(200, { ...indicadoresAuditoriaFixture(), consultas: 0 }) } });
    renderizar("/admin/auditoria");
    const cargando = await screen.findByText("Cargando indicadores…");
    expect(cargando).toHaveAttribute("aria-live", "polite");
    soltar();
    const alerta = (await screen.findByText(/No se pudieron cargar los indicadores/)).closest("[role=alert]") as HTMLElement;
    fallar = false;
    fireEvent.click(within(alerta).getByRole("button", { name: "Reintentar" }));
    expect(await screen.findByText("Sin datos: no hubo consultas en los últimos 30 días.")).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// Lista
// ---------------------------------------------------------------------------
describe("M13 · lista de consultas", () => {
  it("tabla con sus columnas, la etiqueta «Prueba» y «Con reintento»", async () => {
    backend();
    renderizar("/admin/auditoria");
    const tabla = await tablaLista();
    const encabezados = within(tabla).getAllByRole("columnheader").map((th) => th.textContent);
    expect(encabezados).toEqual(["Fecha", "Usuario", "Resultado", "Intentos", "Tiempo", "Modelo", "Tokens", "Costo", "Acciones"]);
    const filas = within(tabla).getAllByRole("row").slice(1);
    const fixture = paginaAuditoriaFixture().consultas;
    expect(filas).toHaveLength(fixture.length);
    const real = filas[0];
    expect(real).toHaveTextContent("enf.rojas");
    expect(real).toHaveTextContent("claude-sonnet-5-5 · prompt v1.1");
    expect(real).toHaveTextContent("Con reintento");
    expect(real).toHaveTextContent("14.8 s");
    expect(real).toHaveTextContent("US$ 0.042");
    expect(within(real).queryByText("Prueba")).not.toBeInTheDocument();
    const prueba = filas[fixture.findIndex((c) => c.modo_prueba)];
    expect(within(prueba).getByText("Prueba")).toHaveClass("etiqueta", "etiqueta--prueba");
    expect(screen.getByText(`Mostrando 1 a ${fixture.length} de ${fixture.length} consultas`)).toBeInTheDocument();
  });

  it("debajo de 800 px muestra tarjetas con los mismos datos", async () => {
    simularAncho(true);
    backend();
    renderizar("/admin/auditoria");
    const lista = await screen.findByRole("list", { name: "Consultas auditadas" });
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(within(lista).getAllByRole("listitem")).toHaveLength(paginaAuditoriaFixture().consultas.length);
    expect(within(lista).getAllByText("Prueba")).toHaveLength(1);
    expect(within(lista).getAllByRole("link", { name: /^Ver el detalle de la consulta de/ })[0]).toHaveTextContent("Ver detalle");
  });

  it("por omisión no pide las de prueba; el interruptor pide incluir_pruebas=true y vuelve a la página 1", async () => {
    const b = backend();
    renderizar("/admin/auditoria?pagina=2");
    await tablaLista();
    expect(b.ultima().has("incluir_pruebas")).toBe(false);
    expect(b.ultima().get("desplazamiento")).toBe("20");
    const interruptor = screen.getByRole("switch", { name: "Incluir consultas de prueba" });
    expect(interruptor).not.toBeChecked();
    fireEvent.click(interruptor);
    await waitFor(() => expect(b.ultima().get("incluir_pruebas")).toBe("true"));
    expect(b.ultima().get("desplazamiento")).toBe("0");
    expect(screen.getByRole("switch", { name: "Incluir consultas de prueba" })).toBeChecked();
  });

  it("lee los filtros y la página de la dirección y los aplica al pedir la lista", async () => {
    const b = backend();
    renderizar("/admin/auditoria?estado=ERROR&desde=2026-10-01&hasta=2026-10-20&pruebas=1&pagina=3");
    await tablaLista();
    const p = b.ultima();
    expect([p.get("estado"), p.get("fecha_desde"), p.get("fecha_hasta"), p.get("incluir_pruebas"), p.get("limite"),
            p.get("desplazamiento")]).toEqual(["ERROR", "2026-10-01", "2026-10-20", "true", "20", "40"]);
    expect(screen.getByLabelText("Estado")).toHaveValue("ERROR");
    expect(screen.getByLabelText("Desde")).toHaveValue("2026-10-01");
    expect(screen.getByRole("switch", { name: "Incluir consultas de prueba" })).toBeChecked();
  });

  it("filtrar envía el estado y las fechas, y rechaza «Hasta» anterior a «Desde»", async () => {
    const b = backend();
    renderizar("/admin/auditoria");
    await tablaLista();
    fireEvent.change(screen.getByLabelText("Desde"), { target: { value: "2026-10-20" } });
    fireEvent.change(screen.getByLabelText("Hasta"), { target: { value: "2026-10-01" } });
    fireEvent.click(screen.getByRole("button", { name: "Filtrar" }));
    expect(await screen.findByText("La fecha «Hasta» no puede ser anterior a «Desde».")).toBeInTheDocument();
    const pedidasAntes = b.pedidas.length;
    fireEvent.change(screen.getByLabelText("Hasta"), { target: { value: "2026-10-21" } });
    fireEvent.change(screen.getByLabelText("Estado"), { target: { value: "VERIFICADA" } });
    fireEvent.click(screen.getByRole("button", { name: "Filtrar" }));
    await waitFor(() => expect(b.pedidas.length).toBeGreaterThan(pedidasAntes));
    expect([b.ultima().get("estado"), b.ultima().get("fecha_desde"), b.ultima().get("fecha_hasta")])
      .toEqual(["VERIFICADA", "2026-10-20", "2026-10-21"]);
  });

  it("paginación de 20 con el total", async () => {
    const base = paginaAuditoriaFixture();
    const b = backend({ pagina: { ...base, total: 45 } });
    renderizar("/admin/auditoria");
    await tablaLista();
    const nav = screen.getByRole("navigation", { name: "Paginación de la auditoría" });
    expect(nav).toHaveTextContent("Página 1 de 3");
    fireEvent.click(within(nav).getByRole("button", { name: "Siguiente" }));
    await waitFor(() => expect(b.ultima().get("desplazamiento")).toBe("20"));
  });

  it("carga, vacío y error con «Reintentar»", async () => {
    let respuesta: () => Response = () => respuestaJson(500, { detail: "Error interno del servidor" });
    backend({ pagina: () => respuesta() });
    renderizar("/admin/auditoria");
    expect(await screen.findByText("Cargando consultas…")).toHaveAttribute("aria-live", "polite");
    const alerta = (await screen.findByText(/No se pudieron cargar las consultas/)).closest("[role=alert]") as HTMLElement;
    respuesta = () => respuestaJson(200, { total: 0, limite: 20, desplazamiento: 0, incluir_pruebas: false, consultas: [] });
    fireEvent.click(within(alerta).getByRole("button", { name: "Reintentar" }));
    expect(await screen.findByText("Aún no hay consultas registradas.")).toBeInTheDocument();
  });

  it("un 403 del servidor se muestra como error de la lista", async () => {
    backend({ pagina: () => respuestaJson(403, { detail: "Su rol no tiene el permiso VER_AUDITORIA" }) });
    renderizar("/admin/auditoria");
    expect(await screen.findByText(/No se pudieron cargar las consultas. Su rol no tiene el permiso VER_AUDITORIA/))
      .toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// Detalle
// ---------------------------------------------------------------------------
describe("M13 · detalle de una consulta", () => {
  it("abre el detalle desde la lista y vuelve con los filtros y la página", async () => {
    const b = backend();
    renderizar("/admin/auditoria?estado=VERIFICADA&pruebas=1&pagina=2");
    const tabla = await tablaLista();
    fireEvent.click(within(tabla).getAllByRole("link", { name: /^Ver el detalle de la consulta de enf\.rojas/ })[0]);
    expect(await screen.findByRole("heading", { level: 1, name: /^Consulta del / })).toBeInTheDocument();
    const antes = b.pedidas.length;
    fireEvent.click(screen.getByRole("link", { name: "Volver a la auditoría" }));
    await tablaLista();
    expect(b.pedidas.length).toBe(antes + 1);
    expect([b.ultima().get("estado"), b.ultima().get("incluir_pruebas"), b.ultima().get("desplazamiento")])
      .toEqual(["VERIFICADA", "true", "20"]);
    expect(screen.getByRole("switch", { name: "Incluir consultas de prueba" })).toBeChecked();
  });

  it("muestra el resumen, las verificaciones, los fragmentos con su origen y la solicitud con su nota", async () => {
    backend();
    renderizar(`/admin/auditoria/${ID_DETALLE}`);
    const d = detalleAuditoriaFixture();
    expect(await screen.findByRole("heading", { level: 1, name: `Consulta del ${fechaHora(d.fecha_hora_inicio)}` }))
      .toBeInTheDocument();
    expect(screen.queryByText("Prueba")).not.toBeInTheDocument();
    expect(screen.getByText("2 (con reintento)")).toBeInTheDocument();
    const intento2 = screen.getByRole("region", { name: "Intento 2 · Búsqueda ampliada" });
    expect(within(intento2).getByText("claude-sonnet-5-5")).toBeInTheDocument();
    expect(within(intento2).getByText("v1.1")).toBeInTheDocument();
    expect(within(intento2).getByText("5,020 entrada · 392 salida · 12 razonamiento")).toBeInTheDocument();
    expect(within(intento2).getByText("0.412 frente a 0.150")).toBeInTheDocument();
    expect(within(intento2).getByText("Aprobado: la solicitud no tenía identificadores")).toBeInTheDocument();
    for (const nombre of ["6.1 Citas textuales", "6.2 Consistencia y dosis", "6.3 Suficiencia de la evidencia"]) {
      expect(within(intento2).getByText(nombre).parentElement).toHaveTextContent("Cumplido");
    }
    const intento1 = screen.getByRole("region", { name: "Intento 1 · Búsqueda inicial" });
    expect(within(intento1).getByText("6.3 Suficiencia de la evidencia").parentElement).toHaveTextContent("No cumplido");
    const fragmentos = within(intento2).getByRole("region", { name: "Fragmentos enviados en el intento 2" });
    const filas = within(fragmentos).getAllByRole("row").slice(1);
    expect(filas.map((f) => within(f).getByRole("rowheader").textContent)).toEqual(["F-01", "F-02", "F-03"]);
    expect(filas[0]).toHaveTextContent("Reranker");
    expect(filas[0]).toHaveTextContent("0.800");
    expect(filas[2]).toHaveTextContent("Agregado por referencia");
    expect(filas[0]).toHaveTextContent("PRUEBA-C-MINSA");
    const codigo = within(intento2).getByRole("region", { name: "Solicitud enviada al modelo en el intento 2" });
    expect(codigo.tagName).toBe("PRE");
    expect(codigo.textContent).toBe(JSON.stringify(d.intentos[1].solicitud_enviada, null, 2));
    expect(within(intento2).getByText(NOTA_SIN_IDENTIFICADORES)).toBeInTheDocument();
  });

  it("solicitud no disponible: bloqueada por el control previo o sin envío al modelo", async () => {
    const d = detalleAuditoriaFixture();
    d.intentos[0] = { ...d.intentos[0], control_identificadores: false, solicitud_enviada: null };
    d.intentos[1] = { ...d.intentos[1], control_identificadores: null, solicitud_enviada: null, modelo_llm: null };
    backend({ extra: { [GET_DETALLE]: () => respuestaJson(200, d) } });
    renderizar(`/admin/auditoria/${ID_DETALLE}`);
    const intento1 = await screen.findByRole("region", { name: "Intento 1 · Búsqueda inicial" });
    expect(within(intento1).getByText(/el control previo encontró posibles identificadores y bloqueó la solicitud/))
      .toBeInTheDocument();
    expect(within(intento1).getByText("Bloqueado: la solicitud no se envió")).toBeInTheDocument();
    const intento2 = screen.getByRole("region", { name: "Intento 2 · Búsqueda ampliada" });
    expect(within(intento2).getByText(/en este intento no se envió una solicitud al modelo/)).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: /^Solicitud enviada al modelo/ })).not.toBeInTheDocument();
    expect(screen.queryByText(NOTA_SIN_IDENTIFICADORES)).not.toBeInTheDocument();
  });

  it("una consulta de prueba va marcada; una sin intentos lo explica; un 404 da el mensaje", async () => {
    const prueba: DetalleAuditoria = { ...detalleAuditoriaFixture(), modo_prueba: true };
    backend({ extra: { [GET_DETALLE]: () => respuestaJson(200, prueba) } });
    const vista = renderizar(`/admin/auditoria/${ID_DETALLE}`);
    expect(await screen.findByText("Prueba")).toHaveClass("etiqueta--prueba");
    expect(screen.getByText(/Consulta de prueba: la respuesta la generó el simulador/)).toBeInTheDocument();
    vista.unmount();
    backend({ extra: { [GET_DETALLE]: () => respuestaJson(200, { ...prueba, modo_prueba: false, intentos: [] }) } });
    const vista2 = renderizar(`/admin/auditoria/${ID_DETALLE}`);
    expect(await screen.findByText(/no llegó a la búsqueda ni al modelo de lenguaje/)).toBeInTheDocument();
    vista2.unmount();
    backend({ extra: { [GET_DETALLE]: () => respuestaJson(404, { detail: "La consulta no existe" }) } });
    renderizar(`/admin/auditoria/${ID_DETALLE}`);
    expect(await screen.findByRole("alert")).toHaveTextContent("La consulta no existe");
    expect(screen.getByRole("link", { name: "Volver a la auditoría" })).toHaveAttribute("href", "/admin/auditoria");
  });
});

// ---------------------------------------------------------------------------
// Permisos, menú y seguridad de la pantalla
// ---------------------------------------------------------------------------
describe("M13 · permisos y seguridad", () => {
  it.each([
    ["Enfermera CRED", ["REGISTRAR_PACIENTE", "REALIZAR_CONSULTA", "EXPORTAR_REPORTE"]],
    ["Médico", ["REALIZAR_CONSULTA", "EXPORTAR_REPORTE"]],
    ["Nutricionista", ["REALIZAR_CONSULTA", "EXPORTAR_REPORTE"]],
  ])("%s sin VER_AUDITORIA vuelve al inicio, sin «Auditoría» en el menú y sin llamar a la API", async (rol, permisos) => {
    for (const ruta of ["/admin/auditoria", `/admin/auditoria/${ID_DETALLE}`]) {
      const usuario = { ...USUARIO, rol, nombre_completo: `Usuaria ${rol}`, permisos };
      const { f } = backend({ usuario });
      const vista = renderizar(ruta);
      expect(await screen.findByRole("heading", { level: 1, name: `Hola, Usuaria ${rol}` })).toBeInTheDocument();
      expect(screen.queryByRole("link", { name: "Auditoría" })).not.toBeInTheDocument();
      expect(f.mock.calls.some(([r]) => String(r).startsWith("/api/auditoria"))).toBe(false);
      vista.unmount();
    }
  });

  it("el menú muestra «Auditoría» con el permiso", async () => {
    backend();
    renderizar("/");
    expect(await screen.findByRole("link", { name: "Auditoría" })).toHaveAttribute("href", "/admin/auditoria");
  });

  it("un campo de identidad inesperado del servidor no se muestra en la lista, los indicadores ni el detalle", async () => {
    const pagina = paginaAuditoriaFixture();
    pagina.consultas = pagina.consultas.map((c) => ({ ...c, ...IDENTIDAD }) as ConsultaAuditada);
    const d = detalleAuditoriaFixture() as DetalleAuditoria & Record<string, unknown>;
    Object.assign(d, IDENTIDAD);
    d.intentos = d.intentos.map((i) => ({ ...i, ...IDENTIDAD, fragmentos: i.fragmentos.map((x) => ({ ...x, ...IDENTIDAD })) }));
    backend({ pagina, extra: {
      [GET_AUDITORIA_INDICADORES]: () => respuestaJson(200, { ...indicadoresAuditoriaFixture(), ...IDENTIDAD }),
      [GET_DETALLE]: () => respuestaJson(200, d) } });
    const vista = renderizar("/admin/auditoria");
    await tablaLista();
    await screen.findByText(NOTA_SIN_PRUEBAS);
    for (const valor of Object.values(IDENTIDAD)) expect(document.body.textContent).not.toContain(valor);
    vista.unmount();
    renderizar(`/admin/auditoria/${ID_DETALLE}`);
    await screen.findByRole("region", { name: "Intento 2 · Búsqueda ampliada" });
    for (const valor of Object.values(IDENTIDAD)) expect(document.body.textContent).not.toContain(valor);
  });

  it("las respuestas se reducen a los campos conocidos", () => {
    const d = limpiarDetalle({ ...detalleAuditoriaFixture(), ...IDENTIDAD });
    expect(Object.keys(d)).not.toContain("nombres_apellidos");
    expect(JSON.stringify(limpiarPagina({ ...paginaAuditoriaFixture(), consultas: [{ ...IDENTIDAD }] }))).not.toContain("Secret");
    expect(JSON.stringify(limpiarIndicadores({ ...indicadoresAuditoriaFixture(), ...IDENTIDAD }))).not.toContain("Secret");
  });

  it("solo llama a las rutas de auditoría y no guarda nada en el navegador", async () => {
    localStorage.clear();
    sessionStorage.clear();
    const { f } = backend();
    renderizar("/admin/auditoria");
    const tabla = await tablaLista();
    fireEvent.click(within(tabla).getAllByRole("link", { name: /^Ver el detalle/ })[0]);
    await screen.findByRole("region", { name: "Intento 2 · Búsqueda ampliada" });
    const rutas = f.mock.calls.map(([r]) => String(r)).filter((r) => r !== "/api/auth/me");
    expect(rutas.length).toBeGreaterThanOrEqual(3);
    expect(rutas.every((r) => r.startsWith("/api/auditoria/"))).toBe(true);
    expect(localStorage.length).toBe(0);
    expect(Object.keys(sessionStorage)).toEqual(["cdss.token"]);
  });
});
