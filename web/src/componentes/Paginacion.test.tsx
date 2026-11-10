import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Paginacion } from "./Paginacion";

const sinCambio = () => undefined;

describe("Paginacion", () => {
  it("usa el singular cuando hay un solo elemento", () => {
    render(
      <Paginacion
        pagina={1}
        porPagina={25}
        total={1}
        cambiar={sinCambio}
        singular="propuesta"
        sustantivo="propuestas"
      />,
    );
    expect(screen.getByText("1 propuesta")).toBeInTheDocument();
  });

  it("usa el plural con cero o con varios", () => {
    const { rerender } = render(
      <Paginacion
        pagina={1}
        porPagina={25}
        total={0}
        cambiar={sinCambio}
        singular="proveedor"
        sustantivo="proveedores"
      />,
    );
    expect(screen.getByText("0 proveedores")).toBeInTheDocument();
    rerender(
      <Paginacion
        pagina={2}
        porPagina={25}
        total={60}
        cambiar={sinCambio}
        singular="proveedor"
        sustantivo="proveedores"
      />,
    );
    expect(screen.getByText("26 a 50 de 60 proveedores")).toBeInTheDocument();
  });
});
