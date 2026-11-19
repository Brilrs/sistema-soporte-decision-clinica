// Entrada a M09 («Exportar reporte») desde M05, M07 y M08. Solo aparece si la consulta tiene
// resultado (VERIFICADA o EVIDENCIA_INSUFICIENTE) y el rol tiene EXPORTAR_REPORTE; si no, no se
// muestra nada (el backend respondería 409 o 403).
import { Link } from "react-router-dom";
import { useAuth } from "../../auth/AuthContext";

export const ESTADOS_EXPORTABLES = ["VERIFICADA", "EVIDENCIA_INSUFICIENTE"];

export function puedeExportar(estado: string, tienePermiso: (p: string) => boolean): boolean {
  return ESTADOS_EXPORTABLES.includes(estado) && tienePermiso("EXPORTAR_REPORTE");
}

type Props = {
  idConsulta: string;
  estado: string;
  texto?: string;
  etiqueta?: string; // nombre accesible cuando el texto visible no basta (filas de M08)
  chico?: boolean;
};

export default function BotonExportarReporte({ idConsulta, estado, texto = "Exportar reporte", etiqueta, chico }: Props) {
  const { tienePermiso } = useAuth();
  if (!puedeExportar(estado, tienePermiso)) return null;
  return (
    <Link className={`boton boton--secundario boton--auto${chico ? " boton--chico" : ""}`} to={`/consultas/${idConsulta}/reporte`}
          aria-label={etiqueta}>
      {texto}
    </Link>
  );
}
