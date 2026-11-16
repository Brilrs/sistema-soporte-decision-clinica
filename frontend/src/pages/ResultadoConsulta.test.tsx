// Pruebas de M05 (parte E3) con fetch simulado y los resultados de los fixtures del contrato.
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import { guardarToken } from "../api/cliente";
import type { EstadoFinal, EventoFin, ResultadoConsulta } from "../api/tipos_consulta";
import { AuthProvider } from "../auth/AuthContext";
import { AVISO_DECISION, SUGERENCIA_FUERA_DE_DOMINIO, TITULOS_ESTADO } from "../consulta/textos";
import { textoDesenlace } from "../components/MensajeDesenlace";
import {
  GET_RESULTADO,
  HISTORIAL_FIXTURE,
  ID_CONSULTA,
  ID_PACIENTE_FIXTURE,
  lineasFixture,
  respuestaJson,
  resultadoFixture,
  simularBackend,
} from "../pruebas/simulador";
import { decimal, fechaHora } from "../utilidades/formato";

const RUTA = `/consultas/${ID_CONSULTA}`;

function renderizar(entrada: string | { pathname: string; state: unknown } = RUTA) {
  guardarToken("token-de-prueba");
  return render(
    <MemoryRouter initialEntries={[entrada]}>
      <AuthProvider>
        <App />
      </AuthProvider>
    </MemoryRouter>,
  );
}

function conResultado(r: ResultadoConsulta) {
  return simularBackend({ [GET_RESULTADO]: () => respuestaJson(200, r) });
}

const llamadasGet = (f: ReturnType<typeof simularBackend>) =>
  f.mock.calls.filter(([r, i]) => !i?.method && r === `/api/consultas/${ID_CONSULTA}`).length;

afterEach(() => {
  vi.useRealTimers();
});

