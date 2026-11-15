// M05: resumen, pasos numerados con su tipo y sus citas, y advertencias de la recomendación.
import type { Cita, Recomendacion } from "../../api/tipos_consulta";
import { TIPOS_PASO } from "../../utilidades/formato";
import EnlaceCita from "./EnlaceCita";

type Props = { recomendacion: Recomendacion; citas: Cita[]; irACita: (etiqueta: string) => void };

export default function RecomendacionClinica({ recomendacion: r, citas, irACita }: Props) {
  const porEtiqueta = new Map(citas.map((c) => [c.etiqueta, c]));
  return (
    <>
      <p className="recomendacion__resumen">{r.resumen}</p>
      <ol className="recomendacion__pasos">
        {r.recomendacion.map((paso, i) => (
          <li key={i} className="recomendacion__paso">
            <span className={`etiqueta etiqueta--paso etiqueta--paso-${paso.tipo}`}>{TIPOS_PASO[paso.tipo] ?? paso.tipo}</span>{" "}
            <span>{paso.texto}</span>
            {paso.citas.length > 0 && (
              <span className="recomendacion__citas">
                {paso.citas.map((etiqueta) => (
                  <EnlaceCita key={etiqueta} etiqueta={etiqueta} cita={porEtiqueta.get(etiqueta)} irACita={irACita} />
                ))}
              </span>
            )}
          </li>
        ))}
      </ol>
      {r.advertencias.length > 0 && (
        <div className="recomendacion__advertencias">
          <h3>Advertencias</h3>
          <ul>
            {r.advertencias.map((a, i) => <li key={i}>{a}</li>)}
          </ul>
        </div>
      )}
    </>
  );
}
