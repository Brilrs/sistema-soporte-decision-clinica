// «Vigencia del tamizaje» de M12 (parte E2): los días durante los que un tamizaje sirve para evaluar,
// con su estado de verificación, norma y fecha. En edición, un campo de días con sus límites (los de la
// configuración combinados con las reglas del servidor: de 7 a 90, con confirmación por encima de 60).
import { useId, useState } from "react";
import { parametrosApi } from "../../api/parametros";
import type { EdicionVigencia, GrupoVigencia as Grupo } from "../../api/tipos_parametros";
import { fechaHora } from "../../utilidades/formato";
import EstadoVerificacion from "./EstadoVerificacion";
import SeccionEditable from "./SeccionEditable";
import { TITULOS, VIGENCIA_ADVERTENCIA, VIGENCIA_MAX, VIGENCIA_MIN } from "./textos";
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

const ID = "vigencia";
const dias = (v: string | number) => `${v} días`;

export default function GrupoVigencia({ datos, puedeEditar, bloqueado, alActualizar, alRecargar, alBloquear }: Props) {
  const ed = useEdicion();
  const [valor, setValor] = useState(datos.valor);
  const [verificado, setVerificado] = useState(datos.verificado);
  const ids = { campo: useId(), ayuda: useId(), error: useId() };
  const minimo = Math.max(VIGENCIA_MIN, datos.valor_minimo ?? VIGENCIA_MIN);
  const maximo = Math.min(VIGENCIA_MAX, datos.valor_maximo ?? VIGENCIA_MAX);

  const texto = valor.trim();
  const entero = /^\d{1,3}$/.test(texto) ? Number(texto) : null;
  const valida = entero !== null;
  const cambios: FilaCambio[] = ed.editando && valida && (String(entero) !== datos.valor || verificado !== datos.verificado)
    ? [{ clave: "valor", elemento: "Días de vigencia", antes: dias(datos.valor), despues: dias(entero),
         verificadoAntes: datos.verificado, verificadoDespues: verificado }]
    : [];
  const errores = ed.erroresDe("valor");
  const invalida = ed.editando && !valida;
  const describir = [ids.ayuda, invalida || errores.length > 0 ? ids.error : ""].join(" ").trim();

  return (
    <SeccionEditable id={ID} titulo={TITULOS.vigencia_tamizaje} puedeEditar={puedeEditar} bloqueado={bloqueado}
                     editando={ed.editando} hayCambios={cambios.length > 0} entradaValida={valida} exito={ed.exito}
                     alEditar={() => { setValor(datos.valor); setVerificado(datos.verificado); ed.editar(); }}
                     alDescartar={ed.descartar} alGuardar={ed.abrirVentana}
                     descripcion={<p className="texto-tenue parametros__nota">
                       Si el último tamizaje del paciente supera este plazo, el sistema lo avisa antes de la consulta.
                     </p>}
                     ventana={ed.ventana && entero !== null && (
                       <VentanaGuardar<EdicionVigencia>
                         id="m12-guardar-vigencia" titulo={TITULOS.vigencia_tamizaje} cambios={cambios}
                         etiquetaCampo={(ruta) => (ruta === "valor" ? "Días de vigencia" : ruta)}
                         enviar={(comun) => parametrosApi.guardarVigencia({ ...comun, version: datos.version, valor: entero, verificado })}
                         alGuardado={(r) => { ed.terminar(mensajeExito(TITULOS.vigencia_tamizaje, cambios)); alActualizar(r.grupo); }}
                         alCerrar={ed.cerrarVentana} alRecargar={() => { ed.descartar(); alRecargar(); }} alBloquear={alBloquear}
                         alErroresCampo={ed.setErrores} />
                     )}>
      <dl className="parametros__vigencia">
        <div>
          <dt>{ed.editando ? <label htmlFor={ids.campo}>Días de vigencia</label> : "Días de vigencia"}</dt>
          <dd>
            {ed.editando ? (
              <>
                <input id={ids.campo} className="parametros__campo" type="number" inputMode="numeric" min={minimo} max={maximo}
                       step={1} value={valor} disabled={bloqueado} aria-describedby={describir}
                       aria-invalid={invalida || errores.length > 0 || undefined} onChange={(e) => setValor(e.target.value)} />
                <p className="campo__ayuda" id={ids.ayuda}>
                  Entre {minimo} y {maximo} días. Más de {VIGENCIA_ADVERTENCIA} días pide confirmación escrita.
                </p>
                {(invalida || errores.length > 0) && (
                  <p className="campo__error" id={ids.error}>
                    {invalida ? "Escriba un número entero de días. " : ""}{errores.map((x) => x.mensaje).join(". ")}
                  </p>
                )}
              </>
            ) : <strong className="parametros__valor">{dias(datos.valor)}</strong>}
          </dd>
        </div>
        <div>
          <dt>Estado</dt>
          <dd>
            {ed.editando ? (
              <label className="casilla parametros__casilla">
                <input type="checkbox" checked={verificado} disabled={bloqueado}
                       onChange={(e) => setVerificado(e.target.checked)} />
                Validado por el CRED (criterio operativo, no normativo)
              </label>
            ) : <EstadoVerificacion verificado={datos.verificado} />}
          </dd>
        </div>
        <div><dt>Norma y referencia</dt><dd>{datos.documento?.codigo ?? "Sin norma"} · {datos.referencia ?? "sin referencia"}</dd></div>
        <div><dt>Rige desde</dt><dd>{fechaHora(datos.vigente_desde)}</dd></div>
      </dl>
    </SeccionEditable>
  );
}
