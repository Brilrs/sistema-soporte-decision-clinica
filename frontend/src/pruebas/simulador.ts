/// <reference types="vite/client" />
// Simulador del backend para las pruebas de pantallas: fetch falso por método y ruta, streams
// NDJSON a partir de los fixtures del contrato (src/__fixtures__) y datos ficticios del paciente.
// Nunca llama al backend ni a la API del modelo de lenguaje.
import { vi } from "vitest";
import type { Ficha, Historial, TamizajeHistorial } from "../api/pacientes";
import type { EstadoFinal, ResultadoConsulta } from "../api/tipos_consulta";
import type { DestinoReporte, ReporteListado, VistaPreviaReporte } from "../api/tipos_reporte";
import listaReportes from "../__fixtures__/reportes_lista.json";
import vistaCuidador from "../__fixtures__/reporte_vista_previa_cuidador.json";
import vistaExpediente from "../__fixtures__/reporte_vista_previa_expediente.json";

const codificador = new TextEncoder();

export const STREAMS = import.meta.glob<string>("../__fixtures__/consulta_*.ndjson", {
  query: "?raw",
  import: "default",
  eager: true,
});
export const RESULTADOS = import.meta.glob<ResultadoConsulta>("../__fixtures__/resultado_*.json", {
  import: "default",
  eager: true,
});

export function lineasFixture(estado: EstadoFinal): string[] {
  return STREAMS[`../__fixtures__/consulta_${estado.toLowerCase()}.ndjson`].trimEnd().split("\n");
}

export function resultadoFixture(estado: EstadoFinal): ResultadoConsulta {
  return structuredClone(RESULTADOS[`../__fixtures__/resultado_${estado.toLowerCase()}.json`]);
}

// Id de las consultas de los fixtures (UUID normalizado).
export const ID_CONSULTA = "00000000-0000-4000-8000-000000000001";
export const ID_PACIENTE = "p-0001";
// Paciente y tamizaje de los resultados de los fixtures (resultado_*.json).
export const ID_PACIENTE_FIXTURE = "00000000-0000-4000-8000-000000000002";
export const ID_TAMIZAJE_FIXTURE = "00000000-0000-4000-8000-000000000003";

export function respuestaJson(estado: number, datos: unknown): Response {
  return new Response(JSON.stringify(datos), { status: estado, headers: { "Content-Type": "application/json" } });
}

// Respuesta NDJSON con todo el cuerpo, cortado en trozos de bytes de tamaño variable.
export function respuestaStream(lineas: string[], { cerrar = true } = {}): Response {
  const bytes = codificador.encode(lineas.map((l) => l + "\n").join(""));
  const cuerpo = new ReadableStream<Uint8Array>({
    start(c) {
      for (let i = 0, k = 0; i < bytes.length; k++) {
        const largo = [5, 64, 1, 300][k % 4];
        c.enqueue(bytes.slice(i, i + largo));
        i += largo;
      }
      if (cerrar) c.close();
    },
  });
  return new Response(cuerpo, { status: 200, headers: { "Content-Type": "application/x-ndjson" } });
}

// Stream que la prueba alimenta línea por línea.
export function streamControlado() {
  let control!: ReadableStreamDefaultController<Uint8Array>;
  const estado = { cancelado: false };
  const cuerpo = new ReadableStream<Uint8Array>({
    start(c) {
      control = c;
    },
    cancel() {
      estado.cancelado = true;
    },
  });
  return {
    respuesta: () => new Response(cuerpo, { status: 200, headers: { "Content-Type": "application/x-ndjson" } }),
    enviar: (...lineas: (string | object)[]) =>
      lineas.forEach((l) => control.enqueue(codificador.encode((typeof l === "string" ? l : JSON.stringify(l)) + "\n"))),
    cerrar: () => control.close(),
    get cancelado() {
      return estado.cancelado;
    },
  };
}

