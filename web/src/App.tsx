import { QueryCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import { Link, Route, Routes } from "react-router";
import type { ClienteApi } from "./api/cliente";
import { useSesion } from "./api/consultas";
import { ProveedorCliente, ProveedorUsuario } from "./api/contexto";
import { Cargando, EstadoError, EstadoVacio } from "./componentes/Estados";
import { Marco } from "./componentes/Marco";
import { Vista } from "./componentes/Vista";
import { Asistente } from "./vistas/Asistente";
import { Bitacora } from "./vistas/Bitacora";
import { CargarCfdi } from "./vistas/CargarCfdi";
import { Documentos } from "./vistas/Documentos";
import { Entrar } from "./vistas/Entrar";
import { FacturaDetalle } from "./vistas/FacturaDetalle";
import { Facturas } from "./vistas/Facturas";
import { PropuestaDetalle, Propuestas } from "./vistas/Propuestas";
import { ProveedorDetalle, Proveedores } from "./vistas/Proveedores";
import { Tablero } from "./vistas/Tablero";

export function crearClienteConsultas(): QueryClient {
  const consultas: QueryClient = new QueryClient({
    // Si la sesión vence a media tarea, cualquier 401 devuelve a la pantalla de entrada.
    queryCache: new QueryCache({
      onError: (error, consulta) => {
        if (error.estado === 401 && consulta.queryKey[0] !== "sesion") {
          void consultas.resetQueries({ queryKey: ["sesion"] });
        }
      },
    }),
    defaultOptions: {
      queries: {
        // Un 4xx no se arregla reintentando; solo se reintenta una vez ante fallas de red o 5xx.
        retry: (intentos, error) =>
          intentos < 1 && (error.estado === 0 || error.estado >= 500) && error.estado !== 503,
        refetchOnWindowFocus: false,
        staleTime: 15_000,
      },
    },
  });
  return consultas;
}

function NoEncontrada() {
  return (
    <Vista titulo="Página no encontrada">
      <EstadoVacio
        titulo="Esta dirección no existe en Cotejo"
        accion={
          <Link className="boton" to="/">
            Ir al tablero
          </Link>
        }
      >
        Revisa el enlace o vuelve al tablero.
      </EstadoVacio>
    </Vista>
  );
}

function Rutas() {
  return (
    <Routes>
      <Route path="/" element={<Tablero />} />
      <Route path="/facturas" element={<Facturas />} />
      <Route path="/facturas/cargar" element={<CargarCfdi />} />
      <Route path="/facturas/:id" element={<FacturaDetalle />} />
      <Route path="/proveedores" element={<Proveedores />} />
      <Route path="/proveedores/:id" element={<ProveedorDetalle />} />
      <Route path="/documentos" element={<Documentos />} />
      <Route path="/propuestas" element={<Propuestas />} />
      <Route path="/propuestas/:id" element={<PropuestaDetalle />} />
      <Route path="/asistente" element={<Asistente />} />
      <Route path="/bitacora" element={<Bitacora />} />
      <Route path="*" element={<NoEncontrada />} />
    </Routes>
  );
}

/** Decide entre la pantalla de entrada y la aplicación según la sesión. */
function ConSesion() {
  const sesion = useSesion();
  if (sesion.isPending) {
    return (
      <main className="entrar">
        <Cargando texto="Abriendo Cotejo" />
      </main>
    );
  }
  if (sesion.isError) {
    if (sesion.error.estado === 401) return <Entrar />;
    return (
      <main className="entrar">
        <div className="entrar-caja">
          <EstadoError
            titulo="No pudimos conectar con Cotejo"
            error={sesion.error}
            reintentar={() => void sesion.refetch()}
          />
        </div>
      </main>
    );
  }
  if (!sesion.data) return <Entrar />;
  return (
    <ProveedorUsuario usuario={sesion.data}>
      <Marco>
        <Rutas />
      </Marco>
    </ProveedorUsuario>
  );
}

export function App({ cliente }: { cliente: ClienteApi }) {
  const [consultas] = useState(crearClienteConsultas);
  return (
    <QueryClientProvider client={consultas}>
      <ProveedorCliente cliente={cliente}>
        <ConSesion />
      </ProveedorCliente>
    </QueryClientProvider>
  );
}
