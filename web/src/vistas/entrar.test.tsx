import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ErrorApi } from "../api/cliente";
import { montar, violacionesAxe } from "../pruebas/utilidades";

describe("entrar a la demo (F3)", () => {
  it("avisa que los datos son ficticios y no tiene violaciones de axe", async () => {
    montar("/", { sesion: null });
    expect(await screen.findByText(/Esta es una demo con datos ficticios/)).toBeInTheDocument();
    expect(await violacionesAxe()).toEqual([]);
  });

  it("entra con un clic como aprobador", async () => {
    const { usuario } = montar("/", { sesion: null });
    await usuario.click(await screen.findByRole("button", { name: "Entrar como aprobador" }));
    expect(await screen.findByText("Rol aprobador")).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "Tablero", level: 1 })).toBeInTheDocument();
  });

  it("dentro de la app el aviso de demo sigue visible y se puede reiniciar", async () => {
    const { usuario } = montar("/");
    expect(await screen.findByText(/Demo pública con datos ficticios/)).toBeInTheDocument();
    await usuario.click(screen.getByRole("button", { name: "Reiniciar demo" }));
    expect(
      await screen.findByText(/Demo reiniciada: 16 facturas y 3 documentos/),
    ).toBeInTheDocument();
  });

  it("si el reinicio está limitado, explica cuándo volver a intentar", async () => {
    const { usuario } = montar("/", {
      fallas: {
        reiniciarDemo: new ErrorApi(429, "LIMITE_REINICIO", "La demo se reinició hace poco.", {
          limite: 1,
          se_reinicia: "2026-11-09T18:02:00Z",
        }),
      },
    });
    await usuario.click(await screen.findByRole("button", { name: "Reiniciar demo" }));
    expect(
      await screen.findByText(
        "La demo se reinició hace poco. Podrás intentarlo de nuevo a partir del 9 nov 2026, 12:02.",
      ),
    ).toBeInTheDocument();
  });

  it("salir regresa a la pantalla de entrada", async () => {
    const { usuario } = montar("/");
    await usuario.click(await screen.findByRole("button", { name: "Salir" }));
    expect(
      await screen.findByRole("button", { name: "Entrar como capturista" }),
    ).toBeInTheDocument();
  });
});

describe("tablero (B4, B5)", () => {
  it("muestra el adeudo total y la moneda extranjera con su equivalente", async () => {
    montar("/");
    expect(await screen.findByText("Adeudo total")).toBeInTheDocument();
    expect(screen.getByText("2,784.00 USD")).toBeInTheDocument();
    expect(screen.getByText("$51,370.37 MXN")).toBeInTheDocument();
    expect(
      screen.getByRole("table", { name: "Antigüedad de saldos en pesos" }),
    ).toBeInTheDocument();
  });

  it("la lista de facturas muestra la factura en USD con su tipo de cambio", async () => {
    montar("/facturas?moneda=USD");
    expect(await screen.findByText("INT-2026-118")).toBeInTheDocument();
    expect(screen.getAllByText(/al TC 18.4520/).length).toBeGreaterThan(0);
  });
});
