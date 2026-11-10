import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { ClienteApi } from "../api/cliente";
import { montar } from "../pruebas/utilidades";

// D4: aprobar y rechazar se muestran solo cuando la API dice `puede_decidir`.

function conPuedeDecidir(valor: boolean) {
  return (cliente: ClienteApi): ClienteApi => ({
    ...cliente,
    propuesta: async (id) => ({ ...(await cliente.propuesta(id)), puede_decidir: valor }),
  });
}

describe("decisión sobre propuestas", () => {
  it("el aprobador ve aprobar y rechazar en una propuesta pendiente de otra persona", async () => {
    montar("/propuestas/3", { sesion: "aprobador" });
    expect(
      await screen.findByRole("button", { name: "Aprobar y registrar 3 pagos" }),
    ).toBeEnabled();
    expect(screen.getByRole("button", { name: "Rechazar propuesta" })).toBeInTheDocument();
  });

  it("el capturista no ve los botones y se le explica quién decide", async () => {
    montar("/propuestas/3", { sesion: "capturista" });
    expect(await screen.findByText(/Solo el rol aprobador puede aprobarla/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Aprobar/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Rechazar/ })).not.toBeInTheDocument();
  });

  it("si la API dice que no puede decidir, un aprobador tampoco ve los botones", async () => {
    montar("/propuestas/3", { sesion: "aprobador" }, conPuedeDecidir(false));
    expect(await screen.findByText(/Tú creaste esta propuesta/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Aprobar/ })).not.toBeInTheDocument();
  });

  it("los botones dependen de la API y no del rol que la interfaz cree conocer", async () => {
    montar("/propuestas/3", { sesion: "capturista" }, conPuedeDecidir(true));
    expect(await screen.findByRole("button", { name: /Aprobar y registrar/ })).toBeInTheDocument();
  });

  it("una propuesta ya decidida no muestra botones a nadie", async () => {
    montar("/propuestas/2", { sesion: "aprobador" });
    expect(await screen.findByText(/Aprobada por Ricardo Salas/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Aprobar/ })).not.toBeInTheDocument();
  });

  it("aprobar registra la decisión y la muestra", async () => {
    const { usuario } = montar("/propuestas/3", { sesion: "aprobador" });
    await usuario.click(await screen.findByRole("button", { name: "Aprobar y registrar 3 pagos" }));
    expect(await screen.findByText(/Aprobada por Ricardo Salas/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Aprobar/ })).not.toBeInTheDocument();
  });

  it("rechazar exige un motivo de al menos 5 caracteres", async () => {
    const { usuario } = montar("/propuestas/3", { sesion: "aprobador" });
    await usuario.click(await screen.findByRole("button", { name: "Rechazar propuesta" }));
    await usuario.type(screen.getByLabelText(/Motivo del rechazo/), "no");
    await usuario.click(screen.getByRole("button", { name: "Confirmar rechazo" }));
    expect(screen.getByText("Escribe entre 5 y 500 caracteres.")).toBeInTheDocument();
    await usuario.type(screen.getByLabelText(/Motivo del rechazo/), " cuadra el monto");
    await usuario.click(screen.getByRole("button", { name: "Confirmar rechazo" }));
    expect(await screen.findByText(/Motivo: no cuadra el monto/)).toBeInTheDocument();
  });
});

describe("acciones visibles por rol", () => {
  it("solo el capturista ve Cargar CFDI y Nueva propuesta", async () => {
    montar("/facturas", { sesion: "capturista" });
    expect(await screen.findByRole("link", { name: "Cargar CFDI" })).toBeInTheDocument();

    montar("/facturas", { sesion: "aprobador" });
    await screen.findAllByText("A-4410");
    const vistas = screen.getAllByRole("main");
    expect(
      within(vistas[1] as HTMLElement).queryByRole("link", { name: "Cargar CFDI" }),
    ).toBeNull();
  });

  it("solo el aprobador puede resolver alertas de una factura", async () => {
    montar("/facturas/114", { sesion: "capturista" });
    await screen.findByText(/Posible duplicado/);
    expect(screen.queryByRole("button", { name: "Resolver alerta" })).not.toBeInTheDocument();
  });

  it("el aprobador resuelve una alerta con nota y queda marcada", async () => {
    const { usuario } = montar("/facturas/114", { sesion: "aprobador" });
    await usuario.click(await screen.findByRole("button", { name: "Resolver alerta" }));
    await usuario.type(screen.getByLabelText(/Nota de resolución/), "Son dos entregas distintas.");
    await usuario.click(screen.getByRole("button", { name: "Marcar como resuelta" }));
    expect(await screen.findByText(/Resuelta por Ricardo Salas/)).toBeInTheDocument();
  });

  it("el posible duplicado enlaza a la otra factura", async () => {
    montar("/facturas/114");
    const enlace = await screen.findByRole("link", { name: /Abrir la otra factura/ });
    expect(enlace).toHaveAttribute("href", "/facturas/103");
  });
});
