import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { ErrorApi } from "./cliente";
import { useCliente } from "./contexto";
import type {
  EstadoPropuesta,
  FiltrosBitacora,
  FiltrosFacturas,
  NuevaPropuesta,
  Rol,
} from "./tipos";

// Claves de caché agrupadas por entidad para invalidar todo lo relacionado tras una mutación.
export const claves = {
  sesion: ["sesion"] as const,
  configuracion: ["configuracion"] as const,
  tablero: ["tablero"] as const,
  facturas: (f: FiltrosFacturas) => ["facturas", f] as const,
  factura: (id: number) => ["facturas", "detalle", id] as const,
  proveedores: (p: object) => ["proveedores", p] as const,
  proveedor: (id: number) => ["proveedores", "detalle", id] as const,
  documentos: (p: object) => ["documentos", p] as const,
  fragmento: (id: number) => ["fragmentos", id] as const,
  asistente: ["asistente", "estado"] as const,
  propuestas: (p: object) => ["propuestas", p] as const,
  propuesta: (id: number) => ["propuestas", "detalle", id] as const,
  bitacora: (f: FiltrosBitacora) => ["bitacora", f] as const,
};

/** Borra la caché de todo menos la sesión, para que otro usuario no vea datos del anterior. */
function olvidarDatos(qc: ReturnType<typeof useQueryClient>) {
  qc.removeQueries({ predicate: (q) => q.queryKey[0] !== "sesion" });
}

export function useSesion() {
  const api = useCliente();
  return useQuery<Awaited<ReturnType<typeof api.sesion>>, ErrorApi>({
    queryKey: claves.sesion,
    queryFn: () => api.sesion(),
    retry: false,
    staleTime: 60_000,
  });
}

export function useConfiguracion() {
  const api = useCliente();
  return useQuery({
    queryKey: claves.configuracion,
    queryFn: () => api.configuracion(),
    staleTime: 5 * 60_000,
  });
}

export function useEntrarDemo() {
  const api = useCliente();
  const qc = useQueryClient();
  return useMutation<Awaited<ReturnType<typeof api.entrarDemo>>, ErrorApi, Rol>({
    mutationFn: (rol) => api.entrarDemo(rol),
    onSuccess: (usuario) => {
      olvidarDatos(qc);
      qc.setQueryData(claves.sesion, usuario);
    },
  });
}

export function useEntrar() {
  const api = useCliente();
  const qc = useQueryClient();
  return useMutation<
    Awaited<ReturnType<typeof api.entrar>>,
    ErrorApi,
    { usuario: string; contrasena: string }
  >({
    mutationFn: ({ usuario, contrasena }) => api.entrar(usuario, contrasena),
    onSuccess: (usuario) => {
      olvidarDatos(qc);
      qc.setQueryData(claves.sesion, usuario);
    },
  });
}

export function useSalir() {
  const api = useCliente();
  const qc = useQueryClient();
  return useMutation<void, ErrorApi>({
    mutationFn: () => api.salir(),
    onSettled: () => {
      olvidarDatos(qc);
      void qc.resetQueries({ queryKey: claves.sesion });
    },
  });
}

export function useReiniciarDemo() {
  const api = useCliente();
  const qc = useQueryClient();
  return useMutation<Awaited<ReturnType<typeof api.reiniciarDemo>>, ErrorApi>({
    mutationFn: () => api.reiniciarDemo(),
    onSuccess: () => {
      void qc.invalidateQueries({ predicate: (q) => q.queryKey[0] !== "sesion" });
    },
  });
}

export function useTablero() {
  const api = useCliente();
  return useQuery({ queryKey: claves.tablero, queryFn: () => api.tablero() });
}

export function useFacturas(filtros: FiltrosFacturas) {
  const api = useCliente();
  return useQuery({
    queryKey: claves.facturas(filtros),
    queryFn: () => api.facturas(filtros),
    placeholderData: keepPreviousData,
  });
}

export function useFactura(id: number) {
  const api = useCliente();
  return useQuery({ queryKey: claves.factura(id), queryFn: () => api.factura(id) });
}

function invalidarCuentas(qc: ReturnType<typeof useQueryClient>) {
  for (const raiz of ["facturas", "tablero", "proveedores", "propuestas", "bitacora"]) {
    void qc.invalidateQueries({ queryKey: [raiz] });
  }
}

export function useCargarCfdi() {
  const api = useCliente();
  const qc = useQueryClient();
  return useMutation<Awaited<ReturnType<typeof api.cargarCfdi>>, ErrorApi, File[]>({
    mutationFn: (archivos) => api.cargarCfdi(archivos),
    onSuccess: () => invalidarCuentas(qc),
  });
}

export function useResolverAlerta() {
  const api = useCliente();
  const qc = useQueryClient();
  return useMutation<
    Awaited<ReturnType<typeof api.resolverAlerta>>,
    ErrorApi,
    { id: number; nota: string }
  >({
    mutationFn: ({ id, nota }) => api.resolverAlerta(id, nota),
    onSuccess: () => invalidarCuentas(qc),
  });
}

