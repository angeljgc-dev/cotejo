// Datos de ejemplo, todos ficticios, con la forma exacta del contrato de la API. Solo se usan en
// pruebas y en el modo `vite --mode ejemplo`; el paquete de producción no los incluye.

import type {
  Alerta,
  Concepto,
  DocumentoResumen,
  EntradaBitacora,
  FacturaDetalle,
  Fragmento,
  Propuesta,
  ProveedorResumen,
  Usuario,
  UsuarioCorto,
} from "../api/tipos";

export const HOY = "2026-11-09";

export const CAPTURISTA: Usuario = {
  id: 1,
  usuario: "demo.capturista",
  nombre: "Laura Méndez",
  rol: "capturista",
  es_demo: true,
};

export const APROBADOR: Usuario = {
  id: 2,
  usuario: "demo.aprobador",
  nombre: "Ricardo Salas",
  rol: "aprobador",
  es_demo: true,
};

export const corto = (u: Usuario): UsuarioCorto => ({ id: u.id, nombre: u.nombre, rol: u.rol });

type ProveedorBase = Omit<ProveedorResumen, "adeudo_mxn" | "facturas_con_saldo">;

export const PROVEEDORES: ProveedorBase[] = [
  {
    id: 1,
    rfc: "AND150310AB1",
    nombre: "Aceros del Norte Ficticios",
    dias_credito: 30,
    rfc_valido: true,
    situacion_69b: null,
  },
  {
    id: 2,
    rfc: "PCD120501KX2",
    nombre: "Papelería Central Demo",
    dias_credito: 15,
    rfc_valido: true,
    situacion_69b: null,
  },
  {
    id: 3,
    rfc: "TSE180922HJ3",
    nombre: "Transportes Sierra Ejemplo",
    dias_credito: 45,
    rfc_valido: true,
    situacion_69b: null,
  },
  {
    id: 4,
    rfc: "SCP200115QW4",
    nombre: "Software Contable de Prueba",
    dias_credito: 30,
    rfc_valido: true,
    situacion_69b: null,
  },
  {
    id: 5,
    rfc: "EFC110707LM5",
    nombre: "Empaques Ficticios del Centro",
    dias_credito: 60,
    rfc_valido: true,
    situacion_69b: null,
  },
  {
    id: 6,
    rfc: "SLF190404ZZ6",
    nombre: "Servicios Logísticos Fantasma",
    dias_credito: 30,
    rfc_valido: true,
    situacion_69b: "Presunto",
  },
  {
    id: 7,
    rfc: "LID16083OPP7",
    nombre: "Limpieza Integral Demo",
    dias_credito: 30,
    rfc_valido: false,
    situacion_69b: null,
  },
  {
    id: 8,
    rfc: "EFP140228RT8",
    nombre: "Energía Ficticia Peninsular",
    dias_credito: 30,
    rfc_valido: true,
    situacion_69b: null,
  },
];

interface FacturaSemilla {
  id: number;
  proveedor: number;
  serie: string;
  folio: string;
  fecha: string;
  subtotal: string;
  iva: string;
  retencion?: string;
  total: string;
  moneda?: string;
  tipo_cambio?: string;
  total_mxn?: string;
  saldo: string;
  saldo_mxn?: string;
  metodo: "PUE" | "PPD";
  concepto: string;
}

