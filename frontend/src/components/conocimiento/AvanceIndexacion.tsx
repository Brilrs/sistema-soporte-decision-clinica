// Tarjeta de avance de la indexación (M11): documento, las cinco etapas con la actual, la barra
// (role="progressbar", «148 de 240 fragmentos») y, al terminar, el resultado: correcto o con el
// mensaje de error y «Reintentar». El cambio de etapa se anuncia en una región aria-live cortés
// (solo la etapa, no cada fragmento, para no saturar al lector de pantalla).
import { useEffect, useRef, useState } from "react";
import type { Documento, Trabajo } from "../../api/conocimiento";
import { ETAPAS, TIPOS_TRABAJO, textoEtapa } from "./textos";

type Props = {
  trabajos: Trabajo[];
  terminados: Documento[]; // documentos cuyo trabajo acaba de terminar (con su último trabajo)
  reintentar: (doc: Documento) => void;
  reintentando: string | null;
  descartar: (id: string) => void;
};

function estadoEtapa(t: Trabajo, indice: number): "lista" | "en_curso" | "pendiente" {
  const actual = ETAPAS.findIndex((e) => e.codigo === t.etapa);
  if (t.estado !== "EN_CURSO" || actual < 0) return "pendiente";
  return indice < actual ? "lista" : indice === actual ? "en_curso" : "pendiente";
}

const ESTADO_LECTOR = { lista: "completada", en_curso: "en curso", pendiente: "pendiente" };

function Barra({ t }: { t: Trabajo }) {
  const conTotal = t.total !== null && t.total > 0;
  const texto = t.estado === "PENDIENTE" ? "En cola: el indexador la tomará en cuanto termine el trabajo anterior."
    : conTotal ? `${t.procesados} de ${t.total} fragmentos` : "Calculando los fragmentos…";
  const porcentaje = conTotal ? Math.min(100, Math.round((t.procesados / (t.total as number)) * 100)) : 0;
  return (
    <>
      <div className="avance__barra" role="progressbar" aria-label={`Avance de la indexación de ${t.titulo}`}
           aria-valuemin={0} aria-valuemax={conTotal ? (t.total as number) : undefined}
           aria-valuenow={conTotal ? t.procesados : undefined} aria-valuetext={texto}>
        <span style={{ width: `${porcentaje}%` }} />
      </div>
      <p className="indexacion__cuenta">{texto}</p>
    </>
  );
}

export default function AvanceIndexacion({ trabajos, terminados, reintentar, reintentando, descartar }: Props) {
  // Anuncio cortés del cambio de etapa (o de estado) de cada trabajo.
  const [anuncio, setAnuncio] = useState("");
  const vistos = useRef(new Map<string, string>());
  useEffect(() => {
    const cambios: string[] = [];
    for (const t of trabajos) {
      const clave = `${t.estado}:${t.etapa ?? ""}`;
      if (vistos.current.get(t.id_trabajo) !== clave) {
        const etapa = textoEtapa(t.etapa);
        cambios.push(t.estado === "PENDIENTE" ? `«${t.titulo}» está en cola para indexarse.`
          : etapa ? `Indexación de «${t.titulo}»: etapa ${etapa}.` : `Comenzó la indexación de «${t.titulo}».`);
        vistos.current.set(t.id_trabajo, clave);
      }
    }
    for (const d of terminados) {
      const clave = `fin:${d.ultimo_trabajo?.id_trabajo}`;
      if (!vistos.current.has(clave)) {
        cambios.push(d.ultimo_trabajo?.estado === "ERROR" ? `La indexación de «${d.titulo}» terminó con error.`
          : `La indexación de «${d.titulo}» terminó.`);
        vistos.current.set(clave, "1");
      }
    }
    if (cambios.length) setAnuncio(cambios.join(" "));
  }, [trabajos, terminados]);

  const visibles = trabajos.length > 0 || terminados.length > 0;
  return (
    <>
      <p className="solo-lectores" aria-live="polite" role="status">{anuncio}</p>
      {visibles && (
        <section className="indexacion" aria-labelledby="indexacion-titulo">
          <h2 id="indexacion-titulo" className="indexacion__titulo">Avance de la indexación</h2>
          {trabajos.map((t) => (
            <article key={t.id_trabajo} className="indexacion__trabajo" aria-label={`${TIPOS_TRABAJO[t.tipo] ?? t.tipo} de ${t.titulo}`}>
              <p className="indexacion__documento">
                <span className="texto-tenue">{t.estado === "PENDIENTE" ? "En cola: " : "Indexando: "}</span>
                <strong>{t.titulo}</strong>
              </p>
              <ol className="indexacion__etapas">
                {ETAPAS.map((e, i) => {
                  const estado = estadoEtapa(t, i);
                  return (
                    <li key={e.codigo} className={`indexacion__etapa indexacion__etapa--${estado}`}
                        aria-current={estado === "en_curso" ? "step" : undefined}>
                      <span className="indexacion__icono" aria-hidden="true">{estado === "lista" ? "✓" : estado === "en_curso" ? "…" : ""}</span>
                      <span>{e.texto}<span className="solo-lectores">: {ESTADO_LECTOR[estado]}</span></span>
                    </li>
                  );
                })}
              </ol>
              <Barra t={t} />
            </article>
          ))}
          {terminados.map((d) => {
            const fallo = d.ultimo_trabajo?.estado === "ERROR";
            return (
              <article key={d.ultimo_trabajo?.id_trabajo ?? d.id_documento}
                       className={`indexacion__fin indexacion__fin--${fallo ? "error" : "ok"}`}
                       aria-label={`Resultado de la indexación de ${d.titulo}`}>
                {fallo ? (
                  <>
                    <p className="indexacion__fin-titulo"><strong>No se pudo indexar «{d.titulo}».</strong></p>
                    {d.ultimo_trabajo?.mensaje_error && <p className="indexacion__mensaje">{d.ultimo_trabajo.mensaje_error}</p>}
                  </>
                ) : (
                  <p className="indexacion__fin-titulo">
                    <strong>«{d.titulo}» quedó indexada</strong> con {d.fragmentos_vigentes} fragmentos vigentes.
                  </p>
                )}
                <div className="indexacion__fin-acciones">
                  {fallo && d.estado_indexacion === "ERROR" && (
                    <button type="button" className="boton boton--secundario boton--chico" disabled={reintentando === d.id_documento}
                            onClick={() => reintentar(d)} aria-label={`Reintentar: ${d.titulo}`}>
                      {reintentando === d.id_documento ? "Reintentando…" : "Reintentar"}
                    </button>
                  )}
                  <button type="button" className="boton boton--neutro boton--chico" onClick={() => descartar(d.id_documento)}
                          aria-label={`Ocultar el resultado de ${d.titulo}`}>Ocultar</button>
                </div>
              </article>
            );
          })}
        </section>
      )}
    </>
  );
}
