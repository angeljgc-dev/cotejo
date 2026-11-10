import { describe, expect, it } from "vitest";
import { formatearImporte, normalizarImporteCapturado, proporcionMilesimas } from "./importes";

describe("formatearImporte", () => {
  it("agrupa miles con coma y conserva dos decimales", () => {
    expect(formatearImporte("1160.00")).toBe("$1,160.00");
    expect(formatearImporte("1234567.89")).toBe("$1,234,567.89");
    expect(formatearImporte("999.99")).toBe("$999.99");
  });

  it("completa a dos decimales sin redondear ni recortar", () => {
    expect(formatearImporte("15")).toBe("$15.00");
    expect(formatearImporte("15.5")).toBe("$15.50");
    expect(formatearImporte("12.345600")).toBe("$12.345600");
  });

  it("muestra los negativos con signo menos antes del símbolo", () => {
    expect(formatearImporte("-1234.50")).toBe("−$1,234.50");
    expect(formatearImporte("-0.00")).toBe("$0.00");
  });

  it("quita ceros a la izquierda", () => {
    expect(formatearImporte("0001.50")).toBe("$1.50");
    expect(formatearImporte("0")).toBe("$0.00");
  });

  it("usa el código de moneda cuando no es MXN", () => {
    expect(formatearImporte("2500.00", "USD")).toBe("2,500.00 USD");
    expect(formatearImporte("-10.00", "EUR")).toBe("−10.00 EUR");
  });

  it("agrega MXN si se pide el código explícito", () => {
    expect(formatearImporte("1160.00", "MXN", { codigo: true })).toBe("$1,160.00 MXN");
  });

  it("deja intacto un texto que no es un decimal válido", () => {
    expect(formatearImporte("abc")).toBe("abc");
    expect(formatearImporte("1e5")).toBe("1e5");
    expect(formatearImporte("")).toBe("");
  });

  it("no pierde precisión con cifras que el punto flotante no representa", () => {
    expect(formatearImporte("90071992547409931.37")).toBe("$90,071,992,547,409,931.37");
    expect(formatearImporte("0.10")).toBe("$0.10");
  });
});

describe("proporcionMilesimas", () => {
  it("calcula la parte en milésimas con enteros exactos", () => {
    expect(proporcionMilesimas("250.00", "1000.00")).toBe(250);
    expect(proporcionMilesimas("1000.00", "1000.00")).toBe(1000);
    expect(proporcionMilesimas("0.01", "3.00")).toBe(3);
  });

  it("devuelve cero si el total es cero o algún texto es inválido", () => {
    expect(proporcionMilesimas("10.00", "0.00")).toBe(0);
    expect(proporcionMilesimas("x", "10.00")).toBe(0);
  });

  it("acota el resultado entre 0 y 1000", () => {
    expect(proporcionMilesimas("2000.00", "1000.00")).toBe(1000);
    expect(proporcionMilesimas("-5.00", "1000.00")).toBe(0);
  });
});

describe("normalizarImporteCapturado", () => {
  it("acepta pesos con comas de miles y hasta dos decimales", () => {
    expect(normalizarImporteCapturado("150,000")).toBe("150000.00");
    expect(normalizarImporteCapturado(" $2,500.5 ")).toBe("2500.50");
    expect(normalizarImporteCapturado("80000.25")).toBe("80000.25");
  });

  it("rechaza cero, negativos, letras y más de dos decimales", () => {
    expect(normalizarImporteCapturado("0")).toBeNull();
    expect(normalizarImporteCapturado("-100")).toBeNull();
    expect(normalizarImporteCapturado("cien")).toBeNull();
    expect(normalizarImporteCapturado("10.123")).toBeNull();
    expect(normalizarImporteCapturado("")).toBeNull();
  });
});
