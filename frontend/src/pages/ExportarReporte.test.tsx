// Pruebas de la parte C2 del Sprint 3: M09 «Exportar reporte» (/consultas/:id/reporte) y sus entradas
// desde M05, M07, M08 y «Reportes» (/reportes). Fetch simulado con los fixtures de la parte C1
// (src/__fixtures__/reporte_*.json, generados por el backend); sin API real ni modelo de lenguaje.
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import { guardarToken, leerToken } from "../api/cliente";
import type { ConsultaPropia, ResultadoConsulta } from "../api/tipos_consulta";
import type { ReporteListado } from "../api/tipos_reporte";
import { AuthProvider } from "../auth/AuthContext";
import { AVISO_PRUEBA, AVISO_REVISION, AYUDA_REPORTES_ANTERIORES } from "../components/reporte/textos";
import {
  FICHA,
  FICHA_FIXTURE,
  GET_REPORTES,
  GET_RESULTADO,
  GET_VISTA_PREVIA,
  HISTORIAL,
  ID_CONSULTA,
  ID_PACIENTE,
  ID_PACIENTE_FIXTURE,
  POST_REPORTE,
  USUARIO,
  reportesFixture,
  respuestaJson,
  respuestaPdf,
  resultadoFixture,
  simularBackend,
  vistaPreviaFixture,
} from "../pruebas/simulador";

const RUTA_M09 = `/consultas/${ID_CONSULTA}/reporte`;
const OPCIONALES_EXPEDIENTE = "RECOMENDACION,EVIDENCIAS,ADVERTENCIAS,VERIFICACION,DECISION,FIRMA";

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

// Backend de M09: resultado VERIFICADA (consulta de prueba), vista previa según el destino, lista
// y POST. Guarda las URL de la vista previa y cuenta los POST.
function backendM09({ resultado = resultadoFixture("VERIFICADA"), lista = reportesFixture(), extra = {} as Parameters<typeof simularBackend>[0],
                      post = (n: number) => respuestaPdf(`EV-2026-0000${n + 2}`) as Response | Promise<Response> } = {}) {
  const vistas: URL[] = [];
  let posts = 0;
  let listas = 0;
  const generados: ReporteListado[] = [];
  const f = simularBackend({
    // Sexo explícito: no depende del valor por omisión del simulador.
    [`GET /api/pacientes/${ID_PACIENTE_FIXTURE}`]: () => respuestaJson(200, { ...FICHA_FIXTURE, sexo: "F" }),
    [GET_RESULTADO]: () => respuestaJson(200, resultado),
    [GET_VISTA_PREVIA]: (_i, url) => {
      vistas.push(url);
      const destino = url.searchParams.get("destino") === "CUIDADOR" ? "CUIDADOR" : "EXPEDIENTE";
      return respuestaJson(200, { ...vistaPreviaFixture(destino), modo_prueba: resultado.modo_prueba });
    },
    [GET_REPORTES]: () => {
      listas += 1;
      return respuestaJson(200, [...generados, ...lista]);
    },
    [POST_REPORTE]: async (init) => {
      posts += 1;
      const r = await post(posts);
      if (r.status === 201) {
        const cuerpo = JSON.parse(String(init?.body));
        generados.unshift({ numero_reporte: r.headers.get("X-Reporte-Numero")!, destino: cuerpo.destino, secciones: cuerpo.secciones,
                            formato: "PDF", fecha_generacion: "2026-11-18T10:00:00-05:00", hash_documento: r.headers.get("X-Reporte-Hash") });
      }
      return r;
    },
    ...extra,
  });
  return { f, vistas, posts: () => posts, listas: () => listas, parametros: () => vistas.map((u) => u.search) };
}

let crear: ReturnType<typeof vi.fn>;
let liberar: ReturnType<typeof vi.fn>;
let abrir: ReturnType<typeof vi.fn>;
beforeEach(() => {
  let n = 0;
  crear = vi.fn(() => `blob:prueba-${++n}`);
  liberar = vi.fn();
  abrir = vi.fn();
  Object.assign(URL, { createObjectURL: crear, revokeObjectURL: liberar });
  vi.stubGlobal("open", abrir);
});
afterEach(() => vi.unstubAllGlobals());

