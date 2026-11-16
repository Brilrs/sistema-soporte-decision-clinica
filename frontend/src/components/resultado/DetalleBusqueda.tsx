// M07 · «Detalle de la búsqueda» (RF8): por intento, el tipo de búsqueda, los candidatos que
// evaluó el reranker, la relevancia máxima frente al umbral y el resultado del intento. Los
// valores son los del backend (relevancia y umbral con 3 decimales); no se calcula nada aquí.
// Desplegable con <details>: el teclado y los lectores de pantalla lo manejan sin código propio.
import type { Intento, ResultadoIntento } from "../../api/tipos_consulta";
import { decimal } from "../../utilidades/formato";

const TIPOS = { INICIAL: "Búsqueda inicial", AMPLIADA: "Búsqueda ampliada" } as const;

const RESULTADOS: Record<ResultadoIntento, string> = {
  APROBADO: "Aprobado",
  REINTENTO: "Se reintentó",
  EVIDENCIA_INSUFICIENTE: "Evidencia insuficiente",
  ERROR: "Error",
};

export function relevancia(valor: number | null): string {
  return valor === null ? "Sin fragmentos" : decimal(valor, 3);
}

export default function DetalleBusqueda({ intentos }: { intentos: Intento[] }) {
  return (
    <details className="detalle-busqueda">
      <summary>Detalle de la búsqueda</summary>
      {intentos.length === 0 ? (
        <p className="texto-tenue">La consulta no llegó a buscar en las guías clínicas.</p>
      ) : (
        <>
          <p className="detalle-busqueda__resumen">
            {intentos.length === 1 ? "Se hizo 1 búsqueda" : `Se hicieron ${intentos.length} búsquedas`} en las guías
            clínicas vigentes. Una búsqueda respalda la respuesta si su relevancia máxima alcanza el umbral.
          </p>
          <div className="tabla-contenedor detalle-busqueda__tabla" tabIndex={0} role="region"
               aria-label="Intentos de búsqueda">
            <table className="tabla">
              <thead>
                <tr>
                  <th scope="col">Intento</th>
                  <th scope="col">Tipo de búsqueda</th>
                  <th scope="col">Candidatos evaluados</th>
                  <th scope="col">Relevancia máxima</th>
                  <th scope="col">Umbral</th>
                  <th scope="col">Resultado</th>
                </tr>
              </thead>
              <tbody>
                {intentos.map((i) => (
                  <tr key={i.numero}>
                    <th scope="row">{i.numero}</th>
                    <td>{TIPOS[i.tipo_busqueda] ?? i.tipo_busqueda}</td>
                    <td className="detalle-busqueda__numero">{i.candidatos_evaluados}</td>
                    <td className="detalle-busqueda__numero">{relevancia(i.relevancia_maxima)}</td>
                    <td className="detalle-busqueda__numero">{decimal(i.umbral_relevancia, 3)}</td>
                    <td>{RESULTADOS[i.resultado] ?? i.resultado}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </details>
  );
}
