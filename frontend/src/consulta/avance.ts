// Avance de una consulta por etapas (M04). Los 8 nodos del grafo se muestran como las 6 etapas
// del mockup: normalizar y recuperar forman «Buscando evidencia» y salida no se muestra (solo
// registra el resultado). Funciones puras: se prueban sin pantalla.
import type { EventoConsulta, EventoEnCola, Nodo } from "../api/tipos_consulta";

export type Etapa = { clave: string; texto: string; nodos: Nodo[] };

export const ETAPAS: Etapa[] = [
  { clave: "validar", texto: "Validando datos y vigencia del tamizaje", nodos: ["validar"] },
  { clave: "clasificar", texto: "Calculando clasificación (NTS 213-MINSA / OMS 2024)", nodos: ["clasificar"] },
  { clave: "buscar", texto: "Buscando evidencia en guías clínicas", nodos: ["normalizar", "recuperar"] },
  { clave: "proteger", texto: "Protegiendo datos del paciente", nodos: ["proteger"] },
  { clave: "generar", texto: "Generando recomendación", nodos: ["generar"] },
  { clave: "verificar", texto: "Verificando citas y consistencia", nodos: ["verificar"] },
];

export type EstadoEtapa = "pendiente" | "en_curso" | "lista";

export type Avance = {
  hechos: Nodo[]; // nodos terminados en el intento actual
  intento: number;
  ampliada: boolean; // el segundo intento usa la búsqueda ampliada
  enCola: EventoEnCola | null;
  terminado: boolean;
};

export const AVANCE_INICIAL: Avance = { hechos: [], intento: 1, ampliada: false, enCola: null, terminado: false };

// Al reintentar, verificar indica desde dónde se repite: AMPLIADA vuelve a recuperar (con otros
// términos) y REGENERAR vuelve a proteger y generar.
const SE_REPITEN: Record<string, Nodo[]> = {
  AMPLIADA: ["recuperar", "proteger", "generar", "verificar"],
  REGENERAR: ["proteger", "generar", "verificar"],
};

export function avanzar(a: Avance, e: EventoConsulta): Avance {
  switch (e.tipo) {
    case "en_cola":
      return { ...a, enCola: e };
    case "fin":
    case "error":
      return { ...a, enCola: null, terminado: true };
    case "etapa": {
      if (e.etapa === "salida") return { ...a, enCola: null };
      const repetir = e.etapa === "verificar" && e.siguiente ? SE_REPITEN[e.siguiente] : undefined;
      if (repetir) {
        return {
          ...a,
          hechos: a.hechos.filter((n) => !repetir.includes(n)),
          intento: a.intento + 1,
          ampliada: a.ampliada || e.siguiente === "AMPLIADA",
          enCola: null,
        };
      }
      const hechos = a.hechos.includes(e.etapa) ? a.hechos : [...a.hechos, e.etapa];
      return { ...a, hechos, enCola: null };
    }
    default:
      return a;
  }
}

// Una etapa está lista cuando terminaron todos sus nodos; la primera que no lo está queda en
// curso mientras la consulta siga activa.
export function estadosEtapas(a: Avance, activa: boolean): EstadoEtapa[] {
  const listas = ETAPAS.map((et) => et.nodos.every((n) => a.hechos.includes(n)));
  const enCurso = activa && !a.terminado ? listas.indexOf(false) : -1;
  return listas.map((lista, i) => (lista ? "lista" : i === enCurso ? "en_curso" : "pendiente"));
}

export const RECURSOS: Record<EventoEnCola["recurso"], string> = {
  modelos: "el servicio de búsqueda de evidencia",
  llm: "el servicio de generación",
};
