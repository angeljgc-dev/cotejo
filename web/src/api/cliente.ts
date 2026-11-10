import type {
  Alerta,
  Configuracion,
  DemoReiniciada,
  DocumentoResumen,
  EntradaBitacora,
  ErrorRespuesta,
  EstadoAsistente,
  EstadoPropuesta,
  FacturaDetalle,
  FacturaResumen,
  FiltrosBitacora,
  FiltrosFacturas,
  Fragmento,
  MensajeChat,
  NuevaPropuesta,
  Pagina,
  Propuesta,
  PropuestaResumen,
  ProveedorDetalle,
  ProveedorResumen,
  ResultadoCarga,
  ResultadoDocumento,
  Rol,
  Tablero,
  Usuario,
} from "./tipos";

/** Error de la API con el formato `{"error": {codigo, mensaje, detalle}}`. */
export class ErrorApi extends Error {
  readonly estado: number;
  readonly codigo: string;
  /** Casi siempre un objeto; en RENGLONES_INVALIDOS el contrato lo describe como lista. */
  readonly detalle: Record<string, unknown> | unknown[];

  constructor(
    estado: number,
    codigo: string,
    mensaje: string,
    detalle: Record<string, unknown> | unknown[] = {},
  ) {
    super(mensaje);
    this.name = "ErrorApi";
    this.estado = estado;
    this.codigo = codigo;
    this.detalle = detalle;
  }
}

export interface PaginaParams {
  pagina?: number;
  por_pagina?: number;
}

/**
 * Todo lo que la interfaz sabe hacer con el backend. La implementación real usa fetch; las
 * pruebas y el modo de ejemplo inyectan otra con los mismos tipos.
 */
export interface ClienteApi {
  sesion(): Promise<Usuario>;
  entrarDemo(rol: Rol): Promise<Usuario>;
  entrar(usuario: string, contrasena: string): Promise<Usuario>;
  salir(): Promise<void>;
  configuracion(): Promise<Configuracion>;
  reiniciarDemo(): Promise<DemoReiniciada>;

  tablero(): Promise<Tablero>;
  facturas(filtros: FiltrosFacturas): Promise<Pagina<FacturaResumen>>;
  factura(id: number): Promise<FacturaDetalle>;
  cargarCfdi(archivos: File[]): Promise<ResultadoCarga>;
  resolverAlerta(id: number, nota: string): Promise<Alerta>;

  proveedores(params: { texto?: string } & PaginaParams): Promise<Pagina<ProveedorResumen>>;
  proveedor(id: number): Promise<ProveedorDetalle>;
  editarProveedor(id: number, cambios: { dias_credito: number }): Promise<ProveedorResumen>;

  documentos(params: { proveedor_id?: number } & PaginaParams): Promise<Pagina<DocumentoResumen>>;
  subirDocumentos(archivos: File[], proveedorId: number | null): Promise<ResultadoDocumento[]>;
  fragmento(id: number): Promise<Fragmento>;

  estadoAsistente(): Promise<EstadoAsistente>;
  enviarMensaje(conversacionId: string | null, texto: string): Promise<MensajeChat>;

  propuestas(
    params: { estado?: EstadoPropuesta } & PaginaParams,
  ): Promise<Pagina<PropuestaResumen>>;
  propuesta(id: number): Promise<Propuesta>;
  crearPropuesta(datos: NuevaPropuesta): Promise<Propuesta>;
  aprobarPropuesta(id: number): Promise<Propuesta>;
  rechazarPropuesta(id: number, motivo: string): Promise<Propuesta>;

  bitacora(filtros: FiltrosBitacora): Promise<Pagina<EntradaBitacora>>;
}

type Parametros = Record<string, string | number | boolean | undefined | null>;

function consulta(params: Parametros): string {
  const qs = new URLSearchParams();
  for (const [clave, valor] of Object.entries(params)) {
    if (valor === undefined || valor === null || valor === "") continue;
    qs.set(clave, String(valor));
  }
  const texto = qs.toString();
  return texto ? `?${texto}` : "";
}

function esErrorRespuesta(valor: unknown): valor is ErrorRespuesta {
  if (typeof valor !== "object" || valor === null || !("error" in valor)) return false;
  const error = (valor as { error: unknown }).error;
  return (
    typeof error === "object" &&
    error !== null &&
    typeof (error as { codigo?: unknown }).codigo === "string" &&
    typeof (error as { mensaje?: unknown }).mensaje === "string"
  );
}

const MENSAJE_RED =
  "No hay conexión con el servidor de Cotejo. Revisa tu conexión a internet y vuelve a intentarlo.";

