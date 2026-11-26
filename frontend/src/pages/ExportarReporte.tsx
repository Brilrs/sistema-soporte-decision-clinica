// M09 · Exportar reporte (HU10, RF6), ruta /consultas/:id/reporte, permiso EXPORTAR_REPORTE.
// Usa las rutas de la parte C1 (docs/contrato_reportes.md):
// - el GET de la consulta y la ficha dan los datos de arriba (paciente, fecha, estado);
// - la vista previa se pide al cambiar el destino o las secciones, con una espera corta;
// - «Generar reporte (PDF)» hace un solo POST, que emite un reporte con su número. «Descargar PDF» y
//   «Abrir para imprimir» usan ese mismo PDF (blob en memoria), sin otro POST. El blob se libera al
//   generar otro o al salir de la pantalla; nada se guarda en localStorage, sessionStorage ni caché;
// - la lista de reportes emitidos se actualiza después de generar.
// Solo las consultas con resultado (VERIFICADA o EVIDENCIA_INSUFICIENTE) se exportan.
import { useCallback, useEffect, useId, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ErrorApi, mensajeError } from "../api/cliente";
import { consultasApi } from "../api/consultas";
import { pacientesApi, type Ficha } from "../api/pacientes";
import { reportesApi } from "../api/reportes";
import type { ResultadoConsulta } from "../api/tipos_consulta";
import {
  SECCIONES_OBLIGATORIAS,
  SECCIONES_POR_DESTINO,
  type DestinoReporte,
  type ReporteListado,
  type SeccionReporte,
  type VistaPreviaReporte,
} from "../api/tipos_reporte";
import { EtiquetaEstadoConsulta } from "../components/Etiquetas";
import Migas from "../components/Migas";
import DocumentoReporte from "../components/reporte/DocumentoReporte";
import ListaReportes from "../components/reporte/ListaReportes";
import {
  AVISO_PRUEBA,
  AVISO_REVISION,
  AYUDA_GENERADO,
  DESTINOS,
  FRASES_FINALES,
  SECCIONES,
} from "../components/reporte/textos";
import { ESTADOS_CONSULTA, fechaHora } from "../utilidades/formato";
import { useTituloPagina } from "../utilidades/useTituloPagina";

export const ESPERA_VISTA_PREVIA_MS = 350;
export const ESTADOS_CON_RESULTADO = ["VERIFICADA", "EVIDENCIA_INSUFICIENTE"];
const ORDEN_DESTINOS: DestinoReporte[] = ["EXPEDIENTE", "CUIDADOR"];

// Opcionales elegidas por destino: al cambiar de destino se conserva lo elegido en cada uno.
const opcionales = (d: DestinoReporte) => SECCIONES_POR_DESTINO[d].filter((s) => !SECCIONES_OBLIGATORIAS.includes(s));
const inicial = (): Record<DestinoReporte, SeccionReporte[]> => ({ EXPEDIENTE: opcionales("EXPEDIENTE"), CUIDADOR: opcionales("CUIDADOR") });

type Problema = { codigo: number | null; mensaje: string };
const problema = (e: unknown): Problema => ({ codigo: e instanceof ErrorApi ? e.estado : null, mensaje: mensajeError(e) });
type Vista = { estado: "cargando" } | { estado: "error"; problema: Problema } | { estado: "lista"; vista: VistaPreviaReporte };
type Generado = { numero: string; hash: string; url: string };

