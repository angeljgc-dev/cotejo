import type { Fecha, FechaHora } from "../api/tipos";

const MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];
const ZONA = "America/Mexico_City";

/** "2026-11-09" -> "9 nov 2026". Se parte el texto para no depender de la zona del navegador. */
export function formatearFecha(fecha: Fecha): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(fecha);
  if (!m) return fecha;
  const mes = MESES[Number(m[2]) - 1];
  if (!mes) return fecha;
  return `${Number(m[3])} ${mes} ${m[1]}`;
}

const formatoZona = new Intl.DateTimeFormat("en-CA", {
  timeZone: ZONA,
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
});

/** Fecha y hora en la zona de la Ciudad de México: "9 nov 2026, 10:15". */
export function formatearFechaHora(valor: FechaHora): string {
  const instante = new Date(valor);
  if (Number.isNaN(instante.getTime())) return valor;
  const partes: Record<string, string> = {};
  for (const p of formatoZona.formatToParts(instante)) partes[p.type] = p.value;
  const fecha = formatearFecha(`${partes.year}-${partes.month}-${partes.day}`);
  return `${fecha}, ${partes.hour}:${partes.minute}`;
}

/** Texto corto para `dias_vencido` (negativo = faltan días). */
export function textoVencimiento(diasVencido: number | null): string {
  if (diasVencido === null) return "Sin vencimiento";
  if (diasVencido === 0) return "Vence hoy";
  if (diasVencido === -1) return "Vence mañana";
  if (diasVencido < 0) return `Vence en ${-diasVencido} días`;
  return `Vencida hace ${diasVencido} ${diasVencido === 1 ? "día" : "días"}`;
}
