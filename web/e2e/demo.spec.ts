import { expect, type Page, test } from "@playwright/test";
import { entrarComo, irA, sinScrollHorizontal, VISTAS } from "./apoyo";

// La semilla de la demo debe traer al menos una propuesta pendiente creada por el capturista,
// para que quien entra como aprobador tenga algo que decidir.
async function abrirPropuestaPendiente(page: Page) {
  await irA(page, "/propuestas?estado=pendiente");
  await expect(page.locator(".cargando")).toHaveCount(0);
  const enlace = page.locator("table a[href^='/propuestas/']").first();
  await expect(enlace, "la demo necesita una propuesta pendiente").toBeVisible();
  await enlace.click();
  await expect(page.getByRole("heading", { name: "Facturas incluidas" })).toBeVisible();
}

test.describe("demo pública", () => {
  test("avisa que los datos son ficticios antes de entrar", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByText(/datos ficticios/).first()).toBeVisible();
    await expect(page.getByRole("button", { name: "Entrar como capturista" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Entrar como aprobador" })).toBeVisible();
    await sinScrollHorizontal(page);
  });

  test("el capturista recorre todas las vistas sin errores ni scroll horizontal", async ({
    page,
  }) => {
    await entrarComo(page, "capturista");
    await expect(page.getByRole("button", { name: "Reiniciar demo" })).toBeVisible();
    // Se escucha a partir de aquí: antes de entrar, GET /api/sesion responde 401 por contrato y el
    // navegador lo anota como error de red aunque la aplicación lo maneje.
    const errores: string[] = [];
    page.on("console", (m) => {
      if (m.type() === "error") errores.push(m.text());
    });
    for (const vista of VISTAS) {
      await irA(page, vista.ruta);
      await expect(page.getByRole("heading", { name: vista.titulo, level: 1 })).toBeVisible();
      await expect(page.locator(".cargando")).toHaveCount(0);
      await expect(page.getByRole("alert")).toHaveCount(0);
      await sinScrollHorizontal(page);
    }
    expect(errores).toEqual([]);
  });

  test("abre el detalle de una factura desde la lista", async ({ page }) => {
    await entrarComo(page, "capturista");
    await irA(page, "/facturas");
    await page.locator("table a[href^='/facturas/']").first().click();
    await expect(page.getByRole("heading", { name: /^Factura / })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Alertas" })).toBeVisible();
    await sinScrollHorizontal(page);
  });

  test("el capturista no ve botones para aprobar propuestas", async ({ page }) => {
    await entrarComo(page, "capturista");
    await abrirPropuestaPendiente(page);
    await expect(page.getByRole("button", { name: /Aprobar/ })).toHaveCount(0);
  });

  test("el aprobador ve aprobar y rechazar en una propuesta pendiente ajena", async ({ page }) => {
    await entrarComo(page, "aprobador");
    await abrirPropuestaPendiente(page);
    await expect(page.getByRole("button", { name: /Aprobar y registrar/ })).toBeVisible();
    await expect(page.getByRole("button", { name: "Rechazar propuesta" })).toBeVisible();
  });

  test("el asistente muestra su cuota o explica que no está configurado", async ({ page }) => {
    await entrarComo(page, "capturista");
    await irA(page, "/asistente");
    await expect(
      page.getByText(/Te quedan \d+ de \d+ preguntas hoy|no está disponible|Ya usaste las/),
    ).toBeVisible();
  });

  test("salir regresa a la pantalla de entrada", async ({ page }) => {
    await entrarComo(page, "aprobador");
    const menu = page.getByRole("button", { name: "Menú" });
    if (await menu.isVisible()) await menu.click();
    await page.getByRole("button", { name: "Salir" }).click();
    await expect(page.getByRole("button", { name: "Entrar como aprobador" })).toBeVisible();
  });
});
