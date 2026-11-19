// «Historial de cambios» de M12 (parte E2): versiones de los parámetros, de la más reciente a la más
// antigua (GET /api/parametros/historial), con filtro por grupo y paginación de 20. Tabla desde 800 px
// y tarjetas por debajo, como en M13. Se recarga después de cada guardado.
import { useEffect, useId, useState } from "react";
import { mensajeError } from "../../api/cliente";
import { parametrosApi } from "../../api/parametros";
import type { GrupoHistorial, PaginaHistorial, VersionHistorial } from "../../api/tipos_parametros";
import { VACIO, decimal, fechaHora } from "../../utilidades/formato";
import { useAnchoAngosto } from "../Layout";
import EstadoVerificacion from "./EstadoVerificacion";
import { GRUPOS_HISTORIAL, SIN_LIMITE, elementoLegible } from "./textos";

export const POR_PAGINA = 20;
type Carga = { estado: "cargando" } | { estado: "error"; mensaje: string } | { estado: "listo"; p: PaginaHistorial };

function numero(v: unknown): string {
  return v === null || v === undefined ? SIN_LIMITE : decimal(Number(v));
}

export function valorLegible(v: VersionHistorial): string {
  const x = v.valores;
  if (v.grupo === "puntos_corte") return `${numero(x.hb_min_g_dl)} a ${numero(x.hb_max_g_dl)} g/dL`;
  if (v.grupo === "ajuste_altitud") return `${numero(x.ajuste_g_dl)} g/dL`;
  if (v.grupo === "vigencia_tamizaje") return `${x.valor} días`;
  return String(x.valor ?? VACIO);
}

export default function HistorialParametros({ recarga, descripciones }: { recarga: number; descripciones: Record<string, string> }) {
  const [grupo, setGrupo] = useState<GrupoHistorial | "">("");
  const [pagina, setPagina] = useState(1);
  const [carga, setCarga] = useState<Carga>({ estado: "cargando" });
  const [intento, setIntento] = useState(0);
  const angosto = useAnchoAngosto();
  const idFiltro = useId();

  useEffect(() => {
    const control = new AbortController();
    setCarga({ estado: "cargando" });
    parametrosApi.historial(grupo || null, POR_PAGINA, (pagina - 1) * POR_PAGINA, control.signal)
      .then((p) => setCarga({ estado: "listo", p }))
      .catch((e) => !control.signal.aborted && setCarga({ estado: "error", mensaje: mensajeError(e) }));
    return () => control.abort();
  }, [grupo, pagina, recarga, intento]);

  const paginas = carga.estado === "listo" ? Math.max(1, Math.ceil(carga.p.total / POR_PAGINA)) : 1;
  const elemento = (v: VersionHistorial) => elementoLegible(v.elemento, descripciones);

  return (
    <section className="tarjeta tarjeta--ancha parametros__seccion" aria-labelledby="historial-titulo">
      <h2 id="historial-titulo">Historial de cambios</h2>
      <div className="parametros__filtro">
        <label htmlFor={idFiltro}>Grupo</label>
        <select id={idFiltro} value={grupo} onChange={(e) => { setGrupo(e.target.value as GrupoHistorial | ""); setPagina(1); }}>
          <option value="">Todos</option>
          {Object.entries(GRUPOS_HISTORIAL).map(([valor, texto]) => <option key={valor} value={valor}>{texto}</option>)}
        </select>
      </div>
      {carga.estado === "cargando" ? (
        <p className="vacio" role="status" aria-live="polite">Cargando el historial…</p>
      ) : carga.estado === "error" ? (
        <div className="alerta alerta--error" role="alert">
          <p className="alerta__texto">No se pudo cargar el historial. {carga.mensaje}</p>
          <button type="button" className="boton boton--secundario boton--auto" onClick={() => setIntento((n) => n + 1)}>Reintentar</button>
        </div>
      ) : carga.p.versiones.length === 0 ? (
        <p className="vacio" role="status">No hay versiones registradas para este grupo.</p>
      ) : (
        <>
          <p className="texto-tenue parametros__conteo" role="status">
            Mostrando {carga.p.desplazamiento + 1} a {carga.p.desplazamiento + carga.p.versiones.length} de {carga.p.total} versiones
          </p>
          {angosto ? (
            <ul className="parametros__tarjetas" aria-label="Versiones de los parámetros">
              {carga.p.versiones.map((v) => (
                <li key={`${v.tabla}-${v.id}`} className="parametros__tarjeta">
                  <p className="parametros__tarjeta-cabecera"><strong>{elemento(v)}</strong> <EstadoVerificacion verificado={v.verificado} /></p>
                  <dl className="parametros__tarjeta-datos">
                    <div><dt>Valor</dt><dd>{valorLegible(v)}</dd></div>
                    <div><dt>Vigente desde</dt><dd>{fechaHora(v.vigente_desde)}</dd></div>
                    <div><dt>Hasta</dt><dd>{v.vigente_hasta ? fechaHora(v.vigente_hasta) : "Vigente"}</dd></div>
                    <div><dt>Motivo</dt><dd>{v.motivo_cambio ?? "Carga inicial"}</dd></div>
                    <div><dt>Referencia</dt><dd>{v.referencia ?? VACIO}</dd></div>
                    <div><dt>Quién</dt><dd>{v.modificado_por}</dd></div>
                  </dl>
                </li>
              ))}
            </ul>
          ) : (
            <div className="tabla-contenedor parametros__historial" tabIndex={0} role="region" aria-label="Versiones de los parámetros">
              <table className="tabla tabla--compacta">
                <thead>
                  <tr>
                    <th scope="col">Elemento</th>
                    <th scope="col">Valor</th>
                    <th scope="col">Vigente desde</th>
                    <th scope="col">Hasta</th>
                    <th scope="col">Motivo</th>
                    <th scope="col">Referencia</th>
                    <th scope="col">Verificado</th>
                    <th scope="col">Quién</th>
                  </tr>
                </thead>
                <tbody>
                  {carga.p.versiones.map((v) => (
                    <tr key={`${v.tabla}-${v.id}`}>
                      <th scope="row" className="parametros__descripcion">{elemento(v)}</th>
                      <td className="parametros__numero">{valorLegible(v)}</td>
                      <td>{fechaHora(v.vigente_desde)}</td>
                      <td>{v.vigente_hasta ? fechaHora(v.vigente_hasta) : "Vigente"}</td>
                      <td className="parametros__texto-largo">{v.motivo_cambio ?? "Carga inicial"}</td>
                      <td className="parametros__texto-largo">{v.referencia ?? VACIO}</td>
                      <td><EstadoVerificacion verificado={v.verificado} /></td>
                      <td>{v.modificado_por}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {paginas > 1 && (
            <nav className="parametros__paginacion" aria-label="Paginación del historial">
              <button type="button" className="boton boton--neutro boton--auto" disabled={pagina <= 1}
                      onClick={() => setPagina((n) => n - 1)}>Anterior</button>
              <span>Página {pagina} de {paginas}</span>
              <button type="button" className="boton boton--neutro boton--auto" disabled={pagina >= paginas}
                      onClick={() => setPagina((n) => n + 1)}>Siguiente</button>
            </nav>
          )}
        </>
      )}
    </section>
  );
}