// Los importes están escritos a mano y cuadran: subtotal + IVA - retención = total.
export const FACTURAS_SEMILLA: FacturaSemilla[] = [
  {
    id: 101,
    proveedor: 1,
    serie: "A",
    folio: "4410",
    fecha: "2026-07-28",
    subtotal: "184500.00",
    iva: "29520.00",
    total: "214020.00",
    saldo: "214020.00",
    metodo: "PPD",
    concepto: "Lámina de acero calibre 14, rollo",
  },
  {
    id: 102,
    proveedor: 1,
    serie: "A",
    folio: "4452",
    fecha: "2026-09-02",
    subtotal: "96800.00",
    iva: "15488.00",
    total: "112288.00",
    saldo: "62288.00",
    metodo: "PPD",
    concepto: "Perfil tubular rectangular 2x1",
  },
  {
    id: 103,
    proveedor: 1,
    serie: "A",
    folio: "4501",
    fecha: "2026-10-20",
    subtotal: "143250.00",
    iva: "22920.00",
    total: "166170.00",
    saldo: "166170.00",
    metodo: "PPD",
    concepto: "Placa de acero A36 de 1/4",
  },
  {
    id: 104,
    proveedor: 2,
    serie: "F",
    folio: "8812",
    fecha: "2026-10-27",
    subtotal: "6420.00",
    iva: "1027.20",
    total: "7447.20",
    saldo: "7447.20",
    metodo: "PUE",
    concepto: "Papel bond carta, caja con 10 paquetes",
  },
  {
    id: 105,
    proveedor: 2,
    serie: "F",
    folio: "8790",
    fecha: "2026-10-03",
    subtotal: "3180.50",
    iva: "508.88",
    total: "3689.38",
    saldo: "0.00",
    metodo: "PUE",
    concepto: "Tóner para impresora láser",
  },
  {
    id: 106,
    proveedor: 3,
    serie: "T",
    folio: "1207",
    fecha: "2026-08-14",
    subtotal: "38000.00",
    iva: "6080.00",
    retencion: "1520.00",
    total: "42560.00",
    saldo: "42560.00",
    metodo: "PPD",
    concepto: "Flete Monterrey a Querétaro, 3 viajes",
  },
  {
    id: 107,
    proveedor: 3,
    serie: "T",
    folio: "1260",
    fecha: "2026-10-01",
    subtotal: "25500.00",
    iva: "4080.00",
    retencion: "1020.00",
    total: "28560.00",
    saldo: "28560.00",
    metodo: "PPD",
    concepto: "Flete local con maniobras",
  },
  {
    id: 108,
    proveedor: 4,
    serie: "INT",
    folio: "2026-118",
    fecha: "2026-10-15",
    subtotal: "2400.00",
    iva: "384.00",
    total: "2784.00",
    moneda: "USD",
    tipo_cambio: "18.4520",
    total_mxn: "51370.37",
    saldo: "2784.00",
    saldo_mxn: "51370.37",
    metodo: "PPD",
    concepto: "Licencia anual de sistema contable, 12 usuarios",
  },
  {
    id: 109,
    proveedor: 5,
    serie: "E",
    folio: "3301",
    fecha: "2026-06-30",
    subtotal: "71200.00",
    iva: "11392.00",
    total: "82592.00",
    saldo: "82592.00",
    metodo: "PPD",
    concepto: "Caja de cartón corrugado 40x30x30",
  },
  {
    id: 110,
    proveedor: 5,
    serie: "E",
    folio: "3388",
    fecha: "2026-09-25",
    subtotal: "54300.00",
    iva: "8688.00",
    total: "62988.00",
    saldo: "62988.00",
    metodo: "PPD",
    concepto: "Esquinero de cartón y fleje",
  },
  {
    id: 111,
    proveedor: 6,
    serie: "SL",
    folio: "077",
    fecha: "2026-09-10",
    subtotal: "118000.00",
    iva: "18880.00",
    total: "136880.00",
    saldo: "136880.00",
    metodo: "PPD",
    concepto: "Servicio de logística integral, septiembre",
  },
  {
    id: 112,
    proveedor: 7,
    serie: "L",
    folio: "550",
    fecha: "2026-10-31",
    subtotal: "12900.00",
    iva: "2064.00",
    total: "14964.00",
    saldo: "14964.00",
    metodo: "PPD",
    concepto: "Limpieza de nave industrial, octubre",
  },
  {
    id: 113,
    proveedor: 8,
    serie: "EN",
    folio: "90311",
    fecha: "2026-10-12",
    subtotal: "48760.00",
    iva: "7801.60",
    total: "56561.60",
    saldo: "56561.60",
    metodo: "PPD",
    concepto: "Suministro eléctrico, periodo septiembre",
  },
  {
    id: 114,
    proveedor: 1,
    serie: "A",
    folio: "4503",
    fecha: "2026-10-22",
    subtotal: "143250.00",
    iva: "22920.00",
    total: "166170.00",
    saldo: "166170.00",
    metodo: "PPD",
    concepto: "Placa de acero A36 de 1/4",
  },
  {
    id: 115,
    proveedor: 8,
    serie: "EN",
    folio: "90288",
    fecha: "2026-09-11",
    subtotal: "45120.00",
    iva: "7219.20",
    total: "52339.20",
    saldo: "0.00",
    metodo: "PPD",
    concepto: "Suministro eléctrico, periodo agosto",
  },
  {
    id: 116,
    proveedor: 3,
    serie: "T",
    folio: "1301",
    fecha: "2026-11-04",
    subtotal: "18400.00",
    iva: "2944.00",
    retencion: "736.00",
    total: "20608.00",
    saldo: "20608.00",
    metodo: "PPD",
    concepto: "Flete Querétaro a Guadalajara",
  },
];

