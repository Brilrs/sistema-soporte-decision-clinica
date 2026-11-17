// Pruebas de la parte E5: M07 (evidencia insuficiente con el detalle de la búsqueda) y la ventana
// «Registrar decisión clínica», con fetch simulado y los fixtures del contrato (sin API real).
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import App from "../App";
import { guardarToken, leerToken } from "../api/cliente";
import type { Decision, EstadoFinal, ResultadoConsulta, TipoDecision } from "../api/tipos_consulta";
import { AuthProvider } from "../auth/AuthContext";
import DecisionClinica from "../components/resultado/DecisionClinica";
import {
  AVISO_DECISION_DEFINITIVA,
  AVISO_NOTA_PRIVACIDAD,
  LARGO_MAXIMO_NOTA,
  MENSAJE_EVIDENCIA_INSUFICIENTE,
  SIN_PERMISO_DECISION,
  TIPOS_DECISION,
} from "../consulta/textos";
import {
  GET_RESULTADO,
  ID_CONSULTA,
  ID_PACIENTE,
  ID_PACIENTE_FIXTURE,
  POST_CONSULTA,
  USUARIO,
  lineasFixture,
  respuestaJson,
  respuestaStream,
  resultadoFixture,
  simularBackend,
} from "../pruebas/simulador";
import { fechaHora } from "../utilidades/formato";

const RUTA_M05 = `/consultas/${ID_CONSULTA}`;
const POST_DECISION = `POST /api/consultas/${ID_CONSULTA}/decision`;
const LISTA_FIXTURE = `GET /api/pacientes/${ID_PACIENTE_FIXTURE}/consultas`;

function renderizar(ruta = RUTA_M05) {
  guardarToken("token-de-prueba");
  return render(
    <MemoryRouter initialEntries={[ruta]}>
      <AuthProvider>
        <App />
      </AuthProvider>
    </MemoryRouter>,
  );
}

function decisionRegistrada(tipo: TipoDecision, nota: string | null): Decision {
  return { id_decision: "d-0001", id_usuario: USUARIO.id_usuario, tipo_decision: tipo, nota,
           fecha_registro: "2026-11-15T10:30:00-05:00" };
}

// GET del resultado (con cambios opcionales) y, si se da, el POST de la decisión.
function backend(estado: EstadoFinal, cambios: Partial<ResultadoConsulta> = {},
                 decidir?: (cuerpo: { tipo_decision: TipoDecision; nota: string | null }) => Response | Promise<Response>) {
  let resultado: ResultadoConsulta = { ...resultadoFixture(estado), ...cambios };
  const fetchFalso = simularBackend({
    [GET_RESULTADO]: () => respuestaJson(200, resultado),
    [LISTA_FIXTURE]: () => respuestaJson(200, []),
    ...(decidir ? { [POST_DECISION]: (init) => decidir(JSON.parse(String(init?.body))) } : {}),
  });
  return {
    fetchFalso,
    // Lo que devolverá el GET en adelante (por ejemplo, tras registrar la decisión).
    actualizar: (c: Partial<ResultadoConsulta>) => {
      resultado = { ...resultado, ...c };
    },
    posts: () => fetchFalso.mock.calls.filter(([r, i]) => i?.method === "POST" && String(r).endsWith("/decision")),
    gets: () => fetchFalso.mock.calls.filter(([r, i]) => !i?.method && r === `/api/consultas/${ID_CONSULTA}`).length,
  };
}

async function abrirVentana() {
  fireEvent.click(await screen.findByRole("button", { name: "Registrar decisión clínica" }));
  return screen.getByRole("dialog", { name: "Registrar decisión clínica" });
}

const etiqueta = (t: TipoDecision) => TIPOS_DECISION[t].etiqueta;

function elegir(ventana: HTMLElement, tipo: TipoDecision) {
  fireEvent.click(within(ventana).getByRole("radio", { name: new RegExp(etiqueta(tipo)) }));
}

function escribirNota(ventana: HTMLElement, texto: string) {
  fireEvent.change(within(ventana).getByLabelText(/Nota: conducta adoptada/), { target: { value: texto } });
}

