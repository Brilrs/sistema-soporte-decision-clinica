// Mensaje de un estado final que no es una respuesta verificada (M04 y M05): título, texto del
// backend y, en FUERA_DE_DOMINIO, la sugerencia de reformular mencionando el tema.
import type { EstadoFinal } from "../api/tipos_consulta";
import { ESTADOS_GRAVES, MENSAJES_POR_DEFECTO, SUGERENCIA_FUERA_DE_DOMINIO, TITULOS_ESTADO } from "../consulta/textos";

export default function MensajeDesenlace({ estado, mensaje }: { estado: EstadoFinal; mensaje: string | null }) {
  const grave = ESTADOS_GRAVES.includes(estado);
  return (
    <div className={`desenlace ${grave ? "desenlace--error" : "desenlace--aviso"}`} role="alert">
      <strong>{TITULOS_ESTADO[estado]}</strong>
      <p>{mensaje || MENSAJES_POR_DEFECTO[estado]}</p>
      {estado === "FUERA_DE_DOMINIO" && <p className="desenlace__sugerencia">{SUGERENCIA_FUERA_DE_DOMINIO}</p>}
    </div>
  );
}
