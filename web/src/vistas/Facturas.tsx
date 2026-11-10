import { useId } from "react";
import { Link, useSearchParams } from "react-router";
import { useFacturas } from "../api/consultas";
import { useUsuario } from "../api/contexto";
import type { FiltroEstadoFactura, FiltrosFacturas, OrdenFacturas } from "../api/tipos";
import { Cargando, EstadoError, EstadoVacio } from "../componentes/Estados";
import { ImporteConEquivalente } from "../componentes/Importe";
import { InsigniaPago, nombreFactura } from "../componentes/Insignias";
import { Paginacion } from "../componentes/Paginacion";
import { Vista } from "../componentes/Vista";
import { formatearFecha, textoVencimiento } from "../utilidades/fechas";

const ESTADOS: { valor: FiltroEstadoFactura; texto: string }[] = [
  { valor: "todas", texto: "Todas" },
  { valor: "pendiente", texto: "Con saldo" },
  { valor: "vencida", texto: "Vencidas" },
  { valor: "por_vencer", texto: "Por vencer" },
  { valor: "pagada", texto: "Pagadas" },
];

const ORDENES: { valor: OrdenFacturas; texto: string }[] = [
  { valor: "vencimiento", texto: "Vencimiento" },
  { valor: "fecha", texto: "Emisión reciente" },
  { valor: "saldo", texto: "Saldo mayor" },
  { valor: "total", texto: "Total mayor" },
];

const POR_PAGINA = 25;

export function leerFiltros(params: URLSearchParams): FiltrosFacturas {
  const estado = params.get("estado") as FiltroEstadoFactura | null;
  const orden = params.get("orden") as OrdenFacturas | null;
  const severidad = params.get("severidad");
  const proveedor = Number(params.get("proveedor_id"));
  return {
    estado: estado && ESTADOS.some((e) => e.valor === estado) ? estado : "todas",
    orden: orden && ORDENES.some((o) => o.valor === orden) ? orden : "vencimiento",
    texto: params.get("texto") ?? undefined,
    moneda: params.get("moneda") ?? undefined,
    con_alertas: params.get("con_alertas") === "true" ? true : undefined,
    severidad: severidad === "bloqueante" || severidad === "alerta" ? severidad : undefined,
    proveedor_id: Number.isInteger(proveedor) && proveedor > 0 ? proveedor : undefined,
    pagina: Math.max(1, Number(params.get("pagina")) || 1),
    por_pagina: POR_PAGINA,
  };
}

