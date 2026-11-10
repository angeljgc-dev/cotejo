import type { ReactNode } from "react";
import { ErrorApi } from "../api/cliente";
import { formatearFechaHora } from "../utilidades/fechas";

export function Cargando({ texto }: { texto: string }) {
  return (
    <div className="cargando" role="status" aria-live="polite">
      <span className="cargando-barra" aria-hidden="true" />
      <span>{texto}</span>
    </div>
  );
}

export function EstadoVacio({
  titulo,
  children,
  accion,
}: {
  titulo: string;
  children?: ReactNode;
  accion?: ReactNode;
}) {
  return (
    <div className="estado">
      <h2>{titulo}</h2>
      {children ? <p>{children}</p> : null}
      {accion}
    </div>
  );
}

/** Mensaje legible para cualquier error que venga de una consulta o mutación. */
export function mensajeDeError(error: unknown): string {
  if (error instanceof ErrorApi) {
    if (error.codigo === "VALIDACION") {
      const campos =
        !Array.isArray(error.detalle) && Array.isArray(error.detalle.campos)
          ? error.detalle.campos
          : [];
      const detalle = campos
        .map((c: unknown) =>
          typeof c === "object" && c !== null && "mensaje" in c ? String(c.mensaje) : "",
        )
        .filter(Boolean)
        .join(" ");
      return detalle ? `${error.message} ${detalle}` : error.message;
    }
    if (error.codigo.startsWith("LIMITE_") && !Array.isArray(error.detalle)) {
      const reinicio = error.detalle.se_reinicia;
      if (typeof reinicio === "string") {
        return `${error.message} Podrás intentarlo de nuevo a partir del ${formatearFechaHora(reinicio)}.`;
      }
    }
    return error.message;
  }
  return "Ocurrió un error inesperado en la página. Recarga e intenta de nuevo.";
}

export function EstadoError({
  titulo,
  error,
  reintentar,
}: {
  titulo: string;
  error: unknown;
  reintentar?: () => void;
}) {
  return (
    <div className="estado estado-error" role="alert">
      <h2>{titulo}</h2>
      <p>{mensajeDeError(error)}</p>
      {reintentar ? (
        <button type="button" className="boton" onClick={reintentar}>
          Intentar de nuevo
        </button>
      ) : null}
    </div>
  );
}

/** Error de una acción (no de una carga de datos): aparece junto al formulario que lo causó. */
export function ErrorAccion({ error }: { error: unknown }) {
  if (!error) return null;
  return (
    <div className="mensaje mensaje-error" role="alert">
      <p>{mensajeDeError(error)}</p>
    </div>
  );
}
