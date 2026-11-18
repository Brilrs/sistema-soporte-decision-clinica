// Pruebas de la parte E6: M08 «Evaluaciones realizadas», «Guardar y evaluar» de M14 y M03, el
// texto de 6.3, la página «Historial de consultas» y los títulos de pestaña. Fetch simulado con
// los datos ficticios del simulador; sin API real.
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import App from "../App";
import { guardarToken } from "../api/cliente";
import type { Historial } from "../api/pacientes";
import type { ConsultaListada, ResultadoConsulta } from "../api/tipos_consulta";
import { AuthProvider } from "../auth/AuthContext";
import { TIPOS_DECISION } from "../consulta/textos";
import {
  FICHA,
  GET_RESULTADO,
  HISTORIAL,
  ID_CONSULTA,
  ID_PACIENTE,
  USUARIO,
  respuestaJson,
  resultadoFixture,
  simularBackend,
} from "../pruebas/simulador";
import { decimal, fechaHora } from "../utilidades/formato";
import { NOMBRE_SISTEMA } from "../utilidades/useTituloPagina";

const RUTA_M08 = `/pacientes/${ID_PACIENTE}/historial`;
const RUTA_M14 = `/pacientes/${ID_PACIENTE}/tamizajes/nuevo`;
const GET_HISTORIAL = `GET /api/pacientes/${ID_PACIENTE}/historial`;

function renderizar(ruta: string | { pathname: string; state: unknown }) {
  guardarToken("token-de-prueba");
  return render(
    <MemoryRouter initialEntries={[ruta]}>
      <AuthProvider>
        <App />
      </AuthProvider>
    </MemoryRouter>,
  );
}

function consulta(cambios: Partial<ConsultaListada>): ConsultaListada {
  return {
    id_consulta: "c-0001", id_tamizaje: "t-0001", fecha_tamizaje: "2026-11-01", id_consulta_previa: null,
    estado: "VERIFICADA", texto_filtrado: "¿Qué dosis de hierro le corresponde?", idioma: "es",
    fecha_hora_inicio: "2026-11-10T10:00:00-05:00", fecha_hora_fin: "2026-11-10T10:00:20-05:00", numero_intentos: 1,
    latencia_total_ms: 20000, confirma_tamizaje_no_vigente: false, categoria: "ANEMIA_LEVE", tipo_decision: null,
    modo_prueba: false, ...cambios,
  };
}

// Desordenadas a propósito: la pantalla las muestra de la más reciente a la más antigua.
const CONSULTAS: ConsultaListada[] = [
  consulta({ id_consulta: "c-antigua", id_tamizaje: "t-0000", fecha_hora_inicio: "2026-05-12T09:26:00-05:00",
             estado: "EVIDENCIA_INSUFICIENTE", categoria: "ANEMIA_LEVE",
             texto_filtrado: "¿Cuántas horas hay que esperar entre el antiparasitario y el sulfato ferroso si se dan el mismo día?",
             tipo_decision: "CRITERIO_CLINICO_PROPIO" }),
  consulta({ id_consulta: "c-reciente", fecha_hora_inicio: "2026-11-10T10:42:00-05:00", modo_prueba: true,
             tipo_decision: "ACEPTA_RECOMENDACION" }),
  consulta({ id_consulta: "c-media", fecha_hora_inicio: "2026-11-10T08:15:00-05:00", estado: "FUERA_DE_DOMINIO",
             categoria: null, texto_filtrado: null }),
];

function conHistorial(consultas: ConsultaListada[], extra: Parameters<typeof simularBackend>[0] = {}) {
  const historial: Historial = { ...HISTORIAL, consultas };
  return simularBackend({ [GET_HISTORIAL]: () => respuestaJson(200, historial), ...extra });
}

async function tablaEvaluaciones() {
  const seccion = await screen.findByRole("region", { name: "Evaluaciones realizadas" });
  return { seccion, filas: () => within(seccion).queryAllByRole("row").slice(1) };
}

