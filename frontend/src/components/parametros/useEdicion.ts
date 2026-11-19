// Estado común de la edición de un grupo de M12: modo edición, ventana de confirmación, errores de la
// API por campo (rutas como tramos.0.categorias.1.hb_max_g_dl) y aviso de éxito.
import { useState } from "react";
import type { CampoMensaje } from "../../api/tipos_parametros";

export function useEdicion() {
  const [editando, setEditando] = useState(false);
  const [ventana, setVentana] = useState(false);
  const [errores, setErrores] = useState<CampoMensaje[]>([]);
  const [exito, setExito] = useState<string | null>(null);
  return {
    editando, ventana, errores, exito, setErrores,
    editar: () => { setEditando(true); setExito(null); setErrores([]); },
    descartar: () => { setEditando(false); setVentana(false); setErrores([]); },
    abrirVentana: () => setVentana(true),
    cerrarVentana: () => setVentana(false),
    terminar: (mensaje: string) => { setVentana(false); setEditando(false); setErrores([]); setExito(mensaje); },
    // Errores cuyo campo empieza con el prefijo (los de una fila de la tabla).
    erroresDe: (prefijo: string) => errores.filter((e) => e.campo === prefijo || e.campo.startsWith(`${prefijo}.`)),
  };
}

export function mensajeExito(titulo: string, cambios: { elemento: string; antes: string; despues: string }[]): string {
  const detalle = cambios.map((c) => `${c.elemento}: ${c.antes} → ${c.despues}`).join("; ");
  return `Cambios guardados en «${titulo}», vigentes desde ahora. ${detalle}.`;
}
