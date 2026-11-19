// «Puntos de corte de hemoglobina» de M12 (parte E2). Por tramo de edad (6 a 23 y 24 a 59 meses), una
// fila por categoría con su límite inferior y superior, estado de verificación, norma y fecha. En
// edición solo se escribe el límite superior: el inferior de cada categoría se calcula (el superior de
// la categoría más severa anterior más 0,1), la más severa no tiene inferior y «sin anemia» no tiene
// superior. Todo en décimas enteras. El PUT reenvía los tramos tal como se leyeron, con los valores
// nuevos, su verificado y la versión del grupo.
import { useState } from "react";
import { parametrosApi } from "../../api/parametros";
import type { EdicionPuntosCorte, GrupoPuntosCorte as Grupo, PuntoCorte } from "../../api/tipos_parametros";
import { fechaHora } from "../../utilidades/formato";
import EstadoVerificacion from "./EstadoVerificacion";
import SeccionEditable from "./SeccionEditable";
import { TITULOS, aDecimas, categoria, deDecimas, leerDecimas, mostrarDecimas, textoDecimas } from "./textos";
import { mensajeExito, useEdicion } from "./useEdicion";
import VentanaGuardar, { type FilaCambio } from "./VentanaGuardar";

type Props = {
  datos: Grupo;
  puedeEditar: boolean;
  bloqueado: boolean;
  alActualizar: (g: Grupo) => void;
  alRecargar: () => void;
  alBloquear: () => void;
};

type Borrador = Record<string, { superior: string; verificado: boolean }>;
type Calculada = { c: PuntoCorte; j: number; min: number | null; max: number | null; valida: boolean; verificado: boolean };

const ID = "puntos-corte";
const clave = (i: number, j: number) => `${i}-${j}`;
const SIN_ANEMIA = "SIN_ANEMIA";
const ORDEN = ["SIN_ANEMIA", "ANEMIA_LEVE", "ANEMIA_MODERADA", "ANEMIA_SEVERA"];

function rango(min: number | null, max: number | null): string {
  if (min === null && max === null) return "sin límites";
  if (min === null) return `hasta ${mostrarDecimas(max)} g/dL`;
  if (max === null) return `desde ${mostrarDecimas(min)} g/dL`;
  return `${mostrarDecimas(min)} a ${mostrarDecimas(max)} g/dL`;
}

// Calcula los límites de un tramo a partir del borrador: de la más severa a «sin anemia», el inferior
// de cada categoría es el superior de la anterior más una décima.
export function calcularTramo(categorias: PuntoCorte[], i: number, borrador: Borrador | null): Calculada[] {
  const porSeveridad = categorias.map((c, j) => ({ c, j }))
    .sort((a, b) => ORDEN.indexOf(b.c.categoria) - ORDEN.indexOf(a.c.categoria));
  const salida: Calculada[] = [];
  let anterior: number | null | undefined;
  for (const { c, j } of porSeveridad) {
    const b = borrador?.[clave(i, j)];
    const max = c.categoria === SIN_ANEMIA ? null : b ? leerDecimas(b.superior) : aDecimas(c.hb_max_g_dl);
    const valida = c.categoria === SIN_ANEMIA || max !== null;
    const min = anterior === undefined ? null : anterior === null ? null : anterior + 1;
    salida.push({ c, j, min: anterior === undefined ? aDecimas(c.hb_min_g_dl) : min, max, valida,
                  verificado: b ? b.verificado : c.verificado });
    anterior = max;
  }
  return salida.sort((a, b) => a.j - b.j);
}

function borradorInicial(datos: Grupo): Borrador {
  const b: Borrador = {};
  datos.tramos.forEach((t, i) => t.categorias.forEach((c, j) => {
    b[clave(i, j)] = { superior: textoDecimas(aDecimas(c.hb_max_g_dl)), verificado: c.verificado };
  }));
  return b;
}