// ---------------------------------------------------------------------------
// M08 · Evaluaciones realizadas
// ---------------------------------------------------------------------------
describe("M08 · evaluaciones realizadas", () => {
  it("lista las consultas de la más reciente a la más antigua, con sus datos y enlace", async () => {
    conHistorial(CONSULTAS);
    renderizar(RUTA_M08);
    const { seccion, filas } = await tablaEvaluaciones();
    expect(within(seccion).getByText("Solo se muestran las consultas que usted realizó.")).toBeInTheDocument();
    const [primera, segunda, tercera] = filas();
    expect(filas()).toHaveLength(3);
    // Orden por fecha y hora de inicio.
    expect(primera).toHaveTextContent(fechaHora("2026-11-10T10:42:00-05:00"));
    expect(segunda).toHaveTextContent(fechaHora("2026-11-10T08:15:00-05:00"));
    expect(tercera).toHaveTextContent(fechaHora("2026-05-12T09:26:00-05:00"));
    // Hb del tamizaje de la consulta, clasificación, estado con color, «Prueba» y decisión.
    expect(within(primera).getByText(decimal(HISTORIAL.tamizajes[0].hemoglobina_g_dl))).toBeInTheDocument();
    expect(within(primera).getByText("Anemia leve")).toHaveClass("etiqueta--ANEMIA_LEVE");
    expect(within(primera).getByText("Verificada")).toHaveClass("etiqueta--estado-VERIFICADA");
    expect(within(primera).getByText("Prueba")).toHaveClass("etiqueta--prueba");
    expect(within(primera).getByText(TIPOS_DECISION.ACEPTA_RECOMENDACION.etiqueta)).toBeInTheDocument();
    expect(within(tercera).getByText(decimal(HISTORIAL.tamizajes[1].hemoglobina_g_dl))).toBeInTheDocument();
    expect(within(tercera).getByText("Evidencia insuficiente")).toHaveClass("etiqueta--estado-EVIDENCIA_INSUFICIENTE");
    expect(within(tercera).queryByText("Prueba")).not.toBeInTheDocument();
    expect(within(tercera).getByText(TIPOS_DECISION.CRITERIO_CLINICO_PROPIO.etiqueta)).toBeInTheDocument();
    // Sin decisión, sin pregunta y sin clasificación: se dice, no se inventa.
    expect(within(segunda).getByText("Sin decisión")).toBeInTheDocument();
    expect(within(segunda).getByText("Sin pregunta registrada")).toBeInTheDocument();
    expect(within(segunda).getByText("Sin clasificación")).toBeInTheDocument();
    expect(within(segunda).getByText("Fuera del alcance")).toHaveClass("etiqueta--estado-FUERA_DE_DOMINIO");
    // La pregunta larga se corta con puntos suspensivos (CSS) y conserva el texto completo.
    const pregunta = within(tercera).getByText(/antiparasitario y el sulfato ferroso/);
    expect(pregunta).toHaveClass("evaluaciones__pregunta");
    expect(pregunta).toHaveAttribute("title", CONSULTAS[0].texto_filtrado);
    // Cada fila enlaza a su consulta.
    const ver = within(primera).getByRole("link", { name: `Ver la consulta del ${fechaHora("2026-11-10T10:42:00-05:00")}` });
    expect(ver).toHaveAttribute("href", "/consultas/c-reciente");
  });

  it("«Ver» abre la consulta en /consultas/:id", async () => {
    conHistorial([consulta({ id_consulta: ID_CONSULTA })],
                 { [GET_RESULTADO]: () => respuestaJson(200, resultadoFixture("VERIFICADA")) });
    renderizar(RUTA_M08);
    const { filas } = await tablaEvaluaciones();
    fireEvent.click(within(filas()[0]).getByRole("link", { name: /Ver la consulta/ }));
    expect(await screen.findByRole("heading", { name: "Recomendación clínica" })).toBeInTheDocument();
  });

  it("filtra por fecha y avisa si no hay consultas ese día", async () => {
    conHistorial(CONSULTAS);
    renderizar(RUTA_M08);
    const { seccion, filas } = await tablaEvaluaciones();
    const filtro = within(seccion).getByLabelText("Filtrar por fecha");
    fireEvent.change(filtro, { target: { value: "2026-11-10" } });
    expect(filas()).toHaveLength(2);
    fireEvent.change(filtro, { target: { value: "2026-01-01" } });
    expect(within(seccion).getByRole("status")).toHaveTextContent("No hay consultas en la fecha elegida.");
    fireEvent.click(within(seccion).getByRole("button", { name: "Ver todas" }));
    expect(filas()).toHaveLength(3);
  });

  it("sin consultas muestra un estado vacío claro y sin filtro", async () => {
    conHistorial([]);
    renderizar(RUTA_M08);
    const { seccion } = await tablaEvaluaciones();
    expect(within(seccion).getByText(/Aún no realizó consultas clínicas para este paciente/)).toBeInTheDocument();
    expect(within(seccion).queryByLabelText("Filtrar por fecha")).not.toBeInTheDocument();
    expect(within(seccion).queryByRole("table")).not.toBeInTheDocument();
  });

  it("un rol que no realiza consultas recibe una explicación en lugar de una lista vacía", async () => {
    conHistorial([], { "GET /api/auth/me": () => respuestaJson(200, { ...USUARIO, permisos: ["REGISTRAR_PACIENTE"] }) });
    renderizar(RUTA_M08);
    const { seccion } = await tablaEvaluaciones();
    expect(within(seccion).getByText(/Su rol no realiza consultas clínicas/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Nueva consulta" })).not.toBeInTheDocument();
  });

  it("muestra «Cargando…» mientras llega el historial", async () => {
    let responder: (r: Response) => void = () => undefined;
    simularBackend({ [GET_HISTORIAL]: () => new Promise<Response>((r) => (responder = r)) });
    renderizar(RUTA_M08);
    // Primero carga la sesión (la cabecera muestra «Cerrar sesión»); después, el historial.
    await screen.findByRole("button", { name: "Cerrar sesión" });
    expect(screen.getByText("Cargando…")).toBeInTheDocument();
    responder(respuestaJson(200, { ...HISTORIAL, consultas: [] }));
    expect(await screen.findByRole("region", { name: "Evaluaciones realizadas" })).toBeInTheDocument();
  });

  it("«Nueva consulta» abre M04 del paciente", async () => {
    conHistorial([]);
    renderizar(RUTA_M08);
    fireEvent.click(await screen.findByRole("button", { name: "Nueva consulta" }));
    expect(await screen.findByRole("heading", { name: "Consulta clínica" })).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// Buscador de «Nueva consulta» (/consultas/nueva). Hasta la parte B del Sprint 3 estaba en
// /consultas, que ahora es la lista de consultas propias (HistorialConsultas.test.tsx).
// ---------------------------------------------------------------------------
describe("Buscador de «Nueva consulta» (/consultas/nueva)", () => {
  it("busca pacientes y «Ver historial» abre M08 con sus consultas", async () => {
    conHistorial(CONSULTAS, {
      "GET /api/pacientes": () => respuestaJson(200, [{ id_paciente: ID_PACIENTE, nombres_apellidos: FICHA.nombres_apellidos,
        numero_hc: FICHA.numero_hc, sexo: "M", edad_meses_actual: 16, ultimo_tamizaje: null }]),
    });
    renderizar("/consultas/nueva");
    expect(await screen.findByRole("heading", { level: 1, name: "Nueva consulta" })).toBeInTheDocument();
    expect(screen.getByText(/las consultas que usted le realizó/)).toBeInTheDocument();
    fireEvent.click(await screen.findByRole("button", { name: `Ver historial: ${FICHA.nombres_apellidos}` }));
    const { filas } = await tablaEvaluaciones();
    expect(filas()).toHaveLength(3);
  });
});

// ---------------------------------------------------------------------------
// «Guardar y evaluar» (M14 y M03)
// ---------------------------------------------------------------------------
const TAMIZAJE_REGISTRADO = {
  id_tamizaje: "t-nuevo", edad_meses: 16,
  clasificacion: { categoria: "ANEMIA_LEVE", nivel_riesgo: "MODERADO", requiere_derivacion: false, altitud_msnm: 150,
                   ajuste_hb_g_dl: "0.0", hb_ajustada_g_dl: "10.2" },
  motivo_sin_clasificacion: null,
};

function backendM14() {
  return simularBackend({
    "GET /api/catalogos/sintomas": () => respuestaJson(200, []),
    "GET /api/catalogos/distritos": () => respuestaJson(200, []),
    [`POST /api/pacientes/${ID_PACIENTE}/tamizajes`]: () => respuestaJson(201, TAMIZAJE_REGISTRADO),
  });
}

async function llenarTamizaje() {
  fireEvent.change(await screen.findByLabelText(/Fecha del tamizaje/), { target: { value: "2026-11-15" } });
  fireEvent.change(screen.getByLabelText(/Hemoglobina \(g\/dL\)/), { target: { value: "10.2" } });
}

describe("M14 · «Guardar y evaluar»", () => {
  it("guarda el tamizaje y abre M04 con el aviso de la clasificación calculada", async () => {
    const f = backendM14();
    renderizar(RUTA_M14);
    await llenarTamizaje();
    expect(screen.queryByText("Disponible en el Sprint 2")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Guardar y evaluar" }));
    expect(await screen.findByRole("heading", { name: "Consulta clínica" })).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Tamizaje registrado. Clasificación: Anemia leve (Hb ajustada 10.2 g/dL).");
    const post = f.mock.calls.find(([r, i]) => i?.method === "POST" && String(r).endsWith("/tamizajes"));
    expect(JSON.parse(String(post?.[1]?.body))).toMatchObject({ fecha_tamizaje: "2026-11-15", hemoglobina_g_dl: 10.2 });
  });

  it("«Guardar» sigue llevando al historial", async () => {
    backendM14();
    renderizar(RUTA_M14);
    await llenarTamizaje();
    fireEvent.click(screen.getByRole("button", { name: "Guardar" }));
    expect(await screen.findByRole("region", { name: "Evaluaciones realizadas" })).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Tamizaje registrado.");
  });

  it("desde la consulta solo ofrece «Guardar», que ya vuelve a M04", async () => {
    backendM14();
    renderizar({ pathname: RUTA_M14, state: { volverAConsulta: { pregunta: "¿Qué dosis le corresponde?" } } });
    await llenarTamizaje();
    expect(screen.queryByRole("button", { name: "Guardar y evaluar" })).not.toBeInTheDocument();
    expect(screen.getByText("Al guardar volverá a la consulta clínica con su pregunta.")).toBeInTheDocument();
  });

  it("sin REALIZAR_CONSULTA no ofrece «Guardar y evaluar»", async () => {
    simularBackend({
      "GET /api/auth/me": () => respuestaJson(200, { ...USUARIO, permisos: ["REGISTRAR_PACIENTE"] }),
      "GET /api/catalogos/sintomas": () => respuestaJson(200, []),
      "GET /api/catalogos/distritos": () => respuestaJson(200, []),
    });
    renderizar(RUTA_M14);
    expect(await screen.findByRole("button", { name: "Guardar" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Guardar y evaluar" })).not.toBeInTheDocument();
  });

  it("M03 ofrece «Guardar y evaluar» habilitable, sin la nota del Sprint 2", async () => {
    simularBackend({
      "GET /api/catalogos/sintomas": () => respuestaJson(200, []),
      "GET /api/catalogos/distritos": () => respuestaJson(200, []),
    });
    renderizar("/pacientes/nuevo");
    const boton = await screen.findByRole("button", { name: "Guardar y evaluar" });
    expect(boton).toHaveAttribute("type", "submit");
    expect(screen.queryByText("Disponible en el Sprint 2")).not.toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// 6.3 en la verificación (M05 y M07)
// ---------------------------------------------------------------------------
function conVerificacion(estado: "VERIFICADA" | "EVIDENCIA_INSUFICIENTE", cambios: Partial<NonNullable<ResultadoConsulta["verificacion"]>>) {
  const r = resultadoFixture(estado);
  r.verificacion = { ...r.verificacion!, ...cambios };
  simularBackend({ [GET_RESULTADO]: () => respuestaJson(200, r) });
  renderizar(`/consultas/${ID_CONSULTA}`);
}

async function control63() {
  const verif = await screen.findByRole("region", { name: "Verificación de la respuesta" });
  return within(verif).getAllByRole("listitem")[2];
}

describe("verificación 6.3", () => {
  it("si no se cumple con la relevancia sobre el umbral, explica que el modelo juzgó insuficientes los fragmentos", async () => {
    conVerificacion("EVIDENCIA_INSUFICIENTE", { valida_evidencia: false, relevancia_maxima: 0.881, umbral_relevancia: 0.15 });
    const c = await control63();
    expect(c).toHaveTextContent("6.3 Suficiencia de la evidencia: No cumplido");
    expect(c).toHaveTextContent(
      "El modelo indicó que los fragmentos recuperados no bastan para responder, aunque la relevancia máxima (0.881) " +
      "supera el umbral (0.150).");
  });

  it("si no se cumple porque ningún fragmento alcanzó el umbral, lo dice", async () => {
    conVerificacion("EVIDENCIA_INSUFICIENTE", { valida_evidencia: false, relevancia_maxima: 0.011, umbral_relevancia: 0.15 });
    expect(await control63()).toHaveTextContent("Ningún fragmento alcanzó el umbral: relevancia máxima 0.011 frente al umbral 0.150.");
  });

  it("si se cumple, muestra la relevancia frente al umbral", async () => {
    conVerificacion("VERIFICADA", { valida_evidencia: true, relevancia_maxima: 0.342, umbral_relevancia: 0.15 });
    const c = await control63();
    expect(c).toHaveTextContent("Relevancia máxima 0.342 frente al umbral 0.150.");
    expect(c).not.toHaveTextContent("El modelo indicó");
  });
});

// ---------------------------------------------------------------------------
// Títulos de pestaña
// ---------------------------------------------------------------------------
describe("títulos de pestaña", () => {
  it.each([
    [RUTA_M08, "Historial del paciente"],
    [RUTA_M14, "Nuevo tamizaje"],
    [`/pacientes/${ID_PACIENTE}/consulta`, "Consulta clínica"],
    ["/consultas", "Historial de consultas"],
    ["/consultas/nueva", "Nueva consulta"],
    ["/pacientes", "Pacientes"],
  ])("%s: «%s · CDSS Anemia Infantil», sin datos del paciente", async (ruta, pantalla) => {
    conHistorial([], {
      "GET /api/pacientes": () => respuestaJson(200, []),
      "GET /api/consultas": () => respuestaJson(200, { total: 0, limite: 20, desplazamiento: 0, consultas: [] }),
      "GET /api/catalogos/sintomas": () => respuestaJson(200, []),
      "GET /api/catalogos/distritos": () => respuestaJson(200, []),
    });
    renderizar(ruta);
    await waitFor(() => expect(document.title).toBe(`${pantalla} · ${NOMBRE_SISTEMA}`));
    expect(document.title).not.toContain(FICHA.nombres_apellidos);
  });

  it("M05 y M07 distinguen el resultado de la evidencia insuficiente", async () => {
    simularBackend({ [GET_RESULTADO]: () => respuestaJson(200, resultadoFixture("EVIDENCIA_INSUFICIENTE")) });
    const vista = renderizar(`/consultas/${ID_CONSULTA}`);
    await waitFor(() => expect(document.title).toBe(`Evidencia insuficiente · ${NOMBRE_SISTEMA}`));
    vista.unmount();
    simularBackend({ [GET_RESULTADO]: () => respuestaJson(200, resultadoFixture("VERIFICADA")) });
    renderizar(`/consultas/${ID_CONSULTA}`);
    await waitFor(() => expect(document.title).toBe(`Resultado de la consulta · ${NOMBRE_SISTEMA}`));
  });

  it("el inicio de sesión tiene su título", async () => {
    guardarToken(null);
    simularBackend();
    render(<MemoryRouter initialEntries={["/login"]}><AuthProvider><App /></AuthProvider></MemoryRouter>);
    await waitFor(() => expect(document.title).toBe(`Iniciar sesión · ${NOMBRE_SISTEMA}`));
  });
});
