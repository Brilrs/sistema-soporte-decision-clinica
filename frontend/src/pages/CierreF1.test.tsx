// Pruebas de la parte F1 en la interfaz: aviso de cambio de grupo de edad en M05 (P6) e
// indicadores de M02 con las consultas reales (P2). La continuación de M15 por la ruta nueva (P5)
// está en VentanasConsulta.test.tsx y el aviso de la nota filtrada (P1) en DecisionClinica.test.tsx.
import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import App from "../App";
import { guardarToken } from "../api/cliente";
import type { ResultadoConsulta, TramoEdad } from "../api/tipos_consulta";
import { AuthProvider } from "../auth/AuthContext";
import { avisoCambioDeTramo } from "../consulta/textos";
import {
  FICHA_FIXTURE,
  GET_RESULTADO,
  ID_CONSULTA,
  ID_PACIENTE_FIXTURE,
  respuestaJson,
  resultadoFixture,
  simularBackend,
} from "../pruebas/simulador";

function renderizar(ruta: string) {
  guardarToken("token-de-prueba");
  return render(
    <MemoryRouter initialEntries={[ruta]}>
      <AuthProvider>
        <App />
      </AuthProvider>
    </MemoryRouter>,
  );
}

const DE_5_A_6: TramoEdad = {
  edad_meses_tamizaje: 5, edad_meses_consulta: 6, tramo_tamizaje: null,
  tramo_consulta: { edad_min_meses: 6, edad_max_meses: 23 }, cambio: true,
};

function conResultado(cambios: Partial<ResultadoConsulta>, sexo: "M" | "F") {
  simularBackend({
    [GET_RESULTADO]: () => respuestaJson(200, { ...resultadoFixture("VERIFICADA"), ...cambios }),
    [`GET /api/pacientes/${ID_PACIENTE_FIXTURE}`]: () => respuestaJson(200, { ...FICHA_FIXTURE, sexo }),
  });
  renderizar(`/consultas/${ID_CONSULTA}`);
}

describe("M05 · aviso de cambio de grupo de edad (P6)", () => {
  it("con cambio de tramo muestra un aviso breve, sin alarma, con las dos edades", async () => {
    conResultado({ tramo_edad: DE_5_A_6 }, "M");
    // La ficha (con el sexo) llega después del resultado: hasta entonces el aviso dice «El niño o la
    // niña». Se espera la ficha para no depender de cuál de las dos respuestas resuelve primero.
    await screen.findByRole("heading", { level: 1, name: FICHA_FIXTURE.nombres_apellidos });
    const aviso = await screen.findByText(/pasó a otro grupo de edad/);
    expect(aviso).toHaveAttribute("role", "note");
    expect(aviso).toHaveClass("alerta--aviso");
    expect(aviso).not.toHaveClass("alerta--error");
    expect(aviso).toHaveTextContent(
      "El niño pasó a otro grupo de edad desde el tamizaje (5 meses entonces, 6 meses en esta consulta). " +
      "Verifique que la recomendación aplique a su edad actual.");
  });

  it("habla de «la niña» cuando la ficha es de sexo femenino (de 23 a 24 meses)", async () => {
    conResultado({ tramo_edad: { edad_meses_tamizaje: 23, edad_meses_consulta: 24,
      tramo_tamizaje: { edad_min_meses: 6, edad_max_meses: 23 }, tramo_consulta: { edad_min_meses: 24, edad_max_meses: 59 },
      cambio: true } }, "F");
    expect(await screen.findByText(/^La niña pasó a otro grupo de edad desde el tamizaje \(23 meses entonces, 24 meses/))
      .toBeInTheDocument();
  });

  it("sin cambio de tramo no muestra el aviso", async () => {
    conResultado({}, "M");  // el fixture trae cambio: false
    await screen.findByRole("heading", { name: "Recomendación clínica" });
    expect(screen.queryByText(/pasó a otro grupo de edad/)).not.toBeInTheDocument();
  });

  it("también aparece en los estados sin recomendación, como evidencia insuficiente", async () => {
    simularBackend({
      [GET_RESULTADO]: () => respuestaJson(200, { ...resultadoFixture("EVIDENCIA_INSUFICIENTE"), tramo_edad: DE_5_A_6 }),
    });
    renderizar(`/consultas/${ID_CONSULTA}`);
    expect(await screen.findByText(/pasó a otro grupo de edad/)).toBeInTheDocument();
  });

  it("el texto se arma sin tecnicismos y con singular para un mes", () => {
    expect(avisoCambioDeTramo(null, 1, 2)).toBe(
      "El niño o la niña pasó a otro grupo de edad desde el tamizaje (1 mes entonces, 2 meses en esta consulta). " +
      "Verifique que la recomendación aplique a su edad actual.");
  });
});

describe("M02 · indicadores de las consultas (P2)", () => {
  function conIndicadores(evaluaciones: number | null, tiempo: number | null) {
    simularBackend({
      "GET /api/pacientes": () => respuestaJson(200, []),
      "GET /api/pacientes/indicadores": () => respuestaJson(200, {
        evaluaciones_hoy: evaluaciones, con_anemia_detectada: 3, controles_pendientes: 2,
        tiempo_medio_respuesta_s: tiempo, dias_vigencia_tamizaje: 30 }),
    });
    renderizar("/pacientes");
  }
  const tarjeta = (titulo: string) => screen.getByText(titulo).closest(".indicador") as HTMLElement;

  it("muestra las evaluaciones del día y el tiempo medio con su unidad", async () => {
    conIndicadores(2, 6.8);
    await screen.findByText("6.8 s");
    expect(within(tarjeta("Evaluaciones hoy")).getByText("2")).toBeInTheDocument();
    expect(within(tarjeta("Evaluaciones hoy")).getByText(/sin las de prueba/)).toBeInTheDocument();
    expect(within(tarjeta("Tiempo medio de respuesta")).getByText("6.8 s")).toBeInTheDocument();
  });

  it("sin consultas reales en el día muestra «Sin datos» en los dos", async () => {
    conIndicadores(null, null);
    await screen.findByText("Con anemia detectada");
    expect(within(tarjeta("Evaluaciones hoy")).getByText("Sin datos")).toBeInTheDocument();
    expect(within(tarjeta("Tiempo medio de respuesta")).getByText("Sin datos")).toBeInTheDocument();
  });
});
