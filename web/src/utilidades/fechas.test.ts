import { describe, expect, it } from "vitest";
import { formatearFecha, formatearFechaHora, textoVencimiento } from "./fechas";

describe("formatearFecha", () => {
  it("formatea una fecha ISO sin moverla de día", () => {
    expect(formatearFecha("2026-11-09")).toBe("9 nov 2026");
    expect(formatearFecha("2026-01-31")).toBe("31 ene 2026");
    expect(formatearFecha("2026-12-01")).toBe("1 dic 2026");
  });

  it("deja intacto un texto que no es fecha", () => {
    expect(formatearFecha("ayer")).toBe("ayer");
  });
});

describe("formatearFechaHora", () => {
  it("convierte a la hora de la Ciudad de México", () => {
    expect(formatearFechaHora("2026-11-09T16:15:00Z")).toBe("9 nov 2026, 10:15");
  });

  it("respeta el cambio de día y de mes al convertir", () => {
    expect(formatearFechaHora("2026-11-10T05:30:00Z")).toBe("9 nov 2026, 23:30");
    expect(formatearFechaHora("2026-12-01T03:00:00Z")).toBe("30 nov 2026, 21:00");
  });
});

describe("textoVencimiento", () => {
  it("describe vencidas, por vencer y el día de hoy", () => {
    expect(textoVencimiento(12)).toBe("Vencida hace 12 días");
    expect(textoVencimiento(1)).toBe("Vencida hace 1 día");
    expect(textoVencimiento(0)).toBe("Vence hoy");
    expect(textoVencimiento(-5)).toBe("Vence en 5 días");
    expect(textoVencimiento(-1)).toBe("Vence mañana");
    expect(textoVencimiento(null)).toBe("Sin vencimiento");
  });
});