describe("M05 · Resultado de la consulta (VERIFICADA)", () => {
  it("muestra cabecera, pregunta, riesgo, recomendación, citas, verificación, aviso y acciones", async () => {
    const r = resultadoFixture("VERIFICADA");
    conResultado(r);
    renderizar();

    expect(await screen.findByRole("heading", { level: 1, name: "Paciente Ficticio Dos" })).toBeInTheDocument();
    const cabecera = screen.getByRole("heading", { level: 1 }).closest(".resultado__cabecera") as HTMLElement;
    expect(cabecera).toHaveTextContent("HC HC-PRUEBA-2");
    // El fixture tiene 15 meses en el tamizaje y 16 hoy.
    expect(cabecera).toHaveTextContent("15 meses al tamizaje (hoy 16 meses)");
    expect(cabecera).toHaveTextContent(`Consulta del ${fechaHora(r.fecha_hora_inicio)}`);
    expect(within(cabecera).getByText(r.texto_filtrado!)).toBeInTheDocument();

    // Riesgo y clasificación
    const riesgo = screen.getByRole("region", { name: "Nivel de riesgo" });
    expect(within(riesgo).getByText("BAJO")).toBeInTheDocument();
    expect(within(riesgo).getByText("Sin anemia")).toBeInTheDocument();
    expect(riesgo).toHaveTextContent(`Hb observada${decimal("11.4")} g/dL`);
    expect(riesgo).toHaveTextContent(`Hb ajustada por altitud${decimal(11.4)} g/dL`);
    expect(riesgo).toHaveTextContent("Ajuste por altitudSin ajuste (355 m.s.n.m.)");
    expect(within(riesgo).getByText("No requiere derivación.")).toBeInTheDocument();

    // Recomendación
    const reco = screen.getByRole("region", { name: "Recomendación clínica" });
    expect(within(reco).getByText(r.recomendacion!.resumen)).toBeInTheDocument();
    const pasos = within(reco).getAllByRole("listitem");
    expect(pasos).toHaveLength(1);
    expect(pasos[0]).toHaveTextContent("Prevención Seguir la indicación del fragmento citado.F-05");
    expect(within(reco).queryByRole("heading", { name: "Advertencias" })).not.toBeInTheDocument();

    // Tabla de citas
    const tabla = within(reco).getByRole("table");
    const fila = within(tabla).getAllByRole("row")[1];
    expect(fila).toHaveTextContent("F-05");
    expect(fila).toHaveTextContent("PRUEBA-C-OMS");
    expect(fila).toHaveTextContent("Guía de prueba PRUEBA-C-OMS");
    expect(fila).toHaveTextContent("Sección 1");
    expect(fila).toHaveTextContent("pág. 1");
    expect(within(fila).getByText(decimal(0.105, 3))).toBeInTheDocument();

    // Verificación
    const verif = screen.getByRole("region", { name: "Verificación de la respuesta" });
    expect(within(verif).getAllByText("Cumplido")).toHaveLength(3);
    expect(verif).toHaveTextContent(`Relevancia máxima ${decimal(0.342, 3)} frente al umbral ${decimal(0.05, 3)}.`);
    expect(verif).toHaveTextContent("Intento 1, búsqueda inicial");
    expect(verif).toHaveTextContent("1 cita de 6 fragmentos evaluados");

    // Avisos y acciones
    expect(screen.getByText(AVISO_DECISION)).toBeInTheDocument();
    expect(screen.getByText(/MODO DE PRUEBA: respuesta no clínica/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Volver al paciente" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Nueva consulta" })).toBeEnabled();
    const decision = screen.getByRole("button", { name: "Registrar decisión clínica" });
    expect(decision).toBeDisabled();
    expect(decision).toHaveAccessibleDescription("disponible en la siguiente parte");
    expect(screen.getByRole("button", { name: "Exportar reporte" })).toBeDisabled();
  });

  it("los encabezados van en orden, sin saltos de nivel", async () => {
    conResultado(resultadoFixture("VERIFICADA"));
    renderizar();
    await screen.findByRole("heading", { level: 1, name: "Paciente Ficticio Dos" });
    const niveles = screen.getAllByRole("heading").map((h) => Number(h.tagName.slice(1)));
    expect(niveles[0]).toBe(1);
    niveles.slice(1).forEach((n, i) => expect(n - niveles[i]).toBeLessThanOrEqual(1));
    expect(screen.getAllByRole("heading").map((h) => h.textContent)).toEqual([
      "Paciente Ficticio Dos", "Nivel de riesgo", "Recomendación clínica", "Evidencias citadas",
      "Verificación de la respuesta", "Factores identificados",
    ]);
  });

  it("muestra la cita en inglés literal con lang=\"en\" y la traducción de apoyo rotulada", async () => {
    const r = resultadoFixture("VERIFICADA");
    conResultado(r);
    renderizar();
    await screen.findByRole("heading", { name: "Evidencias citadas" });
    const cita = r.citas[0];
    const extracto = document.querySelector(`#cita-F-05 blockquote`) as HTMLElement;
    expect(extracto).toHaveAttribute("lang", "en");
    expect(extracto.textContent).toBe(cita.extracto); // carácter a carácter
    const traduccion = document.querySelector("#cita-F-05 .cita__traduccion") as HTMLElement;
    expect(traduccion).toHaveAttribute("lang", "es");
    expect(within(traduccion).getByText("Traducción de apoyo, no oficial")).toBeInTheDocument();
    expect(within(traduccion).getByText(cita.extracto_traducido!)).toBeInTheDocument();
  });

  it("no altera un extracto con filas de tabla, espacios y saltos de línea", async () => {
    const r = resultadoFixture("VERIFICADA");
    const literal = "Tabla N° 20\n| Edad | Control de Hb |\n|  6 a 23 meses  | al mes, a los 3 y a los 6 meses |\n\n  Nota: «sin cambios».";
    r.citas[0] = { ...r.citas[0], extracto: literal, extracto_traducido: null, etiqueta_traduccion: null, idioma: "es" };
    conResultado(r);
    renderizar();
    await screen.findByRole("heading", { name: "Evidencias citadas" });
    const extracto = document.querySelector("#cita-F-05 blockquote") as HTMLElement;
    expect(extracto.textContent).toBe(literal);
    expect(extracto).toHaveAttribute("lang", "es");
    expect(extracto).toHaveClass("cita__extracto");
    expect(document.querySelector("#cita-F-05 .cita__traduccion")).toBeNull();
  });

  it("cada etiqueta F-xx es un enlace con nombre claro que lleva a su cita", async () => {
    const r = resultadoFixture("VERIFICADA");
    const base = r.citas[0];
    r.citas = [
      { ...base, etiqueta: "F-01", documento: "NTS de prueba", fuente: "NTS-PRUEBA", idioma: "es", extracto_traducido: null, etiqueta_traduccion: null },
      base,
    ];
    r.recomendacion!.recomendacion = [
      { tipo: "TRATAMIENTO", texto: "Paso uno.", citas: ["F-01"] },
      { tipo: "SEGUIMIENTO", texto: "Paso dos.", citas: ["F-05", "F-01"] },
    ];
    r.recomendacion!.advertencias = ["Advertencia de prueba."];
    conResultado(r);
    renderizar();
    await screen.findByRole("heading", { name: "Recomendación clínica" });
    expect(screen.getByRole("heading", { level: 3, name: "Advertencias" })).toBeInTheDocument();
    expect(screen.getByText("Advertencia de prueba.")).toBeInTheDocument();

    const enlaces = screen.getAllByRole("link", { name: "Ver cita F-01: NTS de prueba" });
    expect(enlaces).toHaveLength(2);
    expect(enlaces[0]).toHaveAttribute("href", "#cita-F-01");
    fireEvent.click(enlaces[0]);
    expect(document.activeElement).toBe(document.getElementById("cita-F-01"));
    expect(document.getElementById("cita-F-01")).toHaveClass("tabla-citas__fila--resaltada");

    fireEvent.click(screen.getByRole("link", { name: "Ver cita F-05: Guía de prueba PRUEBA-C-OMS" }));
    expect(document.activeElement).toBe(document.getElementById("cita-F-05"));
    expect(document.getElementById("cita-F-01")).not.toHaveClass("tabla-citas__fila--resaltada");
    expect(screen.getAllByText(/Tratamiento|Seguimiento/, { selector: ".etiqueta--paso" }).map((e) => e.textContent))
      .toEqual(["Tratamiento", "Seguimiento"]);
  });

  it("en la cabecera muestra solo la edad al tamizaje si no cambió hasta hoy", async () => {
    const historial = { ...HISTORIAL_FIXTURE, tamizajes: HISTORIAL_FIXTURE.tamizajes.map((t) => ({ ...t, edad_meses: 16 })) };
    simularBackend({
      [GET_RESULTADO]: () => respuestaJson(200, resultadoFixture("VERIFICADA")),
      [`GET /api/pacientes/${ID_PACIENTE_FIXTURE}/historial`]: () => respuestaJson(200, historial),
    });
    renderizar();
    await screen.findByRole("heading", { level: 1, name: "Paciente Ficticio Dos" });
    const cabecera = screen.getByRole("heading", { level: 1 }).closest(".resultado__cabecera") as HTMLElement;
    // La Hb observada sale del mismo historial: cuando aparece, la edad al tamizaje ya está cargada.
    const riesgo = screen.getByRole("region", { name: "Nivel de riesgo" });
    await waitFor(() => expect(riesgo).toHaveTextContent(`Hb observada${decimal("11.4")} g/dL`));
    expect(cabecera).toHaveTextContent("16 meses");
    expect(cabecera).not.toHaveTextContent("al tamizaje");
    expect(cabecera).not.toHaveTextContent("hoy");
  });

  it("ordena la tabla de evidencias por número de etiqueta, no por el orden del reranker", async () => {
    const r = resultadoFixture("VERIFICADA");
    const base = r.citas[0];
    const cita = (etiqueta: string) => ({ ...base, etiqueta, documento: `Documento ${etiqueta}` });
    // Orden del reranker, como lo entrega el backend.
    r.citas = [cita("F-05"), cita("F-02"), cita("F-10"), cita("F-01"), cita("F-03")];
    conResultado(r);
    renderizar();
    const reco = await screen.findByRole("region", { name: "Tabla de evidencias citadas" });
    const filas = within(reco).getAllByRole("row").slice(1);
    expect(filas.map((f) => within(f).getByRole("rowheader").textContent))
      .toEqual(["F-01", "F-02", "F-03", "F-05", "F-10"]);
    expect(filas.map((f) => f.id)).toEqual(["cita-F-01", "cita-F-02", "cita-F-03", "cita-F-05", "cita-F-10"]);
  });

  it("marca un control null como «no se ejecutó» y uno fallido como no cumplido", async () => {
    const r = resultadoFixture("VERIFICADA");
    r.verificacion = { ...r.verificacion!, valida_consistencia: null, valida_evidencia: false, relevancia_maxima: null };
    conResultado(r);
    renderizar();
    const verif = await screen.findByRole("region", { name: "Verificación de la respuesta" });
    const controles = within(verif).getAllByRole("listitem");
    expect(controles[0]).toHaveTextContent("6.1 Citas textuales: Cumplido");
    expect(controles[1]).toHaveTextContent("6.2 Consistencia y dosis: No se ejecutó");
    expect(controles[2]).toHaveTextContent("6.3 Suficiencia de la evidencia: No cumplido");
    expect(controles[2]).toHaveTextContent(`Relevancia máxima sin dato frente al umbral ${decimal(0.05, 3)}.`);
  });

  it("destaca la derivación y el ajuste por altitud cuando corresponden", async () => {
    const r = resultadoFixture("VERIFICADA");
    r.clasificacion = { categoria: "ANEMIA_SEVERA", nivel_riesgo: "MUY_ALTO", hb_ajustada_g_dl: 6.8, ajuste_hb_g_dl: 1.3,
                        altitud_msnm: 3200, requiere_derivacion: true };
    conResultado(r);
    renderizar();
    const riesgo = await screen.findByRole("region", { name: "Nivel de riesgo" });
    expect(within(riesgo).getByText("MUY ALTO")).toBeInTheDocument();
    expect(within(riesgo).getByText("Anemia severa")).toBeInTheDocument();
    expect(riesgo).toHaveTextContent(`Ajuste por altitud${decimal(1.3)} g/dL (3200 m.s.n.m.)`);
    expect(within(riesgo).getByText(/Requiere derivación a un establecimiento de mayor capacidad resolutiva/)).toBeInTheDocument();
  });

  it("sin modo de prueba no muestra el aviso", async () => {
    conResultado({ ...resultadoFixture("VERIFICADA"), modo_prueba: false });
    renderizar();
    await screen.findByRole("heading", { name: "Recomendación clínica" });
    expect(screen.queryByText(/MODO DE PRUEBA/)).not.toBeInTheDocument();
  });

  it("al llegar desde el stream muestra el evento fin sin esperar el GET", async () => {
    const lineas = lineasFixture("VERIFICADA");
    const fin = JSON.parse(lineas[lineas.length - 1]) as EventoFin;
    simularBackend({ [GET_RESULTADO]: () => new Promise<Response>(() => {}) }); // el GET no responde
    renderizar({ pathname: RUTA, state: { fin } });
    expect(await screen.findByRole("heading", { name: "Recomendación clínica" })).toBeInTheDocument();
    expect(screen.getByText(fin.recomendacion!.resumen)).toBeInTheDocument();
    expect(document.querySelector("#cita-F-05 blockquote")!.textContent).toBe(fin.citas[0].extracto);
    expect(screen.getByText(/MODO DE PRUEBA/)).toBeInTheDocument();
    // La pregunta llega con el GET.
    const pregunta = document.querySelector(".resultado__pregunta") as HTMLElement;
    expect(pregunta).toHaveTextContent("Cargando…");
  });

  it("«Nueva consulta» abre M04 del paciente", async () => {
    conResultado(resultadoFixture("VERIFICADA"));
    renderizar();
    fireEvent.click(await screen.findByRole("button", { name: "Nueva consulta" }));
    expect(await screen.findByRole("heading", { name: "Consulta clínica" })).toBeInTheDocument();
  });
});

