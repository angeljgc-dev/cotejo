import { render } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import { MemoryRouter } from "react-router";
import { App } from "../App";
import type { ClienteApi } from "../api/cliente";
import { crearClienteEjemplo, type OpcionesEjemplo } from "../ejemplo/clienteEjemplo";

/** Monta la aplicación completa en una ruta con el backend simulado. */
export function montar(
  ruta: string,
  opciones: OpcionesEjemplo = {},
  ajustar?: (cliente: ClienteApi) => ClienteApi,
) {
  const base = crearClienteEjemplo({ sesion: "capturista", ...opciones });
  const cliente = ajustar ? ajustar(base) : base;
  const usuario = userEvent.setup({ applyAccept: false });
  const resultado = render(
    <MemoryRouter initialEntries={[ruta]}>
      <App cliente={cliente} />
    </MemoryRouter>,
  );
  return { ...resultado, usuario, cliente };
}

/**
 * Corre axe sobre el documento. El contraste no se mide aquí porque jsdom no calcula estilos;
 * lo cubren la prueba de tokens y la de Playwright en el navegador.
 */
export async function violacionesAxe(contenedor: Element = document.body): Promise<string[]> {
  const resultado = await axe.run(contenedor, {
    rules: { "color-contrast": { enabled: false } },
  });
  return resultado.violations.map(
    (v) => `${v.id}: ${v.help} (${v.nodes.map((n) => n.target.join(" ")).join(", ")})`,
  );
}