/**
 * Cliente real. Envía la cookie de sesión y, en todo método que modifica, la cabecera
 * `X-Cotejo: 1` que el backend exige contra CSRF.
 */
export function crearClienteHttp(base = "/api", fetchFn: typeof fetch = fetch): ClienteApi {
  async function pedir<T>(metodo: string, ruta: string, cuerpo?: unknown): Promise<T> {
    const cabeceras: Record<string, string> = { Accept: "application/json" };
    if (metodo !== "GET") cabeceras["X-Cotejo"] = "1";
    let body: BodyInit | undefined;
    if (cuerpo instanceof FormData) {
      body = cuerpo;
    } else if (cuerpo !== undefined) {
      cabeceras["Content-Type"] = "application/json";
      body = JSON.stringify(cuerpo);
    }

    let respuesta: Response;
    try {
      respuesta = await fetchFn(`${base}${ruta}`, {
        method: metodo,
        headers: cabeceras,
        credentials: "same-origin",
        body,
      });
    } catch (causa) {
      throw new ErrorApi(0, "SIN_CONEXION", MENSAJE_RED, { causa: String(causa) });
    }

    if (respuesta.status === 204) return undefined as T;
    const texto = await respuesta.text();
    let datos: unknown = null;
    if (texto) {
      try {
        datos = JSON.parse(texto);
      } catch {
        datos = null;
      }
    }
    if (!respuesta.ok) {
      if (esErrorRespuesta(datos)) {
        throw new ErrorApi(
          respuesta.status,
          datos.error.codigo,
          datos.error.mensaje,
          datos.error.detalle ?? {},
        );
      }
      throw new ErrorApi(
        respuesta.status,
        "ERROR_INTERNO",
        `El servidor respondió con un error (${respuesta.status}). Intenta de nuevo en unos minutos.`,
      );
    }
    return datos as T;
  }

  function archivos(campo: string, lista: File[], extra: Record<string, string> = {}): FormData {
    const datos = new FormData();
    for (const archivo of lista) datos.append(campo, archivo, archivo.name);
    for (const [clave, valor] of Object.entries(extra)) datos.append(clave, valor);
    return datos;
  }

  return {
    sesion: () => pedir("GET", "/sesion"),
    entrarDemo: (rol) => pedir("POST", "/sesion/demo", { rol }),
    entrar: (usuario, contrasena) => pedir("POST", "/sesion", { usuario, contrasena }),
    salir: () => pedir("DELETE", "/sesion"),
    configuracion: () => pedir("GET", "/configuracion"),
    reiniciarDemo: () => pedir("POST", "/demo/reiniciar", {}),

    tablero: () => pedir("GET", "/tablero"),
    facturas: (filtros) => pedir("GET", `/facturas${consulta({ ...filtros })}`),
    factura: (id) => pedir("GET", `/facturas/${id}`),
    cargarCfdi: (lista) => pedir("POST", "/cargas/cfdi", archivos("archivos", lista)),
    resolverAlerta: (id, nota) => pedir("POST", `/alertas/${id}/resolver`, { nota }),

    proveedores: (params) => pedir("GET", `/proveedores${consulta({ ...params })}`),
    proveedor: (id) => pedir("GET", `/proveedores/${id}`),
    editarProveedor: (id, cambios) => pedir("PATCH", `/proveedores/${id}`, cambios),

    documentos: (params) => pedir("GET", `/documentos${consulta({ ...params })}`),
    subirDocumentos: (lista, proveedorId) =>
      pedir(
        "POST",
        "/documentos",
        archivos(
          "archivos",
          lista,
          proveedorId === null ? {} : { proveedor_id: String(proveedorId) },
        ),
      ),
    fragmento: (id) => pedir("GET", `/fragmentos/${id}`),

    estadoAsistente: () => pedir("GET", "/asistente/estado"),
    enviarMensaje: (conversacion_id, texto) =>
      pedir("POST", "/asistente/mensajes", { conversacion_id, texto }),

    propuestas: (params) => pedir("GET", `/propuestas${consulta({ ...params })}`),
    propuesta: (id) => pedir("GET", `/propuestas/${id}`),
    crearPropuesta: (datos) => pedir("POST", "/propuestas", datos),
    aprobarPropuesta: (id) => pedir("POST", `/propuestas/${id}/aprobar`, {}),
    rechazarPropuesta: (id, motivo) => pedir("POST", `/propuestas/${id}/rechazar`, { motivo }),

    bitacora: (filtros) => pedir("GET", `/bitacora${consulta({ ...filtros })}`),
  };
}

/** URL directa para descargar el XML original (un enlace normal, con la cookie de sesión). */
export function urlXmlFactura(id: number, base = "/api"): string {
  return `${base}/facturas/${id}/xml`;
}
