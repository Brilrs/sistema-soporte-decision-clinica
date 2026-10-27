// Catálogos de distritos y síntomas para los formularios (se cargan una vez por pantalla).
import { useEffect, useState } from "react";
import { pacientesApi, type Distrito, type Sintoma } from "./pacientes";
import { mensajeError } from "./cliente";

export function useCatalogos() {
  const [distritos, setDistritos] = useState<Distrito[]>([]);
  const [sintomas, setSintomas] = useState<Sintoma[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([pacientesApi.distritos(), pacientesApi.sintomas()])
      .then(([d, s]) => {
        setDistritos(d);
        setSintomas(s);
      })
      .catch((e) => setError(mensajeError(e)));
  }, []);

  return { distritos, sintomas, error };
}
