// Evolución de la hemoglobina (M08), en SVG sin librerías externas.
// - Cada punto es la Hb ajustada por altitud (la que se compara con los puntos de corte) y
//   lleva el color de su propia clasificación guardada.
// - Las franjas de fondo son los puntos de corte vigentes del grupo de edad del tamizaje más
//   reciente; una nota al pie lo indica, porque los controles anteriores pueden pertenecer a
//   otro grupo de edad.
import type { Franja, TamizajeHistorial } from "../api/pacientes";
import { CATEGORIAS, decimal, fecha } from "../utilidades/formato";

const ANCHO = 560;
const ALTO = 280;
const MARGEN = { izq: 44, der: 20, sup: 24, inf: 34 };

// Mismos tonos que las etiquetas de clasificación (estilos.css)
const COLOR_FRANJA: Record<string, string> = {
  SIN_ANEMIA: "#e7f6ee", ANEMIA_LEVE: "#fff4dc", ANEMIA_MODERADA: "#fdecea", ANEMIA_SEVERA: "#f9d4d0",
};
const COLOR_PUNTO: Record<string, string> = {
  SIN_ANEMIA: "#11734b", ANEMIA_LEVE: "#9a5b00", ANEMIA_MODERADA: "#b42318", ANEMIA_SEVERA: "#7a1209",
};
const COLOR_SIN_CLASIFICAR = "#6b7280";

type Punto = { t: TamizajeHistorial; fechaMs: number; hb: number; ajustada: boolean };

function fechaMs(iso: string): number {
  const [a, m, d] = iso.split("-").map(Number);
  return new Date(a, m - 1, d).getTime();
}

function mesAnio(iso: string): string {
  const [a, m] = iso.split("-").map(Number);
  const mes = new Date(a, m - 1, 1).toLocaleDateString("es-PE", { month: "short" }).replace(".", "");
  return `${mes.charAt(0).toUpperCase()}${mes.slice(1)} ${a}`;
}