const RECEPTOR = {
  rfc: "CFI010101AA1",
  nombre: "Comercializadora Ficticia del Bajío",
  uso_cfdi: "G03",
};

export const EMPRESA = { rfc: RECEPTOR.rfc, nombre: RECEPTOR.nombre };

/** UUID ficticio y estable a partir del id. */
export function uuidFicticio(id: number): string {
  const h = id.toString(16).padStart(4, "0");
  return `5f3c9a1e-${h}-4c2b-9d7e-0a6b${h}c1e2f3`.toUpperCase();
}

function alerta(
  id: number,
  factura: number | null,
  proveedor: number | null,
  codigo: string,
  severidad: "alerta" | "bloqueante",
  mensaje: string,
  relacionada: number | null = null,
): Alerta {
  return {
    id,
    factura_id: factura,
    proveedor_id: proveedor,
    codigo,
    severidad,
    mensaje,
    detalle: {},
    factura_relacionada_id: relacionada,
    estado: "abierta",
    creada_en: "2026-11-03T16:20:00Z",
    resuelta_por: null,
    resuelta_en: null,
    nota_resolucion: null,
  };
}

export const ALERTAS: Alerta[] = [
  alerta(
    1,
    114,
    1,
    "POSIBLE_DUPLICADO",
    "bloqueante",
    "Posible duplicado: mismo proveedor y mismo total que la factura A-4501, emitida 2 días antes.",
    103,
  ),
  alerta(
    2,
    111,
    6,
    "PROVEEDOR_69B",
    "bloqueante",
    "El RFC del emisor aparece en la lista 69-B del SAT como Presunto. No se puede proponer su pago.",
  ),
  alerta(
    3,
    112,
    7,
    "RFC_INVALIDO",
    "alerta",
    "El RFC del emisor no tiene un formato válido: el sexto carácter es una letra O, no un cero.",
  ),
  alerta(
    4,
    108,
    4,
    "MONEDA_EXTRANJERA",
    "alerta",
    "Factura en USD. El equivalente en pesos usa el tipo de cambio del comprobante (18.4520).",
  ),
];

function conceptosDe(f: FacturaSemilla): Concepto[] {
  return [
    {
      orden: 1,
      clave_prod_serv: "30102200",
      cantidad: "1.000000",
      clave_unidad: "E48",
      unidad: "Unidad de servicio",
      descripcion: f.concepto,
      valor_unitario: `${f.subtotal}0000`,
      importe: `${f.subtotal}0000`,
      descuento: null,
    },
  ];
}

export function detalleDe(f: FacturaSemilla): Omit<
  FacturaDetalle,
  "vencimiento" | "dias_vencido" | "proveedor" | "en_propuesta_pendiente"
