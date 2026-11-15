// Etiqueta F-xx de la recomendación: enlace a su fila en la tabla de evidencias citadas.
import type { MouseEvent } from "react";
import type { Cita } from "../../api/tipos_consulta";

export const idCita = (etiqueta: string) => `cita-${etiqueta}`;

type Props = { etiqueta: string; cita: Cita | undefined; irACita: (etiqueta: string) => void };

export default function EnlaceCita({ etiqueta, cita, irACita }: Props) {
  if (!cita) {
    return <span className="cita-enlace cita-enlace--sin-fuente" title="Cita sin fragmento en la tabla">{etiqueta}</span>;
  }
  function alPulsar(e: MouseEvent<HTMLAnchorElement>) {
    e.preventDefault();
    irACita(etiqueta);
  }
  return (
    <a className="cita-enlace" href={`#${idCita(etiqueta)}`} onClick={alPulsar}
       aria-label={`Ver cita ${etiqueta}: ${cita.documento}`}>
      {etiqueta}
    </a>
  );
}
