// Pruebas de la parte E2 del Sprint 3: M12 «Parámetros clínicos» (/admin/parametros). Fetch simulado con
// los fixtures de las partes E1a y E1b (src/__fixtures__/parametros*.json y parametros_put_*.json,
// generados por el backend); sin API real. No hay pacientes en esta pantalla; nada depende de la hora.
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import confirmacion from "../__fixtures__/parametros_put_confirmacion.json";
import conflicto from "../__fixtures__/parametros_put_conflicto.json";
import respuestaVigencia from "../__fixtures__/parametros_put_respuesta.json";
import sinCambios from "../__fixtures__/parametros_put_sin_cambios.json";
import validacion from "../__fixtures__/parametros_put_validacion.json";
import historialFixture from "../__fixtures__/parametros_historial.json";
import huellaFixture from "../__fixtures__/parametros_huella.json";
import parametrosFixture from "../__fixtures__/parametros.json";
import soloLecturaFixture from "../__fixtures__/parametros_solo_lectura.json";
import { guardarToken } from "../api/cliente";
import type { PaginaHistorial, Parametros } from "../api/tipos_parametros";
import { AuthProvider } from "../auth/AuthContext";
import { CONSULTA_ANGOSTA } from "../components/Layout";
import { AVISO_EVALUACION, AVISO_PENDIENTES, AVISO_SOLO_LECTURA, NOTA_EFECTO } from "../components/parametros/textos";
import { USUARIO_AUDITOR, respuestaJson, simularBackend } from "../pruebas/simulador";

const COORDINADOR = USUARIO_AUDITOR;
const ADMINISTRADOR = { ...USUARIO_AUDITOR, id_usuario: "u-0005", nombre_completo: "Administrador Prueba", rol: "Administrador",
                        permisos: ["ADMINISTRAR_USUARIOS", "ADMINISTRAR_GUIAS", "VER_PARAMETROS", "VER_AUDITORIA"] };
const MOTIVO = "Prueba de la pantalla M12";
const copia = <T,>(x: T): T => structuredClone(x);
const ultima = (urls: URL[]): URL | undefined => urls[urls.length - 1];

type Manejador = (init: RequestInit | undefined, url: URL) => Response | Promise<Response>;

function renderizar() {
  guardarToken("token-de-prueba");
  return render(
    <MemoryRouter initialEntries={["/admin/parametros"]}>
      <AuthProvider>
        <App />
      </AuthProvider>
    </MemoryRouter>,
  );
}

// Backend de M12. Guarda los cuerpos de los PUT y las URL del historial.
function backend({ parametros = copia(parametrosFixture) as Parametros, usuario = COORDINADOR as object,
                   historial = copia(historialFixture) as PaginaHistorial, put = {} as Record<string, Manejador>,
                   lectura }: { parametros?: Parametros; usuario?: object; historial?: PaginaHistorial;
                                put?: Record<string, Manejador>; lectura?: Manejador } = {}) {
  const cuerpos: { ruta: string; cuerpo: Record<string, unknown> }[] = [];
  const historiales: URL[] = [];
  let lecturas = 0;
  let huellas = 0;
  const rutasPut = Object.fromEntries(Object.entries(put).map(([ruta, m]) => [`PUT ${ruta}`, ((init, url) => {
    cuerpos.push({ ruta, cuerpo: JSON.parse(String(init?.body)) });
    return m(init, url);
  }) as Manejador]));
  const f = simularBackend({
    "GET /api/auth/me": () => respuestaJson(200, usuario),
    "GET /api/parametros": (init, url) => { lecturas += 1; return lectura ? lectura(init, url) : respuestaJson(200, parametros); },
    "GET /api/parametros/huella": () => { huellas += 1; return respuestaJson(200, huellaFixture); },
    "GET /api/parametros/historial": (_i, url) => { historiales.push(url); return respuestaJson(200, historial); },
    ...rutasPut,
  });
  return { f, cuerpos, historiales, lecturas: () => lecturas, huellas: () => huellas };
}

async function seccion(nombre: string) {
  return screen.findByRole("region", { name: nombre });
}

async function abrirEdicion(nombre: string) {
  const s = await seccion(nombre);
  fireEvent.click(within(s).getByRole("button", { name: "Editar" }));
  return s;
}