export default function GrupoPuntosCorte({ datos, puedeEditar, bloqueado, alActualizar, alRecargar, alBloquear }: Props) {
  const ed = useEdicion();
  const [borrador, setBorrador] = useState<Borrador>(() => borradorInicial(datos));
  const tramos = datos.tramos.map((t, i) => ({ t, i, filas: calcularTramo(t.categorias, i, ed.editando ? borrador : null) }));

  const cambios: FilaCambio[] = [];
  let entradaValida = true;
  for (const { t, i, filas } of tramos) {
    for (const f of filas) {
      entradaValida &&= f.valida;
      const minAntes = aDecimas(f.c.hb_min_g_dl);
      const maxAntes = aDecimas(f.c.hb_max_g_dl);
      if (f.valida && (f.min !== minAntes || f.max !== maxAntes || f.verificado !== f.c.verificado)) {
        cambios.push({ clave: clave(i, f.j), elemento: `${t.edad_min_meses} a ${t.edad_max_meses} meses · ${categoria(f.c.categoria)}`,
                       antes: rango(minAntes, maxAntes), despues: rango(f.min, f.max),
                       verificadoAntes: f.c.verificado, verificadoDespues: f.verificado });
      }
    }
  }

  const etiquetaCampo = (ruta: string) => {
    const m = /^tramos\.(\d+)\.categorias\.(\d+)\.(\w+)$/.exec(ruta);
    if (!m) return ruta === "tramos" ? "Tramos de edad" : ruta;
    const t = datos.tramos[Number(m[1])];
    const c = t?.categorias[Number(m[2])];
    const campo = m[3] === "hb_min_g_dl" ? "límite inferior" : m[3] === "hb_max_g_dl" ? "límite superior" : "verificación";
    return t && c ? `${t.edad_min_meses} a ${t.edad_max_meses} meses, ${categoria(c.categoria)}, ${campo}` : ruta;
  };

  const editar = () => {
    setBorrador(borradorInicial(datos));
    ed.editar();
  };

  const cuerpo = () => datos.tramos.map((t, i) => ({
    ...t,
    categorias: calcularTramo(t.categorias, i, borrador).map((f) => ({
      ...f.c, hb_min_g_dl: deDecimas(f.min), hb_max_g_dl: deDecimas(f.max), verificado: f.verificado,
    })),
  }));

  return (
    <SeccionEditable id={ID} titulo={TITULOS.puntos_corte} puedeEditar={puedeEditar} bloqueado={bloqueado}
                     editando={ed.editando} hayCambios={cambios.length > 0} entradaValida={entradaValida} exito={ed.exito}
                     alEditar={editar} alDescartar={ed.descartar} alGuardar={ed.abrirVentana}
                     descripcion={<p className="texto-tenue parametros__nota">
                       Hemoglobina a nivel del mar, en g/dL. Los tramos de edad son fijos. En edición solo se escribe el
                       límite superior: el inferior de la categoría siguiente se calcula solo (superior más 0.1).
                     </p>}
                     ventana={ed.ventana && (
                       <VentanaGuardar<EdicionPuntosCorte>
                         id="m12-guardar-puntos" titulo={TITULOS.puntos_corte} cambios={cambios} etiquetaCampo={etiquetaCampo}
                         enviar={(comun) => parametrosApi.guardarPuntosCorte({ ...comun, version: datos.version, tramos: cuerpo() })}
                         alGuardado={(r) => { ed.terminar(mensajeExito(TITULOS.puntos_corte, cambios)); alActualizar(r.grupo); }}
                         alCerrar={ed.cerrarVentana} alRecargar={() => { ed.descartar(); alRecargar(); }} alBloquear={alBloquear}
                         alErroresCampo={ed.setErrores} />
                     )}>
      {tramos.map(({ t, i, filas }) => (
        <div key={i} className="parametros__tramo">
          <h3 className="parametros__subtitulo">{t.edad_min_meses} a {t.edad_max_meses} meses</h3>
          <table className="tabla tabla-apilable parametros__tabla">
            <thead>
              <tr>
                <th scope="col">Clasificación</th>
                <th scope="col">Límite inferior</th>
                <th scope="col">Límite superior</th>
                <th scope="col">Estado</th>
                <th scope="col">Norma y referencia</th>
                <th scope="col">Rige desde</th>
              </tr>
            </thead>
            <tbody>
              {filas.map((f) => {
                const k = clave(i, f.j);
                const errores = ed.erroresDe(`tramos.${i}.categorias.${f.j}`);
                const idError = `${ID}-${k}-error`;
                const invalida = ed.editando && !f.valida;
                const descripcion = invalida || errores.length > 0 ? idError : undefined;
                const nombre = `${categoria(f.c.categoria)}, ${t.edad_min_meses} a ${t.edad_max_meses} meses`;
                return (
                  <tr key={k}>
                    <th scope="row" data-etiqueta="Clasificación">{categoria(f.c.categoria)}</th>
                    <td data-etiqueta="Límite inferior" className="parametros__numero">{mostrarDecimas(f.min)}</td>
                    <td data-etiqueta="Límite superior" className="parametros__numero">
                      {ed.editando && f.c.categoria !== SIN_ANEMIA ? (
                        <>
                          <label className="solo-lectores" htmlFor={`${ID}-${k}`}>Límite superior de {nombre} (g/dL)</label>
                          <input id={`${ID}-${k}`} className="parametros__campo" inputMode="decimal" autoComplete="off"
                                 value={borrador[k]?.superior ?? ""} disabled={bloqueado}
                                 aria-invalid={invalida || errores.length > 0 || undefined} aria-describedby={descripcion}
                                 onChange={(e) => setBorrador((b) => ({ ...b, [k]: { ...b[k], superior: e.target.value } }))} />
                        </>
                      ) : mostrarDecimas(f.max)}
                      {(invalida || errores.length > 0) && (
                        <p className="campo__error" id={idError}>
                          {invalida ? "Escriba un número con un decimal como máximo, por ejemplo 9,4 o 9.4. " : ""}
                          {errores.map((x) => x.mensaje).join(". ")}
                        </p>
                      )}
                    </td>
                    <td data-etiqueta="Estado">
                      {ed.editando ? (
                        <label className="casilla parametros__casilla">
                          <input type="checkbox" checked={borrador[k]?.verificado ?? false} disabled={bloqueado}
                                 aria-describedby={descripcion}
                                 onChange={(e) => setBorrador((b) => ({ ...b, [k]: { ...b[k], verificado: e.target.checked } }))} />
                          Verificado contra la norma<span className="solo-lectores">: {nombre}</span>
                        </label>
                      ) : <EstadoVerificacion verificado={f.c.verificado} />}
                    </td>
                    <td data-etiqueta="Norma y referencia" className="parametros__referencia">
                      {f.c.documento?.codigo ?? "Sin norma"}
                      <span className="texto-tenue"> · {f.c.referencia ?? "sin referencia"}</span>
                    </td>
                    <td data-etiqueta="Rige desde">{fechaHora(f.c.vigente_desde)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ))}
    </SeccionEditable>
  );
}
