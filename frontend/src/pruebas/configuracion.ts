// Configuración común de Vitest: matchers de jest-dom (toBeInTheDocument, etc.) y limpieza del
// DOM y del almacenamiento de sesión entre pruebas.
import "@testing-library/jest-dom/vitest";
import { cleanup, configure } from "@testing-library/react";
import { afterEach } from "vitest";

// findBy y waitFor esperan hasta 5 s (1 s por omisión): con la máquina cargada (por ejemplo, el servicio
// modelos calentando) una pantalla puede tardar más de 1 s en mostrarse en jsdom. Solo alarga la espera
// máxima; las pruebas que pasan no tardan más.
configure({ asyncUtilTimeout: 5000 });

afterEach(() => {
  cleanup();
  sessionStorage.clear();
});
