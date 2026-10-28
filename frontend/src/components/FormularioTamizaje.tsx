// Datos del control actual: medición, antropometría, síntomas (HU05) y antecedentes.
// Se usa en el registro del paciente (M03) y en el nuevo tamizaje (M14); en M14 muestra,
// debajo de cada valor, el del control anterior y señala los antecedentes que cambiaron.
import type { MetodoMedicion, Sintoma, TamizajeEntrada, TamizajeHistorial } from "../api/pacientes";
import { METODOS, decimal, edad, edadEnMeses, fecha, hoyIso, leerDecimal } from "../utilidades/formato";

export type FormTamizaje = {
  fecha_tamizaje: string;
  hemoglobina_g_dl: string;
  metodo_medicion: MetodoMedicion | "";
  peso_kg: string;
  talla_cm: string;
  recibe_suplementacion_hierro: boolean;
  lactancia_materna_actual: boolean;
  parasitosis_reciente: boolean;
  observaciones: string;
  sintomas: Record<number, string>; // id_sintoma marcado -> detalle (solo para «Otro»)
};

export function formTamizajeVacio(anterior?: TamizajeHistorial | null): FormTamizaje {
  // Los antecedentes parten del control anterior: se marca solo lo que cambió.
  return {
    fecha_tamizaje: hoyIso(),
    hemoglobina_g_dl: "",
    metodo_medicion: anterior?.metodo_medicion ?? "HEMOGLOBINOMETRO",
    peso_kg: "",
    talla_cm: "",
    recibe_suplementacion_hierro: !!anterior?.recibe_suplementacion_hierro,
    lactancia_materna_actual: !!anterior?.lactancia_materna_actual,
    parasitosis_reciente: !!anterior?.parasitosis_reciente,
    observaciones: "",
    sintomas: {},
  };
}

export function aEntradaTamizaje(f: FormTamizaje): TamizajeEntrada {
  return {
    fecha_tamizaje: f.fecha_tamizaje,
    hemoglobina_g_dl: leerDecimal(f.hemoglobina_g_dl),
    metodo_medicion: f.metodo_medicion || null,
    peso_kg: leerDecimal(f.peso_kg),
    talla_cm: leerDecimal(f.talla_cm),
    recibe_suplementacion_hierro: f.recibe_suplementacion_hierro,
    lactancia_materna_actual: f.lactancia_materna_actual,
    parasitosis_reciente: f.parasitosis_reciente,
    observaciones: f.observaciones.trim() || null,
    sintomas: Object.entries(f.sintomas).map(([id, detalle]) => ({ id_sintoma: Number(id), detalle: detalle.trim() || null })),
  };
}

// Números escritos que no se pueden leer (por ejemplo «9,8,1»): se avisan antes de enviar.
export function erroresTamizaje(f: FormTamizaje): string | null {
  for (const [campo, nombre] of [["hemoglobina_g_dl", "La hemoglobina"], ["peso_kg", "El peso"], ["talla_cm", "La talla"]] as const) {
    if (f[campo].trim() && leerDecimal(f[campo]) === null) return `${nombre} debe ser un número`;
  }
  return null;
}

const ANTECEDENTES = [
  ["recibe_suplementacion_hierro", "Recibe suplementación con hierro"],
  ["lactancia_materna_actual", "Lactancia materna actual"],
  ["parasitosis_reciente", "Parasitosis reciente"],
] as const;

const Ob = () => <span className="obligatorio"> *</span>;

