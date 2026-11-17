// Estado de una consulta en curso (M04, M06 y M15): lee el NDJSON, sigue el avance, recupera el
// resultado tras un corte y cancela al desmontar la pantalla. La misma lógica sirve para la
// consulta nueva, la reanudación con datos faltantes y la continuación con un tamizaje vencido.
import { useCallback, useEffect, useReducer, useRef } from "react";
import { ErrorApi, mensajeError } from "../api/cliente";
import { consultasApi, ErrorConsulta, recuperarResultado } from "../api/consultas";
import type {
  ClasificacionConsulta,
  ConsultaEntrada,
  DatosFaltantesEntrada,
  EstadoFinal,
  EventoConsulta,
  EventoFin,
  EventoFinal,
  OpcionDecision,
  ResultadoConsulta,
  Vigencia,
} from "../api/tipos_consulta";
import { AVANCE_INICIAL, avanzar, type Avance } from "./avance";

export type Fase =
  | "inactiva"
  | "en_curso" // stream abierto
  | "recuperando" // el stream se cortó: se consulta el resultado guardado
  | "terminada" // llegó el estado final (por el stream o por la recuperación)
  | "cancelada"
  | "error"; // error antes del stream, o el resultado no se pudo recuperar

// Lo que M04 necesita del estado final, venga del evento fin, del evento error o del GET.
export type Desenlace = {
  estado: EstadoFinal;
  id_consulta: string | null;
  mensaje: string | null;
  modo_prueba: boolean;
  // Evento fin completo, si llegó por el stream (M05 lo muestra sin esperar el GET).
  fin: EventoFin | null;
  // Para M06, M15 y el resumen de los estados sin recomendación.
  datos_faltantes: string[]; // etiquetas pendientes (por ejemplo «hemoglobina»)
  vigencia: Vigencia | null;
  clasificacion: ClasificacionConsulta | null;
  // Tipos de decisión que admite (ERROR desde M04 abre la decisión en M05).
  opciones_decision: OpcionDecision[];
};

export type EstadoConsultaEnCurso = {
  fase: Fase;
  avance: Avance;
  idConsulta: string | null;
  desenlace: Desenlace | null;
  error: string | null;
  // El resultado no se pudo recuperar a tiempo: M04 ofrece «Ver resultado».
  puedeVerResultado: boolean;
  inicio: number | null; // Date.now() al enviar
  finMs: number | null; // duración total, al terminar
};

const INICIAL: EstadoConsultaEnCurso = {
  fase: "inactiva",
  avance: AVANCE_INICIAL,
  idConsulta: null,
  desenlace: null,
  error: null,
  puedeVerResultado: false,
  inicio: null,
  finMs: null,
};

type Accion =
  | { tipo: "iniciar"; ahora: number }
  | { tipo: "evento"; evento: EventoConsulta }
  | { tipo: "terminar"; desenlace: Desenlace; ahora: number }
  | { tipo: "recuperar"; idConsulta: string }
  | { tipo: "fallar"; error: string; puedeVerResultado?: boolean; ahora: number }
  | { tipo: "cancelar"; ahora: number };

function reductor(s: EstadoConsultaEnCurso, a: Accion): EstadoConsultaEnCurso {
  const cerrar = (ahora: number) => (s.inicio === null ? null : ahora - s.inicio);
  switch (a.tipo) {
    case "iniciar":
      return { ...INICIAL, fase: "en_curso", inicio: a.ahora };
    case "evento": {
      const id = "id_consulta" in a.evento && a.evento.id_consulta ? a.evento.id_consulta : null;
      return { ...s, avance: avanzar(s.avance, a.evento), idConsulta: s.idConsulta ?? id };
    }
    case "terminar":
      return { ...s, fase: "terminada", desenlace: a.desenlace, finMs: cerrar(a.ahora), avance: { ...s.avance, enCola: null, terminado: true } };
    case "recuperar":
      return { ...s, fase: "recuperando", idConsulta: a.idConsulta, avance: { ...s.avance, enCola: null } };
    case "fallar":
      return {
        ...s,
        fase: "error",
        error: a.error,
        puedeVerResultado: !!a.puedeVerResultado,
        finMs: cerrar(a.ahora),
        avance: { ...s.avance, enCola: null, terminado: true },
      };
    case "cancelar":
      return { ...s, fase: "cancelada", finMs: cerrar(a.ahora), avance: { ...s.avance, enCola: null, terminado: true } };
  }
}

function desdeEvento(e: EventoFinal): Desenlace {
  const fin = e.tipo === "fin" ? e : null;
  return { estado: e.estado, id_consulta: e.id_consulta, mensaje: e.mensaje, modo_prueba: !!fin?.modo_prueba, fin,
           datos_faltantes: fin?.datos_faltantes ?? [], vigencia: fin?.vigencia ?? null, clasificacion: fin?.clasificacion ?? null,
           opciones_decision: e.opciones_decision ?? [] };
}

