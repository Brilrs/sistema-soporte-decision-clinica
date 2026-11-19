// M11 · Base de conocimiento (HU12). Solo para el permiso ADMINISTRAR_GUIAS: tabla de guías,
// «Cargar guía» (solo nivel 2), avance de la indexación consultado cada 3 s mientras haya trabajos
// activos, detalle de cada guía, «Reintentar» para las que terminaron en error y «Retirar» (HU17,
// Sprint 3 parte F) para las vigentes. Sin datos clínicos. Contrato: docs/contrato_conocimiento.md.
import { useCallback, useEffect, useId, useRef, useState } from "react";
import { mensajeError } from "../api/cliente";
import { conocimientoApi, type Documento, type DocumentoCreado, type Trabajo } from "../api/conocimiento";
import { useAuth } from "../auth/AuthContext";
import AvanceIndexacion from "../components/conocimiento/AvanceIndexacion";
import TablaGuias from "../components/conocimiento/TablaGuias";
import { NOTA_OBSOLETAS, NOTA_RETIRAR, NOTA_RETIRAR_SIN_PERMISO } from "../components/conocimiento/textos";
import { useTrabajosActivos } from "../components/conocimiento/useTrabajosActivos";
import VentanaCargarGuia from "../components/conocimiento/VentanaCargarGuia";
import VentanaDetalleGuia from "../components/conocimiento/VentanaDetalleGuia";
import VentanaRetirarGuia from "../components/conocimiento/VentanaRetirarGuia";
import { useTituloPagina } from "../utilidades/useTituloPagina";

