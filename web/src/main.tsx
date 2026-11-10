import "@fontsource-variable/instrument-sans/wdth.css";
import "./estilos/tokens.css";
import "./estilos/base.css";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router";
import { App } from "./App";
import { type ClienteApi, crearClienteHttp } from "./api/cliente";

async function elegirCliente(): Promise<ClienteApi> {
  // `vite --mode ejemplo` usa el backend simulado. La condición se resuelve al compilar, así que
  // el paquete de producción no incluye el módulo de ejemplo.
  if (import.meta.env.MODE === "ejemplo") {
    const { crearClienteEjemplo } = await import("./ejemplo/clienteEjemplo");
    return crearClienteEjemplo({ sesion: null, latencia: 250 });
  }
  return crearClienteHttp("/api");
}

const raiz = document.getElementById("raiz");
if (!raiz) throw new Error("Falta el elemento #raiz en index.html");

void elegirCliente().then((cliente) => {
  createRoot(raiz).render(
    <StrictMode>
      <BrowserRouter>
        <App cliente={cliente} />
      </BrowserRouter>
    </StrictMode>,
  );
});
