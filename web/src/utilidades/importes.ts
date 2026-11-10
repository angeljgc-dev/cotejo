import type { Importe } from "../api/tipos";

// Los importes llegan como texto decimal exacto. Aquí solo se reordenan dígitos: ninguna función
// convierte dinero a número de punto flotante ni suma importes.

const DECIMAL = /^(-?)(\d+)(?:\.(\d+))?$/;
const MENOS = "−";

interface Partes {
  negativo: boolean;
  entero: string;
  fraccion: string;
}

function partir(texto: string): Partes | null {
  const m = DECIMAL.exec(texto.trim());
  if (!m) return null;
  const entero = (m[2] ?? "0").replace(/^0+(?=\d)/, "");
  const fraccion = (m[3] ?? "").padEnd(2, "0");
  const esCero = /^0+$/.test(entero) && /^0*$/.test(fraccion);
  return { negativo: m[1] === "-" && !esCero, entero, fraccion };
}

function agruparMiles(entero: string): string {
  return entero.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
}

export interface OpcionesFormato {
  /** Agrega el código de moneda también para MXN ("$1,160.00 MXN"). */
  codigo?: boolean;
}

/**
 * Formatea un importe para mostrarlo. MXN usa el signo de pesos; otras monedas, su código ISO al
 * final. Conserva todos los decimales recibidos (mínimo dos). Si el texto no es un decimal válido
 * se devuelve tal cual, para no esconder un dato inesperado.
 */
export function formatearImporte(
  texto: Importe,
  moneda = "MXN",
  opciones: OpcionesFormato = {},
): string {
  const p = partir(texto);
  if (!p) return texto;
  const cifra = `${agruparMiles(p.entero)}.${p.fraccion}`;
  const signo = p.negativo ? MENOS : "";
  if (moneda === "MXN") {
    return `${signo}$${cifra}${opciones.codigo ? " MXN" : ""}`;
  }
  return `${signo}${cifra} ${moneda}`;
}

function aCentavos(texto: string): bigint | null {
  const p = partir(texto);
  if (!p) return null;
  const centavos = BigInt(`${p.entero}${p.fraccion.slice(0, 2)}`);
  return p.negativo ? -centavos : centavos;
}

/**
 * Proporción de `parte` sobre `total` en milésimas enteras (0 a 1000), calculada con enteros
 * exactos. Sirve solo para dibujar el ancho de una barra.
 */
export function proporcionMilesimas(parte: Importe, total: Importe): number {
  const a = aCentavos(parte);
  const b = aCentavos(total);
  if (a === null || b === null || b <= 0n || a <= 0n) return 0;
  const milesimas = (a * 1000n) / b;
  return milesimas > 1000n ? 1000 : Number(milesimas);
}

/**
 * Convierte lo que una persona escribe en un campo de pesos ("150,000", "$2,500.5") al texto
 * decimal que espera la API ("150000.00"). Devuelve null si no es un importe positivo con a lo
 * más dos decimales.
 */
export function normalizarImporteCapturado(entrada: string): Importe | null {
  const limpio = entrada.trim().replace(/^\$/, "").replace(/,/g, "").trim();
  const m = /^(\d{1,13})(?:\.(\d{1,2}))?$/.exec(limpio);
  if (!m) return null;
  const entero = (m[1] ?? "0").replace(/^0+(?=\d)/, "");
  const fraccion = (m[2] ?? "").padEnd(2, "0");
  if (/^0+$/.test(entero) && /^0+$/.test(fraccion)) return null;
  return `${entero}.${fraccion}`;
}
