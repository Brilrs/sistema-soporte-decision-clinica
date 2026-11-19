// Tabla de guías de M11, compacta como las de M08: cabe sin desplazamiento interno desde unos
// 1000 px; por debajo se desplaza dentro de su contenedor. Los botones nombran la guía para los
// lectores de pantalla («Ver: NTS 213...»). «Retirar» (HU17, Sprint 3 parte F) abre la ventana de
// retiro en las guías vigentes, con el permiso ADMINISTRAR_GUIAS; en las obsoletas (o sin el permiso)
// queda gris, con aria-disabled y la nota como descripción accesible.
import type { Documento } from "../../api/conocimiento";
import { VACIO } from "../../utilidades/formato";
import { ESTADOS_DOCUMENTO, ESTADOS_INDEXACION, NIVELES, puedeReintentar } from "./textos";

type Props = {
  documentos: Documento[];
  ver: (doc: Documento, boton: HTMLButtonElement) => void;
  reintentar: (doc: Documento) => void;
  reintentando: string | null;
  retirar: (doc: Documento, boton: HTMLButtonElement) => void;
  puedeRetirar: boolean;
  idNotaRetirar: string;
};

// Nombre corto para los botones: el código si existe (NTS 213-MINSA/DGIESP-2024); si no, el título.
export const nombreGuia = (d: Documento) => d.codigo_documento ?? d.titulo;

export default function TablaGuias({ documentos, ver, reintentar, reintentando, retirar, puedeRetirar, idNotaRetirar }: Props) {
  return (
    <div className="tabla-contenedor guias__tabla" tabIndex={0} role="region" aria-label="Guías de la base de conocimiento">
      <table className="tabla tabla--compacta">
        <thead>
          <tr>
            <th scope="col">Documento</th>
            <th scope="col">Nivel</th>
            <th scope="col">Versión / año</th>
            <th scope="col" className="guias__numero">Fragmentos</th>
            <th scope="col" className="guias__numero">Citas (30 días)</th>
            <th scope="col">Estado</th>
            <th scope="col"><span className="solo-lectores">Acciones</span></th>
          </tr>
        </thead>
        <tbody>
          {documentos.map((d) => {
            const nivel = NIVELES[d.nivel];
            const estado = ESTADOS_DOCUMENTO[d.estado];
            const indexacion = ESTADOS_INDEXACION[d.estado_indexacion];
            const nombre = nombreGuia(d);
            return (
              <tr key={d.id_documento}>
                <td className="guias__documento">
                  <strong className="guias__titulo" title={d.titulo}>{d.titulo}</strong>
                  {d.codigo_documento && <span className="guias__codigo">{d.codigo_documento}</span>}
                </td>
                <td><span className={`etiqueta ${nivel.clase}`}>{nivel.texto}</span></td>
                <td>
                  {d.anio_publicacion}
                  {d.version && d.version !== d.codigo_documento && <span className="guias__codigo">{d.version}</span>}
                </td>
                <td className="guias__numero">{d.fragmentos_vigentes}</td>
                <td className="guias__numero">{d.citas_30_dias > 0 ? d.citas_30_dias : VACIO}</td>
                <td>
                  <span className="guias__estados">
                    <span className={`etiqueta ${estado.clase}`}>{estado.texto}</span>
                    <span className={`etiqueta ${indexacion.clase}`}>{indexacion.texto}</span>
                  </span>
                </td>
                <td>
                  <div className="guias__acciones">
                    <button type="button" className="boton boton--neutro boton--chico" aria-label={`Ver: ${nombre}`}
                            onClick={(e) => ver(d, e.currentTarget)}>Ver</button>
                    {puedeReintentar(d) && (
                      <button type="button" className="boton boton--secundario boton--chico" aria-label={`Reintentar: ${nombre}`}
                              disabled={reintentando === d.id_documento} onClick={() => reintentar(d)}>
                        {reintentando === d.id_documento ? "Reintentando…" : "Reintentar"}
                      </button>
                    )}
                    {d.estado === "VIGENTE" && puedeRetirar ? (
                      <button type="button" className="boton boton--peligro boton--chico" aria-label={`Retirar: ${nombre}`}
                              onClick={(e) => retirar(d, e.currentTarget)}>Retirar</button>
                    ) : (
                      // aria-disabled y no disabled: sigue recibiendo el foco, así el lector de pantalla
                      // anuncia que no está disponible y lee la nota. No hace nada al pulsarlo.
                      <button type="button" className="boton boton--peligro boton--chico" aria-disabled="true"
                              aria-label={`Retirar: ${nombre}`} aria-describedby={idNotaRetirar}
                              title={d.estado === "OBSOLETA" ? "La guía ya está retirada" : "Sin permiso para retirar guías"}>
                        Retirar
                      </button>
                    )}
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
