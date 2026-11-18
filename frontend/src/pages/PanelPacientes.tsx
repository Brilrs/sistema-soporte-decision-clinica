// M02 · Panel de pacientes (HU02, HU04, HU18). En modo «nueva» es el buscador de «Nueva consulta»
// (/consultas/nueva, Sprint 3 parte B): el que estaba en /consultas antes de la lista de consultas
// propias (P10). Sin indicadores ni registro; cada paciente tiene «Nueva consulta» (M04) y «Ver
// historial» (M08, el flujo que ya tenía). La búsqueda se envía por POST y el texto no se guarda en
// la URL ni en el navegador.
import { useEffect, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { mensajeError } from "../api/cliente";
import { pacientesApi, type Indicadores, type PacienteListado } from "../api/pacientes";
import { useAuth } from "../auth/AuthContext";
import Migas from "../components/Migas";
import TablaPacientes from "../components/TablaPacientes";
import TarjetaIndicador from "../components/TarjetaIndicador";
import { decimal } from "../utilidades/formato";
import { useTituloPagina } from "../utilidades/useTituloPagina";

export default function PanelPacientes({ modo = "panel" }: { modo?: "panel" | "nueva" }) {
  useTituloPagina(modo === "panel" ? "Pacientes" : "Nueva consulta");
  const { tienePermiso } = useAuth();
  const navegar = useNavigate();
  const puedeRegistrar = tienePermiso("REGISTRAR_PACIENTE") && modo === "panel";
  // «Abrir» (panel) y «Nueva consulta» (buscador de /consultas/nueva) abren la consulta clínica (M04);
  // el buscador agrega «Ver historial» (M08).
  const abrirConsulta = tienePermiso("REALIZAR_CONSULTA");
  const textoAbrir = modo === "panel" ? "Abrir" : "Nueva consulta";
  const verHistorial = modo === "nueva";
  const [texto, setTexto] = useState("");
  const [busqueda, setBusqueda] = useState<PacienteListado[] | null>(null);
  const [recientes, setRecientes] = useState<PacienteListado[] | null>(null);
  const [indicadores, setIndicadores] = useState<Indicadores | null>(null);
  const [buscando, setBuscando] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    pacientesApi.recientes().then(setRecientes).catch((e) => setError(mensajeError(e)));
    if (modo === "panel") pacientesApi.indicadores().then(setIndicadores).catch((e) => setError(mensajeError(e)));
  }, [modo]);

  async function buscar(e: FormEvent) {
    e.preventDefault();
    const termino = texto.trim();
    if (!termino) {
      setBusqueda(null);
      return;
    }
    setError(null);
    setBuscando(true);
    try {
      setBusqueda(await pacientesApi.buscar(termino));
    } catch (err) {
      setError(mensajeError(err));
    } finally {
      setBuscando(false);
    }
  }

  function limpiar() {
    setTexto("");
    setBusqueda(null);
  }

  const dias = indicadores?.dias_vigencia_tamizaje;

  return (
    <section>
      {modo === "nueva" && <Migas items={[{ texto: "Historial de consultas", ruta: "/consultas" }, { texto: "Nueva consulta" }]} />}
      <h1>{modo === "panel" ? "Pacientes" : "Nueva consulta"}</h1>
      <p className="texto-tenue">
        {modo === "panel"
          ? "Busque un paciente, registre uno nuevo o agregue el tamizaje de un nuevo control"
          : "Busque al paciente para iniciar la consulta clínica o ver la evolución de su hemoglobina y las consultas que usted le realizó"}
      </p>

      <form className="tarjeta tarjeta--ancha buscador" onSubmit={buscar} role="search">
        <input aria-label="Buscar paciente" placeholder="Buscar por DNI, N.° de historia clínica o nombre…"
               value={texto} maxLength={150} autoComplete="off" onChange={(e) => setTexto(e.target.value)} />
        <button className="boton boton--primario" type="submit" disabled={buscando}>
          {buscando ? "Buscando…" : "Buscar"}
        </button>
        {puedeRegistrar && (
          <button className="boton boton--secundario" type="button" onClick={() => navegar("/pacientes/nuevo")}>
            + Nuevo paciente
          </button>
        )}
      </form>

      {error && <p className="alerta alerta--error" role="alert">{error}</p>}

      {modo === "panel" && (
        <div className="indicadores">
          <TarjetaIndicador titulo="Evaluaciones hoy" valor={indicadores?.evaluaciones_hoy}
                            nota="Verificadas o con evidencia insuficiente, sin las de prueba" />
          <TarjetaIndicador titulo="Con anemia detectada" valor={indicadores?.con_anemia_detectada} color="var(--ambar)"
                            nota="Según el último tamizaje de cada paciente" />
          <TarjetaIndicador titulo="Controles pendientes" valor={indicadores?.controles_pendientes} color="var(--azul-700)"
                            nota={dias ? `Último tamizaje con más de ${dias} días` : undefined} />
          <TarjetaIndicador titulo="Tiempo medio de respuesta"
                            valor={indicadores?.tiempo_medio_respuesta_s == null ? null : `${decimal(indicadores.tiempo_medio_respuesta_s)} s`}
                            nota="Consultas evaluadas hoy, sin las de prueba" />
        </div>
      )}

      <div className="tarjeta tarjeta--ancha">
        <div className="encabezado-pagina">
          <h2>{busqueda ? `Resultados de la búsqueda (${busqueda.length})` : "Pacientes atendidos recientemente"}</h2>
          {busqueda && <button className="boton boton--neutro boton--chico" onClick={limpiar}>Ver recientes</button>}
        </div>
        {busqueda
          ? <TablaPacientes pacientes={busqueda} puedeRegistrar={puedeRegistrar} abrirConsulta={abrirConsulta} textoAbrir={textoAbrir} verHistorial={verHistorial}
                            vacio="No se encontró ningún paciente. Revise el DNI, el N.° de historia clínica o el nombre." />
          : recientes === null
            ? <p className="vacio">Cargando…</p>
            : <TablaPacientes pacientes={recientes} puedeRegistrar={puedeRegistrar} abrirConsulta={abrirConsulta} textoAbrir={textoAbrir} verHistorial={verHistorial}
                              vacio="Aún no hay pacientes registrados." />}
      </div>
    </section>
  );
}
