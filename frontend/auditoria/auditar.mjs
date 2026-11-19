// Auditoría visual de la interfaz (pendiente P13): desbordes horizontales en 10 anchos, elementos
// con position absolute que escapan de su contenedor con desplazamiento, áreas táctiles y,
// opcionalmente, accesibilidad con axe-core (WCAG 2.0 y 2.1, niveles A y AA).
//
// Trabaja sobre la compilación servida por `vite preview` (puerto 4173) y lee el backend real
// (Nginx, puerto 8080) con los usuarios de seed_demo. Las respuestas de las consultas y de M11 se
// simulan con los fixtures del contrato (src/__fixtures__ y src/pruebas/conocimiento); las
// escrituras nunca llegan al backend. Uso y opciones en README.md.
import { chromium } from "playwright-core";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const AQUI = path.dirname(fileURLToPath(import.meta.url));
const FRONTEND = path.resolve(AQUI, "..");
const RAIZ = path.resolve(FRONTEND, "..");
const FIX = path.join(FRONTEND, "src", "__fixtures__");
const FIX_M11 = path.join(FRONTEND, "src", "pruebas", "conocimiento");

// ---------------------------------------------------------------------------
// Opciones
// ---------------------------------------------------------------------------
const opciones = Object.fromEntries(process.argv.slice(2).map((a) => {
  const m = a.match(/^--([^=]+)(?:=(.*))?$/);
  if (!m) throw new Error(`Opción no reconocida: ${a} (use --nombre=valor)`);
  return [m[1], m[2] ?? true];
}));
const lista = (v) => (typeof v === "string" ? v.split(",").map((x) => x.trim()).filter(Boolean) : null);
const ANCHOS_DESBORDE = [320, 360, 390, 600, 768, 800, 1000, 1024, 1280, 1920];
const ANCHOS = lista(opciones.anchos)?.map(Number) ?? ANCHOS_DESBORDE;
const ANCHOS_AXE = opciones.axe ? (lista(opciones["axe-anchos"])?.map(Number) ?? [390, 1280]) : [];
const SOLO = lista(opciones.pantallas);
const ETIQUETA = typeof opciones.etiqueta === "string" ? opciones.etiqueta : new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-");
const CAPTURAS = opciones.capturas === "todas" ? "todas" : opciones.capturas ? "problemas" : null;
const CSS_EXTRA = typeof opciones["css-extra"] === "string" ? fs.readFileSync(opciones["css-extra"], "utf-8") : null;
const API = process.env.CDSS_API ?? "http://localhost:8080";
const APP = process.env.CDSS_APP ?? "http://localhost:4173";
const SALIDA = path.join(AQUI, "resultados", ETIQUETA);
fs.mkdirSync(SALIDA, { recursive: true });

// ---------------------------------------------------------------------------
// Sesiones: la contraseña de los usuarios de seed_demo se lee de .env y no se imprime.
// ---------------------------------------------------------------------------
const env = fs.readFileSync(path.join(RAIZ, ".env"), "utf-8");
const clave = env.match(/^SEED_CONTRASENA=(.*)$/m)?.[1].trim().replace(/^["']|["']$/g, "");
if (!clave) throw new Error("Falta SEED_CONTRASENA en .env");
async function entrar(usuario) {
  const r = await fetch(`${API}/api/auth/login`, { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ usuario, contrasena: clave }) });
  if (!r.ok) throw new Error(`Inicio de sesión de ${usuario}: ${r.status} (¿stack levantado y seed_demo cargado?)`);
  return (await r.json()).token;
}
const tokenClinico = await entrar("enf.rojas");
const tokenAdmin = await entrar("admin.cdss");
const leerApi = async (ruta) => (await fetch(`${API}${ruta}`, { headers: { Authorization: `Bearer ${tokenClinico}` } })).json();

// Un paciente de seed_demo con tamizaje para las pantallas del paciente.
let paciente = null, historial = null;
for (const p of await leerApi("/api/pacientes")) {
  const h = await leerApi(`/api/pacientes/${p.id_paciente}/historial`);
  if (h.tamizajes?.length) { paciente = p.id_paciente; historial = h; break; }
}
if (!paciente) throw new Error("No hay pacientes con tamizaje: ejecute seed_demo");
const ficha = await leerApi(`/api/pacientes/${paciente}`);

// ---------------------------------------------------------------------------
// Datos simulados: textos largos (incluida una palabra sin espacios) para forzar los cortes.
// ---------------------------------------------------------------------------
const leerJson = (archivo) => JSON.parse(fs.readFileSync(archivo, "utf-8"));
const LARGA = "Tiene anemia leve, no recibe suplementación con hierro desde hace tres meses y la madre refiere poco apetito. " +
  "¿Qué tratamiento le corresponde, en qué dosis y cada cuánto se controla la hemoglobina según la norma técnica vigente?";
