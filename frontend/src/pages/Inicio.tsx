// Pantalla de bienvenida tras el inicio de sesión; muestra el estado de los servicios.
import { useEffect, useState } from "react";
import { api } from "../api/cliente";
import { useAuth } from "../auth/AuthContext";

type Salud = Record<string, string>;

const NOMBRES: Record<string, string> = {
  bd_clinica: "Base de datos · componente clínico",
  bd_generacion: "Base de datos · componente de generación",
  bd_admin: "Base de datos · componente de administración",
  chromadb: "Base vectorial (ChromaDB)",
};

export default function Inicio() {
  const { usuario } = useAuth();
  const [salud, setSalud] = useState<Salud | null>(null);

  useEffect(() => {
    api<Salud>("/api/salud").then(setSalud).catch(() => setSalud({ estado: "sin conexión" }));
  }, []);

  return (
    <section>
      <h1>Hola, {usuario?.nombre_completo}</h1>
      <p className="texto-tenue">Rol: {usuario?.rol} · Permisos: {usuario?.permisos.join(", ")}</p>

      <div className="tarjeta">
        <h2>Estado de los servicios</h2>
        {!salud && <p className="texto-tenue">Consultando…</p>}
        {salud && (
          <table className="tabla">
            <tbody>
              {Object.entries(NOMBRES).map(([clave, nombre]) => (
                <tr key={clave}>
                  <td>{nombre}</td>
                  <td><span className={`estado ${salud[clave] === "ok" ? "estado--ok" : "estado--mal"}`}>{salud[clave] ?? "sin dato"}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </section>
  );
}
