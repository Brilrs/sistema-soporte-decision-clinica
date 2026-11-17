// «Cargar guía» de M11: formulario en una ventana (Modal) con el PDF y sus metadatos. Solo nivel 2
// desde la pantalla (el nivel 1 se ve deshabilitado con su nota). Valida en el cliente lo evidente
// y muestra cada error de la API junto a su campo: 409 (duplicado, con el título existente, o cupo
// de trabajos lleno), 413, 415 y 422. Con error la ventana sigue abierta; al cargar bien se cierra.
import { useRef, useState, type FormEvent, type RefObject } from "react";
import { conocimientoApi, type DocumentoCreado, type MetadatosGuia } from "../../api/conocimiento";
import Modal from "../Modal";
import {
  AVISO_P14, ENTIDADES, IDIOMAS, NOTA_NIVEL_1, ORDEN_CAMPOS, TIPOS_DOCUMENTO, erroresDeLaApi, validarGuia,
  type CampoGuia, type ErroresGuia,
} from "./textos";

const VACIOS: MetadatosGuia = {
  titulo: "", codigo_documento: "", entidad_emisora: "", tipo_documento: "", anio_publicacion: "", idioma: "es", nivel: "2",
  pagina_inicio_cuerpo: "", pagina_fin_cuerpo: "",
};

type Props = {
  alCerrar: () => void;
  alCargar: (creado: DocumentoCreado) => void;
  focoAlCerrar?: RefObject<HTMLElement | null>;
};

// Id del control que recibe el foco por cada campo con error.
const CONTROL: Record<CampoGuia, string> = {
  archivo: "guia-archivo", nivel: "guia-nivel-2", titulo: "guia-titulo", codigo_documento: "guia-codigo",
  entidad_emisora: "guia-entidad", tipo_documento: "guia-tipo", anio_publicacion: "guia-anio", idioma: "guia-idioma",
  paginas: "guia-pagina-inicio", pagina_inicio_cuerpo: "guia-pagina-inicio", pagina_fin_cuerpo: "guia-pagina-fin",
};

