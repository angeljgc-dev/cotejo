import { describe, expect, it } from "vitest";
import { crearClienteHttp, ErrorApi } from "./cliente";

interface Llamada {
  url: string;
  init: RequestInit;
}

function fetchGrabado(respuesta: () => Response) {
  const llamadas: Llamada[] = [];
  const fn: typeof fetch = async (entrada, init) => {
    llamadas.push({ url: String(entrada), init: init ?? {} });
    return respuesta();
  };
  return { fn, llamadas };
}

function json(estado: number, cuerpo: unknown): Response {
  return new Response(JSON.stringify(cuerpo), {
    status: estado,
    headers: { "Content-Type": "application/json" },
  });
}

describe("crearClienteHttp", () => {
  it("manda la cabecera X-Cotejo solo en métodos que modifican", async () => {
    const { fn, llamadas } = fetchGrabado(() => json(200, { id: 1 }));
    const api = crearClienteHttp("/api", fn);
    await api.tablero();
    await api.aprobarPropuesta(7);
    const [get, post] = llamadas;
    expect(new Headers(get?.init.headers).get("X-Cotejo")).toBeNull();
    expect(new Headers(post?.init.headers).get("X-Cotejo")).toBe("1");
    expect(post?.url).toBe("/api/propuestas/7/aprobar");
    expect(post?.init.method).toBe("POST");
    expect(post?.init.credentials).toBe("same-origin");
  });

  it("arma la cadena de consulta sin parámetros vacíos", async () => {
    const { fn, llamadas } = fetchGrabado(() =>
      json(200, { elementos: [], total: 0, pagina: 1, por_pagina: 25 }),
    );
    const api = crearClienteHttp("/api", fn);
    await api.facturas({ estado: "vencida", texto: "", con_alertas: true, pagina: 2 });
    expect(llamadas[0]?.url).toBe("/api/facturas?estado=vencida&con_alertas=true&pagina=2");
  });

  it("convierte el formato de error de la API en ErrorApi", async () => {
    const { fn } = fetchGrabado(() =>
      json(403, {
        error: {
          codigo: "ROL_INSUFICIENTE",
          mensaje: "Esta acción es solo para el rol aprobador.",
          detalle: {},
        },
      }),
    );
    const api = crearClienteHttp("/api", fn);
    const error = await api.aprobarPropuesta(1).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ErrorApi);
    expect((error as ErrorApi).codigo).toBe("ROL_INSUFICIENTE");
    expect((error as ErrorApi).estado).toBe(403);
    expect((error as ErrorApi).message).toBe("Esta acción es solo para el rol aprobador.");
  });

  it("explica la falta de conexión cuando fetch falla", async () => {
    const fn: typeof fetch = async () => {
      throw new TypeError("Failed to fetch");
    };
    const error = await crearClienteHttp("/api", fn)
      .tablero()
      .catch((e: unknown) => e);
    expect((error as ErrorApi).codigo).toBe("SIN_CONEXION");
    expect((error as ErrorApi).message).toMatch(/No hay conexión/);
  });

  it("da un mensaje útil si el error no trae el formato esperado", async () => {
    const { fn } = fetchGrabado(() => new Response("<html>502</html>", { status: 502 }));
    const error = await crearClienteHttp("/api", fn)
      .tablero()
      .catch((e: unknown) => e);
    expect((error as ErrorApi).estado).toBe(502);
    expect((error as ErrorApi).message).toMatch(/502/);
  });

  it("envía los CFDI como multipart con el campo archivos", async () => {
    const { fn, llamadas } = fetchGrabado(() =>
      json(200, {
        carga_id: 1,
        archivos: [],
        resumen: { aceptadas: 0, con_alertas: 0, rechazadas: 0, duplicadas: 0 },
      }),
    );
    const a = new File(["<x/>"], "a.xml", { type: "application/xml" });
    const b = new File(["<y/>"], "b.xml", { type: "application/xml" });
    await crearClienteHttp("/api", fn).cargarCfdi([a, b]);
    const cuerpo = llamadas[0]?.init.body;
    expect(cuerpo).toBeInstanceOf(FormData);
    expect((cuerpo as FormData).getAll("archivos")).toHaveLength(2);
    expect(new Headers(llamadas[0]?.init.headers).get("Content-Type")).toBeNull();
  });
});
