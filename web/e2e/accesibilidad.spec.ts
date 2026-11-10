import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { entrarComo, irA, VISTAS } from "./apoyo";

const ETIQUETAS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"];

test("la pantalla de entrada cumple WCAG 2.1 AA según axe", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("button", { name: "Entrar como capturista" })).toBeVisible();
  const resultado = await new AxeBuilder({ page }).withTags(ETIQUETAS).analyze();
  expect(resultado.violations).toEqual([]);
});

for (const vista of VISTAS) {
  test(`${vista.titulo} cumple WCAG 2.1 AA según axe, contraste incluido`, async ({ page }) => {
    await entrarComo(page, "capturista");
    await irA(page, vista.ruta);
    await expect(page.getByRole("heading", { name: vista.titulo, level: 1 })).toBeVisible();
    await expect(page.locator(".cargando")).toHaveCount(0);
    const resultado = await new AxeBuilder({ page }).withTags(ETIQUETAS).analyze();
    expect(resultado.violations).toEqual([]);
  });
}

test("el primer Tab lleva al enlace para saltar al contenido y el foco se ve", async ({ page }) => {
  await entrarComo(page, "capturista");
  await page.locator("body").focus();
  await page.keyboard.press("Tab");
  const enfocado = page.locator(":focus");
  await expect(enfocado).toHaveText("Saltar al contenido");
  const contorno = await enfocado.evaluate((el) => getComputedStyle(el).outlineStyle);
  expect(contorno).not.toBe("none");
});

test("la navegación principal se recorre con teclado", async ({ page }) => {
  await entrarComo(page, "capturista");
  const menu = page.getByRole("button", { name: "Menú" });
  if (await menu.isVisible()) {
    await menu.focus();
    await page.keyboard.press("Enter");
  }
  const enlace = page
    .getByRole("navigation", { name: "Secciones" })
    .getByRole("link", { name: "Facturas" });
  await enlace.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("heading", { name: "Facturas", level: 1 })).toBeVisible();
  await expect(page.locator("#principal")).toBeFocused();
});
