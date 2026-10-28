// M10 · Gestión de usuarios (HU11). Lista de cuentas y panel para crear o editar.
// Las cuentas no se eliminan: se desactivan. Las contraseñas las genera el sistema y se
// muestran una sola vez (AvisoContrasena). El backend vuelve a validar todas las reglas.
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { mensajeError } from "../api/cliente";
import { usuariosApi, type RolesYPermisos, type UsuarioCambios, type UsuarioCuenta } from "../api/usuarios";
import { useAuth } from "../auth/AuthContext";
import AvisoContrasena from "../components/AvisoContrasena";
import { momentoRelativo } from "../utilidades/formato";

// Textos cortos de los permisos (como en el prototipo); si llega uno nuevo se usa su descripción.
const PERMISOS: Record<string, string> = {
  REGISTRAR_PACIENTE: "Registrar pacientes",
  REALIZAR_CONSULTA: "Realizar consultas",
  EXPORTAR_REPORTE: "Exportar reportes",
  CONFIGURAR_PARAMETROS: "Configurar parámetros",
  ADMINISTRAR_GUIAS: "Administrar guías",
  ADMINISTRAR_USUARIOS: "Administrar usuarios",
  VER_AUDITORIA: "Ver auditoría",
};

const ESTADOS: Record<string, { texto: string; clase: string }> = {
  ACTIVO: { texto: "Activo", clase: "estado--ok" },
  INACTIVO: { texto: "Inactivo", clase: "estado--inactivo" },
  BLOQUEADO: { texto: "Bloqueado", clase: "estado--mal" },
};

// «Enfermera CRED» -> «enfermera-cred», para el color de la etiqueta del rol.
function claseRol(nombre: string): string {
  return nombre.normalize("NFD").replace(/\p{Diacritic}/gu, "").toLowerCase().replace(/\s+/g, "-");
}

type Form = { nombre_completo: string; nombre_usuario: string; correo_institucional: string; id_rol: string };
type Panel = { modo: "nuevo" } | { modo: "editar"; id: string };
type Aviso = { titulo: string; nombreUsuario: string; contrasena: string };

const FORM_VACIO: Form = { nombre_completo: "", nombre_usuario: "", correo_institucional: "", id_rol: "" };

function formDesde(u: UsuarioCuenta): Form {
  return { nombre_completo: u.nombre_completo, nombre_usuario: u.nombre_usuario,
           correo_institucional: u.correo_institucional ?? "", id_rol: String(u.id_rol) };
}

