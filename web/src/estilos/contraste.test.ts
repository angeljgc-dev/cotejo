import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { contraste } from "../utilidades/contraste";

const css = readFileSync(resolve(__dirname, "tokens.css"), "utf8");

function token(nombre: string): string {
  const m = new RegExp(`--${nombre}:\\s*(#[0-9a-fA-F]{6})`).exec(css);
  if (!m?.[1]) throw new Error(`Falta el token --${nombre}`);
  return m[1];
}

describe("contraste", () => {
  it("calcula la razón WCAG de colores conocidos", () => {
    expect(contraste("#000000", "#ffffff")).toBeCloseTo(21, 1);
    expect(contraste("#777777", "#ffffff")).toBeCloseTo(4.48, 1);
  });
});

describe("tokens de color cumplen WCAG AA", () => {
  const texto: [string, string][] = [
    ["tinta", "papel"],
    ["tinta", "superficie"],
    ["tinta-suave", "papel"],
    ["tinta-suave", "superficie"],
    ["tinta-suave", "superficie-hundida"],
    ["jade", "superficie"],
    ["jade", "papel"],
    ["jade", "jade-claro"],
    ["sobre-jade", "jade"],
    ["sobre-jade", "jade-hover"],
    ["ambar", "ambar-fondo"],
    ["bermellon", "bermellon-fondo"],
    ["bermellon", "superficie"],
    ["exito", "exito-fondo"],
  ];
  it.each(texto)("texto %s sobre %s llega a 4.5:1", (frente, fondo) => {
    expect(contraste(token(frente), token(fondo))).toBeGreaterThanOrEqual(4.5);
  });

  const graficos: [string, string][] = [
    ["linea-fuerte", "superficie"],
    ["foco", "papel"],
    ["foco", "superficie"],
    ["edad-por-vencer", "superficie"],
    ["edad-1-30", "superficie"],
    ["edad-31-60", "superficie"],
    ["edad-61-90", "superficie"],
    ["edad-mas-90", "superficie"],
    ["ambar-borde", "ambar-fondo"],
  ];
  it.each(graficos)("elemento gráfico %s sobre %s llega a 3:1", (frente, fondo) => {
    expect(contraste(token(frente), token(fondo))).toBeGreaterThanOrEqual(3);
  });
});
