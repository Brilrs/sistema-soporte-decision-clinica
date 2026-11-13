// Configuración común de Vitest: matchers de jest-dom (toBeInTheDocument, etc.) y limpieza del
// DOM y del almacenamiento de sesión entre pruebas.
import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

afterEach(() => {
  cleanup();
  sessionStorage.clear();
});