> & {
  proveedor_id: number;
} {
  const moneda = f.moneda ?? "MXN";
  const alertas = ALERTAS.filter((a) => a.factura_id === f.id);
  const pagada = f.saldo === "0.00";
  const parcial = !pagada && f.saldo !== f.total;
  return {
    id: f.id,
    proveedor_id: f.proveedor,
    uuid: uuidFicticio(f.id),
    tipo: "I",
    serie: f.serie,
    folio: f.folio,
    fecha_emision: f.fecha,
    moneda,
    tipo_cambio: f.tipo_cambio ?? null,
    total: f.total,
    total_mxn: f.total_mxn ?? f.total,
    saldo: f.saldo,
    saldo_mxn: f.saldo_mxn ?? f.saldo,
    estado_pago: pagada ? "pagada" : parcial ? "parcial" : "pendiente",
    resultado: alertas.length > 0 ? "aceptada_con_alertas" : "aceptada",
    alertas_abiertas: alertas.filter((a) => a.estado === "abierta").length,
    tiene_bloqueante: alertas.some((a) => a.severidad === "bloqueante" && a.estado === "abierta"),
    version: "4.0",
    fecha_timbrado: `${f.fecha}T17:42:10Z`,
    receptor: RECEPTOR,
    subtotal: f.subtotal,
    descuento: null,
    total_impuestos_trasladados: f.iva,
    total_impuestos_retenidos: f.retencion ?? null,
    impuestos_locales_trasladados: null,
    impuestos_locales_retenidos: null,
    metodo_pago: f.metodo,
    forma_pago: f.metodo === "PUE" ? "03" : "99",
    condiciones_pago: null,
    exportacion: "01",
    lugar_expedicion: "64000",
    conceptos: conceptosDe(f),
    impuestos: [
      {
        clase: "traslado",
        impuesto: "002",
        tipo_factor: "Tasa",
        tasa_o_cuota: "0.160000",
        base: f.subtotal,
        importe: f.iva,
      },
      ...(f.retencion
        ? [
            {
              clase: "retencion",
              impuesto: "002",
              tipo_factor: "Tasa",
              tasa_o_cuota: "0.040000",
              base: f.subtotal,
              importe: f.retencion,
            },
          ]
        : []),
    ],
    relacionados: [],
    aplicaciones:
      f.id === 102
        ? [
            {
              id: 9001,
              origen: "pago_aprobado",
              importe: "50000.00",
              importe_solicitado: "50000.00",
              fecha: "2026-10-06",
              origen_factura_id: null,
              propuesta_id: 2,
              num_parcialidad: 1,
            },
          ]
        : pagada
          ? [
              {
                id: 9000 + f.id,
                origen: "complemento_pago",
                importe: f.total,
                importe_solicitado: f.total,
                fecha: "2026-10-30",
                origen_factura_id: null,
                propuesta_id: null,
                num_parcialidad: 1,
              },
            ]
          : [],
    alertas,
    carga: { id: 12, creado_en: "2026-11-03T16:20:00Z", usuario: corto(CAPTURISTA) },
  };
}

export const DOCUMENTOS: DocumentoResumen[] = [
  {
    id: 1,
    nombre: "Contrato de suministro Aceros del Norte.pdf",
    tipo: "pdf",
    proveedor: { id: 1, rfc: "AND150310AB1", nombre: "Aceros del Norte Ficticios" },
    paginas: 4,
    fragmentos: 11,
    estado: "indexado",
    explicacion: null,
    subido_por: corto(CAPTURISTA),
    creado_en: "2026-10-02T15:00:00Z",
  },
  {
    id: 2,
    nombre: "Política de pagos 2026.md",
    tipo: "md",
    proveedor: null,
    paginas: 1,
    fragmentos: 6,
    estado: "indexado",
    explicacion: null,
    subido_por: corto(CAPTURISTA),
    creado_en: "2026-09-15T17:30:00Z",
  },
  {
    id: 3,
    nombre: "Contrato de fletes firmado.pdf",
    tipo: "pdf",
    proveedor: { id: 3, rfc: "TSE180922HJ3", nombre: "Transportes Sierra Ejemplo" },
    paginas: 3,
    fragmentos: 0,
    estado: "sin_texto",
    explicacion:
      "El PDF no tiene texto que se pueda extraer; parece una imagen escaneada. Sube una versión con texto o un archivo .txt con su contenido.",
    subido_por: corto(CAPTURISTA),
    creado_en: "2026-10-20T18:05:00Z",
  },
];