export default function ExportarReporte() {
  useTituloPagina("Exportar reporte");
  const { id = "" } = useParams();
  const [consulta, setConsulta] = useState<ResultadoConsulta | null>(null);
  const [ficha, setFicha] = useState<Ficha | null>(null);
  const [errorConsulta, setErrorConsulta] = useState<Problema | null>(null);
  const [destino, setDestino] = useState<DestinoReporte>("EXPEDIENTE");
  const [elegidas, setElegidas] = useState(inicial);
  const [vista, setVista] = useState<Vista>({ estado: "cargando" });
  // Última vista previa recibida: mantiene los avisos visibles mientras se pide la siguiente.
  const [ultimaVista, setUltimaVista] = useState<VistaPreviaReporte | null>(null);
  const [intentoVista, setIntentoVista] = useState(0);
  const [sinResultado, setSinResultado] = useState<string | null>(null);
  const [generando, setGenerando] = useState(false);
  const enCurso = useRef(false);
  const [generado, setGenerado] = useState<Generado | null>(null);
  const [errorGenerar, setErrorGenerar] = useState<string | null>(null);
  const [reportes, setReportes] = useState<ReporteListado[] | null>(null);
  const [errorLista, setErrorLista] = useState<string | null>(null);
  const [intentoLista, setIntentoLista] = useState(0);
  const idDestino = useId();
  const idSecciones = useId();
  const idEstadoGenerar = useId();

  const secciones: SeccionReporte[] = SECCIONES_POR_DESTINO[destino].filter(
    (s) => SECCIONES_OBLIGATORIAS.includes(s) || elegidas[destino].includes(s));
  const clave = `${destino}:${secciones.join(",")}`;
  const exportable = consulta !== null && ESTADOS_CON_RESULTADO.includes(consulta.estado) && !sinResultado;

  // Datos de la consulta (estado, fecha, modo de prueba) y del paciente.
  useEffect(() => {
    const control = new AbortController();
    consultasApi.resultado(id, control.signal)
      .then((r) => {
        setConsulta(r);
        if (!ESTADOS_CON_RESULTADO.includes(r.estado)) setSinResultado(mensajeSinResultado(r.estado));
        pacientesApi.ficha(r.id_paciente).then(setFicha).catch(() => setFicha(null));
      })
      .catch((e) => !control.signal.aborted && setErrorConsulta(problema(e)));
    return () => control.abort();
  }, [id]);

  // Vista previa: espera corta después del último cambio y cancela la anterior.
  useEffect(() => {
    if (!consulta || !exportable) return;
    const control = new AbortController();
    setVista({ estado: "cargando" });
    const t = setTimeout(() => {
      reportesApi.vistaPrevia(id, destino, secciones, control.signal)
        .then((v) => {
          setVista({ estado: "lista", vista: v });
          setUltimaVista(v);
        })
        .catch((e) => {
          if (control.signal.aborted) return;
          const p = problema(e);
          if (p.codigo === 409) setSinResultado(p.mensaje);
          setVista({ estado: "error", problema: p });
        });
    }, ESPERA_VISTA_PREVIA_MS);
    return () => {
      clearTimeout(t);
      control.abort();
    };
    // clave resume el destino y las secciones.
  }, [id, consulta, exportable, clave, intentoVista]);

  // Reportes emitidos de la consulta.
  useEffect(() => {
    if (!consulta) return;
    const control = new AbortController();
    setErrorLista(null);
    reportesApi.listar(id, control.signal)
      .then(setReportes)
      .catch((e) => !control.signal.aborted && setErrorLista(mensajeError(e)));
    return () => control.abort();
  }, [id, consulta, intentoLista]);

  // El PDF generado vive en un blob de la página: se libera al generar otro o al salir.
  useEffect(() => {
    const url = generado?.url;
    return () => {
      if (url) URL.revokeObjectURL(url);
    };
  }, [generado]);

  const generar = useCallback(async () => {
    if (enCurso.current || !exportable) return;
    enCurso.current = true;
    setGenerando(true);
    setErrorGenerar(null);
    try {
      const r = await reportesApi.generar(id, destino, secciones);
      setGenerado({ numero: r.numero, hash: r.hash, url: URL.createObjectURL(r.pdf) });
      setIntentoLista((n) => n + 1);
    } catch (e) {
      const p = problema(e);
      if (p.codigo === 409) setSinResultado(p.mensaje);
      setErrorGenerar(p.mensaje);
    } finally {
      enCurso.current = false;
      setGenerando(false);
    }
  }, [id, destino, secciones, exportable]);

  function alternar(s: SeccionReporte, marcada: boolean) {
    if (SECCIONES_OBLIGATORIAS.includes(s)) return;
    setElegidas((actual) => ({
      ...actual,
      [destino]: marcada ? [...actual[destino], s] : actual[destino].filter((x) => x !== s),
    }));
  }

  if (errorConsulta) {
    return (
      <section className="reporte">
        <h1>Exportar reporte</h1>
        <div className="alerta alerta--error" role="alert">
          <p className="alerta__texto">{errorConsulta.mensaje}</p>
          {errorConsulta.codigo === 404 && <Link to="/consultas">Ir al historial de consultas</Link>}
        </div>
      </section>
    );
  }
  if (!consulta) return <p className="cargando">Cargando…</p>;

  const modoPrueba = consulta.modo_prueba || !!ultimaVista?.modo_prueba;
  const enRevision = destino === "CUIDADOR" && ultimaVista?.destino === "CUIDADOR" && ultimaVista.revision_pendiente;
  const estadoGenerar = generando ? "Generando el reporte…" : generado ? `Reporte ${generado.numero} generado.` : "";

  return (
    <section className="reporte">
      <Migas items={[
        { texto: "Pacientes", ruta: "/pacientes" },
        ...(ficha ? [{ texto: ficha.nombres_apellidos, ruta: `/pacientes/${ficha.id_paciente}/historial` }] : []),
        { texto: "Resultado de la consulta", ruta: `/consultas/${consulta.id_consulta}` },
        { texto: "Exportar reporte" },
      ]} />
      <div className="encabezado-pagina">
        <div className="reporte__titulo">
          <h1>Exportar reporte</h1>
          <p className="texto-tenue reporte__datos">
            {ficha && <><strong>{ficha.nombres_apellidos}</strong> · HC {ficha.numero_hc} · </>}
            Consulta del {consulta.fecha_hora_inicio ? fechaHora(consulta.fecha_hora_inicio) : "-"} ·{" "}
            <EtiquetaEstadoConsulta estado={consulta.estado} />
          </p>
        </div>
        <Link className="boton boton--neutro boton--auto" to={`/consultas/${consulta.id_consulta}`}>Volver al resultado</Link>
      </div>

      {modoPrueba && <p className="alerta alerta--error reporte__aviso" role="note"><strong>{AVISO_PRUEBA}</strong></p>}
      {enRevision && <p className="alerta alerta--aviso reporte__aviso" role="note"><strong>{AVISO_REVISION}</strong></p>}
      {sinResultado && <p className="alerta alerta--aviso reporte__aviso" role="alert">{sinResultado}</p>}

      <div className="reporte__cuerpo">
        <form className="tarjeta reporte__opciones" onSubmit={(e) => { e.preventDefault(); void generar(); }}
              aria-label="Opciones del reporte">
          <fieldset className="reporte__grupo" aria-describedby={`${idDestino}-ayuda`}>
            <legend>Destino</legend>
            {ORDEN_DESTINOS.map((d) => (
              <label key={d} className="reporte__opcion">
                <input type="radio" name="destino" value={d} checked={destino === d} disabled={!exportable}
                       onChange={() => setDestino(d)} />
                <span>{DESTINOS[d].etiqueta}</span>
              </label>
            ))}
            <p id={`${idDestino}-ayuda`} className="texto-tenue reporte__ayuda">{DESTINOS[destino].ayuda}</p>
          </fieldset>

          <fieldset className="reporte__grupo" aria-describedby={`${idSecciones}-ayuda`}>
            <legend>Incluir en el reporte</legend>
            {SECCIONES_POR_DESTINO[destino].map((s) => {
              const obligatoria = SECCIONES_OBLIGATORIAS.includes(s);
              return (
                <label key={s} className="reporte__opcion">
                  <input type="checkbox" checked={obligatoria || elegidas[destino].includes(s)}
                         disabled={obligatoria || !exportable} onChange={(e) => alternar(s, e.target.checked)} />
                  <span>{SECCIONES[destino][s]}{obligatoria && <>{" "}<span className="reporte__obligatoria">(obligatoria)</span></>}</span>
                </label>
              );
            })}
            <label className="reporte__opcion">
              <input type="checkbox" checked disabled readOnly />
              <span>Frase «{FRASES_FINALES[destino].replace(/\.$/, "")}»{" "}<span className="reporte__obligatoria">(obligatoria)</span></span>
            </label>
            <p id={`${idSecciones}-ayuda`} className="texto-tenue reporte__ayuda">
              Las obligatorias van siempre. La vista previa se actualiza al cambiar las opciones.
            </p>
          </fieldset>

          <button type="submit" className="boton boton--primario" disabled={!exportable || generando}
                  aria-describedby={idEstadoGenerar}>
            {generando ? "Generando…" : "Generar reporte (PDF)"}
          </button>
          <p id={idEstadoGenerar} className="reporte__estado" role="status" aria-live="polite">{estadoGenerar}</p>
          {errorGenerar && <p className="alerta alerta--error" role="alert">No se pudo generar el reporte. {errorGenerar}</p>}

          {generado && (
            <div className="reporte__generado" aria-labelledby="titulo-generado">
              <h2 id="titulo-generado" className="reporte__generado-titulo">Reporte {generado.numero}</h2>
              <p className="reporte__huella"><span className="texto-tenue">SHA-256: </span><code>{generado.hash}</code></p>
              <div className="reporte__acciones">
                <a className="boton boton--secundario" href={generado.url} download={`${generado.numero}.pdf`}>Descargar PDF</a>
                <button type="button" className="boton boton--neutro" onClick={() => window.open(generado.url, "_blank")}>
                  Abrir para imprimir
                </button>
              </div>
              <p className="texto-tenue reporte__ayuda">{AYUDA_GENERADO}</p>
            </div>
          )}
        </form>

        <section className="tarjeta reporte__vista" aria-labelledby="titulo-vista-previa" aria-busy={vista.estado === "cargando"}>
          <h2 id="titulo-vista-previa">Vista previa</h2>
          {!exportable ? (
            <p className="vacio">No hay vista previa: la consulta no tiene un resultado para exportar.</p>
          ) : vista.estado === "cargando" ? (
            <p className="vacio" role="status">Actualizando la vista previa…</p>
          ) : vista.estado === "error" ? (
            <div className="alerta alerta--error" role="alert">
              <p className="alerta__texto">No se pudo cargar la vista previa. {vista.problema.mensaje}</p>
              <button type="button" className="boton boton--secundario boton--chico" onClick={() => setIntentoVista((n) => n + 1)}>
                Reintentar
              </button>
            </div>
          ) : (
            <DocumentoReporte vista={vista.vista} />
          )}
        </section>
      </div>

      <ListaReportes reportes={reportes} error={errorLista} reintentar={() => setIntentoLista((n) => n + 1)} />
    </section>
  );
}

function mensajeSinResultado(estado: string): string {
  return `Esta consulta no tiene un resultado para exportar (estado: ${ESTADOS_CONSULTA[estado] ?? estado}). Solo se exportan las consultas verificadas o con evidencia insuficiente.`;
}
