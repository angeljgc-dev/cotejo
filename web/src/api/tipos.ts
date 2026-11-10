// Espejo del contrato de la API. Todo importe viaja como texto decimal exacto ("1160.00");
// la interfaz solo lo formatea, nunca lo convierte a número.

export type Importe = string;
/** Fecha ISO sin hora: "2026-11-09". */
export type Fecha = string;
/** Fecha y hora ISO 8601 con zona: "2026-11-09T10:15:00-06:00". */
export type FechaHora = string;

export type Rol = "capturista" | "aprobador";

export interface ErrorRespuesta {
  error: {
    codigo: string;
    mensaje: string;
    detalle: Record<string, unknown> | unknown[];
  };
}

export interface Pagina<T> {
  elementos: T[];
  total: number;
  pagina: number;
  por_pagina: number;
}

export interface UsuarioCorto {
  id: number;
  nombre: string;
  rol: Rol;
}

export interface ProveedorCorto {
  id: number;
  rfc: string;
  nombre: string;
}

export type SeveridadAlerta = "alerta" | "bloqueante";

export interface Alerta {
  id: number;
  factura_id: number | null;
  proveedor_id: number | null;
  codigo: string;
  severidad: SeveridadAlerta;
  mensaje: string;
  detalle: Record<string, unknown>;
  factura_relacionada_id: number | null;
  estado: "abierta" | "resuelta";
  creada_en: FechaHora;
  resuelta_por: UsuarioCorto | null;
  resuelta_en: FechaHora | null;
  nota_resolucion: string | null;
}

export interface Motivo {
  codigo: string;
  mensaje: string;
  severidad: "rechazo" | "alerta" | "bloqueante";
}

// Sesión y salud

export interface Salud {
  estado: "ok";
  base: "ok" | "error";
  version: string;
  modo_demo: boolean;
  asistente_configurado: boolean;
}

export interface Usuario {
  id: number;
  usuario: string;
  nombre: string;
  rol: Rol;
  es_demo: boolean;
}

export interface Configuracion {
  empresa_rfc: string;
  empresa_nombre: string;
  modo_demo: boolean;
  aviso_demo: string | null;
  hoy: Fecha;
  zona_horaria: string;
  limites: {
    chat_por_dia: number;
    archivos_por_carga: number;
    mb_por_xml: number;
    mb_por_documento: number;
  };
}

export interface DemoReiniciada {
  reiniciada_en: FechaHora;
  facturas: number;
  documentos: number;
}

// Cargas de CFDI

export type ResultadoArchivoCfdi = "aceptada" | "aceptada_con_alertas" | "rechazada" | "duplicada";
export type TipoComprobante = "I" | "E" | "P";

export interface ArchivoCargado {
  nombre: string;
  resultado: ResultadoArchivoCfdi;
  motivos: Motivo[];
  uuid: string | null;
  factura_id: number | null;
  tipo: TipoComprobante | null;
  ya_existia: boolean;
}

export interface ResultadoCarga {
  carga_id: number;
  archivos: ArchivoCargado[];
  resumen: {
    aceptadas: number;
    con_alertas: number;
    rechazadas: number;
    duplicadas: number;
  };
}

// Facturas

export type EstadoPago = "pendiente" | "parcial" | "pagada" | "no_aplica";
export type FiltroEstadoFactura = "pendiente" | "vencida" | "por_vencer" | "pagada" | "todas";
export type OrdenFacturas = "vencimiento" | "fecha" | "saldo" | "total";

export interface FiltrosFacturas {
  proveedor_id?: number;
  tipo?: TipoComprobante;
  estado?: FiltroEstadoFactura;
  con_alertas?: boolean;
  severidad?: SeveridadAlerta;
  moneda?: string;
  desde?: Fecha;
  hasta?: Fecha;
  vence_desde?: Fecha;
  vence_hasta?: Fecha;
  texto?: string;
  orden?: OrdenFacturas;
  pagina?: number;
  por_pagina?: number;
}