export default function VentanaCargarGuia({ alCerrar, alCargar, focoAlCerrar }: Props) {
  const [datos, setDatos] = useState<MetadatosGuia>(VACIOS);
  const [archivo, setArchivo] = useState<File | null>(null);
  const [errores, setErrores] = useState<ErroresGuia>({});
  const [enviando, setEnviando] = useState(false);
  const formulario = useRef<HTMLFormElement>(null);
  const errorGeneral = useRef<HTMLParagraphElement>(null);

  const cambiar = (campo: keyof MetadatosGuia, valor: string) => {
    setDatos((d) => ({ ...d, [campo]: valor }));
    const clave: CampoGuia = campo.startsWith("pagina_") ? "paginas" : campo;
    if (errores[clave]) setErrores((e) => ({ ...e, [clave]: undefined }));
  };

  function enfocarPrimero(e: ErroresGuia) {
    const primero = ORDEN_CAMPOS.find((c) => e[c]);
    // Tras el render que muestra los mensajes.
    window.setTimeout(() => {
      if (primero) formulario.current?.querySelector<HTMLElement>(`#${CONTROL[primero]}`)?.focus();
      else if (e.general) errorGeneral.current?.focus();
    }, 0);
  }

  async function enviar(ev: FormEvent) {
    ev.preventDefault();
    if (enviando) return;
    const locales = validarGuia(archivo, datos);
    if (Object.values(locales).some(Boolean)) {
      setErrores(locales);
      enfocarPrimero(locales);
      return;
    }
    setErrores({});
    setEnviando(true);
    try {
      const creado = await conocimientoApi.cargar(archivo as File, datos);
      alCargar(creado);
    } catch (err) {
      const e = erroresDeLaApi(err);
      setErrores(e);
      setEnviando(false);
      enfocarPrimero(e);
    }
  }

  // Atributos de accesibilidad de un control con su ayuda y su posible error.
  const describir = (campo: CampoGuia, ayuda?: string) => {
    const ids = [ayuda, errores[campo] ? `${CONTROL[campo]}-error` : null].filter(Boolean).join(" ");
    return { "aria-invalid": errores[campo] ? true : undefined, "aria-describedby": ids || undefined };
  };
  const mensaje = (campo: CampoGuia) =>
    errores[campo] ? <p className="campo__error" id={`${CONTROL[campo]}-error`}>{errores[campo]}</p> : null;

  return (
    <Modal id="m11-cargar" titulo="Cargar guía clínica (PDF)" icono="↑" alCerrar={alCerrar} cerrable={!enviando}
           focoAlCerrar={focoAlCerrar}
           descripcion={<p>El texto se extrae, se fragmenta y se indexa automáticamente. Las guías de nivel 2 sirven de respaldo
             metodológico y no se citan al profesional.</p>}>
      <p className="alerta alerta--aviso guia__aviso" id="guia-aviso-p14">{AVISO_P14}</p>
      <form ref={formulario} onSubmit={enviar} noValidate>
        <fieldset className="modal__campos" disabled={enviando}>
          <label htmlFor="guia-archivo">Archivo PDF <span className="obligatorio" aria-hidden="true">*</span></label>
          <input id="guia-archivo" type="file" accept="application/pdf,.pdf" required
                 {...describir("archivo", "guia-archivo-ayuda")}
                 onChange={(e) => { setArchivo(e.target.files?.[0] ?? null); setErrores((x) => ({ ...x, archivo: undefined })); }} />
          <p className="campo__ayuda" id="guia-archivo-ayuda">Hasta 20 MB.</p>
          {mensaje("archivo")}

          <fieldset className="guia__nivel">
            <legend>Nivel</legend>
            <label className="casilla guia__opcion guia__opcion--deshabilitada">
              <input type="radio" name="nivel" value="1" disabled aria-describedby="guia-nota-nivel-1" />
              Nivel 1 · citable
            </label>
            <p className="campo__ayuda guia__nota-nivel" id="guia-nota-nivel-1">{NOTA_NIVEL_1}</p>
            <label className="casilla guia__opcion">
              <input id="guia-nivel-2" type="radio" name="nivel" value="2" checked={datos.nivel === "2"}
                     aria-describedby={errores.nivel ? "guia-nivel-2-error" : undefined}
                     onChange={() => cambiar("nivel", "2")} />
              Nivel 2 · metodológico
            </label>
            {mensaje("nivel")}
          </fieldset>

          <label htmlFor="guia-titulo">Título <span className="obligatorio" aria-hidden="true">*</span></label>
          <input id="guia-titulo" value={datos.titulo} maxLength={255} required autoComplete="off" {...describir("titulo")}
                 onChange={(e) => cambiar("titulo", e.target.value)} />
          {mensaje("titulo")}

          <label htmlFor="guia-codigo">Código <span className="texto-tenue">(opcional)</span></label>
          <input id="guia-codigo" value={datos.codigo_documento} maxLength={80} autoComplete="off"
                 placeholder="p. ej., NTS 213-MINSA/DGIESP-2024" {...describir("codigo_documento")}
                 onChange={(e) => cambiar("codigo_documento", e.target.value)} />
          {mensaje("codigo_documento")}

          <div className="rejilla rejilla--2 guia__rejilla">
            <div>
              <label htmlFor="guia-entidad">Entidad emisora <span className="obligatorio" aria-hidden="true">*</span></label>
              <select id="guia-entidad" value={datos.entidad_emisora} required {...describir("entidad_emisora")}
                      onChange={(e) => cambiar("entidad_emisora", e.target.value)}>
                <option value="" disabled>Seleccione</option>
                {ENTIDADES.map((x) => <option key={x.valor} value={x.valor}>{x.texto}</option>)}
              </select>
              {mensaje("entidad_emisora")}
            </div>
            <div>
              <label htmlFor="guia-tipo">Tipo de documento <span className="obligatorio" aria-hidden="true">*</span></label>
              <select id="guia-tipo" value={datos.tipo_documento} required {...describir("tipo_documento")}
                      onChange={(e) => cambiar("tipo_documento", e.target.value)}>
                <option value="" disabled>Seleccione</option>
                {TIPOS_DOCUMENTO.map((x) => <option key={x.valor} value={x.valor}>{x.texto}</option>)}
              </select>
              {mensaje("tipo_documento")}
            </div>
            <div>
              <label htmlFor="guia-anio">Año de publicación <span className="obligatorio" aria-hidden="true">*</span></label>
              <input id="guia-anio" inputMode="numeric" value={datos.anio_publicacion} maxLength={4} required autoComplete="off"
                     placeholder="p. ej., 2024" {...describir("anio_publicacion")}
                     onChange={(e) => cambiar("anio_publicacion", e.target.value)} />
              {mensaje("anio_publicacion")}
            </div>
            <div>
              <label htmlFor="guia-idioma">Idioma <span className="obligatorio" aria-hidden="true">*</span></label>
              <select id="guia-idioma" value={datos.idioma} required {...describir("idioma")}
                      onChange={(e) => cambiar("idioma", e.target.value)}>
                {IDIOMAS.map((x) => <option key={x.valor} value={x.valor}>{x.texto}</option>)}
              </select>
              {mensaje("idioma")}
            </div>
          </div>

          <fieldset className="guia__paginas" aria-describedby="guia-paginas-ayuda">
            <legend>Páginas del cuerpo <span className="texto-tenue">(opcional)</span></legend>
            <p className="campo__ayuda" id="guia-paginas-ayuda">
              Para no indexar portada, índice ni anexos. Si las deja vacías se indexan todas las páginas.
            </p>
            <div className="rejilla rejilla--2 guia__rejilla">
              <div>
                <label htmlFor="guia-pagina-inicio">Desde la página</label>
                <input id="guia-pagina-inicio" inputMode="numeric" value={datos.pagina_inicio_cuerpo} maxLength={5} autoComplete="off"
                       {...describir("paginas")} onChange={(e) => cambiar("pagina_inicio_cuerpo", e.target.value)} />
              </div>
              <div>
                <label htmlFor="guia-pagina-fin">Hasta la página</label>
                <input id="guia-pagina-fin" inputMode="numeric" value={datos.pagina_fin_cuerpo} maxLength={5} autoComplete="off"
                       aria-invalid={errores.paginas ? true : undefined}
                       aria-describedby={errores.paginas ? "guia-pagina-inicio-error" : undefined}
                       onChange={(e) => cambiar("pagina_fin_cuerpo", e.target.value)} />
              </div>
            </div>
            {mensaje("paginas")}
          </fieldset>
        </fieldset>

        {errores.general && (
          <p ref={errorGeneral} tabIndex={-1} className="alerta alerta--error" role="alert">{errores.general}</p>
        )}

        <div className="acciones">
          <button type="button" className="boton boton--neutro" onClick={alCerrar} disabled={enviando}>Cancelar</button>
          <button type="submit" className="boton boton--primario" disabled={enviando} aria-describedby="guia-aviso-p14">
            {enviando ? "Cargando…" : "Cargar guía"}
          </button>
        </div>
      </form>
    </Modal>
  );
}
