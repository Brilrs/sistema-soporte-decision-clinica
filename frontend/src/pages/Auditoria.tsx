// M13 · «Auditoría y trazabilidad» (/admin/auditoria, HU13; Sprint 3, parte D2), permiso VER_AUDITORIA.
// Rutas de la parte D1 (docs/contrato_auditoria.md): indicadores de 30 días sin consultas de prueba y
// la lista de todas las consultas, con filtros de estado y fechas (días de Lima) y el interruptor
// «Incluir consultas de prueba» (apagado por omisión, decisión 5). Los filtros y la página van en la
// dirección, como en «Historial de consultas», para conservarlos al volver del detalle. Desde 800 px
// la lista es una tabla compacta; por debajo, tarjetas apiladas. La pantalla solo llama a las rutas de
// auditoría y no guarda nada en el navegador.
import { useEffect, useId, useState, type FormEvent } from "react";
import { Link, useLocation, useSearchParams } from "react-router-dom";
import { auditoriaApi } from "../api/auditoria";
import { mensajeError } from "../api/cliente";
import type { ConsultaAuditada, EstadoAuditado, PaginaAuditoria } from "../api/tipos_auditoria";
import { EtiquetaEstadoConsulta } from "../components/Etiquetas";
import { useAnchoAngosto } from "../components/Layout";
import IndicadoresAuditoria from "../components/auditoria/IndicadoresAuditoria";
import { entero, latencia, modeloYPrompt, usd } from "../components/auditoria/formato";
import { ESTADOS_CONSULTA, fechaHora } from "../utilidades/formato";
import { useTituloPagina } from "../utilidades/useTituloPagina";

export const POR_PAGINA = 20;
const FECHA = /^\d{4}-\d{2}-\d{2}$/;

type Filtros = { estado: EstadoAuditado | ""; desde: string; hasta: string };
type Parametros = Filtros & { pruebas: boolean; pagina: number };

// Lee los filtros, el interruptor y la página de la dirección, descartando lo que no sea válido.
export function leerParametros(p: URLSearchParams): Parametros {
  const estado = p.get("estado") ?? "";
  const desde = p.get("desde") ?? "";
  const hasta = p.get("hasta") ?? "";
  const pagina = Number(p.get("pagina") ?? "1");
  return {
    estado: estado in ESTADOS_CONSULTA ? (estado as EstadoAuditado) : "",
    desde: FECHA.test(desde) ? desde : "",
    hasta: FECHA.test(hasta) ? hasta : "",
    pruebas: p.get("pruebas") === "1",
    pagina: Number.isInteger(pagina) && pagina >= 1 ? pagina : 1,
  };
}

export function escribirParametros(f: Parametros): URLSearchParams {
  const p = new URLSearchParams();
  if (f.estado) p.set("estado", f.estado);
  if (f.desde) p.set("desde", f.desde);
  if (f.hasta) p.set("hasta", f.hasta);
  if (f.pruebas) p.set("pruebas", "1");
  if (f.pagina > 1) p.set("pagina", String(f.pagina));
  return p;
}

type Carga = { estado: "cargando" } | { estado: "error"; mensaje: string } | { estado: "listo"; pagina: PaginaAuditoria };

