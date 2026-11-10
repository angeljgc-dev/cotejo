import { createContext, type ReactNode, useContext } from "react";
import type { ClienteApi } from "./cliente";
import type { Usuario } from "./tipos";

const ContextoCliente = createContext<ClienteApi | null>(null);
const ContextoUsuario = createContext<Usuario | null>(null);

export function ProveedorCliente({
  cliente,
  children,
}: {
  cliente: ClienteApi;
  children: ReactNode;
}) {
  return <ContextoCliente.Provider value={cliente}>{children}</ContextoCliente.Provider>;
}

export function useCliente(): ClienteApi {
  const cliente = useContext(ContextoCliente);
  if (!cliente) throw new Error("useCliente necesita un ProveedorCliente arriba en el árbol.");
  return cliente;
}

export function ProveedorUsuario({ usuario, children }: { usuario: Usuario; children: ReactNode }) {
  return <ContextoUsuario.Provider value={usuario}>{children}</ContextoUsuario.Provider>;
}

/** Usuario con sesión. Solo existe dentro del marco de la aplicación, después de Entrar. */
export function useUsuario(): Usuario {
  const usuario = useContext(ContextoUsuario);
  if (!usuario) throw new Error("useUsuario se usó fuera de una sesión iniciada.");
  return usuario;
}
