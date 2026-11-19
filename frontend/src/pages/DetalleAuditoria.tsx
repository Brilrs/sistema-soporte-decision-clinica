// Detalle de auditoría de una consulta (M13, /admin/auditoria/:id; Sprint 3, parte D2), permiso
// VER_AUDITORIA. GET /api/auditoria/consultas/{id} (docs/contrato_auditoria.md): estado, intentos,
// tiempos, modelo, prompt, tokens y costo; por intento, la búsqueda, la verificación 6.1 a 6.3, el
// control de identificadores, los fragmentos enviados y la solicitud exacta enviada al modelo. Una
// página propia (no un panel) para que a 320 px el bloque de la solicitud tenga todo el ancho. El
// enlace de vuelta conserva los filtros y la página de la lista. Solo se muestran los campos que
// la pantalla conoce: la respuesta ya llega reducida a ellos (api/auditoria.ts) y el resumen se arma
// con la lista fija RESUMEN.
import { useEffect, useState, type ReactNode } from "react";
import { Link, useLocation, useParams } from "react-router-dom";
import { auditoriaApi } from "../api/auditoria";
import { ErrorApi, mensajeError } from "../api/cliente";
import type { DetalleAuditoria as Detalle, FragmentoAuditado, IntentoAuditado } from "../api/tipos_auditoria";
import { EtiquetaEstadoConsulta } from "../components/Etiquetas";
import Migas from "../components/Migas";
import {
  BUSQUEDAS,
  NOTA_SIN_IDENTIFICADORES,
  RESULTADOS_INTENTO,
  VERIFICACIONES,
  controlPrevio,
  entero,
  latencia,
  paginas,
  resultadoControl,
  usd,
} from "../components/auditoria/formato";
import { VACIO, decimal, fechaHora, siNo } from "../utilidades/formato";
import { useTituloPagina } from "../utilidades/useTituloPagina";

type Carga = { estado: "cargando" } | { estado: "error"; mensaje: string; codigo: number | null } | { estado: "listo"; d: Detalle };

// Datos de la consulta que se muestran, en orden (nunca se recorre la respuesta completa).
const RESUMEN: { etiqueta: string; valor: (d: Detalle) => ReactNode }[] = [
  { etiqueta: "Usuario", valor: (d) => d.nombre_usuario },
  { etiqueta: "Inicio", valor: (d) => fechaHora(d.fecha_hora_inicio) },
  { etiqueta: "Fin", valor: (d) => (d.fecha_hora_fin ? fechaHora(d.fecha_hora_fin) : VACIO) },
  { etiqueta: "Intentos", valor: (d) => (d.numero_intentos === 2 ? "2 (con reintento)" : String(d.numero_intentos)) },
  { etiqueta: "Tiempo total", valor: (d) => latencia(d.latencia_total_ms) },
  { etiqueta: "Tokens", valor: (d) => `${entero(d.tokens_entrada)} entrada · ${entero(d.tokens_salida)} salida` },
  { etiqueta: "Costo", valor: (d) => usd(d.costo_usd, 3) },
  { etiqueta: "Tamizaje no vigente confirmado", valor: (d) => siNo(d.confirma_tamizaje_no_vigente) },
];

// Solo un texto de búsqueda que empiece con «?» vuelve a la lista con sus filtros.
function volverA(estado: unknown): string {
  const volver = (estado as { volver?: unknown } | null)?.volver;
  return typeof volver === "string" && volver.startsWith("?") ? `/admin/auditoria${volver}` : "/admin/auditoria";
}