export default function Auditoria() {
  useTituloPagina("Auditoría");
  const [parametros, setParametros] = useSearchParams();
  const actual = leerParametros(parametros);
  const clave = escribirParametros(actual).toString();
  const [borrador, setBorrador] = useState<Filtros>({ estado: actual.estado, desde: actual.desde, hasta: actual.hasta });
  const [errorFechas, setErrorFechas] = useState<string | null>(null);
  const [carga, setCarga] = useState<Carga>({ estado: "cargando" });
  const [intento, setIntento] = useState(0);
  const angosto = useAnchoAngosto();
  const ids = { estado: useId(), desde: useId(), hasta: useId(), errorFechas: useId(), pruebas: useId() };
  const conFiltros = Boolean(actual.estado || actual.desde || actual.hasta || actual.pruebas);

  useEffect(() => {
    setBorrador({ estado: actual.estado, desde: actual.desde, hasta: actual.hasta });
    // clave resume los filtros, el interruptor y la página de la dirección.
  }, [clave]);

  useEffect(() => {
    const control = new AbortController();
    setCarga({ estado: "cargando" });
    auditoriaApi.consultas({
      estado: actual.estado || undefined, fecha_desde: actual.desde || undefined, fecha_hasta: actual.hasta || undefined,
      incluir_pruebas: actual.pruebas, limite: POR_PAGINA, desplazamiento: (actual.pagina - 1) * POR_PAGINA,
    }, control.signal)
      .then((pagina) => setCarga({ estado: "listo", pagina }))
      .catch((e) => !control.signal.aborted && setCarga({ estado: "error", mensaje: mensajeError(e) }));
    return () => control.abort();
  }, [clave, intento]);

  function filtrar(e: FormEvent) {
    e.preventDefault();
    if (borrador.desde && borrador.hasta && borrador.desde > borrador.hasta) {
      setErrorFechas("La fecha «Hasta» no puede ser anterior a «Desde».");
      return;
    }
    setErrorFechas(null);
    setParametros(escribirParametros({ ...borrador, pruebas: actual.pruebas, pagina: 1 }));
  }

  // El interruptor se aplica de inmediato y vuelve a la primera página, sin tocar los demás filtros.
  function alternarPruebas(incluir: boolean) {
    setParametros(escribirParametros({ ...actual, pruebas: incluir, pagina: 1 }));
  }

  function limpiar() {
    setErrorFechas(null);
    setParametros(new URLSearchParams());
  }

  const irA = (pagina: number) => setParametros(escribirParametros({ ...actual, pagina }));

  return (
    <section className="auditoria">
      <div className="encabezado-pagina">
        <div className="auditoria__titulo">
          <h1>Auditoría y trazabilidad</h1>
          <p className="texto-tenue">
            Registro de cada consulta procesada por el sistema: resultado, tiempo, modelo, tokens y costo. Abra una
            consulta para ver la solicitud enviada al modelo, los fragmentos y la verificación.
          </p>
        </div>
      </div>

      <div className="tarjeta tarjeta--ancha">
        <IndicadoresAuditoria />
      </div>

      <form className="tarjeta tarjeta--ancha auditoria__filtros" onSubmit={filtrar} aria-label="Filtros de la auditoría"
            noValidate>
        <div className="auditoria__campo">
          <label htmlFor={ids.estado}>Estado</label>
          <select id={ids.estado} value={borrador.estado}
                  onChange={(e) => setBorrador({ ...borrador, estado: e.target.value as Filtros["estado"] })}>
            <option value="">Todos</option>
            {Object.entries(ESTADOS_CONSULTA).map(([valor, texto]) => <option key={valor} value={valor}>{texto}</option>)}
          </select>
        </div>
        <div className="auditoria__campo">
          <label htmlFor={ids.desde}>Desde</label>
          <input id={ids.desde} type="date" value={borrador.desde} aria-invalid={errorFechas ? true : undefined}
                 aria-describedby={errorFechas ? ids.errorFechas : undefined}
                 onChange={(e) => setBorrador({ ...borrador, desde: e.target.value })} />
        </div>
        <div className="auditoria__campo">
          <label htmlFor={ids.hasta}>Hasta</label>
          <input id={ids.hasta} type="date" value={borrador.hasta} aria-invalid={errorFechas ? true : undefined}
                 aria-describedby={errorFechas ? ids.errorFechas : undefined}
                 onChange={(e) => setBorrador({ ...borrador, hasta: e.target.value })} />
        </div>
        <div className="auditoria__botones">
          <button className="boton boton--secundario" type="submit">Filtrar</button>
          {conFiltros && <button className="boton boton--neutro" type="button" onClick={limpiar}>Limpiar filtros</button>}
        </div>
        <label className="auditoria__interruptor" htmlFor={ids.pruebas}>
          <input id={ids.pruebas} type="checkbox" role="switch" checked={actual.pruebas}
                 onChange={(e) => alternarPruebas(e.target.checked)} />
          <span>Incluir consultas de prueba</span>
        </label>
        <p className="texto-tenue auditoria__ayuda">
          Las fechas son días de Lima. Las consultas de prueba (respuestas simuladas, no clínicas) se ocultan salvo que
          active el interruptor; nunca cuentan en los indicadores.
        </p>
        {errorFechas && <p id={ids.errorFechas} className="campo__error auditoria__error" role="alert">{errorFechas}</p>}
      </form>

      <div className="tarjeta tarjeta--ancha">
        <h2 className="auditoria__subtitulo-lista">Consultas</h2>
        {carga.estado === "cargando" ? (
          <p className="vacio" role="status" aria-live="polite">Cargando consultas…</p>
        ) : carga.estado === "error" ? (
          <div className="alerta alerta--error" role="alert">
            <p className="alerta__texto">No se pudieron cargar las consultas. {carga.mensaje}</p>
            <button type="button" className="boton boton--secundario boton--chico" onClick={() => setIntento((n) => n + 1)}>
              Reintentar
            </button>
          </div>
        ) : carga.pagina.consultas.length === 0 && carga.pagina.total > 0 ? (
          <div className="vacio" role="status">
            <p>No hay consultas en esta página.</p>
            <button type="button" className="boton boton--neutro boton--chico" onClick={() => irA(1)}>Ir a la primera página</button>
          </div>
        ) : carga.pagina.consultas.length === 0 ? (
          <p className="vacio" role="status">
            {conFiltros ? "No hay consultas con esos filtros." : "Aún no hay consultas registradas."}
          </p>
        ) : (
          <>
            <p className="texto-tenue auditoria__conteo" role="status">{rango(carga.pagina)}</p>
            {angosto ? <Tarjetas consultas={carga.pagina.consultas} /> : <Tabla consultas={carga.pagina.consultas} />}
            <Paginacion pagina={actual.pagina} total={carga.pagina.total} irA={irA} />
          </>
        )}
      </div>
    </section>
  );
}

