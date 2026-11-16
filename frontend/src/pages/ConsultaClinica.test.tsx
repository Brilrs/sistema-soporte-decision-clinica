// Pruebas de M04 (parte E2) con fetch simulado y los streams de los fixtures del contrato.
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import { guardarToken, leerToken } from "../api/cliente";
import { ESTADOS_FINALES, type EstadoFinal } from "../api/tipos_consulta";
import { AuthProvider } from "../auth/AuthContext";
import { decimal } from "../utilidades/formato";
import { ETAPAS } from "../consulta/avance";
import { EJEMPLO_CONSULTA } from "./ConsultaClinica";
import { MENSAJE_ERROR, SUGERENCIA_FUERA_DE_DOMINIO } from "../consulta/textos";
import { textoDesenlace } from "../components/MensajeDesenlace";
import {
  GET_RESULTADO,
  ID_CONSULTA,
  ID_PACIENTE,
  POST_CONSULTA,
  lineasFixture,
  respuestaJson,
  respuestaStream,
  resultadoFixture,
  simularBackend,
  streamControlado,
} from "../pruebas/simulador";

const RUTA_M04 = `/pacientes/${ID_PACIENTE}/consulta`;
const PREGUNTA = "¿Qué dosis de hierro corresponde según su hemoglobina?";

