// Mensaje de un estado final que no es una respuesta verificada (M04 y M05): título, texto y,
// según el estado, la sugerencia para reformular. ERROR y SOLICITUD_BLOQUEADA usan textos propios
// (consulta/textos.ts); los demás, el mensaje del backend. Si el mensaje dice lo mismo que el
// título, se muestra solo el título.
import type { EstadoFinal } from "../api/tipos_consulta";
import {
  COMO_REFORMULAR_BLOQUEADA,
  ESTADOS_GRAVES,
  MENSAJES_POR_DEFECTO,
  MENSAJES_PROPIOS,
  SUGERENCIA_FUERA_DE_DOMINIO,
  TITULOS_ESTADO,
} from "../consulta/textos";

const normalizar = (t: string) => t.trim().replace(/[.:;!¡?¿\s]+$/u, "").toLocaleLowerCase("es-PE");

export function textoDesenlace(estado: EstadoFinal, mensaje: string | null): string | null {
  const texto = MENSAJES_PROPIOS[estado] ?? (mensaje?.trim() || MENSAJES_POR_DEFECTO[estado]);
  return normalizar(texto) === normalizar(TITULOS_ESTADO[estado]) ? null : texto;
}

export default function MensajeDesenlace({ estado, mensaje }: { estado: EstadoFinal; mensaje: string | null }) {
  const grave = ESTADOS_GRAVES.includes(estado);
  const texto = textoDesenlace(estado, mensaje);
  return (
    <div className={`desenlace ${grave ? "desenlace--error" : "desenlace--aviso"}`} role="alert">
      <strong>{TITULOS_ESTADO[estado]}</strong>
      {texto && <p>{texto}</p>}
      {estado === "FUERA_DE_DOMINIO" && <p className="desenlace__sugerencia">{SUGERENCIA_FUERA_DE_DOMINIO}</p>}
      {estado === "SOLICITUD_BLOQUEADA" && (
        <p className="desenlace__sugerencia"><strong>Cómo reformular: </strong>{COMO_REFORMULAR_BLOQUEADA}</p>
      )}
    </div>
  );
}
