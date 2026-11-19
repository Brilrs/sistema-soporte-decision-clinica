// M12 · «Parámetros clínicos» (/admin/parametros, HU14; Sprint 3, parte E2), permiso VER_PARAMETROS.
// Rutas de las partes E1a y E1b (docs/contrato_parametros.md). Quién edita lo decide puede_editar del
// GET (CONFIGURAR_PARAMETROS, solo el Coordinador CRED), nunca el nombre del rol; con modo_evaluacion
// la edición queda deshabilitada. Secciones, en orden: puntos de corte, ajuste por altitud y vigencia
// (editables por grupo), riesgo por clasificación, recuperación, modelo e indexación (solo lectura),
// huella de configuración e historial. No hay datos de pacientes en esta pantalla.
import { useEffect, useState } from "react";
import { mensajeError } from "../api/cliente";
import { parametrosApi } from "../api/parametros";
import type { Parametros } from "../api/tipos_parametros";
import GrupoAjusteAltitud from "../components/parametros/GrupoAjusteAltitud";
import GrupoPuntosCorte from "../components/parametros/GrupoPuntosCorte";
import GrupoVigencia from "../components/parametros/GrupoVigencia";
import HistorialParametros from "../components/parametros/HistorialParametros";
import HuellaConfiguracion from "../components/parametros/HuellaConfiguracion";
import { SeccionParametros, SeccionRiesgo } from "../components/parametros/SoloLectura";
import { AVISO_EVALUACION, AVISO_PENDIENTES, AVISO_SOLO_LECTURA, NOTA_EFECTO, TITULOS } from "../components/parametros/textos";
import { useTituloPagina } from "../utilidades/useTituloPagina";

type Carga = { estado: "cargando" } | { estado: "error"; mensaje: string } | { estado: "listo"; p: Parametros };

export function pendientesPorGrupo(p: Parametros): { grupo: string; cantidad: number }[] {
  const puntos = p.puntos_corte.tramos.reduce((n, t) => n + t.categorias.filter((c) => !c.verificado).length, 0);
  const altitud = p.ajuste_altitud.rangos.filter((r) => !r.verificado).length;
  const vigencia = p.vigencia_tamizaje.verificado ? 0 : 1;
  return [
    { grupo: TITULOS.puntos_corte, cantidad: puntos },
    { grupo: TITULOS.ajuste_altitud, cantidad: altitud },
    { grupo: TITULOS.vigencia_tamizaje, cantidad: vigencia },
  ].filter((x) => x.cantidad > 0);
}

export default function ParametrosClinicos() {
  useTituloPagina("Parámetros clínicos");
  const [carga, setCarga] = useState<Carga>({ estado: "cargando" });
  const [intento, setIntento] = useState(0);
  // Cada recarga monta de nuevo los grupos (descarta lo escrito); cada guardado recarga huella e historial.
  const [recargaGrupos, setRecargaGrupos] = useState(0);
  const [recargaDerivados, setRecargaDerivados] = useState(0);
  const [bloqueadoLocal, setBloqueadoLocal] = useState(false);

  useEffect(() => {
    const control = new AbortController();
    setCarga({ estado: "cargando" });
    parametrosApi.leer(control.signal)
      .then((p) => { setCarga({ estado: "listo", p }); setRecargaGrupos((n) => n + 1); })
      .catch((e) => !control.signal.aborted && setCarga({ estado: "error", mensaje: mensajeError(e) }));
    return () => control.abort();
  }, [intento]);

  const recargar = () => { setIntento((n) => n + 1); setRecargaDerivados((n) => n + 1); };
  const actualizar = <K extends "puntos_corte" | "ajuste_altitud" | "vigencia_tamizaje">(clave: K, grupo: Parametros[K]) => {
    setCarga((c) => (c.estado === "listo" ? { estado: "listo", p: { ...c.p, [clave]: grupo } } : c));
    setRecargaDerivados((n) => n + 1);
  };

  if (carga.estado !== "listo") {
    return (
      <section className="parametros">
        <h1>Parámetros clínicos</h1>
        <p className="parametros__efecto">{NOTA_EFECTO}</p>
        {carga.estado === "cargando" ? (
          <p className="vacio" role="status" aria-live="polite">Cargando los parámetros…</p>
        ) : (
          <div className="alerta alerta--error" role="alert">
            <p className="alerta__texto">No se pudieron cargar los parámetros. {carga.mensaje}</p>
            <button type="button" className="boton boton--secundario boton--auto" onClick={() => setIntento((n) => n + 1)}>
              Reintentar
            </button>
          </div>
        )}
      </section>
    );
  }

  const p = carga.p;
  const bloqueado = p.modo_evaluacion || bloqueadoLocal;
  const pendientes = pendientesPorGrupo(p);
  const descripciones = Object.fromEntries([...p.recuperacion, ...p.modelo, ...p.indexacion, p.vigencia_tamizaje]
    .map((x) => [x.clave, x.descripcion]));
  const comunes = { puedeEditar: p.puede_editar, bloqueado, alRecargar: recargar, alBloquear: () => setBloqueadoLocal(true) };

  return (
    <section className="parametros">
      <div className="encabezado-pagina">
        <div className="parametros__titulo">
          <h1>Parámetros clínicos</h1>
          <p className="parametros__efecto">{NOTA_EFECTO}</p>
        </div>
      </div>

      {bloqueado && <p className="alerta alerta--aviso parametros__aviso" role="note"><strong>{AVISO_EVALUACION}.</strong></p>}
      {!p.puede_editar && <p className="alerta alerta--info parametros__aviso" role="note">{AVISO_SOLO_LECTURA}.</p>}
      {pendientes.length > 0 && (
        <div className="alerta alerta--aviso parametros__aviso" role="note">
          <p className="alerta__texto"><strong>{AVISO_PENDIENTES}:</strong></p>
          <ul className="parametros__pendientes">
            {pendientes.map((x) => <li key={x.grupo}>{x.grupo}: {x.cantidad} {x.cantidad === 1 ? "valor" : "valores"}</li>)}
          </ul>
        </div>
      )}

      <GrupoPuntosCorte key={`pc-${recargaGrupos}`} datos={p.puntos_corte} {...comunes}
                        alActualizar={(g) => actualizar("puntos_corte", g)} />
      <GrupoAjusteAltitud key={`aa-${recargaGrupos}`} datos={p.ajuste_altitud} {...comunes}
                          alActualizar={(g) => actualizar("ajuste_altitud", g)} />
      <GrupoVigencia key={`vt-${recargaGrupos}`} datos={p.vigencia_tamizaje} {...comunes}
                     alActualizar={(g) => actualizar("vigencia_tamizaje", g)} />
      <SeccionRiesgo riesgo={p.riesgo} />
      <SeccionParametros id="recuperacion" titulo="Recuperación" parametros={p.recuperacion} />
      <SeccionParametros id="modelo" titulo="Modelo" parametros={p.modelo} />
      <SeccionParametros id="indexacion" titulo="Indexación" parametros={p.indexacion} />
      <HuellaConfiguracion recarga={recargaDerivados} />
      <HistorialParametros recarga={recargaDerivados} descripciones={descripciones} />
    </section>
  );
}
