import { expect, type Page } from "@playwright/test";

export const VISTAS = [
  { ruta: "/", titulo: "Tablero" },
  { ruta: "/facturas", titulo: "Facturas" },
  { ruta: "/proveedores", titulo: "Proveedores" },
  { ruta: "/documentos", titulo: "Documentos" },
  { ruta: "/propuestas", titulo: "Propuestas de pago" },
  { ruta: "/asistente", titulo: "Asistente" },
  { ruta: "/bitacora", titulo: "Bitácora" },
];

/** Entra a la demo con el rol pedido desde la pantalla de entrada. */
export async function entrarComo(page: Page, rol: "capturista" | "aprobador") {
  await page.goto("/");
  await page.getByRole("button", { name: `Entrar como ${rol}` }).click();
  await expect(page.getByRole("heading", { name: "Tablero", level: 1 })).toBeVisible();
}

/** Navega dentro de la aplicación sin recargar, como lo haría una persona con el menú. */
export async function irA(page: Page, ruta: string) {
  await page.evaluate((r) => {
    window.history.pushState({}, "", r);
    window.dispatchEvent(new PopStateEvent("popstate"));
  }, ruta);
}

/** Ancho del documento contra el de la ventana: debe caber sin scroll horizontal (F1). */
export async function sinScrollHorizontal(page: Page) {
  const { ancho, ventana } = await page.evaluate(() => ({
    ancho: document.documentElement.scrollWidth,
    ventana: document.documentElement.clientWidth,
  }));
  expect(ancho, "el contenido no debe ser más ancho que la ventana").toBeLessThanOrEqual(ventana);
}