describe("M05 · EN_PROCESO", () => {
  it("consulta el GET cada 2 s y muestra el resultado cuando termina", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const final = resultadoFixture("VERIFICADA");
    let llamadas = 0;
    const f = simularBackend({
      [GET_RESULTADO]: () => respuestaJson(200, ++llamadas < 3 ? { ...final, estado: "EN_PROCESO" } : final),
    });
    renderizar();
    expect(await screen.findByRole("heading", { name: "En proceso" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Recomendación clínica" })).not.toBeInTheDocument();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2_000);
    });
    expect(await screen.findByRole("heading", { name: "Recomendación clínica" })).toBeInTheDocument();
    expect(llamadasGet(f)).toBe(3);
  });

  it("pasados 60 s sigue en proceso y ofrece volver a revisar", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const enProceso = { ...resultadoFixture("VERIFICADA"), estado: "EN_PROCESO" };
    const f = simularBackend({ [GET_RESULTADO]: () => respuestaJson(200, enProceso) });
    renderizar();
    await screen.findByRole("heading", { name: "En proceso" });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000);
    });
    expect(await screen.findByText(/sigue en proceso en el servidor después de 60 s/)).toBeInTheDocument();
    const antes = llamadasGet(f);
    fireEvent.click(screen.getByRole("button", { name: "Volver a revisar" }));
    await waitFor(() => expect(llamadasGet(f)).toBeGreaterThan(antes));
  });
});