export default function FormularioTamizaje({ valor, cambiar, sintomas, fechaNacimiento, anterior, mostrarEdad = true }: {
  valor: FormTamizaje;
  cambiar: (cambios: Partial<FormTamizaje>) => void;
  sintomas: Sintoma[];
  fechaNacimiento: string;
  anterior?: TamizajeHistorial | null;
  mostrarEdad?: boolean;
}) {
  const idOtro = sintomas.find((s) => s.nombre === "Otro")?.id_sintoma;

  function alternarSintoma(id: number, marcado: boolean) {
    const nuevos = { ...valor.sintomas };
    if (marcado) nuevos[id] = "";
    else delete nuevos[id];
    cambiar({ sintomas: nuevos });
  }

  const Anterior = ({ texto }: { texto: string | null }) =>
    anterior && texto ? <p className="anterior">Anterior: {texto}</p> : null;

  return (
    <>
      <div className="rejilla">
        <div>
          <label htmlFor="fecha-tamizaje">Fecha del tamizaje<Ob /></label>
          <input id="fecha-tamizaje" type="date" max={hoyIso()} value={valor.fecha_tamizaje}
                 onChange={(e) => cambiar({ fecha_tamizaje: e.target.value })} />
        </div>
        {mostrarEdad && (
          <div>
            <label htmlFor="edad-fecha">Edad a la fecha</label>
            <input id="edad-fecha" readOnly value={edad(edadEnMeses(fechaNacimiento, valor.fecha_tamizaje))} />
          </div>
        )}
        <div>
          <label htmlFor="metodo">Método de medición</label>
          <select id="metodo" value={valor.metodo_medicion}
                  onChange={(e) => cambiar({ metodo_medicion: e.target.value as MetodoMedicion | "" })}>
            <option value="">No registrado</option>
            {Object.entries(METODOS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </div>
        <div>
          <label htmlFor="hb">Hemoglobina (g/dL)<Ob /></label>
          <input id="hb" inputMode="decimal" placeholder="Ej.: 10,6" value={valor.hemoglobina_g_dl}
                 onChange={(e) => cambiar({ hemoglobina_g_dl: e.target.value })} />
          <Anterior texto={anterior?.hemoglobina_g_dl
            ? `${decimal(anterior.hemoglobina_g_dl)} · ${fecha(anterior.fecha_tamizaje)}` : null} />
        </div>
        <div>
          <label htmlFor="peso">Peso (kg)</label>
          <input id="peso" inputMode="decimal" value={valor.peso_kg} onChange={(e) => cambiar({ peso_kg: e.target.value })} />
          <Anterior texto={anterior?.peso_kg ? decimal(anterior.peso_kg) : null} />
        </div>
        <div>
          <label htmlFor="talla">Talla (cm)</label>
          <input id="talla" inputMode="decimal" value={valor.talla_cm} onChange={(e) => cambiar({ talla_cm: e.target.value })} />
          <Anterior texto={anterior?.talla_cm ? decimal(anterior.talla_cm) : null} />
        </div>
      </div>

      <div className="columnas">
        <div>
          <p className="subtitulo">
            Síntomas observados
            {anterior && <span> (anterior: {anterior.sintomas.length
              ? anterior.sintomas.map((s) => s.nombre.toLowerCase()).join(", ") : "ninguno"})</span>}
          </p>
          <div className="casillas">
            {sintomas.map((s) => (
              <label key={s.id_sintoma} className="casilla">
                <input type="checkbox" checked={s.id_sintoma in valor.sintomas}
                       onChange={(e) => alternarSintoma(s.id_sintoma, e.target.checked)} />
                {s.nombre}
              </label>
            ))}
          </div>
          {idOtro !== undefined && idOtro in valor.sintomas && (
            <>
              <label htmlFor="otro">Especifique el síntoma<Ob /></label>
              <input id="otro" maxLength={150} value={valor.sintomas[idOtro]}
                     onChange={(e) => cambiar({ sintomas: { ...valor.sintomas, [idOtro]: e.target.value } })} />
            </>
          )}
        </div>
        <div>
          <p className="subtitulo">{anterior ? "Antecedentes actuales" : "Antecedentes"}</p>
          {ANTECEDENTES.map(([campo, texto]) => {
            const cambio = anterior && anterior[campo] !== null && anterior[campo] !== valor[campo];
            return (
              <label key={campo} className="casilla" style={{ marginBottom: ".35rem" }}>
                <input type="checkbox" checked={valor[campo]} onChange={(e) => cambiar({ [campo]: e.target.checked })} />
                {texto}
                {cambio && <span className="etiqueta etiqueta--cambio">cambió</span>}
              </label>
            );
          })}
        </div>
      </div>

      <label htmlFor="observaciones">Observaciones</label>
      <textarea id="observaciones" maxLength={2000} value={valor.observaciones}
                onChange={(e) => cambiar({ observaciones: e.target.value })} />
    </>
  );
}
