// Avance de la indexación (M11): GET /api/conocimiento/trabajos?activos=true cada 3 s mientras haya
// trabajos PENDIENTE o EN_CURSO y la pestaña esté visible. Sin trabajos activos, o con la pestaña
// oculta, no se consulta; al volver a la pestaña se consulta enseguida si quedaban activos. Cuando un
// trabajo deja la lista (terminó bien o con error) se avisa con sus ids para refrescar la tabla.
import { useCallback, useEffect, useRef, useState } from "react";
import { conocimientoApi, type Trabajo } from "../../api/conocimiento";

export const INTERVALO_MS = 3000;

const visible = () => typeof document === "undefined" || document.visibilityState !== "hidden";

export function useTrabajosActivos(alTerminar: (terminados: Trabajo[]) => void) {
  const [trabajos, setTrabajos] = useState<Trabajo[]>([]);
  const [error, setError] = useState(false);
  const anteriores = useRef<Trabajo[]>([]);
  const temporizador = useRef<number | null>(null);
  const terminarRef = useRef(alTerminar);
  terminarRef.current = alTerminar;
  const montado = useRef(true);

  const detener = useCallback(() => {
    if (temporizador.current !== null) window.clearTimeout(temporizador.current);
    temporizador.current = null;
  }, []);

  const consultar = useCallback(async () => {
    detener();
    let activos: Trabajo[];
    try {
      activos = await conocimientoApi.trabajosActivos();
      if (!montado.current) return;
      setError(false);
    } catch {
      if (!montado.current) return;
      // Un fallo de red no detiene el seguimiento si había trabajos activos: se reintenta.
      setError(true);
      activos = anteriores.current;
    }
    const ids = new Set(activos.map((t) => t.id_trabajo));
    const terminados = anteriores.current.filter((t) => !ids.has(t.id_trabajo));
    anteriores.current = activos;
    setTrabajos(activos);
    if (terminados.length) terminarRef.current(terminados);
    if (activos.length && visible()) temporizador.current = window.setTimeout(() => void consultar(), INTERVALO_MS);
  }, [detener]);

  useEffect(() => {
    montado.current = true;
    void consultar();
    function cambioDeVisibilidad() {
      if (!visible()) detener();
      else if (anteriores.current.length && temporizador.current === null) void consultar();
    }
    document.addEventListener("visibilitychange", cambioDeVisibilidad);
    return () => {
      montado.current = false;
      detener();
      document.removeEventListener("visibilitychange", cambioDeVisibilidad);
    };
  }, [consultar, detener]);

  // Tras cargar una guía o pedir un reintento: consulta ya, sin esperar el intervalo.
  return { trabajos, error, actualizar: consultar };
}
