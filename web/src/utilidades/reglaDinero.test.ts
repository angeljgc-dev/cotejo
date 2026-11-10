import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, resolve } from "node:path";
import { describe, expect, it } from "vitest";

// Regla de la interfaz: el dinero nunca pasa por punto flotante. Esta prueba busca en el código
// de la aplicación (no en las pruebas ni en el backend simulado) las conversiones típicas.
const RAIZ = resolve(__dirname, "..");
const PROHIBIDOS = [/parseFloat\s*\(/, /\.toFixed\s*\(/, /Number\.parseFloat/];

function archivos(dir: string): string[] {
  return readdirSync(dir).flatMap((nombre) => {
    const ruta = join(dir, nombre);
    if (statSync(ruta).isDirectory()) return nombre === "ejemplo" ? [] : archivos(ruta);
    return /\.(ts|tsx)$/.test(nombre) && !/\.test\.tsx?$/.test(nombre) ? [ruta] : [];
  });
}

describe("regla de dinero", () => {
  it("ningún archivo de la interfaz convierte importes a punto flotante", () => {
    const hallazgos = archivos(RAIZ).flatMap((ruta) => {
      const texto = readFileSync(ruta, "utf8");
      return PROHIBIDOS.filter((p) => p.test(texto)).map((p) => `${ruta}: ${p}`);
    });
    expect(hallazgos).toEqual([]);
  });
});