function escribir(campo: HTMLElement, valor: string) {
  fireEvent.change(campo, { target: { value: valor } });
}

afterEach(() => {
  delete (window as { matchMedia?: unknown }).matchMedia;
});

// ---------------------------------------------------------------------------
// Lectura, roles y avisos
// ---------------------------------------------------------------------------
describe("M12 · lectura y avisos", () => {
  it("muestra el texto del efecto, las secciones en orden y el conteo de pendientes de verificar", async () => {
    backend();
    renderizar();
    expect(await screen.findByRole("heading", { level: 1, name: "Parámetros clínicos" })).toBeInTheDocument();
    expect(screen.getByText(NOTA_EFECTO)).toBeInTheDocument();
    await seccion("Historial de cambios");
    const titulos = screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent);
    expect(titulos).toEqual(["Puntos de corte de hemoglobina", "Ajuste por altitud", "Vigencia del tamizaje",
                             "Riesgo por clasificación", "Recuperación", "Modelo", "Indexación", "Huella de configuración",
                             "Historial de cambios"]);
    const pendientes = screen.getByText(`${AVISO_PENDIENTES}:`).closest("[role=note]") as HTMLElement;
    expect(pendientes).toHaveTextContent("Puntos de corte de hemoglobina: 8 valores");
    expect(pendientes).toHaveTextContent("Ajuste por altitud: 11 valores");
    expect(pendientes).toHaveTextContent("Vigencia del tamizaje: 1 valor");
    expect(within(await seccion("Vigencia del tamizaje")).getByText("Pendiente de verificar")).toBeInTheDocument();
    expect(within(await seccion("Recuperación")).getByText("Se cambian solo por migración, con medición.")).toBeInTheDocument();
    expect(screen.queryByText(AVISO_SOLO_LECTURA, { exact: false })).not.toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Editar" })).toHaveLength(3);
  });

  it("el Administrador (puede_editar falso) ve el aviso de solo lectura y ningún control de edición", async () => {
    backend({ parametros: copia(soloLecturaFixture) as Parametros, usuario: ADMINISTRADOR });
    renderizar();
    expect(await screen.findByText(`${AVISO_SOLO_LECTURA}.`)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Editar" })).not.toBeInTheDocument();
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  });

  it("en modo de evaluación muestra el aviso y deshabilita «Editar» con el motivo", async () => {
    backend({ parametros: { ...(copia(parametrosFixture) as Parametros), modo_evaluacion: true } });
    renderizar();
    expect(await screen.findByText(`${AVISO_EVALUACION}.`, { selector: "strong" })).toBeInTheDocument();
    const editar = screen.getAllByRole("button", { name: "Editar" });
    expect(editar).toHaveLength(3);
    for (const b of editar) {
      expect(b).toBeDisabled();
      expect(b).toHaveAccessibleDescription(`${AVISO_EVALUACION}.`);
    }
  });

  it("error de carga con «Reintentar»", async () => {
    let fallar = true;
    backend({ lectura: () => (fallar ? respuestaJson(500, { detail: "Error interno del servidor" })
      : respuestaJson(200, copia(parametrosFixture))) });
    renderizar();
    const alerta = (await screen.findByText(/No se pudieron cargar los parámetros/)).closest("[role=alert]") as HTMLElement;
    fallar = false;
    fireEvent.click(within(alerta).getByRole("button", { name: "Reintentar" }));
    expect(await seccion("Puntos de corte de hemoglobina")).toBeInTheDocument();
  });

  it("la huella completa con «Copiar» y sus componentes", async () => {
    const escribirPortapapeles = vi.fn(async () => undefined);
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText: escribirPortapapeles } });
    backend();
    renderizar();
    const s = await seccion("Huella de configuración");
    expect(await within(s).findByText(huellaFixture.huella)).toBeInTheDocument();
    expect(within(s).getByRole("list", { name: "Componentes de la huella" }).children).toHaveLength(huellaFixture.componentes.length);
    fireEvent.click(within(s).getByRole("button", { name: "Copiar" }));
    expect(await within(s).findByText("Huella copiada.")).toBeInTheDocument();
    expect(escribirPortapapeles).toHaveBeenCalledWith(huellaFixture.huella);
  });
});