const consultasLargas = [0, 1, 2].map((i) => ({
  id_consulta: `00000000-0000-4000-8000-00000000010${i}`, id_tamizaje: historial.tamizajes[0].id_tamizaje,
  fecha_tamizaje: historial.tamizajes[0].fecha_tamizaje, id_consulta_previa: null,
  estado: ["VERIFICADA", "FUERA_DE_DOMINIO", "EVIDENCIA_INSUFICIENTE"][i],
  texto_filtrado: i === 2 ? "Suplementación" + "conhierropreventivaparaniñosdeseismeses".repeat(3) : LARGA,
  idioma: "es", fecha_hora_inicio: "2026-11-10T10:00:00-05:00", fecha_hora_fin: "2026-11-10T10:00:20-05:00",
  numero_intentos: 1, latencia_total_ms: 20000, confirma_tamizaje_no_vigente: false, categoria: "ANEMIA_LEVE",
  tipo_decision: null, modo_prueba: true,
}));

const ID_CON = "00000000-0000-4000-8000-000000000001";
const ID_PAC_FIX = "00000000-0000-4000-8000-000000000002";
const resultadoFix = (estado, cambios) => JSON.stringify({ ...leerJson(path.join(FIX, `resultado_${estado.toLowerCase()}.json`)), ...(cambios ?? {}) });
const streamFix = (estado) => fs.readFileSync(path.join(FIX, `consulta_${estado.toLowerCase()}.ndjson`), "utf-8");
const NOTA_LARGA = "Indico sulfato ferroso en gotas y control de hemoglobina en un mes. " +
  "Explico a la madre la administración separada de los lácteos. " + "Palabrasinespaciosmuylargaparaprobarelcorte".repeat(3);
const DECISION = { id_decision: "d-1", id_usuario: "x", tipo_decision: "MODIFICA_RECOMENDACION", nota: NOTA_LARGA,
  fecha_registro: "2026-11-15T10:30:00-05:00",
  registrada_por: "Lic. María de los Ángeles Huamaní Quispecondori de la Villanueva" };
// «Historial de consultas» (P10, Sprint 3 parte B): nombres e historias largas, una pregunta de 100
// caracteres con una palabra sin espacios, la marca «Prueba» y paginación (45 en total).
const consultasPropias = [0, 1, 2, 3].map((i) => ({
  id_consulta: `00000000-0000-4000-8000-00000000020${i}`, id_paciente: paciente,
  nombres_apellidos: i === 0 ? "María de los Ángeles Huamaní Quispecondori de la Villanueva" : ficha.nombres_apellidos,
  numero_hc: i === 0 ? "HC-2026-000123456789" : ficha.numero_hc, edad_meses: [7, 23, 40, 59][i],
  estado: ["VERIFICADA", "EVIDENCIA_INSUFICIENTE", "TAMIZAJE_NO_VIGENTE", "SOLICITUD_BLOQUEADA"][i],
  categoria: ["ANEMIA_MODERADA", "SIN_ANEMIA", null, "ANEMIA_SEVERA"][i], nivel_riesgo: ["ALTO", "BAJO", null, "MUY_ALTO"][i],
  fecha_hora_inicio: `2026-11-1${i}T10:42:00-05:00`, modo_prueba: i % 2 === 0,
  pregunta: i === 1 ? null : i === 2 ? "Suplementación" + "conhierropreventivaparaniñosdeseismeses".repeat(2) + "…"
    : LARGA.slice(0, 99) + "…",
}));
const paginaPropias = { total: 45, limite: 20, desplazamiento: 0, consultas: consultasPropias };
const fichaFix = { ...ficha, id_paciente: ID_PAC_FIX };
const historialFix = { ...historial, id_paciente: ID_PAC_FIX,
  tamizajes: historial.tamizajes.map((t, i) => (i === 0 ? { ...t, id_tamizaje: "00000000-0000-4000-8000-000000000003" } : t)) };
const citaPuntero = () => {
  const base = leerJson(path.join(FIX, "resultado_verificada.json")).citas[0];
  return [{ ...base, etiqueta: "F-02", puntaje_reranker: 0.412 },
    { ...base, etiqueta: "F-05", origen: "PUNTERO", agregado_por_referencia_de: "F-02", puntaje_reranker: null, idioma: "es",
      extracto: "| 6 a 11 meses de edad | 3 mediciones: a partir de los 6 meses de edad; al tercer mes de iniciada la suplementación (control) |",
      extracto_traducido: null, etiqueta_traduccion: null, fuente: "RM 429-2024/MINSA",
      seccion: "6.1.1 A Tabla 4 (mod. RM 429-2024/MINSA, modificación N.° 5)" }];
};

// M09 (reporte exportable, Sprint 3 parte C2): vistas previas y lista de los fixtures de la parte C1.
// La consulta «real» no es de prueba y lleva una decisión con nota y nombre largos; el POST se responde
// aquí con bytes ficticios y las cabeceras del contrato (nunca llega al backend).
const AVISO_PRUEBA = "MODO DE PRUEBA, no es un documento clínico";
const vistaM09 = (destino, prueba) => {
  const v = leerJson(path.join(FIX, `reporte_vista_previa_${destino.toLowerCase()}.json`));
  v.modo_prueba = prueba;
  if (!prueba) v.avisos = v.avisos.filter((a) => a !== AVISO_PRUEBA);
  v.bloques = v.bloques.map((b) => (b.seccion !== "DECISION" ? b : { ...b, campos: [
    { etiqueta: "Tipo de decisión", valor: "Modifica la recomendación" }, { etiqueta: "Nota", valor: NOTA_LARGA },
    { etiqueta: "Registrada por", valor: DECISION.registrada_por }, { etiqueta: "Fecha y hora", valor: "15/11/2026 10:30" }] }));
  return v;
};
const REPORTES_M09 = leerJson(path.join(FIX, "reportes_lista.json"));

