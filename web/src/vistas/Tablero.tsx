import { Link } from "react-router";
import { useTablero } from "../api/consultas";
import type { Tablero as DatosTablero } from "../api/tipos";
import { Cargando, EstadoError, EstadoVacio } from "../componentes/Estados";
import { Importe } from "../componentes/Importe";
import { Vista } from "../componentes/Vista";
import { formatearFecha } from "../utilidades/fechas";
import { formatearImporte, proporcionMilesimas } from "../utilidades/importes";

const RUTA_GRUPO: Record<DatosTablero["antiguedad"][number]["grupo"], string> = {
  por_vencer: "/facturas?estado=por_vencer",
  "1_30": "/facturas?estado=vencida",
  "31_60": "/facturas?estado=vencida",
  "61_90": "/facturas?estado=vencida",
  mas_90: "/facturas?estado=vencida",
};

function plural(n: number, uno: string, varios: string) {
  return `${n} ${n === 1 ? uno : varios}`;
}

function Antiguedad({ t }: { t: DatosTablero }) {
  return (
    <section className="panel" aria-labelledby="titulo-antiguedad">
      <div className="panel-titulo">
        <h2 id="titulo-antiguedad">Antigüedad de saldos</h2>
        <span className="secundario">Días vencidos al corte</span>
      </div>
      <div className="cinta" aria-hidden="true">
        {t.antiguedad.map((g) => {
          const milesimas = proporcionMilesimas(g.saldo_mxn, t.adeudo_total_mxn);
          if (milesimas === 0) return null;
          return (
            <span
              key={g.grupo}
              className="cinta-tramo"
              data-grupo={g.grupo}
              style={{ flexGrow: milesimas }}
              title={`${g.etiqueta}: ${formatearImporte(g.saldo_mxn)}`}
            />
          );
        })}
      </div>
      <div className="tabla-contenedor">
        <table className="tabla">
          <caption className="solo-lectores">Antigüedad de saldos en pesos</caption>
          <thead>
            <tr>
              <th scope="col">Grupo</th>
              <th scope="col" className="num">
                Facturas
              </th>
              <th scope="col" className="num">
                Saldo MXN
              </th>
            </tr>
          </thead>
          <tbody>
            {t.antiguedad.map((g) => (
              <tr key={g.grupo}>
                <th scope="row">
                  <span className="muestra" data-grupo={g.grupo} aria-hidden="true" />
                  {g.facturas > 0 ? <Link to={RUTA_GRUPO[g.grupo]}>{g.etiqueta}</Link> : g.etiqueta}
                </th>
                <td className="num">{g.facturas}</td>
                <td className="num">
                  <Importe valor={g.saldo_mxn} />
                </td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr>
              <th scope="row">Total</th>
              <td className="num">{t.antiguedad.reduce((n, g) => n + g.facturas, 0)}</td>
              <td className="num">
                <Importe valor={t.adeudo_total_mxn} />
              </td>
            </tr>
          </tfoot>
        </table>
      </div>
    </section>
  );
}

function PorProveedor({ t }: { t: DatosTablero }) {
  const mayor = t.por_proveedor[0]?.saldo_mxn ?? "0";
  return (
    <section className="panel" aria-labelledby="titulo-proveedores">
      <div className="panel-titulo">
        <h2 id="titulo-proveedores">Adeudo por proveedor</h2>
        <Link to="/proveedores">Ver todos</Link>
      </div>
      <table className="tabla">
        <caption className="solo-lectores">Proveedores con mayor adeudo</caption>
        <thead>
          <tr>
            <th scope="col">Proveedor</th>
            <th scope="col" className="num">
              Saldo MXN
            </th>
          </tr>
        </thead>
        <tbody>
          {t.por_proveedor.map((p) => (
            <tr key={p.proveedor.id}>
              <td>
                <Link to={`/proveedores/${p.proveedor.id}`}>{p.proveedor.nombre}</Link>
                <span className="secundario bloque">
                  {plural(p.facturas, "factura", "facturas")}
                </span>
                <div className="barra-proveedor" aria-hidden="true">
                  <span style={{ width: `${proporcionMilesimas(p.saldo_mxn, mayor) / 10}%` }} />
                </div>
              </td>
              <td className="num">
                <Importe valor={p.saldo_mxn} />
              </td>
            </tr>
          ))}
          {t.otros_proveedores.proveedores > 0 ? (
            <tr>
              <td>{`Otros ${plural(t.otros_proveedores.proveedores, "proveedor", "proveedores")}`}</td>
              <td className="num">
                <Importe valor={t.otros_proveedores.saldo_mxn} />
              </td>
            </tr>
          ) : null}
        </tbody>
      </table>
    </section>
  );
}

export function Tablero() {
  const consulta = useTablero();

  if (consulta.isPending) {
    return (
      <Vista titulo="Tablero">
        <Cargando texto="Calculando adeudos y vencimientos" />
      </Vista>
    );
  }
  if (consulta.isError) {
    return (
      <Vista titulo="Tablero">
        <EstadoError
          titulo="No pudimos calcular el tablero"
          error={consulta.error}
          reintentar={() => void consulta.refetch()}
        />
      </Vista>
    );
  }

  const t = consulta.data;
  const sinAdeudo = t.por_proveedor.length === 0 && t.antiguedad.every((g) => g.facturas === 0);

  return (
    <Vista titulo="Tablero" descripcion={`Saldos al ${formatearFecha(t.fecha_corte)}, en pesos.`}>
      {sinAdeudo ? (
        <EstadoVacio
          titulo="No hay saldos por pagar"
          accion={
            <Link className="boton boton-primario" to="/facturas/cargar">
              Cargar facturas CFDI
            </Link>
          }
        >
          Cuando cargues facturas con saldo pendiente, aquí verás cuánto debes, a quién y qué vence
          primero.
        </EstadoVacio>
      ) : (
        <>
          <div className="tablero-cabeza">
            <section className="panel" aria-labelledby="titulo-adeudo">
              <h2 id="titulo-adeudo" className="secundario">
                Adeudo total
              </h2>
              <p className="cifra-grande">
                <Importe valor={t.adeudo_total_mxn} />
              </p>
              {t.adeudo_por_moneda.length > 1 ? (
                <ul className="secundario">
                  {t.adeudo_por_moneda.map((m) => (
                    <li key={m.moneda}>
                      {m.moneda === "MXN" ? (
                        <>
                          <Importe valor={m.saldo} /> en pesos
                        </>
                      ) : (
                        <>
                          <Importe valor={m.saldo} moneda={m.moneda} /> equivalen a{" "}
                          <Importe valor={m.saldo_mxn} codigo />
                        </>
                      )}
                    </li>
                  ))}
                </ul>
              ) : null}
              <dl className="cifras">
                <div>
                  <dt>Vence en 7 días</dt>
                  <dd>
                    <Importe valor={t.vencen_7_dias.saldo_mxn} />
                    <small>{plural(t.vencen_7_dias.facturas, "factura", "facturas")}</small>
                  </dd>
                </div>
                <div>
                  <dt>Vence en 30 días</dt>
                  <dd>
                    <Importe valor={t.vencen_30_dias.saldo_mxn} />
                    <small>{plural(t.vencen_30_dias.facturas, "factura", "facturas")}</small>
                  </dd>
                </div>
              </dl>
            </section>
            <section className="panel" aria-labelledby="titulo-atencion">
              <h2 id="titulo-atencion">Requiere atención</h2>
              <dl className="cifras">
                <div>
                  <dt>Facturas con alertas</dt>
                  <dd>
                    <Link to="/facturas?con_alertas=true">{t.facturas_con_alertas}</Link>
                  </dd>
                </div>
                <div>
                  <dt>Bloqueadas para pago</dt>
                  <dd>
                    <Link to="/facturas?severidad=bloqueante">{t.facturas_bloqueadas}</Link>
                  </dd>
                </div>
                <div>
                  <dt>Propuestas por aprobar</dt>
                  <dd>
                    <Link to="/propuestas?estado=pendiente">{t.propuestas_pendientes}</Link>
                  </dd>
                </div>
              </dl>
            </section>
          </div>
          <Antiguedad t={t} />
          <PorProveedor t={t} />
        </>
      )}
    </Vista>
  );
}
