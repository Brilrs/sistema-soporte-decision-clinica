// «Cambiar mi contraseña» (Sprint 3, parte I). Dos modos:
// - Obligatorio: la cuenta es nueva o su contraseña fue restablecida (debe_cambiar_contrasena). Sin
//   «Cancelar» ni menú; App redirige aquí cualquier otra dirección y el encabezado solo deja «Cerrar sesión».
// - Voluntario: desde «Cambiar contraseña» del encabezado, para todos los roles, con «Cancelar».
// Al terminar, el backend devuelve un token nuevo (las demás sesiones del usuario dejan de valer), se
// guarda y se vuelve al inicio con un aviso. Las contraseñas solo viven en el estado de esta pantalla.
import { useEffect, useRef, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { ErrorCambioContrasena } from "../api/auth";
import { mensajeError } from "../api/cliente";
import { useAuth } from "../auth/AuthContext";
import { useTituloPagina } from "../utilidades/useTituloPagina";

export const RUTA_CAMBIO_CONTRASENA = "/cambiar-contrasena";
export const AVISO_CAMBIO_CORRECTO = "Su contraseña se cambió correctamente.";
// Igual que CONTRASENA_LONGITUD_MINIMA por omisión en el backend; /api/auth/me trae el valor vigente.
const MINIMO_POR_OMISION = 10;

type Campo = "actual" | "nueva" | "confirmacion";
type Errores = Partial<Record<Campo, string>>;

const CAMPOS: Campo[] = ["actual", "nueva", "confirmacion"];
const ETIQUETAS: Record<Campo, string> = {
  actual: "Contraseña actual",
  nueva: "Nueva contraseña",
  confirmacion: "Confirme la nueva contraseña",
};
const AUTOCOMPLETAR: Record<Campo, string> = {
  actual: "current-password",
  nueva: "new-password",
  confirmacion: "new-password",
};
// Campo del backend (ErrorCambioContrasena.campo) al campo de la pantalla
const CAMPO_DEL_BACKEND = { contrasena_actual: "actual", contrasena_nueva: "nueva" } as const;

export function textoPolitica(minimo: number): string {
  return `Mínimo ${minimo} caracteres, con al menos una letra y un número`;
}

// Misma regla que cumple_politica del backend (letras y dígitos de cualquier alfabeto).
export function cumplePolitica(contrasena: string, minimo: number): boolean {
  return [...contrasena].length >= minimo && /\p{L}/u.test(contrasena) && /\p{Nd}/u.test(contrasena);
}

function validar(valores: Record<Campo, string>, minimo: number): Errores {
  const errores: Errores = {};
  if (!valores.actual) errores.actual = "Escriba su contraseña actual.";
  if (!valores.nueva) errores.nueva = "Escriba la nueva contraseña.";
  else if (!cumplePolitica(valores.nueva, minimo)) {
    errores.nueva = `La nueva contraseña no cumple la política: ${textoPolitica(minimo).toLowerCase()}.`;
  } else if (valores.nueva === valores.actual) errores.nueva = "La nueva contraseña debe ser distinta de la actual.";
  if (!valores.confirmacion) errores.confirmacion = "Repita la nueva contraseña.";
  else if (valores.confirmacion !== valores.nueva) {
    errores.confirmacion = "La confirmación no coincide con la nueva contraseña.";
  }
  return errores;
}

function CampoContrasena({ campo, valor, visible, error, ayuda, cambiar, alternar }: {
  campo: Campo;
  valor: string;
  visible: boolean;
  error?: string;
  ayuda?: string;
  cambiar: (valor: string) => void;
  alternar: () => void;
}) {
  const id = `cc-${campo}`;
  const descripcion = [ayuda && `${id}-ayuda`, error && `${id}-error`].filter(Boolean).join(" ") || undefined;
  const accion = visible ? "Ocultar" : "Mostrar";
  return (
    <div className="cambio-contrasena__campo">
      <label htmlFor={id}>{ETIQUETAS[campo]} <span className="obligatorio" aria-hidden="true">*</span></label>
      <div className="cambio-contrasena__entrada">
        <input id={id} name={campo} type={visible ? "text" : "password"} autoComplete={AUTOCOMPLETAR[campo]}
               value={valor} maxLength={200} spellCheck={false} autoCapitalize="none" required
               aria-invalid={error ? true : undefined} aria-describedby={descripcion}
               onChange={(e) => cambiar(e.target.value)} />
        <button type="button" className="boton boton--neutro cambio-contrasena__ver" aria-controls={id}
                aria-label={`${accion} ${ETIQUETAS[campo].toLowerCase()}`} onClick={alternar}>
          {accion}
        </button>
      </div>
      {ayuda && <p id={`${id}-ayuda`} className="campo__ayuda">{ayuda}</p>}
      {error && <p id={`${id}-error`} className="campo__error">{error}</p>}
    </div>
  );
}

export default function CambiarContrasena() {
  useTituloPagina("Cambiar mi contraseña");
  const { usuario, cambiarContrasena } = useAuth();
  const navegar = useNavigate();
  const [valores, setValores] = useState<Record<Campo, string>>({ actual: "", nueva: "", confirmacion: "" });
  const [visibles, setVisibles] = useState<Record<Campo, boolean>>({ actual: false, nueva: false, confirmacion: false });
  const [errores, setErrores] = useState<Errores>({});
  const [errorGeneral, setErrorGeneral] = useState<string | null>(null);
  const [enviando, setEnviando] = useState(false);
  // Cada envío con errores lleva el foco al resumen (también si los errores no cambiaron).
  const [intentoConErrores, setIntentoConErrores] = useState(0);
  const resumen = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (intentoConErrores > 0) resumen.current?.focus();
  }, [intentoConErrores]);

  if (!usuario) return null;
  const obligatorio = usuario.debe_cambiar_contrasena;
  const minimo = usuario.contrasena_longitud_minima ?? MINIMO_POR_OMISION;
  const conError = CAMPOS.filter((c) => errores[c]);

  function mostrarErrores(nuevos: Errores, general: string | null) {
    setErrores(nuevos);
    setErrorGeneral(general);
    setIntentoConErrores((n) => n + 1);
  }

  async function enviar(e: FormEvent) {
    e.preventDefault();
    if (enviando) return;
    const encontrados = validar(valores, minimo);
    if (Object.keys(encontrados).length > 0) return mostrarErrores(encontrados, null);
    setErrores({});
    setErrorGeneral(null);
    setEnviando(true);
    try {
      await cambiarContrasena(valores.actual, valores.nueva);
      navegar("/", { replace: true, state: { aviso: AVISO_CAMBIO_CORRECTO } });
    } catch (err) {
      setEnviando(false);
      if (err instanceof ErrorCambioContrasena && err.campo) {
        mostrarErrores({ [CAMPO_DEL_BACKEND[err.campo]]: err.message }, null);
      } else if (err instanceof ErrorCambioContrasena && err.estado === 401 && !err.codigoCambio) {
        // Sesión vencida o revocada: AuthContext ya la cerró y el login muestra el motivo.
      } else {
        mostrarErrores({}, mensajeError(err));
      }
    }
  }

  return (
    <section className="cambio-contrasena">
      <h1>Cambiar mi contraseña</h1>
      {obligatorio ? (
        <p className="alerta alerta--aviso cambio-contrasena__motivo">
          Por seguridad, debe cambiar la contraseña temporal antes de usar el sistema.
        </p>
      ) : (
        <p className="texto-tenue">Al cambiarla, se cerrarán las sesiones que tenga abiertas en otros equipos.</p>
      )}

      <div className="tarjeta">
        {(conError.length > 0 || errorGeneral) && (
          <div ref={resumen} className="resumen-errores" role="alert" tabIndex={-1} aria-labelledby="cc-resumen-titulo">
            <h2 id="cc-resumen-titulo" className="resumen-errores__titulo">No se pudo cambiar la contraseña</h2>
            {errorGeneral && <p className="resumen-errores__texto">{errorGeneral}</p>}
            {conError.length > 0 && (
              <ul>
                {conError.map((c) => (
                  <li key={c}>
                    <a href={`#cc-${c}`} onClick={(ev) => {
                      ev.preventDefault();
                      document.getElementById(`cc-${c}`)?.focus();
                    }}>{ETIQUETAS[c]}: {errores[c]}</a>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}

        <form onSubmit={enviar} noValidate aria-label="Cambiar mi contraseña">
          {CAMPOS.map((c) => (
            <CampoContrasena key={c} campo={c} valor={valores[c]} visible={visibles[c]} error={errores[c]}
                             ayuda={c === "nueva" ? `${textoPolitica(minimo)}.` : undefined}
                             cambiar={(v) => setValores((x) => ({ ...x, [c]: v }))}
                             alternar={() => setVisibles((x) => ({ ...x, [c]: !x[c] }))} />
          ))}

          <div className="acciones">
            {!obligatorio && (
              <button type="button" className="boton boton--neutro" disabled={enviando} onClick={() => navegar("/")}>
                Cancelar
              </button>
            )}
            <button type="submit" className="boton boton--primario" disabled={enviando}>
              {enviando ? "Cambiando…" : "Cambiar contraseña"}
            </button>
          </div>
        </form>
      </div>
    </section>
  );
}