// M13 (auditoría, Sprint 3 parte D2): fixtures de la parte D1 con 45 consultas en total (paginación),
// un modelo largo y un detalle con una solicitud de líneas largas (una palabra sin espacios) y un intento
// bloqueado por el control previo.
const IND_M13 = leerJson(path.join(FIX, "auditoria_indicadores.json"));
const LISTA_M13 = (() => {
  const p = leerJson(path.join(FIX, "auditoria_consultas.json"));
  p.total = 45;
  p.consultas = p.consultas.map((c, i) => (i === 0 ? { ...c, modelo_llm: "claude-sonnet-5-5-20261101-version-larga-de-prueba" } : c));
  return p;
})();
const DETALLE_M13 = (() => {
  const d = leerJson(path.join(FIX, "auditoria_detalle.json"));
  const sol = d.intentos[1].solicitud_enviada;
  sol.evidencia = sol.evidencia.map((e, i) => ({ ...e, texto: i === 0
    ? "Suplementación" + "conhierropreventivaparaniñosdeseismeses".repeat(4)
    : `${LARGA} ${LARGA}` }));
  d.intentos[0] = { ...d.intentos[0], control_identificadores: false, solicitud_enviada: null };
  return d;
})();
const ID_M13 = DETALLE_M13.id_consulta;

// M11: guías reales (fixtures) más tres ficticias con estados que la base real no tiene.
const DOCS_REALES = leerJson(path.join(FIX_M11, "documentos.json"));
const DETALLE_M11 = leerJson(path.join(FIX_M11, "detalle_nts213.json"));
const AHORA = "2026-11-16T15:00:00Z";
const trabajo = (id, estado, cambios = {}) => ({ id_trabajo: id, tipo: "INDEXACION", estado, etapa: null, procesados: 0, total: null,
  mensaje_error: null, fecha_solicitud: AHORA, fecha_fin: null, ...cambios });
const DOCS_EXTRA = [
  { ...DOCS_REALES[0], id_documento: "20000000-0000-4000-8000-000000000001", nivel: 2, codigo_documento: null, version: null,
    titulo: "Directiva sanitaria de suplementación preventiva con hierro en niñas y niños menores de 36 meses 2026",
    entidad_emisora: "MINSA", tipo_documento: "DIRECTIVA", anio_publicacion: 2026, idioma: "es", estado_indexacion: "EN_PROCESO",
    version_indexacion: null, fragmentos_vigentes: 0, citas_30_dias: 0,
    ultimo_trabajo: trabajo("t-1", "EN_CURSO", { etapa: "EMBEDDINGS", procesados: 148, total: 240 }) },
  { ...DOCS_REALES[0], id_documento: "20000000-0000-4000-8000-000000000002", nivel: 2, codigo_documento: "LIT-RAG-2025",
    titulo: "Literatura metodológica RAG clínico: artículos de soporte", entidad_emisora: "OTRA", tipo_documento: "LITERATURA",
    anio_publicacion: 2025, idioma: "en", estado_indexacion: "ERROR", version_indexacion: null, fragmentos_vigentes: 0,
    citas_30_dias: 0, version: null,
    ultimo_trabajo: trabajo("t-2", "ERROR", { etapa: "EXTRACCION", mensaje_error: "ValueError: el PDF no tiene capa de texto", fecha_fin: AHORA }) },
  { ...DOCS_REALES[2], id_documento: "20000000-0000-4000-8000-000000000003", codigo_documento: "NTS 134-MINSA/DGIESP-2017",
    titulo: "Norma técnica: manejo terapéutico y preventivo de la anemia", anio_publicacion: 2017, version: "RM 250-2017/MINSA",
    estado: "OBSOLETA", fragmentos_vigentes: 0, citas_30_dias: 0, version_indexacion: 2 },
];
const DOCS_M11 = [...DOCS_REALES, ...DOCS_EXTRA];
const ACTIVOS_M11 = [
  { ...DOCS_EXTRA[0].ultimo_trabajo, id_documento: DOCS_EXTRA[0].id_documento, titulo: DOCS_EXTRA[0].titulo, fecha_inicio: AHORA,
    solicitado_por: "Administrador CDSS" },
  { ...trabajo("t-3", "PENDIENTE"), id_documento: "x", titulo: "Guía de consejería nutricional para el control de la anemia infantil",
    fecha_inicio: null, solicitado_por: "Administrador CDSS" },
];

// ---------------------------------------------------------------------------
// Pantallas y estados
// ---------------------------------------------------------------------------
const m05 = (estado, extra = {}) => ({ ruta: `/consultas/${ID_CON}`, resultado: estado, esperar: "Pregunta realizada", ...extra });
const m09 = (extra = {}) => ({ ruta: `/consultas/${ID_CON}/reporte`, resultado: "VERIFICADA", esperar: "Reportes generados de esta consulta",
  m09: { destino: "EXPEDIENTE", prueba: true, ...extra },
  cambios: { modo_prueba: extra.prueba ?? true, ...(extra.prueba === false ? { decision: DECISION, opciones_decision: [] } : {}) } });
