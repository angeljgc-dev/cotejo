import { type FormEvent, useState } from "react";
import { Link, useParams } from "react-router";
import { urlXmlFactura } from "../api/cliente";
import { useFactura, useResolverAlerta } from "../api/consultas";
import { useUsuario } from "../api/contexto";
import type { Alerta, FacturaDetalle as Detalle } from "../api/tipos";
import { Cargando, ErrorAccion, EstadoError } from "../componentes/Estados";
import { Importe, ImporteConEquivalente } from "../componentes/Importe";
import { InsigniaPago, InsigniaSeveridad, nombreFactura } from "../componentes/Insignias";
import { Vista } from "../componentes/Vista";
import { formatearFecha, formatearFechaHora, textoVencimiento } from "../utilidades/fechas";

const ORIGEN_APLICACION: Record<string, string> = {
  pago_aprobado: "Pago aprobado en Cotejo",
  complemento_pago: "Complemento de pago (CFDI tipo P)",
  nota_credito: "Nota de crédito (CFDI tipo E)",
};

function ResolverAlerta({ alerta }: { alerta: Alerta }) {
  const resolver = useResolverAlerta();
  const [abierto, setAbierto] = useState(false);
  const [nota, setNota] = useState("");
  const [intentado, setIntentado] = useState(false);
  const notaValida = nota.trim().length >= 5 && nota.trim().length <= 500;
  const idNota = `nota-${alerta.id}`;

  function enviar(e: FormEvent) {
    e.preventDefault();
    setIntentado(true);
    if (!notaValida) return;
    resolver.mutate({ id: alerta.id, nota: nota.trim() });
  }

  if (!abierto) {
    return (
      <div>
        <button type="button" className="boton" onClick={() => setAbierto(true)}>
          Resolver alerta
        </button>
      </div>
    );
  }
  return (
    <form onSubmit={enviar} className="formulario-chat">
      <label className="campo" htmlFor={idNota}>
        Nota de resolución
        <span className="campo-ayuda">
          Explica por qué la alerta ya no aplica. Queda en la bitácora; la factura no cambia.
        </span>
      </label>
      <textarea
        id={idNota}
        className="area-texto"
        value={nota}
        onChange={(e) => setNota(e.target.value)}
        aria-invalid={intentado && !notaValida}
        aria-describedby={intentado && !notaValida ? `${idNota}-error` : undefined}
        maxLength={500}
      />
      {intentado && !notaValida ? (
        <span id={`${idNota}-error`} className="campo-error">
          Escribe entre 5 y 500 caracteres.
        </span>
      ) : null}
      <ErrorAccion error={resolver.error} />
      <div className="acciones">
        <button type="submit" className="boton boton-primario" disabled={resolver.isPending}>
          Marcar como resuelta
        </button>
        <button type="button" className="boton" onClick={() => setAbierto(false)}>
          Cancelar
        </button>
      </div>
    </form>
  );
}

function Alertas({ f }: { f: Detalle }) {
  const usuario = useUsuario();
  if (f.alertas.length === 0) {
    return (
      <section className="panel" aria-labelledby="titulo-alertas">
        <h2 id="titulo-alertas">Alertas</h2>
        <p className="secundario">Esta factura pasó todas las validaciones sin alertas.</p>
      </section>
    );
  }
  return (
    <section className="panel" aria-labelledby="titulo-alertas">
      <h2 id="titulo-alertas">Alertas</h2>
      <ul className="lista-alertas">
        {f.alertas.map((a) => (
          <li
            key={a.id}
            className={`mensaje ${
              a.estado === "resuelta"
                ? ""
                : a.severidad === "bloqueante"
                  ? "mensaje-bloqueante"
                  : "mensaje-alerta"
            }`}
          >
            <div className="acciones">
              {a.estado === "resuelta" ? (
                <span className="insignia insignia-exito">Resuelta</span>
              ) : (
                <InsigniaSeveridad severidad={a.severidad} />
              )}
              <strong>{a.mensaje}</strong>
            </div>
            {a.factura_relacionada_id !== null ? (
              <p>
                <Link to={`/facturas/${a.factura_relacionada_id}`}>
                  Abrir la otra factura para compararlas
                </Link>
              </p>
            ) : null}
            {a.estado === "resuelta" ? (
              <p className="secundario">
                {`Resuelta por ${a.resuelta_por?.nombre ?? "alguien"}${
                  a.resuelta_en ? ` el ${formatearFechaHora(a.resuelta_en)}` : ""
                }: ${a.nota_resolucion ?? ""}`}
              </p>
            ) : usuario.rol === "aprobador" ? (
              <ResolverAlerta alerta={a} />
            ) : null}
          </li>
        ))}
      </ul>
    </section>
  );
}