// ---------------------------------------------------------------------------
// Vigencia: flujo completo
// ---------------------------------------------------------------------------
describe("M12 · vigencia del tamizaje", () => {
  it("edita, confirma en la ventana con la tabla antes y después, guarda y recarga historial y huella", async () => {
    const b = backend({ put: { "/api/parametros/vigencia-tamizaje": () => respuestaJson(200, respuestaVigencia) } });
    renderizar();
    const s = await abrirEdicion("Vigencia del tamizaje");
    const guardarCambios = within(s).getByRole("button", { name: "Guardar cambios" });
    expect(guardarCambios).toBeDisabled();
    const campo = within(s).getByLabelText("Días de vigencia");
    expect(campo).toHaveValue(30);
    expect(campo).toHaveAccessibleDescription(/Entre 7 y 90 días/);
    escribir(campo, "45");
    expect(guardarCambios).toBeEnabled();
    fireEvent.click(guardarCambios);

    const ventana = await screen.findByRole("dialog", { name: "Guardar cambios: Vigencia del tamizaje" });
    const fila = within(ventana).getByRole("row", { name: /Días de vigencia/ });
    expect(fila).toHaveTextContent("30 días");
    expect(fila).toHaveTextContent("45 días");
    const motivo = within(ventana).getByLabelText(/Motivo del cambio/);
    await waitFor(() => expect(motivo).toHaveFocus());
    const guardar = within(ventana).getByRole("button", { name: "Guardar" });
    expect(guardar).toBeDisabled();
    escribir(motivo, "corto");
    expect(within(ventana).getByText(/5 de 500 caracteres \(mínimo 10\)/)).toBeInTheDocument();
    expect(guardar).toBeDisabled();
    escribir(motivo, MOTIVO);
    expect(guardar).toBeEnabled();
    const historialesAntes = b.historiales.length;
    const huellasAntes = b.huellas();
    fireEvent.click(guardar);

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(b.cuerpos).toHaveLength(1);
    expect(b.cuerpos[0].cuerpo).toEqual({ motivo_cambio: MOTIVO, referencia: null,
                                          version: parametrosFixture.vigencia_tamizaje.version, valor: 45, verificado: false });
    const exito = await within(s).findByRole("status");
    expect(exito).toHaveTextContent("Cambios guardados en «Vigencia del tamizaje»");
    expect(exito).toHaveTextContent("Días de vigencia: 30 días → 45 días");
    await waitFor(() => expect(exito).toHaveFocus());
    expect(within(s).getByText("45 días")).toBeInTheDocument();
    await waitFor(() => expect(b.historiales.length).toBeGreaterThan(historialesAntes));
    await waitFor(() => expect(b.huellas()).toBeGreaterThan(huellasAntes));
  });

  it("«Descartar» vuelve a lo cargado sin enviar nada", async () => {
    const b = backend({ put: { "/api/parametros/vigencia-tamizaje": () => respuestaJson(200, respuestaVigencia) } });
    renderizar();
    const s = await abrirEdicion("Vigencia del tamizaje");
    escribir(within(s).getByLabelText("Días de vigencia"), "45");
    fireEvent.click(within(s).getByRole("button", { name: "Descartar" }));
    expect(within(s).getByText("30 días")).toBeInTheDocument();
    expect(within(s).queryByLabelText("Días de vigencia")).not.toBeInTheDocument();
    expect(b.cuerpos).toHaveLength(0);
    expect(b.f.mock.calls.some(([, init]) => (init as RequestInit | undefined)?.method === "PUT")).toBe(false);
  });

  it("confirmar contra la norma sin cambiar el valor exige la referencia", async () => {
    const b = backend({ put: { "/api/parametros/vigencia-tamizaje": () => respuestaJson(200, respuestaVigencia) } });
    renderizar();
    const s = await abrirEdicion("Vigencia del tamizaje");
    fireEvent.click(within(s).getByRole("checkbox", { name: "Verificado contra la norma" }));
    fireEvent.click(within(s).getByRole("button", { name: "Guardar cambios" }));
    const ventana = await screen.findByRole("dialog");
    const fila = within(ventana).getByRole("row", { name: /Días de vigencia/ });
    expect(within(fila).getByText("Pendiente de verificar")).toBeInTheDocument();
    expect(within(fila).getByText("Verificado")).toBeInTheDocument();
    escribir(within(ventana).getByLabelText(/Motivo del cambio/), MOTIVO);
    const guardar = within(ventana).getByRole("button", { name: "Guardar" });
    expect(guardar).toBeDisabled();
    escribir(within(ventana).getByLabelText(/Referencia/), "NTS 213, Tabla 4, p. 12");
    fireEvent.click(guardar);
    await waitFor(() => expect(b.cuerpos).toHaveLength(1));
    expect(b.cuerpos[0].cuerpo).toMatchObject({ valor: 30, verificado: true, referencia: "NTS 213, Tabla 4, p. 12" });
  });

  it("al cancelar la ventana el foco vuelve a «Guardar cambios»", async () => {
    backend();
    renderizar();
    const s = await abrirEdicion("Vigencia del tamizaje");
    escribir(within(s).getByLabelText("Días de vigencia"), "45");
    const guardarCambios = within(s).getByRole("button", { name: "Guardar cambios" });
    guardarCambios.focus();
    fireEvent.click(guardarCambios);
    const ventana = await screen.findByRole("dialog");
    fireEvent.click(within(ventana).getByRole("button", { name: "Cancelar" }));
    await waitFor(() => expect(guardarCambios).toHaveFocus());
    expect(within(s).getByLabelText("Días de vigencia")).toHaveValue(45);
  });
});

