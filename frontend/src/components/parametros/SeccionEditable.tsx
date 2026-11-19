// Armazón de un grupo editable de M12 (parte E2): título, botones «Editar», «Descartar» y «Guardar
// cambios» con el mismo patrón en los tres grupos, el aviso de éxito y la ventana de confirmación.
// «Editar» solo se habilita con puede_editar y sin modo de evaluación; sin puede_editar no hay
// botones. «Guardar cambios» queda deshabilitado mientras no haya cambios válidos.
import { useEffect, useRef, type ReactNode } from "react";
import { AVISO_EVALUACION } from "./textos";

type Props = {
  id: string;
  titulo: string;
  descripcion?: ReactNode;
  puedeEditar: boolean;
  bloqueado: boolean;
  editando: boolean;
  hayCambios: boolean;
  entradaValida: boolean;
  exito: string | null;
  alEditar: () => void;
  alDescartar: () => void;
  alGuardar: () => void;
  children: ReactNode;
  ventana: ReactNode;
};

export default function SeccionEditable({ id, titulo, descripcion, puedeEditar, bloqueado, editando, hayCambios, entradaValida,
                                          exito, alEditar, alDescartar, alGuardar, children, ventana }: Props) {
  const avisoExito = useRef<HTMLParagraphElement>(null);
  const motivoBloqueo = `${id}-bloqueo`;

  useEffect(() => {
    if (exito) avisoExito.current?.focus();
  }, [exito]);

  return (
    <section className="tarjeta tarjeta--ancha parametros__seccion" aria-labelledby={`${id}-titulo`}>
      <div className="parametros__cabecera-seccion">
        <h2 id={`${id}-titulo`}>{titulo}</h2>
        {puedeEditar && !editando && (
          <button type="button" className="boton boton--secundario boton--auto" disabled={bloqueado} onClick={alEditar}
                  aria-describedby={bloqueado ? motivoBloqueo : undefined}>
            Editar
          </button>
        )}
      </div>
      {bloqueado && puedeEditar && <p className="campo__ayuda" id={motivoBloqueo}>{AVISO_EVALUACION}.</p>}
      {descripcion}
      {exito && (
        <p ref={avisoExito} tabIndex={-1} className="alerta alerta--exito parametros__exito" role="status">{exito}</p>
      )}
      {children}
      {editando && (
        <div className="acciones parametros__acciones">
          <button type="button" className="boton boton--neutro" onClick={alDescartar}>Descartar</button>
          <button type="button" className="boton boton--primario" disabled={!hayCambios || !entradaValida || bloqueado}
                  onClick={alGuardar}>
            Guardar cambios
          </button>
        </div>
      )}
      {ventana}
    </section>
  );
}
