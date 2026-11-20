// Pruebas de M11 · Base de conocimiento (parte F2c): tabla con las 4 guías reales, estados de
// carga, vacío y error, acceso solo con ADMINISTRAR_GUIAS, formulario de carga (validaciones del
// cliente, nivel 1 deshabilitado y cada error de la API junto a su campo), avance de la indexación
// con temporizadores falsos, reintento, detalle y «Retirar» deshabilitado. Fetch simulado con las
// respuestas reales de la API (src/pruebas/conocimiento); sin API real.
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import { guardarToken } from "../api/cliente";
import type { Documento, Trabajo } from "../api/conocimiento";
import { AuthProvider } from "../auth/AuthContext";
import { INTERVALO_MS } from "../components/conocimiento/useTrabajosActivos";
import { AVISO_P14, NOTA_NIVEL_1, NOTA_OBSOLETAS, NOTA_RETIRAR } from "../components/conocimiento/textos";
import {
  ADMIN, DETALLE_NTS213, DOCUMENTOS, ID_NUEVA, MENSAJE_ERROR_INDEXADOR, TITULO_NUEVA, guiaEnError, guiaNueva, trabajo,
} from "../pruebas/conocimiento";
import { USUARIO, respuestaJson, simularBackend } from "../pruebas/simulador";
import { NOMBRE_SISTEMA } from "../utilidades/useTituloPagina";

const RUTA = "/admin/conocimiento";
const GET_DOCUMENTOS = "GET /api/conocimiento/documentos";
const GET_ACTIVOS = "GET /api/conocimiento/trabajos?activos=true";
const POST_CARGAR = "POST /api/conocimiento/documentos";
type Rutas = Parameters<typeof simularBackend>[0];

function renderizar(rutas: Rutas = {}, usuario: object = ADMIN) {
  const fetchFalso = simularBackend({
    "GET /api/auth/me": () => respuestaJson(200, usuario),
    [GET_DOCUMENTOS]: () => respuestaJson(200, DOCUMENTOS()),
    [GET_ACTIVOS]: () => respuestaJson(200, []),
    ...rutas,
  });
  guardarToken("token-de-prueba");
  render(
    <MemoryRouter initialEntries={[RUTA]}>
      <AuthProvider>
        <App />
      </AuthProvider>
    </MemoryRouter>,
  );
  return fetchFalso;
}

const llamadas = (f: ReturnType<typeof simularBackend>, clave: string) =>
  f.mock.calls.filter(([ruta, init]) => `${init?.method ?? "GET"} ${String(ruta)}` === clave);

// Respuestas en secuencia: la última se repite.
function secuencia(...datos: unknown[]) {
  let i = 0;
  return () => respuestaJson(200, datos[Math.min(i++, datos.length - 1)]);
}

async function tabla() {
  const region = await screen.findByRole("region", { name: "Guías de la base de conocimiento" });
  return { region, filas: () => within(region).getAllByRole("row").slice(1) };
}

afterEach(() => {
  vi.useRealTimers();
  delete (document as { visibilityState?: unknown }).visibilityState;
});