export default function DetalleAuditoria() {
  useTituloPagina("Detalle de auditoría");
  const { id = "" } = useParams();
  const { state } = useLocation();
  const destino = volverA(state);
  const [carga, setCarga] = useState<Carga>({ estado: "cargando" });
  const [intento, setIntento] = useState(0);

  useEffect(() => {
    const control = new AbortController();
    setCarga({ estado: "cargando" });
    auditoriaApi.detalle(id, control.signal)
      .then((d) => setCarga({ estado: "listo", d }))
      .catch((e) => !control.signal.aborted && setCarga({
        estado: "error", mensaje: mensajeError(e), codigo: e instanceof ErrorApi ? e.estado : null }));
    return () => control.abort();
  }, [id, intento]);

  const volver = <Link className="boton boton--neutro boton--auto auditoria__volver" to={destino}>Volver a la auditoría</Link>;

  if (carga.estado !== "listo") {
    return (
      <section className="auditoria auditoria-detalle">
        <Migas items={[{ texto: "Auditoría", ruta: destino }, { texto: "Detalle de la consulta" }]} />
        <div className="encabezado-pagina">
          <h1>Detalle de la consulta</h1>
          {volver}
        </div>
        {carga.estado === "cargando" ? (
          <p className="vacio" role="status" aria-live="polite">Cargando el detalle…</p>
        ) : (
          <div className="alerta alerta--error" role="alert">
            <p className="alerta__texto">
              {carga.codigo === 404 ? carga.mensaje : `No se pudo cargar el detalle. ${carga.mensaje}`}
            </p>
            {carga.codigo !== 404 && (
              <button type="button" className="boton boton--secundario boton--chico" onClick={() => setIntento((n) => n + 1)}>
                Reintentar
              </button>
            )}
          </div>
        )}
      </section>
    );
  }

  const d = carga.d;
  return (
    <section className="auditoria auditoria-detalle">
      <Migas items={[{ texto: "Auditoría", ruta: destino }, { texto: "Detalle de la consulta" }]} />
      <div className="encabezado-pagina">
        <div className="auditoria__titulo">
          <h1>Consulta del {fechaHora(d.fecha_hora_inicio)}</h1>
          <p className="auditoria__etiquetas">
            <EtiquetaEstadoConsulta estado={d.estado} />
            {d.modo_prueba && <span className="etiqueta etiqueta--prueba">Prueba</span>}
          </p>
          {d.modo_prueba && (
            <p className="texto-tenue auditoria__nota-prueba">
              Consulta de prueba: la respuesta la generó el simulador, no el modelo de lenguaje. No cuenta en los indicadores.
            </p>
          )}
        </div>
        {volver}
      </div>

      <div className="tarjeta tarjeta--ancha">
        <h2>Resumen</h2>
        <dl className="auditoria__datos">
          {RESUMEN.map((campo) => (
            <div key={campo.etiqueta}>
              <dt>{campo.etiqueta}</dt>
              <dd>{campo.valor(d)}</dd>
            </div>
          ))}
        </dl>
      </div>

      {d.intentos.length === 0 ? (
        <div className="tarjeta tarjeta--ancha">
          <p className="vacio">
            Esta consulta no llegó a la búsqueda ni al modelo de lenguaje: no tiene intentos, fragmentos ni solicitud.
          </p>
        </div>
      ) : (
        d.intentos.map((i) => <Intento key={i.numero_intento} i={i} />)
      )}
    </section>
  );
}

