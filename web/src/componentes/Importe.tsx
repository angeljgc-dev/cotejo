import type { Importe as TextoImporte } from "../api/tipos";
import { formatearImporte } from "../utilidades/importes";

export function Importe({
  valor,
  moneda = "MXN",
  codigo = false,
  className,
}: {
  valor: TextoImporte | null;
  moneda?: string;
  codigo?: boolean;
  className?: string;
}) {
  if (valor === null) return <span className="secundario">No aplica</span>;
  return (
    <span className={className ? `importe ${className}` : "importe"}>
      {formatearImporte(valor, moneda, { codigo })}
    </span>
  );
}

/**
 * Importe en su moneda y, si no es MXN, su equivalente en pesos con el tipo de cambio del
 * comprobante (criterio B5).
 */
export function ImporteConEquivalente({
  valor,
  valorMxn,
  moneda,
  tipoCambio,
}: {
  valor: TextoImporte | null;
  valorMxn: TextoImporte | null;
  moneda: string;
  tipoCambio: string | null;
}) {
  if (moneda === "MXN") return <Importe valor={valor} />;
  return (
    <span>
      <Importe valor={valor} moneda={moneda} />
      <span className="secundario bloque">
        <Importe valor={valorMxn} codigo />
        {tipoCambio ? ` al TC ${tipoCambio}` : null}
      </span>
    </span>
  );
}