function rango(p: PaginaAuditoria): string {
  const desde = p.desplazamiento + 1;
  const hasta = p.desplazamiento + p.consultas.length;
  return `Mostrando ${desde} a ${hasta} de ${p.total} ${p.total === 1 ? "consulta" : "consultas"}`;
}

function Estado({ c }: { c: ConsultaAuditada }) {
  return (
    <span className="auditoria__etiquetas">
      <EtiquetaEstadoConsulta estado={c.estado} />
      {c.modo_prueba && <span className="etiqueta etiqueta--prueba">Prueba</span>}
    </span>
  );
}

function Intentos({ c }: { c: ConsultaAuditada }) {
  return c.con_reintento
    ? <span className="etiqueta etiqueta--reintento">Con reintento</span>
    : <span>{c.numero_intentos === 0 ? "Sin intentos" : `${c.numero_intentos} intento`}</span>;
}

function Tokens({ c }: { c: ConsultaAuditada }) {
  return <>{entero(c.tokens_total)}</>;
}

// El detalle recibe la dirección actual (filtros y página) para el enlace de vuelta.
function useEnlaceDetalle() {
  const { search } = useLocation();
  return (c: ConsultaAuditada) => ({
    to: `/admin/auditoria/${c.id_consulta}`,
    state: { volver: search },
    "aria-label": `Ver el detalle de la consulta de ${c.nombre_usuario} del ${fechaHora(c.fecha_hora_inicio)}`,
  });
}

function Tabla({ consultas }: { consultas: ConsultaAuditada[] }) {
  const enlace = useEnlaceDetalle();
  return (
    <div className="tabla-contenedor auditoria__tabla" tabIndex={0} role="region" aria-label="Consultas auditadas">
      <table className="tabla tabla--compacta">
        <thead>
          <tr>
            <th scope="col">Fecha</th>
            <th scope="col">Usuario</th>
            <th scope="col">Resultado</th>
            <th scope="col">Intentos</th>
            <th scope="col">Tiempo</th>
            <th scope="col">Modelo</th>
            <th scope="col">Tokens</th>
            <th scope="col">Costo</th>
            <th scope="col"><span className="solo-lectores">Acciones</span></th>
          </tr>
        </thead>
        <tbody>
          {consultas.map((c) => (
            <tr key={c.id_consulta}>
              <td className="auditoria__fecha">{fechaHora(c.fecha_hora_inicio)}</td>
              <td className="auditoria__usuario">{c.nombre_usuario}</td>
              <td><Estado c={c} /></td>
              <td><Intentos c={c} /></td>
              <td className="auditoria__numero">{latencia(c.latencia_total_ms)}</td>
              <td className="auditoria__modelo">{modeloYPrompt(c.modelo_llm, c.version_prompt)}</td>
              <td className="auditoria__numero"><Tokens c={c} /></td>
              <td className="auditoria__numero">{usd(c.costo_usd, 3)}</td>
              <td className="auditoria__ver">
                <Link className="boton boton--secundario boton--chico" {...enlace(c)}>Ver</Link>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Tarjetas({ consultas }: { consultas: ConsultaAuditada[] }) {
  const enlace = useEnlaceDetalle();
  return (
    <ul className="auditoria__tarjetas-lista" aria-label="Consultas auditadas">
      {consultas.map((c) => (
        <li key={c.id_consulta} className="auditoria__tarjeta">
          <p className="auditoria__tarjeta-cabecera">
            <span className="auditoria__fecha">{fechaHora(c.fecha_hora_inicio)}</span>
            <Estado c={c} />
          </p>
          <dl className="auditoria__tarjeta-datos">
            <div><dt>Usuario</dt><dd className="auditoria__usuario">{c.nombre_usuario}</dd></div>
            <div><dt>Intentos</dt><dd><Intentos c={c} /></dd></div>
            <div><dt>Tiempo</dt><dd>{latencia(c.latencia_total_ms)}</dd></div>
            <div><dt>Modelo</dt><dd className="auditoria__modelo">{modeloYPrompt(c.modelo_llm, c.version_prompt)}</dd></div>
            <div><dt>Tokens</dt><dd><Tokens c={c} /></dd></div>
            <div><dt>Costo</dt><dd>{usd(c.costo_usd, 3)}</dd></div>
          </dl>
          <Link className="boton boton--secundario auditoria__tarjeta-ver" {...enlace(c)}>Ver detalle</Link>
        </li>
      ))}
    </ul>
  );
}

function Paginacion({ pagina, total, irA }: { pagina: number; total: number; irA: (pagina: number) => void }) {
  const paginas = Math.max(1, Math.ceil(total / POR_PAGINA));
  if (paginas <= 1) return null;
  return (
    <nav className="auditoria__paginacion" aria-label="Paginación de la auditoría">
      <button type="button" className="boton boton--neutro" disabled={pagina <= 1} onClick={() => irA(pagina - 1)}>
        Anterior
      </button>
      <span>Página {Math.min(pagina, paginas)} de {paginas}</span>
      <button type="button" className="boton boton--neutro" disabled={pagina >= paginas} onClick={() => irA(pagina + 1)}>
        Siguiente
      </button>
    </nav>
  );
}