export function FacturaDetalle() {
  const { id } = useParams();
  const facturaId = Number(id);
  const consulta = useFactura(facturaId);

  if (consulta.isPending) {
    return (
      <Vista titulo="Factura">
        <Cargando texto="Cargando la factura" />
      </Vista>
    );
  }
  if (consulta.isError) {
    return (
      <Vista titulo="Factura" migas={<Link to="/facturas">Facturas</Link>}>
        <EstadoError
          titulo="No pudimos abrir esta factura"
          error={consulta.error}
          reintentar={consulta.error.estado === 404 ? undefined : () => void consulta.refetch()}
        />
      </Vista>
    );
  }
  const f = consulta.data;
  const mxn = f.moneda === "MXN";

  return (
    <Vista
      titulo={`Factura ${nombreFactura(f)}`}
      migas={<Link to="/facturas">Facturas</Link>}
      descripcion={`${f.proveedor.nombre}, emitida el ${formatearFecha(f.fecha_emision)}`}
      acciones={
        <a className="boton" href={urlXmlFactura(f.id)} download>
          Descargar XML
        </a>
      }
    >
      {f.tiene_bloqueante ? (
        <div className="mensaje mensaje-bloqueante" role="note">
          <p>
            <strong>Bloqueada para pago.</strong> No puede entrar en una propuesta mientras tenga
            una alerta bloqueante abierta.
          </p>
        </div>
      ) : null}

      <section className="panel" aria-labelledby="titulo-saldo">
        <div className="panel-titulo">
          <h2 id="titulo-saldo">Saldo</h2>
          <InsigniaPago estado={f.estado_pago} />
        </div>
        <p className="cifra-grande">
          <Importe valor={f.saldo} moneda={f.moneda} />
        </p>
        {!mxn ? (
          <p className="secundario">
            {"Equivale a "}
            <Importe valor={f.saldo_mxn} codigo />
            {f.tipo_cambio ? ` con el tipo de cambio del comprobante, ${f.tipo_cambio}.` : "."}
          </p>
        ) : null}
        <dl className="datos">
          <div>
            <dt>Vencimiento</dt>
            <dd>
              {f.vencimiento ? formatearFecha(f.vencimiento) : "Sin fecha"}
              {f.estado_pago !== "pagada"
                ? ` (${textoVencimiento(f.dias_vencido).toLowerCase()})`
                : ""}
            </dd>
          </div>
          <div>
            <dt>Método y forma de pago</dt>
            <dd>{`${f.metodo_pago ?? "Sin método"}, forma ${f.forma_pago ?? "sin especificar"}`}</dd>
          </div>
          {f.en_propuesta_pendiente !== null ? (
            <div>
              <dt>Propuesta</dt>
              <dd>
                <Link to={`/propuestas/${f.en_propuesta_pendiente}`}>
                  {`En la propuesta ${f.en_propuesta_pendiente}, pendiente de aprobar`}
                </Link>
              </dd>
            </div>
          ) : null}
        </dl>
      </section>

      <Alertas f={f} />

      <section className="panel" aria-labelledby="titulo-comprobante">
        <h2 id="titulo-comprobante">Comprobante</h2>
        <dl className="datos">
          <div>
            <dt>Emisor</dt>
            <dd>
              <Link to={`/proveedores/${f.proveedor.id}`}>{f.proveedor.nombre}</Link>
              <span className="uuid bloque">{f.proveedor.rfc}</span>
            </dd>
          </div>
          <div>
            <dt>Receptor</dt>
            <dd>
              {f.receptor.nombre}
              <span className="uuid bloque">{`${f.receptor.rfc}, uso ${f.receptor.uso_cfdi}`}</span>
            </dd>
          </div>
          <div>
            <dt>Folio fiscal (UUID)</dt>
            <dd className="uuid">{f.uuid}</dd>
          </div>
          <div>
            <dt>Versión y tipo</dt>
            <dd>{`CFDI ${f.version}, tipo ${f.tipo}`}</dd>
          </div>
          <div>
            <dt>Timbrado</dt>
            <dd>{formatearFechaHora(f.fecha_timbrado)}</dd>
          </div>
          <div>
            <dt>Lugar de expedición</dt>
            <dd>{`C.P. ${f.lugar_expedicion}`}</dd>
          </div>
        </dl>
        <dl className="cuadre" aria-label="Cuadre de importes">
          <dt>Subtotal</dt>
          <dd>
            <Importe valor={f.subtotal} moneda={f.moneda} />
          </dd>
          {f.descuento ? (
            <>
              <dt>Descuento</dt>
              <dd>
                <Importe valor={f.descuento} moneda={f.moneda} />
              </dd>
            </>
          ) : null}
          {f.total_impuestos_trasladados ? (
            <>
              <dt>Impuestos trasladados</dt>
              <dd>
                <Importe valor={f.total_impuestos_trasladados} moneda={f.moneda} />
              </dd>
            </>
          ) : null}
          {f.total_impuestos_retenidos ? (
            <>
              <dt>Impuestos retenidos</dt>
              <dd>
                <Importe valor={f.total_impuestos_retenidos} moneda={f.moneda} />
              </dd>
            </>
          ) : null}
          <dt className="total">Total</dt>
          <dd className="total">
            <ImporteConEquivalente
              valor={f.total}
              valorMxn={f.total_mxn}
              moneda={f.moneda}
              tipoCambio={f.tipo_cambio}
            />
          </dd>
        </dl>
      </section>

      <section className="panel" aria-labelledby="titulo-conceptos">
        <h2 id="titulo-conceptos">Conceptos</h2>
        <table className="tabla tabla-apilable">
          <caption className="solo-lectores">Conceptos del comprobante</caption>
          <thead>
            <tr>
              <th scope="col">Descripción</th>
              <th scope="col">Clave</th>
              <th scope="col" className="num">
                Cantidad
              </th>
              <th scope="col" className="num">
                Valor unitario
              </th>
              <th scope="col" className="num">
                Importe
              </th>
            </tr>
          </thead>
          <tbody>
            {f.conceptos.map((c) => (
              <tr key={c.orden}>
                <td data-columna="Descripción">{c.descripcion}</td>
                <td data-columna="Clave">{`${c.clave_prod_serv} (${c.clave_unidad})`}</td>
                <td data-columna="Cantidad" className="num">
                  {c.cantidad}
                </td>
                <td data-columna="Valor unitario" className="num">
                  <Importe valor={c.valor_unitario} moneda={f.moneda} />
                </td>
                <td data-columna="Importe" className="num">
                  <Importe valor={c.importe} moneda={f.moneda} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="panel" aria-labelledby="titulo-aplicaciones">
        <h2 id="titulo-aplicaciones">Pagos y notas de crédito</h2>
        {f.aplicaciones.length === 0 ? (
          <p className="secundario">
            Sin pagos ni notas de crédito aplicados. El saldo es igual al total.
          </p>
        ) : (
          <table className="tabla tabla-apilable">
            <caption className="solo-lectores">Aplicaciones al saldo</caption>
            <thead>
              <tr>
                <th scope="col">Fecha</th>
                <th scope="col">Origen</th>
                <th scope="col" className="num">
                  Importe aplicado
                </th>
              </tr>
            </thead>
            <tbody>
              {f.aplicaciones.map((a) => (
                <tr key={a.id}>
                  <td data-columna="Fecha">{formatearFecha(a.fecha)}</td>
                  <td data-columna="Origen">
                    {ORIGEN_APLICACION[a.origen] ?? a.origen}
                    {a.num_parcialidad !== null ? `, parcialidad ${a.num_parcialidad}` : ""}
                    {a.propuesta_id !== null ? (
                      <Link className="bloque" to={`/propuestas/${a.propuesta_id}`}>
                        {`Propuesta ${a.propuesta_id}`}
                      </Link>
                    ) : null}
                    {a.origen_factura_id !== null ? (
                      <Link className="bloque" to={`/facturas/${a.origen_factura_id}`}>
                        Ver el CFDI que lo aplicó
                      </Link>
                    ) : null}
                  </td>
                  <td data-columna="Importe aplicado" className="num">
                    <Importe valor={a.importe} moneda={f.moneda} />
                    {a.importe !== a.importe_solicitado ? (
                      <span className="secundario bloque">
                        {"De "}
                        <Importe valor={a.importe_solicitado} moneda={f.moneda} />
                        {" solicitados"}
                      </span>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      {f.relacionados.length > 0 ? (
        <section className="panel" aria-labelledby="titulo-relacionados">
          <h2 id="titulo-relacionados">CFDI relacionados</h2>
          <ul>
            {f.relacionados.map((r) => (
              <li key={r.uuid}>
                {r.factura_id !== null ? (
                  <Link to={`/facturas/${r.factura_id}`}>{r.uuid}</Link>
                ) : (
                  <span className="uuid">{`${r.uuid} (no cargado)`}</span>
                )}
                {` tipo de relación ${r.tipo_relacion}`}
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      <p className="secundario">
        {`Cargada por ${f.carga.usuario.nombre} el ${formatearFechaHora(f.carga.creado_en)}, carga ${f.carga.id}.`}
      </p>
    </Vista>
  );
}
