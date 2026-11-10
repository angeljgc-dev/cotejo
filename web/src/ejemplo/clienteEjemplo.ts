// Backend simulado en memoria con el contrato de la API. Sirve para las pruebas de la interfaz y
// para ver Cotejo sin levantar el servidor (`npm run dev:ejemplo`). Los agregados del tablero se
// calculan aquí con enteros en centavos porque este módulo hace el papel del backend; la interfaz
// nunca suma importes.

import { type ClienteApi, ErrorApi } from "../api/cliente";
import type {
  ArchivoCargado,
  EstadoAsistente,
  FacturaDetalle,
  FacturaResumen,
  GrupoAntiguedad,
  MensajeChat,
  Pagina,
  Propuesta,
  ProveedorResumen,
  ResultadoDocumento,
  Tablero,
  Usuario,
} from "../api/tipos";
import {
  ALERTAS,
  APROBADOR,
  bitacoraInicial,
  CAPTURISTA,
  corto,
  DOCUMENTOS,
  detalleDe,
  EMPRESA,
  FACTURAS_SEMILLA,
  FRAGMENTOS,
  HOY,
  PROVEEDORES,
  propuestasIniciales,
} from "./datos";

export type ModoAsistente = "disponible" | "sin_llave" | "sin_cuota";

export interface OpcionesEjemplo {
  /** Usuario con sesión al iniciar; null obliga a pasar por Entrar. */
  sesion?: "capturista" | "aprobador" | null;
  /** Todas las listas vacías, como una instalación recién hecha. */
  vacio?: boolean;
  /** Métodos que fallan con el error dado (para probar estados de error). */
  fallas?: Partial<Record<keyof ClienteApi, ErrorApi>>;
  asistente?: ModoAsistente;
  /** Retraso artificial en milisegundos para ver los estados de carga. */
  latencia?: number;
}

function centavos(texto: string): bigint {
  const [entero = "0", fraccion = ""] = texto.replace("-", "").split(".");
  const valor = BigInt(`${entero}${fraccion.padEnd(2, "0").slice(0, 2)}`);
  return texto.startsWith("-") ? -valor : valor;
}

function aTexto(c: bigint): string {
  const negativo = c < 0n;
  const abs = negativo ? -c : c;
  const s = abs.toString().padStart(3, "0");
  return `${negativo ? "-" : ""}${s.slice(0, -2)}.${s.slice(-2)}`;
}

function sumar(lista: string[]): string {
  return aTexto(lista.reduce((acc, x) => acc + centavos(x), 0n));
}

function diasEntre(desde: string, hasta: string): number {
  const a = Date.UTC(
    Number(desde.slice(0, 4)),
    Number(desde.slice(5, 7)) - 1,
    Number(desde.slice(8, 10)),
  );
  const b = Date.UTC(
    Number(hasta.slice(0, 4)),
    Number(hasta.slice(5, 7)) - 1,
    Number(hasta.slice(8, 10)),
  );
  return Math.round((b - a) / 86_400_000);
}

function sumarDias(fecha: string, dias: number): string {
  const d = new Date(
    Date.UTC(Number(fecha.slice(0, 4)), Number(fecha.slice(5, 7)) - 1, Number(fecha.slice(8, 10))),
  );
  d.setUTCDate(d.getUTCDate() + dias);
  return d.toISOString().slice(0, 10);
}

function paginar<T>(lista: T[], pagina = 1, porPagina = 25): Pagina<T> {
  const inicio = (pagina - 1) * porPagina;
  return {
    elementos: lista.slice(inicio, inicio + porPagina),
    total: lista.length,
    pagina,
    por_pagina: porPagina,
  };
}

function noEncontrada(entidad: string): ErrorApi {
  return new ErrorApi(
    404,
    `${entidad}_NO_ENCONTRADA`,
    "No encontramos ese registro. Quizá se reinició la demo.",
  );
}