export default function BaseConocimiento() {
  useTituloPagina("Base de conocimiento");
  const [documentos, setDocumentos] = useState<Documento[] | null>(null);
  const [errorCarga, setErrorCarga] = useState<string | null>(null);
  const [cargarAbierta, setCargarAbierta] = useState(false);
  const [detalle, setDetalle] = useState<Documento | null>(null);
  const [terminados, setTerminados] = useState<string[]>([]); // documentos cuyo trabajo acaba de terminar
  const [reintentando, setReintentando] = useState<string | null>(null);
  const [aviso, setAviso] = useState<{ tipo: "exito" | "error"; texto: string } | null>(null);
  const botonCargar = useRef<HTMLButtonElement>(null);
  const botonVer = useRef<HTMLButtonElement | null>(null);
  const botonRetirar = useRef<HTMLButtonElement | null>(null);
  const [retiro, setRetiro] = useState<Documento | null>(null);
  const idNotaRetirar = useId();
  const { tienePermiso } = useAuth();
  const puedeRetirar = tienePermiso("ADMINISTRAR_GUIAS");

  const cargarDocumentos = useCallback(async () => {
    setErrorCarga(null);
    try {
      setDocumentos(await conocimientoApi.listar());
    } catch (e) {
      setErrorCarga(mensajeError(e));
    }
  }, []);
  useEffect(() => {
    void cargarDocumentos();
  }, [cargarDocumentos]);

  // Al terminar un trabajo se refresca la tabla y se muestra su resultado en la tarjeta de avance.
  const alTerminar = useCallback((fin: Trabajo[]) => {
    setTerminados((previos) => [...new Set([...previos, ...fin.map((t) => t.id_documento)])]);
    void cargarDocumentos();
  }, [cargarDocumentos]);
  const { trabajos, actualizar } = useTrabajosActivos(alTerminar);

  // Resultado de un trabajo terminado, con el último trabajo de la tabla ya refrescada (si aún no
  // se refrescó o el documento volvió a la cola, no se muestra).
  const activos = new Set(trabajos.map((t) => t.id_documento));
  const resultados = (documentos ?? []).filter((d) => terminados.includes(d.id_documento) && !activos.has(d.id_documento)
    && (d.ultimo_trabajo?.estado === "COMPLETADO" || d.ultimo_trabajo?.estado === "ERROR"));

  function alCargar(creado: DocumentoCreado) {
    setCargarAbierta(false);
    setAviso({ tipo: "exito", texto: `«${creado.documento.titulo}» se cargó y quedó en cola para indexarse.` });
    void cargarDocumentos();
    void actualizar();
  }

  async function reintentar(doc: Documento) {
    setReintentando(doc.id_documento);
    setAviso(null);
    try {
      const { trabajo } = await conocimientoApi.reintentar(doc.id_documento);
      setTerminados((t) => t.filter((id) => id !== doc.id_documento));
      setAviso({ tipo: "exito", texto: trabajo.tipo === "RETIRO" ? `Se volvió a poner en cola el retiro de «${doc.titulo}».`
        : `Se volvió a poner en cola la indexación de «${doc.titulo}».` });
      await Promise.all([cargarDocumentos(), actualizar()]);
    } catch (e) {
      setAviso({ tipo: "error", texto: `No se pudo reintentar «${doc.titulo}»: ${mensajeError(e)}` });
    } finally {
      setReintentando(null);
    }
  }

  function ver(doc: Documento, boton: HTMLButtonElement) {
    botonVer.current = boton;
    setDetalle(doc);
  }

  function abrirRetiro(doc: Documento, boton: HTMLButtonElement) {
    botonRetirar.current = boton;
    setAviso(null);
    setRetiro(doc);
  }

  // Tras retirar, el foco vuelve a «Cargar guía»: la fila ya no tiene un «Retirar» activo.
  function alRetirar(creado: DocumentoCreado) {
    setRetiro(null);
    botonCargar.current?.focus();
    setTerminados((t) => t.filter((id) => id !== creado.documento.id_documento));
    setAviso({ tipo: "exito", texto: `«${creado.documento.titulo}» quedó retirada: ya no se citará en nuevas consultas. `
      + "Las consultas anteriores conservan sus citas." });
    void cargarDocumentos();
    void actualizar();
  }

  function recargarTrasConflicto() {
    setRetiro(null);
    void cargarDocumentos();
    void actualizar();
  }

  return (
    <section className="conocimiento">
      <div className="encabezado-pagina">
        <div>
          <h1>Base de conocimiento</h1>
          <p className="texto-tenue">Guías clínicas indexadas para la recuperación de evidencia</p>
        </div>
        <button ref={botonCargar} type="button" className="boton boton--primario boton--auto"
                onClick={() => { setAviso(null); setCargarAbierta(true); }}>
          Cargar guía
        </button>
      </div>

      {aviso && (
        <p className={`alerta ${aviso.tipo === "exito" ? "alerta--exito" : "alerta--error"}`}
           role={aviso.tipo === "exito" ? "status" : "alert"}>{aviso.texto}</p>
      )}

      <AvanceIndexacion trabajos={trabajos} terminados={resultados} reintentar={(d) => void reintentar(d)}
                        reintentando={reintentando}
                        descartar={(id) => setTerminados((t) => t.filter((x) => x !== id))} />

      <div className="tarjeta tarjeta--ancha guias">
        {errorCarga ? (
          <div className="alerta alerta--error" role="alert">
            <p className="alerta__texto">No se pudo cargar la lista de guías: {errorCarga}</p>
            <button type="button" className="boton boton--neutro boton--chico" onClick={() => void cargarDocumentos()}>
              Reintentar
            </button>
          </div>
        ) : documentos === null ? (
          <p className="vacio" role="status">Cargando las guías…</p>
        ) : documentos.length === 0 ? (
          <p className="vacio">Aún no hay guías. Use «Cargar guía» para agregar la primera.</p>
        ) : (
          <TablaGuias documentos={documentos} ver={ver} reintentar={(d) => void reintentar(d)} reintentando={reintentando}
                      retirar={abrirRetiro} puedeRetirar={puedeRetirar} idNotaRetirar={idNotaRetirar} />
        )}
      </div>
      <p className="guias__pie">{NOTA_OBSOLETAS}</p>
      <p className="guias__pie" id={idNotaRetirar}>{puedeRetirar ? NOTA_RETIRAR : NOTA_RETIRAR_SIN_PERMISO}</p>

      {cargarAbierta && (
        <VentanaCargarGuia alCerrar={() => setCargarAbierta(false)} alCargar={alCargar} focoAlCerrar={botonCargar} />
      )}
      {detalle && <VentanaDetalleGuia documento={detalle} alCerrar={() => setDetalle(null)} focoAlCerrar={botonVer} />}
      {retiro && (
        <VentanaRetirarGuia documento={retiro} alCerrar={() => setRetiro(null)} alRetirar={alRetirar}
                            alRecargar={recargarTrasConflicto} focoAlCerrar={botonRetirar} />
      )}
    </section>
  );
}
