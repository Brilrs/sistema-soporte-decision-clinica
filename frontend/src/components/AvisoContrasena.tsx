// Muestra una sola vez la contraseña generada por el sistema. Vive solo en el estado de
// React de la pantalla: no se guarda en el navegador y desaparece al cerrar el aviso.
import { useEffect, useRef, useState } from "react";

export default function AvisoContrasena({ titulo, nombreUsuario, contrasena, cerrar }: {
  titulo: string;
  nombreUsuario: string;
  contrasena: string;
  cerrar: () => void;
}) {
  const [copiada, setCopiada] = useState<boolean | null>(null);
  const campo = useRef<HTMLInputElement>(null);
  const botonCerrar = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    botonCerrar.current?.focus();
    const alPulsar = (e: KeyboardEvent) => e.key === "Escape" && cerrar();
    window.addEventListener("keydown", alPulsar);
    return () => window.removeEventListener("keydown", alPulsar);
  }, [cerrar]);

  async function copiar() {
    try {
      await navigator.clipboard.writeText(contrasena);
      setCopiada(true);
    } catch {
      // Sin acceso al portapapeles (p. ej., fuera de HTTPS): se selecciona para copiarla a mano
      campo.current?.select();
      setCopiada(false);
    }
  }

  return (
    <div className="velo">
      <div className="dialogo" role="dialog" aria-modal="true" aria-labelledby="aviso-contrasena-titulo">
        <h2 id="aviso-contrasena-titulo">{titulo}</h2>
        <p>
          Contraseña temporal de <strong>{nombreUsuario}</strong>. Entréguela al usuario por un medio seguro.
        </p>
        <div className="contrasena">
          <input ref={campo} readOnly value={contrasena} aria-label="Contraseña temporal" autoComplete="off"
                 spellCheck={false} onFocus={(e) => e.target.select()} />
          <button type="button" className="boton boton--secundario" onClick={copiar}>
            {copiada ? "Copiada" : "Copiar"}
          </button>
        </div>
        {copiada === false && <p className="nota-sprint">No se pudo copiar automáticamente: use Ctrl+C.</p>}
        <p className="alerta alerta--aviso">
          Esta es la única vez que se muestra. Si se pierde, deberá restablecerla de nuevo.
        </p>
        <div className="acciones">
          <button ref={botonCerrar} type="button" className="boton boton--primario" onClick={cerrar}>
            Cerrar
          </button>
        </div>
      </div>
    </div>
  );
}
