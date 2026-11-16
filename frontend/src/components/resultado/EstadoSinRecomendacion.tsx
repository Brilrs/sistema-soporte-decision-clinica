// Resumen de una consulta que terminó sin recomendación (M04, M05 y M07): estado a ancho completo,
// acciones para seguir, la decisión clínica si el estado la admite y, debajo, la clasificación
// calculada por reglas a partir del tamizaje y lo que la respuesta haya traído (verificación o
// citas). Una sola columna en todas las anchuras, para que las tarjetas no queden desalineadas.
import type { ReactNode } from "react";
import type { ClasificacionConsulta, EstadoFinal } from "../../api/tipos_consulta";
import { AVISO_DECISION, ROTULO_CLASIFICACION } from "../../consulta/textos";
import MensajeDesenlace from "../MensajeDesenlace";
import RiesgoClasificacion from "./RiesgoClasificacion";

type Props = {
  estado: EstadoFinal;
  mensaje: string | null;
  clasificacion: ClasificacionConsulta | null;
  hbObservada: string | number | null;
  nivel?: 2 | 3; // h2 en M05; h3 dentro de la tarjeta de consulta de M04
  acciones?: ReactNode;
  decision?: ReactNode; // «Registrar decisión clínica» o la decisión registrada
  complementos?: ReactNode; // tarjetas después de la clasificación (verificación, citas)
  children?: ReactNode; // detalle propio del estado (por ejemplo, los datos faltantes)
};

export default function EstadoSinRecomendacion({ estado, mensaje, clasificacion, hbObservada, nivel = 2, acciones,
                                                 decision, complementos, children }: Props) {
  const H = nivel === 3 ? "h3" : "h2";
  return (
    <div className="estado-consulta">
      <section className="tarjeta estado-consulta__estado" aria-labelledby="titulo-estado">
        <H id="titulo-estado">Estado de la consulta</H>
        <MensajeDesenlace estado={estado} mensaje={mensaje} />
        {children}
        {acciones && <div className="acciones acciones--izquierda">{acciones}</div>}
        {decision && <div className="estado-consulta__decision">{decision}</div>}
        <p className="resultado__aviso-decision" role="note">{AVISO_DECISION}</p>
      </section>
      {clasificacion && (
        <RiesgoClasificacion clasificacion={clasificacion} hbObservada={hbObservada} nivel={nivel}
                             titulo="Clasificación del paciente" rotulo={ROTULO_CLASIFICACION} />
      )}
      {complementos}
    </div>
  );
}
