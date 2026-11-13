// Consultas clínicas (Sprint 2, parte E1): lector del NDJSON por etapas y llamadas JSON.
// Contrato: docs/contrato_consultas.md. Tipos: ./tipos_consulta.ts.
import { api, cabecerasCon, errorDeRespuesta, guardarToken } from "./cliente";
import {
  esEventoConocido,
  esEventoFinal,
  type ConsultaEntrada,
  type ConsultaListada,
  type DatosFaltantesEntrada,
  type Decision,
  type DecisionEntrada,
  type EventoConsulta,
  type EventoFinal,
  type ResultadoConsulta,
} from "./tipos_consulta";

// Plazo del cliente para todo el stream, desde el envío hasta el evento final.
export const PLAZO_STREAM_MS = 120_000;
// Recuperación tras un corte: GET cada 2 s hasta 60 s mientras siga EN_PROCESO.
export const INTERVALO_RECUPERACION_MS = 2_000;
export const PLAZO_RECUPERACION_MS = 60_000;

export type CodigoErrorConsulta =
  | "stream_cortado" // el stream terminó sin evento fin ni error
  | "respuesta_invalida" // una línea no es JSON válido
  | "plazo_agotado" // pasaron PLAZO_STREAM_MS sin evento final
  | "cancelada" // el usuario canceló (AbortController)
  | "recuperacion_agotada"; // la consulta siguió EN_PROCESO durante PLAZO_RECUPERACION_MS

const MENSAJES: Record<CodigoErrorConsulta, string> = {
  stream_cortado: "Se interrumpió la conexión antes de recibir el resultado de la consulta.",
  respuesta_invalida: "El servidor envió una respuesta que no se pudo leer.",
  plazo_agotado: "La consulta superó el tiempo máximo de espera.",
  cancelada: "Se canceló la consulta.",
  recuperacion_agotada: "La consulta sigue en proceso. Revise el resultado más tarde en las consultas del paciente.",
};

// Error del lector después de un 200. id_consulta permite recuperar el resultado con el GET
// (la consulta sigue en el servidor hasta su estado final aunque el cliente se desconecte).
export class ErrorConsulta extends Error {
  constructor(
    public codigo: CodigoErrorConsulta,
    public id_consulta: string | null = null,
    mensaje: string = MENSAJES[codigo],
  ) {
    super(mensaje);
    this.name = "ErrorConsulta";
  }
}

export type OpcionesStream = {
  senal?: AbortSignal; // cancelación por el usuario
  plazoMs?: number;
};

function idDe(evento: EventoConsulta): string | null {
  return "id_consulta" in evento && typeof evento.id_consulta === "string" ? evento.id_consulta : null;
}

// read() que también termina si se aborta, aunque la implementación de fetch no lo propague.
function leerTrozo(
  lector: ReadableStreamDefaultReader<Uint8Array>,
  senal: AbortSignal,
): Promise<ReadableStreamReadResult<Uint8Array>> {
  if (senal.aborted) return Promise.reject(senal.reason);
  return new Promise((resolver, rechazar) => {
    const alAbortar = () => rechazar(senal.reason);
    senal.addEventListener("abort", alAbortar, { once: true });
    lector.read().then(
      (r) => {
        senal.removeEventListener("abort", alAbortar);
        resolver(r);
      },
      (e) => {
        senal.removeEventListener("abort", alAbortar);
        rechazar(e);
      },
    );
  });
}

/**
 * POST que responde NDJSON. Entrega cada evento conocido en orden (los de tipo desconocido se
 * ignoran) y termina con el evento final («fin» o «error»), que también es el valor de retorno.
 *
 * - Respuesta distinta de 200 antes del stream: ErrorApi con el «detail» del backend. Un 401
 *   además borra el token de la sesión.
 * - Stream sin evento final, línea inválida, plazo agotado o cancelación: ErrorConsulta, con el
 *   id_consulta si ya llegó.
 */
