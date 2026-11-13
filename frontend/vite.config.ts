/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// En desarrollo, /api se redirige al backend (uvicorn en el puerto 8000).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { "/api": "http://localhost:8000" },
  },
  // Pruebas (npm test): Vitest con jsdom; los fixtures del contrato están en src/__fixtures__.
  test: {
    environment: "jsdom",
    setupFiles: ["./src/pruebas/configuracion.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
    restoreMocks: true,
    unstubGlobals: true,
  },
});
