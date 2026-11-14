// Aviso de que la respuesta la generó el cliente falso (CDSS_LLM=falso): no tiene valor clínico.
export default function AvisoModoPrueba() {
  return (
    <p className="aviso-modo-prueba" role="note">
      <strong>MODO DE PRUEBA: respuesta no clínica.</strong> La generó el simulador del sistema, no el modelo de
      lenguaje. No la use para decidir la atención del paciente.
    </p>
  );
}