export function useProveedores(params: { texto?: string; pagina?: number }) {
  const api = useCliente();
  return useQuery({
    queryKey: claves.proveedores(params),
    queryFn: () => api.proveedores({ ...params, por_pagina: 25 }),
    placeholderData: keepPreviousData,
  });
}

/** Lista completa para un selector (hasta 100, el máximo que admite la API). */
export function useProveedoresParaSelector() {
  const api = useCliente();
  return useQuery({
    queryKey: claves.proveedores({ selector: true }),
    queryFn: () => api.proveedores({ por_pagina: 100 }),
  });
}

export function useProveedor(id: number) {
  const api = useCliente();
  return useQuery({ queryKey: claves.proveedor(id), queryFn: () => api.proveedor(id) });
}

export function useEditarProveedor(id: number) {
  const api = useCliente();
  const qc = useQueryClient();
  return useMutation<Awaited<ReturnType<typeof api.editarProveedor>>, ErrorApi, number>({
    mutationFn: (dias) => api.editarProveedor(id, { dias_credito: dias }),
    onSuccess: () => invalidarCuentas(qc),
  });
}

export function useDocumentos(params: { pagina?: number }) {
  const api = useCliente();
  return useQuery({
    queryKey: claves.documentos(params),
    queryFn: () => api.documentos({ ...params, por_pagina: 25 }),
  });
}

export function useSubirDocumentos() {
  const api = useCliente();
  const qc = useQueryClient();
  return useMutation<
    Awaited<ReturnType<typeof api.subirDocumentos>>,
    ErrorApi,
    { archivos: File[]; proveedorId: number | null }
  >({
    mutationFn: ({ archivos, proveedorId }) => api.subirDocumentos(archivos, proveedorId),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["documentos"] });
      void qc.invalidateQueries({ queryKey: ["bitacora"] });
    },
  });
}

export function useFragmento(id: number | null) {
  const api = useCliente();
  return useQuery({
    queryKey: claves.fragmento(id ?? 0),
    queryFn: () => api.fragmento(id ?? 0),
    enabled: id !== null,
    staleTime: Number.POSITIVE_INFINITY,
  });
}

export function useEstadoAsistente() {
  const api = useCliente();
  return useQuery({ queryKey: claves.asistente, queryFn: () => api.estadoAsistente() });
}

export function useEnviarMensaje() {
  const api = useCliente();
  const qc = useQueryClient();
  return useMutation<
    Awaited<ReturnType<typeof api.enviarMensaje>>,
    ErrorApi,
    { conversacionId: string | null; texto: string }
  >({
    mutationFn: ({ conversacionId, texto }) => api.enviarMensaje(conversacionId, texto),
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: claves.asistente });
    },
    onSuccess: (mensaje) => {
      if (mensaje.propuesta_id !== null) {
        void qc.invalidateQueries({ queryKey: ["propuestas"] });
        void qc.invalidateQueries({ queryKey: ["tablero"] });
      }
    },
  });
}

export function usePropuestas(params: { estado?: EstadoPropuesta; pagina?: number }) {
  const api = useCliente();
  return useQuery({
    queryKey: claves.propuestas(params),
    queryFn: () => api.propuestas({ ...params, por_pagina: 25 }),
    placeholderData: keepPreviousData,
  });
}

export function usePropuesta(id: number) {
  const api = useCliente();
  return useQuery({ queryKey: claves.propuesta(id), queryFn: () => api.propuesta(id) });
}

export function useCrearPropuesta() {
  const api = useCliente();
  const qc = useQueryClient();
  return useMutation<Awaited<ReturnType<typeof api.crearPropuesta>>, ErrorApi, NuevaPropuesta>({
    mutationFn: (datos) => api.crearPropuesta(datos),
    onSuccess: () => invalidarCuentas(qc),
  });
}

export function useDecidirPropuesta(id: number) {
  const api = useCliente();
  const qc = useQueryClient();
  return useMutation<
    Awaited<ReturnType<typeof api.aprobarPropuesta>>,
    ErrorApi,
    { accion: "aprobar" } | { accion: "rechazar"; motivo: string }
  >({
    mutationFn: (d) =>
      d.accion === "aprobar" ? api.aprobarPropuesta(id) : api.rechazarPropuesta(id, d.motivo),
    onSuccess: (propuesta) => {
      qc.setQueryData(claves.propuesta(id), propuesta);
      invalidarCuentas(qc);
    },
  });
}

export function useBitacora(filtros: FiltrosBitacora) {
  const api = useCliente();
  return useQuery({
    queryKey: claves.bitacora(filtros),
    queryFn: () => api.bitacora(filtros),
    placeholderData: keepPreviousData,
  });
}

// Todas las consultas y mutaciones fallan con ErrorApi (el cliente convierte cualquier otro error).
declare module "@tanstack/react-query" {
  interface Register {
    defaultError: ErrorApi;
  }
}