async function vistaLista() {
  return screen.findByRole("article", { name: "Vista previa del documento" });
}

// ---------------------------------------------------------------------------
// M09: opciones y vista previa
// ---------------------------------------------------------------------------
describe("M09 · opciones y vista previa", () => {
  it("muestra la consulta, el destino, las secciones con las obligatorias bloqueadas y la vista previa", async () => {
    const { parametros } = backendM09();
    renderizar(RUTA_M09);
    expect(await screen.findByRole("heading", { level: 1, name: "Exportar reporte" })).toBeInTheDocument();
    expect(await screen.findByText(FICHA_FIXTURE.nombres_apellidos, { selector: "strong" })).toBeInTheDocument();
    expect(screen.getByText("Verificada")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Volver al resultado" })).toHaveAttribute("href", `/consultas/${ID_CONSULTA}`);

    const destino = screen.getByRole("group", { name: "Destino" });
    expect(within(destino).getByRole("radio", { name: "Expediente clínico" })).toBeChecked();
    expect(within(destino).getByRole("radio", { name: "Entrega al cuidador" })).not.toBeChecked();

    const secciones = screen.getByRole("group", { name: "Incluir en el reporte" });
    for (const nombre of [/Datos del paciente \(obligatoria\)/, /Clasificación y nivel de riesgo \(obligatoria\)/,
                          /La decisión final corresponde al profesional tratante.*\(obligatoria\)/]) {
      const casilla = within(secciones).getByRole("checkbox", { name: nombre });
      expect(casilla).toBeChecked();
      expect(casilla).toBeDisabled();
    }
    expect(within(secciones).getByRole("checkbox", { name: "Evidencias citadas" })).toBeEnabled();

    const hoja = await vistaLista();
    expect(hoja).toHaveTextContent("Reporte de evaluación de anemia infantil");
    expect(hoja).toHaveTextContent("N.° se asigna al generar");
    expect(parametros()).toEqual([`?destino=EXPEDIENTE&secciones=${encodeURIComponent(`PACIENTE,CLASIFICACION,${OPCIONALES_EXPEDIENTE}`)}`]);

    // Lista de reportes emitidos con la ayuda de que no se reentregan.
    const lista = screen.getByRole("region", { name: "Reportes generados de esta consulta" });
    expect(lista).toHaveTextContent(AYUDA_REPORTES_ANTERIORES);
    expect(await within(lista).findAllByRole("listitem")).toHaveLength(2);
  });

  it("las obligatorias no se pueden desmarcar y siempre se piden", async () => {
    const { parametros } = backendM09();
    renderizar(RUTA_M09);
    await vistaLista();
    const paciente = screen.getByRole("checkbox", { name: /Datos del paciente/ });
    fireEvent.click(paciente);
    expect(paciente).toBeChecked();
    fireEvent.click(screen.getByRole("checkbox", { name: "Advertencias" }));
    await waitFor(() => expect(parametros()).toHaveLength(2));
    const ultima = new URLSearchParams(parametros()[1]).get("secciones")!.split(",");
    expect(ultima).toEqual(["PACIENTE", "CLASIFICACION", "RECOMENDACION", "EVIDENCIAS", "VERIFICACION", "DECISION", "FIRMA"]);
  });

  it("al cambiar de destino muestra sus secciones, pide la vista previa y avisa del texto en revisión", async () => {
    const { parametros } = backendM09();
    renderizar(RUTA_M09);
    await vistaLista();
    expect(screen.queryByText(AVISO_REVISION)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("radio", { name: "Entrega al cuidador" }));
    const secciones = screen.getByRole("group", { name: "Incluir en el reporte" });
    expect(within(secciones).queryByRole("checkbox", { name: "Evidencias citadas" })).not.toBeInTheDocument();
    expect(within(secciones).getByRole("checkbox", { name: "Indicaciones del personal de salud" })).toBeChecked();
    // La frase final del cuidador es la de la familia (fila 166).
    expect(within(secciones).getByRole("checkbox", { name: /Estas indicaciones las revisa y confirma.*(obligatoria)/ })).toBeDisabled();
    expect(within(secciones).queryByRole("checkbox", { name: /La decisión final corresponde/ })).not.toBeInTheDocument();
    await waitFor(() => expect(parametros()).toHaveLength(2));
    expect(new URLSearchParams(parametros()[1]).get("destino")).toBe("CUIDADOR");
    expect(new URLSearchParams(parametros()[1]).get("secciones")).toBe("PACIENTE,CLASIFICACION,RECOMENDACION,FIRMA");
    expect(await screen.findByText(AVISO_REVISION, { selector: "strong" })).toBeInTheDocument();
    expect(await vistaLista()).toHaveTextContent("Información para la familia");
  });

  it("el aviso de texto en revisión sigue visible mientras se actualiza la vista previa del cuidador", async () => {
    let soltar: (() => void) | null = null;
    const pedidas: string[] = [];
    backendM09({ extra: { [GET_VISTA_PREVIA]: (_i, url) => {
      pedidas.push(url.search);
      const v = vistaPreviaFixture(url.searchParams.get("destino") === "CUIDADOR" ? "CUIDADOR" : "EXPEDIENTE");
      if (!url.searchParams.get("secciones")?.includes("FIRMA")) {
        return new Promise<Response>((res) => { soltar = () => res(respuestaJson(200, v)); });
      }
      return respuestaJson(200, v);
    } } });
    renderizar(RUTA_M09);
    await vistaLista();
    fireEvent.click(screen.getByRole("radio", { name: "Entrega al cuidador" }));
    expect(await screen.findByText(AVISO_REVISION, { selector: "strong" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("checkbox", { name: "Espacio de firma y sello" }));
    await waitFor(() => expect(pedidas).toHaveLength(3));
    expect(screen.getByText("Actualizando la vista previa…")).toBeInTheDocument();
    expect(screen.getByText(AVISO_REVISION, { selector: "strong" })).toBeInTheDocument();
    soltar!();
    expect(await vistaLista()).toBeInTheDocument();
    // Al volver al expediente el aviso desaparece.
    fireEvent.click(screen.getByRole("radio", { name: "Expediente clínico" }));
    expect(screen.queryByText(AVISO_REVISION, { selector: "strong" })).not.toBeInTheDocument();
  });

  it("cuidador con las frases revisadas: sin aviso de texto en revisión", async () => {
    backendM09({ extra: { [GET_VISTA_PREVIA]: (_i, url) => respuestaJson(200, {
      ...vistaPreviaFixture(url.searchParams.get("destino") === "CUIDADOR" ? "CUIDADOR" : "EXPEDIENTE"), revision_pendiente: false, avisos: [] }) } });
    renderizar(RUTA_M09);
    await vistaLista();
    fireEvent.click(screen.getByRole("radio", { name: "Entrega al cuidador" }));
    await waitFor(() => expect(screen.getByRole("article", { name: "Vista previa del documento" })).toHaveTextContent("Información para la familia"));
    expect(screen.queryByText(AVISO_REVISION, { selector: "strong" })).not.toBeInTheDocument();
  });

  it("varios cambios seguidos piden una sola vista previa con lo último elegido", async () => {
    const { parametros } = backendM09();
    renderizar(RUTA_M09);
    await vistaLista();
    for (const nombre of ["Advertencias", "Evidencias citadas", "Espacio de firma y sello"]) {
      fireEvent.click(screen.getByRole("checkbox", { name: nombre }));
    }
    await waitFor(() => expect(parametros()).toHaveLength(2));
    expect(new URLSearchParams(parametros()[1]).get("secciones")).toBe("PACIENTE,CLASIFICACION,RECOMENDACION,VERIFICACION,DECISION");
  });

  it("si falla la vista previa, «Reintentar» la vuelve a pedir", async () => {
    let falla = true;
    backendM09({ extra: { [GET_VISTA_PREVIA]: () => (falla ? respuestaJson(500, { detail: "Error interno" })
      : respuestaJson(200, vistaPreviaFixture("EXPEDIENTE"))) } });
    renderizar(RUTA_M09);
    const alerta = await screen.findByText(/No se pudo cargar la vista previa/);
    falla = false;
    fireEvent.click(within(alerta.closest("[role=alert]") as HTMLElement).getByRole("button", { name: "Reintentar" }));
    expect(await vistaLista()).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// M09: generar, descargar e imprimir sin otro POST
// ---------------------------------------------------------------------------
describe("M09 · generar el reporte", () => {
  it("un solo POST: número y huella visibles, descargar y abrir para imprimir usan el mismo PDF", async () => {
    const b = backendM09();
    renderizar(RUTA_M09);
    await vistaLista();
    const listasAntes = b.listas();
    fireEvent.click(screen.getByRole("button", { name: "Generar reporte (PDF)" }));
    expect(await screen.findByRole("heading", { name: "Reporte EV-2026-00003" })).toBeInTheDocument();
    expect(screen.getAllByText("b".repeat(64)).length).toBeGreaterThanOrEqual(1);
    const descargar = screen.getByRole("link", { name: "Descargar PDF" });
    expect(descargar).toHaveAttribute("href", "blob:prueba-1");
    expect(descargar).toHaveAttribute("download", "EV-2026-00003.pdf");
    descargar.addEventListener("click", (e) => e.preventDefault());
    fireEvent.click(descargar);
    fireEvent.click(descargar);
    fireEvent.click(screen.getByRole("button", { name: "Abrir para imprimir" }));
    fireEvent.click(screen.getByRole("button", { name: "Abrir para imprimir" }));
    expect(abrir).toHaveBeenCalledTimes(2);
    expect(abrir).toHaveBeenCalledWith("blob:prueba-1", "_blank");
    expect(b.posts()).toBe(1);
    expect(crear).toHaveBeenCalledTimes(1);
    // El cuerpo lleva el destino y las secciones elegidas.
    const cuerpo = JSON.parse(String(b.f.mock.calls.find(([r, i]) => r === `/api/consultas/${ID_CONSULTA}/reportes` && i?.method === "POST")![1]!.body));
    expect(cuerpo).toEqual({ destino: "EXPEDIENTE", secciones: ["PACIENTE", "CLASIFICACION", ...OPCIONALES_EXPEDIENTE.split(",")], formato: "PDF" });
    // La lista se actualiza con el reporte nuevo.
    await waitFor(() => expect(b.listas()).toBe(listasAntes + 1));
    const emitidos = await screen.findByRole("list", { name: "Reportes emitidos" });
    await waitFor(() => expect(within(emitidos).getAllByRole("listitem")).toHaveLength(3));
    expect(within(emitidos).getAllByRole("listitem")[0]).toHaveTextContent("EV-2026-00003");
  });

  it("no permite un segundo POST mientras se genera, ni enviando el formulario dos veces", async () => {
    let terminar!: (r: Response) => void;
    const b = backendM09({ post: () => new Promise<Response>((r) => { terminar = r; }) });
    renderizar(RUTA_M09);
    await vistaLista();
    const formulario = screen.getByRole("form", { name: "Opciones del reporte" });
    fireEvent.submit(formulario);
    fireEvent.submit(formulario);
    const boton = await screen.findByRole("button", { name: "Generando…" });
    expect(boton).toBeDisabled();
    expect(screen.getByText("Generando el reporte…")).toHaveAttribute("aria-live", "polite");
    fireEvent.click(boton);
    fireEvent.submit(formulario);
    expect(b.posts()).toBe(1);
    terminar(respuestaPdf("EV-2026-00003"));
    expect(await screen.findByRole("heading", { name: "Reporte EV-2026-00003" })).toBeInTheDocument();
    expect(b.posts()).toBe(1);
  });

  it("libera el PDF al generar otro y al salir de la pantalla", async () => {
    backendM09();
    const vista = renderizar(RUTA_M09);
    await vistaLista();
    fireEvent.click(screen.getByRole("button", { name: "Generar reporte (PDF)" }));
    await screen.findByRole("heading", { name: "Reporte EV-2026-00003" });
    fireEvent.click(screen.getByRole("button", { name: "Generar reporte (PDF)" }));
    await screen.findByRole("heading", { name: "Reporte EV-2026-00004" });
    expect(liberar).toHaveBeenCalledWith("blob:prueba-1");
    expect(liberar).not.toHaveBeenCalledWith("blob:prueba-2");
    vista.unmount();
    expect(liberar).toHaveBeenCalledWith("blob:prueba-2");
  });

  it("no guarda el PDF ni datos del paciente en el almacenamiento del navegador", async () => {
    localStorage.clear();
    sessionStorage.clear();
    backendM09();
    renderizar(RUTA_M09);
    await vistaLista();
    fireEvent.click(screen.getByRole("button", { name: "Generar reporte (PDF)" }));
    await screen.findByRole("heading", { name: "Reporte EV-2026-00003" });
    expect(localStorage.length).toBe(0);
    expect(Object.keys(sessionStorage)).toEqual(["cdss.token"]);
  });
});

// ---------------------------------------------------------------------------
// M09: avisos y errores
// ---------------------------------------------------------------------------
describe("M09 · avisos y errores", () => {
  it("consulta de prueba: banner «MODO DE PRUEBA»; consulta real: sin banner", async () => {
    backendM09();
    const vista = renderizar(RUTA_M09);
    expect(await screen.findByText(AVISO_PRUEBA, { selector: "strong" })).toBeInTheDocument();
    vista.unmount();
    backendM09({ resultado: { ...resultadoFixture("VERIFICADA"), modo_prueba: false } });
    renderizar(RUTA_M09);
    await vistaLista();
    expect(screen.queryByText(AVISO_PRUEBA, { selector: "strong" })).not.toBeInTheDocument();
  });

  it("sin resultado: lo explica, deshabilita «Generar» y no pide la vista previa", async () => {
    const { parametros, posts } = backendM09({ resultado: resultadoFixture("FUERA_DE_DOMINIO") });
    renderizar(RUTA_M09);
    expect(await screen.findByText(/no tiene un resultado para exportar \(estado: Fuera del alcance\)/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Generar reporte (PDF)" })).toBeDisabled();
    expect(screen.getByRole("radio", { name: "Entrega al cuidador" })).toBeDisabled();
    fireEvent.submit(screen.getByRole("form", { name: "Opciones del reporte" }));
    expect(posts()).toBe(0);
    expect(parametros()).toEqual([]);
  });

  it("un 409 de la vista previa deshabilita «Generar»", async () => {
    backendM09({ extra: { [GET_VISTA_PREVIA]: () => respuestaJson(409, { detail: "Solo se puede exportar el reporte de una consulta verificada o con evidencia insuficiente (estado actual: ERROR)" }) } });
    renderizar(RUTA_M09);
    expect(await screen.findByText(/estado actual: ERROR/, { selector: "p.alerta" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Generar reporte (PDF)" })).toBeDisabled();
  });

  it("errores del POST (403, 409, 422 y de red) se muestran sin dejar el botón bloqueado salvo el 409", async () => {
    const respuestas: (() => Response | Promise<Response>)[] = [
      () => respuestaJson(403, { detail: "No tiene permiso para esta acción" }),
      () => respuestaJson(422, { detail: "Revise los datos ingresados. secciones: no se admite" }),
      () => Promise.reject(new TypeError("Failed to fetch")),
      () => respuestaJson(409, { detail: "Solo se puede exportar el reporte de una consulta verificada o con evidencia insuficiente (estado actual: ERROR)" }),
    ];
    backendM09({ post: (n) => respuestas[n - 1]() });
    renderizar(RUTA_M09);
    await vistaLista();
    const boton = () => screen.getByRole("button", { name: "Generar reporte (PDF)" });
    for (const texto of ["No tiene permiso para esta acción", "secciones: no se admite", "No se pudo conectar con el servidor"]) {
      fireEvent.click(boton());
      const alerta = await screen.findByText(texto, { exact: false, selector: "p.alerta" });
      expect(alerta).toHaveTextContent(/^No se pudo generar el reporte\./);
      expect(boton()).toBeEnabled();
    }
    fireEvent.click(boton());
    await waitFor(() => expect(boton()).toBeDisabled());
  });

  it("un 401 del POST cierra la sesión como en el resto de la aplicación", async () => {
    backendM09({ post: () => respuestaJson(401, { detail: "Sesión no válida o expirada" }) });
    renderizar(RUTA_M09);
    await vistaLista();
    fireEvent.click(screen.getByRole("button", { name: "Generar reporte (PDF)" }));
    expect(await screen.findByRole("heading", { name: "Iniciar sesión" })).toBeInTheDocument();
    expect(leerToken()).toBeNull();
    expect(crear).not.toHaveBeenCalled();
  });

  it("404 y 403 de la consulta: mensaje del proyecto", async () => {
    simularBackend({ [GET_RESULTADO]: () => respuestaJson(404, { detail: "La consulta no existe" }) });
    const vista = renderizar(RUTA_M09);
    const alerta = await screen.findByRole("alert");
    expect(alerta).toHaveTextContent("La consulta no existe");
    expect(within(alerta).getByRole("link", { name: "Ir al historial de consultas" })).toHaveAttribute("href", "/consultas");
    vista.unmount();
    simularBackend({ [GET_RESULTADO]: () => respuestaJson(403, { detail: "No tiene permiso para esta acción" }) });
    renderizar(RUTA_M09);
    expect(await screen.findByRole("alert")).toHaveTextContent("No tiene permiso para esta acción");
  });

  it("un rol sin EXPORTAR_REPORTE vuelve al inicio desde M09 y desde /reportes", async () => {
    for (const ruta of [RUTA_M09, "/reportes"]) {
      const sinPermiso = { ...USUARIO, nombre_completo: "Usuaria Sin Reportes", permisos: ["REGISTRAR_PACIENTE", "REALIZAR_CONSULTA"] };
      const f = simularBackend({ "GET /api/auth/me": () => respuestaJson(200, sinPermiso) });
      const vista = renderizar(ruta);
      expect(await screen.findByRole("heading", { level: 1, name: "Hola, Usuaria Sin Reportes" })).toBeInTheDocument();
      expect(f.mock.calls.some(([r]) => String(r).includes("/reportes"))).toBe(false);
      vista.unmount();
    }
  });
});

// ---------------------------------------------------------------------------
// Entradas a M09: M05, M07, M08 y «Reportes»
// ---------------------------------------------------------------------------
describe("Entradas a M09", () => {
  function conResultado(resultado: ResultadoConsulta, permisos = USUARIO.permisos) {
    simularBackend({ [GET_RESULTADO]: () => respuestaJson(200, resultado),
                     "GET /api/auth/me": () => respuestaJson(200, { ...USUARIO, permisos }),
                     [`GET /api/pacientes/${ID_PACIENTE_FIXTURE}/consultas`]: () => respuestaJson(200, []) });
    return renderizar(`/consultas/${ID_CONSULTA}`);
  }

  it("M05 (verificada) y M07 (evidencia insuficiente) llevan a M09 con el permiso", async () => {
    let vista = conResultado(resultadoFixture("VERIFICADA"));
    expect(await screen.findByRole("link", { name: "Exportar reporte" })).toHaveAttribute("href", RUTA_M09);
    vista.unmount();
    vista = conResultado(resultadoFixture("EVIDENCIA_INSUFICIENTE"));
    expect(await screen.findByRole("link", { name: "Exportar reporte" })).toHaveAttribute("href", RUTA_M09);
    vista.unmount();
  });

  it("M05 sin resultado o sin permiso no ofrece «Exportar reporte»", async () => {
    let vista = conResultado(resultadoFixture("FUERA_DE_DOMINIO"));
    await screen.findByRole("heading", { name: "Estado de la consulta" });
    expect(screen.queryByRole("link", { name: "Exportar reporte" })).not.toBeInTheDocument();
    vista.unmount();
    vista = conResultado(resultadoFixture("VERIFICADA"), ["REGISTRAR_PACIENTE", "REALIZAR_CONSULTA"]);
    await screen.findByRole("heading", { name: "Recomendación clínica" });
    expect(screen.queryByRole("link", { name: "Exportar reporte" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Exportar reporte" })).not.toBeInTheDocument();
  });

  it("M08: «Reporte» solo en las consultas con resultado y con el permiso", async () => {
    const consulta = (id: string, estado: ConsultaPropia["estado"], hora: string) => ({
      id_consulta: id, id_tamizaje: "t-0001", fecha_tamizaje: "2026-11-01", id_consulta_previa: null, estado,
      texto_filtrado: "¿Qué dosis de hierro le corresponde?", idioma: "es" as const, fecha_hora_inicio: `2026-11-10T${hora}:00-05:00`,
      fecha_hora_fin: null, numero_intentos: 1, latencia_total_ms: 1000, confirma_tamizaje_no_vigente: false,
      categoria: "ANEMIA_LEVE", tipo_decision: null, modo_prueba: false,
    });
    const historial = (permisos = USUARIO.permisos) => {
      simularBackend({
        "GET /api/auth/me": () => respuestaJson(200, { ...USUARIO, permisos }),
        [`GET /api/pacientes/${ID_PACIENTE}`]: () => respuestaJson(200, { ...FICHA, sexo: "F" }),
        [`GET /api/pacientes/${ID_PACIENTE}/historial`]: () => respuestaJson(200, { ...HISTORIAL, consultas: [
          consulta("c-ver", "VERIFICADA", "10:00"), consulta("c-ei", "EVIDENCIA_INSUFICIENTE", "09:00"), consulta("c-fd", "FUERA_DE_DOMINIO", "08:00")] }) });
      return renderizar(`/pacientes/${ID_PACIENTE}/historial`);
    };
    const vista = historial();
    let tabla = await screen.findByRole("region", { name: "Consultas del paciente" });
    const reportes = within(tabla).getAllByRole("link", { name: /^Exportar el reporte de la consulta del/ });
    expect(reportes.map((a) => a.getAttribute("href")).sort()).toEqual(["/consultas/c-ei/reporte", "/consultas/c-ver/reporte"]);
    expect(within(tabla).getAllByRole("link", { name: /^Ver la consulta del/ })).toHaveLength(3);
    vista.unmount();
    // Sin EXPORTAR_REPORTE: solo «Ver».
    historial(["REGISTRAR_PACIENTE", "REALIZAR_CONSULTA"]);
    tabla = await screen.findByRole("region", { name: "Consultas del paciente" });
    expect(within(tabla).getAllByRole("link", { name: /^Ver la consulta del/ })).toHaveLength(3);
    expect(within(tabla).queryByRole("link", { name: /^Exportar el reporte/ })).not.toBeInTheDocument();
  });

  it("«Reportes» (/reportes) es la lista de consultas propias con «Exportar» en las que tienen resultado", async () => {
    const propia = (id: string, estado: ConsultaPropia["estado"], hora: string): ConsultaPropia => ({
      id_consulta: id, id_paciente: ID_PACIENTE, nombres_apellidos: "Paciente Ficticio Uno", numero_hc: "HC-PRUEBA-1", edad_meses: 16,
      estado, categoria: "ANEMIA_LEVE", nivel_riesgo: "MODERADO", fecha_hora_inicio: `2026-11-10T${hora}:00-05:00`,
      modo_prueba: false, pregunta: "¿Qué dosis de hierro le corresponde?" });
    simularBackend({ "GET /api/consultas": () => respuestaJson(200, { total: 2, limite: 20, desplazamiento: 0, consultas: [
      propia("c-ver", "VERIFICADA", "10:00"), propia("c-err", "ERROR", "09:00")] }) });
    renderizar("/reportes");
    expect(await screen.findByRole("heading", { level: 1, name: "Reportes" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Nueva consulta" })).not.toBeInTheDocument();
    const filas = within(await screen.findByRole("region", { name: "Consultas realizadas" })).getAllByRole("row").slice(1);
    expect(within(filas[0]).getByRole("link", { name: /^Exportar el reporte de la consulta de Paciente Ficticio Uno/ }))
      .toHaveAttribute("href", "/consultas/c-ver/reporte");
    expect(within(filas[0]).getByRole("link", { name: /^Ver la consulta de/ })).toBeInTheDocument();
    expect(within(filas[1]).queryByRole("link", { name: /^Exportar/ })).not.toBeInTheDocument();
    expect(filas[1]).toHaveTextContent("Sin resultado para exportar");
    const menu = screen.getByRole("navigation", { name: /menú|Menú/ });
    expect(within(menu).getByRole("link", { name: "Reportes" })).toHaveAttribute("href", "/reportes");
  });
});