// ---------------------------------------------------------------------------
// Datos ficticios (no corresponden a ninguna persona)
// ---------------------------------------------------------------------------
export const USUARIO = {
  id_usuario: "u-0001",
  nombre_usuario: "enf.prueba",
  nombre_completo: "Lic. Usuaria Prueba",
  rol: "Enfermera CRED",
  permisos: ["REGISTRAR_PACIENTE", "REALIZAR_CONSULTA", "EXPORTAR_REPORTE"],
};

export const FICHA: Ficha = {
  id_paciente: ID_PACIENTE,
  nombres_apellidos: "Paciente Ficticio Uno",
  dni: "00000001",
  numero_hc: "HC-PRUEBA-1",
  direccion: null,
  fecha_nacimiento: "2025-07-10",
  edad_meses_actual: 16,
  sexo: "M",
  ubigeo_residencia: "150101",
  distrito: "Lima",
  provincia: "Lima",
  departamento: "Lima",
  altitud_msnm: 150,
  edad_gestacional_nacer: "A_TERMINO",
  bajo_peso_nacer: false,
  registrado_por: "Lic. Usuaria Prueba",
  fecha_registro: "2026-05-12T09:00:00-05:00",
};

function tamizaje(cambios: Partial<TamizajeHistorial>): TamizajeHistorial {
  return {
    id_tamizaje: "t-0001",
    fecha_tamizaje: "2026-11-01",
    fecha_registro: "2026-11-01T10:00:00-05:00",
    edad_meses: 15,
    hemoglobina_g_dl: "9.8",
    metodo_medicion: "HEMOGLOBINOMETRO",
    peso_kg: "10.2",
    talla_cm: "78.0",
    recibe_suplementacion_hierro: false,
    lactancia_materna_actual: true,
    parasitosis_reciente: false,
    observaciones: null,
    profesional: "Lic. Usuaria Prueba",
    sintomas: [{ id_sintoma: 1, nombre: "Palidez", detalle: null }],
    vigente: true,
    clasificacion: {
      categoria: "ANEMIA_LEVE",
      nivel_riesgo: "MODERADO",
      requiere_derivacion: false,
      altitud_msnm: 150,
      ajuste_hb_g_dl: "0.0",
      hb_ajustada_g_dl: "9.8",
    },
    motivo_sin_clasificacion: null,
    ...cambios,
  };
}

export const HISTORIAL: Historial = {
  id_paciente: ID_PACIENTE,
  tamizajes: [
    tamizaje({}),
    tamizaje({ id_tamizaje: "t-0000", fecha_tamizaje: "2026-05-12", hemoglobina_g_dl: "10.1", vigente: false, sintomas: [] }),
  ],
  franjas: [],
  consultas: [],
};

// Ficha e historial del paciente de los fixtures, para M05.
export const FICHA_FIXTURE: Ficha = { ...FICHA, id_paciente: ID_PACIENTE_FIXTURE, nombres_apellidos: "Paciente Ficticio Dos", numero_hc: "HC-PRUEBA-2" };
export const HISTORIAL_FIXTURE: Historial = {
  id_paciente: ID_PACIENTE_FIXTURE,
  tamizajes: [tamizaje({ id_tamizaje: ID_TAMIZAJE_FIXTURE, hemoglobina_g_dl: "11.4" })],
  franjas: [],
  consultas: [],
};

// ---------------------------------------------------------------------------
// fetch falso
// ---------------------------------------------------------------------------
type Manejador = (init: RequestInit | undefined, url: URL) => Response | Promise<Response>;

