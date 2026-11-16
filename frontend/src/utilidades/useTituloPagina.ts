// Título de la pestaña del navegador: «Pantalla · CDSS Anemia Infantil». Nunca lleva datos del
// paciente (nombre, DNI, HC): el título queda en el historial del navegador y en la barra de tareas.
import { useEffect } from "react";

export const NOMBRE_SISTEMA = "CDSS Anemia Infantil";

export function tituloPagina(pantalla: string | null): string {
  return pantalla ? `${pantalla} · ${NOMBRE_SISTEMA}` : NOMBRE_SISTEMA;
}

export function useTituloPagina(pantalla: string | null): void {
  useEffect(() => {
    document.title = tituloPagina(pantalla);
  }, [pantalla]);
}
