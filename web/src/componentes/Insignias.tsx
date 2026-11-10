import type { EstadoPago, EstadoPropuesta, SeveridadAlerta } from "../api/tipos";

export function InsigniaSeveridad({ severidad }: { severidad: SeveridadAlerta }) {
  return severidad === "bloqueante" ? (
    <span className="insignia insignia-bloqueante">Bloqueante</span>
  ) : (
    <span className="insignia insignia-alerta">Alerta</span>
  );
}

const PAGO: Record<EstadoPago, { texto: string; clase: string }> = {
  pendiente: { texto: "Pendiente", clase: "insignia" },
  parcial: { texto: "Pago parcial", clase: "insignia insignia-jade" },
  pagada: { texto: "Pagada", clase: "insignia insignia-exito" },
  no_aplica: { texto: "No aplica", clase: "insignia" },
};

export function InsigniaPago({ estado }: { estado: EstadoPago }) {
  const p = PAGO[estado];
  return <span className={p.clase}>{p.texto}</span>;
}

const PROPUESTA: Record<EstadoPropuesta, { texto: string; clase: string }> = {
  pendiente: { texto: "Pendiente de aprobar", clase: "insignia insignia-alerta" },
  aprobada: { texto: "Aprobada", clase: "insignia insignia-exito" },
  rechazada: { texto: "Rechazada", clase: "insignia insignia-bloqueante" },
};

export function InsigniaPropuesta({ estado }: { estado: EstadoPropuesta }) {
  const p = PROPUESTA[estado];
  return <span className={p.clase}>{p.texto}</span>;
}

/** Serie y folio legibles: "A-4410"; si el CFDI no trae ninguno, los primeros 8 del UUID. */
export function nombreFactura(f: {
  serie: string | null;
  folio: string | null;
  uuid: string;
}): string {
  const partes = [f.serie, f.folio].filter((x): x is string => Boolean(x));
  return partes.length > 0 ? partes.join("-") : f.uuid.slice(0, 8);
}