export interface FacturaResumen {
  id: number;
  uuid: string;
  tipo: TipoComprobante;
  serie: string | null;
  folio: string | null;
  fecha_emision: Fecha;
  proveedor: ProveedorCorto;
  moneda: string;
  tipo_cambio: Importe | null;
  total: Importe;
  total_mxn: Importe;
  saldo: Importe | null;
  saldo_mxn: Importe | null;
  vencimiento: Fecha | null;
  /** Negativo significa que faltan días para el vencimiento. */
  dias_vencido: number | null;
  estado_pago: EstadoPago;
  resultado: "aceptada" | "aceptada_con_alertas";
  alertas_abiertas: number;
  tiene_bloqueante: boolean;
  en_propuesta_pendiente: number | null;
}

export interface Concepto {
  orden: number;
  clave_prod_serv: string;
  cantidad: string;
  clave_unidad: string;
  unidad: string | null;
  descripcion: string;
  valor_unitario: Importe;
  importe: Importe;
  descuento: Importe | null;
}

export interface ImpuestoFactura {
  clase: string;
  impuesto: string;
  tipo_factor: string;
  tasa_o_cuota: string | null;
  base: Importe;
  importe: Importe | null;
}

export interface Relacionado {
  uuid: string;
  tipo_relacion: string;
  factura_id: number | null;
}

export interface Aplicacion {
  id: number;
  origen: string;
  importe: Importe;
  importe_solicitado: Importe;
  fecha: Fecha;
  origen_factura_id: number | null;
  propuesta_id: number | null;
  num_parcialidad: number | null;
}

export interface FacturaDetalle extends FacturaResumen {
  version: string;
  fecha_timbrado: FechaHora;
  receptor: { rfc: string; nombre: string; uso_cfdi: string };
  subtotal: Importe;
  descuento: Importe | null;
  total_impuestos_trasladados: Importe | null;
  total_impuestos_retenidos: Importe | null;
  impuestos_locales_trasladados: Importe | null;
  impuestos_locales_retenidos: Importe | null;
  metodo_pago: string | null;
  forma_pago: string | null;
  condiciones_pago: string | null;
  exportacion: string | null;
  lugar_expedicion: string;
  conceptos: Concepto[];
  impuestos: ImpuestoFactura[];
  relacionados: Relacionado[];
  aplicaciones: Aplicacion[];
  alertas: Alerta[];
  carga: { id: number; creado_en: FechaHora; usuario: UsuarioCorto };
}

// Proveedores

export interface ProveedorResumen {
  id: number;
  rfc: string;
  nombre: string;
  dias_credito: number;
  rfc_valido: boolean;
  situacion_69b: "Presunto" | "Definitivo" | null;
  adeudo_mxn: Importe;
  facturas_con_saldo: number;
}

export interface SaldoPorMoneda {
  moneda: string;
  saldo: Importe;
  saldo_mxn: Importe;
}

export interface ProveedorDetalle extends ProveedorResumen {
  adeudo_por_moneda: SaldoPorMoneda[];
  documentos: { id: number; nombre: string; tipo: string; estado: EstadoDocumento }[];
}

// Tablero

export type GrupoAntiguedad = "por_vencer" | "1_30" | "31_60" | "61_90" | "mas_90";

export interface Tablero {
  fecha_corte: Fecha;
  adeudo_total_mxn: Importe;
  adeudo_por_moneda: SaldoPorMoneda[];
  por_proveedor: { proveedor: ProveedorCorto; saldo_mxn: Importe; facturas: number }[];
  otros_proveedores: { saldo_mxn: Importe; proveedores: number };
  antiguedad: { grupo: GrupoAntiguedad; etiqueta: string; saldo_mxn: Importe; facturas: number }[];
  vencen_7_dias: { saldo_mxn: Importe; facturas: number };
  vencen_30_dias: { saldo_mxn: Importe; facturas: number };
  facturas_con_alertas: number;
  facturas_bloqueadas: number;
  propuestas_pendientes: number;
}

// Bitácora

export type AccionBitacora =
  | "SESION_INICIADA"
  | "CARGA_CFDI"
  | "CARGA_DOCUMENTO"
  | "LISTA_69B_CARGADA"
  | "PROVEEDOR_EDITADO"
  | "ALERTA_RESUELTA"
  | "PROPUESTA_CREADA"
  | "PROPUESTA_APROBADA"
  | "PROPUESTA_RECHAZADA"
  | "PAGO_REGISTRADO"
  | "DEMO_REINICIADA";

