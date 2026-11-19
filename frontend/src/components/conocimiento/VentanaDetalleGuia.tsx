// «Ver» de M11: ventana con los metadatos de la guía, quién la cargó y cuándo, sus versiones de
// indexación (fragmentos totales y vigentes, modelo de embeddings) y el historial de trabajos.
// GET /api/conocimiento/documentos/{id}; la respuesta no trae rutas del servidor.
import { useCallback, useEffect, useState, type RefObject } from "react";
import { mensajeError } from "../../api/cliente";
import { conocimientoApi, type DetalleDocumento, type Documento } from "../../api/conocimiento";
import { VACIO, fecha, fechaHora } from "../../utilidades/formato";
import Modal from "../Modal";
import {
  ENTIDADES, ESTADOS_DOCUMENTO, ESTADOS_INDEXACION, ESTADOS_TRABAJO, IDIOMAS, NIVELES, TIPOS_DOCUMENTO, TIPOS_TRABAJO,
  textoDe, textoEtapa,
} from "./textos";

type Props = { documento: Documento; alCerrar: () => void; focoAlCerrar?: RefObject<HTMLElement | null> };

function avanceDe(t: DetalleDocumento["trabajos"][number]): string {
  const etapa = textoEtapa(t.etapa);
  if (t.total !== null && t.total > 0) return `${etapa ?? "Avance"}: ${t.procesados} de ${t.total}`;
  return etapa ?? VACIO;
}

export default function VentanaDetalleGuia({ documento, alCerrar, focoAlCerrar }: Props) {
  const [detalle, setDetalle] = useState<DetalleDocumento | null>(null);
  const [error, setError] = useState<string | null>(null);

  const cargar = useCallback(() => {
    setError(null);
    conocimientoApi.detalle(documento.id_documento).then(setDetalle).catch((e) => setError(mensajeError(e)));
  }, [documento.id_documento]);
  useEffect(cargar, [cargar]);

  const d = detalle;
  const paginas = d && d.pagina_inicio_cuerpo !== null ? `${d.pagina_inicio_cuerpo} a ${d.pagina_fin_cuerpo}` : "Todas las páginas";
  return (
    <Modal id="m11-detalle" titulo={documento.titulo} icono="i" amplia alCerrar={alCerrar} focoAlCerrar={focoAlCerrar}
           descripcion={<p>{documento.codigo_documento ?? "Sin código"} · {NIVELES[documento.nivel].texto}</p>}>
      {error ? (
        <div className="alerta alerta--error" role="alert">
          <p className="alerta__texto">No se pudo cargar el detalle: {error}</p>
          <button type="button" className="boton boton--neutro boton--chico" onClick={cargar}>Reintentar</button>
        </div>
      ) : !d ? (
        <p className="vacio" role="status">Cargando el detalle…</p>
      ) : (
        <div className="detalle-guia">
          <dl className="detalle-guia__datos">
            <div><dt>Entidad emisora</dt><dd>{textoDe(ENTIDADES, d.entidad_emisora)}</dd></div>
            <div><dt>Tipo de documento</dt><dd>{textoDe(TIPOS_DOCUMENTO, d.tipo_documento)}</dd></div>
            <div><dt>Versión</dt><dd>{d.version ?? VACIO}</dd></div>
            <div><dt>Año</dt><dd>{d.anio_publicacion}</dd></div>
            <div><dt>Fecha de publicación</dt><dd>{fecha(d.fecha_publicacion)}</dd></div>
            <div><dt>Idioma</dt><dd>{textoDe(IDIOMAS, d.idioma)}</dd></div>
            <div><dt>Páginas que se indexan</dt><dd>{paginas}</dd></div>
            <div><dt>Estado</dt>
              <dd>{ESTADOS_DOCUMENTO[d.estado].texto} · {ESTADOS_INDEXACION[d.estado_indexacion].texto}</dd></div>
            <div><dt>Versión de indexación</dt><dd>{d.version_indexacion ?? "Sin indexar"}</dd></div>
            <div><dt>Fragmentos vigentes</dt><dd>{d.fragmentos_vigentes}</dd></div>
            <div><dt>Cargada por</dt><dd>{d.cargado_por}</dd></div>
            <div><dt>Fecha de carga</dt><dd>{fechaHora(d.fecha_carga)}</dd></div>
            {d.estado === "OBSOLETA" && (
              <>
                <div><dt>Retirada por</dt><dd>{d.retirado_por ?? VACIO}</dd></div>
                <div><dt>Fecha de retiro</dt><dd>{d.fecha_retiro ? fechaHora(d.fecha_retiro) : VACIO}</dd></div>
                <div className="detalle-guia__motivo"><dt>Motivo del retiro</dt><dd>{d.motivo_retiro ?? VACIO}</dd></div>
              </>
            )}
            <div className="detalle-guia__hash"><dt>Huella del archivo (SHA-256)</dt><dd><code>{d.hash_archivo ?? VACIO}</code></dd></div>
          </dl>

          <h3 className="detalle-guia__subtitulo" id="m11-versiones">Versiones de indexación</h3>
          {d.versiones.length === 0 ? (
            <p className="vacio">Todavía no se indexó.</p>
          ) : (
            <div className="tabla-contenedor detalle-guia__tabla" tabIndex={0} role="region" aria-labelledby="m11-versiones">
              <table className="tabla tabla--compacta">
                <thead>
                  <tr>
                    <th scope="col">Versión</th>
                    <th scope="col" className="guias__numero">Fragmentos</th>
                    <th scope="col" className="guias__numero">Vigentes</th>
                    <th scope="col">Modelo de embeddings</th>
                  </tr>
                </thead>
                <tbody>
                  {d.versiones.map((v) => (
                    <tr key={v.version_indexacion}>
                      <td>{v.version_indexacion}</td>
                      <td className="guias__numero">{v.fragmentos}</td>
                      <td className="guias__numero">{v.vigentes}</td>
                      <td>{v.modelo_embedding ?? VACIO}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <h3 className="detalle-guia__subtitulo" id="m11-trabajos">Historial de trabajos</h3>
          {d.trabajos.length === 0 ? (
            <p className="vacio">Sin trabajos registrados.</p>
          ) : (
            <div className="tabla-contenedor detalle-guia__tabla" tabIndex={0} role="region" aria-labelledby="m11-trabajos">
              <table className="tabla tabla--compacta">
                <thead>
                  <tr>
                    <th scope="col">Solicitado</th>
                    <th scope="col">Tipo</th>
                    <th scope="col">Estado</th>
                    <th scope="col">Avance</th>
                    <th scope="col">Por</th>
                  </tr>
                </thead>
                <tbody>
                  {d.trabajos.map((t) => (
                    <tr key={t.id_trabajo}>
                      <td>{fechaHora(t.fecha_solicitud)}</td>
                      <td>{TIPOS_TRABAJO[t.tipo] ?? t.tipo}</td>
                      <td>
                        {ESTADOS_TRABAJO[t.estado] ?? t.estado}
                        {t.mensaje_error && <span className="detalle-guia__error">{t.mensaje_error}</span>}
                      </td>
                      <td>{avanceDe(t)}</td>
                      <td>{t.solicitado_por}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
      <div className="acciones">
        <button type="button" className="boton boton--neutro" onClick={alCerrar}>Cerrar</button>
      </div>
    </Modal>
  );
}