export const FRAGMENTOS: Fragmento[] = [
  {
    id: 41,
    documento: { id: 1, nombre: "Contrato de suministro Aceros del Norte.pdf" },
    pagina: 2,
    orden: 4,
    texto:
      "Cláusula Sexta. Condiciones de pago. EL CLIENTE pagará cada factura dentro de los 30 días naturales siguientes a su emisión, mediante transferencia a la cuenta que EL PROVEEDOR indique por escrito.",
    anterior_id: null,
    siguiente_id: 42,
  },
  {
    id: 42,
    documento: { id: 1, nombre: "Contrato de suministro Aceros del Norte.pdf" },
    pagina: 2,
    orden: 5,
    texto:
      "Cláusula Séptima. Pago anticipado. Si EL CLIENTE liquida una factura dentro de los primeros 10 días naturales, EL PROVEEDOR otorgará un descuento de 2% sobre el subtotal mediante nota de crédito.",
    anterior_id: 41,
    siguiente_id: 43,
  },
  {
    id: 43,
    documento: { id: 1, nombre: "Contrato de suministro Aceros del Norte.pdf" },
    pagina: 3,
    orden: 6,
    texto:
      "Cláusula Octava. Pagos tardíos. Los saldos vencidos por más de 15 días generarán una pena convencional de 1.5% mensual sobre el saldo insoluto, sin que exceda el 10% del total de la factura.",
    anterior_id: 42,
    siguiente_id: null,
  },
  {
    id: 51,
    documento: { id: 2, nombre: "Política de pagos 2026.md" },
    pagina: 1,
    orden: 2,
    texto:
      "Los pagos se programan los martes y jueves. Toda propuesta de pago requiere la aprobación de tesorería; quien captura una propuesta no puede aprobarla.",
    anterior_id: null,
    siguiente_id: null,
  },
];

export function propuestasIniciales(): Propuesta[] {
  return [
    {
      id: 3,
      estado: "pendiente",
      presupuesto_mxn: "300000.00",
      total_mxn: "283750.80",
      fecha_limite: "2026-11-13",
      origen: "asistente",
      creada_por: corto(CAPTURISTA),
      creado_en: "2026-11-09T15:12:00Z",
      renglones: [
        {
          id: 31,
          factura: {
            id: 101,
            uuid: uuidFicticio(101),
            serie: "A",
            folio: "4410",
            proveedor: { id: 1, rfc: "AND150310AB1", nombre: "Aceros del Norte Ficticios" },
            moneda: "MXN",
            vencimiento: "2026-08-27",
            saldo_actual: "214020.00",
          },
          importe: "214020.00",
          importe_mxn: "214020.00",
          razon:
            "Vencida hace 74 días; el contrato aplica pena de 1.5% mensual después de 15 días.",
        },
        {
          id: 32,
          factura: {
            id: 106,
            uuid: uuidFicticio(106),
            serie: "T",
            folio: "1207",
            proveedor: { id: 3, rfc: "TSE180922HJ3", nombre: "Transportes Sierra Ejemplo" },
            moneda: "MXN",
            vencimiento: "2026-09-28",
            saldo_actual: "42560.00",
          },
          importe: "42560.00",
          importe_mxn: "42560.00",
          razon: "Vencida hace 42 días.",
        },
        {
          id: 33,
          factura: {
            id: 113,
            uuid: uuidFicticio(113),
            serie: "EN",
            folio: "90311",
            proveedor: { id: 8, rfc: "EFP140228RT8", nombre: "Energía Ficticia Peninsular" },
            moneda: "MXN",
            vencimiento: "2026-11-11",
            saldo_actual: "56561.60",
          },
          importe: "27170.80",
          importe_mxn: "27170.80",
          razon: "Vence en 2 días; se cubre parcialmente para no exceder el presupuesto.",
        },
      ],
      excluidas: [
        {
          factura_id: 111,
          codigo: "PROVEEDOR_69B",
          motivo: "El proveedor está en la lista 69-B como Presunto.",
        },
        {
          factura_id: 114,
          codigo: "POSIBLE_DUPLICADO",
          motivo: "Tiene una alerta de posible duplicado sin resolver.",
        },
      ],
      decidida_por: null,
      decidida_en: null,
      motivo_rechazo: null,
      puede_decidir: false,
    },
    {
      id: 2,
      estado: "aprobada",
      presupuesto_mxn: "50000.00",
      total_mxn: "50000.00",
      fecha_limite: "2026-10-06",
      origen: "api",
      creada_por: corto(CAPTURISTA),
      creado_en: "2026-10-05T16:00:00Z",
      renglones: [
        {
          id: 21,
          factura: {
            id: 102,
            uuid: uuidFicticio(102),
            serie: "A",
            folio: "4452",
            proveedor: { id: 1, rfc: "AND150310AB1", nombre: "Aceros del Norte Ficticios" },
            moneda: "MXN",
            vencimiento: "2026-10-02",
            saldo_actual: "62288.00",
          },
          importe: "50000.00",
          importe_mxn: "50000.00",
          razon: "Abono parcial acordado con el proveedor.",
        },
      ],
      excluidas: [],
      decidida_por: corto(APROBADOR),
      decidida_en: "2026-10-06T14:30:00Z",
      motivo_rechazo: null,
      puede_decidir: false,
    },
    {
      id: 1,
      estado: "rechazada",
      presupuesto_mxn: "20000.00",
      total_mxn: "14964.00",
      fecha_limite: "2026-10-01",
      origen: "api",
      creada_por: corto(CAPTURISTA),
      creado_en: "2026-09-29T19:10:00Z",
      renglones: [],
      excluidas: [],
      decidida_por: corto(APROBADOR),
      decidida_en: "2026-09-30T15:00:00Z",
      motivo_rechazo: "Falta confirmar con el proveedor el monto del servicio.",
      puede_decidir: false,
    },
  ];
}

