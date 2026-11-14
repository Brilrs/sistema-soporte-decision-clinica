// Avance de la consulta por etapas (M04): lista con su estado, barra, tiempo transcurrido,
// aviso de espera en cola y botón «Cancelar». Una región aria-live anuncia la etapa en curso.
import { useEffect, useState } from "react";
import { ETAPAS, RECURSOS, estadosEtapas, type Avance } from "../consulta/avance";
import { segundos } from "../utilidades/formato";

const TEXTO_ESTADO = { lista: "lista", en_curso: "en curso", pendiente: "pendiente" } as const;

// Tiempo desde «inicio»; se actualiza cada décima de segundo mientras la consulta está activa.
function useTranscurrido(inicio: number | null, finMs: number | null, activa: boolean): number {
  const [ahora, setAhora] = useState(() => Date.now());
  useEffect(() => {
    if (!activa) return;
    setAhora(Date.now());
    const t = setInterval(() => setAhora(Date.now()), 100);
    return () => clearInterval(t);
  }, [activa]);
  if (finMs !== null) return finMs;
  return inicio === null ? 0 : Math.max(ahora - inicio, 0);
}

export default function AvanceConsulta({ avance, activa, recuperando, inicio, finMs, cancelar }: {
  avance: Avance;
  activa: boolean;
  recuperando: boolean;
  inicio: number | null;
  finMs: number | null;
  cancelar: () => void;
}) {
  const estados = estadosEtapas(avance, activa && !recuperando);
  const listas = estados.filter((e) => e === "lista").length;
  const enCurso = estados.indexOf("en_curso");
  const transcurrido = useTranscurrido(inicio, finMs, activa);

  // Lo que se anuncia: la etapa en curso, la espera en cola o la recuperación (sin el cronómetro).
  const anuncio = recuperando
    ? "Se interrumpió la conexión. Recuperando el resultado guardado."
    : avance.enCola
      ? `En espera: ${RECURSOS[avance.enCola.recurso]} está atendiendo otras consultas.`
      : enCurso >= 0
        ? `${ETAPAS[enCurso].texto}${avance.intento > 1 ? `, intento ${avance.intento}` : ""}.`
        : "";

  return (
    <div className="avance" aria-busy={activa}>
      <div className="avance__titulo">
        <h3>{activa ? "Procesando la consulta…" : "Avance de la consulta"}</h3>
        {activa && !recuperando && (
          <button type="button" className="boton boton--neutro boton--chico" onClick={cancelar}>Cancelar</button>
        )}
      </div>
      {avance.intento > 1 && (
        <p className="avance__intento">
          Intento {avance.intento}: {avance.ampliada ? "búsqueda ampliada con sinónimos y términos en inglés" : "nueva generación"}.
        </p>
      )}
      <ol className="avance__etapas">
        {ETAPAS.map((et, i) => (
          <li key={et.clave} className={`avance__etapa avance__etapa--${estados[i]}`}
              aria-current={estados[i] === "en_curso" ? "step" : undefined}>
            <span className="avance__icono" aria-hidden="true">{estados[i] === "lista" ? "✓" : i + 1}</span>
            <span>{et.texto}</span>
            <span className="solo-lectores"> ({TEXTO_ESTADO[estados[i]]})</span>
          </li>
        ))}
      </ol>
      {avance.enCola && activa && (
        <p className="alerta alerta--aviso avance__cola">
          En espera: {RECURSOS[avance.enCola.recurso]} está atendiendo otras consultas. La suya continuará
          automáticamente.
        </p>
      )}
      <div className="avance__barra" role="progressbar" aria-label="Etapas terminadas"
           aria-valuemin={0} aria-valuemax={ETAPAS.length} aria-valuenow={listas}>
        <span style={{ width: `${(listas / ETAPAS.length) * 100}%` }} />
      </div>
      <p className="avance__tiempo">Tiempo transcurrido: {segundos(transcurrido)}</p>
      <p className="solo-lectores" role="status" aria-live="polite" aria-atomic="true">{anuncio}</p>
    </div>
  );
}
