// Ventana modal accesible (M06 y M15): role="dialog" con aria-modal, título y descripción
// asociados, foco en el primer control al abrir (o en el que se indique), foco atrapado con Tab
// y Mayús + Tab, Esc para cerrar y, al cerrar, foco de vuelta al control que la abrió.
// Mientras «cerrable» es falso (por ejemplo, con la consulta en curso) Esc no la cierra.
import { useEffect, useRef, type KeyboardEvent, type ReactNode, type RefObject } from "react";

const ENFOCABLES =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

type Props = {
  id: string; // prefijo de los ids del título y la descripción
  titulo: string;
  descripcion?: ReactNode;
  alCerrar: () => void;
  cerrable?: boolean;
  focoInicial?: RefObject<HTMLElement | null>;
  // Control que recibe el foco al cerrar; por defecto, el que tenía el foco al abrir.
  focoAlCerrar?: RefObject<HTMLElement | null>;
  icono?: string; // marca decorativa de la cabecera («!» en M06 y M15)
  amplia?: boolean; // ventana más ancha (detalle de una guía en M11, con tablas)
  children: ReactNode;
};

export default function Modal({ id, titulo, descripcion, alCerrar, cerrable = true, focoInicial, focoAlCerrar, icono = "!", amplia = false, children }: Props) {
  const ventana = useRef<HTMLDivElement>(null);
  const cerrarRef = useRef(alCerrar);
  cerrarRef.current = alCerrar;

  useEffect(() => {
    const anterior = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const primero = focoInicial?.current ?? ventana.current?.querySelector<HTMLElement>(ENFOCABLES) ?? ventana.current;
    primero?.focus();
    const desborde = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = desborde;
      const destino = focoAlCerrar?.current ?? anterior;
      if (destino?.isConnected) destino.focus();
    };
    // Solo al abrir y al cerrar.
  }, []);

  function tecla(e: KeyboardEvent<HTMLDivElement>) {
    if (e.key === "Escape") {
      e.stopPropagation();
      if (cerrable) cerrarRef.current();
      return;
    }
    if (e.key !== "Tab" || !ventana.current) return;
    const enfocables = [...ventana.current.querySelectorAll<HTMLElement>(ENFOCABLES)];
    if (enfocables.length === 0) {
      e.preventDefault();
      ventana.current.focus();
      return;
    }
    const primero = enfocables[0];
    const ultimo = enfocables[enfocables.length - 1];
    const activo = document.activeElement;
    if (e.shiftKey && (activo === primero || activo === ventana.current)) {
      e.preventDefault();
      ultimo.focus();
    } else if (!e.shiftKey && activo === ultimo) {
      e.preventDefault();
      primero.focus();
    }
  }

  return (
    <div className="modal__fondo">
      <div ref={ventana} className={amplia ? "modal modal--amplia" : "modal"} role="dialog" aria-modal="true" tabIndex={-1}
           aria-labelledby={`${id}-titulo`} aria-describedby={descripcion ? `${id}-descripcion` : undefined}
           onKeyDown={tecla}>
        <div className="modal__cabecera">
          <span className="modal__icono" aria-hidden="true">{icono}</span>
          <div>
            <h2 id={`${id}-titulo`} className="modal__titulo">{titulo}</h2>
            {descripcion && <div id={`${id}-descripcion`} className="modal__descripcion">{descripcion}</div>}
          </div>
        </div>
        {children}
      </div>
    </div>
  );
}
