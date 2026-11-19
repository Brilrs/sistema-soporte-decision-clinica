// Pruebas de «Retirar» en M11 (HU17, Sprint 3 parte F): cada estado de la ventana (carga y error de las
// referencias, nivel 2 con el motivo, nivel 1 bloqueado por referencias, nivel 1 con el código exacto),
// los errores del POST (409, 422, 423 y 403), el aviso de éxito con la tabla y la tarjeta de avance, el
// detalle de una guía obsoleta y «Reintentar» de un retiro fallido. Fetch simulado; sin API real.
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import App from "../App";
import { guardarToken } from "../api/cliente";
import type { Documento, ReferenciasGuia } from "../api/conocimiento";
import { AuthProvider } from "../auth/AuthContext";
import { TEXTO_BLOQUEO_REFERENCIAS, TEXTO_RETIRO } from "../components/conocimiento/textos";
import { ADMIN, DETALLE_NTS213, DOCUMENTOS, ID_NUEVA, TITULO_NUEVA, guiaNueva, trabajo, trabajoResumen } from "../pruebas/conocimiento";
import { respuestaJson, simularBackend } from "../pruebas/simulador";

const RUTA = "/admin/conocimiento";
const GET_DOCUMENTOS = "GET /api/conocimiento/documentos";
const GET_ACTIVOS = "GET /api/conocimiento/trabajos?activos=true";
const OMS2016 = "10000000-0000-0000-0000-000000002016";
const NTS = "10000000-0000-0000-0000-000000000213";
const refs = (id: string) => `GET /api/conocimiento/documentos/${id}/referencias`;
const retiro = (id: string) => `POST /api/conocimiento/documentos/${id}/retiro`;
const MOTIVO = "Guía reemplazada por una revisión más reciente";
type Rutas = Parameters<typeof simularBackend>[0];

const guia2 = () => guiaNueva({ estado_indexacion: "COMPLETADA", fragmentos_vigentes: 12,
                                ultimo_trabajo: trabajoResumen({ estado: "COMPLETADO" }) });

function referencias(id: string, nivel: 1 | 2, cambios: Partial<ReferenciasGuia> = {}): ReferenciasGuia {
  return { id_documento: id, nivel, estado: "VIGENTE", codigo_confirmacion: nivel === 1 ? "OMS 2016" : null,
           referencias: [], puede_retirarse: true, ...cambios };
}

const REFERENCIAS_NTS: ReferenciasGuia = referencias(NTS, 1, {
  codigo_confirmacion: "NTS 213-MINSA/DGIESP-2024", puede_retirarse: false,
  referencias: [
    { tipo: "MAPA_MODIFICACIONES", descripcion: "Es la guía base del mapa de modificaciones del indexador (rm429_2024.yaml): «RM 429-2024/MINSA» modifica su texto" },
    { tipo: "PUNTERO", descripcion: "La regla de punteros «nts213-tabla4» (punteros.yaml) la usa como documento de origen" },
  ],
});

