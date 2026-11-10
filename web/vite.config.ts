import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": "http://localhost:8000",
    },
  },
  build: {
    // Las fuentes y las imágenes se sirven como archivos: la política de seguridad de contenido
    // del backend no admite fuentes en data: URI.
    assetsInlineLimit: 0,
    sourcemap: false,
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/pruebas/preparacion.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
    css: false,
  },
});