// ---------------------------------------------------------------------------
// Respuestas de error
// ---------------------------------------------------------------------------
async function enviarVigencia(valor: string) {
  const s = await abrirEdicion("Vigencia del tamizaje");
  escribir(within(s).getByLabelText("Días de vigencia"), valor);
  fireEvent.click(within(s).getByRole("button", { name: "Guardar cambios" }));
  const ventana = await screen.findByRole("dialog");
  escribir(within(ventana).getByLabelText(/Motivo del cambio/), MOTIVO);
  fireEvent.click(within(ventana).getByRole("button", { name: "Guardar" }));
  return { s, ventana };
}

describe("M12 · respuestas de error", () => {
  it("VALIDACION: resumen en la ventana y el error junto al campo, sin cerrar", async () => {
    backend({ put: { "/api/parametros/vigencia-tamizaje": () => respuestaJson(422, validacion) } });
    renderizar();
    const { s, ventana } = await enviarVigencia("100");
    const alerta = await within(ventana).findByRole("alert");
    expect(alerta).toHaveTextContent("Días de vigencia: debe ser un número entero de días entre 7 y 90");
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(within(s).getByLabelText("Días de vigencia")).toHaveAccessibleDescription(/debe ser un número entero de días entre 7 y 90/);
    expect(within(s).getByLabelText("Días de vigencia")).toHaveAttribute("aria-invalid", "true");
  });

  it("REQUIERE_CONFIRMACION: advertencias y Guardar solo con el texto exacto CONFIRMO, que se reenvía", async () => {
    let n = 0;
    const b = backend({ put: { "/api/parametros/vigencia-tamizaje": () => (++n === 1 ? respuestaJson(422, confirmacion)
      : respuestaJson(200, respuestaVigencia)) } });
    renderizar();
    const { ventana } = await enviarVigencia("75");
    expect(await within(ventana).findByText(/una vigencia de 75 días supera los 60 días/)).toBeInTheDocument();
    const campo = within(ventana).getByLabelText("Escriba CONFIRMO para continuar");
    const guardar = within(ventana).getByRole("button", { name: "Guardar" });
    expect(guardar).toBeDisabled();
    for (const texto of ["confirmo", "CONFIRMO ", " CONFIRMO", "CONFIRM", "Confirmo"]) {
      escribir(campo, texto);
      expect(guardar, texto).toBeDisabled();
    }
    escribir(campo, "CONFIRMO");
    expect(guardar).toBeEnabled();
    fireEvent.click(guardar);
    await waitFor(() => expect(b.cuerpos).toHaveLength(2));
    expect(b.cuerpos[0].cuerpo).not.toHaveProperty("confirmacion_escrita");
    expect(b.cuerpos[1].cuerpo).toMatchObject({ confirmacion_escrita: "CONFIRMO", valor: 75, motivo_cambio: MOTIVO });
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("SIN_CAMBIOS: mensaje sin perder lo escrito", async () => {
    backend({ put: { "/api/parametros/vigencia-tamizaje": () => respuestaJson(422, sinCambios) } });
    renderizar();
    const { ventana } = await enviarVigencia("45");
    expect(await within(ventana).findByText(sinCambios.detail)).toBeInTheDocument();
    expect(within(ventana).getByLabelText(/Motivo del cambio/)).toHaveValue(MOTIVO);
  });

  it("409: mensaje y «Recargar valores», que descarta la edición y vuelve a leer", async () => {
    const b = backend({ put: { "/api/parametros/vigencia-tamizaje": () => respuestaJson(409, conflicto) } });
    renderizar();
    const { ventana } = await enviarVigencia("45");
    expect(await within(ventana).findByText(conflicto.detail)).toBeInTheDocument();
    expect(within(ventana).getByRole("button", { name: "Guardar" })).toBeDisabled();
    expect(within(ventana).getByLabelText(/Motivo del cambio/)).toHaveValue(MOTIVO);
    const lecturas = b.lecturas();
    fireEvent.click(within(ventana).getByRole("button", { name: "Recargar valores" }));
    await waitFor(() => expect(b.lecturas()).toBe(lecturas + 1));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    const s = await seccion("Vigencia del tamizaje");
    expect(within(s).queryByLabelText("Días de vigencia")).not.toBeInTheDocument();
    expect(within(s).getByText("30 días")).toBeInTheDocument();
  });

  it("423: mensaje y la edición queda deshabilitada", async () => {
    backend({ put: { "/api/parametros/vigencia-tamizaje": () => respuestaJson(423, {
      detail: "El sistema está en modo de evaluación: los cambios de parámetros y de la base de conocimiento están bloqueados hasta que termine la evaluación." }) } });
    renderizar();
    const { s, ventana } = await enviarVigencia("45");
    expect(await within(ventana).findByText(/El sistema está en modo de evaluación/)).toBeInTheDocument();
    expect(within(ventana).getByRole("button", { name: "Guardar" })).toBeDisabled();
    fireEvent.click(within(ventana).getByRole("button", { name: "Cancelar" }));
    expect(await screen.findByText(`${AVISO_EVALUACION}.`, { selector: "strong" })).toBeInTheDocument();
    expect(within(s).getByLabelText("Días de vigencia")).toBeDisabled();
    expect(within(s).getByRole("button", { name: "Guardar cambios" })).toBeDisabled();
    for (const b of screen.getAllByRole("button", { name: "Editar" })) expect(b).toBeDisabled();
  });

  it("403: mensaje claro", async () => {
    backend({ put: { "/api/parametros/vigencia-tamizaje": () => respuestaJson(403, { detail: "Su rol no tiene el permiso CONFIGURAR_PARAMETROS" }) } });
    renderizar();
    const { ventana } = await enviarVigencia("45");
    expect(await within(ventana).findByText("Su rol no tiene el permiso CONFIGURAR_PARAMETROS")).toBeInTheDocument();
    expect(within(ventana).getByRole("button", { name: "Guardar" })).toBeDisabled();
  });
});

// ---------------------------------------------------------------------------
// Puntos de corte y altitud
// ---------------------------------------------------------------------------
describe("M12 · puntos de corte y ajuste por altitud", () => {
  it("el límite inferior se calcula solo, con aritmética exacta, y acepta coma o punto", async () => {
    const b = backend({ put: { "/api/parametros/puntos-corte": () => respuestaJson(422, sinCambios) } });
    renderizar();
    const s = await abrirEdicion("Puntos de corte de hemoglobina");
    const moderada = within(s).getByLabelText("Límite superior de Anemia moderada, 24 a 59 meses (g/dL)");
    const leve = within(s).getByLabelText("Límite superior de Anemia leve, 24 a 59 meses (g/dL)");
    expect(within(s).queryByLabelText(/Límite superior de Sin anemia/)).not.toBeInTheDocument();
    expect(within(s).queryByLabelText(/Límite inferior/)).not.toBeInTheDocument();
    escribir(moderada, "9,8");
    escribir(leve, "10.9");
    const filaLeve = within(s).getAllByRole("row", { name: /^Anemia leve/ })[1];
    expect(within(filaLeve).getByText("9.9")).toBeInTheDocument();
    const filaSin = within(s).getAllByRole("row", { name: /^Sin anemia/ })[1];
    expect(filaSin).toHaveTextContent("11.0");
    expect(filaSin).not.toHaveTextContent(/11\.0000|10\.9999/);
    escribir(leve, "10,95");
    expect(within(s).getByText(/Escriba un número con un decimal como máximo/)).toBeInTheDocument();
    expect(within(s).getByRole("button", { name: "Guardar cambios" })).toBeDisabled();
    escribir(leve, "10.9");

    fireEvent.click(within(s).getByRole("button", { name: "Guardar cambios" }));
    const ventana = await screen.findByRole("dialog");
    const filas = within(ventana).getAllByRole("row").slice(1);
    expect(filas.map((f) => f.querySelector("th")?.textContent)).toEqual(
      ["24 a 59 meses · Anemia leve", "24 a 59 meses · Anemia moderada"]);
    expect(filas[0]).toHaveTextContent("10.0 a 10.9 g/dL");
    expect(filas[0]).toHaveTextContent("9.9 a 10.9 g/dL");
    expect(filas[1]).toHaveTextContent("7.0 a 9.8 g/dL");
    escribir(within(ventana).getByLabelText(/Motivo del cambio/), MOTIVO);
    fireEvent.click(within(ventana).getByRole("button", { name: "Guardar" }));
    await waitFor(() => expect(b.cuerpos).toHaveLength(1));
    const tramos = b.cuerpos[0].cuerpo.tramos as { edad_min_meses: number; categorias: { categoria: string; hb_min_g_dl: number | null; hb_max_g_dl: number | null; verificado: boolean }[] }[];
    const t = tramos.find((x) => x.edad_min_meses === 24)!;
    const por = Object.fromEntries(t.categorias.map((c) => [c.categoria, [c.hb_min_g_dl, c.hb_max_g_dl]]));
    expect(por).toEqual({ SIN_ANEMIA: [11, null], ANEMIA_LEVE: [9.9, 10.9], ANEMIA_MODERADA: [7, 9.8], ANEMIA_SEVERA: [null, 6.9] });
    expect(b.cuerpos[0].cuerpo.version).toBe(parametrosFixture.puntos_corte.version);
    expect(tramos).toHaveLength(2);
  });

  it("errores de VALIDACION junto a la fila del punto de corte", async () => {
    const error = { detail: "Revise los datos ingresados. tramos.1.categorias.1.hb_min_g_dl: debe ser 10.0", codigo: "VALIDACION",
                    errores: [{ campo: "tramos.1.categorias.1.hb_min_g_dl", mensaje: "debe ser 10.0: los límites deben ser contiguos" }] };
    backend({ put: { "/api/parametros/puntos-corte": () => respuestaJson(422, error) } });
    renderizar();
    const s = await abrirEdicion("Puntos de corte de hemoglobina");
    escribir(within(s).getByLabelText("Límite superior de Anemia moderada, 24 a 59 meses (g/dL)"), "9.8");
    fireEvent.click(within(s).getByRole("button", { name: "Guardar cambios" }));
    const ventana = await screen.findByRole("dialog");
    escribir(within(ventana).getByLabelText(/Motivo del cambio/), MOTIVO);
    fireEvent.click(within(ventana).getByRole("button", { name: "Guardar" }));
    expect(await within(ventana).findByText(/24 a 59 meses, Anemia leve, límite inferior: debe ser 10.0/)).toBeInTheDocument();
    expect(within(s).getByLabelText("Límite superior de Anemia leve, 24 a 59 meses (g/dL)"))
      .toHaveAccessibleDescription(/debe ser 10.0: los límites deben ser contiguos/);
  });

  it("ajuste por altitud: solo el ajuste es editable y el cuerpo reenvía los rangos", async () => {
    const b = backend({ put: { "/api/parametros/ajuste-altitud": () => respuestaJson(422, sinCambios) } });
    renderizar();
    const s = await abrirEdicion("Ajuste por altitud");
    expect(within(s).getAllByRole("textbox")).toHaveLength(parametrosFixture.ajuste_altitud.rangos.length);
    escribir(within(s).getByLabelText("Ajuste para 0 a 499 m.s.n.m. (g/dL)"), "0,1");
    fireEvent.click(within(s).getByRole("button", { name: "Guardar cambios" }));
    const ventana = await screen.findByRole("dialog");
    const filas = within(ventana).getAllByRole("row").slice(1);
    expect(filas).toHaveLength(1);
    expect(filas[0]).toHaveTextContent("0.0 g/dL");
    expect(filas[0]).toHaveTextContent("0.1 g/dL");
    escribir(within(ventana).getByLabelText(/Motivo del cambio/), MOTIVO);
    fireEvent.click(within(ventana).getByRole("button", { name: "Guardar" }));
    await waitFor(() => expect(b.cuerpos).toHaveLength(1));
    const rangos = b.cuerpos[0].cuerpo.rangos as { altitud_min_msnm: number; altitud_max_msnm: number; ajuste_g_dl: number }[];
    expect(rangos).toHaveLength(parametrosFixture.ajuste_altitud.rangos.length);
    expect(rangos[0]).toMatchObject({ altitud_min_msnm: 0, altitud_max_msnm: 499, ajuste_g_dl: 0.1 });
    expect(rangos[1].ajuste_g_dl).toBe(parametrosFixture.ajuste_altitud.rangos[1].ajuste_g_dl);
    expect(b.cuerpos[0].cuerpo.version).toBe(parametrosFixture.ajuste_altitud.version);
  });
});

// ---------------------------------------------------------------------------
// Historial
// ---------------------------------------------------------------------------
describe("M12 · historial", () => {
  it("pagina de 20 y filtra por grupo", async () => {
    const b = backend({ historial: { ...(copia(historialFixture) as PaginaHistorial), total: 45 } });
    renderizar();
    const s = await seccion("Historial de cambios");
    const nav = await within(s).findByRole("navigation", { name: "Paginación del historial" });
    expect(nav).toHaveTextContent("Página 1 de 3");
    fireEvent.click(within(nav).getByRole("button", { name: "Siguiente" }));
    await waitFor(() => expect(ultima(b.historiales)?.searchParams.get("desplazamiento")).toBe("20"));
    expect(ultima(b.historiales)?.searchParams.get("limite")).toBe("20");
    fireEvent.change(within(s).getByLabelText("Grupo"), { target: { value: "recuperacion" } });
    await waitFor(() => expect(ultima(b.historiales)?.searchParams.get("grupo")).toBe("recuperacion"));
    expect(ultima(b.historiales)?.searchParams.get("desplazamiento")).toBe("0");
  });

  it("columnas legibles en la tabla y tarjetas por debajo de 800 px", async () => {
    backend();
    renderizar();
    const s = await seccion("Historial de cambios");
    const tabla = await within(s).findByRole("region", { name: "Versiones de los parámetros" });
    expect(within(tabla).getAllByRole("columnheader").map((c) => c.textContent)).toEqual(
      ["Elemento", "Valor", "Vigente desde", "Hasta", "Motivo", "Referencia", "Verificado", "Quién"]);
    expect(within(tabla).getAllByRole("row")).toHaveLength(historialFixture.versiones.length + 1);
    expect(tabla).not.toHaveTextContent("BONIFICACION_EDAD");
  });

  it("en pantalla angosta el historial va en tarjetas", async () => {
    const lista = { matches: true, media: CONSULTA_ANGOSTA, addEventListener: vi.fn(), removeEventListener: vi.fn() };
    Object.defineProperty(window, "matchMedia", { configurable: true, writable: true, value: () => lista });
    backend();
    renderizar();
    const s = await seccion("Historial de cambios");
    const tarjetas = await within(s).findByRole("list", { name: "Versiones de los parámetros" });
    expect(within(tarjetas).getAllByRole("listitem")).toHaveLength(historialFixture.versiones.length);
  });
});
