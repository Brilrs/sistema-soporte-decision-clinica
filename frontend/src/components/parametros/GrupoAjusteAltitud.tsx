// «Ajuste por altitud» de M12 (parte E2): un rango de altitud por fila con el ajuste (g/dL que se
// restan a la Hb observada), estado de verificación, norma y fecha. En pantalla los límites de altitud
// no se editan (la API sí admite otra forma de la tabla); solo el ajuste de cada rango, en décimas.
import { useState } from "react";
import { parametrosApi } from "../../api/parametros";
import type { EdicionAjusteAltitud, GrupoAjusteAltitud as Grupo } from "../../api/tipos_parametros";
import { fechaHora } from "../../utilidades/formato";
import EstadoVerificacion from "./EstadoVerificacion";
import SeccionEditable from "./SeccionEditable";
import { TITULOS, aDecimas, deDecimas, leerDecimas, mostrarDecimas, textoDecimas } from "./textos";
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

type Borrador = { ajuste: string; verificado: boolean }[];
const ID = "ajuste-altitud";
const altitud = (min: number, max: number) => `${min.toLocaleString("es-PE")} a ${max.toLocaleString("es-PE")} m.s.n.m.`;

export default function GrupoAjusteAltitud({ datos, puedeEditar, bloqueado, alActualizar, alRecargar, alBloquear }: Props) {
  const ed = useEdicion();
  const inicial = (): Borrador => datos.rangos.map((r) => ({ ajuste: textoDecimas(aDecimas(r.ajuste_g_dl)), verificado: r.verificado }));
  const [borrador, setBorrador] = useState<Borrador>(inicial);

  const filas = datos.rangos.map((r, i) => {
    const b = ed.editando ? borrador[i] : null;
    const ajuste = b ? leerDecimas(b.ajuste) : aDecimas(r.ajuste_g_dl);
    return { r, i, ajuste, valida: ajuste !== null, verificado: b ? b.verificado : r.verificado };
  });
  const entradaValida = filas.every((f) => f.valida);
  const cambios: FilaCambio[] = filas
    .filter((f) => f.valida && (f.ajuste !== aDecimas(f.r.ajuste_g_dl) || f.verificado !== f.r.verificado))
    .map((f) => ({ clave: String(f.i), elemento: altitud(f.r.altitud_min_msnm, f.r.altitud_max_msnm),
                   antes: `${mostrarDecimas(aDecimas(f.r.ajuste_g_dl))} g/dL`, despues: `${mostrarDecimas(f.ajuste)} g/dL`,
                   verificadoAntes: f.r.verificado, verificadoDespues: f.verificado }));

  const etiquetaCampo = (ruta: string) => {
    const m = /^rangos\.(\d+)\.(\w+)$/.exec(ruta);
    const r = m ? datos.rangos[Number(m[1])] : undefined;
    if (!m || !r) return ruta === "rangos" ? "Rangos de altitud" : ruta;
    const campo = m[2] === "ajuste_g_dl" ? "ajuste" : m[2] === "verificado" ? "verificación" : "límites";
    return `${altitud(r.altitud_min_msnm, r.altitud_max_msnm)}, ${campo}`;
  };

  const cuerpo = () => datos.rangos.map((r, i) => ({
    ...r, ajuste_g_dl: deDecimas(leerDecimas(borrador[i].ajuste)) ?? r.ajuste_g_dl, verificado: borrador[i].verificado,
  }));

  return (
    <SeccionEditable id={ID} titulo={TITULOS.ajuste_altitud} puedeEditar={puedeEditar} bloqueado={bloqueado}
                     editando={ed.editando} hayCambios={cambios.length > 0} entradaValida={entradaValida} exito={ed.exito}
                     alEditar={() => { setBorrador(inicial()); ed.editar(); }} alDescartar={ed.descartar}
                     alGuardar={ed.abrirVentana}
                     descripcion={<p className="texto-tenue parametros__nota">
                       Valor que se resta a la hemoglobina observada según la altitud de residencia, antes de clasificar.
                       Los límites de altitud no se cambian desde esta pantalla.
                     </p>}
                     ventana={ed.ventana && (
                       <VentanaGuardar<EdicionAjusteAltitud>
                         id="m12-guardar-altitud" titulo={TITULOS.ajuste_altitud} cambios={cambios} etiquetaCampo={etiquetaCampo}
                         enviar={(comun) => parametrosApi.guardarAjusteAltitud({ ...comun, version: datos.version, rangos: cuerpo() })}
                         alGuardado={(r) => { ed.terminar(mensajeExito(TITULOS.ajuste_altitud, cambios)); alActualizar(r.grupo); }}
                         alCerrar={ed.cerrarVentana} alRecargar={() => { ed.descartar(); alRecargar(); }} alBloquear={alBloquear}
                         alErroresCampo={ed.setErrores} />
                     )}>
      <table className="tabla tabla-apilable parametros__tabla">
        <thead>
          <tr>
            <th scope="col">Altitud de residencia</th>
            <th scope="col">Ajuste (g/dL)</th>
            <th scope="col">Estado</th>
            <th scope="col">Norma y referencia</th>
            <th scope="col">Rige desde</th>
          </tr>
        </thead>
        <tbody>
          {filas.map((f) => {
            const errores = ed.erroresDe(`rangos.${f.i}`);
            const idError = `${ID}-${f.i}-error`;
            const invalida = ed.editando && !f.valida;
            const descripcion = invalida || errores.length > 0 ? idError : undefined;
            const nombre = altitud(f.r.altitud_min_msnm, f.r.altitud_max_msnm);
            return (
              <tr key={f.r.id_ajuste}>
                <th scope="row" data-etiqueta="Altitud de residencia">{nombre}</th>
                <td data-etiqueta="Ajuste (g/dL)" className="parametros__numero">
                  {ed.editando ? (
                    <>
                      <label className="solo-lectores" htmlFor={`${ID}-${f.i}`}>Ajuste para {nombre} (g/dL)</label>
                      <input id={`${ID}-${f.i}`} className="parametros__campo" inputMode="decimal" autoComplete="off"
                             value={borrador[f.i]?.ajuste ?? ""} disabled={bloqueado}
                             aria-invalid={invalida || errores.length > 0 || undefined} aria-describedby={descripcion}
                             onChange={(e) => setBorrador((b) => b.map((x, j) => (j === f.i ? { ...x, ajuste: e.target.value } : x)))} />
                    </>
                  ) : mostrarDecimas(f.ajuste)}
                  {(invalida || errores.length > 0) && (
                    <p className="campo__error" id={idError}>
                      {invalida ? "Escriba un número con un decimal como máximo, por ejemplo 0,4 o 0.4. " : ""}
                      {errores.map((x) => x.mensaje).join(". ")}
                    </p>
                  )}
                </td>
                <td data-etiqueta="Estado">
                  {ed.editando ? (
                    <label className="casilla parametros__casilla">
                      <input type="checkbox" checked={borrador[f.i]?.verificado ?? false} disabled={bloqueado}
                             aria-describedby={descripcion}
                             onChange={(e) => setBorrador((b) => b.map((x, j) => (j === f.i ? { ...x, verificado: e.target.checked } : x)))} />
                      Verificado contra la norma<span className="solo-lectores">: {nombre}</span>
                    </label>
                  ) : <EstadoVerificacion verificado={f.r.verificado} />}
                </td>
                <td data-etiqueta="Norma y referencia" className="parametros__referencia">
                  {f.r.documento?.codigo ?? "Sin norma"}
                  <span className="texto-tenue"> · {f.r.referencia ?? "sin referencia"}</span>
                </td>
                <td data-etiqueta="Rige desde">{fechaHora(f.r.vigente_desde)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </SeccionEditable>
  );
}
