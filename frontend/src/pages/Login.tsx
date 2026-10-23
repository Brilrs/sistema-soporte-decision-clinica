// M01 · Inicio de sesión (HU01)
import { useState, type FormEvent } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { ErrorApi, useAuth } from "../auth/AuthContext";

export default function Login() {
  const { usuario, iniciarSesion } = useAuth();
  const navegar = useNavigate();
  const ubicacion = useLocation();
  const [nombreUsuario, setNombreUsuario] = useState("");
  const [contrasena, setContrasena] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [enviando, setEnviando] = useState(false);

  if (usuario) return <Navigate to="/" replace />;

  async function enviar(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setEnviando(true);
    try {
      await iniciarSesion(nombreUsuario.trim(), contrasena);
      const destino = (ubicacion.state as { desde?: string } | null)?.desde ?? "/";
      navegar(destino, { replace: true });
    } catch (err) {
      setError(err instanceof ErrorApi ? err.message : "No se pudo conectar con el servidor");
    } finally {
      setEnviando(false);
    }
  }

  return (
    <div className="login">
      <aside className="login__marca">
        <div className="logo">CD</div>
        <h1>Sistema de Soporte a la Decisión Clínica</h1>
        <p className="login__sub">Evaluación de riesgo de anemia infantil · CRED</p>
        <ul>
          <li>Recomendaciones basadas en guías MINSA y OMS</li>
          <li>Cada afirmación con su fuente citada</li>
          <li>Datos del paciente protegidos (Ley N.° 29733)</li>
        </ul>
        <p className="login__pie">Centro de Salud San Luis · Lima</p>
      </aside>

      <main className="login__panel">
        <form className="login__form" onSubmit={enviar} noValidate>
          <h2>Iniciar sesión</h2>
          <p className="texto-tenue">Ingrese con su usuario institucional</p>

          <label htmlFor="usuario">Usuario</label>
          <input id="usuario" autoComplete="username" value={nombreUsuario}
                 onChange={(e) => setNombreUsuario(e.target.value)} required autoFocus />

          <label htmlFor="contrasena">Contraseña</label>
          <input id="contrasena" type="password" autoComplete="current-password" value={contrasena}
                 onChange={(e) => setContrasena(e.target.value)} required />

          {error && <p className="alerta alerta--error" role="alert">{error}</p>}

          <button className="boton boton--primario" type="submit"
                  disabled={enviando || !nombreUsuario || !contrasena}>
            {enviando ? "Ingresando…" : "Ingresar"}
          </button>

          <p className="aviso">
            Acceso restringido al personal autorizado. Todas las acciones quedan registradas con fines de auditoría.
          </p>
        </form>
      </main>
    </div>
  );
}
