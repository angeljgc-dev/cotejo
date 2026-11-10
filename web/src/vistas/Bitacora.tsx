import { useId } from "react";
import { Link, useSearchParams } from "react-router";
import { useBitacora } from "../api/consultas";
import type { AccionBitacora, EntradaBitacora } from "../api/tipos";
import { Cargando, EstadoError, EstadoVacio } from "../componentes/Estados";
import { Paginacion } from "../componentes/Paginacion";
import { Vista } from "../componentes/Vista";
import { formatearFechaHora } from "../utilidades/fechas";
import { formatearImporte } from "../utilidades/importes";

export const ACCIONES: Record<AccionBitacora, string> = {
  SESION_INICIADA: "Inició sesión",
  CARGA_CFDI: "Cargó CFDI",
  CARGA_DOCUMENTO: "Subió un documento",
  LISTA_69B_CARGADA: "Cargó la lista 69-B",
  PROVEEDOR_EDITADO: "Editó un proveedor",
  ALERTA_RESUELTA: "Resolvió una alerta",
  PROPUESTA_CREADA: "Creó una propuesta",
  PROPUESTA_APROBADA: "Aprobó una propuesta",
  PROPUESTA_RECHAZADA: "Rechazó una propuesta",
  PAGO_REGISTRADO: "Registró un pago",
  DEMO_REINICIADA: "Reinició la demo",
};

const RUTA_ENTIDAD: Record<string, string> = {
  factura: "/facturas",
  propuesta: "/propuestas",
  proveedor: "/proveedores",
};

const ETIQUETA_DETALLE: Record<string, string> = {
  renglones: "renglones",
  total_mxn: "total",
  importe: "importe",
  origen: "origen",
  aceptadas: "aceptadas",
  con_alertas: "con alertas",
  rechazadas: "rechazadas",
  duplicadas: "ya existían",
  resultado: "resultado",
  registros: "registros",
  alertas_creadas: "alertas creadas",
  motivo: "motivo",
  nota: "nota",
  campo: "campo",
  anterior: "antes",
  nuevo: "después",
  propuesta_id: "propuesta",
  demo: "demo",
};

/** Resume el detalle libre de la bitácora en una línea legible; los importes se formatean. */
export function resumirDetalle(detalle: Record<string, unknown>): string {
  return Object.entries(detalle)
    .filter(([, v]) => v !== null && v !== undefined && typeof v !== "object")
    .map(([k, v]) => {
      const etiqueta = ETIQUETA_DETALLE[k] ?? k.replace(/_/g, " ");
      const valor =
        typeof v === "boolean"
          ? v
            ? "sí"
            : "no"
          : k === "total_mxn" || k === "importe"
            ? formatearImporte(String(v))
            : String(v);
      return `${etiqueta}: ${valor}`;
    })
    .join("; ");
}

function Entidad({ e }: { e: EntradaBitacora }) {
  const ruta = RUTA_ENTIDAD[e.entidad];
  const texto = e.entidad_id === null ? e.entidad : `${e.entidad} ${e.entidad_id}`;
  if (!ruta || e.entidad_id === null) return <span>{texto}</span>;
  return <Link to={`${ruta}/${e.entidad_id}`}>{texto}</Link>;
}

export function Bitacora() {
  const [params, setParams] = useSearchParams();
  const accionParam = params.get("accion");
  const accion =
    accionParam && accionParam in ACCIONES ? (accionParam as AccionBitacora) : undefined;
  const pagina = Math.max(1, Number(params.get("pagina")) || 1);
  const consulta = useBitacora({ accion, pagina, por_pagina: 25 });
  const id = useId();

  return (
    <Vista
      titulo="Bitácora"
      descripcion="Quién hizo qué y cuándo: cargas, propuestas, aprobaciones, rechazos y pagos. No se puede editar."
    >
      <div className="filtros">
        <label className="campo" htmlFor={`${id}-accion`}>
          Acción
          <select
            id={`${id}-accion`}
            className="selector"
            value={accion ?? ""}
            onChange={(ev) =>
              setParams(
                ev.target.value
                  ? new URLSearchParams({ accion: ev.target.value })
                  : new URLSearchParams(),
              )
            }
          >
            <option value="">Todas</option>
            {Object.entries(ACCIONES).map(([valor, texto]) => (
              <option key={valor} value={valor}>
                {texto}
              </option>
            ))}
          </select>
        </label>
      </div>
      {consulta.isPending ? (
        <Cargando texto="Cargando la bitácora" />
      ) : consulta.isError ? (
        <EstadoError
          titulo="No pudimos cargar la bitácora"
          error={consulta.error}
          reintentar={() => void consulta.refetch()}
        />
      ) : consulta.data.elementos.length === 0 ? (
        <EstadoVacio titulo={accion ? "No hay registros de esa acción" : "La bitácora está vacía"}>
          {accion
            ? "Elige otra acción o quita el filtro."
            : "Cada carga, propuesta, aprobación y rechazo quedará registrado aquí con quién y cuándo."}
        </EstadoVacio>
      ) : (
        <div className="panel">
          <table className="tabla tabla-apilable">
            <caption className="solo-lectores">Registros de la bitácora</caption>
            <thead>
              <tr>
                <th scope="col">Cuándo</th>
                <th scope="col">Quién</th>
                <th scope="col">Qué</th>
                <th scope="col">Sobre</th>
                <th scope="col">Detalle</th>
              </tr>
            </thead>
            <tbody>
              {consulta.data.elementos.map((e) => (
                <tr key={e.id}>
                  <td data-columna="Cuándo">{formatearFechaHora(e.ocurrido_en)}</td>
                  <td data-columna="Quién">
                    {e.usuario ? (
                      <>
                        {e.usuario.nombre}
                        <span className="secundario bloque">{e.usuario.rol}</span>
                      </>
                    ) : (
                      "Sistema"
                    )}
                  </td>
                  <td data-columna="Qué">{ACCIONES[e.accion] ?? e.accion}</td>
                  <td data-columna="Sobre">
                    <Entidad e={e} />
                  </td>
                  <td data-columna="Detalle">{resumirDetalle(e.detalle)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <Paginacion
            pagina={consulta.data.pagina}
            porPagina={consulta.data.por_pagina}
            total={consulta.data.total}
            singular="registro"
            sustantivo="registros"
            cambiar={(n) => {
              const s = new URLSearchParams(params);
              s.set("pagina", String(n));
              setParams(s);
            }}
          />
        </div>
      )}
    </Vista>
  );
}