// Rutas base de M04 (sesión, ficha, historial y consultas previas); las pruebas agregan o
// reemplazan las demás con la clave «MÉTODO /ruta». Si no hay una clave con la cadena de consulta
// exacta, se usa la de la ruta sin ella (por ejemplo «GET /api/consultas» para cualquier filtro), y el
// manejador recibe la URL para leer los parámetros.
export function simularBackend(rutas: Record<string, Manejador> = {}) {
  const base: Record<string, Manejador> = {
    "GET /api/auth/me": () => respuestaJson(200, USUARIO),
    [`GET /api/pacientes/${ID_PACIENTE}`]: () => respuestaJson(200, FICHA),
    [`GET /api/pacientes/${ID_PACIENTE}/historial`]: () => respuestaJson(200, HISTORIAL),
    [`GET /api/pacientes/${ID_PACIENTE}/consultas`]: () => respuestaJson(200, []),
    [`GET /api/pacientes/${ID_PACIENTE_FIXTURE}`]: () => respuestaJson(200, FICHA_FIXTURE),
    [`GET /api/pacientes/${ID_PACIENTE_FIXTURE}/historial`]: () => respuestaJson(200, HISTORIAL_FIXTURE),
  };
  const todas = { ...base, ...rutas };
  const fetchFalso = vi.fn(async (ruta: RequestInfo | URL, init?: RequestInit) => {
    const metodo = init?.method ?? "GET";
    const clave = `${metodo} ${String(ruta)}`;
    const url = new URL(String(ruta), "http://localhost");
    const manejador = todas[clave] ?? todas[`${metodo} ${url.pathname}`];
    if (!manejador) return respuestaJson(404, { detail: `Ruta no simulada: ${clave}` });
    return manejador(init, url);
  });
  vi.stubGlobal("fetch", fetchFalso);
  return fetchFalso;
}

export const POST_CONSULTA = `POST /api/pacientes/${ID_PACIENTE}/consultas`;
export const GET_RESULTADO = `GET /api/consultas/${ID_CONSULTA}`;

// Stream de una consulta reanudada (M06 o M15): las líneas del fixture con el id de la consulta
// nueva y, en el evento fin, la consulta previa.
export const ID_CONSULTA_REANUDADA = "00000000-0000-4000-8000-000000000009";
export function lineasReanudadas(estado: EstadoFinal, idNueva = ID_CONSULTA_REANUDADA, idPrevia = ID_CONSULTA): string[] {
  return lineasFixture(estado).map((linea) => {
    const evento = JSON.parse(linea);
    if ("id_consulta" in evento) evento.id_consulta = idNueva;
    if (evento.tipo === "fin") evento.id_consulta_previa = idPrevia;
    return JSON.stringify(evento);
  });
}

export function resultadoReanudado(estado: EstadoFinal, idNueva = ID_CONSULTA_REANUDADA, idPrevia = ID_CONSULTA): ResultadoConsulta {
  return { ...resultadoFixture(estado), id_consulta: idNueva, id_consulta_previa: idPrevia };
}

// ---------------------------------------------------------------------------
// Reporte exportable (M09, parte C2): fixtures de la parte C1 (generados por el backend)
// ---------------------------------------------------------------------------
export const RUTA_REPORTES = `/api/consultas/${ID_CONSULTA}/reportes`;
export const GET_VISTA_PREVIA = `GET ${RUTA_REPORTES}/vista-previa`;
export const GET_REPORTES = `GET ${RUTA_REPORTES}`;
export const POST_REPORTE = `POST ${RUTA_REPORTES}`;

export function vistaPreviaFixture(destino: DestinoReporte): VistaPreviaReporte {
  return structuredClone((destino === "EXPEDIENTE" ? vistaExpediente : vistaCuidador) as VistaPreviaReporte);
}

export function reportesFixture(): ReporteListado[] {
  return structuredClone(listaReportes as ReporteListado[]);
}

// Respuesta del POST: el PDF (bytes ficticios) con el número y la huella en las cabeceras.
export function respuestaPdf(numero: string, hash = "b".repeat(64)): Response {
  return new Response(new Uint8Array([37, 80, 68, 70, 45]), {
    status: 201,
    headers: { "Content-Type": "application/pdf", "X-Reporte-Numero": numero, "X-Reporte-Hash": hash,
               "Content-Disposition": `attachment; filename="${numero}.pdf"`, "Cache-Control": "no-store" },
  });
}
