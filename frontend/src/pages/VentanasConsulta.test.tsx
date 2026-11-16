// Pruebas de la parte E4: ventanas M06 (datos faltantes) y M15 (tamizaje no vigente) desde M04
// y desde M05, vuelta de M14 a M04 con la pregunta, estados sin recomendación rediseñados y
// avance cerrado. Fetch simulado con los fixtures del contrato; nunca llama a la API real.
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import { guardarToken } from "../api/cliente";
import type { EstadoFinal } from "../api/tipos_consulta";
import { AuthProvider } from "../auth/AuthContext";
import { AVISO_CONTINUAR } from "../components/consulta/VentanaTamizajeNoVigente";
import { validarHemoglobina } from "../components/consulta/VentanaDatosFaltantes";
import { textoDesenlace } from "../components/MensajeDesenlace";
import {
  COMO_REFORMULAR_BLOQUEADA,
  MENSAJE_BLOQUEADA,
  MENSAJE_ERROR,
  SUGERENCIA_FUERA_DE_DOMINIO,
  TITULOS_ESTADO,
} from "../consulta/textos";
import {
  GET_RESULTADO,
  ID_CONSULTA,
  ID_CONSULTA_REANUDADA,
  ID_PACIENTE,
  ID_PACIENTE_FIXTURE,
  ID_TAMIZAJE_FIXTURE,
  POST_CONSULTA,
  lineasFixture,
  lineasReanudadas,
  respuestaJson,
  respuestaStream,
  resultadoFixture,
  resultadoReanudado,
  simularBackend,
  streamControlado,
} from "../pruebas/simulador";

const RUTA_M04 = `/pacientes/${ID_PACIENTE}/consulta`;
const RUTA_M05 = `/consultas/${ID_CONSULTA}`;
const PREGUNTA = "¿Qué dosis de hierro corresponde según su hemoglobina?";
const POST_DATOS = `POST /api/consultas/${ID_CONSULTA}/datos-faltantes`;
const GET_REANUDADA = `GET /api/consultas/${ID_CONSULTA_REANUDADA}`;
const POST_CONSULTA_FIXTURE = `POST /api/pacientes/${ID_PACIENTE_FIXTURE}/consultas`;

function renderizar(ruta: string | { pathname: string; state: unknown } = RUTA_M04) {
  guardarToken("token-de-prueba");
  return render(
    <MemoryRouter initialEntries={[ruta]}>
      <AuthProvider>
        <App />
      </AuthProvider>
    </MemoryRouter>,
  );
}

async function escribirYEnviar(texto = PREGUNTA) {
  const campo = await screen.findByLabelText("Consulta sobre el paciente");
  fireEvent.change(campo, { target: { value: texto } });
  fireEvent.click(screen.getByRole("button", { name: "Enviar" }));
}

type Fetch = ReturnType<typeof simularBackend>;
const llamadas = (f: Fetch, clave: string) =>
  f.mock.calls.filter(([ruta, init]) => `${init?.method ?? "GET"} ${String(ruta)}` === clave);
const cuerpo = (f: Fetch, clave: string) => JSON.parse(String(llamadas(f, clave)[0][1]!.body));

const campoHb = () => screen.getByLabelText(/Hemoglobina \(g\/dL\)/);

afterEach(() => {
  vi.useRealTimers();
  document.body.style.overflow = "";
});