export interface EntradaBitacora {
  id: number;
  ocurrido_en: FechaHora;
  usuario: UsuarioCorto | null;
  accion: AccionBitacora;
  entidad: string;
  entidad_id: number | string | null;
  detalle: Record<string, unknown>;
}

export interface FiltrosBitacora {
  accion?: AccionBitacora;
  usuario_id?: number;
  entidad?: string;
  entidad_id?: number;
  desde?: Fecha;
  hasta?: Fecha;
  pagina?: number;
  por_pagina?: number;
}

// Documentos y búsqueda

export type EstadoDocumento = "indexado" | "sin_texto";

export interface ResultadoDocumento {
  nombre: string;
  resultado: "indexado" | "sin_texto" | "rechazado" | "duplicado";
  documento_id: number | null;
  paginas: number | null;
  fragmentos: number | null;
  explicacion: string | null;
  motivos: Motivo[];
}

export interface DocumentoResumen {
  id: number;
  nombre: string;
  tipo: string;
  proveedor: ProveedorCorto | null;
  paginas: number | null;
  fragmentos: number | null;
  estado: EstadoDocumento;
  explicacion: string | null;
  subido_por: UsuarioCorto;
  creado_en: FechaHora;
}

export interface Fragmento {
  id: number;
  documento: { id: number; nombre: string };
  pagina: number;
  orden: number;
  texto: string;
  anterior_id: number | null;
  siguiente_id: number | null;
}

// Asistente

export interface EstadoAsistente {
  disponible: boolean;
  motivo: string | null;
  modelo: string | null;
  restantes_hoy: number;
  limite_dia: number;
}

export interface HerramientaUsada {
  nombre: string;
  argumentos: Record<string, unknown>;
  resumen: string;
  duracion_ms: number;
  error: string | null;
}

export interface FacturaBase {
  id: number;
  uuid: string;
  serie: string | null;
  folio: string | null;
  proveedor: ProveedorCorto;
  moneda: string;
  saldo: Importe | null;
}

export interface Cita {
  fragmento_id: number;
  documento_id: number;
  documento: string;
  pagina: number;
}

export interface MensajeChat {
  id: number;
  conversacion_id: string;
  rol: "asistente";
  texto: string;
  creado_en: FechaHora;
  herramientas: HerramientaUsada[];
  facturas_base: FacturaBase[];
  citas: Cita[];
  propuesta_id: number | null;
  advertencias: {
    codigo: "CIFRA_NO_RESPALDADA" | "CITA_INVALIDA" | "LIMITE_PASOS";
    mensaje: string;
  }[];
  modelo: string;
}

// Propuestas

export type EstadoPropuesta = "pendiente" | "aprobada" | "rechazada";
export type Horizonte = "vencidas" | "esta_semana" | "proximos_7_dias" | "proximos_30_dias";

export interface NuevaPropuesta {
  presupuesto_mxn: Importe;
  horizonte: Horizonte | null;
  fecha_limite: Fecha | null;
  factura_ids: number[] | null;
}

export interface PropuestaResumen {
  id: number;
  estado: EstadoPropuesta;
  presupuesto_mxn: Importe;
  total_mxn: Importe;
  renglones: number;
  creada_por: UsuarioCorto;
  creado_en: FechaHora;
  decidida_por: UsuarioCorto | null;
}

export interface RenglonPropuesta {
  id: number;
  factura: {
    id: number;
    uuid: string;
    serie: string | null;
    folio: string | null;
    proveedor: ProveedorCorto;
    moneda: string;
    vencimiento: Fecha | null;
    saldo_actual: Importe;
  };
  importe: Importe;
  importe_mxn: Importe;
  razon: string;
}

export interface Propuesta {
  id: number;
  estado: EstadoPropuesta;
  presupuesto_mxn: Importe;
  total_mxn: Importe;
  fecha_limite: Fecha | null;
  origen: string;
  creada_por: UsuarioCorto;
  creado_en: FechaHora;
  renglones: RenglonPropuesta[];
  excluidas: { factura_id: number; codigo: string; motivo: string }[];
  decidida_por: UsuarioCorto | null;
  decidida_en: FechaHora | null;
  motivo_rechazo: string | null;
  /** Verdadero si el usuario actual es aprobador y no creó la propuesta. */
  puede_decidir: boolean;
}
