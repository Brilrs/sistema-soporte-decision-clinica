// «Historial de consultas» (/consultas, P10, Sprint 3 parte B): las consultas clínicas del usuario
// autenticado de todos sus pacientes (GET /api/consultas; el backend nunca lista las de otro), de la
// más reciente a la más antigua, con filtros de estado y fechas (días de Lima) y paginación. Desde
// 800 px es una tabla compacta; por debajo, tarjetas apiladas (solo se monta una de las dos). Cada
// consulta abre su resultado (/consultas/:id). «Nueva consulta» lleva al buscador de pacientes
// (/consultas/nueva), que antes estaba en esta ruta. Los filtros y la página van en la dirección
// (sin datos del paciente) para conservarlos al volver del resultado.
import { useEffect, useId, useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { mensajeError } from "../api/cliente";
import { consultasApi } from "../api/consultas";
import type { ConsultaPropia, EstadoConsulta, PaginaConsultas } from "../api/tipos_consulta";
import { EtiquetaClasificacion, EtiquetaEstadoConsulta, EtiquetaRiesgo } from "../components/Etiquetas";
import { useAnchoAngosto } from "../components/Layout";
import { ESTADOS_CONSULTA, edad, fechaHora } from "../utilidades/formato";
import { useTituloPagina } from "../utilidades/useTituloPagina";

export const POR_PAGINA = 20;
const FECHA = /^\d{4}-\d{2}-\d{2}$/;

type Filtros = { estado: EstadoConsulta | ""; desde: string; hasta: string };

// Lee los filtros y la página de la dirección, descartando lo que no sea válido.
function leerParametros(p: URLSearchParams): Filtros & { pagina: number } {
  const estado = p.get("estado") ?? "";
  const desde = p.get("desde") ?? "";
  const hasta = p.get("hasta") ?? "";
  const pagina = Number(p.get("pagina") ?? "1");
  return {
    estado: estado in ESTADOS_CONSULTA ? (estado as EstadoConsulta) : "",
    desde: FECHA.test(desde) ? desde : "",
    hasta: FECHA.test(hasta) ? hasta : "",
    pagina: Number.isInteger(pagina) && pagina >= 1 ? pagina : 1,
  };
}

function escribirParametros(f: Filtros, pagina: number): URLSearchParams {
  const p = new URLSearchParams();
  if (f.estado) p.set("estado", f.estado);
  if (f.desde) p.set("desde", f.desde);
  if (f.hasta) p.set("hasta", f.hasta);
  if (pagina > 1) p.set("pagina", String(pagina));
  return p;
}

type Carga = { estado: "cargando" } | { estado: "error"; mensaje: string } | { estado: "listo"; pagina: PaginaConsultas };

export default function HistorialConsultas() {
  useTituloPagina("Historial de consultas");
  const [parametros, setParametros] = useSearchParams();
  const actual = leerParametros(parametros);
  const clave = escribirParametros(actual, actual.pagina).toString();
  const [borrador, setBorrador] = useState<Filtros>({ estado: actual.estado, desde: actual.desde, hasta: actual.hasta });
  const [errorFechas, setErrorFechas] = useState<string | null>(null);
  const [carga, setCarga] = useState<Carga>({ estado: "cargando" });
  const [intento, setIntento] = useState(0);
  const angosto = useAnchoAngosto();
  const ids = { estado: useId(), desde: useId(), hasta: useId(), errorFechas: useId() };
  const conFiltros = Boolean(actual.estado || actual.desde || actual.hasta);

  // El borrador sigue a la dirección (al volver atrás o al limpiar).
  useEffect(() => {
    setBorrador({ estado: actual.estado, desde: actual.desde, hasta: actual.hasta });
    // clave resume los filtros y la página de la dirección.
  }, [clave]);

  useEffect(() => {
    const control = new AbortController();
    setCarga({ estado: "cargando" });
    consultasApi.misConsultas({
      estado: actual.estado, fecha_desde: actual.desde, fecha_hasta: actual.hasta,
      limite: POR_PAGINA, desplazamiento: (actual.pagina - 1) * POR_PAGINA,
    }, control.signal)
      .then((pagina) => setCarga({ estado: "listo", pagina }))
      .catch((e) => {
        if (!control.signal.aborted) setCarga({ estado: "error", mensaje: mensajeError(e) });
      });
    return () => control.abort();
  }, [clave, intento]);

  function filtrar(e: FormEvent) {
    e.preventDefault();
    if (borrador.desde && borrador.hasta && borrador.desde > borrador.hasta) {
      setErrorFechas("La fecha «Hasta» no puede ser anterior a «Desde».");
      return;
    }
    setErrorFechas(null);
    setParametros(escribirParametros(borrador, 1));
  }

  function limpiar() {
    setErrorFechas(null);
    setParametros(new URLSearchParams());
  }

  const irA = (pagina: number) => setParametros(escribirParametros(actual, pagina));

  return (
    <section className="consultas-propias">
      <div className="encabezado-pagina">
        <div className="consultas-propias__titulo">
          <h1>Historial de consultas</h1>
          <p className="texto-tenue">
            Las consultas clínicas que usted realizó, de la más reciente a la más antigua. Solo se muestran las suyas.
          </p>
        </div>
        <Link className="boton boton--primario boton--auto" to="/consultas/nueva">Nueva consulta</Link>
      </div>

      <form className="tarjeta tarjeta--ancha consultas-propias__filtros" onSubmit={filtrar} aria-label="Filtros de las consultas"
            noValidate>
        <div className="consultas-propias__campo">
          <label htmlFor={ids.estado}>Estado</label>
          <select id={ids.estado} value={borrador.estado}
                  onChange={(e) => setBorrador({ ...borrador, estado: e.target.value as Filtros["estado"] })}>
            <option value="">Todos</option>
            {Object.entries(ESTADOS_CONSULTA).map(([valor, texto]) => <option key={valor} value={valor}>{texto}</option>)}
          </select>
        </div>
        <div className="consultas-propias__campo">
          <label htmlFor={ids.desde}>Desde</label>
          <input id={ids.desde} type="date" value={borrador.desde} aria-invalid={errorFechas ? true : undefined}
                 aria-describedby={errorFechas ? ids.errorFechas : undefined}
                 onChange={(e) => setBorrador({ ...borrador, desde: e.target.value })} />
        </div>
        <div className="consultas-propias__campo">
          <label htmlFor={ids.hasta}>Hasta</label>
          <input id={ids.hasta} type="date" value={borrador.hasta} aria-invalid={errorFechas ? true : undefined}
                 aria-describedby={errorFechas ? ids.errorFechas : undefined}
                 onChange={(e) => setBorrador({ ...borrador, hasta: e.target.value })} />
        </div>
        <div className="consultas-propias__botones">
          <button className="boton boton--secundario" type="submit">Filtrar</button>
          {conFiltros && <button className="boton boton--neutro" type="button" onClick={limpiar}>Limpiar filtros</button>}
        </div>
        {errorFechas && <p id={ids.errorFechas} className="campo__error consultas-propias__error" role="alert">{errorFechas}</p>}
      </form>

      <div className="tarjeta tarjeta--ancha">
        {carga.estado === "cargando" ? (
          <p className="vacio" role="status">Cargando consultas…</p>
        ) : carga.estado === "error" ? (
          <div className="alerta alerta--error" role="alert">
            <p>No se pudieron cargar las consultas. {carga.mensaje}</p>
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
            {conFiltros ? "No hay consultas con esos filtros." : "Aún no realizó consultas clínicas. Use «Nueva consulta» para iniciar una."}
          </p>
        ) : (
          <>
            <p className="texto-tenue consultas-propias__conteo" role="status">
              {rango(carga.pagina)}
            </p>
            {angosto ? <Tarjetas consultas={carga.pagina.consultas} /> : <Tabla consultas={carga.pagina.consultas} />}
            <Paginacion pagina={actual.pagina} total={carga.pagina.total} irA={irA} />
          </>
        )}
      </div>
    </section>
  );
}

function rango(p: PaginaConsultas): string {
  const desde = p.desplazamiento + 1;
  const hasta = p.desplazamiento + p.consultas.length;
  return `Mostrando ${desde} a ${hasta} de ${p.total} ${p.total === 1 ? "consulta" : "consultas"}`;
}

function Estado({ c }: { c: ConsultaPropia }) {
  return (
    <>
      <EtiquetaEstadoConsulta estado={c.estado} />
      {c.modo_prueba && <span className="etiqueta etiqueta--prueba">Prueba</span>}
    </>
  );
}

function Pregunta({ texto }: { texto: string | null }) {
  return texto
    ? <span className="consultas-propias__pregunta">{texto}</span>
    : <span className="texto-tenue">Sin pregunta registrada</span>;
}

function enlaceVer(c: ConsultaPropia): { to: string; "aria-label": string } {
  return { to: `/consultas/${c.id_consulta}`, "aria-label": `Ver la consulta de ${c.nombres_apellidos} del ${fechaHora(c.fecha_hora_inicio)}` };
}

function Tabla({ consultas }: { consultas: ConsultaPropia[] }) {
  return (
    <div className="tabla-contenedor consultas-propias__tabla" tabIndex={0} role="region" aria-label="Consultas realizadas">
      <table className="tabla tabla--compacta">
        <thead>
          <tr>
            <th scope="col">Fecha</th>
            <th scope="col">Paciente</th>
            <th scope="col">Clasificación y riesgo</th>
            <th scope="col">Consulta</th>
            <th scope="col">Estado</th>
            <th scope="col"><span className="solo-lectores">Acciones</span></th>
          </tr>
        </thead>
        <tbody>
          {consultas.map((c) => (
            <tr key={c.id_consulta}>
              <td className="consultas-propias__fecha">{fechaHora(c.fecha_hora_inicio)}</td>
              <td>
                <span className="consultas-propias__paciente">
                  <strong>{c.nombres_apellidos}</strong>
                  <span className="texto-tenue">HC {c.numero_hc} · {edad(c.edad_meses)}</span>
                </span>
              </td>
              <td>
                <span className="consultas-propias__etiquetas">
                  <EtiquetaClasificacion categoria={c.categoria} sinTexto="Sin clasificación" />
                  {c.nivel_riesgo && <EtiquetaRiesgo nivel={c.nivel_riesgo} />}
                </span>
              </td>
              <td className="consultas-propias__pregunta-celda"><Pregunta texto={c.pregunta} /></td>
              <td><Estado c={c} /></td>
              <td className="consultas-propias__ver">
                <Link className="boton boton--secundario boton--chico" {...enlaceVer(c)}>Ver</Link>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Tarjetas({ consultas }: { consultas: ConsultaPropia[] }) {
  return (
    <ul className="consultas-propias__tarjetas" aria-label="Consultas realizadas">
      {consultas.map((c) => (
        <li key={c.id_consulta} className="consultas-propias__tarjeta">
          <p className="consultas-propias__tarjeta-cabecera">
            <span className="consultas-propias__fecha">{fechaHora(c.fecha_hora_inicio)}</span>
            <span><Estado c={c} /></span>
          </p>
          <p className="consultas-propias__paciente">
            <strong>{c.nombres_apellidos}</strong>
            <span className="texto-tenue">HC {c.numero_hc} · {edad(c.edad_meses)}</span>
          </p>
          <p className="consultas-propias__etiquetas">
            <EtiquetaClasificacion categoria={c.categoria} sinTexto="Sin clasificación" />
            {c.nivel_riesgo && <EtiquetaRiesgo nivel={c.nivel_riesgo} />}
          </p>
          <p className="consultas-propias__tarjeta-pregunta"><Pregunta texto={c.pregunta} /></p>
          <Link className="boton boton--secundario consultas-propias__tarjeta-ver" {...enlaceVer(c)}>Ver resultado</Link>
        </li>
      ))}
    </ul>
  );
}

function Paginacion({ pagina, total, irA }: { pagina: number; total: number; irA: (pagina: number) => void }) {
  const paginas = Math.max(1, Math.ceil(total / POR_PAGINA));
  if (paginas <= 1) return null;
  return (
    <nav className="consultas-propias__paginacion" aria-label="Paginación de las consultas">
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