describe("M05 · estados sin recomendación al recargar", () => {
  const OTROS: EstadoFinal[] = ["EVIDENCIA_INSUFICIENTE", "DATOS_FALTANTES", "TAMIZAJE_NO_VIGENTE", "FUERA_DE_DOMINIO",
                               "SOLICITUD_BLOQUEADA", "ERROR"];
  const ACCION: Partial<Record<EstadoFinal, string>> = {
    ERROR: "Reintentar",
    FUERA_DE_DOMINIO: "Reformular la pregunta",
    SOLICITUD_BLOQUEADA: "Reformular la consulta",
    DATOS_FALTANTES: "Completar datos",
    TAMIZAJE_NO_VIGENTE: "Revisar el tamizaje",
  };

  it.each(OTROS)("%s: estado a ancho completo, clasificación debajo y su acción", async (estado) => {
    const r = resultadoFixture(estado);
    simularBackend({
      [GET_RESULTADO]: () => respuestaJson(200, r),
      [`GET /api/pacientes/${ID_PACIENTE_FIXTURE}/consultas`]: () => respuestaJson(200, []),
    });
    renderizar();
    const titulo = await screen.findByRole("heading", { name: "Estado de la consulta" });
    // M06 y M15 se abren solas; aquí se revisa el resumen de fondo.
    if (estado === "DATOS_FALTANTES" || estado === "TAMIZAJE_NO_VIGENTE") await screen.findByRole("dialog");
    const tarjeta = titulo.closest("section") as HTMLElement;
    const alerta = within(tarjeta).getByRole("alert");
    expect(alerta).toHaveTextContent(TITULOS_ESTADO[estado]);
    expect(within(alerta).getByText(textoDesenlace(estado, r.mensaje)!)).toBeInTheDocument();
    expect(within(tarjeta).getByText(AVISO_DECISION)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Volver al paciente" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Nueva consulta" })).toBeInTheDocument();
    expect(within(screen.getByText("Pregunta realizada").parentElement!).getByText(r.texto_filtrado!)).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Recomendación clínica" })).not.toBeInTheDocument();
    expect(screen.queryByText(SUGERENCIA_FUERA_DE_DOMINIO) !== null).toBe(estado === "FUERA_DE_DOMINIO");
    if (estado === "DATOS_FALTANTES") expect(within(tarjeta).getByText(r.datos_faltantes[0].mensaje)).toBeInTheDocument();
    const accion = ACCION[estado];
    if (accion) expect(within(tarjeta).getByRole("button", { name: accion })).toBeInTheDocument();
    else expect(within(tarjeta).queryByRole("button")).not.toBeInTheDocument();
    // Una sola columna: el estado y, debajo, la clasificación, en el mismo contenedor.
    const contenedor = tarjeta.parentElement as HTMLElement;
    expect(contenedor).toHaveClass("estado-consulta");
    if (r.clasificacion) {
      const clasificacion = screen.getByRole("region", { name: "Clasificación del paciente" });
      expect(clasificacion.parentElement).toBe(contenedor);
      expect(tarjeta.compareDocumentPosition(clasificacion) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
      expect(clasificacion).toHaveTextContent("Calculada por reglas a partir del tamizaje, no por el modelo.");
    } else {
      expect(screen.queryByRole("region", { name: "Clasificación del paciente" })).not.toBeInTheDocument();
    }
  });
});

