import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { type ClienteApi, ErrorApi } from "../api/cliente";
import { montar } from "../pruebas/utilidades";

async function preguntar(usuario: ReturnType<typeof montar>["usuario"], texto: string) {
  const campo = await screen.findByLabelText("Tu pregunta");
  await usuario.type(campo, texto);
  await usuario.click(screen.getByRole("button", { name: "Preguntar" }));
}

describe("citas (D2)", () => {
  it("una cita abre el fragmento del documento con su página", async () => {
    const { usuario } = montar("/asistente");
    await preguntar(usuario, "¿Qué dice el contrato sobre pagos tardíos?");
    const cita = await screen.findByRole("button", {
      name: "Fuente 2: Contrato de suministro Aceros del Norte.pdf, página 3",
    });
    await usuario.click(cita);
    const panel = await screen.findByRole("complementary", {
      name: "Contrato de suministro Aceros del Norte.pdf",
    });
    expect(within(panel).getByText(/pena convencional de 1.5% mensual/)).toBeInTheDocument();
    expect(within(panel).getByText("Página 3")).toBeInTheDocument();
    expect(within(panel).getByRole("heading")).toHaveFocus();
  });

  it("el panel navega al fragmento anterior y se cierra", async () => {
    const { usuario } = montar("/asistente");
    await preguntar(usuario, "condiciones del contrato");
    await usuario.click(
      await screen.findByRole("button", {
        name: "Fuente 2: Contrato de suministro Aceros del Norte.pdf, página 3",
      }),
    );
    await usuario.click(await screen.findByRole("button", { name: "Fragmento anterior" }));
    expect(await screen.findByText(/Cláusula Séptima/)).toBeInTheDocument();
    await usuario.click(screen.getByRole("button", { name: "Cerrar fragmento" }));
    expect(screen.queryByRole("complementary", { name: /Contrato/ })).not.toBeInTheDocument();
  });
});

describe("cómo lo calculé (D1, D7) y propuestas (D3)", () => {
  it("muestra herramientas usadas y facturas base con enlace", async () => {
    const { usuario } = montar("/asistente");
    await preguntar(usuario, "¿Cuánto le debemos a Aceros del Norte?");
    await usuario.click(await screen.findByText("Cómo lo calculé"));
    expect(screen.getByText("adeudo_por_proveedor")).toBeInTheDocument();
    const tabla = screen.getByRole("table", { name: "Facturas en que se basa la respuesta" });
    expect(within(tabla).getByRole("link", { name: "A-4410" })).toHaveAttribute(
      "href",
      "/facturas/101",
    );
  });

  it("una respuesta que creó una propuesta enlaza a ella", async () => {
    const { usuario } = montar("/asistente");
    await preguntar(usuario, "Propón los pagos de esta semana con presupuesto de 300 mil");
    expect(await screen.findByRole("link", { name: "Abrir la propuesta 3" })).toHaveAttribute(
      "href",
      "/propuestas/3",
    );
  });
});

describe("sin llave de modelo (D8)", () => {
  it("explica que no está configurado, desactiva el chat y ofrece el resto", async () => {
    montar("/asistente", { asistente: "sin_llave" });
    expect(
      await screen.findByText(/El asistente no está configurado en esta instalación/),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Tu pregunta")).toBeDisabled();
    expect(screen.getByRole("button", { name: "Preguntar" })).toBeDisabled();
    expect(screen.getByRole("link", { name: "facturas" })).toHaveAttribute("href", "/facturas");
  });

  it("si el servidor responde 503 al enviar, se muestra el motivo sin romper la vista", async () => {
    const ajustar = (c: ClienteApi): ClienteApi => ({
      ...c,
      enviarMensaje: async () => {
        throw new ErrorApi(
          503,
          "ASISTENTE_NO_CONFIGURADO",
          "El asistente no está configurado en esta instalación. El resto de Cotejo funciona normalmente.",
        );
      },
    });
    const { usuario } = montar("/asistente", {}, ajustar);
    await preguntar(usuario, "hola");
    expect(await screen.findByRole("alert")).toHaveTextContent(/El resto de Cotejo funciona/);
    expect(screen.getByRole("heading", { name: "Asistente" })).toBeInTheDocument();
  });
});

describe("cuota diaria (D10)", () => {
  it("muestra las preguntas restantes y baja al enviar una", async () => {
    const { usuario } = montar("/asistente");
    expect(await screen.findByText("Te quedan 17 de 20 preguntas hoy.")).toBeInTheDocument();
    await preguntar(usuario, "¿Cuánto le debemos a Aceros del Norte?");
    expect(await screen.findByText("Te quedan 16 de 20 preguntas hoy.")).toBeInTheDocument();
  });

  it("sin cuota, lo dice y desactiva el envío", async () => {
    montar("/asistente", { asistente: "sin_cuota" });
    expect(await screen.findByText(/Ya usaste las 20 preguntas de hoy/)).toBeInTheDocument();
    expect(screen.getByLabelText("Tu pregunta")).toBeDisabled();
  });

  it("un 429 del servidor dice cuándo se reinicia la cuota", async () => {
    const ajustar = (c: ClienteApi): ClienteApi => ({
      ...c,
      enviarMensaje: async () => {
        throw new ErrorApi(429, "LIMITE_CHAT", "Llegaste al límite de preguntas de hoy.", {
          limite: 20,
          se_reinicia: "2026-11-10T00:00:00-06:00",
        });
      },
    });
    const { usuario } = montar("/asistente", {}, ajustar);
    await preguntar(usuario, "hola");
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Llegaste al límite de preguntas de hoy. Podrás intentarlo de nuevo a partir del 10 nov 2026, 00:00.",
    );
  });
});