function renderizar(rutas: Rutas = {}) {
  const fetchFalso = simularBackend({
    "GET /api/auth/me": () => respuestaJson(200, ADMIN),
    [GET_DOCUMENTOS]: () => respuestaJson(200, [...DOCUMENTOS(), guia2()]),
    [GET_ACTIVOS]: () => respuestaJson(200, []),
    [refs(ID_NUEVA)]: () => respuestaJson(200, referencias(ID_NUEVA, 2)),
    [refs(OMS2016)]: () => respuestaJson(200, referencias(OMS2016, 1)),
    [refs(NTS)]: () => respuestaJson(200, REFERENCIAS_NTS),
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
const cuerpo = (f: ReturnType<typeof simularBackend>, clave: string) =>
  JSON.parse(String(llamadas(f, clave).slice(-1)[0]?.[1]?.body));

async function abrir(nombre: string) {
  await screen.findByRole("region", { name: "Guías de la base de conocimiento" });
  fireEvent.click(screen.getByRole("button", { name: `Retirar: ${nombre}` }));
  return screen.findByRole("dialog", { name: `Retirar «${nombre}»` });
}

const botonRetirar = (v: HTMLElement) => within(v).getByRole("button", { name: /^(Retirar|Retirando…)$/ });

function escribirMotivo(v: HTMLElement, texto = MOTIVO) {
  fireEvent.change(within(v).getByLabelText(/Motivo del retiro/), { target: { value: texto } });
}

function retirada(doc: Documento): Documento {
  return { ...doc, estado: "OBSOLETA", retirado_por: "Administración de prueba", fecha_retiro: "2026-11-19T15:00:00Z",
           motivo_retiro: MOTIVO, ultimo_trabajo: trabajoResumen({ id_trabajo: "t-retiro", tipo: "RETIRO" }) };
}

describe("M11 · ventana de retiro", () => {
  it("al abrirla muestra la carga de referencias y el texto fijo", async () => {
    renderizar({ [refs(ID_NUEVA)]: () => new Promise(() => {}) });
    const v = await abrir(TITULO_NUEVA);
    expect(within(v).getByRole("status")).toHaveTextContent("Revisando si otras partes del sistema usan esta guía");
    expect(v).toHaveAccessibleDescription(TEXTO_RETIRO);
    expect(botonRetirar(v)).toBeDisabled();
  });

  it("si las referencias fallan muestra el error y «Reintentar» las vuelve a pedir", async () => {
    let fallar = true;
    const f = renderizar({
      [refs(ID_NUEVA)]: () => (fallar ? respuestaJson(500, { detail: "Error interno" }) : respuestaJson(200, referencias(ID_NUEVA, 2))),
    });
    const v = await abrir(TITULO_NUEVA);
    expect(await within(v).findByRole("alert")).toHaveTextContent("No se pudieron revisar las referencias de la guía: Error interno");
    expect(botonRetirar(v)).toBeDisabled();
    fallar = false;
    fireEvent.click(within(v).getByRole("button", { name: "Reintentar" }));
    expect(await within(v).findByLabelText(/Motivo del retiro/)).toBeInTheDocument();
    expect(llamadas(f, refs(ID_NUEVA))).toHaveLength(2);
  });

  it("nivel 2: el motivo con contador habilita «Retirar»; sin código; al retirar avisa, refresca y sigue el trabajo", async () => {
    const f = renderizar({
      [GET_DOCUMENTOS]: (() => {
        let i = 0;
        return () => respuestaJson(200, i++ === 0 ? [...DOCUMENTOS(), guia2()] : [...DOCUMENTOS(), retirada(guia2())]);
      })(),
      [GET_ACTIVOS]: (() => {
        let i = 0;
        return () => respuestaJson(200, i++ === 0 ? [] : [trabajo({ id_trabajo: "t-retiro", tipo: "RETIRO" })]);
      })(),
      [retiro(ID_NUEVA)]: () => respuestaJson(201, { documento: retirada(guia2()), trabajo: trabajo({ id_trabajo: "t-retiro", tipo: "RETIRO" }) }),
    });
    const v = await abrir(TITULO_NUEVA);
    await within(v).findByLabelText(/Motivo del retiro/);
    expect(within(v).queryByLabelText(/Escriba el código/)).not.toBeInTheDocument();
    expect(within(v).getByText("0 de 250 caracteres (mínimo 10)")).toBeInTheDocument();
    escribirMotivo(v, "  corto    ");
    expect(within(v).getByText("5 de 250 caracteres (mínimo 10)")).toBeInTheDocument();
    expect(botonRetirar(v)).toBeDisabled();
    expect(botonRetirar(v)).toHaveAccessibleDescription("Escriba un motivo de 10 a 250 caracteres.");
    escribirMotivo(v, ` ${MOTIVO} `);
    expect(botonRetirar(v)).toBeEnabled();
    fireEvent.click(botonRetirar(v));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(cuerpo(f, retiro(ID_NUEVA))).toEqual({ motivo: MOTIVO });
    expect(await screen.findByText(`«${TITULO_NUEVA}» quedó retirada: ya no se citará en nuevas consultas. `
      + "Las consultas anteriores conservan sus citas.")).toBeInTheDocument();
    expect(await screen.findByText("Retiro en cola:")).toBeInTheDocument();
    const region = screen.getByRole("region", { name: "Guías de la base de conocimiento" });
    await waitFor(() => expect(within(region).getByRole("button", { name: `Retirar: ${TITULO_NUEVA}` }))
      .toHaveAttribute("aria-disabled", "true"));
    expect(within(region).getByText("Obsoleta")).toBeInTheDocument();
  });

  it("nivel 1 con referencias: lista que bloquea, sin motivo y «Retirar» deshabilitado con la explicación", async () => {
    const f = renderizar();
    const v = await abrir("NTS 213-MINSA/DGIESP-2024");
    const alerta = await within(v).findByRole("alert");
    expect(alerta).toHaveTextContent(TEXTO_BLOQUEO_REFERENCIAS);
    const items = within(alerta).getAllByRole("listitem");
    expect(items).toHaveLength(2);
    expect(items[0]).toHaveTextContent("Mapa de modificaciones: Es la guía base del mapa");
    expect(items[1]).toHaveTextContent("Regla de punteros: La regla de punteros «nts213-tabla4»");
    expect(within(v).queryByLabelText(/Motivo del retiro/)).not.toBeInTheDocument();
    expect(botonRetirar(v)).toBeDisabled();
    expect(botonRetirar(v)).toHaveAccessibleDescription("No se puede retirar mientras existan las referencias de la lista.");
    fireEvent.click(within(v).getByRole("button", { name: "Cancelar" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(llamadas(f, retiro(NTS))).toHaveLength(0);
  });

  it("nivel 1 sin referencias: «Retirar» solo con el código exacto, que se envía como confirmación", async () => {
    const f = renderizar({ [retiro(OMS2016)]: () => respuestaJson(201, { documento: retirada(DOCUMENTOS()[3]),
                                                                       trabajo: trabajo({ tipo: "RETIRO" }) }) });
    const v = await abrir("OMS 2016");
    await within(v).findByLabelText(/Motivo del retiro/);
    escribirMotivo(v);
    const codigo = within(v).getByLabelText("Escriba el código del documento (OMS 2016) para confirmar");
    expect(codigo).toHaveAccessibleDescription("Debe coincidir exactamente, con mayúsculas, espacios y signos.");
    expect(botonRetirar(v)).toBeDisabled();
    expect(botonRetirar(v)).toHaveAccessibleDescription("Escriba el código del documento exactamente para confirmar.");
    for (const intento of ["oms 2016", "OMS 2016 ", "OMS2016", "OMS 201"]) {
      fireEvent.change(codigo, { target: { value: intento } });
      expect(botonRetirar(v)).toBeDisabled();
      fireEvent.click(botonRetirar(v));
    }
    expect(llamadas(f, retiro(OMS2016))).toHaveLength(0);
    fireEvent.change(codigo, { target: { value: "OMS 2016" } });
    expect(botonRetirar(v)).toBeEnabled();
    fireEvent.click(botonRetirar(v));
    await waitFor(() => expect(llamadas(f, retiro(OMS2016))).toHaveLength(1));
    expect(cuerpo(f, retiro(OMS2016))).toEqual({ motivo: MOTIVO, confirmacion: "OMS 2016" });
  });

  it("409 de una guía que cambió: mensaje y «Recargar», que cierra y vuelve a pedir la lista", async () => {
    const f = renderizar({ [retiro(ID_NUEVA)]: () => respuestaJson(409, { detail: "La guía ya está retirada", codigo: "YA_OBSOLETA" }) });
    const v = await abrir(TITULO_NUEVA);
    await within(v).findByLabelText(/Motivo del retiro/);
    escribirMotivo(v);
    fireEvent.click(botonRetirar(v));
    expect(await within(v).findByRole("alert")).toHaveTextContent("La guía cambió mientras se revisaba: La guía ya está retirada.");
    expect(botonRetirar(v)).toBeDisabled();
    const antes = llamadas(f, GET_DOCUMENTOS).length;
    fireEvent.click(within(v).getByRole("button", { name: "Recargar" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    await waitFor(() => expect(llamadas(f, GET_DOCUMENTOS).length).toBe(antes + 1));
  });

  it("409 con referencias nuevas: muestra la lista que bloquea", async () => {
    renderizar({ [retiro(OMS2016)]: () => respuestaJson(409, {
      detail: "No se puede retirar", codigo: "REFERENCIAS_VIGENTES",
      referencias: [{ tipo: "UMBRAL_HEMOGLOBINA", descripcion: "8 puntos de corte de hemoglobina vigentes la citan como norma" }],
    }) });
    const v = await abrir("OMS 2016");
    await within(v).findByLabelText(/Motivo del retiro/);
    escribirMotivo(v);
    fireEvent.change(within(v).getByLabelText(/Escriba el código/), { target: { value: "OMS 2016" } });
    fireEvent.click(botonRetirar(v));
    const alerta = await within(v).findByRole("alert");
    expect(alerta).toHaveTextContent("Puntos de corte: 8 puntos de corte de hemoglobina vigentes la citan como norma");
    expect(botonRetirar(v)).toBeDisabled();
  });

  it("422 de la confirmación: el mensaje queda junto al campo", async () => {
    renderizar({ [retiro(OMS2016)]: () => respuestaJson(422, {
      detail: "Para retirar una guía de nivel 1, escriba su código exactamente como aparece", codigo: "CONFIRMACION_INCORRECTA" }) });
    const v = await abrir("OMS 2016");
    await within(v).findByLabelText(/Motivo del retiro/);
    escribirMotivo(v);
    const codigo = within(v).getByLabelText(/Escriba el código/);
    fireEvent.change(codigo, { target: { value: "OMS 2016" } });
    fireEvent.click(botonRetirar(v));
    await waitFor(() => expect(codigo).toHaveAttribute("aria-invalid", "true"));
    expect(codigo).toHaveAccessibleDescription(
      "Debe coincidir exactamente, con mayúsculas, espacios y signos. Para retirar una guía de nivel 1, escriba su código exactamente como aparece");
  });

  it("422 del motivo: el mensaje queda junto al motivo", async () => {
    renderizar({ [retiro(ID_NUEVA)]: () => respuestaJson(422, {
      detail: "El motivo del retiro debe tener entre 10 y 250 caracteres", codigo: "MOTIVO_INVALIDO" }) });
    const v = await abrir(TITULO_NUEVA);
    const motivo = await within(v).findByLabelText(/Motivo del retiro/);
    escribirMotivo(v);
    fireEvent.click(botonRetirar(v));
    await waitFor(() => expect(motivo).toHaveAttribute("aria-invalid", "true"));
    expect(within(v).getByText("El motivo del retiro debe tener entre 10 y 250 caracteres")).toBeInTheDocument();
  });

  it("423 del modo de evaluación: muestra el bloqueo y deja «Retirar» deshabilitado", async () => {
    renderizar({ [retiro(ID_NUEVA)]: () => respuestaJson(423, {
      detail: "El sistema está en modo de evaluación: los cambios de parámetros y de la base de conocimiento están bloqueados hasta que termine la evaluación." }) });
    const v = await abrir(TITULO_NUEVA);
    await within(v).findByLabelText(/Motivo del retiro/);
    escribirMotivo(v);
    fireEvent.click(botonRetirar(v));
    expect(await within(v).findByRole("alert")).toHaveTextContent("El sistema está en modo de evaluación");
    expect(botonRetirar(v)).toBeDisabled();
    expect(within(v).queryByRole("button", { name: "Recargar" })).not.toBeInTheDocument();
  });

  it("403: avisa que el rol no tiene permiso", async () => {
    renderizar({ [retiro(ID_NUEVA)]: () => respuestaJson(403, { detail: "No autorizado" }) });
    const v = await abrir(TITULO_NUEVA);
    await within(v).findByLabelText(/Motivo del retiro/);
    escribirMotivo(v);
    fireEvent.click(botonRetirar(v));
    expect(await within(v).findByRole("alert")).toHaveTextContent("Su rol no tiene permiso para retirar guías.");
  });
});

describe("M11 · guía obsoleta", () => {
  it("el detalle muestra quién la retiró, cuándo y el motivo", async () => {
    const vieja = retirada(DOCUMENTOS()[2]);
    renderizar({
      [GET_DOCUMENTOS]: () => respuestaJson(200, [vieja]),
      [`GET /api/conocimiento/documentos/${NTS}`]: () => respuestaJson(200, { ...DETALLE_NTS213(), ...vieja }),
    });
    await screen.findByRole("region", { name: "Guías de la base de conocimiento" });
    fireEvent.click(screen.getByRole("button", { name: "Ver: NTS 213-MINSA/DGIESP-2024" }));
    const v = await screen.findByRole("dialog");
    const termino = async (t: string) => (await within(v).findByText(t)).nextElementSibling;
    expect(await termino("Retirada por")).toHaveTextContent("Administración de prueba");
    expect(await termino("Fecha de retiro")).toHaveTextContent("19/11/2026");
    expect(await termino("Motivo del retiro")).toHaveTextContent(MOTIVO);
  });

  it("un retiro que terminó en error muestra «Reintentar», que pide otro retiro", async () => {
    const vieja = retirada(guia2());
    vieja.ultimo_trabajo = trabajoResumen({ tipo: "RETIRO", estado: "ERROR", mensaje_error: "No se pudieron actualizar los vectores" });
    const POST_REINTENTAR = `POST /api/conocimiento/documentos/${ID_NUEVA}/reintentar`;
    const f = renderizar({
      [GET_DOCUMENTOS]: () => respuestaJson(200, [vieja]),
      [POST_REINTENTAR]: () => respuestaJson(201, { trabajo: trabajo({ tipo: "RETIRO" }) }),
    });
    await screen.findByRole("region", { name: "Guías de la base de conocimiento" });
    fireEvent.click(screen.getByRole("button", { name: `Reintentar: ${TITULO_NUEVA}` }));
    expect(await screen.findByText(`Se volvió a poner en cola el retiro de «${TITULO_NUEVA}».`)).toBeInTheDocument();
    expect(llamadas(f, POST_REINTENTAR)).toHaveLength(1);
  });

  it("una obsoleta con la indexación en error no ofrece «Reintentar»", async () => {
    const vieja = { ...retirada(guia2()), estado_indexacion: "ERROR" as const,
                    ultimo_trabajo: trabajoResumen({ tipo: "RETIRO", estado: "COMPLETADO" }) };
    renderizar({ [GET_DOCUMENTOS]: () => respuestaJson(200, [vieja]) });
    await screen.findByRole("region", { name: "Guías de la base de conocimiento" });
    expect(screen.queryByRole("button", { name: /^Reintentar/ })).not.toBeInTheDocument();
  });
});
