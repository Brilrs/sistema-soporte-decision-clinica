/// <reference types="vite/client" />
// Pruebas del lector NDJSON de consultas y de la recuperación tras un corte (parte E1).
// fetch se simula: nunca se llama al backend ni a la API del modelo de lenguaje.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ErrorApi, guardarToken, leerToken } from "./cliente";
import { consultasApi, ErrorConsulta, leerStreamConsulta, recuperarResultado } from "./consultas";
import { ESTADOS_FINALES, type EventoConsulta, type EventoFinal, type ResultadoConsulta } from "./tipos_consulta";

const RUTA = "/api/pacientes/p-1/consultas";
const ID = "00000000-0000-4000-8000-000000000001";
const codificador = new TextEncoder();

const etapa = (n: number, extra: object = {}) => ({
  tipo: "etapa",
  etapa: "validar",
  intento: null,
  ms: 10,
  id_consulta: ID,
  transcurrido_ms: n,
  ...extra,
});
const fin = (extra: object = {}) => ({
  tipo: "fin",
  id_consulta: ID,
  id_paciente: "p-1",
  id_consulta_previa: null,
  estado: "VERIFICADA",
  mensaje: null,
  idioma: "es",
  datos_faltantes: [],
  vigencia: { dias_transcurridos: 1, dias_vigencia: 30, continua_con_tamizaje_no_vigente: false },
  clasificacion: null,
  recomendacion: null,
  citas: [],
  numero_intentos: 1,
  intentos: [],
  verificacion: null,
  modo_prueba: true,
  opciones_decision: [],
  tiempos_ms: null,
  transcurrido_ms: 900,
  ...extra,
});
const linea = (o: object) => JSON.stringify(o) + "\n";

// Respuesta 200 cuyo cuerpo llega en los trozos indicados (texto o bytes). Con abierto: true el
// stream no se cierra nunca (para probar la cancelación y el plazo).
function respuestaNdjson(trozos: (string | Uint8Array)[], { abierto = false } = {}): Response {
  const cuerpo = new ReadableStream<Uint8Array>({
    start(c) {
      for (const t of trozos) c.enqueue(typeof t === "string" ? codificador.encode(t) : t);
      if (!abierto) c.close();
    },
  });
  return new Response(cuerpo, { status: 200, headers: { "Content-Type": "application/x-ndjson" } });
}

function respuestaJson(estado: number, datos: unknown): Response {
  return new Response(JSON.stringify(datos), { status: estado, headers: { "Content-Type": "application/json" } });
}

function simularFetch(...respuestas: (Response | (() => Response))[]) {
  const fetchFalso = vi.fn(async (_ruta: RequestInfo | URL, _init?: RequestInit) => {
    const r = respuestas.length > 1 ? respuestas.shift()! : respuestas[0];
    return typeof r === "function" ? r() : r;
  });
  vi.stubGlobal("fetch", fetchFalso);
  return fetchFalso;
}

async function leerTodo(gen: AsyncGenerator<EventoConsulta, EventoFinal, void>) {
  const eventos: EventoConsulta[] = [];
  for (;;) {
    const r = await gen.next();
    if (r.done) return { eventos, final: r.value };
    eventos.push(r.value);
  }
}

async function errorDe(promesa: Promise<unknown>): Promise<unknown> {
  try {
    await promesa;
  } catch (e) {
    return e;
  }
  throw new Error("se esperaba un error");
}