// ---------------------------------------------------------------------------
// Estados y opciones
// ---------------------------------------------------------------------------
describe("decisión clínica · estados y opciones (opciones_decision)", () => {
  it("VERIFICADA: tres opciones; la nota es obligatoria solo con «Modifica la recomendación»", async () => {
    backend("VERIFICADA");
    renderizar();
    const ventana = await abrirVentana();
    const opciones = within(ventana).getAllByRole("radio");
    expect(opciones.map((o) => (o as HTMLInputElement).value)).toEqual(
      ["ACEPTA_RECOMENDACION", "MODIFICA_RECOMENDACION", "CRITERIO_CLINICO_PROPIO"]);
    // Ninguna elegida de antemano: el profesional decide.
    expect(opciones.every((o) => !(o as HTMLInputElement).checked)).toBe(true);
    const nota = within(ventana).getByLabelText(/Nota: conducta adoptada/);
    elegir(ventana, "ACEPTA_RECOMENDACION");
    expect(nota).not.toHaveAttribute("aria-required");
    expect(within(ventana).getByText("(opcional)")).toBeInTheDocument();
    elegir(ventana, "MODIFICA_RECOMENDACION");
    expect(nota).toHaveAttribute("aria-required", "true");
    expect(within(ventana).getByText("(obligatoria)")).toBeInTheDocument();
    elegir(ventana, "CRITERIO_CLINICO_PROPIO");
    expect(nota).not.toHaveAttribute("aria-required");
  });

  it.each(["EVIDENCIA_INSUFICIENTE", "ERROR"] as EstadoFinal[])(
    "%s: solo «Aplica su criterio clínico», ya elegida y con nota opcional", async (estado) => {
      backend(estado);
      renderizar();
      const ventana = await abrirVentana();
      const opciones = within(ventana).getAllByRole("radio");
      expect(opciones).toHaveLength(1);
      expect(opciones[0]).toHaveAccessibleName(expect.stringContaining(etiqueta("CRITERIO_CLINICO_PROPIO")));
      expect(opciones[0]).toBeChecked();
      expect(within(ventana).getByText("(opcional)")).toBeInTheDocument();
    });

  it.each(["DATOS_FALTANTES", "TAMIZAJE_NO_VIGENTE", "FUERA_DE_DOMINIO", "SOLICITUD_BLOQUEADA"] as EstadoFinal[])(
    "%s: no ofrece decisión", async (estado) => {
      backend(estado);
      renderizar();
      expect(await screen.findByRole("heading", { name: "Estado de la consulta" })).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Registrar decisión clínica" })).not.toBeInTheDocument();
      expect(screen.queryByText(SIN_PERMISO_DECISION)).not.toBeInTheDocument();
    });

  it("las opciones vienen del resultado, no de reglas propias de la interfaz", async () => {
    // Si el backend dijera que la nota es obligatoria con CRITERIO_CLINICO_PROPIO, se respeta.
    backend("ERROR", { opciones_decision: [{ tipo: "CRITERIO_CLINICO_PROPIO", nota_obligatoria: true }] });
    renderizar();
    const ventana = await abrirVentana();
    fireEvent.click(within(ventana).getByRole("button", { name: "Continuar" }));
    expect(await within(ventana).findByText(/la nota es obligatoria/)).toBeInTheDocument();
  });

  it("un rol sin permiso para decidir no ve el botón y recibe una nota", async () => {
    // La ruta /consultas/:id ya exige REALIZAR_CONSULTA; el componente se prueba solo.
    simularBackend({ "GET /api/auth/me": () => respuestaJson(200, { ...USUARIO, permisos: ["EXPORTAR_REPORTE"] }) });
    guardarToken("token-de-prueba");
    render(
      <MemoryRouter>
        <AuthProvider>
          <DecisionClinica idConsulta={ID_CONSULTA} decision={null} alRegistrar={() => undefined} alConflicto={() => undefined}
                           opciones={[{ tipo: "CRITERIO_CLINICO_PROPIO", nota_obligatoria: false }]} />
        </AuthProvider>
      </MemoryRouter>,
    );
    expect(await screen.findByText(SIN_PERMISO_DECISION)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Registrar decisión clínica" })).not.toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// Nota y confirmación
// ---------------------------------------------------------------------------
describe("decisión clínica · nota y confirmación", () => {
  it("sin tipo elegido avisa y lleva el foco a la primera opción", async () => {
    backend("VERIFICADA");
    renderizar();
    const ventana = await abrirVentana();
    fireEvent.click(within(ventana).getByRole("button", { name: "Continuar" }));
    expect(await within(ventana).findByText("Elija el tipo de decisión.")).toHaveAttribute("role", "alert");
    expect(within(ventana).getAllByRole("radio")[0]).toHaveFocus();
  });

  it("con «Modifica la recomendación» la nota vacía o con solo espacios no pasa", async () => {
    const b = backend("VERIFICADA", {}, () => respuestaJson(201, decisionRegistrada("MODIFICA_RECOMENDACION", "x")));
    renderizar();
    const ventana = await abrirVentana();
    elegir(ventana, "MODIFICA_RECOMENDACION");
    escribirNota(ventana, "   ");
    fireEvent.click(within(ventana).getByRole("button", { name: "Continuar" }));
    const nota = within(ventana).getByLabelText(/Nota: conducta adoptada/);
    expect(await within(ventana).findByText(/con esta opción la nota es obligatoria/)).toBeInTheDocument();
    expect(nota).toHaveAttribute("aria-invalid", "true");
    expect(nota).toHaveFocus();
    expect(nota).toHaveAccessibleDescription(expect.stringContaining("la nota es obligatoria"));
    expect(b.posts()).toHaveLength(0);
  });

  it("con una opción de nota opcional se puede continuar sin nota", async () => {
    backend("VERIFICADA");
    renderizar();
    const ventana = await abrirVentana();
    elegir(ventana, "ACEPTA_RECOMENDACION");
    fireEvent.click(within(ventana).getByRole("button", { name: "Continuar" }));
    expect(await within(ventana).findByRole("heading", { name: "Confirme la decisión" })).toBeInTheDocument();
    expect(within(ventana).getByText("Sin nota")).toBeInTheDocument();
  });

  it("muestra el aviso de privacidad, el contador y el límite del backend", async () => {
    backend("EVIDENCIA_INSUFICIENTE");
    renderizar();
    const ventana = await abrirVentana();
    const nota = within(ventana).getByLabelText(/Nota: conducta adoptada/);
    expect(nota).toHaveAccessibleDescription(expect.stringContaining(AVISO_NOTA_PRIVACIDAD));
    expect(within(ventana).getByText(`0 de ${LARGO_MAXIMO_NOTA} caracteres`)).toBeInTheDocument();
    escribirNota(ventana, "Indico sulfato ferroso y control en 30 días.");
    expect(within(ventana).getByText(`44 de ${LARGO_MAXIMO_NOTA} caracteres`)).toBeInTheDocument();
    escribirNota(ventana, "a".repeat(LARGO_MAXIMO_NOTA));
    fireEvent.click(within(ventana).getByRole("button", { name: "Continuar" }));
    expect(await within(ventana).findByRole("heading", { name: "Confirme la decisión" })).toBeInTheDocument();
    fireEvent.click(within(ventana).getByRole("button", { name: "Volver y corregir" }));
    escribirNota(ventana, "a".repeat(LARGO_MAXIMO_NOTA + 1));
    expect(within(ventana).getByText(`${LARGO_MAXIMO_NOTA + 1} de ${LARGO_MAXIMO_NOTA} caracteres`)).toBeInTheDocument();
    fireEvent.click(within(ventana).getByRole("button", { name: "Continuar" }));
    expect(await within(ventana).findByText(`La nota admite hasta ${LARGO_MAXIMO_NOTA} caracteres; tiene ${LARGO_MAXIMO_NOTA + 1}.`))
      .toBeInTheDocument();
  });

  it("pide confirmación antes de guardar y permite volver a corregir sin perder lo escrito", async () => {
    const b = backend("VERIFICADA", {}, () => respuestaJson(201, decisionRegistrada("MODIFICA_RECOMENDACION", "Dosis ajustada")));
    renderizar();
    const ventana = await abrirVentana();
    elegir(ventana, "MODIFICA_RECOMENDACION");
    escribirNota(ventana, "Dosis ajustada");
    fireEvent.click(within(ventana).getByRole("button", { name: "Continuar" }));
    const titulo = await within(ventana).findByRole("heading", { name: "Confirme la decisión" });
    expect(titulo).toHaveFocus();
    expect(within(ventana).getByText(AVISO_DECISION_DEFINITIVA)).toBeInTheDocument();
    expect(within(ventana).getByText(etiqueta("MODIFICA_RECOMENDACION"))).toBeInTheDocument();
    expect(within(ventana).getByText("Dosis ajustada")).toBeInTheDocument();
    expect(b.posts()).toHaveLength(0);
    fireEvent.click(within(ventana).getByRole("button", { name: "Volver y corregir" }));
    expect(within(ventana).getByRole("radio", { name: new RegExp(etiqueta("MODIFICA_RECOMENDACION")) })).toBeChecked();
    expect(within(ventana).getByLabelText(/Nota: conducta adoptada/)).toHaveValue("Dosis ajustada");
    expect(b.posts()).toHaveLength(0);
  });
});

// ---------------------------------------------------------------------------
// Registro y errores
// ---------------------------------------------------------------------------
async function confirmar(ventana: HTMLElement, tipo: TipoDecision, nota = "") {
  elegir(ventana, tipo);
  if (nota) escribirNota(ventana, nota);
  fireEvent.click(within(ventana).getByRole("button", { name: "Continuar" }));
  fireEvent.click(await within(ventana).findByRole("button", { name: "Confirmar y registrar" }));
}

describe("decisión clínica · registro", () => {
  it("201: envía tipo y nota sin espacios sobrantes, muestra la decisión y no permite repetirla", async () => {
    const registrada = decisionRegistrada("MODIFICA_RECOMENDACION", "Sulfato ferroso 3 mg/kg/día");
    const b = backend("VERIFICADA", {}, () => respuestaJson(201, registrada));
    renderizar();
    const ventana = await abrirVentana();
    await confirmar(ventana, "MODIFICA_RECOMENDACION", "  Sulfato ferroso 3 mg/kg/día  ");

    const panel = await screen.findByRole("region", { name: "Decisión clínica registrada" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(JSON.parse(String(b.posts()[0][1]?.body))).toEqual(
      { tipo_decision: "MODIFICA_RECOMENDACION", nota: "Sulfato ferroso 3 mg/kg/día" });
    expect(within(panel).getByText(etiqueta("MODIFICA_RECOMENDACION"))).toBeInTheDocument();
    expect(within(panel).getByText("Sulfato ferroso 3 mg/kg/día")).toBeInTheDocument();
    expect(within(panel).getByText(fechaHora(registrada.fecha_registro))).toBeInTheDocument();
    expect(within(panel).getByText(USUARIO.nombre_completo)).toBeInTheDocument();
    expect(within(panel).getByRole("heading", { name: "Decisión clínica registrada" })).toHaveFocus();
    // El botón queda deshabilitado: no se puede repetir.
    const boton = within(panel).getByRole("button", { name: "Registrar decisión clínica" });
    expect(boton).toBeDisabled();
    expect(boton).toHaveAccessibleDescription(/no se puede modificar ni registrar de nuevo/);
    expect(screen.getAllByRole("button", { name: "Registrar decisión clínica" }).every((x) => (x as HTMLButtonElement).disabled))
      .toBe(true);
    expect(b.posts()).toHaveLength(1);
    expect(screen.queryByText(/datos personales reemplazados/)).not.toBeInTheDocument();
  });

  it("201 sin nota: «Sin nota» y nota null en el cuerpo", async () => {
    const b = backend("EVIDENCIA_INSUFICIENTE", {}, () => respuestaJson(201, decisionRegistrada("CRITERIO_CLINICO_PROPIO", null)));
    renderizar();
    const ventana = await abrirVentana();
    await confirmar(ventana, "CRITERIO_CLINICO_PROPIO");
    const panel = await screen.findByRole("region", { name: "Decisión clínica registrada" });
    expect(within(panel).getByText("Sin nota")).toBeInTheDocument();
    expect(JSON.parse(String(b.posts()[0][1]?.body))).toEqual({ tipo_decision: "CRITERIO_CLINICO_PROPIO", nota: null });
  });

  it("si el backend guarda la nota distinta, lo avisa y muestra la guardada", async () => {
    backend("ERROR", {}, () => respuestaJson(201, decisionRegistrada("CRITERIO_CLINICO_PROPIO", "Control en [FECHA].")));
    renderizar();
    const ventana = await abrirVentana();
    await confirmar(ventana, "CRITERIO_CLINICO_PROPIO", "Control el 20/12/2026.");
    const panel = await screen.findByRole("region", { name: "Decisión clínica registrada" });
    expect(within(panel).getByText("Control en [FECHA].")).toBeInTheDocument();
    expect(within(panel).getByRole("status")).toHaveTextContent(
      "Por privacidad, el sistema guardó la nota con los datos personales reemplazados por marcas como [PACIENTE] o [DNI].");
  });

  it("al recargar, la decisión viene del GET y no se puede registrar otra", async () => {
    backend("VERIFICADA", { decision: decisionRegistrada("ACEPTA_RECOMENDACION", null), opciones_decision: [] });
    renderizar();
    const panel = await screen.findByRole("region", { name: "Decisión clínica registrada" });
    expect(within(panel).getByText(etiqueta("ACEPTA_RECOMENDACION"))).toBeInTheDocument();
    expect(within(panel).getByText("Sin nota")).toBeInTheDocument();
    expect(within(panel).getByText(USUARIO.nombre_completo)).toBeInTheDocument();
    expect(within(panel).getByRole("button", { name: "Registrar decisión clínica" })).toBeDisabled();
  });

  it("tras registrar, una recarga sigue mostrando la decisión (GET)", async () => {
    const registrada = decisionRegistrada("CRITERIO_CLINICO_PROPIO", "Derivo a pediatría.");
    const b = backend("EVIDENCIA_INSUFICIENTE", {}, () => respuestaJson(201, registrada));
    const vista = renderizar();
    await confirmar(await abrirVentana(), "CRITERIO_CLINICO_PROPIO", "Derivo a pediatría.");
    await screen.findByRole("region", { name: "Decisión clínica registrada" });
    // El backend ya la tiene: el GET la devuelve y opciones_decision viene vacía.
    b.actualizar({ decision: registrada, opciones_decision: [] });
    vista.unmount();
    renderizar();
    const panel = await screen.findByRole("region", { name: "Decisión clínica registrada" });
    expect(within(panel).getByText("Derivo a pediatría.")).toBeInTheDocument();
    expect(within(panel).getByRole("button", { name: "Registrar decisión clínica" })).toBeDisabled();
  });

  it("409: muestra el mensaje del backend, solo ofrece cerrar y al cerrar vuelve a pedir el resultado", async () => {
    const detalle = "La consulta ya tiene una decisión registrada";
    const b = backend("VERIFICADA", {}, () => respuestaJson(409, { detail: detalle }));
    renderizar();
    const ventana = await abrirVentana();
    await confirmar(ventana, "ACEPTA_RECOMENDACION");
    const alerta = await within(ventana).findByRole("alert");
    expect(alerta).toHaveTextContent(detalle);
    await waitFor(() => expect(alerta).toHaveFocus());
    expect(within(ventana).queryByRole("button", { name: "Confirmar y registrar" })).not.toBeInTheDocument();
    const antes = b.gets();
    b.actualizar({ decision: decisionRegistrada("CRITERIO_CLINICO_PROPIO", "Desde otra pestaña"), opciones_decision: [] });
    fireEvent.click(within(ventana).getByRole("button", { name: "Cerrar" }));
    await waitFor(() => expect(b.gets()).toBe(antes + 1));
    expect(await screen.findByText("Desde otra pestaña")).toBeInTheDocument();
  });

  it("404: muestra el mensaje del backend y no reintenta", async () => {
    const b = backend("ERROR", {}, () => respuestaJson(404, { detail: "Consulta no encontrada" }));
    renderizar();
    const ventana = await abrirVentana();
    await confirmar(ventana, "CRITERIO_CLINICO_PROPIO");
    expect(await within(ventana).findByRole("alert")).toHaveTextContent("Consulta no encontrada");
    expect(within(ventana).getByRole("button", { name: "Cerrar" })).toBeInTheDocument();
    const antes = b.gets();
    fireEvent.click(within(ventana).getByRole("button", { name: "Cerrar" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(b.gets()).toBe(antes);
    expect(b.posts()).toHaveLength(1);
  });

  it("422: vuelve al formulario con el mensaje del backend y el foco en la nota", async () => {
    const detalle = "Revise los datos ingresados. nota: admite como máximo 1000 caracteres";
    backend("VERIFICADA", {}, () => respuestaJson(422, { detail: detalle, errores: [] }));
    renderizar();
    const ventana = await abrirVentana();
    await confirmar(ventana, "MODIFICA_RECOMENDACION", "Cambio la dosis");
    expect(await within(ventana).findByRole("alert")).toHaveTextContent(detalle);
    expect(within(ventana).getByRole("button", { name: "Continuar" })).toBeInTheDocument();
    await waitFor(() => expect(within(ventana).getByLabelText(/Nota: conducta adoptada/)).toHaveFocus());
    expect(within(ventana).getByLabelText(/Nota: conducta adoptada/)).toHaveValue("Cambio la dosis");
  });

  it("401: cierra la sesión como en el resto de la aplicación", async () => {
    backend("EVIDENCIA_INSUFICIENTE", {}, () => respuestaJson(401, { detail: "Sesión no válida o expirada" }));
    renderizar();
    await confirmar(await abrirVentana(), "CRITERIO_CLINICO_PROPIO");
    expect(await screen.findByRole("heading", { name: "Iniciar sesión" })).toBeInTheDocument();
    expect(leerToken()).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// Accesibilidad de la ventana
// ---------------------------------------------------------------------------
describe("decisión clínica · accesibilidad de la ventana", () => {
  it("diálogo modal con título y descripción, foco en la primera opción, Esc y foco de vuelta", async () => {
    backend("VERIFICADA");
    renderizar();
    const boton = await screen.findByRole("button", { name: "Registrar decisión clínica" });
    fireEvent.click(boton);
    const ventana = screen.getByRole("dialog", { name: "Registrar decisión clínica" });
    expect(ventana).toHaveAttribute("aria-modal", "true");
    expect(ventana).toHaveAccessibleDescription(/La decisión final es suya/);
    expect(within(ventana).getAllByRole("radio")[0]).toHaveFocus();
    expect(within(ventana).getByRole("group", { name: /Tipo de decisión/ })).toBeInTheDocument();
    fireEvent.keyDown(ventana, { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(boton).toHaveFocus();
  });

  it("el foco queda atrapado en la ventana con Tab y Mayús + Tab", async () => {
    backend("ERROR");
    renderizar();
    const ventana = await abrirVentana();
    const continuar = within(ventana).getByRole("button", { name: "Continuar" });
    const primero = within(ventana).getByRole("radio");
    continuar.focus();
    fireEvent.keyDown(ventana, { key: "Tab" });
    expect(primero).toHaveFocus();
    fireEvent.keyDown(ventana, { key: "Tab", shiftKey: true });
    expect(continuar).toHaveFocus();
  });

  it("mientras guarda, Esc no la cierra y los botones quedan deshabilitados", async () => {
    let responder: (r: Response) => void = () => undefined;
    backend("VERIFICADA", {}, () => new Promise<Response>((r) => (responder = r)));
    renderizar();
    const ventana = await abrirVentana();
    await confirmar(ventana, "ACEPTA_RECOMENDACION");
    expect(await within(ventana).findByRole("button", { name: "Registrando…" })).toBeDisabled();
    fireEvent.keyDown(ventana, { key: "Escape" });
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    await act(async () => responder(respuestaJson(201, decisionRegistrada("ACEPTA_RECOMENDACION", null))));
    expect(await screen.findByRole("region", { name: "Decisión clínica registrada" })).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// M07: evidencia insuficiente
// ---------------------------------------------------------------------------
describe("M07 · evidencia insuficiente", () => {
  it("mensaje claro, qué puede hacer, clasificación en una columna y la acción para reformular", async () => {
    const r = resultadoFixture("EVIDENCIA_INSUFICIENTE");
    backend("EVIDENCIA_INSUFICIENTE");
    renderizar();
    const titulo = await screen.findByRole("heading", { name: "Estado de la consulta" });
    const tarjeta = titulo.closest("section") as HTMLElement;
    expect(within(tarjeta).getByRole("alert")).toHaveTextContent(MENSAJE_EVIDENCIA_INSUFICIENTE);
    expect(within(tarjeta).getByRole("heading", { name: "Qué puede hacer" })).toBeInTheDocument();
    expect(within(tarjeta).getByText(/administrador evalúe incorporar nuevas guías/)).toBeInTheDocument();
    expect(within(tarjeta).getByRole("button", { name: "Reformular la consulta" })).toBeInTheDocument();
    expect(within(tarjeta).getByRole("button", { name: "Registrar decisión clínica" })).toBeEnabled();
    const clasificacion = screen.getByRole("region", { name: "Clasificación del paciente" });
    expect(clasificacion.parentElement).toBe(tarjeta.parentElement);
    expect(tarjeta.parentElement).toHaveClass("estado-consulta");
    // Sin recomendación y sin citas inventadas; la verificación sí vino en la respuesta.
    expect(screen.queryByRole("heading", { name: "Recomendación clínica" })).not.toBeInTheDocument();
    expect(r.citas).toHaveLength(0);
    expect(screen.queryByRole("heading", { name: "Evidencias citadas" })).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Verificación de la respuesta" })).toBeInTheDocument();
  });

  it("detalle de la búsqueda con dos intentos: desplegable y con los valores del backend", async () => {
    backend("EVIDENCIA_INSUFICIENTE");
    renderizar();
    const resumen = await screen.findByText("Detalle de la búsqueda");
    const detalle = resumen.closest("details") as HTMLDetailsElement;
    expect(detalle.open).toBe(false);
    fireEvent.click(resumen);
    await waitFor(() => expect(detalle.open).toBe(true));
    const filas = within(detalle).getAllByRole("row").slice(1);
    expect(filas).toHaveLength(2);
    // Fixture: 6 candidatos, relevancia 0.237, umbral 0.050 (parámetros de la base de pruebas).
    expect(filas.map((f) => within(f).getAllByRole("cell").map((c) => c.textContent))).toEqual([
      ["Búsqueda inicial", "6", "0.237", "0.050", "Se reintentó"],
      ["Búsqueda ampliada", "6", "0.237", "0.050", "Evidencia insuficiente"],
    ]);
    expect(within(filas[0]).getByRole("rowheader")).toHaveTextContent("1");
    expect(within(detalle).getByText(/Se hicieron 2 búsquedas/)).toBeInTheDocument();
  });

  it("detalle de la búsqueda con un intento y los parámetros de producción (8 candidatos, umbral 0.150)", async () => {
    backend("EVIDENCIA_INSUFICIENTE", {
      numero_intentos: 1,
      intentos: [{ numero: 1, tipo_busqueda: "INICIAL", candidatos_evaluados: 8, relevancia_maxima: 0.1, umbral_relevancia: 0.15,
                   resultado: "EVIDENCIA_INSUFICIENTE" }],
      verificacion: null,
    });
    renderizar();
    const resumen = await screen.findByText("Detalle de la búsqueda");
    fireEvent.click(resumen);
    const detalle = resumen.closest("details") as HTMLElement;
    const filas = within(detalle).getAllByRole("row").slice(1);
    expect(within(filas[0]).getAllByRole("cell").map((c) => c.textContent))
      .toEqual(["Búsqueda inicial", "8", "0.100", "0.150", "Evidencia insuficiente"]);
    expect(within(detalle).getByText(/Se hizo 1 búsqueda/)).toBeInTheDocument();
    // Sin verificación en la respuesta: no se muestra ninguna.
    expect(screen.queryByRole("heading", { name: "Verificación de la respuesta" })).not.toBeInTheDocument();
  });

  it("si la respuesta trae citas, las muestra tal como vienen", async () => {
    const citas = resultadoFixture("VERIFICADA").citas;
    backend("EVIDENCIA_INSUFICIENTE", { citas });
    renderizar();
    expect(await screen.findByRole("heading", { name: "Evidencias citadas" })).toBeInTheDocument();
    expect(screen.getByText(citas[0].extracto)).toBeInTheDocument();
  });

  it("una relevancia sin fragmentos se muestra como tal, sin inventar un valor", async () => {
    backend("EVIDENCIA_INSUFICIENTE", {
      intentos: [{ numero: 1, tipo_busqueda: "INICIAL", candidatos_evaluados: 0, relevancia_maxima: null, umbral_relevancia: 0.15,
                   resultado: "EVIDENCIA_INSUFICIENTE" }],
    });
    renderizar();
    fireEvent.click(await screen.findByText("Detalle de la búsqueda"));
    expect(screen.getByRole("cell", { name: "Sin fragmentos" })).toBeInTheDocument();
  });

  it("desde M04, una consulta con evidencia insuficiente abre M07 con el detalle", async () => {
    simularBackend({
      [POST_CONSULTA]: () => respuestaStream(lineasFixture("EVIDENCIA_INSUFICIENTE")),
      [GET_RESULTADO]: () => respuestaJson(200, resultadoFixture("EVIDENCIA_INSUFICIENTE")),
      [LISTA_FIXTURE]: () => respuestaJson(200, []),
    });
    renderizar(`/pacientes/${ID_PACIENTE}/consulta`);
    fireEvent.change(await screen.findByLabelText("Consulta sobre el paciente"),
                     { target: { value: "¿Cuántas horas espero entre el antiparasitario y el hierro?" } });
    fireEvent.click(screen.getByRole("button", { name: "Enviar" }));
    expect(await screen.findByText("Detalle de la búsqueda")).toBeInTheDocument();
    expect(screen.getByText(MENSAJE_EVIDENCIA_INSUFICIENTE)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Registrar decisión clínica" })).toBeEnabled();
  });

  it("desde el ERROR de M04, «Registrar decisión clínica» abre M05 con la ventana", async () => {
    simularBackend({
      [POST_CONSULTA]: () => respuestaStream(lineasFixture("ERROR")),
      [GET_RESULTADO]: () => respuestaJson(200, resultadoFixture("ERROR")),
    });
    renderizar(`/pacientes/${ID_PACIENTE}/consulta`);
    fireEvent.change(await screen.findByLabelText("Consulta sobre el paciente"),
                     { target: { value: "¿Qué dosis de hierro le corresponde?" } });
    fireEvent.click(screen.getByRole("button", { name: "Enviar" }));
    fireEvent.click(await screen.findByRole("button", { name: "Registrar decisión clínica" }));
    const ventana = await screen.findByRole("dialog", { name: "Registrar decisión clínica" });
    expect(within(ventana).getByRole("radio")).toBeChecked();
    // La cabecera con el nombre depende de la ficha, que llega después del resultado.
    expect(await screen.findByRole("heading", { level: 1, name: "Paciente Ficticio Dos" })).toBeInTheDocument();
  });
});
