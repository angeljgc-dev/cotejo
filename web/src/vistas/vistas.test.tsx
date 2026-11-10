import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { type ClienteApi, ErrorApi } from "../api/cliente";
import { montar, violacionesAxe } from "../pruebas/utilidades";

interface CasoVista {
  vista: string;
  ruta: string;
  cargando: string;
  metodo: keyof ClienteApi;
  cargado: RegExp;
  vacio: RegExp | null;
  error: RegExp;
}

// Una fila por vista: qué se ve con datos, qué dice vacía y qué dice si la API falla (F2, F4).
const VISTAS: CasoVista[] = [
  {
    vista: "Tablero",
    cargando: "Calculando adeudos y vencimientos",
    ruta: "/",
    metodo: "tablero",
    cargado: /Antigüedad de saldos/,
    vacio: /No hay saldos por pagar/,
    error: /No pudimos calcular el tablero/,
  },
  {
    vista: "Facturas",
    cargando: "Cargando facturas",
    ruta: "/facturas",
    metodo: "facturas",
    cargado: /A-4410/,
    vacio: /Todavía no hay facturas/,
    error: /No pudimos cargar las facturas/,
  },
  {
    vista: "Detalle de factura",
    cargando: "Cargando la factura",
    ruta: "/facturas/114",
    metodo: "factura",
    cargado: /Posible duplicado/,
    vacio: null,
    error: /No pudimos abrir esta factura/,
  },
  {
    vista: "Proveedores",
    cargando: "Cargando proveedores",
    ruta: "/proveedores",
    metodo: "proveedores",
    cargado: /Servicios Logísticos Fantasma/,
    vacio: /Todavía no hay proveedores/,
    error: /No pudimos cargar los proveedores/,
  },
  {
    vista: "Detalle de proveedor",
    cargando: "Cargando el proveedor",
    ruta: "/proveedores/6",
    metodo: "proveedor",
    cargado: /Lista 69-B del SAT: Presunto/,
    vacio: null,
    error: /No pudimos abrir este proveedor/,
  },
  {
    vista: "Documentos",
    cargando: "Cargando documentos",
    ruta: "/documentos",
    metodo: "documentos",
    cargado: /Contrato de fletes firmado\.pdf/,
    vacio: /Todavía no hay documentos/,
    error: /No pudimos cargar los documentos/,
  },
  {
    vista: "Propuestas",
    cargando: "Cargando propuestas",
    ruta: "/propuestas",
    metodo: "propuestas",
    cargado: /Propuesta 3/,
    vacio: /Todavía no hay propuestas/,
    error: /No pudimos cargar las propuestas/,
  },
  {
    vista: "Detalle de propuesta",
    cargando: "Cargando la propuesta",
    ruta: "/propuestas/3",
    metodo: "propuesta",
    cargado: /Facturas que se dejaron fuera/,
    vacio: null,
    error: /No pudimos abrir esta propuesta/,
  },
  {
    vista: "Asistente",
    cargando: "Revisando si el asistente está disponible",
    ruta: "/asistente",
    metodo: "estadoAsistente",
    cargado: /Te quedan 17 de 20 preguntas hoy/,
    vacio: /Prueba con una de estas preguntas/,
    error: /No pudimos consultar el estado del asistente/,
  },
  {
    vista: "Bitácora",
    cargando: "Cargando la bitácora",
    ruta: "/bitacora",
    metodo: "bitacora",
    cargado: /Aprobó una propuesta/,
    vacio: /La bitácora está vacía/,
    error: /No pudimos cargar la bitácora/,
  },
];

const FALLA = new ErrorApi(
  500,
  "ERROR_INTERNO",
  "El servidor tuvo un problema al responder. Intenta de nuevo en unos minutos.",
);

describe.each(VISTAS)("vista $vista", (caso) => {
  it("muestra un estado de carga y luego los datos", async () => {
    montar(caso.ruta, { latencia: 20 });
    expect(await screen.findByText(caso.cargando)).toBeInTheDocument();
    expect((await screen.findAllByText(caso.cargado)).length).toBeGreaterThan(0);
  });

  it("explica el error con el mensaje de la API y ofrece reintentar o volver", async () => {
    montar(caso.ruta, { fallas: { [caso.metodo]: FALLA } });
    // Un 500 se reintenta una vez antes de mostrarse, por eso la espera es mayor.
    const alerta = await screen.findByRole("alert", {}, { timeout: 4000 });
    expect(alerta).toHaveTextContent(caso.error);
    expect(alerta).toHaveTextContent(/Intenta de nuevo en unos minutos/);
  });

  if (caso.vacio) {
    const vacio = caso.vacio;
    it("tiene un estado vacío que dice qué hacer", async () => {
      montar(caso.ruta, { vacio: true });
      expect((await screen.findAllByText(vacio)).length).toBeGreaterThan(0);
    });
  }

  it("no tiene violaciones de axe con datos", async () => {
    montar(caso.ruta);
    await screen.findAllByText(caso.cargado);
    expect(await violacionesAxe()).toEqual([]);
  });
});

describe("pantalla de carga de CFDI", () => {
  it("no tiene violaciones de axe", async () => {
    montar("/facturas/cargar");
    await screen.findByRole("heading", { name: "Cargar CFDI" });
    expect(await violacionesAxe()).toEqual([]);
  });
});
