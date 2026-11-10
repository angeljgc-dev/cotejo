import { type FormEvent, useId, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router";
import { useEditarProveedor, useProveedor, useProveedores } from "../api/consultas";
import type { ProveedorDetalle as Detalle, ProveedorResumen } from "../api/tipos";
import { Cargando, ErrorAccion, EstadoError, EstadoVacio } from "../componentes/Estados";
import { Importe } from "../componentes/Importe";
import { Paginacion } from "../componentes/Paginacion";
import { Vista } from "../componentes/Vista";

function Situacion({ p }: { p: ProveedorResumen }) {
  return (
    <div className="acciones">
      {p.situacion_69b ? (
        <span className="insignia insignia-bloqueante">{`69-B: ${p.situacion_69b}`}</span>
      ) : null}
      {!p.rfc_valido ? <span className="insignia insignia-alerta">RFC inválido</span> : null}
      {!p.situacion_69b && p.rfc_valido ? (
        <span className="secundario">Sin observaciones</span>
      ) : null}
    </div>
  );
}

export function Proveedores() {
  const [params, setParams] = useSearchParams();
  const texto = params.get("texto") ?? "";
  const pagina = Math.max(1, Number(params.get("pagina")) || 1);
  const consulta = useProveedores({ texto: texto || undefined, pagina });
  const id = useId();

  function buscar(valor: string) {
    const siguientes = new URLSearchParams();
    if (valor) siguientes.set("texto", valor);
    setParams(siguientes, { replace: true });
  }

  return (
    <Vista
      titulo="Proveedores"
      descripcion="Se crean solos al cargar su primera factura, identificados por RFC."
    >
      <search>
        <form
          className="filtros"
          onSubmit={(e) => e.preventDefault()}
          aria-label="Buscar proveedores"
        >
          <label className="campo" htmlFor={`${id}-texto`}>
            Buscar por nombre o RFC
            <input
              id={`${id}-texto`}
              className="entrada"
              type="search"
              defaultValue={texto}
              onChange={(e) => buscar(e.target.value.trim())}
            />
          </label>
        </form>
      </search>
      {consulta.isPending ? (
        <Cargando texto="Cargando proveedores" />
      ) : consulta.isError ? (
        <EstadoError
          titulo="No pudimos cargar los proveedores"
          error={consulta.error}
          reintentar={() => void consulta.refetch()}
        />
      ) : consulta.data.elementos.length === 0 ? (
        texto ? (
          <EstadoVacio titulo={`Ningún proveedor coincide con "${texto}"`}>
            Revisa la ortografía o busca por las primeras letras del RFC.
          </EstadoVacio>
        ) : (
          <EstadoVacio
            titulo="Todavía no hay proveedores"
            accion={
              <Link className="boton" to="/facturas/cargar">
                Cargar CFDI
              </Link>
            }
          >
            Cada proveedor aparece aquí en cuanto se carga una factura suya.
          </EstadoVacio>
        )
      ) : (
        <div className="panel">
          <table className="tabla tabla-apilable">
            <caption className="solo-lectores">Proveedores</caption>
            <thead>
              <tr>
                <th scope="col">Proveedor</th>
                <th scope="col">RFC</th>
                <th scope="col" className="num">
                  Días de crédito
                </th>
                <th scope="col" className="num">
                  Facturas con saldo
                </th>
                <th scope="col" className="num">
                  Adeudo MXN
                </th>
                <th scope="col">Situación</th>
              </tr>
            </thead>
            <tbody>
              {consulta.data.elementos.map((p) => (
                <tr key={p.id}>
                  <td data-columna="Proveedor">
                    <Link to={`/proveedores/${p.id}`}>{p.nombre}</Link>
                  </td>
                  <td data-columna="RFC" className="uuid">
                    {p.rfc}
                  </td>
                  <td data-columna="Días de crédito" className="num">
                    {p.dias_credito}
                  </td>
                  <td data-columna="Facturas con saldo" className="num">
                    {p.facturas_con_saldo}
                  </td>
                  <td data-columna="Adeudo MXN" className="num">
                    <Importe valor={p.adeudo_mxn} />
                  </td>
                  <td data-columna="Situación">
                    <Situacion p={p} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <Paginacion
            pagina={consulta.data.pagina}
            porPagina={consulta.data.por_pagina}
            total={consulta.data.total}
            singular="proveedor"
            sustantivo="proveedores"
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

function EditarCredito({ p }: { p: Detalle }) {
  const editar = useEditarProveedor(p.id);
  const [valor, setValor] = useState(String(p.dias_credito));
  const [intentado, setIntentado] = useState(false);
  const [guardado, setGuardado] = useState(false);
  const id = useId();
  const valido = /^\d{1,3}$/.test(valor) && Number(valor) <= 365;

  function enviar(e: FormEvent) {
    e.preventDefault();
    setIntentado(true);
    setGuardado(false);
    if (!valido) return;
    editar.mutate(Number(valor), { onSuccess: () => setGuardado(true) });
  }

  return (
    <form onSubmit={enviar} className="formulario-chat">
      <label className="campo" htmlFor={id}>
        Días de crédito
        <span className="campo-ayuda">
          El vencimiento de cada factura es su fecha de emisión más estos días.
        </span>
      </label>
      <div className="acciones">
        <input
          id={id}
          className="entrada entrada-corta"
          inputMode="numeric"
          value={valor}
          onChange={(e) => setValor(e.target.value.trim())}
          aria-invalid={intentado && !valido}
          aria-describedby={intentado && !valido ? `${id}-error` : undefined}
        />
        <button type="submit" className="boton" disabled={editar.isPending}>
          Guardar días de crédito
        </button>
      </div>
      {intentado && !valido ? (
        <span id={`${id}-error`} className="campo-error">
          Escribe un número entero de 0 a 365.
        </span>
      ) : null}
      <ErrorAccion error={editar.error} />
      <p role="status" className="secundario">
        {guardado ? "Días de crédito guardados. Los vencimientos se recalcularon." : ""}
      </p>
    </form>
  );
}

export function ProveedorDetalle() {
  const { id } = useParams();
  const consulta = useProveedor(Number(id));
  if (consulta.isPending) {
    return (
      <Vista titulo="Proveedor" migas={<Link to="/proveedores">Proveedores</Link>}>
        <Cargando texto="Cargando el proveedor" />
      </Vista>
    );
  }
  if (consulta.isError) {
    return (
      <Vista titulo="Proveedor" migas={<Link to="/proveedores">Proveedores</Link>}>
        <EstadoError titulo="No pudimos abrir este proveedor" error={consulta.error} />
      </Vista>
    );
  }
  const p = consulta.data;
  return (
    <Vista
      titulo={p.nombre}
      migas={<Link to="/proveedores">Proveedores</Link>}
      descripcion={`RFC ${p.rfc}`}
      acciones={
        <Link className="boton" to={`/facturas?proveedor_id=${p.id}`}>
          Ver sus facturas
        </Link>
      }
    >
      {p.situacion_69b ? (
        <div className="mensaje mensaje-bloqueante" role="note">
          <p>
            <strong>{`Lista 69-B del SAT: ${p.situacion_69b}.`}</strong> Sus facturas quedan
            bloqueadas y no pueden entrar en una propuesta de pago.
          </p>
        </div>
      ) : null}
      <section className="panel" aria-labelledby="titulo-adeudo-proveedor">
        <h2 id="titulo-adeudo-proveedor">Adeudo</h2>
        <p className="cifra-grande">
          <Importe valor={p.adeudo_mxn} />
        </p>
        <p className="secundario">{`${p.facturas_con_saldo} facturas con saldo, en pesos.`}</p>
        {p.adeudo_por_moneda.length > 0 ? (
          <table className="tabla">
            <caption className="solo-lectores">Adeudo por moneda</caption>
            <thead>
              <tr>
                <th scope="col">Moneda</th>
                <th scope="col" className="num">
                  Saldo
                </th>
                <th scope="col" className="num">
                  Equivalente MXN
                </th>
              </tr>
            </thead>
            <tbody>
              {p.adeudo_por_moneda.map((m) => (
                <tr key={m.moneda}>
                  <th scope="row">{m.moneda}</th>
                  <td className="num">
                    <Importe valor={m.saldo} moneda={m.moneda} />
                  </td>
                  <td className="num">
                    <Importe valor={m.saldo_mxn} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : null}
      </section>
      <section className="panel" aria-labelledby="titulo-condiciones">
        <h2 id="titulo-condiciones">Condiciones</h2>
        <Situacion p={p} />
        <EditarCredito key={p.dias_credito} p={p} />
      </section>
      <section className="panel" aria-labelledby="titulo-docs-proveedor">
        <h2 id="titulo-docs-proveedor">Contratos y documentos</h2>
        {p.documentos.length === 0 ? (
          <p className="secundario">
            {"Sin documentos ligados. "}
            <Link to="/documentos">Sube su contrato</Link>
            {" para que el asistente pueda citar sus condiciones."}
          </p>
        ) : (
          <ul>
            {p.documentos.map((d) => (
              <li key={d.id}>
                {d.nombre}
                {d.estado === "sin_texto" ? (
                  <span className="insignia insignia-alerta">Sin texto</span>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </section>
    </Vista>
  );
}