// ---------------------------------------------------------------------------
// Tabla y estados
// ---------------------------------------------------------------------------
describe("M11 · tabla de guías", () => {
  it("muestra las 4 guías con nivel, año, fragmentos, citas y estado, y el título de la pestaña", async () => {
    renderizar();
    const { filas } = await tabla();
    expect(filas()).toHaveLength(4);
    expect(document.title).toBe(`Base de conocimiento · ${NOMBRE_SISTEMA}`);
    const [oms2024, rm429, nts213, oms2016] = filas();
    expect(oms2024).toHaveTextContent("Guideline on haemoglobin cutoffs to define anaemia in individuals and populations");
    expect(oms2024).toHaveTextContent("OMS 2024");
    // Fragmentos vigentes y citas de 30 días (guion si no hay).
    const celdas = (fila: HTMLElement) => within(fila).getAllByRole("cell").map((c) => c.textContent);
    expect(celdas(oms2024).slice(1, 5)).toEqual(["N1 · citable", "2024", "60", "-"]);
    expect(celdas(rm429).slice(3, 5)).toEqual(["14", "20"]);
    expect(celdas(nts213).slice(2, 5)).toEqual(["2024RM 251-2024/MINSA", "83", "133"]);
    expect(celdas(oms2016).slice(2, 5)).toEqual(["2016", "26", "5"]);
    for (const f of filas()) {
      expect(within(f).getByText("Vigente")).toHaveClass("etiqueta--vigente");
      expect(within(f).getByText("Indexada")).toHaveClass("etiqueta--indexacion-COMPLETADA");
    }
    // La versión de indexación no va en la tabla (va en el detalle).
    expect(screen.queryByText("Versión de indexación")).not.toBeInTheDocument();
    expect(screen.getByText(NOTA_OBSOLETAS)).toBeInTheDocument();
  });

  it("los botones nombran la guía; «Retirar» está activo en las vigentes; sin «Reintentar»; nota del retiro", async () => {
    renderizar();
    await tabla();
    expect(screen.getByRole("button", { name: "Ver: NTS 213-MINSA/DGIESP-2024" })).toBeEnabled();
    const retirar = screen.getAllByRole("button", { name: /^Retirar: / });
    expect(retirar).toHaveLength(4);
    for (const b of retirar) {
      expect(b).toBeEnabled();
      expect(b).not.toHaveAttribute("aria-disabled");
      expect(b).toHaveClass("boton--peligro");
    }
    expect(screen.getByText(NOTA_RETIRAR)).toBeInTheDocument();
    expect(screen.queryByText(/Sprint 3/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Reintentar/ })).not.toBeInTheDocument();
  });

  it("guía obsoleta, en cola, indexando y en error: etiquetas, «Retirar» deshabilitado si es obsoleta y «Reintentar» solo en error", async () => {
    const obsoleta: Documento = { ...DOCUMENTOS()[2], id_documento: "obs", codigo_documento: "NTS 134-MINSA/DGIESP-2017", estado: "OBSOLETA" };
    renderizar({ [GET_DOCUMENTOS]: () => respuestaJson(200, [
      guiaNueva(), guiaNueva({ id_documento: "b", titulo: "Otra guía", estado_indexacion: "EN_PROCESO" }),
      { ...guiaEnError(), id_documento: "c", codigo_documento: "LIT-2025" }, obsoleta,
    ]) });
    const { filas } = await tabla();
    const [enCola, indexando, error, vieja] = filas();
    expect(within(enCola).getByText("En cola")).toHaveClass("etiqueta--indexacion-PENDIENTE");
    expect(within(enCola).getByText("N2 · metodológico")).toHaveClass("etiqueta--nivel-2");
    expect(within(indexando).getByText("Indexando")).toHaveClass("etiqueta--indexacion-EN_PROCESO");
    expect(within(error).getByText("Error al indexar")).toHaveClass("etiqueta--indexacion-ERROR");
    expect(within(error).getByRole("button", { name: "Reintentar: LIT-2025" })).toBeEnabled();
    expect(within(vieja).getByText("Obsoleta")).toHaveClass("etiqueta--obsoleta");
    // aria-disabled: se anuncia como no disponible, recibe el foco (para leer la nota) y no hace nada.
    const retirarVieja = within(vieja).getByRole("button", { name: "Retirar: NTS 134-MINSA/DGIESP-2017" });
    expect(retirarVieja).toHaveAttribute("aria-disabled", "true");
    expect(retirarVieja).toHaveAccessibleDescription(NOTA_RETIRAR);
    retirarVieja.focus();
    expect(retirarVieja).toHaveFocus();
    const antes = vi.mocked(fetch).mock.calls.length;
    fireEvent.click(retirarVieja);
    expect(vi.mocked(fetch).mock.calls.length).toBe(antes);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(within(enCola).getByRole("button", { name: `Retirar: ${TITULO_NUEVA}` })).toBeEnabled();
    expect(screen.getAllByRole("button", { name: /^Reintentar/ })).toHaveLength(1);
  });

  it("muestra «Cargando las guías…» mientras llega la lista", async () => {
    renderizar({ [GET_DOCUMENTOS]: () => new Promise<Response>(() => {}) });
    expect(await screen.findByText("Cargando las guías…")).toBeInTheDocument();
  });

  it("sin guías muestra «Aún no hay guías»", async () => {
    renderizar({ [GET_DOCUMENTOS]: () => respuestaJson(200, []) });
    expect(await screen.findByText(/Aún no hay guías/)).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("si la lista falla muestra el error y «Reintentar» la vuelve a pedir", async () => {
    let n = 0;
    const f = renderizar({ [GET_DOCUMENTOS]: () => (n++ === 0
      ? respuestaJson(500, { detail: "Error interno" }) : respuestaJson(200, DOCUMENTOS())) });
    const alerta = await screen.findByRole("alert");
    expect(alerta).toHaveTextContent("No se pudo cargar la lista de guías: Error interno");
    fireEvent.click(within(alerta).getByRole("button", { name: "Reintentar" }));
    const { filas } = await tabla();
    expect(filas()).toHaveLength(4);
    expect(llamadas(f, GET_DOCUMENTOS)).toHaveLength(2);
  });
});

describe("M11 · acceso", () => {
  it.each([
    ["Enfermera CRED", USUARIO.permisos],
    ["Médico", ["REGISTRAR_PACIENTE", "REALIZAR_CONSULTA", "EXPORTAR_REPORTE"]],
    ["Nutricionista", ["REGISTRAR_PACIENTE", "REALIZAR_CONSULTA", "EXPORTAR_REPORTE"]],
    ["Coordinador CRED", ["REALIZAR_CONSULTA", "EXPORTAR_REPORTE", "CONFIGURAR_PARAMETROS", "VER_PARAMETROS", "VER_AUDITORIA"]],
  ])("%s no ve M11: vuelve al inicio sin pedir las guías", async (rol, permisos) => {
    const f = renderizar({}, { ...USUARIO, rol, permisos });
    await waitFor(() => expect(llamadas(f, "GET /api/auth/me").length).toBeGreaterThan(0));
    await waitFor(() => expect(document.title).not.toContain("Base de conocimiento"));
    expect(screen.queryByRole("heading", { name: "Base de conocimiento" })).not.toBeInTheDocument();
    expect(llamadas(f, GET_DOCUMENTOS)).toHaveLength(0);
    expect(screen.queryByRole("link", { name: "Base de conocimiento" })).not.toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// Cargar guía
// ---------------------------------------------------------------------------
function pdf(nombre = "guia.pdf", tamano?: number) {
  const archivo = new File(["%PDF-1.4 contenido"], nombre, { type: "application/pdf" });
  if (tamano !== undefined) Object.defineProperty(archivo, "size", { value: tamano });
  return archivo;
}

async function abrirCarga() {
  await tabla();
  fireEvent.click(screen.getByRole("button", { name: "Cargar guía" }));
  return screen.getByRole("dialog", { name: "Cargar guía clínica (PDF)" });
}

function llenar(ventana: HTMLElement, cambios: Record<string, string> = {}, archivo: File | null = pdf()) {
  const valores: Record<string, string> = {
    "Título": TITULO_NUEVA, "Código (opcional)": "", "Entidad emisora": "OTRA", "Tipo de documento": "LITERATURA",
    "Año de publicación": "2025", "Idioma": "en", "Desde la página": "", "Hasta la página": "", ...cambios,
  };
  if (archivo) fireEvent.change(within(ventana).getByLabelText(/Archivo PDF/), { target: { files: [archivo] } });
  for (const [etiqueta, valor] of Object.entries(valores)) {
    fireEvent.change(within(ventana).getByLabelText(new RegExp(`^${etiqueta.replace(/[()]/g, "\\$&")}`)), { target: { value: valor } });
  }
}

const enviar = (ventana: HTMLElement) => fireEvent.click(within(ventana).getByRole("button", { name: "Cargar guía" }));

describe("M11 · cargar guía", () => {
  it("abre la ventana con el aviso de P14, el nivel 1 deshabilitado con su nota y el nivel 2 elegido", async () => {
    renderizar();
    const ventana = await abrirCarga();
    expect(within(ventana).getByText(AVISO_P14)).toBeInTheDocument();
    // Texto vigente desde la parte J: ya no pide cargar fuera del horario ni anuncia minutos de demora.
    expect(ventana).toHaveTextContent("Indexar una guía tarda unos minutos. Mientras tanto, las consultas pueden ir algo más lentas.");
    expect(ventana).not.toHaveTextContent(/varios minutos|horario de atención/);
    expect(within(ventana).getByRole("button", { name: "Cargar guía" })).toHaveAccessibleDescription(AVISO_P14);
    const n1 = within(ventana).getByRole("radio", { name: "Nivel 1 · citable" });
    expect(n1).toBeDisabled();
    expect(n1).toHaveAccessibleDescription(NOTA_NIVEL_1);
    expect(within(ventana).getByRole("radio", { name: "Nivel 2 · metodológico" })).toBeChecked();
    expect(ventana).not.toHaveTextContent(/MeSH|UMLS/);
    // El foco entra en la ventana y Esc la cierra devolviéndolo a «Cargar guía».
    expect(ventana).toContainElement(document.activeElement as HTMLElement);
    fireEvent.keyDown(ventana, { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cargar guía" })).toHaveFocus();
  });

  it("valida en el cliente lo evidente, marca cada campo y no envía nada", async () => {
    const f = renderizar();
    const ventana = await abrirCarga();
    enviar(ventana);
    const archivo = within(ventana).getByLabelText(/Archivo PDF/);
    expect(archivo).toHaveAttribute("aria-invalid", "true");
    expect(archivo).toHaveAccessibleDescription(/Elija el archivo PDF de la guía/);
    expect(within(ventana).getByLabelText(/^Título/)).toHaveAccessibleDescription(/al menos 3 caracteres/);
    expect(within(ventana).getByLabelText(/^Entidad emisora/)).toHaveAccessibleDescription("Elija la entidad emisora.");
    expect(within(ventana).getByLabelText(/^Tipo de documento/)).toHaveAccessibleDescription("Elija el tipo de documento.");
    expect(within(ventana).getByLabelText(/^Año de publicación/)).toHaveAccessibleDescription(/cuatro cifras/);
    await waitFor(() => expect(archivo).toHaveFocus());
    expect(llamadas(f, POST_CARGAR)).toHaveLength(0);
  });

  it.each([
    ["un archivo que no es PDF", { archivo: pdf("guia.docx") }, /Archivo PDF/, "El archivo debe tener la extensión .pdf."],
    ["un PDF de más de 20 MB", { archivo: pdf("grande.pdf", 20 * 1024 * 1024 + 1) }, /Archivo PDF/, "El archivo supera el máximo de 20 MB."],
    ["un año futuro", { cambios: { "Año de publicación": "2999" } }, /^Año de publicación/, /El año debe estar entre 1948 y/],
    ["un año anterior a 1948", { cambios: { "Año de publicación": "1900" } }, /^Año de publicación/, /El año debe estar entre 1948 y/],
    ["solo la página de inicio", { cambios: { "Desde la página": "3" } }, /^Desde la página/, /o deje las dos vacías/],
    ["inicio mayor que fin", { cambios: { "Desde la página": "9", "Hasta la página": "3" } }, /^Desde la página/,
     "La página de inicio no puede ser mayor que la de fin."],
    ["página 0", { cambios: { "Desde la página": "0", "Hasta la página": "3" } }, /^Desde la página/, /desde 1/],
  ] as [string, { archivo?: File; cambios?: Record<string, string> }, RegExp, string | RegExp][])(
    "rechaza %s en el cliente", async (_, { archivo, cambios }, campo, mensaje) => {
    const f = renderizar();
    const ventana = await abrirCarga();
    llenar(ventana, cambios ?? {}, archivo ?? pdf());
    enviar(ventana);
    expect(within(ventana).getByLabelText(campo)).toHaveAccessibleDescription(
      typeof mensaje === "string" ? expect.stringContaining(mensaje) : mensaje);
    expect(llamadas(f, POST_CARGAR)).toHaveLength(0);
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  // Mensajes reales del backend (backend/app/services/conocimiento.py y routes/conocimiento.py).
  const DUPLICADO = "Este archivo ya está cargado como «Norma técnica de salud para la prevención y control de la anemia»";
  const DUPLICADO_RETIRADA = "Este archivo ya está cargado como «Guía de prueba del retiro» y esa guía está retirada";
  const CUPO = "Ya hay 2 indexaciones pendientes o en curso. Espere a que terminen antes de cargar otra guía: indexar varias a la vez satura el servicio de modelos.";
  const NIVEL = "Desde la pantalla solo se cargan guías de nivel 2 (metodológicas). Las guías de nivel 1 (citables) se cargan por línea de comandos, con sus transcripciones verificadas.";
  it.each([
    ["409 duplicado, con el título existente", 409, DUPLICADO, /Archivo PDF/, DUPLICADO],
    ["409 duplicado de una guía retirada (parte Z)", 409, DUPLICADO_RETIRADA, /Archivo PDF/, DUPLICADO_RETIRADA],
    ["413 tamaño", 413, "El archivo supera el máximo de 20 MB", /Archivo PDF/, "El archivo supera el máximo de 20 MB."],
    ["415 extensión", 415, "El archivo debe tener la extensión .pdf", /Archivo PDF/, "El archivo debe tener la extensión .pdf"],
    ["415 firma", 415, "El archivo no es un PDF válido (no empieza con %PDF-)", /Archivo PDF/, "El archivo no es un PDF válido (no empieza con %PDF-)"],
    ["422 metadato con mensaje en inglés de Pydantic", 422, "Metadatos no válidos. titulo: String should have at least 3 characters",
     /^Título/, "El servidor no aceptó este valor. Revíselo."],
    ["422 año con mensaje propio", 422, "Metadatos no válidos. anio_publicacion: el año de publicación no puede ser posterior al actual",
     /^Año de publicación/, "El año de publicación no puede ser posterior al actual."],
    ["422 de la pareja de páginas", 422, "Metadatos no válidos. datos: la página de inicio del cuerpo no puede ser mayor que la de fin",
     /^Desde la página/, "La página de inicio del cuerpo no puede ser mayor que la de fin."],
    ["422 nivel 1", 422, NIVEL, /Nivel 2 · metodológico/, NIVEL],
  ])("muestra el %s junto a su campo y deja la ventana abierta", async (_, codigo, detalle, campo, mensaje) => {
    renderizar({ [POST_CARGAR]: () => respuestaJson(codigo, { detail: detalle }) });
    const ventana = await abrirCarga();
    llenar(ventana);
    enviar(ventana);
    const control = within(ventana).getByLabelText(campo);
    await waitFor(() => expect(control).toHaveAccessibleDescription(expect.stringContaining(mensaje)));
    if (!(control instanceof HTMLInputElement && control.type === "radio")) expect(control).toHaveAttribute("aria-invalid", "true");
    await waitFor(() => expect(control).toHaveFocus());
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(within(ventana).getByRole("button", { name: "Cargar guía" })).toBeEnabled();
  });

  it("muestra el 409 de cupo lleno como aviso general de la ventana", async () => {
    renderizar({ [POST_CARGAR]: () => respuestaJson(409, { detail: CUPO }) });
    const ventana = await abrirCarga();
    llenar(ventana);
    enviar(ventana);
    const alerta = await within(ventana).findByRole("alert");
    expect(alerta).toHaveTextContent(CUPO);
    await waitFor(() => expect(alerta).toHaveFocus());
    expect(within(ventana).getByLabelText(/Archivo PDF/)).not.toHaveAttribute("aria-invalid");
  });

  it("al cargar bien envía el multipart, cierra la ventana, avisa y empieza a seguir el avance", async () => {
    const nueva = guiaNueva();
    const f = renderizar({
      [GET_DOCUMENTOS]: secuencia(DOCUMENTOS(), [...DOCUMENTOS(), nueva]),
      [GET_ACTIVOS]: secuencia([], [trabajo()]),
      [POST_CARGAR]: () => respuestaJson(201, { documento: nueva, trabajo: trabajo() }),
    });
    const ventana = await abrirCarga();
    llenar(ventana, { "Código (opcional)": "  REV-2025  ", "Desde la página": "2", "Hasta la página": "40" });
    enviar(ventana);
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(await screen.findByText(`«${TITULO_NUEVA}» se cargó y quedó en cola para indexarse.`)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cargar guía" })).toHaveFocus();
    const [[, init]] = llamadas(f, POST_CARGAR);
    const cuerpo = init?.body as FormData;
    expect(cuerpo).toBeInstanceOf(FormData);
    expect((cuerpo.get("archivo") as File).name).toBe("guia.pdf");
    expect(Object.fromEntries([...cuerpo.entries()].filter(([k]) => k !== "archivo"))).toEqual({
      titulo: TITULO_NUEVA, codigo_documento: "REV-2025", entidad_emisora: "OTRA", tipo_documento: "LITERATURA",
      anio_publicacion: "2025", idioma: "en", nivel: "2", pagina_inicio_cuerpo: "2", pagina_fin_cuerpo: "40",
    });
    // El navegador arma el Content-Type del multipart: el cliente no fija application/json.
    expect(new Headers(init?.headers).get("Content-Type")).toBeNull();
    expect(new Headers(init?.headers).get("Authorization")).toBe("Bearer token-de-prueba");
    // Tabla refrescada y avance en pantalla.
    const { filas } = await tabla();
    await waitFor(() => expect(filas()).toHaveLength(5));
    expect(await screen.findByRole("progressbar", { name: `Avance de la indexación de ${TITULO_NUEVA}` })).toBeInTheDocument();
  });

  it("sin páginas del cuerpo no las envía", async () => {
    const f = renderizar({ [POST_CARGAR]: () => respuestaJson(201, { documento: guiaNueva(), trabajo: trabajo() }) });
    const ventana = await abrirCarga();
    llenar(ventana);
    enviar(ventana);
    await waitFor(() => expect(llamadas(f, POST_CARGAR)).toHaveLength(1));
    const cuerpo = llamadas(f, POST_CARGAR)[0][1]?.body as FormData;
    expect(cuerpo.has("pagina_inicio_cuerpo")).toBe(false);
    expect(cuerpo.has("codigo_documento")).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// Avance de la indexación
// ---------------------------------------------------------------------------
const enCurso = (cambios: Partial<Trabajo> = {}) =>
  trabajo({ estado: "EN_CURSO", etapa: "EMBEDDINGS", procesados: 148, total: 240, fecha_inicio: "2026-11-16T15:00:05Z", ...cambios });
const avanzar = (ms: number) => act(async () => { await vi.advanceTimersByTimeAsync(ms); });

describe("M11 · avance de la indexación", () => {
  it("muestra la etapa actual y la barra con «148 de 240 fragmentos»", async () => {
    renderizar({ [GET_ACTIVOS]: () => respuestaJson(200, [enCurso()]) });
    const barra = await screen.findByRole("progressbar", { name: `Avance de la indexación de ${TITULO_NUEVA}` });
    expect(barra).toHaveAttribute("aria-valuenow", "148");
    expect(barra).toHaveAttribute("aria-valuemax", "240");
    expect(barra).toHaveAttribute("aria-valuetext", "148 de 240 fragmentos");
    expect(screen.getByText("148 de 240 fragmentos")).toBeInTheDocument();
    const etapas = within(screen.getByRole("article", { name: `Indexación de ${TITULO_NUEVA}` })).getAllByRole("listitem");
    // Sin el icono (decorativo, aria-hidden): el texto que lee el lector de pantalla.
    expect(etapas.map((e) => e.lastElementChild?.textContent)).toEqual([
      "Extracción: completada", "Fragmentación: completada", "Normalización: completada", "Embeddings: en curso", "Indexación: pendiente",
    ]);
    expect(etapas[3]).toHaveAttribute("aria-current", "step");
  });

  it("un trabajo en cola muestra la barra sin valor y el texto de espera", async () => {
    renderizar({ [GET_ACTIVOS]: () => respuestaJson(200, [trabajo()]) });
    const barra = await screen.findByRole("progressbar");
    expect(barra).not.toHaveAttribute("aria-valuenow");
    expect(barra).toHaveAttribute("aria-valuetext", expect.stringContaining("En cola"));
  });

  it("consulta cada 3 s mientras hay trabajos, anuncia el cambio de etapa y al terminar refresca la tabla y se detiene", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const completada = guiaNueva({ estado_indexacion: "COMPLETADA", fragmentos_vigentes: 37, version_indexacion: 1,
      ultimo_trabajo: { ...enCurso(), estado: "COMPLETADO", etapa: "INDEXACION", procesados: 37, total: 37, fecha_fin: "2026-11-16T15:04:00Z" } });
    const f = renderizar({
      [GET_ACTIVOS]: secuencia([enCurso({ etapa: "FRAGMENTACION", procesados: 0, total: null })], [enCurso()], []),
      [GET_DOCUMENTOS]: secuencia([...DOCUMENTOS(), guiaNueva({ estado_indexacion: "EN_PROCESO" })], [...DOCUMENTOS(), completada]),
    });
    await screen.findByRole("progressbar");
    const anuncio = () => document.querySelector('[aria-live="polite"]')?.textContent;
    expect(anuncio()).toBe(`Indexación de «${TITULO_NUEVA}»: etapa Fragmentación.`);
    expect(llamadas(f, GET_ACTIVOS)).toHaveLength(1);

    await avanzar(INTERVALO_MS);
    expect(llamadas(f, GET_ACTIVOS)).toHaveLength(2);
    await waitFor(() => expect(anuncio()).toBe(`Indexación de «${TITULO_NUEVA}»: etapa Embeddings.`));

    await avanzar(INTERVALO_MS);
    expect(llamadas(f, GET_ACTIVOS)).toHaveLength(3);
    // Terminó: se refresca la tabla y se muestra el resultado.
    await waitFor(() => expect(llamadas(f, GET_DOCUMENTOS)).toHaveLength(2));
    const resultado = await screen.findByRole("article", { name: `Resultado de la indexación de ${TITULO_NUEVA}` });
    expect(resultado).toHaveTextContent(`«${TITULO_NUEVA}» quedó indexada con 37 fragmentos vigentes.`);
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
    await waitFor(() => expect(anuncio()).toBe(`La indexación de «${TITULO_NUEVA}» terminó.`));

    // Sin trabajos activos ya no consulta.
    await avanzar(INTERVALO_MS * 5);
    expect(llamadas(f, GET_ACTIVOS)).toHaveLength(3);
    fireEvent.click(within(resultado).getByRole("button", { name: `Ocultar el resultado de ${TITULO_NUEVA}` }));
    expect(screen.queryByRole("region", { name: "Avance de la indexación" })).not.toBeInTheDocument();
  });

  it("sin trabajos activos al entrar no vuelve a consultar ni muestra la tarjeta", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const f = renderizar();
    await tabla();
    await avanzar(INTERVALO_MS * 4);
    expect(llamadas(f, GET_ACTIVOS)).toHaveLength(1);
    expect(screen.queryByRole("region", { name: "Avance de la indexación" })).not.toBeInTheDocument();
  });

  it("con la pestaña oculta deja de consultar y al volver consulta enseguida", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    let estado: DocumentVisibilityState = "visible";
    Object.defineProperty(document, "visibilityState", { configurable: true, get: () => estado });
    const f = renderizar({ [GET_ACTIVOS]: () => respuestaJson(200, [enCurso()]) });
    await screen.findByRole("progressbar");
    await avanzar(INTERVALO_MS);
    expect(llamadas(f, GET_ACTIVOS)).toHaveLength(2);

    estado = "hidden";
    act(() => { document.dispatchEvent(new Event("visibilitychange")); });
    await avanzar(INTERVALO_MS * 5);
    expect(llamadas(f, GET_ACTIVOS)).toHaveLength(2);

    estado = "visible";
    act(() => { document.dispatchEvent(new Event("visibilitychange")); });
    await waitFor(() => expect(llamadas(f, GET_ACTIVOS)).toHaveLength(3));
    await avanzar(INTERVALO_MS);
    expect(llamadas(f, GET_ACTIVOS)).toHaveLength(4);
  });

  it("un trabajo que termina en ERROR muestra el mensaje y «Reintentar», que lo vuelve a poner en cola", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const f = renderizar({
      [GET_ACTIVOS]: secuencia([enCurso({ etapa: "EXTRACCION", procesados: 0, total: null })], [], [trabajo({ id_trabajo: "t-0002", tipo: "INDEXACION" })]),
      [GET_DOCUMENTOS]: secuencia([...DOCUMENTOS(), guiaNueva({ estado_indexacion: "EN_PROCESO" })], [...DOCUMENTOS(), guiaEnError()],
                                  [...DOCUMENTOS(), guiaNueva()]),
      [`POST /api/conocimiento/documentos/${ID_NUEVA}/reintentar`]: () => respuestaJson(201, { trabajo: trabajo({ id_trabajo: "t-0002" }) }),
    });
    await screen.findByRole("progressbar");
    await avanzar(INTERVALO_MS);
    const resultado = await screen.findByRole("article", { name: `Resultado de la indexación de ${TITULO_NUEVA}` });
    expect(resultado).toHaveTextContent(`No se pudo indexar «${TITULO_NUEVA}».`);
    expect(resultado).toHaveTextContent(MENSAJE_ERROR_INDEXADOR);
    fireEvent.click(within(resultado).getByRole("button", { name: `Reintentar: ${TITULO_NUEVA}` }));
    await waitFor(() => expect(llamadas(f, `POST /api/conocimiento/documentos/${ID_NUEVA}/reintentar`)).toHaveLength(1));
    expect(await screen.findByText(`Se volvió a poner en cola la indexación de «${TITULO_NUEVA}».`)).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByRole("article", { name: /^Resultado de la indexación/ })).not.toBeInTheDocument());
    expect(await screen.findByRole("progressbar")).toHaveAttribute("aria-valuetext", expect.stringContaining("En cola"));
  });
});

// ---------------------------------------------------------------------------
// Reintentar desde la tabla y detalle
// ---------------------------------------------------------------------------
describe("M11 · reintentar y detalle", () => {
  const POST_REINTENTAR = `POST /api/conocimiento/documentos/${ID_NUEVA}/reintentar`;

  it("«Reintentar» de la tabla pide el reintento y refresca", async () => {
    const f = renderizar({
      [GET_DOCUMENTOS]: secuencia([...DOCUMENTOS(), guiaEnError()], [...DOCUMENTOS(), guiaNueva()]),
      [POST_REINTENTAR]: () => respuestaJson(201, { trabajo: trabajo() }),
    });
    await tabla();
    fireEvent.click(screen.getByRole("button", { name: `Reintentar: ${TITULO_NUEVA}` }));
    expect(await screen.findByText(`Se volvió a poner en cola la indexación de «${TITULO_NUEVA}».`)).toBeInTheDocument();
    expect(llamadas(f, POST_REINTENTAR)).toHaveLength(1);
    await waitFor(() => expect(screen.queryByRole("button", { name: `Reintentar: ${TITULO_NUEVA}` })).not.toBeInTheDocument());
    expect(llamadas(f, GET_DOCUMENTOS)).toHaveLength(2);
  });

  it("si el reintento responde 409 muestra el motivo", async () => {
    renderizar({
      [GET_DOCUMENTOS]: () => respuestaJson(200, [...DOCUMENTOS(), guiaEnError()]),
      [POST_REINTENTAR]: () => respuestaJson(409, { detail: "La guía ya tiene una indexación pendiente o en curso" }),
    });
    await tabla();
    fireEvent.click(screen.getByRole("button", { name: `Reintentar: ${TITULO_NUEVA}` }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      `No se pudo reintentar «${TITULO_NUEVA}»: La guía ya tiene una indexación pendiente o en curso`);
  });

  it("«Ver» abre el detalle con metadatos, versiones, trabajos y quién cargó; sin rutas del servidor", async () => {
    const detalle = DETALLE_NTS213();
    renderizar({ [`GET /api/conocimiento/documentos/${detalle.id_documento}`]: () => respuestaJson(200, detalle) });
    await tabla();
    const ver = screen.getByRole("button", { name: "Ver: NTS 213-MINSA/DGIESP-2024" });
    fireEvent.click(ver);
    const ventana = screen.getByRole("dialog", { name: "Norma técnica de salud para la prevención y control de la anemia" });
    const versiones = await within(ventana).findByRole("region", { name: "Versiones de indexación" });
    expect(within(versiones).getAllByRole("row").slice(1).map((r) => r.textContent)).toEqual([
      "510283bge-m3", "41010bge-m3", "3970bge-m3", "2970bge-m3", "1970bge-m3",
    ]);
    const trabajos = within(ventana).getByRole("region", { name: "Historial de trabajos" });
    expect(within(trabajos).getAllByRole("row")).toHaveLength(4);
    expect(trabajos).toHaveTextContent("Reindexación");
    expect(trabajos).toHaveTextContent("Indexación: 102 de 102");
    expect(ventana).toHaveTextContent("Cargada porSistema (carga inicial)");
    expect(ventana).toHaveTextContent("Páginas que se indexan4 a 36");
    expect(ventana).toHaveTextContent("Fecha de publicación08/04/2024");
    expect(ventana).toHaveTextContent("VersiónRM 251-2024/MINSA");
    expect(ventana).toHaveTextContent("Versión de indexación5");
    expect(ventana).not.toHaveTextContent(/local:\/\/|guias_cargadas|\/datos\//);
    fireEvent.keyDown(ventana, { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(ver).toHaveFocus();
  });

  it("si el detalle falla muestra el error con «Reintentar» dentro de la ventana", async () => {
    let n = 0;
    const detalle = DETALLE_NTS213();
    renderizar({ [`GET /api/conocimiento/documentos/${detalle.id_documento}`]: () => (n++ === 0
      ? respuestaJson(500, { detail: "Error interno" }) : respuestaJson(200, detalle)) });
    await tabla();
    fireEvent.click(screen.getByRole("button", { name: "Ver: NTS 213-MINSA/DGIESP-2024" }));
    const ventana = screen.getByRole("dialog");
    fireEvent.click(within(await within(ventana).findByRole("alert")).getByRole("button", { name: "Reintentar" }));
    expect(await within(ventana).findByRole("region", { name: "Versiones de indexación" })).toBeInTheDocument();
  });
});