export default function GraficoHemoglobina({ tamizajes, franjas }: { tamizajes: TamizajeHistorial[]; franjas: Franja[] }) {
  // Del más antiguo al más reciente; los tamizajes sin hemoglobina no se grafican.
  const puntos: Punto[] = [...tamizajes].reverse().flatMap((t) => {
    const valor = t.clasificacion?.hb_ajustada_g_dl ?? t.hemoglobina_g_dl;
    return valor === null ? [] : [{ t, fechaMs: fechaMs(t.fecha_tamizaje), hb: Number(valor), ajustada: !!t.clasificacion }];
  });

  if (puntos.length === 0) {
    return <p className="vacio">Aún no hay mediciones de hemoglobina para graficar.</p>;
  }

  const reciente = tamizajes[0];
  const grupo = franjas.filter((f) => f.edad_min_meses <= reciente.edad_meses && reciente.edad_meses <= f.edad_max_meses);
  const cortes = grupo.flatMap((f) => [f.hb_min_g_dl, f.hb_max_g_dl]).filter((v): v is string => v !== null).map(Number);

  const valores = [...puntos.map((p) => p.hb), ...cortes];
  const yMin = Math.floor(Math.min(...valores) - 1);
  const yMax = Math.ceil(Math.max(...valores) + 1);
  const y = (hb: number) => MARGEN.sup + (yMax - hb) / (yMax - yMin) * (ALTO - MARGEN.sup - MARGEN.inf);

  const t0 = puntos[0].fechaMs;
  const t1 = puntos[puntos.length - 1].fechaMs;
  const anchoUtil = ANCHO - MARGEN.izq - MARGEN.der;
  const x = (ms: number) => t1 === t0 ? MARGEN.izq + anchoUtil / 2 : MARGEN.izq + 20 + (ms - t0) / (t1 - t0) * (anchoUtil - 40);

  // Cada franja va de su límite inferior al inferior de la siguiente (los cortes tienen un decimal).
  const bandas = grupo.map((f) => ({
    categoria: f.categoria,
    desde: f.hb_min_g_dl !== null ? Number(f.hb_min_g_dl) : yMin,
    hasta: f.hb_max_g_dl !== null ? Number(f.hb_max_g_dl) + 0.1 : yMax,
  }));
  const marcas = Array.from(new Set(bandas.map((b) => b.desde).filter((v) => v > yMin))).sort((a, b) => a - b);
  const etiquetasX = puntos.filter((p, i) => i === 0 || mesAnio(p.t.fecha_tamizaje) !== mesAnio(puntos[i - 1].t.fecha_tamizaje));

  return (
    <figure style={{ margin: 0 }}>
      <svg className="grafico" viewBox={`0 0 ${ANCHO} ${ALTO}`} role="img"
           aria-label="Evolución de la hemoglobina ajustada por altitud en el tiempo">
        {bandas.map((b) => (
          <rect key={b.categoria} x={MARGEN.izq} width={anchoUtil}
                y={y(Math.min(b.hasta, yMax))} height={Math.max(0, y(Math.max(b.desde, yMin)) - y(Math.min(b.hasta, yMax)))}
                fill={COLOR_FRANJA[b.categoria] ?? "#f3f4f6"}>
            <title>{CATEGORIAS[b.categoria] ?? b.categoria}</title>
          </rect>
        ))}
        {bandas.length === 0 && (
          <rect x={MARGEN.izq} y={MARGEN.sup} width={anchoUtil} height={ALTO - MARGEN.sup - MARGEN.inf} fill="#f3f4f6" />
        )}

        {[yMin, ...marcas, yMax].map((v) => (
          <text key={v} x={MARGEN.izq - 6} y={y(v) + 4} textAnchor="end" fontSize="11" fill="#6b7280">{decimal(v)}</text>
        ))}
        {etiquetasX.map((p) => (
          <text key={p.t.id_tamizaje} x={x(p.fechaMs)} y={ALTO - 10} textAnchor="middle" fontSize="11" fill="#6b7280">
            {mesAnio(p.t.fecha_tamizaje)}
          </text>
        ))}

        <polyline fill="none" stroke="#1d4ed8" strokeWidth="2.5"
                  points={puntos.map((p) => `${x(p.fechaMs)},${y(p.hb)}`).join(" ")} />
        {puntos.map((p) => {
          const color = p.t.clasificacion ? COLOR_PUNTO[p.t.clasificacion.categoria] ?? COLOR_SIN_CLASIFICAR : COLOR_SIN_CLASIFICAR;
          const detalle = p.t.clasificacion
            ? `Hb observada ${decimal(p.t.hemoglobina_g_dl)} · ajustada ${decimal(p.hb)} g/dL · ${CATEGORIAS[p.t.clasificacion.categoria] ?? p.t.clasificacion.categoria}`
            : `Hb observada ${decimal(p.hb)} g/dL · sin clasificación`;
          return (
            <g key={p.t.id_tamizaje}>
              <circle cx={x(p.fechaMs)} cy={y(p.hb)} r="7" fill={color} stroke="#ffffff" strokeWidth="2">
                <title>{`${fecha(p.t.fecha_tamizaje)} · ${detalle}`}</title>
              </circle>
              <text x={x(p.fechaMs)} y={y(p.hb) - 12} textAnchor="middle" fontSize="12" fontWeight="700" fill="#111827">
                {decimal(p.hb)}
              </text>
            </g>
          );
        })}
      </svg>
      <figcaption className="grafico__nota">
        Hb ajustada por altitud (g/dL); cada punto lleva el color de su clasificación guardada.{" "}
        {grupo.length > 0
          ? `Las franjas son los puntos de corte vigentes del grupo de ${grupo[0].edad_min_meses} a ${grupo[0].edad_max_meses} meses, el del tamizaje más reciente (${reciente.edad_meses} meses).`
          : `Sin franjas: la edad del tamizaje más reciente (${reciente.edad_meses} meses) está fuera del rango de los puntos de corte.`}
        {puntos.some((p) => !p.ajustada) && " Los puntos grises no tienen clasificación y muestran la Hb observada."}
      </figcaption>
    </figure>
  );
}