describe("M06 · Datos faltantes desde M04", () => {
  function conDatosFaltantes(extra: Record<string, () => Response | Promise<Response>> = {}) {
    return simularBackend({
      [POST_CONSULTA]: () => respuestaStream(lineasFixture("DATOS_FALTANTES")),
      [POST_DATOS]: () => respuestaStream(lineasReanudadas("VERIFICADA")),
      [GET_REANUDADA]: () => respuestaJson(200, resultadoReanudado("VERIFICADA")),
      ...extra,
    });
  }

  it("abre una ventana accesible con los datos disponibles y el foco en la hemoglobina", async () => {
    conDatosFaltantes();
    renderizar();
    await escribirYEnviar();
    const ventana = await screen.findByRole("dialog", { name: "Falta información para evaluar" });
    expect(ventana).toHaveAttribute("aria-modal", "true");
    expect(ventana).toHaveAccessibleDescription(/se necesita el siguiente dato/);
    await waitFor(() => expect(document.activeElement).toBe(campoHb()));
    expect(campoHb()).toHaveAttribute("aria-required", "true");
    expect(within(ventana).getByLabelText("Método de medición")).toHaveValue("HEMOGLOBINOMETRO");
    // Solo se pide lo que falta: no hay campos de edad, sexo ni fecha.
    expect(within(ventana).getAllByRole("textbox")).toHaveLength(1);
    const disponibles = within(ventana).getByText("Datos disponibles:").parentElement as HTMLElement;
    expect(disponibles).toHaveTextContent("hemoglobina ✗ (falta)");
    expect(disponibles).toHaveTextContent("edad ✓ (disponible)");
    expect(within(ventana).getByText(/Valor del tamizaje del 01\/11\/2026/)).toBeInTheDocument();
    // De fondo, M04 resume el estado y la tarjeta de avance queda cerrada.
    expect(screen.getByRole("button", { name: "Completar datos" })).toBeInTheDocument();
  });

  it.each([
    ["", "Ingrese la hemoglobina."],
    ["abc", "La hemoglobina debe ser un número, por ejemplo 10.6."],
    ["25", "La hemoglobina debe estar entre 3.0 y 20.0 g/dL."],
    ["2.9", "La hemoglobina debe estar entre 3.0 y 20.0 g/dL."],
    ["10.65", "Use un solo decimal, por ejemplo 10.6."],
  ])("valida «%s» como M14 y anuncia el error sin enviar", async (valor, mensaje) => {
    const f = conDatosFaltantes();
    renderizar();
    await escribirYEnviar();
    await screen.findByRole("dialog");
    fireEvent.change(campoHb(), { target: { value: valor } });
    fireEvent.click(screen.getByRole("button", { name: "Completar y evaluar" }));
    const error = await screen.findByText(mensaje);
    expect(error).toHaveAttribute("role", "alert");
    expect(campoHb()).toHaveAttribute("aria-invalid", "true");
    expect(campoHb()).toHaveAccessibleDescription(new RegExp(mensaje.replace(/[.()]/g, "\\$&")));
    expect(document.activeElement).toBe(campoHb());
    expect(llamadas(f, POST_DATOS)).toHaveLength(0);
  });

  it("acepta los límites y la coma decimal", () => {
    expect(validarHemoglobina("3.0")).toBeNull();
    expect(validarHemoglobina("20")).toBeNull();
    expect(validarHemoglobina("10,6")).toBeNull();
  });

  it("completa la hemoglobina, muestra el avance de la consulta reanudada y abre su resultado en M05", async () => {
    const stream = streamControlado();
    const f = conDatosFaltantes({ [POST_DATOS]: () => stream.respuesta() });
    renderizar();
    await escribirYEnviar();
    const ventana = await screen.findByRole("dialog");
    fireEvent.change(campoHb(), { target: { value: "10,6" } });
    fireEvent.change(within(ventana).getByLabelText("Método de medición"), { target: { value: "LABORATORIO" } });
    fireEvent.click(within(ventana).getByRole("button", { name: "Completar y evaluar" }));

    await waitFor(() => expect(llamadas(f, POST_DATOS)).toHaveLength(1));
    expect(cuerpo(f, POST_DATOS)).toEqual({ hemoglobina_g_dl: 10.6, metodo_medicion: "LABORATORIO" });
    const lineas = lineasReanudadas("VERIFICADA");
    stream.enviar(lineas[0]);
    // El avance se ve dentro de la ventana; mientras sigue, Esc no la cierra.
    await waitFor(() => expect(within(ventana).getByText("Procesando la consulta…")).toBeInTheDocument());
    expect(within(ventana).getByRole("button", { name: "Evaluando…" })).toBeDisabled();
    fireEvent.keyDown(ventana, { key: "Escape" });
    expect(screen.getByRole("dialog")).toBeInTheDocument();

    stream.enviar(...lineas.slice(1));
    stream.cerrar();
    expect(await screen.findByRole("heading", { name: "Recomendación clínica" })).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    // M05 es el de la consulta nueva (no se reenvió la consulta original).
    expect(llamadas(f, POST_CONSULTA)).toHaveLength(1);
    await waitFor(() => expect(llamadas(f, GET_REANUDADA).length).toBeGreaterThan(0));
  });

  it("«Cancelar» y Esc cierran la ventana sin enviar, devuelven el foco y la consulta queda como estaba", async () => {
    const f = conDatosFaltantes();
    renderizar();
    await escribirYEnviar();
    await screen.findByRole("dialog");
    fireEvent.click(screen.getByRole("button", { name: "Cancelar" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(document.activeElement).toBe(screen.getByLabelText("Consulta sobre el paciente"));
    expect(screen.getByText(TITULOS_ESTADO.DATOS_FALTANTES)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Completar datos" }));
    const ventana = await screen.findByRole("dialog");
    fireEvent.keyDown(ventana, { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(llamadas(f, POST_DATOS)).toHaveLength(0);
  });

  it("atrapa el foco: Tab en el último control vuelve al primero y Mayús + Tab al revés", async () => {
    conDatosFaltantes();
    renderizar();
    await escribirYEnviar();
    const ventana = await screen.findByRole("dialog");
    await waitFor(() => expect(document.activeElement).toBe(campoHb()));
    const ultimo = within(ventana).getByRole("button", { name: "Completar y evaluar" });
    fireEvent.keyDown(campoHb(), { key: "Tab", shiftKey: true });
    expect(document.activeElement).toBe(ultimo);
    fireEvent.keyDown(ultimo, { key: "Tab" });
    expect(document.activeElement).toBe(campoHb());
  });

  it("un 409 del backend se muestra en la ventana y permite cerrar", async () => {
    conDatosFaltantes({
      [POST_DATOS]: () => respuestaJson(409, { detail: "Los datos faltantes de esta consulta ya se completaron" }),
    });
    renderizar();
    await escribirYEnviar();
    const ventana = await screen.findByRole("dialog");
    fireEvent.change(campoHb(), { target: { value: "11.2" } });
    fireEvent.click(within(ventana).getByRole("button", { name: "Completar y evaluar" }));
    expect(await within(ventana).findByText("Los datos faltantes de esta consulta ya se completaron")).toBeInTheDocument();
    fireEvent.click(within(ventana).getByRole("button", { name: "Cancelar" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("un dato que no se completa desde la consulta (altitud) se explica sin botón de evaluar", async () => {
    const lineas = lineasFixture("DATOS_FALTANTES").map((l) => l.replace('"datos_faltantes": ["hemoglobina"]', '"datos_faltantes": ["altitud"]'));
    simularBackend({ [POST_CONSULTA]: () => respuestaStream(lineas) });
    renderizar();
    await escribirYEnviar();
    const ventana = await screen.findByRole("dialog");
    expect(within(ventana).getByText(/la corrige el administrador en el catálogo de distritos/)).toBeInTheDocument();
    expect(within(ventana).queryByRole("button", { name: "Completar y evaluar" })).not.toBeInTheDocument();
    expect(within(ventana).queryByRole("textbox")).not.toBeInTheDocument();
    fireEvent.click(within(ventana).getByRole("button", { name: "Cerrar" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});

describe("M06 · Datos faltantes desde M05", () => {
  it("se abre sola al abrir la consulta y, al completar, pasa a M05 de la consulta nueva", async () => {
    const f = simularBackend({
      [GET_RESULTADO]: () => respuestaJson(200, resultadoFixture("DATOS_FALTANTES")),
      [`GET /api/pacientes/${ID_PACIENTE_FIXTURE}/consultas`]: () => respuestaJson(200, []),
      [POST_DATOS]: () => respuestaStream(lineasReanudadas("VERIFICADA")),
      [GET_REANUDADA]: () => respuestaJson(200, resultadoReanudado("VERIFICADA")),
    });
    renderizar(RUTA_M05);
    const ventana = await screen.findByRole("dialog", { name: "Falta información para evaluar" });
    expect(within(ventana).getByText(/La hemoglobina es necesaria para calcular la clasificación/)).toBeInTheDocument();
    fireEvent.change(campoHb(), { target: { value: "9.8" } });
    fireEvent.click(within(ventana).getByRole("button", { name: "Completar y evaluar" }));
    expect(await screen.findByRole("heading", { name: "Recomendación clínica" })).toBeInTheDocument();
    expect(cuerpo(f, POST_DATOS)).toEqual({ hemoglobina_g_dl: 9.8, metodo_medicion: "HEMOGLOBINOMETRO" });
    expect(screen.queryByRole("heading", { name: "Estado de la consulta" })).not.toBeInTheDocument();
  });

  it("si la consulta ya se reanudó, no abre la ventana y enlaza la consulta nueva", async () => {
    simularBackend({
      [GET_RESULTADO]: () => respuestaJson(200, resultadoFixture("DATOS_FALTANTES")),
      [`GET /api/pacientes/${ID_PACIENTE_FIXTURE}/consultas`]: () =>
        respuestaJson(200, [{ ...resultadoReanudado("VERIFICADA"), fecha_tamizaje: "2026-11-01",
                              confirma_tamizaje_no_vigente: false, categoria: null, tipo_decision: null }]),
    });
    renderizar(RUTA_M05);
    expect(await screen.findByRole("link", { name: "Ver la consulta reanudada" })).toHaveAttribute("href", `/consultas/${ID_CONSULTA_REANUDADA}`);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Completar datos" })).not.toBeInTheDocument();
  });
});

describe("M15 · Tamizaje no vigente", () => {
  it("desde M04 informa los días frente a la vigencia, advierte la cautela y «Continuar» reanuda con el avance", async () => {
    const stream = streamControlado();
    // Primer envío: TAMIZAJE_NO_VIGENTE; el segundo (la continuación) usa el stream controlado.
    let envios = 0;
    const f = simularBackend({
      [POST_CONSULTA]: () => (++envios === 1 ? respuestaStream(lineasFixture("TAMIZAJE_NO_VIGENTE")) : stream.respuesta()),
      [GET_REANUDADA]: () => respuestaJson(200, resultadoReanudado("VERIFICADA")),
    });
    renderizar();
    await escribirYEnviar();
    const ventana = await screen.findByRole("dialog", { name: "El tamizaje no está vigente" });
    expect(ventana).toHaveAccessibleDescription("La evaluación usaría el tamizaje registrado hace 84 días. El plazo de vigencia configurado es de 30 días.");
    expect(within(ventana).getByText("01/11/2026")).toBeInTheDocument(); // tamizaje disponible
    expect(within(ventana).getByText(AVISO_CONTINUAR)).toBeInTheDocument();
    expect(AVISO_CONTINUAR).toMatch(/tamizaje vencido/);
    expect(AVISO_CONTINUAR).toMatch(/con cautela/);
    const continuar = within(ventana).getByRole("button", { name: "Continuar con este tamizaje" });
    expect(continuar).toHaveAccessibleDescription(AVISO_CONTINUAR);

    fireEvent.click(continuar);
    await waitFor(() => expect(llamadas(f, POST_CONSULTA)).toHaveLength(2));
    expect(JSON.parse(String(llamadas(f, POST_CONSULTA)[1][1]!.body))).toEqual({
      texto_consulta: PREGUNTA, id_tamizaje: "t-0001", confirma_tamizaje_no_vigente: true, id_consulta_previa: ID_CONSULTA,
    });
    const lineas = lineasReanudadas("VERIFICADA");
    stream.enviar(lineas[0], lineas[1]);
    await waitFor(() => expect(within(ventana).getByText("Procesando la consulta…")).toBeInTheDocument());
    stream.enviar(...lineas.slice(2));
    stream.cerrar();
    expect(await screen.findByRole("heading", { name: "Recomendación clínica" })).toBeInTheDocument();
  });

  it("Esc cierra sin reenviar y el foco vuelve al campo de la consulta", async () => {
    const f = simularBackend({ [POST_CONSULTA]: () => respuestaStream(lineasFixture("TAMIZAJE_NO_VIGENTE")) });
    renderizar();
    await escribirYEnviar();
    const ventana = await screen.findByRole("dialog");
    await waitFor(() => expect(ventana.contains(document.activeElement)).toBe(true));
    fireEvent.keyDown(ventana, { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(document.activeElement).toBe(screen.getByLabelText("Consulta sobre el paciente"));
    expect(llamadas(f, POST_CONSULTA)).toHaveLength(1);
    expect(screen.getByRole("button", { name: "Revisar el tamizaje" })).toBeInTheDocument();
  });

  it("desde M05 se abre sola y «Continuar» reenvía la pregunta guardada con el tamizaje de la consulta", async () => {
    const f = simularBackend({
      [GET_RESULTADO]: () => respuestaJson(200, resultadoFixture("TAMIZAJE_NO_VIGENTE")),
      [`GET /api/pacientes/${ID_PACIENTE_FIXTURE}/consultas`]: () => respuestaJson(200, []),
      [POST_CONSULTA_FIXTURE]: () => respuestaStream(lineasReanudadas("VERIFICADA")),
      [GET_REANUDADA]: () => respuestaJson(200, resultadoReanudado("VERIFICADA")),
    });
    renderizar(RUTA_M05);
    const ventana = await screen.findByRole("dialog", { name: "El tamizaje no está vigente" });
    fireEvent.click(within(ventana).getByRole("button", { name: "Continuar con este tamizaje" }));
    expect(await screen.findByRole("heading", { name: "Recomendación clínica" })).toBeInTheDocument();
    expect(cuerpo(f, POST_CONSULTA_FIXTURE)).toEqual({
      texto_consulta: resultadoFixture("TAMIZAJE_NO_VIGENTE").texto_filtrado, id_tamizaje: ID_TAMIZAJE_FIXTURE,
      confirma_tamizaje_no_vigente: true, id_consulta_previa: ID_CONSULTA,
    });
  });
});

describe("M14 desde la consulta", () => {
  const TAMIZAJE_GUARDADO = {
    id_tamizaje: "t-0002", edad_meses: 16, motivo_sin_clasificacion: null,
    clasificacion: { categoria: "SIN_ANEMIA", nivel_riesgo: "BAJO", requiere_derivacion: false, altitud_msnm: 150,
                     ajuste_hb_g_dl: "0.0", hb_ajustada_g_dl: "11.5" },
  };

  it("«Registrar nuevo tamizaje» de M15 lleva a M14 y, al guardar, vuelve a M04 con la pregunta escrita", async () => {
    const f = simularBackend({
      [POST_CONSULTA]: () => respuestaStream(lineasFixture("TAMIZAJE_NO_VIGENTE")),
      [`POST /api/pacientes/${ID_PACIENTE}/tamizajes`]: () => respuestaJson(201, TAMIZAJE_GUARDADO),
    });
    renderizar();
    await escribirYEnviar();
    const ventana = await screen.findByRole("dialog");
    fireEvent.click(within(ventana).getByRole("button", { name: "Registrar nuevo tamizaje" }));
    expect(await screen.findByRole("heading", { name: "Nuevo tamizaje" })).toBeInTheDocument();
    expect(screen.getByText("Al guardar volverá a la consulta clínica con su pregunta.")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText(/^Hemoglobina \(g\/dL\)/), { target: { value: "11.5" } });
    fireEvent.click(screen.getByRole("button", { name: "Guardar" }));
    expect(await screen.findByRole("heading", { name: "Consulta clínica" })).toBeInTheDocument();
    expect(screen.getByLabelText("Consulta sobre el paciente")).toHaveValue(PREGUNTA);
    expect(screen.getByRole("status")).toHaveTextContent("Tamizaje registrado. Clasificación: Sin anemia");
    expect(llamadas(f, `POST /api/pacientes/${ID_PACIENTE}/tamizajes`)).toHaveLength(1);
  });

  it("desde el historial, M14 sigue volviendo al historial", async () => {
    simularBackend({
      [`POST /api/pacientes/${ID_PACIENTE}/tamizajes`]: () => respuestaJson(201, TAMIZAJE_GUARDADO),
      [`GET /api/pacientes/${ID_PACIENTE}/franjas`]: () => respuestaJson(200, []),
    });
    renderizar(`/pacientes/${ID_PACIENTE}/tamizajes/nuevo`);
    expect(await screen.findByRole("heading", { name: "Nuevo tamizaje" })).toBeInTheDocument();
    expect(screen.queryByText("Al guardar volverá a la consulta clínica con su pregunta.")).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText(/^Hemoglobina \(g\/dL\)/), { target: { value: "11.5" } });
    fireEvent.click(screen.getByRole("button", { name: "Guardar" }));
    expect(await screen.findByText(/Tamizaje registrado/)).toBeInTheDocument();
    expect(screen.queryByLabelText("Consulta sobre el paciente")).not.toBeInTheDocument();
  });
});

describe("Estados sin recomendación rediseñados", () => {
  const conEstado = (estado: EstadoFinal, lineas = lineasFixture(estado)) =>
    simularBackend({ [POST_CONSULTA]: () => respuestaStream(lineas) });

  it("FUERA_DE_DOMINIO: la tarjeta de avance marca los pasos restantes como no ejecutados", async () => {
    conEstado("FUERA_DE_DOMINIO");
    renderizar();
    await escribirYEnviar();
    await screen.findByText(TITULOS_ESTADO.FUERA_DE_DOMINIO);
    const avance = document.querySelector(".avance") as HTMLElement;
    const pasos = within(avance).getAllByRole("listitem");
    expect(pasos[0]).toHaveClass("avance__etapa--lista");
    pasos.slice(1).forEach((p) => {
      expect(p).toHaveClass("avance__etapa--omitida");
      expect(p).toHaveTextContent("no ejecutada");
    });
    expect(within(avance).getByText(/las restantes no se ejecutaron/)).toBeInTheDocument();
    expect(within(avance).getByRole("heading", { name: "Avance de la consulta" })).toBeInTheDocument();
    expect(within(avance).queryByRole("button", { name: "Cancelar" })).not.toBeInTheDocument();
    expect(screen.getByText(SUGERENCIA_FUERA_DE_DOMINIO)).toBeInTheDocument();
  });

  it("FUERA_DE_DOMINIO: «Reformular la pregunta» devuelve la pregunta al campo", async () => {
    conEstado("FUERA_DE_DOMINIO");
    renderizar();
    await escribirYEnviar();
    fireEvent.click(await screen.findByRole("button", { name: "Reformular la pregunta" }));
    const campo = screen.getByLabelText("Consulta sobre el paciente");
    expect(campo).toHaveValue(PREGUNTA);
    expect(document.activeElement).toBe(campo);
  });

  it("si el mensaje del backend es igual al título, se muestra una sola vez", async () => {
    const lineas = lineasFixture("FUERA_DE_DOMINIO");
    const fin = JSON.parse(lineas[lineas.length - 1]);
    fin.mensaje = `${TITULOS_ESTADO.FUERA_DE_DOMINIO}.`;
    lineas[lineas.length - 1] = JSON.stringify(fin);
    conEstado("FUERA_DE_DOMINIO", lineas);
    renderizar();
    await escribirYEnviar();
    await screen.findByText(TITULOS_ESTADO.FUERA_DE_DOMINIO);
    expect(screen.getAllByText(new RegExp(TITULOS_ESTADO.FUERA_DE_DOMINIO))).toHaveLength(1);
    expect(textoDesenlace("FUERA_DE_DOMINIO", fin.mensaje)).toBeNull();
  });

  it("ERROR: mensaje propio, clasificación debajo y «Reintentar» con la pregunta ya escrita", async () => {
    conEstado("ERROR");
    renderizar();
    await escribirYEnviar();
    const alerta = (await screen.findByText(MENSAJE_ERROR)).closest(".desenlace") as HTMLElement;
    expect(alerta).toHaveTextContent(TITULOS_ESTADO.ERROR);
    expect(screen.queryByText("No se pudo evaluar la consulta. Aplique su criterio clínico.")).not.toBeInTheDocument();
    const clasificacion = screen.getByRole("region", { name: "Clasificación del paciente" });
    expect(clasificacion).toHaveTextContent("Calculada por reglas a partir del tamizaje, no por el modelo.");
    expect(within(clasificacion).getByRole("heading", { level: 3 })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Reintentar" }));
    const campo = screen.getByLabelText("Consulta sobre el paciente");
    expect(campo).toHaveValue(PREGUNTA);
    expect(document.activeElement).toBe(campo);
    expect(screen.getByRole("button", { name: "Enviar" })).toBeEnabled();
  });

  it("SOLICITUD_BLOQUEADA: explica qué pasó y cómo reformular, sin repetir la pregunta", async () => {
    conEstado("SOLICITUD_BLOQUEADA");
    renderizar();
    const conDato = "¿Qué dosis le doy a Paciente Ficticio Uno?";
    await escribirYEnviar(conDato);
    const alerta = (await screen.findByText(MENSAJE_BLOQUEADA)).closest(".desenlace") as HTMLElement;
    expect(alerta).toHaveTextContent(COMO_REFORMULAR_BLOQUEADA);
    expect(alerta).not.toHaveTextContent("Paciente Ficticio Uno");
    fireEvent.click(screen.getByRole("button", { name: "Reformular la consulta" }));
    const campo = screen.getByLabelText("Consulta sobre el paciente");
    expect(campo).toHaveValue("");
    expect(document.activeElement).toBe(campo);
  });

  it("ERROR en M05: «Reintentar» lleva a M04 con la pregunta ya escrita", async () => {
    const r = resultadoFixture("ERROR");
    simularBackend({ [GET_RESULTADO]: () => respuestaJson(200, r) });
    renderizar(RUTA_M05);
    fireEvent.click(await screen.findByRole("button", { name: "Reintentar" }));
    expect(await screen.findByLabelText("Consulta sobre el paciente")).toHaveValue(r.texto_filtrado);
    expect(screen.getByRole("heading", { name: "Paciente Ficticio Dos" })).toBeInTheDocument();
  });

  it("SOLICITUD_BLOQUEADA en M05: «Reformular la consulta» lleva a M04 con el campo vacío", async () => {
    simularBackend({ [GET_RESULTADO]: () => respuestaJson(200, resultadoFixture("SOLICITUD_BLOQUEADA")) });
    renderizar(RUTA_M05);
    fireEvent.click(await screen.findByRole("button", { name: "Reformular la consulta" }));
    expect(await screen.findByLabelText("Consulta sobre el paciente")).toHaveValue("");
  });
});