export default function GestionUsuarios() {
  const { usuario: yo } = useAuth();
  const [usuarios, setUsuarios] = useState<UsuarioCuenta[] | null>(null);
  const [catalogo, setCatalogo] = useState<RolesYPermisos | null>(null);
  const [panel, setPanel] = useState<Panel | null>(null);
  const [form, setForm] = useState<Form>(FORM_VACIO);
  const [aviso, setAviso] = useState<Aviso | null>(null);
  const [mensaje, setMensaje] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [errorCarga, setErrorCarga] = useState<string | null>(null);
  const [enviando, setEnviando] = useState(false);
  const cerrarAviso = useCallback(() => setAviso(null), []);

  useEffect(() => {
    usuariosApi.listar().then(setUsuarios).catch((e) => setErrorCarga(mensajeError(e)));
    usuariosApi.roles().then(setCatalogo).catch((e) => setErrorCarga(mensajeError(e)));
  }, []);

  const seleccionado = panel?.modo === "editar" ? usuarios?.find((u) => u.id_usuario === panel.id) ?? null : null;
  const esPropia = seleccionado?.id_usuario === yo?.id_usuario;
  const rolElegido = catalogo?.roles.find((r) => String(r.id_rol) === form.id_rol);
  // Roles que se pueden elegir: los habilitados y, al editar, el que la cuenta ya tiene
  const rolesOpciones = catalogo?.roles.filter((r) => r.activo || String(r.id_rol) === form.id_rol) ?? [];

  function abrir(nuevo: Panel, datos: Form) {
    setPanel(nuevo);
    setForm(datos);
    setError(null);
    setMensaje(null);
  }

  function reemplazar(u: UsuarioCuenta) {
    setUsuarios((lista) => {
      const resto = (lista ?? []).filter((x) => x.id_usuario !== u.id_usuario);
      return [...resto, u].sort((a, b) => Number(b.activo) - Number(a.activo)
        || a.nombre_completo.localeCompare(b.nombre_completo, "es"));
    });
  }

  async function ejecutar(accion: () => Promise<void>) {
    setError(null);
    setMensaje(null);
    setEnviando(true);
    try {
      await accion();
    } catch (err) {
      setError(mensajeError(err));
    } finally {
      setEnviando(false);
    }
  }

  function guardar(e: FormEvent) {
    e.preventDefault();
    const correo = form.correo_institucional.trim() || null;
    if (panel?.modo === "nuevo") {
      return ejecutar(async () => {
        const r = await usuariosApi.crear({ nombre_completo: form.nombre_completo, nombre_usuario: form.nombre_usuario,
                                            correo_institucional: correo, id_rol: Number(form.id_rol) });
        reemplazar(r.usuario);
        abrir({ modo: "editar", id: r.usuario.id_usuario }, formDesde(r.usuario));
        setMensaje("Usuario creado.");
        setAviso({ titulo: "Usuario creado", nombreUsuario: r.usuario.nombre_usuario, contrasena: r.contrasena_temporal });
      });
    }
    if (!seleccionado) return;
    const cambios: UsuarioCambios = {};
    if (form.nombre_completo.trim() !== seleccionado.nombre_completo) cambios.nombre_completo = form.nombre_completo;
    if (correo !== seleccionado.correo_institucional) cambios.correo_institucional = correo;
    if (Number(form.id_rol) !== seleccionado.id_rol) cambios.id_rol = Number(form.id_rol);
    return ejecutar(async () => {
      const u = await usuariosApi.actualizar(seleccionado.id_usuario, cambios);
      reemplazar(u);
      setForm(formDesde(u));
      setMensaje("Cambios guardados.");
    });
  }

  function cambiarEstado(accion: "desactivar" | "reactivar" | "desbloquear", texto: string) {
    if (!seleccionado) return;
    if (accion === "desactivar" && !window.confirm(
      `¿Desactivar la cuenta de ${seleccionado.nombre_usuario}? No podrá iniciar sesión, pero su historial se conserva.`)) return;
    void ejecutar(async () => {
      reemplazar(await usuariosApi[accion](seleccionado.id_usuario));
      setMensaje(texto);
    });
  }

  function restablecer() {
    if (!seleccionado || !window.confirm(
      `¿Generar una contraseña nueva para ${seleccionado.nombre_usuario}? La actual dejará de funcionar.`)) return;
    void ejecutar(async () => {
      const r = await usuariosApi.restablecerContrasena(seleccionado.id_usuario);
      reemplazar(r.usuario);
      setMensaje("Contraseña restablecida.");
      setAviso({ titulo: "Contraseña restablecida", nombreUsuario: r.usuario.nombre_usuario, contrasena: r.contrasena_temporal });
    });
  }

  const sinCambios = seleccionado !== null
    && form.nombre_completo.trim() === seleccionado.nombre_completo
    && (form.correo_institucional.trim() || null) === seleccionado.correo_institucional
    && Number(form.id_rol) === seleccionado.id_rol;
  const incompleto = form.nombre_completo.trim().length < 3 || !form.id_rol
    || (panel?.modo === "nuevo" && form.nombre_usuario.trim().length < 3);

  return (
    <section>
      <div className="encabezado-pagina">
        <div>
          <h1>Usuarios</h1>
          <p className="texto-tenue">Cuentas del personal de salud y sus roles</p>
        </div>
        <button className="boton boton--primario boton--auto" disabled={!catalogo}
                onClick={() => abrir({ modo: "nuevo" }, FORM_VACIO)}>+ Nuevo usuario</button>
      </div>

      {errorCarga && <p className="alerta alerta--error" role="alert">{errorCarga}</p>}

      <div className="usuarios">
        <div className="tarjeta tarjeta--ancha">
          {usuarios === null
            ? <p className="vacio">Cargando…</p>
            : usuarios.length === 0
              ? <p className="vacio">Aún no hay usuarios registrados.</p>
              : (
                <div className="tabla-contenedor">
                  <table className="tabla">
                    <thead>
                      <tr>
                        <th>Nombre</th>
                        <th>Usuario</th>
                        <th>Rol</th>
                        <th>Estado</th>
                        <th>Último acceso</th>
                        <th aria-label="Acciones" />
                      </tr>
                    </thead>
                    <tbody>
                      {usuarios.map((u) => (
                        <tr key={u.id_usuario}
                            className={panel?.modo === "editar" && panel.id === u.id_usuario ? "fila--seleccionada" : undefined}>
                          <td><strong>{u.nombre_completo}</strong></td>
                          <td>{u.nombre_usuario}</td>
                          <td><span className={`etiqueta etiqueta--rol rol--${claseRol(u.rol)}`}>{u.rol}</span></td>
                          <td><span className={`estado ${ESTADOS[u.estado].clase}`}>{ESTADOS[u.estado].texto}</span></td>
                          <td>{momentoRelativo(u.ultimo_acceso, "Nunca")}</td>
                          <td>
                            <div className="tabla__acciones">
                              <button className="boton boton--neutro boton--chico"
                                      onClick={() => abrir({ modo: "editar", id: u.id_usuario }, formDesde(u))}>Editar</button>
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
        </div>

        <div className="tarjeta tarjeta--ancha panel-usuario">
          {panel === null || (panel.modo === "editar" && !seleccionado) ? (
            <p className="vacio">Elija un usuario para editarlo o cree uno nuevo.</p>
          ) : (
            <form onSubmit={guardar} noValidate>
              <h2>{panel.modo === "nuevo" ? "Nuevo usuario" : "Editar usuario"}</h2>

              <label htmlFor="u-nombre">Nombre completo <span className="obligatorio">*</span></label>
              <input id="u-nombre" value={form.nombre_completo} maxLength={150} autoComplete="off"
                     onChange={(e) => setForm({ ...form, nombre_completo: e.target.value })} />

              <label htmlFor="u-usuario">Usuario {panel.modo === "nuevo" && <span className="obligatorio">*</span>}</label>
              <input id="u-usuario" value={form.nombre_usuario} maxLength={50} autoComplete="off" spellCheck={false}
                     readOnly={panel.modo === "editar"} placeholder="p. ej., enf.rojas"
                     onChange={(e) => setForm({ ...form, nombre_usuario: e.target.value.toLowerCase() })} />
              {panel.modo === "nuevo"
                ? <p className="anterior">Letras minúsculas sin tildes, números y puntos. No se puede cambiar después.</p>
                : <p className="anterior">El usuario no se modifica, para conservar la trazabilidad.</p>}

              <label htmlFor="u-correo">Correo institucional <span className="texto-tenue">(opcional)</span></label>
              <input id="u-correo" type="email" value={form.correo_institucional} maxLength={150} autoComplete="off"
                     onChange={(e) => setForm({ ...form, correo_institucional: e.target.value })} />

              <label htmlFor="u-rol">Rol <span className="obligatorio">*</span></label>
              <select id="u-rol" value={form.id_rol} disabled={esPropia}
                      onChange={(e) => setForm({ ...form, id_rol: e.target.value })}>
                <option value="" disabled>Seleccione un rol</option>
                {rolesOpciones.map((r) => <option key={r.id_rol} value={r.id_rol}>{r.nombre}</option>)}
              </select>
              {esPropia && <p className="anterior">No puede cambiar el rol de su propia cuenta.</p>}

              <p className="subtitulo">Permisos del rol</p>
              <div className="permisos">
                {catalogo?.permisos.map((p) => (
                  <label key={p.codigo} className="casilla" title={p.descripcion}>
                    <input type="checkbox" readOnly disabled checked={!!rolElegido?.permisos.includes(p.codigo)} />
                    {PERMISOS[p.codigo] ?? p.descripcion}
                  </label>
                ))}
              </div>

              {seleccionado && (
                <p className="anterior">
                  Estado: <span className={`estado ${ESTADOS[seleccionado.estado].clase}`}>{ESTADOS[seleccionado.estado].texto}</span>
                  {seleccionado.bloqueado && seleccionado.activo && " por intentos fallidos de inicio de sesión"}
                </p>
              )}

              {mensaje && <p className="alerta alerta--exito" role="status">{mensaje}</p>}
              {error && <p className="alerta alerta--error" role="alert">{error}</p>}

              {seleccionado && (
                <div className="acciones acciones--izquierda">
                  {seleccionado.bloqueado && (
                    <button type="button" className="boton boton--neutro boton--chico" disabled={enviando}
                            onClick={() => cambiarEstado("desbloquear", "Cuenta desbloqueada.")}>Desbloquear</button>
                  )}
                  <button type="button" className="boton boton--neutro boton--chico" disabled={enviando} onClick={restablecer}>
                    Restablecer contraseña
                  </button>
                </div>
              )}

              <div className="acciones">
                {panel.modo === "nuevo" && (
                  <button type="button" className="boton boton--neutro" disabled={enviando} onClick={() => setPanel(null)}>
                    Cancelar
                  </button>
                )}
                {seleccionado && !esPropia && (seleccionado.activo ? (
                  <button type="button" className="boton boton--peligro" disabled={enviando}
                          onClick={() => cambiarEstado("desactivar", "Cuenta desactivada.")}>Desactivar</button>
                ) : (
                  <button type="button" className="boton boton--secundario" disabled={enviando}
                          onClick={() => cambiarEstado("reactivar", "Cuenta reactivada.")}>Reactivar</button>
                ))}
                <button type="submit" className="boton boton--primario" disabled={enviando || incompleto || sinCambios}>
                  {enviando ? "Guardando…" : panel.modo === "nuevo" ? "Crear usuario" : "Guardar"}
                </button>
              </div>
            </form>
          )}
        </div>
      </div>

      {aviso && <AvisoContrasena titulo={aviso.titulo} nombreUsuario={aviso.nombreUsuario}
                                 contrasena={aviso.contrasena} cerrar={cerrarAviso} />}
    </section>
  );
}
