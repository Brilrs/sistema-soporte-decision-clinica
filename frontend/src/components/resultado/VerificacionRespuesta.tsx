// M05: controles de verificación 6.1 a 6.3 del intento que decide. null: el control no se
// ejecutó. La marca va acompañada de texto (no depende solo del color).
import type { Intento, Verificacion } from "../../api/tipos_consulta";
import { decimal, segundos } from "../../utilidades/formato";

type Control = { codigo: string; titulo: string; valor: boolean | null; detalle: string };

const MARCAS = {
  cumplido: { icono: "✓", texto: "Cumplido" },
  no_cumplido: { icono: "✗", texto: "No cumplido" },
  no_ejecutado: { icono: "○", texto: "No se ejecutó" },
};

function marca(valor: boolean | null) {
  return valor === null ? "no_ejecutado" : valor ? "cumplido" : "no_cumplido";
}

// 6.3 falla de dos maneras: ningún fragmento alcanza el umbral (sin llamar al modelo) o el modelo
// declara que los fragmentos recuperados no bastan aunque la relevancia supere el umbral.
export function detalleEvidencia(v: Verificacion, relevancia: string): string {
  const umbral = decimal(v.umbral_relevancia, 3);
  if (v.valida_evidencia === false) {
    if (v.relevancia_maxima !== null && v.relevancia_maxima >= v.umbral_relevancia) {
      return `El modelo indicó que los fragmentos recuperados no bastan para responder, aunque la relevancia máxima ` +
        `(${relevancia}) supera el umbral (${umbral}).`;
    }
    return `Ningún fragmento alcanzó el umbral: relevancia máxima ${relevancia} frente al umbral ${umbral}.`;
  }
  return `Relevancia máxima ${relevancia} frente al umbral ${umbral}.`;
}

type Props = {
  verificacion: Verificacion | null;
  intentos: Intento[];
  citas: number;
  latenciaMs: number | null;
};

export default function VerificacionRespuesta({ verificacion: v, intentos, citas, latenciaMs }: Props) {
  if (!v) {
    return (
      <section className="tarjeta resultado__verificacion" aria-labelledby="titulo-verificacion">
        <h2 id="titulo-verificacion">Verificación de la respuesta</h2>
        <p className="texto-tenue">No se ejecutaron los controles de verificación.</p>
      </section>
    );
  }
  const relevancia = v.relevancia_maxima === null ? "sin dato" : decimal(v.relevancia_maxima, 3);
  const controles: Control[] = [
    { codigo: "6.1", titulo: "Citas textuales", valor: v.valida_citas,
      detalle: "Cada afirmación tiene una cita y su extracto coincide con la fuente." },
    { codigo: "6.2", titulo: "Consistencia y dosis", valor: v.valida_consistencia,
      detalle: "Coherente con la clasificación calculada, la derivación y las dosis de la fuente." },
    { codigo: "6.3", titulo: "Suficiencia de la evidencia", valor: v.valida_evidencia,
      detalle: detalleEvidencia(v, relevancia) },
  ];
  const intento = intentos.find((i) => i.numero === v.numero_intento);
  const pie = [
    intento ? `Intento ${intento.numero}, búsqueda ${intento.tipo_busqueda === "AMPLIADA" ? "ampliada" : "inicial"}` : null,
    latenciaMs !== null ? `respuesta en ${segundos(latenciaMs)}` : null,
    intento ? `${citas} ${citas === 1 ? "cita" : "citas"} de ${intento.candidatos_evaluados} fragmentos evaluados` : null,
  ].filter(Boolean);
  return (
    <section className="tarjeta resultado__verificacion" aria-labelledby="titulo-verificacion">
      <h2 id="titulo-verificacion">Verificación de la respuesta</h2>
      <ul className="verificacion">
        {controles.map((c) => {
          const m = MARCAS[marca(c.valor)];
          return (
            <li key={c.codigo} className={`verificacion__control verificacion__control--${marca(c.valor)}`}>
              <span className="verificacion__icono" aria-hidden="true">{m.icono}</span>
              <div>
                <strong>{c.codigo} {c.titulo}: </strong>
                <span className="verificacion__estado">{m.texto}</span>
                <p className="verificacion__detalle">{c.detalle}</p>
              </div>
            </li>
          );
        })}
      </ul>
      {pie.length > 0 && <p className="verificacion__pie">{pie.join(" · ")}</p>}
    </section>
  );
}
