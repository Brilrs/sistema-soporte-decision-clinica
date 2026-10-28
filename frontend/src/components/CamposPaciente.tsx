// Datos permanentes del paciente: identificación (cifrada en el servidor) y datos al nacer.
// Se usan en el registro (M03) y en la corrección de datos (HU04).
import type { Distrito, EdadGestacional, Ficha, PacienteEntrada, Sexo } from "../api/pacientes";
import { EDADES_GESTACIONALES, edad, edadEnMeses, hoyIso } from "../utilidades/formato";

export type FormPaciente = {
  nombres_apellidos: string;
  dni: string;
  numero_hc: string;
  direccion: string;
  ubigeo_residencia: string;
  fecha_nacimiento: string;
  sexo: Sexo | "";
  edad_gestacional_nacer: EdadGestacional;
  bajo_peso_nacer: boolean;
};

export const formPacienteVacio: FormPaciente = {
  nombres_apellidos: "",
  dni: "",
  numero_hc: "",
  direccion: "",
  ubigeo_residencia: "",
  fecha_nacimiento: "",
  sexo: "",
  edad_gestacional_nacer: "NO_REGISTRADO",
  bajo_peso_nacer: false,
};

export function formPacienteDesdeFicha(f: Ficha): FormPaciente {
  return {
    nombres_apellidos: f.nombres_apellidos,
    dni: f.dni,
    numero_hc: f.numero_hc,
    direccion: f.direccion ?? "",
    ubigeo_residencia: f.ubigeo_residencia,
    fecha_nacimiento: f.fecha_nacimiento,
    sexo: f.sexo,
    edad_gestacional_nacer: f.edad_gestacional_nacer,
    bajo_peso_nacer: !!f.bajo_peso_nacer,
  };
}

export function aEntradaPaciente(f: FormPaciente): PacienteEntrada {
  return {
    nombres_apellidos: f.nombres_apellidos.trim(),
    dni: f.dni.trim(),
    numero_hc: f.numero_hc.trim(),
    direccion: f.direccion.trim() || null,
    ubigeo_residencia: f.ubigeo_residencia,
    fecha_nacimiento: f.fecha_nacimiento,
    sexo: f.sexo as Sexo,
    edad_gestacional_nacer: f.edad_gestacional_nacer,
    bajo_peso_nacer: f.bajo_peso_nacer,
  };
}

export function pacienteCompleto(f: FormPaciente): boolean {
  return !!(f.nombres_apellidos.trim() && /^\d{8}$/.test(f.dni.trim()) && f.numero_hc.trim()
    && f.ubigeo_residencia && f.fecha_nacimiento && f.sexo);
}

type Props = { valor: FormPaciente; cambiar: (cambios: Partial<FormPaciente>) => void };

const Ob = () => <span className="obligatorio"> *</span>;

export function CamposIdentificacion({ valor, cambiar, distritos }: Props & { distritos: Distrito[] }) {
  const distrito = distritos.find((d) => d.ubigeo === valor.ubigeo_residencia);
  return (
    <>
      <h2>Identificación<span className="etiqueta etiqueta--privado">no se comparte fuera del sistema</span></h2>
      <label htmlFor="nombres">Nombres y apellidos<Ob /></label>
      <input id="nombres" value={valor.nombres_apellidos} maxLength={150} autoComplete="off"
             onChange={(e) => cambiar({ nombres_apellidos: e.target.value })} />
      <div className="rejilla rejilla--2">
        <div>
          <label htmlFor="dni">DNI<Ob /></label>
          <input id="dni" value={valor.dni} inputMode="numeric" maxLength={8} autoComplete="off"
                 onChange={(e) => cambiar({ dni: e.target.value.replace(/\D/g, "") })} />
        </div>
        <div>
          <label htmlFor="hc">N.° HC<Ob /></label>
          <input id="hc" value={valor.numero_hc} maxLength={20} autoComplete="off"
                 onChange={(e) => cambiar({ numero_hc: e.target.value })} />
        </div>
      </div>
      <label htmlFor="direccion">Dirección</label>
      <input id="direccion" value={valor.direccion} maxLength={250} autoComplete="off"
             onChange={(e) => cambiar({ direccion: e.target.value })} />
      <label htmlFor="distrito">Distrito de residencia<Ob /></label>
      <select id="distrito" value={valor.ubigeo_residencia} onChange={(e) => cambiar({ ubigeo_residencia: e.target.value })}>
        <option value="">Seleccione…</option>
        {distritos.map((d) => <option key={d.ubigeo} value={d.ubigeo}>{d.nombre}, {d.provincia}</option>)}
      </select>
      <label htmlFor="altitud">Altitud (m.s.n.m.)</label>
      <input id="altitud" readOnly value={distrito ? `${distrito.altitud_msnm}  ·  calculada por distrito` : "Se calcula a partir del distrito"} />
    </>
  );
}

export function CamposNacimiento({ valor, cambiar, fechaReferencia }: Props & { fechaReferencia?: string }) {
  const referencia = fechaReferencia || hoyIso();
  return (
    <div className="rejilla">
      <div>
        <label htmlFor="nacimiento">Fecha de nacimiento<Ob /></label>
        <input id="nacimiento" type="date" max={hoyIso()} value={valor.fecha_nacimiento}
               onChange={(e) => cambiar({ fecha_nacimiento: e.target.value })} />
      </div>
      <div>
        <label htmlFor="edad">Edad</label>
        <input id="edad" readOnly value={edad(edadEnMeses(valor.fecha_nacimiento, referencia))} />
      </div>
      <div>
        <label htmlFor="sexo">Sexo<Ob /></label>
        <select id="sexo" value={valor.sexo} onChange={(e) => cambiar({ sexo: e.target.value as Sexo | "" })}>
          <option value="">Seleccione…</option>
          <option value="M">Masculino</option>
          <option value="F">Femenino</option>
        </select>
      </div>
      <div>
        <label htmlFor="gestacional">Edad gestacional al nacer</label>
        <select id="gestacional" value={valor.edad_gestacional_nacer}
                onChange={(e) => cambiar({ edad_gestacional_nacer: e.target.value as EdadGestacional })}>
          {Object.entries(EDADES_GESTACIONALES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
      </div>
      <div>
        <label htmlFor="bajo-peso">Bajo peso al nacer</label>
        <label className="casilla" style={{ marginTop: ".6rem" }}>
          <input id="bajo-peso" type="checkbox" checked={valor.bajo_peso_nacer}
                 onChange={(e) => cambiar({ bajo_peso_nacer: e.target.checked })} />
          Sí
        </label>
      </div>
    </div>
  );
}