describe("lector NDJSON", () => {
  it("envía POST con Authorization y el cuerpo en JSON", async () => {
    guardarToken("token-de-prueba");
    const f = simularFetch(respuestaNdjson([linea(fin())]));
    await leerTodo(leerStreamConsulta(RUTA, { texto_consulta: "¿Dosis de hierro?" }));
    const [ruta, init] = f.mock.calls[0];
    const cabeceras = new Headers(init?.headers);
    expect(ruta).toBe(RUTA);
    expect(init?.method).toBe("POST");
    expect(cabeceras.get("Authorization")).toBe("Bearer token-de-prueba");
    expect(cabeceras.get("Content-Type")).toBe("application/json");
    expect(JSON.parse(init?.body as string)).toEqual({ texto_consulta: "¿Dosis de hierro?" });
  });

  it("arma una línea partida entre dos trozos", async () => {
    const texto = linea(etapa(1)) + linea(fin());
    const corte = 25;
    simularFetch(respuestaNdjson([texto.slice(0, corte), texto.slice(corte)]));
    const { eventos, final } = await leerTodo(leerStreamConsulta(RUTA, {}));
    expect(eventos.map((e) => e.tipo)).toEqual(["etapa", "fin"]);
    expect(final.estado).toBe("VERIFICADA");
  });

  it("separa varias líneas que llegan en un solo trozo", async () => {
    simularFetch(respuestaNdjson([linea(etapa(1)) + linea(etapa(2, { etapa: "clasificar" })) + linea(fin())]));
    const { eventos } = await leerTodo(leerStreamConsulta(RUTA, {}));
    expect(eventos.map((e) => (e.tipo === "etapa" ? e.etapa : e.tipo))).toEqual(["validar", "clasificar", "fin"]);
  });

  it("conserva un carácter UTF-8 de varios bytes cortado entre trozos", async () => {
    const mensaje = "Hemoglobina ajustada por altitud: ¿anemia leve? Sí, según la NTS N.° 213";
    const bytes = codificador.encode(linea(fin({ estado: "ERROR", mensaje })));
    // Corta justo dentro de la «í» (2 bytes) y de la «°» (2 bytes).
    const i = bytes.indexOf(0xc3);
    const j = bytes.lastIndexOf(0xc2);
    simularFetch(respuestaNdjson([bytes.slice(0, i + 1), bytes.slice(i + 1, j + 1), bytes.slice(j + 1)]));
    const { final } = await leerTodo(leerStreamConsulta(RUTA, {}));
    expect(final.mensaje).toBe(mensaje);
  });

  it("acepta la línea final sin salto de línea", async () => {
    simularFetch(respuestaNdjson([linea(etapa(1)) + JSON.stringify(fin())]));
    const { final } = await leerTodo(leerStreamConsulta(RUTA, {}));
    expect(final.tipo).toBe("fin");
  });

  it("ignora líneas vacías y eventos de tipo desconocido", async () => {
    simularFetch(respuestaNdjson([linea(etapa(1)), "\n", linea({ tipo: "latido", t: 1 }), linea({ sin_tipo: 1 }), linea(fin())]));
    const { eventos } = await leerTodo(leerStreamConsulta(RUTA, {}));
    expect(eventos.map((e) => e.tipo)).toEqual(["etapa", "fin"]);
  });

  it("una línea que no es JSON lanza respuesta_invalida con el id de la consulta", async () => {
    simularFetch(respuestaNdjson([linea(etapa(1)), '{"tipo": "etapa", roto\n', linea(fin())]));
    const gen = leerStreamConsulta(RUTA, {});
    expect((await gen.next()).value).toMatchObject({ tipo: "etapa" });
    const e = await errorDe(gen.next());
    expect(e).toBeInstanceOf(ErrorConsulta);
    expect(e).toMatchObject({ codigo: "respuesta_invalida", id_consulta: ID });
  });

  it("un stream que termina sin fin ni error lanza stream_cortado con el id_consulta recibido", async () => {
    simularFetch(respuestaNdjson([linea(etapa(1)), linea(etapa(2, { etapa: "clasificar" }))]));
    const e = await errorDe(leerTodo(leerStreamConsulta(RUTA, {})));
    expect(e).toMatchObject({ codigo: "stream_cortado", id_consulta: ID });
  });

  it("stream_cortado sin id_consulta si no llegó ninguno", async () => {
    simularFetch(respuestaNdjson([linea({ tipo: "en_cola", etapa: "recuperar", recurso: "modelos", transcurrido_ms: 5 })]));
    const e = await errorDe(leerTodo(leerStreamConsulta(RUTA, {})));
    expect(e).toMatchObject({ codigo: "stream_cortado", id_consulta: null });
  });

  it("un fallo de red a mitad del stream es stream_cortado", async () => {
    let n = 0;
    const cuerpo = new ReadableStream<Uint8Array>({
      pull(c) {
        if (n++ === 0) c.enqueue(codificador.encode(linea(etapa(1))));
        else c.error(new TypeError("network error"));
      },
    });
    simularFetch(new Response(cuerpo, { status: 200 }));
    const e = await errorDe(leerTodo(leerStreamConsulta(RUTA, {})));
    expect(e).toMatchObject({ codigo: "stream_cortado", id_consulta: ID });
  });

  it("el evento error se entrega como estado final y deja de leer", async () => {
    const error = {
      tipo: "error",
      id_consulta: ID,
      id_paciente: "p-1",
      estado: "ERROR",
      mensaje: "No se pudo evaluar la consulta. Aplique su criterio clínico.",
      opciones_decision: [{ tipo: "CRITERIO_CLINICO_PROPIO", nota_obligatoria: false }],
      transcurrido_ms: 300,
    };
    simularFetch(respuestaNdjson([linea(etapa(1)), linea(error), linea(fin())]));
    const { eventos, final } = await leerTodo(leerStreamConsulta(RUTA, {}));
    expect(eventos.map((e) => e.tipo)).toEqual(["etapa", "error"]);
    expect(final).toEqual(error);
  });

  it("401 lanza ErrorApi con el detail y cierra la sesión", async () => {
    guardarToken("token-vencido");
    simularFetch(respuestaJson(401, { detail: "La sesión expiró. Inicie sesión nuevamente." }));
    const e = await errorDe(leerTodo(leerStreamConsulta(RUTA, {})));
    expect(e).toBeInstanceOf(ErrorApi);
    expect(e).toMatchObject({ estado: 401, message: "La sesión expiró. Inicie sesión nuevamente." });
    expect(leerToken()).toBeNull();
  });

  it.each([
    [409, "La consulta previa ya se reanudó"],
    [422, "Revise los datos ingresados. texto_consulta: es obligatorio"],
    [404, "El paciente no existe"],
  ])("%i lanza ErrorApi con el mensaje del backend y conserva la sesión", async (estado, detalle) => {
    guardarToken("token-valido");
    simularFetch(respuestaJson(estado, { detail: detalle, errores: [] }));
    const e = await errorDe(leerTodo(leerStreamConsulta(RUTA, {})));
    expect(e).toBeInstanceOf(ErrorApi);
    expect(e).toMatchObject({ estado, message: detalle });
    expect(leerToken()).toBe("token-valido");
  });

  it("un error sin cuerpo JSON usa el mensaje genérico", async () => {
    simularFetch(new Response("Bad Gateway", { status: 502 }));
    const e = await errorDe(leerTodo(leerStreamConsulta(RUTA, {})));
    expect(e).toMatchObject({ estado: 502, message: "No se pudo completar la operación" });
  });

  it("la cancelación con AbortController corta la lectura y libera la conexión", async () => {
    const controlador = new AbortController();
    let cancelado = false;
    const cuerpo = new ReadableStream<Uint8Array>({
      start(c) {
        c.enqueue(codificador.encode(linea(etapa(1))));
      },
      cancel() {
        cancelado = true;
      },
    });
    const f = simularFetch(new Response(cuerpo, { status: 200 }));
    const gen = leerStreamConsulta(RUTA, {}, { senal: controlador.signal });
    expect((await gen.next()).value).toMatchObject({ tipo: "etapa" });
    const pendiente = gen.next();
    controlador.abort();
    const e = await errorDe(pendiente);
    expect(e).toMatchObject({ codigo: "cancelada", id_consulta: ID });
    expect(cancelado).toBe(true);
    expect((f.mock.calls[0][1]?.signal as AbortSignal).aborted).toBe(true);
  });

  it("una señal ya cancelada no envía la consulta", async () => {
    const f = simularFetch(respuestaNdjson([linea(fin())]));
    const controlador = new AbortController();
    controlador.abort();
    const e = await errorDe(leerTodo(leerStreamConsulta(RUTA, {}, { senal: controlador.signal })));
    expect(e).toMatchObject({ codigo: "cancelada" });
    expect(f).not.toHaveBeenCalled();
  });

  it("dejar de iterar libera la conexión", async () => {
    let cancelado = false;
    const cuerpo = new ReadableStream<Uint8Array>({
      start(c) {
        c.enqueue(codificador.encode(linea(etapa(1))));
      },
      cancel() {
        cancelado = true;
      },
    });
    simularFetch(new Response(cuerpo, { status: 200 }));
    for await (const evento of leerStreamConsulta(RUTA, {})) {
      expect(evento.tipo).toBe("etapa");
      break;
    }
    expect(cancelado).toBe(true);
  });

  describe("con temporizadores simulados", () => {
    beforeEach(() => {
      vi.useFakeTimers();
    });
    afterEach(() => {
      vi.useRealTimers();
    });

    it("el plazo del cliente (120 s) lanza plazo_agotado con el id_consulta", async () => {
      simularFetch(respuestaNdjson([linea(etapa(1))], { abierto: true }));
      const gen = leerStreamConsulta(RUTA, {});
      expect((await gen.next()).value).toMatchObject({ tipo: "etapa" });
      const pendiente = errorDe(gen.next());
      await vi.advanceTimersByTimeAsync(119_999);
      await vi.advanceTimersByTimeAsync(1);
      expect(await pendiente).toMatchObject({ codigo: "plazo_agotado", id_consulta: ID });
    });

    it("el plazo también corre mientras se espera la respuesta", async () => {
      vi.stubGlobal(
        "fetch",
        vi.fn(
          (_r: RequestInfo | URL, init?: RequestInit) =>
            new Promise<Response>((_, rechazar) => init?.signal?.addEventListener("abort", () => rechazar(init.signal?.reason))),
        ),
      );
      const pendiente = errorDe(leerTodo(leerStreamConsulta(RUTA, {})));
      await vi.advanceTimersByTimeAsync(120_000);
      expect(await pendiente).toMatchObject({ codigo: "plazo_agotado", id_consulta: null });
    });
  });
});

