import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { useAuth } from "./auth/AuthContext";
import Layout from "./components/Layout";
import EditarPaciente from "./pages/EditarPaciente";
import EnConstruccion from "./pages/EnConstruccion";
import GestionUsuarios from "./pages/GestionUsuarios";
import HistorialPaciente from "./pages/HistorialPaciente";
import Inicio from "./pages/Inicio";
import Login from "./pages/Login";
import NuevoTamizaje from "./pages/NuevoTamizaje";
import PanelPacientes from "./pages/PanelPacientes";
import RegistroPaciente from "./pages/RegistroPaciente";

function Protegida({ children }: { children: JSX.Element }) {
  const { usuario, cargando } = useAuth();
  const ubicacion = useLocation();
  if (cargando) return <p className="cargando">Cargando…</p>;
  if (!usuario) return <Navigate to="/login" replace state={{ desde: ubicacion.pathname }} />;
  return children;
}

// Muestra la pantalla solo si el rol tiene alguno de los permisos; el backend vuelve a validarlo.
function ConPermiso({ permisos, children }: { permisos: string[]; children: JSX.Element }) {
  const { tienePermiso } = useAuth();
  return permisos.some(tienePermiso) ? children : <Navigate to="/" replace />;
}

// Lectura de pacientes: quien los registra o realiza consultas (incluida la coordinación CRED).
const LEER_PACIENTES = ["REGISTRAR_PACIENTE", "REALIZAR_CONSULTA"];
const REGISTRAR = ["REGISTRAR_PACIENTE"];

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route element={<Protegida><Layout /></Protegida>}>
        <Route index element={<Inicio />} />
        <Route path="pacientes" element={<ConPermiso permisos={LEER_PACIENTES}><PanelPacientes /></ConPermiso>} />
        <Route path="pacientes/nuevo" element={<ConPermiso permisos={REGISTRAR}><RegistroPaciente /></ConPermiso>} />
        <Route path="pacientes/:id/historial" element={<ConPermiso permisos={LEER_PACIENTES}><HistorialPaciente /></ConPermiso>} />
        <Route path="pacientes/:id/tamizajes/nuevo" element={<ConPermiso permisos={REGISTRAR}><NuevoTamizaje /></ConPermiso>} />
        <Route path="pacientes/:id/editar" element={<ConPermiso permisos={REGISTRAR}><EditarPaciente /></ConPermiso>} />
        <Route path="consultas" element={<ConPermiso permisos={LEER_PACIENTES}><PanelPacientes modo="historial" /></ConPermiso>} />
        <Route path="reportes" element={<EnConstruccion titulo="Reportes" pantalla="M09 Reporte exportable" sprint={3} />} />
        <Route path="admin/usuarios" element={<ConPermiso permisos={["ADMINISTRAR_USUARIOS"]}><GestionUsuarios /></ConPermiso>} />
        <Route path="admin/conocimiento" element={<EnConstruccion titulo="Base de conocimiento" pantalla="M11 Base de conocimiento" sprint={2} />} />
        <Route path="admin/parametros" element={<EnConstruccion titulo="Parámetros clínicos" pantalla="M12 Parámetros clínicos" sprint={3} />} />
        <Route path="admin/auditoria" element={<EnConstruccion titulo="Auditoría" pantalla="M13 Auditoría y trazabilidad" sprint={3} />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
