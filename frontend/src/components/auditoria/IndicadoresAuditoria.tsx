// Indicadores de los últimos 30 días (GET /api/auditoria/indicadores), siempre sin consultas de
// prueba. Cada valor nulo (porcentajes y latencias sin consultas) se muestra como «Sin datos».
import { useEffect, useState } from "react";
import { auditoriaApi } from "../../api/auditoria";
import { mensajeError } from "../../api/cliente";
import type { IndicadoresAuditoria as Datos } from "../../api/tipos_auditoria";
import { ESTADOS_CONSULTA, fechaHora } from "../../utilidades/formato";
import { EtiquetaEstadoConsulta } from "../Etiquetas";
import TarjetaIndicador from "../TarjetaIndicador";
import { NOTA_SIN_PRUEBAS, consultas, entero, latencia, porcentaje, usd } from "./formato";

type Carga = { estado: "cargando" } | { estado: "error"; mensaje: string } | { estado: "listo"; datos: Datos };

export default function IndicadoresAuditoria() {
  const [carga, setCarga] = useState<Carga>({ estado: "cargando" });
  const [intento, setIntento] = useState(0);

  useEffect(() => {
    const control = new AbortController();
    setCarga({ estado: "cargando" });
    auditoriaApi.indicadores(control.signal)
      .then((datos) => setCarga({ estado: "listo", datos }))
      .catch((e) => !control.signal.aborted && setCarga({ estado: "error", mensaje: mensajeError(e) }));
    return () => control.abort();
  }, [intento]);

  return (
    <section className="auditoria__indicadores" aria-labelledby="titulo-indicadores">
      <div className="auditoria__indicadores-cabecera">
        <h2 id="titulo-indicadores">Últimos 30 días</h2>
        {carga.estado === "listo" && (
          <p className="texto-tenue auditoria__periodo">
            Del {fechaHora(carga.datos.desde)} al {fechaHora(carga.datos.hasta)} · <strong>{NOTA_SIN_PRUEBAS}</strong>
          </p>
        )}
      </div>
      {carga.estado === "cargando" ? (
        <p className="vacio" role="status" aria-live="polite">Cargando indicadores…</p>
      ) : carga.estado === "error" ? (
        <div className="alerta alerta--error" role="alert">
          <p className="alerta__texto">No se pudieron cargar los indicadores. {carga.mensaje}</p>
          <button type="button" className="boton boton--secundario boton--chico" onClick={() => setIntento((n) => n + 1)}>
            Reintentar
          </button>
        </div>
      ) : carga.datos.consultas === 0 ? (
        <p className="vacio" role="status">Sin datos: no hubo consultas en los últimos 30 días.</p>
      ) : (
        <Tarjetas d={carga.datos} />
      )}
    </section>
  );
}

function Tarjetas({ d }: { d: Datos }) {
  const evaluadas = `${entero(d.evaluadas)} ${d.evaluadas === 1 ? "evaluada" : "evaluadas"}`;
  return (
    <>
      <div className="indicadores auditoria__tarjetas">
        <TarjetaIndicador titulo="Consultas (30 días)" valor={entero(d.consultas)} nota={evaluadas} />
        <TarjetaIndicador titulo="Verificadas" valor={porcentaje(d.pct_verificadas)}
                          nota={consultas(d.por_estado.VERIFICADA)} />
        <TarjetaIndicador titulo="Evidencia insuficiente" valor={porcentaje(d.pct_evidencia_insuficiente)}
                          nota={consultas(d.por_estado.EVIDENCIA_INSUFICIENTE)} />
        <TarjetaIndicador titulo="Con reintento" valor={porcentaje(d.pct_con_reintento)}
                          nota={consultas(d.con_reintento)} />
        <TarjetaIndicador titulo="Tiempo p50" valor={d.latencia_p50_ms === null ? null : latencia(d.latencia_p50_ms)}
                          nota="Mediana de todas las consultas" />
        <TarjetaIndicador titulo="Tiempo p90" valor={d.latencia_p90_ms === null ? null : latencia(d.latencia_p90_ms)}
                          nota={d.latencia_p90_flujo_normal_ms === null ? undefined
                            : `Flujo normal: ${latencia(d.latencia_p90_flujo_normal_ms)}`} />
        <TarjetaIndicador titulo="Bloqueadas y errores" valor={`${entero(d.solicitudes_bloqueadas)} · ${entero(d.errores)}`}
                          nota="Solicitudes bloqueadas · errores" />
        <TarjetaIndicador titulo="Costo de API" valor={usd(d.costo_api_usd)}
                          nota={`Tokens: ${entero(d.tokens_entrada)} entrada · ${entero(d.tokens_salida)} salida`} />
      </div>
      <h3 className="auditoria__subtitulo">Consultas por estado</h3>
      <ul className="auditoria__estados" aria-label="Consultas por estado">
        {Object.entries(d.por_estado).map(([estado, n]) => (
          <li key={estado} className="auditoria__estado">
            <EtiquetaEstadoConsulta estado={estado} />
            <span className="auditoria__estado-numero" aria-label={`${ESTADOS_CONSULTA[estado] ?? estado}: ${n}`}>
              {entero(n)}
            </span>
          </li>
        ))}
      </ul>
    </>
  );
}