const m13 = (extra = {}) => ({ ruta: "/admin/auditoria", admin: true, m13: { ...extra }, esperar: "Auditoría y trazabilidad",
  ...(extra.ruta ? { ruta: extra.ruta } : {}) });
const m11 = (extra = {}) => ({ ruta: "/admin/conocimiento", admin: true, m11: true, docs: DOCS_M11, activos: [], ...extra });
const PANTALLAS = {
  login: { ruta: "/login", sinSesion: true, esperar: "Ingresar" },
  inicio: { ruta: "/", esperar: null },
  panel_pacientes: { ruta: "/pacientes", esperar: null },
  historial_consultas: { ruta: "/consultas", esperar: null },
  registro_paciente: { ruta: "/pacientes/nuevo", esperar: null },
  editar_paciente: { ruta: `/pacientes/${paciente}/editar`, esperar: null },
  m08_historial: { ruta: `/pacientes/${paciente}/historial`, esperar: null },
  m08_evaluaciones: { ruta: `/pacientes/${paciente}/historial`, esperar: "Evaluaciones realizadas", historialConConsultas: true },
  m14_nuevo_tamizaje: { ruta: `/pacientes/${paciente}/tamizajes/nuevo`, esperar: null },
  m04_consulta: { ruta: `/pacientes/${paciente}/consulta`, esperar: "Sus consultas previas de este paciente", largas: true },
  m04_fuera_de_dominio: { ruta: `/pacientes/${paciente}/consulta`, esperar: "Sus consultas previas de este paciente", largas: true,
    enviar: "FUERA_DE_DOMINIO" },
  m06_desde_m04: { ruta: `/pacientes/${paciente}/consulta`, esperar: "Sus consultas previas de este paciente", largas: true,
    enviar: "DATOS_FALTANTES", ventanaM04: true },
  m15_desde_m04: { ruta: `/pacientes/${paciente}/consulta`, esperar: "Sus consultas previas de este paciente", largas: true,
    enviar: "TAMIZAJE_NO_VIGENTE", ventanaM04: true },
  m05_verificada: m05("VERIFICADA"),
  m05_error: m05("ERROR"),
  m05_fuera_de_dominio: m05("FUERA_DE_DOMINIO"),
  m05_bloqueada: m05("SOLICITUD_BLOQUEADA"),
  m05_datos_faltantes: m05("DATOS_FALTANTES", { cerrarVentana: true }),
  m05_tamizaje_no_vigente: m05("TAMIZAJE_NO_VIGENTE", { cerrarVentana: true }),
  m05_puntero: m05("VERIFICADA", { cambios: { citas: citaPuntero() } }),
  m05_tramo: m05("VERIFICADA", { cambios: { tramo_edad: { edad_meses_tamizaje: 5, edad_meses_consulta: 6, tramo_tamizaje: null,
    tramo_consulta: { edad_min_meses: 6, edad_max_meses: 23 }, cambio: true } } }),
  m06_ventana: m05("DATOS_FALTANTES", { ventana: true }),
  m15_ventana: m05("TAMIZAJE_NO_VIGENTE", { ventana: true }),
  m07_evidencia_insuficiente: m05("EVIDENCIA_INSUFICIENTE"),
  m07_detalle: m05("EVIDENCIA_INSUFICIENTE", { detalle: true }),
  decision_ventana: m05("VERIFICADA", { decision: "ventana" }),
  decision_confirmacion: m05("VERIFICADA", { decision: "confirmacion" }),
  decision_registrada_m05: m05("VERIFICADA", { cambios: { decision: DECISION, opciones_decision: [] } }),
  decision_registrada_m07: m05("EVIDENCIA_INSUFICIENTE", { cambios: { decision: { ...DECISION, tipo_decision: "CRITERIO_CLINICO_PROPIO" },
    opciones_decision: [] } }),
  menu_clinico: { ruta: "/pacientes", esperar: "Pacientes atendidos recientemente", menu: true },
  menu_admin: { ruta: "/admin/usuarios", admin: true, esperar: null, menu: true },
  m10_usuarios: { ruta: "/admin/usuarios", admin: true, esperar: null },
  m11_lista: m11(),
  m11_avance: m11({ activos: ACTIVOS_M11 }),
  m11_cargar: m11({ abrir: "cargar" }),
  m11_cargar_errores: m11({ abrir: "cargar", enviarVacio: true }),
  m11_detalle: m11({ abrir: "detalle" }),
  m11_vacio: m11({ docs: [] }),
  en_construccion: { ruta: "/admin/parametros", admin: true, esperar: null },
  // Parte C2 del Sprint 3: M09 en ambos destinos, con el reporte generado, y «Reportes» (/reportes).
  m09_expediente_real: m09({ prueba: false, generar: true }),
  m09_expediente_prueba: m09({ prueba: true }),
  m09_cuidador: m09({ prueba: true, destino: "CUIDADOR" }),
  m09_vista_error: m09({ prueba: false, vistaError: true }),
  reportes_lista: { ruta: "/reportes", esperar: "Mostrando 1 a 4 de 45 consultas", lista: paginaPropias },
  // Parte D2 del Sprint 3: M13 (indicadores y lista, con y sin el interruptor de pruebas), el detalle con la
  // solicitud larga y la vista de error.
  m13_lista: m13(),
  m13_pruebas: m13({ ruta: "/admin/auditoria?pruebas=1" }),
  m13_detalle: { ...m13({ ruta: `/admin/auditoria/${ID_M13}`, detalle: true }), esperar: "Volver a la auditoría" },
  m13_error: m13({ error: true }),
  // Parte B del Sprint 3: lista de consultas propias, sus estados y el buscador de «Nueva consulta».
  consultas_lista: { ruta: "/consultas", esperar: "Mostrando 1 a 4 de 45 consultas", lista: paginaPropias },
  consultas_filtros_error: { ruta: "/consultas?desde=2026-11-15&hasta=2026-11-01", esperar: "Mostrando 1 a 4 de 45 consultas",
    lista: paginaPropias, filtrar: true },
  consultas_vacia: { ruta: "/consultas", esperar: "Aún no realizó consultas clínicas", lista: { ...paginaPropias, total: 0, consultas: [] } },
  consultas_error: { ruta: "/consultas", esperar: "No se pudieron cargar las consultas", lista: "error" },
  consultas_nueva: { ruta: "/consultas/nueva", esperar: "Pacientes atendidos recientemente" },
};
if (SOLO) for (const n of SOLO) if (!PANTALLAS[n]) throw new Error(`Pantalla desconocida: ${n}. Disponibles: ${Object.keys(PANTALLAS).join(", ")}`);

