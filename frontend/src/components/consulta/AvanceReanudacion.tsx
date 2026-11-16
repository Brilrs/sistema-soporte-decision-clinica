// Avance por etapas dentro de M06 y M15, con los errores de la reanudación (409, 422, corte del
// stream sin resultado) y, si el resultado no se pudo recuperar a tiempo, «Ver resultado».
import { useNavigate } from "react-router-dom";
import type { EstadoConsultaEnCurso } from "../../consulta/useConsulta";
import { MENSAJE_ERROR } from "../../consulta/textos";
import AvanceConsulta from "../AvanceConsulta";

const MENSAJE_CANCELADA =
  "Se dejó de esperar. La consulta puede terminar igual en el servidor; la encontrará en las consultas previas del paciente.";

type Props = { estado: EstadoConsultaEnCurso; enCurso: boolean; sinResultado: boolean; cancelar: () => void };

export default function AvanceReanudacion({ estado, enCurso, sinResultado, cancelar }: Props) {
  const navegar = useNavigate();
  if (estado.fase === "inactiva") return null;
  return (
    <div className="modal__avance">
      <AvanceConsulta avance={estado.avance} activa={enCurso} recuperando={estado.fase === "recuperando"}
                      inicio={estado.inicio} finMs={estado.finMs} cancelar={cancelar}
                      detenida={estado.fase === "terminada"} />
      {estado.fase === "terminada" && !enCurso && !sinResultado && (
        <p className="texto-tenue" role="status">Abriendo el resultado…</p>
      )}
      {sinResultado && <p className="alerta alerta--error" role="alert">{MENSAJE_ERROR}</p>}
      {estado.fase === "cancelada" && <p className="alerta alerta--aviso" role="status">{MENSAJE_CANCELADA}</p>}
      {estado.fase === "error" && (
        <div className="alerta alerta--error" role="alert">
          <p className="alerta__texto">{estado.error}</p>
          {estado.puedeVerResultado && estado.idConsulta && (
            <button type="button" className="boton boton--secundario boton--chico"
                    onClick={() => navegar(`/consultas/${estado.idConsulta}`)}>Ver resultado</button>
          )}
        </div>
      )}
    </div>
  );
}