// ---------------------------------------------------------------------------
// Fixtures reales del contrato (generados por backend/tests/test_e0_fixtures.py)
// ---------------------------------------------------------------------------
const STREAMS = import.meta.glob<string>("../__fixtures__/consulta_*.ndjson", { query: "?raw", import: "default", eager: true });
const RESULTADOS = import.meta.glob<ResultadoConsulta>("../__fixtures__/resultado_*.json", { import: "default", eager: true });

// Corta el stream en trozos de bytes de tamaño variable (sin respetar líneas ni caracteres).
function trocear(texto: string): Uint8Array[] {
  const bytes = codificador.encode(texto);
  const trozos: Uint8Array[] = [];
  for (let i = 0, k = 0; i < bytes.length; k++) {
    const largo = [1, 7, 64, 3, 513, 2][k % 6];
    trozos.push(bytes.slice(i, i + largo));
    i += largo;
  }
  return trozos;
}

describe("fixtures de los 7 estados", () => {
  it("hay un stream y un resultado por estado final", () => {
    const nombres = (o: object, prefijo: string) =>
      Object.keys(o).map((r) => r.replace(/^.*\//, "").replace(prefijo, "").replace(/\..*$/, "").toUpperCase());
    expect(nombres(STREAMS, "consulta_").sort()).toEqual([...ESTADOS_FINALES].sort());
    expect(nombres(RESULTADOS, "resultado_").sort()).toEqual([...ESTADOS_FINALES].sort());
  });

  it.each([...ESTADOS_FINALES])("%s: el stream troceado termina en su estado", async (estado) => {
    const nombre = estado.toLowerCase();
    const texto = STREAMS[`../__fixtures__/consulta_${nombre}.ndjson`];
    const guardado = RESULTADOS[`../__fixtures__/resultado_${nombre}.json`];
    simularFetch(respuestaNdjson(trocear(texto)));
    const { eventos, final } = await leerTodo(consultasApi.consultar("p-1", { texto_consulta: "pregunta sintética" }));
    expect(eventos).toHaveLength(texto.trimEnd().split("\n").length);
    expect(eventos[0].tipo).toBe("etapa");
    expect(final).toBe(eventos[eventos.length - 1]);
    expect(final.tipo).toBe("fin");
    expect(final.estado).toBe(estado);
    expect(final.id_consulta).toBe(guardado.id_consulta);
    expect(guardado.estado).toBe(estado);
    if (final.tipo !== "fin") return;
    expect(final.modo_prueba).toBe(guardado.modo_prueba);
    expect(final.intentos).toEqual(guardado.intentos);
    expect(final.verificacion).toEqual(guardado.verificacion);
    expect(final.numero_intentos).toBe(final.intentos.length);
    if (estado === "VERIFICADA") {
      const ingles = final.citas.find((c) => c.idioma === "en");
      expect(ingles?.extracto_traducido).toBeTruthy();
      expect(ingles?.etiqueta_traduccion).toBe("Traducción de apoyo, no oficial");
      expect(final.citas.every((c) => typeof c.puntaje_reranker === "number")).toBe(true);
    }
  });
});

// ---------------------------------------------------------------------------
// Llamadas JSON y recuperación tras un corte
// ---------------------------------------------------------------------------
describe("llamadas JSON", () => {
  it("listar, resultado y decisión usan las rutas del contrato", async () => {
    const f = simularFetch(
      () => respuestaJson(200, []),
      () => respuestaJson(200, RESULTADOS["../__fixtures__/resultado_verificada.json"]),
      () => respuestaJson(201, { id_decision: "d-1", id_usuario: "u-1", tipo_decision: "ACEPTA_RECOMENDACION", nota: null, fecha_registro: "x" }),
    );
    expect(await consultasApi.listar("p-1")).toEqual([]);
    expect((await consultasApi.resultado(ID)).estado).toBe("VERIFICADA");
    const d = await consultasApi.registrarDecision(ID, { tipo_decision: "ACEPTA_RECOMENDACION" });
    expect(d.id_decision).toBe("d-1");
    expect(f.mock.calls.map(([r, i]) => [r, i?.method ?? "GET"])).toEqual([
      ["/api/pacientes/p-1/consultas", "GET"],
      [`/api/consultas/${ID}`, "GET"],
      [`/api/consultas/${ID}/decision`, "POST"],
    ]);
    expect(JSON.parse(f.mock.calls[2][1]?.body as string)).toEqual({ tipo_decision: "ACEPTA_RECOMENDACION" });
  });

  it("datos faltantes reutiliza el lector NDJSON", async () => {
    const texto = STREAMS["../__fixtures__/consulta_verificada.ndjson"];
    const f = simularFetch(respuestaNdjson([texto]));
    const { final } = await leerTodo(consultasApi.completarDatosFaltantes(ID, { hemoglobina_g_dl: 10.8 }));
    expect(final.estado).toBe("VERIFICADA");
    expect(f.mock.calls[0][0]).toBe(`/api/consultas/${ID}/datos-faltantes`);
    expect(JSON.parse(f.mock.calls[0][1]?.body as string)).toEqual({ hemoglobina_g_dl: 10.8 });
  });

  it("la decisión rechazada (409) lanza ErrorApi con el mensaje", async () => {
    simularFetch(respuestaJson(409, { detail: "La consulta ya tiene una decisión registrada" }));
    const e = await errorDe(consultasApi.registrarDecision(ID, { tipo_decision: "ACEPTA_RECOMENDACION" }));
    expect(e).toMatchObject({ estado: 409, message: "La consulta ya tiene una decisión registrada" });
  });
});

describe("recuperarResultado", () => {
  const verificada = RESULTADOS["../__fixtures__/resultado_verificada.json"];
  const enProceso = { ...verificada, estado: "EN_PROCESO", recomendacion: null, citas: [] };

  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("consulta el GET cada 2 s mientras siga EN_PROCESO y devuelve el resultado", async () => {
    const f = simularFetch(
      () => respuestaJson(200, enProceso),
      () => respuestaJson(200, enProceso),
      () => respuestaJson(200, verificada),
    );
    const promesa = recuperarResultado(ID);
    await vi.advanceTimersByTimeAsync(0);
    expect(f).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1_999);
    expect(f).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(f).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(2_000);
    expect((await promesa).estado).toBe("VERIFICADA");
    expect(f).toHaveBeenCalledTimes(3);
    // Solo GET: nunca reenvía la consulta.
    expect(f.mock.calls.every(([r, i]) => r === `/api/consultas/${ID}` && (i?.method ?? "GET") === "GET")).toBe(true);
  });

  it("si ya tiene estado final no espera", async () => {
    const f = simularFetch(() => respuestaJson(200, verificada));
    expect((await recuperarResultado(ID)).estado).toBe("VERIFICADA");
    expect(f).toHaveBeenCalledTimes(1);
  });

  it("agota el tiempo a los 60 s", async () => {
    const f = simularFetch(() => respuestaJson(200, enProceso));
    const pendiente = errorDe(recuperarResultado(ID));
    await vi.advanceTimersByTimeAsync(60_000);
    expect(await pendiente).toMatchObject({ codigo: "recuperacion_agotada", id_consulta: ID });
    expect(f).toHaveBeenCalledTimes(31); // en 0, 2, 4, ..., 60 s
  });

  it("propaga el 404 del GET", async () => {
    simularFetch(() => respuestaJson(404, { detail: "La consulta no existe" }));
    const e = await errorDe(recuperarResultado(ID));
    expect(e).toMatchObject({ estado: 404, message: "La consulta no existe" });
  });

  it("se puede cancelar mientras espera", async () => {
    simularFetch(() => respuestaJson(200, enProceso));
    const controlador = new AbortController();
    const pendiente = errorDe(recuperarResultado(ID, { senal: controlador.signal }));
    await vi.advanceTimersByTimeAsync(500);
    controlador.abort();
    expect(await pendiente).toMatchObject({ codigo: "cancelada" });
  });
});
