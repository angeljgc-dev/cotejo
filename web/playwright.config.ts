import { defineConfig, devices } from "@playwright/test";

// Contra el backend real: COTEJO_URL=http://localhost:8000 npm run e2e
// Sin COTEJO_URL se levanta Vite con el backend simulado en un puerto libre al azar; el puerto se
// guarda en el entorno para que los procesos de prueba lean el mismo valor.
if (!process.env.COTEJO_URL && !process.env.E2E_PUERTO) {
  process.env.E2E_PUERTO = String(20000 + Math.floor(Math.random() * 20000));
}
const puerto = process.env.E2E_PUERTO;
const urlBase = process.env.COTEJO_URL ?? `http://127.0.0.1:${puerto}`;

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? "github" : "list",
  use: {
    baseURL: urlBase,
    trace: "retain-on-failure",
    locale: "es-MX",
    timezoneId: "America/Mexico_City",
  },
  projects: [
    {
      name: "escritorio",
      use: { ...devices["Desktop Chrome"], viewport: { width: 1280, height: 800 } },
    },
    {
      name: "telefono",
      use: { ...devices["Desktop Chrome"], viewport: { width: 375, height: 812 } },
    },
  ],
  webServer: process.env.COTEJO_URL
    ? undefined
    : {
        command: `npm run dev:ejemplo -- --host 127.0.0.1 --port ${puerto} --strictPort`,
        url: urlBase,
        reuseExistingServer: false,
        timeout: 60_000,
      },
});
