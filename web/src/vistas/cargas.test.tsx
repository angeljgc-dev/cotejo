import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { montar } from "../pruebas/utilidades";

function xml(nombre: string) {
  return new File(['<cfdi:Comprobante Version="4.0"/>'], nombre, { type: "application/xml" });
}

describe("carga de CFDI por lote", () => {
  it("muestra el resultado y los motivos de cada archivo", async () => {
    const { usuario } = montar("/facturas/cargar");
    const entrada = await screen.findByLabelText(/Archivos XML/);
    await usuario.upload(entrada, [
      xml("buena.xml"),
      xml("con_alerta.xml"),
      xml("cfdi33.xml"),
      xml("dup_A4410.xml"),
      new File(["%PDF-1.4"], "escaneo.pdf", { type: "application/pdf" }),
    ]);
    expect(screen.getByText("5 archivos listos para cargar.")).toBeInTheDocument();
    await usuario.click(screen.getByRole("button", { name: "Validar y cargar" }));

    const tabla = await screen.findByRole("table", { name: "Resultado por archivo" });
    const fila = (nombre: string) => within(tabla).getByText(nombre).closest("tr") as HTMLElement;

    expect(within(fila("buena.xml")).getByText("Aceptada")).toBeInTheDocument();
    expect(within(fila("con_alerta.xml")).getByText("Aceptada con alertas")).toBeInTheDocument();
    expect(within(fila("con_alerta.xml")).getByText(/El total no cuadra/)).toBeInTheDocument();
    expect(within(fila("cfdi33.xml")).getByText("Rechazada")).toBeInTheDocument();
    expect(within(fila("cfdi33.xml")).getByText(/solo acepta CFDI 4.0/)).toBeInTheDocument();
    expect(within(fila("dup_A4410.xml")).getByText("Ya existía")).toBeInTheDocument();
    expect(within(fila("dup_A4410.xml")).getByText(/ya estaba registrado/)).toBeInTheDocument();
    expect(
      within(fila("escaneo.pdf")).getByText(/Solo se aceptan archivos .xml/),
    ).toBeInTheDocument();

    expect(screen.getByText("1 aceptadas")).toBeInTheDocument();
    expect(screen.getByText("2 rechazadas")).toBeInTheDocument();
  });

  it("el aprobador no puede cargar y se le explica por qué", async () => {
    montar("/facturas/cargar", { sesion: "aprobador" });
    expect(await screen.findByText(/Solo el rol capturista carga facturas/)).toBeInTheDocument();
    expect(screen.queryByLabelText(/Archivos XML/)).not.toBeInTheDocument();
  });
});

describe("subida de documentos", () => {
  it("un PDF escaneado queda marcado sin texto con su explicación", async () => {
    const { usuario } = montar("/documentos");
    const entrada = await screen.findByLabelText(/^Archivos/);
    await usuario.upload(entrada, [
      new File(["%PDF-1.4"], "contrato_escaneado.pdf", { type: "application/pdf" }),
      new File(["# Política"], "politica.md", { type: "text/markdown" }),
    ]);
    await usuario.click(screen.getByRole("button", { name: "Subir documentos" }));
    const tabla = await screen.findByRole("table", { name: "Resultado por documento" });
    const fila = within(tabla).getByText("contrato_escaneado.pdf").closest("tr") as HTMLElement;
    expect(within(fila).getByText("Sin texto")).toBeInTheDocument();
    expect(within(fila).getByText(/parece una imagen escaneada/)).toBeInTheDocument();
    const otra = within(tabla).getByText("politica.md").closest("tr") as HTMLElement;
    expect(within(otra).getByText("Listo para consultar")).toBeInTheDocument();
  });
});
