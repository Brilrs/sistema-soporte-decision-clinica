// Ruta de navegación («Pacientes › Registro»).
import { Fragment } from "react";
import { Link } from "react-router-dom";

export type Miga = { texto: string; ruta?: string };

export default function Migas({ items }: { items: Miga[] }) {
  return (
    <nav className="migas" aria-label="Ruta de navegación">
      {items.map((m, i) => (
        <Fragment key={i}>
          {i > 0 && " › "}
          {m.ruta ? <Link to={m.ruta}>{m.texto}</Link> : <span>{m.texto}</span>}
        </Fragment>
      ))}
    </nav>
  );
}
