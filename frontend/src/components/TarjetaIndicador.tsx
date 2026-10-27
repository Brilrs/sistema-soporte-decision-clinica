// Indicador del panel de pacientes (M02). Un valor nulo significa que el dato aún no existe
// (depende de las consultas del Sprint 2): se muestra «Sin datos», nunca un número inventado.
export default function TarjetaIndicador({ titulo, valor, nota, color }: {
  titulo: string;
  valor: number | string | null | undefined;
  nota?: string;
  color?: string;
}) {
  const sinDatos = valor === null || valor === undefined;
  return (
    <div className="indicador">
      <p className="indicador__titulo">{titulo}</p>
      {sinDatos
        ? <p className="indicador__valor indicador__valor--sin-datos">Sin datos</p>
        : <p className="indicador__valor" style={color ? { color } : undefined}>{valor}</p>}
      {nota && <p className="indicador__nota">{nota}</p>}
    </div>
  );
}