// ---------------------------------------------------------------------------
// Mediciones dentro de la página
// ---------------------------------------------------------------------------
function medir() {
  const ancho = document.documentElement.clientWidth;
  const describir = (e) => {
    let s = e.tagName.toLowerCase();
    if (e.id) s += "#" + e.id;
    const c = typeof e.className === "string" ? e.className.trim().split(/\s+/).filter(Boolean).slice(0, 2) : [];
    if (c.length) s += "." + c.join(".");
    const texto = (e.textContent ?? "").trim().slice(0, 30);
    return texto && e.children.length === 0 ? `${s} «${texto}»` : s;
  };
  const recorta = (e) => { const o = getComputedStyle(e); return o.overflowX !== "visible" || o.clip !== "auto"; };
  const resultado = {
    scrollWidth: document.documentElement.scrollWidth, clientWidth: ancho, elementos: [], absolutos: [],
    tablas: [...document.querySelectorAll(".tabla-contenedor")].map((e) => ({
      nombre: e.getAttribute("aria-label") ?? e.closest(".tarjeta")?.querySelector("h2")?.textContent ?? "tabla",
      contenido: e.scrollWidth, visible: e.clientWidth, oculto: e.scrollWidth - e.clientWidth })),
  };
  for (const e of document.body.querySelectorAll("*")) {
    const r = e.getBoundingClientRect();
    if (r.width === 0 && r.height === 0) continue;
    const st = getComputedStyle(e);
    if (st.position === "fixed") continue;

    // P13: un elemento absolute cuyo bloque contenedor (offsetParent) está fuera de un antepasado
    // que recorta o desplaza no queda recortado por él. Si además se sale de ese antepasado, ensancha
    // la página aunque esté oculto con clip (los textos solo para lectores de la fila 84).
    if (st.position === "absolute") {
      const bloque = e.offsetParent;
      let p = e.parentElement, contenedor = null;
      while (p && p !== bloque && p !== document.body) { if (recorta(p)) { contenedor = p; break; } p = p.parentElement; }
      if (contenedor) {
        const rc = contenedor.getBoundingClientRect();
        const exceso = Math.round(Math.max(r.right - rc.right, rc.left - r.left));
        if (exceso > 1) resultado.absolutos.push({ el: describir(e), contenedor: describir(contenedor),
          bloque: bloque ? describir(bloque) : null, exceso, fueraPagina: Math.round(r.right - ancho) });
      }
      if (st.clip !== "auto") continue;
    }

    // Elementos cuyo borde derecho excede el de su padre (que no recorta ni desplaza) o la página.
    if (r.width === 0 || r.height === 0) continue;
    let p = e.parentElement, oculto = null;
    while (p && p !== document.body) { if (recorta(p)) { oculto = p; break; } p = p.parentElement; }
    const padre = e.parentElement;
    if (!padre || padre === document.body) continue;
    const rp = padre.getBoundingClientRect();
    const derechoPadre = rp.right - parseFloat(getComputedStyle(padre).borderRightWidth);
    const exceso = Math.round(r.right - derechoPadre);
    const fueraPagina = Math.round(r.right - ancho);
    if ((exceso > 1 && !recorta(padre)) || (!oculto && fueraPagina > 1)) {
      resultado.elementos.push({ el: describir(e), padre: describir(padre), exceso, fueraPagina, recortadoPor: oculto ? describir(oculto) : null });
    }
  }
  return resultado;
}

