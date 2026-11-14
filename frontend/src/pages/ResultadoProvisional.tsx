// Marcador temporal de /consultas/:id (parte E2). La parte E3 lo reemplaza por M05 (respuesta
// verificada) y M07 (evidencia insuficiente).
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { mensajeError } from "../api/cliente";
import { consultasApi } from "../api/consultas";
import type { ResultadoConsulta } from "../api/tipos_consulta";
import AvisoModoPrueba from "../components/AvisoModoPrueba";
import { ESTADOS_CONSULTA } from "../utilidades/formato";

export default function ResultadoProvisional() {
  const { id = "" } = useParams();
  const [resultado, setResultado] = useState<ResultadoConsulta | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    consultasApi.resultado(id).then(setResultado).catch((e) => setError(mensajeError(e)));
  }, [id]);

  if (!resultado) {
    return error ? <p className="alerta alerta--error" role="alert">{error}</p> : <p className="cargando">Cargando…</p>;
  }

  return (
    <section>
      <h1>Resultado de la consulta</h1>
      {resultado.modo_prueba && <AvisoModoPrueba />}
      <div className="tarjeta tarjeta--vacia">
        <p><strong>Resultado: se construye en E3.</strong></p>
        <p>Estado: <strong data-testid="estado-resultado">{ESTADOS_CONSULTA[resultado.estado] ?? resultado.estado}</strong> ({resultado.estado})</p>
        <p className="texto-tenue">Consulta {resultado.id_consulta}</p>
        <Link to={`/pacientes/${resultado.id_paciente}/consulta`}>Volver a la consulta del paciente</Link>
      </div>
    </section>
  );
}