function desdeResultado(r: ResultadoConsulta): Desenlace {
  return { estado: r.estado as EstadoFinal, id_consulta: r.id_consulta, mensaje: r.mensaje, modo_prueba: r.modo_prueba, fin: null,
           datos_faltantes: r.datos_faltantes.filter((d) => !d.completado).map((d) => d.etiqueta),
           vigencia: r.vigencia, clasificacion: r.clasificacion, opciones_decision: r.opciones_decision ?? [] };
}

type AbrirStream = (senal: AbortSignal) => AsyncGenerator<EventoConsulta, EventoFinal, void>;

export const MENSAJE_SIN_ID =
  "Se interrumpió la conexión antes de que la consulta quedara registrada. Revise su conexión y envíe la consulta de nuevo.";

export function useConsulta(idPaciente: string) {
  const [estado, despachar] = useReducer(reductor, INICIAL);
  const control = useRef<AbortController | null>(null);

  // Al salir de la pantalla (o cambiar de paciente) se deja de esperar: la consulta puede
  // terminar igual en el servidor.
  useEffect(
    () => () => {
      control.current?.abort();
      control.current = null;
    },
    [idPaciente],
  );

  const ejecutar = useCallback(
    async (abrir: AbrirStream) => {
      control.current?.abort();
      const c = new AbortController();
      control.current = c;
      const vigente = () => control.current === c && !c.signal.aborted;
      despachar({ tipo: "iniciar", ahora: Date.now() });

      let idConsulta: string | null = null;
      try {
        let final: EventoFinal | null = null;
        for await (const evento of abrir(c.signal)) {
          if (!vigente()) return;
          if ("id_consulta" in evento && evento.id_consulta) idConsulta ??= evento.id_consulta;
          despachar({ tipo: "evento", evento });
          if (evento.tipo === "fin" || evento.tipo === "error") final = evento;
        }
        if (final && vigente()) despachar({ tipo: "terminar", desenlace: desdeEvento(final), ahora: Date.now() });
      } catch (err) {
        if (c.signal.aborted || (err instanceof ErrorConsulta && err.codigo === "cancelada")) {
          if (control.current === c) despachar({ tipo: "cancelar", ahora: Date.now() });
          return;
        }
        if (!vigente()) return;
        if (!(err instanceof ErrorConsulta)) {
          // Antes del stream: 401 (AuthContext cierra la sesión), 403, 404, 409 o 422 con el
          // mensaje del backend, o un fallo de red.
          despachar({ tipo: "fallar", error: mensajeError(err), ahora: Date.now() });
          return;
        }
        const id = err.id_consulta ?? idConsulta;
        if (!id) {
          despachar({ tipo: "fallar", error: MENSAJE_SIN_ID, ahora: Date.now() });
          return;
        }
        despachar({ tipo: "recuperar", idConsulta: id });
        try {
          const r = await recuperarResultado(id, { senal: c.signal });
          if (vigente()) despachar({ tipo: "terminar", desenlace: desdeResultado(r), ahora: Date.now() });
        } catch (e2) {
          if (c.signal.aborted) {
            if (control.current === c) despachar({ tipo: "cancelar", ahora: Date.now() });
            return;
          }
          if (!vigente()) return;
          const mensaje =
            e2 instanceof ErrorConsulta || e2 instanceof ErrorApi
              ? e2.message
              : "No se pudo obtener el resultado de la consulta.";
          despachar({ tipo: "fallar", error: mensaje, puedeVerResultado: true, ahora: Date.now() });
        }
      }
    },
    [],
  );

  // POST /api/pacientes/{id}/consultas: consulta nueva.
  const enviar = useCallback(
    (entrada: ConsultaEntrada) => ejecutar((senal) => consultasApi.consultar(idPaciente, entrada, { senal })),
    [ejecutar, idPaciente],
  );

  // POST /api/consultas/{id}/datos-faltantes: completa la hemoglobina y reanuda (M06).
  const completarDatos = useCallback(
    (idConsulta: string, datos: DatosFaltantesEntrada) =>
      ejecutar((senal) => consultasApi.completarDatosFaltantes(idConsulta, datos, { senal })),
    [ejecutar],
  );

  // POST /api/consultas/{id}/continuar: continúa con el tamizaje vencido y la pregunta guardada (M15).
  const continuarTamizajeNoVigente = useCallback(
    (idConsulta: string) => ejecutar((senal) => consultasApi.continuarTamizajeNoVigente(idConsulta, { senal })),
    [ejecutar],
  );

  const cancelar = useCallback(() => control.current?.abort(), []);

  return { estado, enviar, completarDatos, continuarTamizajeNoVigente, cancelar };
}
