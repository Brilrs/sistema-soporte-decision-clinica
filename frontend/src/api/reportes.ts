// Reporte exportable (M09, HU10; Sprint 3, parte C2): llamadas a las rutas de la parte C1.
// Contrato: docs/contrato_reportes.md. Tipos: ./tipos_reporte.ts.
// El PDF llega como blob y queda solo en la memoria de la página: no se guarda en localStorage,
// sessionStorage ni en la caché del navegador (el backend responde con Cache-Control: no-store).
import { api, cabecerasCon, errorDeRespuesta, revisarSesion } from "./cliente";
import {
  CABECERA_HASH,
  CABECERA_NUMERO,
  type DestinoReporte,
  type ReporteListado,
  type SeccionReporte,
  type VistaPreviaReporte,
} from "./tipos_reporte";

export type ReporteGenerado = { numero: string; hash: string; pdf: Blob };

const base = (idConsulta: string) => `/api/consultas/${idConsulta}/reportes`;

// Secciones en una sola cadena separada por comas, en el orden recibido (el backend las ordena).
export function parametrosVistaPrevia(destino: DestinoReporte, secciones: SeccionReporte[]): string {
  const p = new URLSearchParams({ destino });
  if (secciones.length) p.set("secciones", secciones.join(","));
  return `?${p.toString()}`;
}

export const reportesApi = {
  // GET .../reportes/vista-previa: el contenido del PDF, sin número ni registro.
  vistaPrevia: (idConsulta: string, destino: DestinoReporte, secciones: SeccionReporte[], senal?: AbortSignal) =>
    api<VistaPreviaReporte>(`${base(idConsulta)}/vista-previa${parametrosVistaPrevia(destino, secciones)}`, {
      signal: senal,
      cache: "no-store",
    }),
  // GET .../reportes: los emitidos, del más reciente al más antiguo, sin el PDF.
  listar: (idConsulta: string, senal?: AbortSignal) => api<ReporteListado[]>(base(idConsulta), { signal: senal }),
  // POST .../reportes: cada llamada emite un reporte nuevo con su número.
  generar: async (idConsulta: string, destino: DestinoReporte, secciones: SeccionReporte[]): Promise<ReporteGenerado> => {
    const opciones: RequestInit = { method: "POST", body: JSON.stringify({ destino, secciones, formato: "PDF" }), cache: "no-store" };
    const cabeceras = cabecerasCon(opciones);
    const respuesta = await fetch(base(idConsulta), { ...opciones, headers: cabeceras });
    revisarSesion(respuesta, cabeceras);
    if (!respuesta.ok) throw await errorDeRespuesta(respuesta);
    return {
      numero: respuesta.headers.get(CABECERA_NUMERO) ?? "",
      hash: respuesta.headers.get(CABECERA_HASH) ?? "",
      pdf: await respuesta.blob(),
    };
  },
};
