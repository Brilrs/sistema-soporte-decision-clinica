// Estado de un valor frente a la norma, con texto (no solo color).
export default function EstadoVerificacion({ verificado }: { verificado: boolean }) {
  return verificado
    ? <span className="etiqueta etiqueta--verificado">Verificado</span>
    : <span className="etiqueta etiqueta--pendiente">Pendiente de verificar</span>;
}