// Controles de menos de 44 px de alto por debajo de 800 px, en el alcance donde el Sprint 2 fijó esa
// regla (menú móvil, M11 y ventanas; ver estilos.test.ts) y en lo nuevo de la parte C2 del Sprint 3
// (M09, sus entradas en M08 y la lista de consultas) y de la parte D2 (M13). Es un aviso, no una falla. Los botones de
// las pantallas clínicas (42 px) y los enlaces dentro del texto quedan fuera de ese alcance.
function tactiles() {
  return [...document.querySelectorAll(".boton-menu, .menu-movil a, .menu-movil button, .conocimiento .boton, .guia__opcion, " +
    ".modal .boton, .modal input:not([type=radio]):not([type=checkbox]), .modal select, .reporte .boton, .reporte__opcion, " +
    ".evaluaciones__acciones .boton, .consultas-propias .boton, .auditoria .boton, .auditoria__interruptor, " +
    ".auditoria__campo select, .auditoria__campo input")]
    .filter((b) => b.getBoundingClientRect().height > 0)
    .map((b) => ({ t: (b.getAttribute("aria-label") ?? b.textContent ?? b.id).trim().slice(0, 30),
                   h: Math.round(b.getBoundingClientRect().height), w: Math.round(b.getBoundingClientRect().width) }))
    .filter((x) => x.h < 44);
}

// ---------------------------------------------------------------------------
// Recorrido
// ---------------------------------------------------------------------------
const AXE = ANCHOS_AXE.length ? fs.readFileSync(path.join(AQUI, "node_modules", "axe-core", "axe.min.js"), "utf-8") : null;
const navegador = await chromium.launch(process.env.CHROME_RUTA ? { executablePath: process.env.CHROME_RUTA } : { channel: "chrome" });
const salida = {}, accesibilidad = {}, avisosTactiles = {};
const anchosDe = () => [...new Set([...ANCHOS, ...ANCHOS_AXE])].sort((a, b) => a - b);

async function simular(p, ruta) {
  const req = ruta.request();
  const u = new URL(req.url());
  const json = (d, estado = 200) => ruta.fulfill({ status: estado, contentType: "application/json",
    body: typeof d === "string" ? d : JSON.stringify(d) });
  if (p.m11) {
    if (u.pathname === "/api/conocimiento/documentos" && req.method() === "GET") return json(p.docs);
    if (u.pathname === "/api/conocimiento/trabajos") return json(p.activos);
    if (u.pathname.startsWith("/api/conocimiento/documentos/")) return json(DETALLE_M11);
  }
  if (p.m13 && u.pathname.startsWith("/api/auditoria/")) {
    if (p.m13.error) return json({ detail: "Error interno del servidor" }, 500);
    if (u.pathname === "/api/auditoria/indicadores") return json(IND_M13);
    if (u.pathname === "/api/auditoria/consultas") return json({ ...LISTA_M13, incluir_pruebas: u.searchParams.get("incluir_pruebas") === "true" });
    if (u.pathname === `/api/auditoria/consultas/${ID_M13}`) return json(DETALLE_M13);
  }
  if (p.lista && u.pathname === "/api/consultas")
    return p.lista === "error" ? json({ detail: "Error interno del servidor" }, 500) : json(p.lista);
  if (p.m09 && u.pathname === `/api/consultas/${ID_CON}/reportes/vista-previa`) {
    if (p.m09.vistaError) return json({ detail: "Error interno del servidor" }, 500);
    return json(vistaM09(u.searchParams.get("destino") === "CUIDADOR" ? "CUIDADOR" : "EXPEDIENTE", p.m09.prueba));
  }
  if (p.m09 && u.pathname === `/api/consultas/${ID_CON}/reportes`) {
    if (req.method() === "GET") return json(REPORTES_M09);
    return ruta.fulfill({ status: 201, contentType: "application/pdf", body: Buffer.from("%PDF-1.4 auditoria"),
      headers: { "X-Reporte-Numero": "EV-2026-00918", "X-Reporte-Hash": "9f".repeat(32), "Cache-Control": "no-store",
                 "Content-Disposition": 'attachment; filename="EV-2026-00918.pdf"' } });
  }
  if (p.resultado && u.pathname === `/api/consultas/${ID_CON}`) return json(resultadoFix(p.resultado, p.cambios));
  if (u.pathname === `/api/pacientes/${ID_PAC_FIX}`) return json(fichaFix);
  if (u.pathname === `/api/pacientes/${ID_PAC_FIX}/historial`) return json(historialFix);
  if (u.pathname === `/api/pacientes/${ID_PAC_FIX}/consultas`) return json([]);
  if (p.historialConConsultas && req.method() === "GET" && u.pathname === `/api/pacientes/${paciente}/historial`) {
    const h = await (await ruta.fetch({ url: `${API}${u.pathname}` })).json();
    const sintomas = [{ id_sintoma: 1, nombre: "Palidez", detalle: null }, { id_sintoma: 2, nombre: "Hiporexia", detalle: null },
      { id_sintoma: 4, nombre: "Fatiga o somnolencia", detalle: null }, { id_sintoma: 6, nombre: "Otro", detalle: "Caída de cabello" }];
    h.tamizajes = h.tamizajes.map((t, i) => (i === 0 ? { ...t, sintomas, vigente: false, hemoglobina_g_dl: "10.6",
      clasificacion: { ...(t.clasificacion ?? {}), categoria: "ANEMIA_MODERADA", hb_ajustada_g_dl: "10.6" } } : t));
    return json({ ...h, consultas: consultasLargas.map((c, i) => ({ ...c, id_tamizaje: h.tamizajes[0].id_tamizaje,
      tipo_decision: i === 0 ? "ACEPTA_RECOMENDACION" : null })) });
  }
  if (p.largas && req.method() === "GET" && u.pathname === `/api/pacientes/${paciente}/consultas`) return json(consultasLargas);
  if (p.enviar && req.method() === "POST" && u.pathname === `/api/pacientes/${paciente}/consultas`)
    return ruta.fulfill({ status: 200, contentType: "application/x-ndjson",
      body: streamFix(p.enviar).replaceAll(ID_PAC_FIX, paciente).replaceAll("\r", "") });
  // Lo demás va al backend real, solo lecturas: las escrituras se responden aquí sin enviarse.
  if (req.method() !== "GET" && u.pathname !== "/api/pacientes/buscar") return json({ detail: "no enviado en la auditoría" }, 409);
  return ruta.fulfill({ response: await ruta.fetch({ url: `${API}${u.pathname}${u.search}` }) });
}

