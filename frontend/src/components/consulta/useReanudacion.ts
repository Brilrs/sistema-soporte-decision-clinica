// Reanudación de una consulta desde M06 (datos faltantes) o M15 (tamizaje no vigente): usa el
// mismo lector NDJSON y el mismo avance que M04 y, al recibir el estado final de la consulta
// nueva, abre su resultado en M05 con el evento fin.
import { useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useConsulta } from "../../consulta/useConsulta";

export function useReanudacion(idPaciente: string) {
  const navegar = useNavigate();
  const consulta = useConsulta(idPaciente);
  const { fase, desenlace } = consulta.estado;

  useEffect(() => {
    if (fase === "terminada" && desenlace?.id_consulta) {
      navegar(`/consultas/${desenlace.id_consulta}`, { state: { fin: desenlace.fin } });
    }
  }, [fase, desenlace, navegar]);

  const enCurso = fase === "en_curso" || fase === "recuperando";
  // Sin id (falló antes de registrarse) no hay resultado que abrir: se informa en la ventana.
  const sinResultado = fase === "terminada" && !desenlace?.id_consulta;
  return { ...consulta, enCurso, sinResultado };
}