function renderizar(ruta = RUTA_M04) {
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

function estadosEtapas(): string[] {
  const lista = document.querySelector(".avance__etapas") as HTMLElement;
  return within(lista)
    .getAllByRole("listitem")
    .map((li) => li.className.replace(/^.*avance__etapa--/, ""));
}

const anuncio = () => document.querySelector(".avance [aria-live]")?.textContent ?? "";

afterEach(() => {
  vi.useRealTimers();
});

describe("M04 · Consulta clínica", () => {
  it("muestra la cabecera, el contexto de la sesión y el aviso de privacidad", async () => {
    simularBackend({
      [`GET /api/pacientes/${ID_PACIENTE}/consultas`]: () =>
        respuestaJson(200, [{ ...resultadoFixture("VERIFICADA"), fecha_tamizaje: "2026-11-01", confirma_tamizaje_no_vigente: false,
          tipo_decision: null, texto_filtrado: "¿Dosis de hierro para [PACIENTE]?" }]),
    });
    renderizar();
    expect(await screen.findByRole("heading", { name: "Paciente Ficticio Uno" })).toBeInTheDocument();
    const contexto = screen.getByRole("complementary", { name: "Contexto de la sesión" });
    expect(within(contexto).getByText("01/11/2026")).toBeInTheDocument();
    expect(within(contexto).getByText("Vigente")).toBeInTheDocument();
    expect(within(contexto).getByText("Anemia leve")).toBeInTheDocument();
    expect(within(contexto).getByText("Palidez")).toBeInTheDocument();
    expect(within(contexto).getByText("Lactancia materna actual · Sin suplementación con hierro")).toBeInTheDocument();
    expect(within(contexto).getByText(`12/05/2026 · Hb ${decimal("10.1")} g/dL · Anemia leve`)).toBeInTheDocument();
    expect(await within(contexto).findByText("¿Dosis de hierro para [PACIENTE]?")).toBeInTheDocument();
    expect(within(contexto).getByText("Prueba")).toBeInTheDocument();
    const aviso = screen.getByText(/No escriba nombres, DNI, historia clínica ni teléfonos/);
    expect(aviso).toHaveTextContent("El sistema ya conoce los datos del paciente");
    expect(aviso).toHaveTextContent("hierro, hemoglobina, anemia, derivación o controles");
    expect(aviso).not.toHaveTextContent("«el paciente»");
    expect(screen.getByLabelText("Consulta sobre el paciente")).toHaveAttribute("placeholder", EJEMPLO_CONSULTA);
    expect(EJEMPLO_CONSULTA).toMatch(/hierro.*hemoglobina/);
    expect(screen.getByRole("button", { name: "+ Nuevo tamizaje" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Enviar" })).toBeDisabled(); // sin texto
  });

  it("muestra las etapas en orden desde el primer evento y deshabilita el envío durante la consulta", async () => {
    const stream = streamControlado();
    const f = simularBackend({ [POST_CONSULTA]: stream.respuesta, [GET_RESULTADO]: () => respuestaJson(200, resultadoFixture("VERIFICADA")) });
    renderizar();
    await escribirYEnviar();

    expect(screen.getByText(PREGUNTA)).toBeInTheDocument();
    const boton = screen.getByRole("button", { name: "Consultando…" });
    expect(boton).toBeDisabled();
    const lista = document.querySelector(".avance__etapas") as HTMLElement;
    expect(within(lista).getAllByRole("listitem").map((li) => li.textContent)).toEqual(
      ETAPAS.map((e, i) => `${i + 1}${e.texto} (${i === 0 ? "en curso" : "pendiente"})`),
    );

    const lineas = lineasFixture("VERIFICADA");
    stream.enviar(lineas[0]); // validar
    await waitFor(() => expect(estadosEtapas()).toEqual(["lista", "en_curso", "pendiente", "pendiente", "pendiente", "pendiente"]));
    expect(anuncio()).toBe("Calculando clasificación (NTS 213-MINSA / OMS 2024).");

    stream.enviar(lineas[1], lineas[2]); // clasificar, normalizar: la búsqueda sigue en curso
    await waitFor(() => expect(estadosEtapas()).toEqual(["lista", "lista", "en_curso", "pendiente", "pendiente", "pendiente"]));
    stream.enviar(lineas[3], lineas[4]); // recuperar, proteger
    await waitFor(() => expect(estadosEtapas().slice(2)).toEqual(["lista", "lista", "en_curso", "pendiente"]));
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "4");
    expect(screen.getByRole("button", { name: "Consultando…" })).toBeDisabled();

    // Cuerpo de la consulta: solo el texto escrito.
    const [, init] = f.mock.calls.find(([r, i]) => `${i?.method} ${r}` === POST_CONSULTA)!;
    expect(JSON.parse(init?.body as string)).toEqual({ texto_consulta: PREGUNTA });

    stream.enviar(...lineas.slice(5));
    stream.cerrar();
    // M05 se muestra con el evento fin y el GET completa la pregunta.
    expect(await screen.findByRole("heading", { name: "Recomendación clínica" })).toBeInTheDocument();
    expect(screen.getByText(resultadoFixture("VERIFICADA").recomendacion!.resumen)).toBeInTheDocument();
  });

  it("marca el segundo intento con búsqueda ampliada", async () => {
    const stream = streamControlado();
    simularBackend({ [POST_CONSULTA]: stream.respuesta });
    renderizar();
    await escribirYEnviar();
    const lineas = lineasFixture("EVIDENCIA_INSUFICIENTE");
    stream.enviar(...lineas.slice(0, 7)); // hasta verificar con siguiente AMPLIADA
    expect(await screen.findByText(/Intento 2: búsqueda ampliada/)).toBeInTheDocument();
    expect(estadosEtapas()).toEqual(["lista", "lista", "en_curso", "pendiente", "pendiente", "pendiente"]);
    stream.cerrar();
  });

  it("muestra el aviso de espera con el evento en_cola y lo quita al avanzar", async () => {
    const stream = streamControlado();
    simularBackend({ [POST_CONSULTA]: stream.respuesta });
    renderizar();
    await escribirYEnviar();
    const lineas = lineasFixture("VERIFICADA");
    stream.enviar(...lineas.slice(0, 5), { tipo: "en_cola", etapa: "generar", recurso: "llm", transcurrido_ms: 700 });
    expect(await screen.findByText(/En espera: el servicio de generación está atendiendo otras consultas/, { selector: ".avance__cola" }))
      .toBeInTheDocument();
    expect(anuncio()).toBe("En espera: el servicio de generación está atendiendo otras consultas.");
    stream.enviar(lineas[5]);
    await waitFor(() => expect(screen.queryByText(/En espera:/, { selector: ".avance__cola" })).not.toBeInTheDocument());
    stream.cerrar();
  });

  it("«Cancelar» corta la espera, avisa que la consulta puede quedar registrada y libera el envío", async () => {
    const stream = streamControlado();
    const f = simularBackend({ [POST_CONSULTA]: stream.respuesta });
    renderizar();
    await escribirYEnviar();
    stream.enviar(lineasFixture("VERIFICADA")[0]);
    await waitFor(() => expect(estadosEtapas()[0]).toBe("lista"));
    fireEvent.click(screen.getByRole("button", { name: "Cancelar" }));
    expect(await screen.findByText(/Se canceló la espera\. La consulta puede terminar igual en el servidor/)).toBeInTheDocument();
    await waitFor(() => expect(stream.cancelado).toBe(true));
    expect(screen.queryByRole("button", { name: "Cancelar" })).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Consulta sobre el paciente"), { target: { value: "otra" } });
    expect(screen.getByRole("button", { name: "Enviar" })).toBeEnabled();
    // Se vuelve a cargar la lista de consultas previas (la consulta pudo quedar registrada).
    const listados = f.mock.calls.filter(([r, i]) => !i?.method && r === `/api/pacientes/${ID_PACIENTE}/consultas`).length;
    expect(listados).toBe(2);
  });

  it("al salir de la pantalla cancela la consulta en curso", async () => {
    const stream = streamControlado();
    simularBackend({ [POST_CONSULTA]: stream.respuesta });
    renderizar();
    await escribirYEnviar();
    stream.enviar(lineasFixture("VERIFICADA")[0]);
    await waitFor(() => expect(estadosEtapas()[0]).toBe("lista"));
    fireEvent.click(screen.getByRole("button", { name: "Historial" }));
    expect(await screen.findByText("Tamizajes registrados")).toBeInTheDocument();
    await waitFor(() => expect(stream.cancelado).toBe(true));
  });

  it.each([...ESTADOS_FINALES])("%s: llega a su resultado o a su mensaje", async (estado: EstadoFinal) => {
    const lineas = lineasFixture(estado);
    simularBackend({ [POST_CONSULTA]: () => respuestaStream(lineas), [GET_RESULTADO]: () => respuestaJson(200, resultadoFixture(estado)) });
    renderizar();
    await escribirYEnviar();
    const fin = JSON.parse(lineas[lineas.length - 1]);
    if (estado === "VERIFICADA" || estado === "EVIDENCIA_INSUFICIENTE") {
      const titulo = estado === "VERIFICADA" ? "Recomendación clínica" : "Estado de la consulta";
      expect(await screen.findByRole("heading", { name: titulo })).toBeInTheDocument();
      expect(screen.getByText(/MODO DE PRUEBA: respuesta no clínica/)).toBeInTheDocument(); // modo_prueba en el fixture
    } else {
      const alerta = await screen.findByText(textoDesenlace(estado, fin.mensaje)!);
      expect(alerta.closest(".desenlace")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Enviar" })).toBeDisabled(); // sin texto, pero ya no en curso
      expect(screen.queryByText(/MODO DE PRUEBA/)).not.toBeInTheDocument();
      // La tarjeta de avance ya no ofrece «Cancelar» (las ventanas M06 y M15 tienen el suyo).
      expect(within(document.querySelector(".avance") as HTMLElement).queryByRole("button", { name: "Cancelar" }))
        .not.toBeInTheDocument();
    }
  });

  it("FUERA_DE_DOMINIO conserva el mensaje del backend y sugiere reformular con el tema", async () => {
    const lineas = lineasFixture("FUERA_DE_DOMINIO");
    simularBackend({ [POST_CONSULTA]: () => respuestaStream(lineas) });
    renderizar();
    await escribirYEnviar();
    const fin = JSON.parse(lineas[lineas.length - 1]);
    const desenlace = (await screen.findByText(fin.mensaje)).closest(".desenlace") as HTMLElement;
    expect(within(desenlace).getByText("Consulta fuera del alcance del sistema")).toBeInTheDocument();
    const sugerencia = within(desenlace).getByText(SUGERENCIA_FUERA_DE_DOMINIO);
    expect(sugerencia).toHaveTextContent(/hierro, hemoglobina, anemia o derivación/);
    // La sugerencia va debajo del texto del backend.
    expect(sugerencia.previousElementSibling).toHaveTextContent(fin.mensaje);
  });

  it.each(["ERROR", "DATOS_FALTANTES", "TAMIZAJE_NO_VIGENTE", "SOLICITUD_BLOQUEADA"] as EstadoFinal[])(
    "%s no muestra la sugerencia de FUERA_DE_DOMINIO", async (estado) => {
      const lineas = lineasFixture(estado);
      simularBackend({ [POST_CONSULTA]: () => respuestaStream(lineas) });
      renderizar();
      await escribirYEnviar();
      expect(await screen.findByText(textoDesenlace(estado, JSON.parse(lineas[lineas.length - 1]).mensaje)!)).toBeInTheDocument();
      expect(screen.queryByText(SUGERENCIA_FUERA_DE_DOMINIO)).not.toBeInTheDocument();
    });

  it("muestra el aviso de modo de prueba en un estado que se informa en M04", async () => {
    const lineas = lineasFixture("ERROR");
    lineas[lineas.length - 1] = lineas[lineas.length - 1].replace('"modo_prueba": false', '"modo_prueba": true');
    simularBackend({ [POST_CONSULTA]: () => respuestaStream(lineas) });
    renderizar();
    await escribirYEnviar();
    expect(await screen.findByText(/MODO DE PRUEBA: respuesta no clínica/)).toBeInTheDocument();
    expect(screen.getByText(MENSAJE_ERROR)).toBeInTheDocument();
  });

  it("el evento error del stream se muestra como estado final", async () => {
    const error = {
      tipo: "error", id_consulta: ID_CONSULTA, id_paciente: ID_PACIENTE, estado: "ERROR",
      mensaje: "No se pudo evaluar la consulta. Aplique su criterio clínico.",
      opciones_decision: [{ tipo: "CRITERIO_CLINICO_PROPIO", nota_obligatoria: false }], transcurrido_ms: 300,
    };
    simularBackend({ [POST_CONSULTA]: () => respuestaStream([lineasFixture("VERIFICADA")[0], JSON.stringify(error)]) });
    renderizar();
    await escribirYEnviar();
    // El texto genérico del backend se reemplaza por el mensaje de ERROR con «Reintentar».
    expect(await screen.findByText(MENSAJE_ERROR)).toBeInTheDocument();
    expect(screen.queryByText(error.mensaje)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reintentar" })).toBeInTheDocument();
  });

  it.each([
    [403, "No tiene permiso para realizar consultas"],
    [404, "El paciente no existe"],
    [409, "La consulta previa ya se reanudó"],
    [422, "El paciente no tiene tamizajes registrados"],
  ])("un %i antes del stream muestra el mensaje del backend", async (codigo, detalle) => {
    simularBackend({ [POST_CONSULTA]: () => respuestaJson(codigo, { detail: detalle }) });
    renderizar();
    await escribirYEnviar();
    expect(await screen.findByText(detalle)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Ver resultado" })).not.toBeInTheDocument();
    expect(leerToken()).toBe("token-de-prueba");
  });

  it("si el stream se corta, recupera el resultado guardado sin reenviar la consulta", async () => {
    const f = simularBackend({
      [POST_CONSULTA]: () => respuestaStream(lineasFixture("DATOS_FALTANTES").slice(0, 1)),
      [GET_RESULTADO]: () => respuestaJson(200, resultadoFixture("DATOS_FALTANTES")),
    });
    renderizar();
    await escribirYEnviar();
    expect(await screen.findByText(/Faltan datos obligatorios del tamizaje: hemoglobina/)).toBeInTheDocument();
    expect(f.mock.calls.filter(([r, i]) => `${i?.method ?? "GET"} ${r}` === POST_CONSULTA)).toHaveLength(1);
    expect(f.mock.calls.some(([r]) => r === `/api/consultas/${ID_CONSULTA}`)).toBe(true);
  });

  it("si el resultado sigue en proceso pasados 60 s, muestra el error con «Ver resultado»", async () => {
    const enProceso = { ...resultadoFixture("VERIFICADA"), estado: "EN_PROCESO" };
    const f = simularBackend({
      [POST_CONSULTA]: () => respuestaStream(lineasFixture("VERIFICADA").slice(0, 3)),
      [GET_RESULTADO]: () => respuestaJson(200, enProceso),
    });
    renderizar();
    const campo = await screen.findByLabelText("Consulta sobre el paciente");
    // Con temporizadores simulados no se usa findBy (espera con temporizadores reales).
    vi.useFakeTimers();
    fireEvent.change(campo, { target: { value: PREGUNTA } });
    fireEvent.click(screen.getByRole("button", { name: "Enviar" }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(anuncio()).toBe("Se interrumpió la conexión. Recuperando el resultado guardado.");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000);
    });
    expect(screen.getByText(/La consulta sigue en proceso/)).toBeInTheDocument();
    expect(f.mock.calls.filter(([r]) => r === `/api/consultas/${ID_CONSULTA}`)).toHaveLength(31);
    vi.useRealTimers();
    fireEvent.click(screen.getByRole("button", { name: "Ver resultado" }));
    expect(await screen.findByRole("heading", { name: "En proceso" })).toBeInTheDocument();
  });

  it("un 401 del stream cierra la sesión en pantalla", async () => {
    simularBackend({ [POST_CONSULTA]: () => respuestaJson(401, { detail: "Sesión no válida o expirada" }) });
    renderizar();
    await escribirYEnviar();
    expect(await screen.findByRole("heading", { name: "Iniciar sesión" })).toBeInTheDocument();
    expect(screen.getByText("Su sesión expiró o ya no es válida. Inicie sesión nuevamente.")).toBeInTheDocument();
    expect(leerToken()).toBeNull();
  });

  it("un 401 de cualquier llamada JSON también cierra la sesión", async () => {
    simularBackend({ [`GET /api/pacientes/${ID_PACIENTE}/historial`]: () => respuestaJson(401, { detail: "Sesión no válida o expirada" }) });
    renderizar();
    expect(await screen.findByRole("heading", { name: "Iniciar sesión" })).toBeInTheDocument();
    expect(leerToken()).toBeNull();
  });

  it("sin tamizajes no permite consultar", async () => {
    simularBackend({ [`GET /api/pacientes/${ID_PACIENTE}/historial`]: () => respuestaJson(200, { id_paciente: ID_PACIENTE, tamizajes: [], franjas: [], consultas: [] }) });
    renderizar();
    expect(await screen.findByText(/El paciente aún no tiene tamizajes/)).toBeInTheDocument();
    expect(screen.getByLabelText("Consulta sobre el paciente")).toBeDisabled();
  });
});

describe("accesos a M04", () => {
  it("«Nueva consulta» en el historial (M08) abre la consulta clínica", async () => {
    simularBackend();
    renderizar(`/pacientes/${ID_PACIENTE}/historial`);
    fireEvent.click(await screen.findByRole("button", { name: "Nueva consulta" }));
    expect(await screen.findByRole("heading", { name: "Consulta clínica" })).toBeInTheDocument();
  });

  it("«Abrir» en el panel de pacientes (M02) abre la consulta clínica", async () => {
    simularBackend({
      "GET /api/pacientes": () =>
        respuestaJson(200, [{ id_paciente: ID_PACIENTE, nombres_apellidos: "Paciente Ficticio Uno", numero_hc: "HC-PRUEBA-1", sexo: "M",
          edad_meses_actual: 16, ultimo_tamizaje: null }]),
      "GET /api/pacientes/indicadores": () =>
        respuestaJson(200, { evaluaciones_hoy: 0, con_anemia_detectada: 0, controles_pendientes: 0, tiempo_medio_respuesta_s: null, dias_vigencia_tamizaje: 30 }),
    });
    renderizar("/pacientes");
    fireEvent.click(await screen.findByRole("button", { name: "Abrir" }));
    expect(await screen.findByRole("heading", { name: "Consulta clínica" })).toBeInTheDocument();
  });

  it("un rol sin REALIZAR_CONSULTA no entra a M04 ni ve «Nueva consulta»", async () => {
    simularBackend({ "GET /api/auth/me": () => respuestaJson(200, { id_usuario: "u-2", nombre_usuario: "adm", nombre_completo: "Admin Prueba",
      rol: "Administrador", permisos: ["ADMINISTRAR_USUARIOS"] }) });
    renderizar();
    await waitFor(() => expect(screen.queryByText("Cargando…")).not.toBeInTheDocument());
    expect(screen.queryByRole("heading", { name: "Consulta clínica" })).not.toBeInTheDocument();
  });
});