async function preparar(pagina, p) {
  if (p.esperar) await pagina.getByText(p.esperar, { exact: false }).first().waitFor({ timeout: 15000 });
  if (p.m11) {
    await pagina.getByRole("heading", { name: "Base de conocimiento" }).waitFor({ timeout: 15000 });
    if (p.docs.length) await pagina.getByRole("region", { name: "Guías de la base de conocimiento" }).waitFor();
  }
  await pagina.waitForLoadState("networkidle");
  if (p.enviar) {
    await pagina.locator("textarea").first().fill("¿Qué dosis de hierro le corresponde según su hemoglobina?");
    await pagina.getByRole("button", { name: "Enviar" }).click();
    if (p.ventanaM04) await pagina.getByRole("dialog").waitFor();
    else await pagina.getByRole("heading", { name: "Estado de la consulta" }).waitFor({ timeout: 8000 });
  }
  if (p.cerrarVentana || p.ventana) await pagina.getByRole("dialog").waitFor();
  if (p.m13) {
    if (p.m13.error) await pagina.getByText("No se pudieron cargar las consultas", { exact: false }).waitFor({ timeout: 8000 });
    else if (p.m13.detalle) await pagina.getByRole("region", { name: "Solicitud enviada al modelo en el intento 2" }).waitFor({ timeout: 8000 });
    else await pagina.getByText("Mostrando 1 a", { exact: false }).waitFor({ timeout: 8000 });
  }
  if (p.m09) {
    if (p.m09.vistaError) await pagina.getByText("No se pudo cargar la vista previa", { exact: false }).waitFor({ timeout: 8000 });
    else await pagina.getByRole("article", { name: "Vista previa del documento" }).waitFor({ timeout: 8000 });
    if (p.m09.destino === "CUIDADOR") {
      await pagina.getByRole("radio", { name: "Entrega al cuidador" }).check();
      await pagina.getByText("Información para la familia").waitFor({ timeout: 8000 });
    }
    if (p.m09.generar) {
      await pagina.getByRole("button", { name: "Generar reporte (PDF)" }).click();
      await pagina.getByRole("heading", { name: "Reporte EV-2026-00918" }).waitFor({ timeout: 8000 });
    }
  }
  if (p.detalle) await pagina.getByText("Detalle de la búsqueda").click();
  if (p.filtrar) {
    await pagina.getByRole("button", { name: "Filtrar" }).click();
    await pagina.getByText("La fecha «Hasta» no puede ser anterior a «Desde».").waitFor();
  }
  if (p.decision) {
    await pagina.getByRole("button", { name: "Registrar decisión clínica" }).click();
    if (p.decision === "confirmacion") {
      await pagina.getByRole("radio", { name: /Modifica la recomendación/ }).check();
      await pagina.locator("#decision-nota").fill(NOTA_LARGA);
      await pagina.getByRole("button", { name: "Continuar" }).click();
      await pagina.getByRole("heading", { name: "Confirme la decisión" }).waitFor();
    }
  }
  if (p.abrir === "cargar") {
    await pagina.getByRole("button", { name: "Cargar guía" }).click();
    await pagina.getByRole("dialog").waitFor();
    if (p.enviarVacio) {
      await pagina.locator("#guia-pagina-inicio").fill("9");
      await pagina.locator("#guia-pagina-fin").fill("3");
      await pagina.getByRole("dialog").getByRole("button", { name: "Cargar guía" }).click();
      await pagina.locator(".campo__error").first().waitFor();
    }
  }
  if (p.abrir === "detalle") {
    await pagina.getByRole("button", { name: "Ver: NTS 213-MINSA/DGIESP-2024" }).click();
    await pagina.getByRole("heading", { name: "Versiones de indexación" }).waitFor();
  }
  if (p.menu) {
    const boton = pagina.getByRole("button", { name: "Abrir menú" });
    if (await boton.isVisible()) { await boton.click(); await pagina.locator(".menu-movil").waitFor(); }
  }
  if (p.cerrarVentana) { await pagina.keyboard.press("Escape"); await pagina.getByRole("dialog").waitFor({ state: "detached" }); }
  await pagina.waitForTimeout(250);
}