export function crearClienteEjemplo(opciones: OpcionesEjemplo = {}): ClienteApi {
  const vacio = opciones.vacio ?? false;
  let usuario: Usuario | null =
    opciones.sesion === undefined
      ? CAPTURISTA
      : opciones.sesion === null
        ? null
        : opciones.sesion === "capturista"
          ? CAPTURISTA
          : APROBADOR;
  let modoAsistente: ModoAsistente = opciones.asistente ?? "disponible";
  const limiteChat = 20;
  let restantes = modoAsistente === "sin_cuota" ? 0 : 17;

  let proveedores = vacio ? [] : PROVEEDORES.map((p) => ({ ...p }));
  let alertas = vacio ? [] : ALERTAS.map((a) => ({ ...a }));
  let documentos = vacio ? [] : DOCUMENTOS.map((d) => ({ ...d }));
  let propuestas = vacio ? [] : propuestasIniciales();
  let bitacora = vacio ? [] : bitacoraInicial();
  let facturas: FacturaDetalle[] = [];
  let siguienteId = 500;
  // Pagos aprobados en esta sesión, en centavos por factura.
  let pagos = new Map<number, bigint>();

  function construirFacturas(): FacturaDetalle[] {
    if (vacio) return [];
    return FACTURAS_SEMILLA.map((semilla) => {
      const base = detalleDe(semilla);
      const prov = proveedores.find((p) => p.id === base.proveedor_id) ?? proveedores[0];
      const vencimiento = sumarDias(base.fecha_emision, prov?.dias_credito ?? 30);
      const pendiente = propuestas.find(
        (p) => p.estado === "pendiente" && p.renglones.some((r) => r.factura.id === base.id),
      );
      const { proveedor_id: _omitido, ...resto } = base;
      const pagado = pagos.get(base.id) ?? 0n;
      const saldo = base.saldo === null ? null : aTexto(centavos(base.saldo) - pagado);
      const liquidada = saldo !== null && centavos(saldo) <= 0n;
      return {
        ...resto,
        saldo,
        saldo_mxn: base.moneda === "MXN" ? saldo : base.saldo_mxn,
        estado_pago: liquidada ? "pagada" : pagado > 0n ? "parcial" : base.estado_pago,
        proveedor: { id: prov?.id ?? 0, rfc: prov?.rfc ?? "", nombre: prov?.nombre ?? "" },
        vencimiento,
        dias_vencido: diasEntre(vencimiento, HOY),
        en_propuesta_pendiente: pendiente?.id ?? null,
      };
    });
  }
  facturas = construirFacturas();
  refrescarAlertasDeFacturas();

  function refrescarAlertasDeFacturas() {
    facturas = facturas.map((f) => {
      const propias = alertas.filter((a) => a.factura_id === f.id);
      const abiertas = propias.filter((a) => a.estado === "abierta");
      return {
        ...f,
        alertas: propias,
        alertas_abiertas: abiertas.length,
        tiene_bloqueante: abiertas.some((a) => a.severidad === "bloqueante"),
      };
    });
  }

  function registrar(
    accion: (typeof bitacora)[number]["accion"],
    entidad: string,
    entidadId: number | null,
    detalle: Record<string, unknown>,
  ) {
    bitacora = [
      {
        id: (bitacora[0]?.id ?? 0) + 1,
        ocurrido_en: new Date().toISOString(),
        usuario: usuario ? corto(usuario) : null,
        accion,
        entidad,
        entidad_id: entidadId,
        detalle,
      },
      ...bitacora,
    ];
  }

  async function responder<T>(metodo: keyof ClienteApi, producir: () => T): Promise<T> {
    if (opciones.latencia) await new Promise((r) => setTimeout(r, opciones.latencia));
    const falla = opciones.fallas?.[metodo];
    if (falla) throw falla;
    if (metodo !== "sesion" && metodo !== "entrarDemo" && metodo !== "entrar" && !usuario) {
      throw new ErrorApi(
        401,
        "NO_AUTENTICADO",
        "Tu sesión terminó. Entra de nuevo para continuar.",
      );
    }
    return producir();
  }

  function exigirRol(rol: "capturista" | "aprobador") {
    if (usuario?.rol !== rol) {
      throw new ErrorApi(403, "ROL_INSUFICIENTE", `Esta acción es solo para el rol ${rol}.`);
    }
  }

  function conSaldo(): FacturaDetalle[] {
    return facturas.filter((f) => f.saldo_mxn !== null && centavos(f.saldo_mxn) > 0n);
  }

  function resumenProveedor(p: (typeof proveedores)[number]): ProveedorResumen {
    const propias = conSaldo().filter((f) => f.proveedor.id === p.id);
    return {
      ...p,
      adeudo_mxn: sumar(propias.map((f) => f.saldo_mxn ?? "0")),
      facturas_con_saldo: propias.length,
    };
  }

  function resumenFactura(f: FacturaDetalle): FacturaResumen {
    const {
      version: _v,
      fecha_timbrado: _ft,
      receptor: _r,
      subtotal: _s,
      descuento: _d,
      total_impuestos_trasladados: _t,
      total_impuestos_retenidos: _tr,
      impuestos_locales_trasladados: _lt,
      impuestos_locales_retenidos: _lr,
      metodo_pago: _mp,
      forma_pago: _fp,
      condiciones_pago: _cp,
      exportacion: _e,
      lugar_expedicion: _le,
      conceptos: _c,
      impuestos: _i,
      relacionados: _rel,
      aplicaciones: _a,
      alertas: _al,
      carga: _ca,
      ...resumen
    } = f;
    return resumen;
  }

  function propuestaVista(p: Propuesta): Propuesta {
    return {
      ...p,
      puede_decidir:
        p.estado === "pendiente" && usuario?.rol === "aprobador" && usuario.id !== p.creada_por.id,
    };
  }

  function tablero(): Tablero {
    const lista = conSaldo();
    const grupos: { grupo: GrupoAntiguedad; etiqueta: string; prueba: (d: number) => boolean }[] = [
      { grupo: "por_vencer", etiqueta: "Por vencer", prueba: (d) => d <= 0 },
      { grupo: "1_30", etiqueta: "1 a 30 días", prueba: (d) => d >= 1 && d <= 30 },
      { grupo: "31_60", etiqueta: "31 a 60 días", prueba: (d) => d >= 31 && d <= 60 },
      { grupo: "61_90", etiqueta: "61 a 90 días", prueba: (d) => d >= 61 && d <= 90 },
      { grupo: "mas_90", etiqueta: "Más de 90 días", prueba: (d) => d > 90 },
    ];
    const porProveedor = proveedores
      .map((p) => resumenProveedor(p))
      .filter((p) => p.facturas_con_saldo > 0)
      .sort((a, b) => (centavos(b.adeudo_mxn) > centavos(a.adeudo_mxn) ? 1 : -1));
    const diez = porProveedor.slice(0, 10);
    const otros = porProveedor.slice(10);
    const vencenEn = (dias: number) =>
      lista.filter((f) => (f.dias_vencido ?? 1) <= 0 && -(f.dias_vencido ?? 0) <= dias);
    const v7 = vencenEn(7);
    const v30 = vencenEn(30);
    const monedas = [...new Set(lista.map((f) => f.moneda))];
    return {
      fecha_corte: HOY,
      adeudo_total_mxn: sumar(lista.map((f) => f.saldo_mxn ?? "0")),
      adeudo_por_moneda: monedas.map((m) => {
        const deMoneda = lista.filter((f) => f.moneda === m);
        return {
          moneda: m,
          saldo: sumar(deMoneda.map((f) => f.saldo ?? "0")),
          saldo_mxn: sumar(deMoneda.map((f) => f.saldo_mxn ?? "0")),
        };
      }),
      por_proveedor: diez.map((p) => ({
        proveedor: { id: p.id, rfc: p.rfc, nombre: p.nombre },
        saldo_mxn: p.adeudo_mxn,
        facturas: p.facturas_con_saldo,
      })),
      otros_proveedores: {
        saldo_mxn: sumar(otros.map((p) => p.adeudo_mxn)),
        proveedores: otros.length,
      },
      antiguedad: grupos.map((g) => {
        const del = lista.filter((f) => g.prueba(f.dias_vencido ?? 0));
        return {
          grupo: g.grupo,
          etiqueta: g.etiqueta,
          saldo_mxn: sumar(del.map((f) => f.saldo_mxn ?? "0")),
          facturas: del.length,
        };
      }),
      vencen_7_dias: { saldo_mxn: sumar(v7.map((f) => f.saldo_mxn ?? "0")), facturas: v7.length },
      vencen_30_dias: {
        saldo_mxn: sumar(v30.map((f) => f.saldo_mxn ?? "0")),
        facturas: v30.length,
      },
      facturas_con_alertas: facturas.filter((f) => f.alertas_abiertas > 0).length,
      facturas_bloqueadas: facturas.filter((f) => f.tiene_bloqueante).length,
      propuestas_pendientes: propuestas.filter((p) => p.estado === "pendiente").length,
    };
  }

  function estadoAsistente(): EstadoAsistente {
    if (modoAsistente === "sin_llave") {
      return {
        disponible: false,
        motivo:
          "El asistente no está configurado en esta instalación. El resto de Cotejo funciona normalmente.",
        modelo: null,
        restantes_hoy: 0,
        limite_dia: limiteChat,
      };
    }
    return {
      disponible: true,
      motivo: null,
      modelo: "modelo-de-ejemplo",
      restantes_hoy: restantes,
      limite_dia: limiteChat,
    };
  }

  function respuestaAsistente(conversacion: string | null, texto: string): MensajeChat {
    const t = texto.toLowerCase();
    const base = {
      id: Date.now(),
      conversacion_id: conversacion ?? "c0a8e7f2-0000-4000-8000-000000000001",
      rol: "asistente" as const,
      creado_en: new Date().toISOString(),
      modelo: "modelo-de-ejemplo",
      advertencias: [],
    };
    if (/contrato|cláusula|clausula|pena|descuento|política|politica/.test(t)) {
      return {
        ...base,
        texto:
          "El contrato con Aceros del Norte fija 30 días naturales para pagar [F:41]. Si un saldo pasa de 15 días vencido, se cobra una pena de 1.5% mensual, con tope de 10% del total [F:43]. Pagar en los primeros 10 días da 2% de descuento sobre el subtotal [F:42].",
        herramientas: [
          {
            nombre: "buscar_documentos",
            argumentos: { consulta: "condiciones de pago y penas Aceros del Norte", k: 5 },
            resumen: "3 fragmentos del contrato de suministro (páginas 2 y 3).",
            duracion_ms: 84,
            error: null,
          },
        ],
        facturas_base: [],
        citas: [
          {
            fragmento_id: 41,
            documento_id: 1,
            documento: "Contrato de suministro Aceros del Norte.pdf",
            pagina: 2,
          },
          {
            fragmento_id: 43,
            documento_id: 1,
            documento: "Contrato de suministro Aceros del Norte.pdf",
            pagina: 3,
          },
          {
            fragmento_id: 42,
            documento_id: 1,
            documento: "Contrato de suministro Aceros del Norte.pdf",
            pagina: 2,
          },
        ],
        propuesta_id: null,
      };
    }
    if (/prop[oó]n|propuesta|presupuesto/.test(t)) {
      return {
        ...base,
        texto:
          "Preparé la propuesta 3 con 3 facturas por $283,750.80 dentro del presupuesto de $300,000.00. Excluí 2 facturas: una de un proveedor en la lista 69-B y un posible duplicado. Queda pendiente de aprobación por tesorería.",
        herramientas: [
          {
            nombre: "proponer_pagos",
            argumentos: { presupuesto_mxn: "300000.00", horizonte: "esta_semana" },
            resumen: "Propuesta 3 creada en estado pendiente, 3 renglones, 2 excluidas.",
            duracion_ms: 152,
            error: null,
          },
        ],
        facturas_base: [101, 106, 113].map((id) => {
          const f = facturas.find((x) => x.id === id);
          return {
            id,
            uuid: f?.uuid ?? "",
            serie: f?.serie ?? null,
            folio: f?.folio ?? null,
            proveedor: f?.proveedor ?? { id: 0, rfc: "", nombre: "" },
            moneda: f?.moneda ?? "MXN",
            saldo: f?.saldo ?? null,
          };
        }),
        citas: [],
        propuesta_id: 3,
      };
    }
    const deAceros = facturas.filter((f) => f.proveedor.id === 1 && f.saldo !== "0.00");
    return {
      ...base,
      texto:
        "A Aceros del Norte Ficticios se le deben $608,648.00 en 4 facturas. La más antigua, A-4410, está vencida desde el 27 de agosto.",
      herramientas: [
        {
          nombre: "adeudo_por_proveedor",
          argumentos: { rfc: "AND150310AB1" },
          resumen: "Saldo de 4 facturas con saldo pendiente; total calculado en la base.",
          duracion_ms: 31,
          error: null,
        },
      ],
      facturas_base: deAceros.map((f) => ({
        id: f.id,
        uuid: f.uuid,
        serie: f.serie,
        folio: f.folio,
        proveedor: f.proveedor,
        moneda: f.moneda,
        saldo: f.saldo,
      })),
      citas: [],
      propuesta_id: null,
    };
  }

  function resultadoCfdi(archivo: File, indice: number): ArchivoCargado {
    const nombre = archivo.name;
    const minus = nombre.toLowerCase();
    if (!minus.endsWith(".xml")) {
      return {
        nombre,
        resultado: "rechazada",
        motivos: [
          {
            codigo: "EXTENSION_NO_PERMITIDA",
            mensaje: "Solo se aceptan archivos .xml en la carga de CFDI.",
            severidad: "rechazo",
          },
        ],
        uuid: null,
        factura_id: null,
        tipo: null,
        ya_existia: false,
      };
    }
    if (minus.includes("33") || minus.includes("rechaz")) {
      return {
        nombre,
        resultado: "rechazada",
        motivos: [
          {
            codigo: "VERSION_NO_SOPORTADA",
            mensaje: "El comprobante es CFDI 3.3. Cotejo solo acepta CFDI 4.0.",
            severidad: "rechazo",
          },
        ],
        uuid: null,
        factura_id: null,
        tipo: null,
        ya_existia: false,
      };
    }
    if (minus.includes("dup")) {
      return {
        nombre,
        resultado: "duplicada",
        motivos: [],
        uuid: facturas[0]?.uuid ?? null,
        factura_id: facturas[0]?.id ?? null,
        tipo: "I",
        ya_existia: true,
      };
    }
    const id = siguienteId++;
    if (minus.includes("alerta")) {
      return {
        nombre,
        resultado: "aceptada_con_alertas",
        motivos: [
          {
            codigo: "TOTAL_NO_CUADRA",
            mensaje: "El total no cuadra con subtotal, descuento e impuestos: difiere por $0.40.",
            severidad: "alerta",
          },
        ],
        uuid: `9A1B2C3D-0000-4000-8000-${String(indice).padStart(12, "0")}`,
        factura_id: id,
        tipo: "I",
        ya_existia: false,
      };
    }
    return {
      nombre,
      resultado: "aceptada",
      motivos: [],
      uuid: `9A1B2C3D-0000-4000-9000-${String(indice).padStart(12, "0")}`,
      factura_id: id,
      tipo: "I",
      ya_existia: false,
    };
  }

  const cliente: ClienteApi = {
    sesion: () =>
      responder("sesion", () => {
        if (!usuario) throw new ErrorApi(401, "NO_AUTENTICADO", "Entra para continuar.");
        return usuario;
      }),
    entrarDemo: (rol) =>
      responder("entrarDemo", () => {
        usuario = rol === "capturista" ? CAPTURISTA : APROBADOR;
        registrar("SESION_INICIADA", "usuario", usuario.id, { demo: true });
        return usuario;
      }),
    entrar: (nombre) =>
      responder("entrar", () => {
        if (nombre === APROBADOR.usuario) usuario = APROBADOR;
        else if (nombre === CAPTURISTA.usuario) usuario = CAPTURISTA;
        else
          throw new ErrorApi(
            401,
            "CREDENCIALES_INVALIDAS",
            "El usuario o la contraseña no coinciden.",
          );
        return usuario;
      }),
    salir: () =>
      responder("salir", () => {
        usuario = null;
      }),
    configuracion: () =>
      responder("configuracion", () => ({
        empresa_rfc: EMPRESA.rfc,
        empresa_nombre: EMPRESA.nombre,
        modo_demo: true,
        aviso_demo:
          "Demo pública con datos ficticios: empresas, RFC, facturas y contratos son inventados. Se reinicia cada noche.",
        hoy: HOY,
        zona_horaria: "America/Mexico_City",
        limites: {
          chat_por_dia: limiteChat,
          archivos_por_carga: 50,
          mb_por_xml: 2,
          mb_por_documento: 10,
        },
      })),
    reiniciarDemo: () =>
      responder("reiniciarDemo", () => {
        proveedores = vacio ? [] : PROVEEDORES.map((p) => ({ ...p }));
        alertas = vacio ? [] : ALERTAS.map((a) => ({ ...a }));
        documentos = vacio ? [] : DOCUMENTOS.map((d) => ({ ...d }));
        propuestas = vacio ? [] : propuestasIniciales();
        bitacora = vacio ? [] : bitacoraInicial();
        pagos = new Map();
        facturas = construirFacturas();
        refrescarAlertasDeFacturas();
        registrar("DEMO_REINICIADA", "demo", null, {});
        return {
          reiniciada_en: new Date().toISOString(),
          facturas: facturas.length,
          documentos: documentos.length,
        };
      }),

    tablero: () => responder("tablero", tablero),
    facturas: (f) =>
      responder("facturas", () => {
        let lista = facturas.filter((x) => x.tipo === (f.tipo ?? "I"));
        if (f.proveedor_id) lista = lista.filter((x) => x.proveedor.id === f.proveedor_id);
        if (f.moneda) lista = lista.filter((x) => x.moneda === f.moneda);
        if (f.con_alertas) lista = lista.filter((x) => x.alertas_abiertas > 0);
        if (f.severidad === "bloqueante") lista = lista.filter((x) => x.tiene_bloqueante);
        const estado = f.estado ?? "todas";
        if (estado === "pagada") lista = lista.filter((x) => x.estado_pago === "pagada");
        if (estado === "pendiente") lista = lista.filter((x) => x.estado_pago !== "pagada");
        if (estado === "vencida")
          lista = lista.filter((x) => x.estado_pago !== "pagada" && (x.dias_vencido ?? 0) > 0);
        if (estado === "por_vencer")
          lista = lista.filter((x) => x.estado_pago !== "pagada" && (x.dias_vencido ?? 1) <= 0);
        if (f.texto) {
          const q = f.texto.toLowerCase();
          lista = lista.filter((x) =>
            [x.uuid, x.serie, x.folio, x.proveedor.rfc, x.proveedor.nombre]
              .filter(Boolean)
              .some((v) => String(v).toLowerCase().includes(q)),
          );
        }
        const orden = f.orden ?? "vencimiento";
        const ordenada = [...lista].sort((a, b) => {
          if (orden === "fecha") return b.fecha_emision.localeCompare(a.fecha_emision);
          if (orden === "saldo")
            return centavos(b.saldo_mxn ?? "0") > centavos(a.saldo_mxn ?? "0") ? 1 : -1;
          if (orden === "total") return centavos(b.total_mxn) > centavos(a.total_mxn) ? 1 : -1;
          return (a.vencimiento ?? "").localeCompare(b.vencimiento ?? "");
        });
        return paginar(ordenada.map(resumenFactura), f.pagina, f.por_pagina);
      }),
    factura: (id) =>
      responder("factura", () => {
        const f = facturas.find((x) => x.id === id);
        if (!f) throw noEncontrada("FACTURA");
        return f;
      }),
    cargarCfdi: (archivos) =>
      responder("cargarCfdi", () => {
        exigirRol("capturista");
        if (archivos.length === 0)
          throw new ErrorApi(422, "SIN_ARCHIVOS", "Elige al menos un archivo XML.");
        const resultado = archivos.map(resultadoCfdi);
        const resumen = {
          aceptadas: resultado.filter((r) => r.resultado === "aceptada").length,
          con_alertas: resultado.filter((r) => r.resultado === "aceptada_con_alertas").length,
          rechazadas: resultado.filter((r) => r.resultado === "rechazada").length,
          duplicadas: resultado.filter((r) => r.resultado === "duplicada").length,
        };
        registrar("CARGA_CFDI", "carga", 13, resumen);
        return { carga_id: 13, archivos: resultado, resumen };
      }),
    resolverAlerta: (id, nota) =>
      responder("resolverAlerta", () => {
        exigirRol("aprobador");
        const a = alertas.find((x) => x.id === id);
        if (!a) throw noEncontrada("ALERTA");
        if (a.estado === "resuelta")
          throw new ErrorApi(409, "ALERTA_YA_RESUELTA", "Esta alerta ya estaba resuelta.");
        if (a.codigo === "PROVEEDOR_69B") {
          throw new ErrorApi(
            422,
            "ALERTA_NO_RESOLUBLE",
            "Las alertas de la lista 69-B solo se cierran al cargar una lista actualizada del SAT.",
          );
        }
        const resuelta = {
          ...a,
          estado: "resuelta" as const,
          resuelta_por: usuario ? corto(usuario) : null,
          resuelta_en: new Date().toISOString(),
          nota_resolucion: nota,
        };
        alertas = alertas.map((x) => (x.id === id ? resuelta : x));
        refrescarAlertasDeFacturas();
        registrar("ALERTA_RESUELTA", "alerta", id, { nota });
        return resuelta;
      }),

    proveedores: (params) =>
      responder("proveedores", () => {
        const q = params.texto?.toLowerCase() ?? "";
        const lista = proveedores
          .filter(
            (p) => !q || p.nombre.toLowerCase().includes(q) || p.rfc.toLowerCase().includes(q),
          )
          .map(resumenProveedor);
        return paginar(lista, params.pagina, params.por_pagina);
      }),
    proveedor: (id) =>
      responder("proveedor", () => {
        const p = proveedores.find((x) => x.id === id);
        if (!p) throw noEncontrada("PROVEEDOR");
        const propias = conSaldo().filter((f) => f.proveedor.id === id);
        const monedas = [...new Set(propias.map((f) => f.moneda))];
        return {
          ...resumenProveedor(p),
          adeudo_por_moneda: monedas.map((m) => ({
            moneda: m,
            saldo: sumar(propias.filter((f) => f.moneda === m).map((f) => f.saldo ?? "0")),
            saldo_mxn: sumar(propias.filter((f) => f.moneda === m).map((f) => f.saldo_mxn ?? "0")),
          })),
          documentos: documentos
            .filter((d) => d.proveedor?.id === id)
            .map((d) => ({ id: d.id, nombre: d.nombre, tipo: d.tipo, estado: d.estado })),
        };
      }),
    editarProveedor: (id, cambios) =>
      responder("editarProveedor", () => {
        const p = proveedores.find((x) => x.id === id);
        if (!p) throw noEncontrada("PROVEEDOR");
        if (
          !Number.isInteger(cambios.dias_credito) ||
          cambios.dias_credito < 0 ||
          cambios.dias_credito > 365
        ) {
          throw new ErrorApi(422, "VALIDACION", "Revisa los datos.", {
            campos: [{ campo: "dias_credito", mensaje: "Escribe un número entero de 0 a 365." }],
          });
        }
        registrar("PROVEEDOR_EDITADO", "proveedor", id, {
          campo: "dias_credito",
          anterior: p.dias_credito,
          nuevo: cambios.dias_credito,
        });
        proveedores = proveedores.map((x) =>
          x.id === id ? { ...x, dias_credito: cambios.dias_credito } : x,
        );
        facturas = construirFacturas();
        refrescarAlertasDeFacturas();
        const actualizado = proveedores.find((x) => x.id === id);
        if (!actualizado) throw noEncontrada("PROVEEDOR");
        return resumenProveedor(actualizado);
      }),

    documentos: (params) =>
      responder("documentos", () => {
        const lista = params.proveedor_id
          ? documentos.filter((d) => d.proveedor?.id === params.proveedor_id)
          : documentos;
        return paginar(lista, params.pagina, params.por_pagina);
      }),
    subirDocumentos: (archivos, proveedorId) =>
      responder("subirDocumentos", () => {
        exigirRol("capturista");
        const prov =
          proveedorId === null ? null : (proveedores.find((p) => p.id === proveedorId) ?? null);
        return archivos.map((a, i): ResultadoDocumento => {
          const minus = a.name.toLowerCase();
          if (!/\.(pdf|txt|md)$/.test(minus)) {
            return {
              nombre: a.name,
              resultado: "rechazado",
              documento_id: null,
              paginas: null,
              fragmentos: null,
              explicacion: null,
              motivos: [
                {
                  codigo: "EXTENSION_NO_PERMITIDA",
                  mensaje: "Solo se aceptan documentos .pdf, .txt o .md.",
                  severidad: "rechazo",
                },
              ],
            };
          }
          const sinTexto = minus.includes("escane");
          const id = 100 + documentos.length + i;
          const resultado: ResultadoDocumento = {
            nombre: a.name,
            resultado: sinTexto ? "sin_texto" : "indexado",
            documento_id: id,
            paginas: sinTexto ? 2 : 1,
            fragmentos: sinTexto ? 0 : 3,
            explicacion: sinTexto
              ? "El PDF no tiene texto que se pueda extraer; parece una imagen escaneada. Sube una versión con texto o un archivo .txt con su contenido."
              : null,
            motivos: [],
          };
          documentos = [
            {
              id,
              nombre: a.name,
              tipo: minus.split(".").pop() ?? "txt",
              proveedor: prov ? { id: prov.id, rfc: prov.rfc, nombre: prov.nombre } : null,
              paginas: resultado.paginas,
              fragmentos: resultado.fragmentos,
              estado: sinTexto ? "sin_texto" : "indexado",
              explicacion: resultado.explicacion,
              subido_por: usuario ? corto(usuario) : corto(CAPTURISTA),
              creado_en: new Date().toISOString(),
            },
            ...documentos,
          ];
          registrar("CARGA_DOCUMENTO", "documento", id, { resultado: resultado.resultado });
          return resultado;
        });
      }),
    fragmento: (id) =>
      responder("fragmento", () => {
        const f = FRAGMENTOS.find((x) => x.id === id);
        if (!f) throw noEncontrada("FRAGMENTO");
        return f;
      }),

    estadoAsistente: () => responder("estadoAsistente", estadoAsistente),
    enviarMensaje: (conversacion, texto) =>
      responder("enviarMensaje", () => {
        if (modoAsistente === "sin_llave") {
          throw new ErrorApi(
            503,
            "ASISTENTE_NO_CONFIGURADO",
            "El asistente no está configurado en esta instalación. El resto de Cotejo funciona normalmente.",
          );
        }
        if (restantes <= 0) {
          throw new ErrorApi(429, "LIMITE_CHAT", "Llegaste al límite de preguntas de hoy.", {
            limite: limiteChat,
            se_reinicia: "2026-11-10T00:00:00-06:00",
          });
        }
        restantes -= 1;
        if (restantes <= 0) modoAsistente = "sin_cuota";
        return respuestaAsistente(conversacion, texto);
      }),

    propuestas: (params) =>
      responder("propuestas", () => {
        const lista = propuestas
          .filter((p) => !params.estado || p.estado === params.estado)
          .map((p) => ({
            id: p.id,
            estado: p.estado,
            presupuesto_mxn: p.presupuesto_mxn,
            total_mxn: p.total_mxn,
            renglones: p.renglones.length,
            creada_por: p.creada_por,
            creado_en: p.creado_en,
            decidida_por: p.decidida_por,
          }));
        return paginar(lista, params.pagina, params.por_pagina);
      }),
    propuesta: (id) =>
      responder("propuesta", () => {
        const p = propuestas.find((x) => x.id === id);
        if (!p) throw noEncontrada("PROPUESTA");
        return propuestaVista(p);
      }),
    crearPropuesta: (datos) =>
      responder("crearPropuesta", () => {
        exigirRol("capturista");
        const candidatas = conSaldo()
          .filter(
            (f) => !f.tiene_bloqueante && f.moneda === "MXN" && f.en_propuesta_pendiente === null,
          )
          .sort((a, b) => (a.vencimiento ?? "").localeCompare(b.vencimiento ?? ""));
        const limite = centavos(datos.presupuesto_mxn);
        let acumulado = 0n;
        const elegidas = candidatas.filter((f) => {
          const saldo = centavos(f.saldo_mxn ?? "0");
          if (acumulado + saldo > limite) return false;
          acumulado += saldo;
          return true;
        });
        if (elegidas.length === 0) {
          throw new ErrorApi(
            422,
            "PROPUESTA_VACIA",
            "Ninguna factura cabe en el presupuesto o todas tienen una barrera. Sube el presupuesto o revisa las alertas.",
          );
        }
        const nueva: Propuesta = {
          id: Math.max(0, ...propuestas.map((p) => p.id)) + 1,
          estado: "pendiente",
          presupuesto_mxn: datos.presupuesto_mxn,
          total_mxn: aTexto(acumulado),
          fecha_limite: datos.fecha_limite,
          origen: "api",
          creada_por: usuario ? corto(usuario) : corto(CAPTURISTA),
          creado_en: new Date().toISOString(),
          renglones: elegidas.map((f, i) => ({
            id: 1000 + i,
            factura: {
              id: f.id,
              uuid: f.uuid,
              serie: f.serie,
              folio: f.folio,
              proveedor: f.proveedor,
              moneda: f.moneda,
              vencimiento: f.vencimiento,
              saldo_actual: f.saldo ?? "0.00",
            },
            importe: f.saldo ?? "0.00",
            importe_mxn: f.saldo_mxn ?? "0.00",
            razon:
              (f.dias_vencido ?? 0) > 0
                ? `Vencida hace ${f.dias_vencido} días.`
                : "Vence dentro del horizonte elegido.",
          })),
          excluidas: facturas
            .filter((f) => f.tiene_bloqueante)
            .map((f) => ({
              factura_id: f.id,
              codigo: "ALERTA_BLOQUEANTE",
              motivo: "Tiene una alerta bloqueante abierta.",
            })),
          decidida_por: null,
          decidida_en: null,
          motivo_rechazo: null,
          puede_decidir: false,
        };
        propuestas = [nueva, ...propuestas];
        facturas = construirFacturas();
        refrescarAlertasDeFacturas();
        registrar("PROPUESTA_CREADA", "propuesta", nueva.id, { renglones: nueva.renglones.length });
        return propuestaVista(nueva);
      }),
    aprobarPropuesta: (id) =>
      responder("aprobarPropuesta", () => {
        exigirRol("aprobador");
        const p = propuestas.find((x) => x.id === id);
        if (!p) throw noEncontrada("PROPUESTA");
        if (p.estado !== "pendiente")
          throw new ErrorApi(409, "PROPUESTA_NO_PENDIENTE", "Esta propuesta ya fue decidida.");
        if (usuario?.id === p.creada_por.id) {
          throw new ErrorApi(403, "MISMO_USUARIO", "Quien creó la propuesta no puede aprobarla.");
        }
        const aprobada: Propuesta = {
          ...p,
          estado: "aprobada",
          decidida_por: usuario ? corto(usuario) : null,
          decidida_en: new Date().toISOString(),
        };
        propuestas = propuestas.map((x) => (x.id === id ? aprobada : x));
        for (const r of p.renglones) {
          pagos.set(r.factura.id, (pagos.get(r.factura.id) ?? 0n) + centavos(r.importe));
          registrar("PAGO_REGISTRADO", "factura", r.factura.id, {
            importe: r.importe,
            propuesta_id: id,
          });
        }
        facturas = construirFacturas();
        refrescarAlertasDeFacturas();
        registrar("PROPUESTA_APROBADA", "propuesta", id, { total_mxn: p.total_mxn });
        return propuestaVista(aprobada);
      }),
    rechazarPropuesta: (id, motivo) =>
      responder("rechazarPropuesta", () => {
        exigirRol("aprobador");
        const p = propuestas.find((x) => x.id === id);
        if (!p) throw noEncontrada("PROPUESTA");
        if (p.estado !== "pendiente")
          throw new ErrorApi(409, "PROPUESTA_NO_PENDIENTE", "Esta propuesta ya fue decidida.");
        const rechazada: Propuesta = {
          ...p,
          estado: "rechazada",
          decidida_por: usuario ? corto(usuario) : null,
          decidida_en: new Date().toISOString(),
          motivo_rechazo: motivo,
        };
        propuestas = propuestas.map((x) => (x.id === id ? rechazada : x));
        facturas = construirFacturas();
        refrescarAlertasDeFacturas();
        registrar("PROPUESTA_RECHAZADA", "propuesta", id, { motivo });
        return propuestaVista(rechazada);
      }),

    bitacora: (f) =>
      responder("bitacora", () => {
        let lista = bitacora;
        if (f.accion) lista = lista.filter((e) => e.accion === f.accion);
        if (f.usuario_id) lista = lista.filter((e) => e.usuario?.id === f.usuario_id);
        return paginar(lista, f.pagina, f.por_pagina);
      }),
  };
  return cliente;
}