export function bitacoraInicial(): EntradaBitacora[] {
  const c = corto(CAPTURISTA);
  const a = corto(APROBADOR);
  return [
    {
      id: 12,
      ocurrido_en: "2026-11-09T15:12:00Z",
      usuario: c,
      accion: "PROPUESTA_CREADA",
      entidad: "propuesta",
      entidad_id: 3,
      detalle: { renglones: 3, total_mxn: "283750.80", origen: "asistente" },
    },
    {
      id: 11,
      ocurrido_en: "2026-11-09T15:05:00Z",
      usuario: c,
      accion: "SESION_INICIADA",
      entidad: "usuario",
      entidad_id: 1,
      detalle: { demo: true },
    },
    {
      id: 10,
      ocurrido_en: "2026-11-04T17:40:00Z",
      usuario: c,
      accion: "CARGA_CFDI",
      entidad: "carga",
      entidad_id: 12,
      detalle: { aceptadas: 3, con_alertas: 1, rechazadas: 1, duplicadas: 0 },
    },
    {
      id: 9,
      ocurrido_en: "2026-10-20T18:05:00Z",
      usuario: c,
      accion: "CARGA_DOCUMENTO",
      entidad: "documento",
      entidad_id: 3,
      detalle: { resultado: "sin_texto" },
    },
    {
      id: 8,
      ocurrido_en: "2026-10-12T16:00:00Z",
      usuario: a,
      accion: "LISTA_69B_CARGADA",
      entidad: "lista_69b",
      entidad_id: null,
      detalle: { registros: 120, alertas_creadas: 1 },
    },
    {
      id: 7,
      ocurrido_en: "2026-10-06T14:30:00Z",
      usuario: a,
      accion: "PROPUESTA_APROBADA",
      entidad: "propuesta",
      entidad_id: 2,
      detalle: { total_mxn: "50000.00" },
    },
    {
      id: 6,
      ocurrido_en: "2026-10-06T14:30:00Z",
      usuario: a,
      accion: "PAGO_REGISTRADO",
      entidad: "factura",
      entidad_id: 102,
      detalle: { importe: "50000.00", propuesta_id: 2 },
    },
    {
      id: 5,
      ocurrido_en: "2026-09-30T15:00:00Z",
      usuario: a,
      accion: "PROPUESTA_RECHAZADA",
      entidad: "propuesta",
      entidad_id: 1,
      detalle: { motivo: "Falta confirmar con el proveedor el monto del servicio." },
    },
    {
      id: 4,
      ocurrido_en: "2026-09-20T16:45:00Z",
      usuario: c,
      accion: "PROVEEDOR_EDITADO",
      entidad: "proveedor",
      entidad_id: 5,
      detalle: { campo: "dias_credito", anterior: 30, nuevo: 60 },
    },
  ];
}
