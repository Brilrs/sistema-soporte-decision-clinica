// M05: nivel de riesgo y clasificación calculados por el sistema (NTS 213 y OMS 2024), con la
// hemoglobina ajustada por altitud y la indicación de derivación.
import type { ClasificacionConsulta } from "../../api/tipos_consulta";
import { CATEGORIAS, NIVELES_RIESGO, decimal } from "../../utilidades/formato";

type Props = {
  clasificacion: ClasificacionConsulta | null;
  hbObservada: string | number | null;
  // En los estados sin recomendación: «Clasificación del paciente» con su rótulo, y nivel de
  // encabezado según la pantalla (h3 dentro de la consulta de M04).
  titulo?: string;
  rotulo?: string;
  nivel?: 2 | 3;
};

const NIVEL = "Nivel de riesgo";

export default function RiesgoClasificacion({ clasificacion: c, hbObservada, titulo = NIVEL, rotulo, nivel = 2 }: Props) {
  const H = nivel === 3 ? "h3" : "h2";
  const encabezado = (
    <>
      <H id="titulo-riesgo" className={titulo === NIVEL ? "riesgo__titulo" : "riesgo__titulo riesgo__titulo--seccion"}>{titulo}</H>
      {rotulo && <p className="riesgo__rotulo">{rotulo}</p>}
    </>
  );
  if (!c) {
    return (
      <section className="tarjeta resultado__riesgo riesgo" aria-labelledby="titulo-riesgo">
        {encabezado}
        <p className="texto-tenue">El sistema no calculó la clasificación para este tamizaje.</p>
      </section>
    );
  }
  const conAjuste = c.ajuste_hb_g_dl !== 0;
  return (
    <section className={`tarjeta resultado__riesgo riesgo riesgo--${c.nivel_riesgo}`} aria-labelledby="titulo-riesgo">
      {encabezado}
      {titulo !== NIVEL && <p className="riesgo__etiqueta-nivel">{NIVEL}</p>}
      <p className="riesgo__nivel">{(NIVELES_RIESGO[c.nivel_riesgo] ?? c.nivel_riesgo).toUpperCase()}</p>
      <span className={`etiqueta etiqueta--${c.categoria}`}>{CATEGORIAS[c.categoria] ?? c.categoria}</span>
      <dl className="riesgo__datos">
        {hbObservada !== null && (
          <div><dt>Hb observada</dt><dd>{decimal(hbObservada)} g/dL</dd></div>
        )}
        <div><dt>Hb ajustada por altitud</dt><dd>{decimal(c.hb_ajustada_g_dl)} g/dL</dd></div>
        <div>
          <dt>Ajuste por altitud</dt>
          <dd>
            {conAjuste ? `${decimal(c.ajuste_hb_g_dl)} g/dL` : "Sin ajuste"}
            {c.altitud_msnm !== null && <> ({c.altitud_msnm} m.s.n.m.)</>}
          </dd>
        </div>
      </dl>
      {c.requiere_derivacion ? (
        <p className="riesgo__derivacion riesgo__derivacion--si">
          Requiere derivación a un establecimiento de mayor capacidad resolutiva.
        </p>
      ) : (
        <p className="riesgo__derivacion">No requiere derivación.</p>
      )}
      <p className="riesgo__norma">Clasificación calculada según NTS 213-MINSA / OMS 2024.</p>
    </section>
  );
}