for (const [nombre, p] of Object.entries(PANTALLAS)) {
  if (SOLO && !SOLO.includes(nombre)) continue;
  for (const ancho of anchosDe()) {
    const pagina = await navegador.newPage({ viewport: { width: ancho, height: 900 } });
    if (!p.sinSesion) await pagina.addInitScript((tk) => sessionStorage.setItem("cdss.token", tk), p.admin ? tokenAdmin : tokenClinico);
    if (CSS_EXTRA) await pagina.addInitScript((css) => document.addEventListener("DOMContentLoaded", () => {
      const s = document.createElement("style"); s.textContent = css; document.head.append(s); }), CSS_EXTRA);
    await pagina.route("**/api/**", (ruta) => simular(p, ruta));
    const clave = `${nombre}@${ancho}`;
    try {
      await pagina.goto(`${APP}${p.ruta}`);
      await preparar(pagina, p);
      if (ANCHOS.includes(ancho)) {
        const m = await pagina.evaluate(medir);
        salida[clave] = m;
        if (ancho < 800) { const t = await pagina.evaluate(tactiles); if (t.length) avisosTactiles[clave] = t; }
        const problema = m.scrollWidth > m.clientWidth || m.elementos.length || m.absolutos.length;
        if (CAPTURAS === "todas" || (CAPTURAS && problema))
          await pagina.screenshot({ path: path.join(SALIDA, `${nombre}_${ancho}.png`), fullPage: true });
      }
      if (AXE && ANCHOS_AXE.includes(ancho)) {
        await pagina.addScriptTag({ content: AXE });
        accesibilidad[clave] = await pagina.evaluate(async () => (await window.axe.run(document, {
          runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"] } })).violations
          .map((v) => ({ id: v.id, impacto: v.impact, ayuda: v.help, total: v.nodes.length,
                        nodos: v.nodes.slice(0, 4).map((n) => n.target.join(" ")), resumen: v.nodes[0]?.failureSummary?.slice(0, 220) })));
      }
    } catch (error) {
      salida[clave] = { error: String(error).split("\n")[0] };
      await pagina.screenshot({ path: path.join(SALIDA, `error_${nombre}_${ancho}.png`), fullPage: true }).catch(() => {});
    }
    await pagina.close();
  }
}
await navegador.close();

// ---------------------------------------------------------------------------
// Informe
// ---------------------------------------------------------------------------
fs.writeFileSync(path.join(SALIDA, "desbordes.json"), JSON.stringify(salida, null, 1) + "\n");
if (AXE) fs.writeFileSync(path.join(SALIDA, "axe.json"), JSON.stringify(accesibilidad, null, 1) + "\n");
if (Object.keys(avisosTactiles).length) fs.writeFileSync(path.join(SALIDA, "tactiles.json"), JSON.stringify(avisosTactiles, null, 1) + "\n");

const celda = (m) => {
  if (!m) return "-";
  if (m.error) return "ERROR";
  const d = m.scrollWidth - m.clientWidth;
  return d > 0 || m.elementos.length || m.absolutos.length ? `${d}/${m.elementos.length}/${m.absolutos.length}` : "ok";
};
console.log("Desbordes (ok, o página px / elementos / absolutos que escapan):");
console.log(["pantalla", ...ANCHOS].join("\t"));
const nombres = [...new Set(Object.keys(salida).map((k) => k.split("@")[0]))];
for (const n of nombres) console.log([n, ...ANCHOS.map((a) => celda(salida[`${n}@${a}`]))].join("\t"));

let fallos = 0;
for (const [k, m] of Object.entries(salida)) {
  if (m.error) { fallos++; console.log(`ERROR ${k}: ${m.error}`); continue; }
  if (m.scrollWidth > m.clientWidth) { fallos++; console.log(`PAGINA ${k}: ${m.scrollWidth - m.clientWidth} px de desplazamiento horizontal`); }
  if (m.elementos.length) { fallos++; console.log(`DESBORDE ${k}: ${JSON.stringify(m.elementos.slice(0, 3))}`); }
  if (m.absolutos.length) { fallos++; console.log(`ABSOLUTO ${k}: ${JSON.stringify(m.absolutos.slice(0, 3))}`); }
}
if (AXE) {
  for (const [k, vs] of Object.entries(accesibilidad)) {
    if (!vs.length) continue;
    fallos++;
    console.log(`AXE ${k}: ${vs.map((v) => `${v.id} (${v.impacto}, ${v.total}) ${v.nodos.join(" | ")}`).join("; ")}`);
  }
  const revisadas = Object.keys(accesibilidad).length;
  console.log(`Axe: ${revisadas} vistas a ${ANCHOS_AXE.join(" y ")} px, ${Object.values(accesibilidad).filter((v) => v.length).length} con infracciones.`);
}
const avisos = Object.keys(avisosTactiles).length;
if (avisos) console.log(`Aviso: ${avisos} vistas con controles de menos de 44 px de alto (ver tactiles.json).`);
console.log(`Resultados en ${path.relative(FRONTEND, SALIDA)}. ${fallos ? `${fallos} problemas.` : "Sin problemas."}`);
process.exitCode = fallos ? 1 : 0;
