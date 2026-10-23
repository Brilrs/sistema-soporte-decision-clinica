import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { useAuth } from "./auth/AuthContext";
import Layout from "./components/Layout";
import EnConstruccion from "./pages/EnConstruccion";
import Inicio from "./pages/Inicio";
import Login from "./pages/Login";

function Protegida({ children }: { children: JSX.Element }) {
  const { usuario, cargando } = useAuth();
  const ubicacion = useLocation();
  if (cargando) return <p className="cargando">Cargando…</p>;
  if (!usuario) return <Navigate to="/login" replace state={{ desde: ubicacion.pathname }} />;
  return children;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route element={<Protegida><Layout /></Protegida>}>
        <Route index element={<Inicio />} />
        <Route path="pacientes" element={<EnConstruccion titulo="Pacientes" pantalla="M02 Panel de pacientes" sprint={1} />} />
        <Route path="consultas" element={<EnConstruccion titulo="Historial de consultas" pantalla="M08 Historial" sprint={1} />} />
        <Route path="reportes" element={<EnConstruccion titulo="Reportes" pantalla="M09 Reporte exportable" sprint={3} />} />
        <Route path="admin/usuarios" element={<EnConstruccion titulo="Usuarios" pantalla="M10 Gestión de usuarios" sprint={1} />} />
        <Route path="admin/conocimiento" element={<EnConstruccion titulo="Base de conocimiento" pantalla="M11 Base de conocimiento" sprint={2} />} />
        <Route path="admin/parametros" element={<EnConstruccion titulo="Parámetros clínicos" pantalla="M12 Parámetros clínicos" sprint={3} />} />
        <Route path="admin/auditoria" element={<EnConstruccion titulo="Auditoría" pantalla="M13 Auditoría y trazabilidad" sprint={3} />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