export function Facturas() {
  const usuario = useUsuario();
  const [params, setParams] = useSearchParams();
  const filtros = leerFiltros(params);
  const consulta = useFacturas(filtros);
  const id = useId();

  function cambiar(clave: string, valor: string | null) {
    const siguientes = new URLSearchParams(params);
    if (valor === null || valor === "") siguientes.delete(clave);
    else siguientes.set(clave, valor);
    if (clave !== "pagina") siguientes.delete("pagina");
    setParams(siguientes, { replace: true });
  }

  const hayFiltros =
    filtros.estado !== "todas" ||
    Boolean(
      filtros.texto ||
        filtros.moneda ||
        filtros.con_alertas ||
        filtros.severidad ||
        filtros.proveedor_id,
    );

  return (
    <Vista
      titulo="Facturas"
      descripcion="CFDI de ingreso recibidos, con su saldo, vencimiento y alertas."
      acciones={
        usuario.rol === "capturista" ? (
          <Link className="boton boton-primario" to="/facturas/cargar">
            Cargar CFDI
          </Link>
        ) : null
      }
    >
      <search>
        <form
          className="filtros"
          onSubmit={(e) => e.preventDefault()}
          aria-label="Filtros de facturas"
        >
          <label className="campo" htmlFor={`${id}-texto`}>
            Buscar
            <input
              id={`${id}-texto`}
              className="entrada"
              type="search"
              placeholder="Folio, RFC o proveedor"
              defaultValue={filtros.texto ?? ""}
              onChange={(e) => cambiar("texto", e.target.value.trim())}
            />
          </label>
          <label className="campo" htmlFor={`${id}-estado`}>
            Estado
            <select
              id={`${id}-estado`}
              className="selector"
              value={filtros.estado}
              onChange={(e) =>
                cambiar("estado", e.target.value === "todas" ? null : e.target.value)
              }
            >
              {ESTADOS.map((e) => (
                <option key={e.valor} value={e.valor}>
                  {e.texto}
                </option>
              ))}
            </select>
          </label>
          <label className="campo" htmlFor={`${id}-moneda`}>
            Moneda
            <select
              id={`${id}-moneda`}
              className="selector"
              value={filtros.moneda ?? ""}
              onChange={(e) => cambiar("moneda", e.target.value)}
            >
              <option value="">Todas</option>
              <option value="MXN">MXN</option>
              <option value="USD">USD</option>
              <option value="EUR">EUR</option>
            </select>
          </label>
          <label className="campo" htmlFor={`${id}-orden`}>
            Ordenar por
            <select
              id={`${id}-orden`}
              className="selector"
              value={filtros.orden}
              onChange={(e) => cambiar("orden", e.target.value)}
            >
              {ORDENES.map((o) => (
                <option key={o.valor} value={o.valor}>
                  {o.texto}
                </option>
              ))}
            </select>
          </label>
          <label className="casilla">
            <input
              type="checkbox"
              checked={filtros.con_alertas ?? false}
              onChange={(e) => cambiar("con_alertas", e.target.checked ? "true" : null)}
            />
            Solo con alertas abiertas
          </label>
          <label className="casilla">
            <input
              type="checkbox"
              checked={filtros.severidad === "bloqueante"}
              onChange={(e) => cambiar("severidad", e.target.checked ? "bloqueante" : null)}
            />
            Solo bloqueadas para pago
          </label>
        </form>
      </search>

      {consulta.isPending ? (
        <Cargando texto="Cargando facturas" />
      ) : consulta.isError ? (
        <EstadoError
          titulo="No pudimos cargar las facturas"
          error={consulta.error}
          reintentar={() => void consulta.refetch()}
        />
      ) : consulta.data.elementos.length === 0 ? (
        hayFiltros ? (
          <EstadoVacio
            titulo="Ninguna factura coincide con los filtros"
            accion={
              <button
                type="button"
                className="boton"
                onClick={() => setParams(new URLSearchParams())}
              >
                Quitar filtros
              </button>
            }
          >
            Prueba con otro estado o borra el texto de búsqueda.
          </EstadoVacio>
        ) : (
          <EstadoVacio
            titulo="Todavía no hay facturas"
            accion={
              usuario.rol === "capturista" ? (
                <Link className="boton boton-primario" to="/facturas/cargar">
                  Cargar CFDI
                </Link>
              ) : null
            }
          >
            {usuario.rol === "capturista"
              ? "Carga los XML de tus CFDI 4.0 y Cotejo los valida, calcula su vencimiento y su saldo."
              : "Cuando el capturista cargue los XML de los CFDI, aparecerán aquí con su saldo y vencimiento."}
          </EstadoVacio>
        )
      ) : (
        <div className="panel">
          <div className="tabla-contenedor">
            <table className="tabla tabla-apilable">
              <caption className="solo-lectores">Facturas</caption>
              <thead>
                <tr>
                  <th scope="col">Factura</th>
                  <th scope="col">Proveedor</th>
                  <th scope="col">Emisión</th>
                  <th scope="col">Vencimiento</th>
                  <th scope="col" className="num">
                    Total
                  </th>
                  <th scope="col" className="num">
                    Saldo
                  </th>
                  <th scope="col">Estado</th>
                </tr>
              </thead>
              <tbody>
                {consulta.data.elementos.map((f) => (
                  <tr key={f.id}>
                    <td data-columna="Factura">
                      <Link to={`/facturas/${f.id}`}>{nombreFactura(f)}</Link>
                    </td>
                    <td data-columna="Proveedor">
                      {f.proveedor.nombre}
                      <span className="uuid bloque">{f.proveedor.rfc}</span>
                    </td>
                    <td data-columna="Emisión" className="sin-corte">
                      {formatearFecha(f.fecha_emision)}
                    </td>
                    <td data-columna="Vencimiento" className="sin-corte">
                      {f.vencimiento ? formatearFecha(f.vencimiento) : "Sin fecha"}
                      {f.estado_pago !== "pagada" ? (
                        <span
                          className={
                            (f.dias_vencido ?? 0) > 0 ? "bloque campo-error" : "bloque secundario"
                          }
                        >
                          {textoVencimiento(f.dias_vencido)}
                        </span>
                      ) : null}
                    </td>
                    <td data-columna="Total" className="num">
                      <ImporteConEquivalente
                        valor={f.total}
                        valorMxn={f.total_mxn}
                        moneda={f.moneda}
                        tipoCambio={f.tipo_cambio}
                      />
                    </td>
                    <td data-columna="Saldo" className="num">
                      <ImporteConEquivalente
                        valor={f.saldo}
                        valorMxn={f.saldo_mxn}
                        moneda={f.moneda}
                        tipoCambio={f.tipo_cambio}
                      />
                    </td>
                    <td data-columna="Estado">
                      <div className="acciones">
                        <InsigniaPago estado={f.estado_pago} />
                        {f.tiene_bloqueante ? (
                          <span className="insignia insignia-bloqueante">Bloqueada</span>
                        ) : f.alertas_abiertas > 0 ? (
                          <span className="insignia insignia-alerta">
                            {f.alertas_abiertas === 1
                              ? "1 alerta"
                              : `${f.alertas_abiertas} alertas`}
                          </span>
                        ) : null}
                        {f.en_propuesta_pendiente !== null ? (
                          <Link
                            to={`/propuestas/${f.en_propuesta_pendiente}`}
                            className="secundario"
                          >
                            {`En propuesta ${f.en_propuesta_pendiente}`}
                          </Link>
                        ) : null}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <Paginacion
            pagina={consulta.data.pagina}
            porPagina={consulta.data.por_pagina}
            total={consulta.data.total}
            singular="factura"
            sustantivo="facturas"
            cambiar={(p) => cambiar("pagina", String(p))}
          />
        </div>
      )}
    </Vista>
  );
}