export async function* leerStreamConsulta(
  ruta: string,
  cuerpo: unknown,
  { senal, plazoMs = PLAZO_STREAM_MS }: OpcionesStream = {},
): AsyncGenerator<EventoConsulta, EventoFinal, void> {
  const controlador = new AbortController();
  let motivo: "cancelada" | "plazo_agotado" | null = null;
  const abortar = (m: "cancelada" | "plazo_agotado") => {
    motivo ??= m;
    controlador.abort(new ErrorConsulta(motivo));
  };
  const alCancelar = () => abortar("cancelada");
  if (senal?.aborted) throw new ErrorConsulta("cancelada");
  senal?.addEventListener("abort", alCancelar, { once: true });
  const temporizador = setTimeout(() => abortar("plazo_agotado"), plazoMs);

  let idConsulta: string | null = null;
  let lector: ReadableStreamDefaultReader<Uint8Array> | null = null;
  let respondio = false;
  // Un fallo de red o un aborto se traduce según la causa y el momento.
  const traducir = (e: unknown): unknown => {
    if (motivo) return new ErrorConsulta(motivo, idConsulta);
    if (respondio && !(e instanceof ErrorConsulta)) return new ErrorConsulta("stream_cortado", idConsulta);
    return e; // antes de la respuesta: el error de red tal cual (como api())
  };

  try {
    const opciones: RequestInit = { method: "POST", body: JSON.stringify(cuerpo) };
    let respuesta: Response;
    try {
      respuesta = await fetch(ruta, {
        ...opciones,
        headers: cabecerasCon({ ...opciones, headers: { Accept: "application/x-ndjson" } }),
        signal: controlador.signal,
      });
    } catch (e) {
      throw traducir(e);
    }
    if (respuesta.status !== 200) {
      if (respuesta.status === 401) guardarToken(null);
      throw await errorDeRespuesta(respuesta);
    }
    respondio = true;
    if (!respuesta.body) throw new ErrorConsulta("stream_cortado");
    lector = respuesta.body.getReader();
    const decodificador = new TextDecoder("utf-8");
    let bufer = "";

    for (;;) {
      let trozo: ReadableStreamReadResult<Uint8Array>;
      try {
        trozo = await leerTrozo(lector, controlador.signal);
      } catch (e) {
        throw traducir(e);
      }
      // stream: true conserva un carácter multibyte partido entre dos trozos.
      bufer += trozo.done ? decodificador.decode() : decodificador.decode(trozo.value, { stream: true });
      const lineas = bufer.split("\n");
      bufer = trozo.done ? "" : (lineas.pop() ?? ""); // la última línea puede venir sin \n

      for (const linea of lineas) {
        if (!linea.trim()) continue;
        let valor: unknown;
        try {
          valor = JSON.parse(linea);
        } catch {
          throw new ErrorConsulta("respuesta_invalida", idConsulta);
        }
        if (!esEventoConocido(valor)) continue;
        idConsulta ??= idDe(valor);
        yield valor;
        if (esEventoFinal(valor)) return valor;
      }
      if (trozo.done) throw new ErrorConsulta("stream_cortado", idConsulta);
    }
  } finally {
    clearTimeout(temporizador);
    senal?.removeEventListener("abort", alCancelar);
    // Si quien consume deja de iterar, se libera la conexión.
    lector?.cancel().catch(() => undefined);
  }
}

function esperar(ms: number, senal?: AbortSignal): Promise<void> {
  return new Promise((resolver, rechazar) => {
    if (senal?.aborted) return rechazar(new ErrorConsulta("cancelada"));
    const alAbortar = () => {
      clearTimeout(t);
      rechazar(new ErrorConsulta("cancelada"));
    };
    const t = setTimeout(() => {
      senal?.removeEventListener("abort", alAbortar);
      resolver();
    }, ms);
    senal?.addEventListener("abort", alAbortar, { once: true });
  });
}

const json = (cuerpo: unknown): RequestInit => ({ body: JSON.stringify(cuerpo) });

export const consultasApi = {
  // POST /api/pacientes/{id}/consultas (NDJSON)
  consultar: (idPaciente: string, entrada: ConsultaEntrada, opciones?: OpcionesStream) =>
    leerStreamConsulta(`/api/pacientes/${idPaciente}/consultas`, entrada, opciones),
  // POST /api/consultas/{id}/datos-faltantes (NDJSON, reanuda como consulta nueva)
  completarDatosFaltantes: (idConsulta: string, datos: DatosFaltantesEntrada, opciones?: OpcionesStream) =>
    leerStreamConsulta(`/api/consultas/${idConsulta}/datos-faltantes`, datos, opciones),
  // GET /api/pacientes/{id}/consultas: solo las del usuario, de la más reciente a la más antigua
  listar: (idPaciente: string) => api<ConsultaListada[]>(`/api/pacientes/${idPaciente}/consultas`),
  // GET /api/consultas/{id}
  resultado: (idConsulta: string, senal?: AbortSignal) =>
    api<ResultadoConsulta>(`/api/consultas/${idConsulta}`, { signal: senal }),
  // POST /api/consultas/{id}/decision (201)
  registrarDecision: (idConsulta: string, entrada: DecisionEntrada) =>
    api<Decision>(`/api/consultas/${idConsulta}/decision`, { method: "POST", ...json(entrada) }),
};

/**
 * Recupera el resultado de una consulta cuyo stream se cortó, sin reenviarla: consulta el GET
 * cada INTERVALO_RECUPERACION_MS mientras el estado sea EN_PROCESO, hasta PLAZO_RECUPERACION_MS.
 * Devuelve el resultado con estado final o lanza ErrorConsulta «recuperacion_agotada». Los
 * errores del GET (404, red) se propagan.
 */
export async function recuperarResultado(
  idConsulta: string,
  {
    senal,
    intervaloMs = INTERVALO_RECUPERACION_MS,
    plazoMs = PLAZO_RECUPERACION_MS,
  }: { senal?: AbortSignal; intervaloMs?: number; plazoMs?: number } = {},
): Promise<ResultadoConsulta> {
  for (let esperado = 0; ; esperado += intervaloMs) {
    const resultado = await consultasApi.resultado(idConsulta, senal);
    if (resultado.estado !== "EN_PROCESO") return resultado;
    if (esperado + intervaloMs > plazoMs) throw new ErrorConsulta("recuperacion_agotada", idConsulta);
    await esperar(intervaloMs, senal);
  }
}
