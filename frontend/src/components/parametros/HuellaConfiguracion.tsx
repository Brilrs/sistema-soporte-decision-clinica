// «Huella de configuración» de M12 (parte E2): el SHA-256 de la configuración vigente, con «Copiar» y la
// huella de cada componente (GET /api/parametros/huella). Se recarga después de cada guardado.
import { useEffect, useState } from "react";
import { mensajeError } from "../../api/cliente";
import { parametrosApi } from "../../api/parametros";
import type { HuellaConfiguracion as Huella } from "../../api/tipos_parametros";
import { fechaHora } from "../../utilidades/formato";
import { COMPONENTES_HUELLA } from "./textos";

type Carga = { estado: "cargando" } | { estado: "error"; mensaje: string } | { estado: "listo"; h: Huella };

export default function HuellaConfiguracion({ recarga }: { recarga: number }) {
  const [carga, setCarga] = useState<Carga>({ estado: "cargando" });
  const [intento, setIntento] = useState(0);
  const [copia, setCopia] = useState<string | null>(null);

  useEffect(() => {
    const control = new AbortController();
    setCarga({ estado: "cargando" });
    setCopia(null);
    parametrosApi.huella(control.signal)
      .then((h) => setCarga({ estado: "listo", h }))
      .catch((e) => !control.signal.aborted && setCarga({ estado: "error", mensaje: mensajeError(e) }));
    return () => control.abort();
  }, [recarga, intento]);

  async function copiar(texto: string) {
    try {
      await navigator.clipboard.writeText(texto);
      setCopia("Huella copiada.");
    } catch {
      setCopia("No se pudo copiar: seleccione la huella y cópiela.");
    }
  }

  return (
    <section className="tarjeta tarjeta--ancha parametros__seccion" aria-labelledby="huella-titulo">
      <h2 id="huella-titulo">Huella de configuración</h2>
      <p className="texto-tenue parametros__nota">
        Resume todos los valores vigentes. Si dos evaluaciones tienen la misma huella, usaron la misma configuración. Solo lectura.
      </p>
      {carga.estado === "cargando" ? (
        <p className="vacio" role="status" aria-live="polite">Cargando la huella…</p>
      ) : carga.estado === "error" ? (
        <div className="alerta alerta--error" role="alert">
          <p className="alerta__texto">No se pudo cargar la huella. {carga.mensaje}</p>
          <button type="button" className="boton boton--secundario boton--auto" onClick={() => setIntento((n) => n + 1)}>Reintentar</button>
        </div>
      ) : (
        <>
          <div className="parametros__huella">
            <code className="parametros__huella-valor" aria-label="Huella SHA-256">{carga.h.huella}</code>
            <button type="button" className="boton boton--secundario boton--auto" onClick={() => copiar(carga.h.huella)}>Copiar</button>
          </div>
          <p className="parametros__copia" role="status">{copia ?? ""}</p>
          <p className="texto-tenue parametros__nota">
            Calculada el {fechaHora(carga.h.calculada_en)}. Versión del prompt: {carga.h.version_prompt ?? "sin dato"}.
          </p>
          <ul className="parametros__componentes" aria-label="Componentes de la huella">
            {carga.h.componentes.map((c) => (
              <li key={c.nombre}>
                <span className="parametros__componente">{COMPONENTES_HUELLA[c.nombre] ?? c.nombre}</span>
                <span className="texto-tenue"> ({c.elementos} {c.elementos === 1 ? "elemento" : "elementos"})</span>
                <code className="parametros__huella-componente">{c.huella}</code>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}