function Intento({ i }: { i: IntentoAuditado }) {
  const titulo = `Intento ${i.numero_intento}${i.tipo_busqueda ? ` · ${BUSQUEDAS[i.tipo_busqueda] ?? i.tipo_busqueda}` : ""}`;
  const idTitulo = `intento-${i.numero_intento}`;
  return (
    <section className="tarjeta tarjeta--ancha auditoria__intento" aria-labelledby={idTitulo}>
      <h2 id={idTitulo}>{titulo}</h2>
      <dl className="auditoria__datos">
        <div><dt>Resultado</dt><dd>{i.resultado ? RESULTADOS_INTENTO[i.resultado] ?? i.resultado : VACIO}</dd></div>
        <div><dt>Modelo</dt><dd className="auditoria__modelo">{i.modelo_llm ?? "Sin llamada al modelo"}</dd></div>
        <div><dt>Versión del prompt</dt><dd>{i.version_prompt ?? VACIO}</dd></div>
        <div><dt>Tiempo del modelo</dt><dd>{latencia(i.latencia_llm_ms)}</dd></div>
        <div>
          <dt>Tokens</dt>
          <dd>{entero(i.tokens_entrada)} entrada · {entero(i.tokens_salida)} salida · {entero(i.tokens_razonamiento)} razonamiento</dd>
        </div>
        <div><dt>Costo</dt><dd>{usd(i.costo_usd, 3)}</dd></div>
        <div><dt>Candidatos evaluados</dt><dd>{entero(i.candidatos_evaluados)}</dd></div>
        <div>
          <dt>Relevancia máxima y umbral</dt>
          <dd>{decimal(i.verificacion.relevancia_maxima, 3)} frente a {decimal(i.verificacion.umbral_relevancia, 3)}</dd>
        </div>
        <div><dt>Control de identificadores</dt><dd>{controlPrevio(i)}</dd></div>
        <div><dt>Hash de la solicitud (SHA-256)</dt><dd><code className="auditoria__hash">{i.hash_solicitud ?? VACIO}</code></dd></div>
      </dl>

      <h3>Verificación</h3>
      <ul className="auditoria__verificaciones">
        {VERIFICACIONES.map((v) => {
          const r = resultadoControl(i.verificacion[v.clave]);
          return (
            <li key={v.clave} className={`auditoria__verificacion auditoria__verificacion--${r.clase}`}>
              <span>{v.nombre}</span>
              <strong>{r.texto}</strong>
            </li>
          );
        })}
      </ul>

      <h3>Fragmentos enviados</h3>
      <Fragmentos fragmentos={i.fragmentos} numero={i.numero_intento} />

      <h3>Solicitud enviada al modelo</h3>
      <Solicitud i={i} />
    </section>
  );
}

function Fragmentos({ fragmentos, numero }: { fragmentos: FragmentoAuditado[]; numero: number }) {
  if (fragmentos.length === 0) return <p className="texto-tenue">En este intento no se enviaron fragmentos al modelo.</p>;
  return (
    <div className="tabla-contenedor auditoria__fragmentos" tabIndex={0} role="region"
         aria-label={`Fragmentos enviados en el intento ${numero}`}>
      <table className="tabla tabla--compacta">
        <thead>
          <tr>
            <th scope="col">Cita</th>
            <th scope="col">Documento</th>
            <th scope="col">Sección y páginas</th>
            <th scope="col">Puntaje</th>
            <th scope="col">Origen</th>
          </tr>
        </thead>
        <tbody>
          {fragmentos.map((f) => (
            <tr key={f.etiqueta ?? `${f.documento}-${f.pagina_inicio}`}>
              <th scope="row">{f.etiqueta ?? VACIO}</th>
              <td className="auditoria__documento">{f.documento ?? VACIO}</td>
              <td className="auditoria__documento">
                {f.seccion ?? VACIO}
                <span className="texto-tenue"> · {paginas(f.pagina_inicio, f.pagina_fin)}</span>
              </td>
              <td className="auditoria__numero">{f.puntaje_reranker === null ? VACIO : decimal(f.puntaje_reranker, 3)}</td>
              <td>
                {f.origen === "PUNTERO"
                  ? <span className="etiqueta etiqueta--puntero">Agregado por referencia</span>
                  : <span className="etiqueta etiqueta--reranker">Reranker</span>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Solicitud({ i }: { i: IntentoAuditado }) {
  if (i.solicitud_enviada === null) {
    const motivo = i.control_identificadores === false
      ? "No disponible: el control previo encontró posibles identificadores y bloqueó la solicitud. Por seguridad no se guarda."
      : "No disponible: en este intento no se envió una solicitud al modelo.";
    return <p className="alerta alerta--aviso auditoria__sin-solicitud">{motivo}</p>;
  }
  const texto = JSON.stringify(i.solicitud_enviada, null, 2);
  return (
    <div className="auditoria__solicitud">
      <p className="auditoria__nota-solicitud"><strong>{NOTA_SIN_IDENTIFICADORES}</strong>: es la solicitud tal como se registró,
        después de la lista blanca de campos y del control previo al envío.</p>
      <pre className="auditoria__codigo" tabIndex={0} role="region"
           aria-label={`Solicitud enviada al modelo en el intento ${i.numero_intento}`}><code>{texto}</code></pre>
    </div>
  );
}
