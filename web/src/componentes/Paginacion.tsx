export function Paginacion({
  pagina,
  porPagina,
  total,
  cambiar,
  singular,
  sustantivo,
}: {
  pagina: number;
  porPagina: number;
  total: number;
  cambiar: (pagina: number) => void;
  singular: string;
  sustantivo: string;
}) {
  const paginas = Math.max(1, Math.ceil(total / porPagina));
  if (total <= porPagina) {
    return <p className="secundario">{`${total} ${total === 1 ? singular : sustantivo}`}</p>;
  }
  const desde = (pagina - 1) * porPagina + 1;
  const hasta = Math.min(total, pagina * porPagina);
  return (
    <nav className="paginacion" aria-label="Paginación">
      <p className="secundario">{`${desde} a ${hasta} de ${total} ${sustantivo}`}</p>
      <div className="acciones">
        <button
          type="button"
          className="boton"
          disabled={pagina <= 1}
          onClick={() => cambiar(pagina - 1)}
        >
          Anterior
        </button>
        <span>{`Página ${pagina} de ${paginas}`}</span>
        <button
          type="button"
          className="boton"
          disabled={pagina >= paginas}
          onClick={() => cambiar(pagina + 1)}
        >
          Siguiente
        </button>
      </div>
    </nav>
  );
}
