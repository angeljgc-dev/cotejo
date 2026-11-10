import { type ReactNode, useEffect } from "react";

/**
 * Encabezado común de cada vista. Fija el título del documento para que lectores de pantalla y
 * pestañas digan dónde está la persona.
 */
export function Vista({
  titulo,
  descripcion,
  acciones,
  migas,
  children,
}: {
  titulo: string;
  descripcion?: ReactNode;
  acciones?: ReactNode;
  migas?: ReactNode;
  children: ReactNode;
}) {
  useEffect(() => {
    document.title = `${titulo} | Cotejo`;
  }, [titulo]);
  return (
    <div className="contenido">
      <header className="encabezado-vista">
        <div>
          {migas ? <div className="migas">{migas}</div> : null}
          <h1>{titulo}</h1>
          {descripcion ? <p>{descripcion}</p> : null}
        </div>
        {acciones ? <div className="acciones">{acciones}</div> : null}
      </header>
      {children}
    </div>
  );
}