describe("M05 · errores", () => {
  it("un 404 muestra el mensaje del backend y el enlace al panel", async () => {
    simularBackend({ [GET_RESULTADO]: () => respuestaJson(404, { detail: "La consulta no existe" }) });
    renderizar();
    expect(await screen.findByText("La consulta no existe")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("link", { name: "Ir al panel de pacientes" }));
    expect(await screen.findByRole("heading", { name: "Pacientes" })).toBeInTheDocument();
  });

  it("un 403 muestra el mensaje del backend sin el enlace del 404", async () => {
    simularBackend({ [GET_RESULTADO]: () => respuestaJson(403, { detail: "No tiene permiso para ver consultas" }) });
    renderizar();
    expect(await screen.findByText("No tiene permiso para ver consultas")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Ir al panel de pacientes" })).not.toBeInTheDocument();
  });

  it("un 401 cierra la sesión", async () => {
    simularBackend({ [GET_RESULTADO]: () => respuestaJson(401, { detail: "Sesión no válida o expirada" }) });
    renderizar();
    expect(await screen.findByRole("heading", { name: "Iniciar sesión" })).toBeInTheDocument();
  });

  it("sin la ficha del paciente, muestra el resultado con una cabecera genérica", async () => {
    simularBackend({
      [GET_RESULTADO]: () => respuestaJson(200, resultadoFixture("VERIFICADA")),
      [`GET /api/pacientes/${resultadoFixture("VERIFICADA").id_paciente}`]: () => respuestaJson(404, { detail: "El paciente no existe" }),
    });
    renderizar();
    expect(await screen.findByRole("heading", { name: "Recomendación clínica" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Resultado de la consulta");
  });
});
