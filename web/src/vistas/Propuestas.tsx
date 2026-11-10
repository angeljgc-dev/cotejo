import { type FormEvent, useId, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";
import {
  useCrearPropuesta,
  useDecidirPropuesta,
  usePropuesta,
  usePropuestas,
} from "../api/consultas";
import { useUsuario } from "../api/contexto";
import type { EstadoPropuesta, Horizonte, Propuesta } from "../api/tipos";
import { Cargando, ErrorAccion, EstadoError, EstadoVacio } from "../componentes/Estados";
import { Importe } from "../componentes/Importe";
import { InsigniaPropuesta, nombreFactura } from "../componentes/Insignias";
import { Paginacion } from "../componentes/Paginacion";
import { Vista } from "../componentes/Vista";
import { formatearFecha, formatearFechaHora } from "../utilidades/fechas";
import { normalizarImporteCapturado } from "../utilidades/importes";

const FILTROS: { valor: EstadoPropuesta | ""; texto: string }[] = [
  { valor: "", texto: "Todas" },
  { valor: "pendiente", texto: "Pendientes" },
  { valor: "aprobada", texto: "Aprobadas" },
  { valor: "rechazada", texto: "Rechazadas" },
];

const HORIZONTES: { valor: Horizonte; texto: string }[] = [
  { valor: "esta_semana", texto: "Esta semana" },
  { valor: "proximos_7_dias", texto: "Próximos 7 días" },
  { valor: "proximos_30_dias", texto: "Próximos 30 días" },
  { valor: "vencidas", texto: "Solo vencidas" },
];

function NuevaPropuesta() {
  const crear = useCrearPropuesta();
  const navegar = useNavigate();
  const [abierto, setAbierto] = useState(false);
  const [presupuesto, setPresupuesto] = useState("");
  const [horizonte, setHorizonte] = useState<Horizonte>("esta_semana");
  const [intentado, setIntentado] = useState(false);
  const id = useId();
  const normalizado = normalizarImporteCapturado(presupuesto);

  function enviar(e: FormEvent) {
    e.preventDefault();
    setIntentado(true);
    if (!normalizado) return;
    crear.mutate(
      { presupuesto_mxn: normalizado, horizonte, fecha_limite: null, factura_ids: null },
      { onSuccess: (p) => navegar(`/propuestas/${p.id}`) },
    );
  }

  if (!abierto) {
    return (
      <button type="button" className="boton boton-primario" onClick={() => setAbierto(true)}>
        Nueva propuesta
      </button>
    );
  }
  return (
    <section className="panel" aria-labelledby={`${id}-titulo`}>
      <h2 id={`${id}-titulo`}>Nueva propuesta de pago</h2>
      <p className="secundario">
        Cotejo elige las facturas por vencimiento sin pasar del presupuesto y deja fuera las que
        tienen una alerta bloqueante. La propuesta queda pendiente hasta que tesorería la apruebe.
      </p>
      <form onSubmit={enviar} className="filtros">
        <label className="campo" htmlFor={`${id}-presupuesto`}>
          Presupuesto en pesos
          <input
            id={`${id}-presupuesto`}
            className="entrada"
            inputMode="decimal"
            placeholder="150,000.00"
            value={presupuesto}
            onChange={(e) => setPresupuesto(e.target.value)}
            aria-invalid={intentado && !normalizado}
            aria-describedby={intentado && !normalizado ? `${id}-error` : undefined}
          />
          {intentado && !normalizado ? (
            <span id={`${id}-error`} className="campo-error">
              Escribe un importe mayor a cero, con hasta dos decimales.
            </span>
          ) : null}
        </label>
        <label className="campo" htmlFor={`${id}-horizonte`}>
          Facturas que vencen
          <select
            id={`${id}-horizonte`}
            className="selector"
            value={horizonte}
            onChange={(e) => setHorizonte(e.target.value as Horizonte)}
          >
            {HORIZONTES.map((h) => (
              <option key={h.valor} value={h.valor}>
                {h.texto}
              </option>
            ))}
          </select>
        </label>
        <div className="acciones">
          <button type="submit" className="boton boton-primario" disabled={crear.isPending}>
            {crear.isPending ? "Armando propuesta" : "Crear propuesta"}
          </button>
          <button type="button" className="boton" onClick={() => setAbierto(false)}>
            Cancelar
          </button>
        </div>
      </form>
      <ErrorAccion error={crear.error} />
    </section>
  );
}

export function Propuestas() {
  const usuario = useUsuario();
  const [params, setParams] = useSearchParams();
  const estadoParam = params.get("estado");
  const estado = FILTROS.find((f) => f.valor === estadoParam)?.valor || undefined;
  const pagina = Math.max(1, Number(params.get("pagina")) || 1);
  const consulta = usePropuestas({ estado, pagina });
  const id = useId();

  return (
    <Vista
      titulo="Propuestas de pago"
      descripcion={
        usuario.rol === "aprobador"
          ? "Revisa cada propuesta y apruébala o recházala. Aprobar registra los pagos y actualiza los saldos."
          : "Cotejo propone qué pagar; tesorería decide. Ninguna propuesta mueve dinero por sí sola."
      }
      acciones={usuario.rol === "capturista" ? <NuevaPropuesta /> : null}
    >
      <div className="filtros">
        <label className="campo" htmlFor={`${id}-estado`}>
          Mostrar
          <select
            id={`${id}-estado`}
            className="selector"
            value={estado ?? ""}
            onChange={(e) =>
              setParams(
                e.target.value
                  ? new URLSearchParams({ estado: e.target.value })
                  : new URLSearchParams(),
              )
            }
          >
            {FILTROS.map((f) => (
              <option key={f.valor} value={f.valor}>
                {f.texto}
              </option>
            ))}
          </select>
        </label>
      </div>
      {consulta.isPending ? (
        <Cargando texto="Cargando propuestas" />
      ) : consulta.isError ? (
        <EstadoError
          titulo="No pudimos cargar las propuestas"
          error={consulta.error}
          reintentar={() => void consulta.refetch()}
        />
      ) : consulta.data.elementos.length === 0 ? (
        <EstadoVacio
          titulo={estado ? "No hay propuestas con ese estado" : "Todavía no hay propuestas"}
          accion={
            usuario.rol === "capturista" ? (
              <Link className="boton" to="/asistente">
                Pedir una al asistente
              </Link>
            ) : null
          }
        >
          {usuario.rol === "capturista"
            ? 'Crea una con el botón Nueva propuesta o pídela en el asistente: "Propón los pagos de esta semana con presupuesto de 300 mil".'
            : "Cuando el capturista prepare una propuesta de pago, aparecerá aquí para que la apruebes o la rechaces."}
        </EstadoVacio>
      ) : (
        <div className="panel">
          <table className="tabla tabla-apilable">
            <caption className="solo-lectores">Propuestas de pago</caption>
            <thead>
              <tr>
                <th scope="col">Propuesta</th>
                <th scope="col">Estado</th>
                <th scope="col" className="num">
                  Facturas
                </th>
                <th scope="col" className="num">
                  Total
                </th>
                <th scope="col" className="num">
                  Presupuesto
                </th>
                <th scope="col">Creada</th>
              </tr>
            </thead>
            <tbody>
              {consulta.data.elementos.map((p) => (
                <tr key={p.id}>
                  <td data-columna="Propuesta">
                    <Link to={`/propuestas/${p.id}`}>{`Propuesta ${p.id}`}</Link>
                  </td>
                  <td data-columna="Estado">
                    <InsigniaPropuesta estado={p.estado} />
                    {p.decidida_por ? (
                      <span className="secundario bloque">{`por ${p.decidida_por.nombre}`}</span>
                    ) : null}
                  </td>
                  <td data-columna="Facturas" className="num">
                    {p.renglones}
                  </td>
                  <td data-columna="Total" className="num">
                    <Importe valor={p.total_mxn} />
                  </td>
                  <td data-columna="Presupuesto" className="num">
                    <Importe valor={p.presupuesto_mxn} />
                  </td>
                  <td data-columna="Creada">
                    {formatearFechaHora(p.creado_en)}
                    <span className="secundario bloque">{p.creada_por.nombre}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <Paginacion
            pagina={consulta.data.pagina}
            porPagina={consulta.data.por_pagina}
            total={consulta.data.total}
            singular="propuesta"
            sustantivo="propuestas"
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

interface RenglonInvalido {
  renglon_id: number;
  motivo: string;
}

// El contrato describe el detalle de RENGLONES_INVALIDOS como una lista, mientras que el formato
// general de error lo define como objeto. Se aceptan ambas formas.
function renglonesInvalidos(detalle: unknown): RenglonInvalido[] {
  const lista = Array.isArray(detalle)
    ? detalle
    : typeof detalle === "object" && detalle !== null && "renglones" in detalle
      ? (detalle as { renglones: unknown }).renglones
      : [];
  if (!Array.isArray(lista)) return [];
  return lista.filter(
    (r): r is RenglonInvalido =>
      typeof r === "object" && r !== null && "renglon_id" in r && "motivo" in r,
  );
}

/** Aprobar y rechazar aparecen solo si la API dice que este usuario puede decidir (D4). */
function Decision({ p }: { p: Propuesta }) {
  const usuario = useUsuario();
  const decidir = useDecidirPropuesta(p.id);
  const [rechazando, setRechazando] = useState(false);
  const [motivo, setMotivo] = useState("");
  const [intentado, setIntentado] = useState(false);
  const id = useId();
  const motivoValido = motivo.trim().length >= 5 && motivo.trim().length <= 500;

  if (p.estado !== "pendiente") return null;

  if (!p.puede_decidir) {
    const texto =
      usuario.rol !== "aprobador"
        ? "Esta propuesta espera la aprobación de tesorería. Solo el rol aprobador puede aprobarla o rechazarla."
        : "Tú creaste esta propuesta; otra persona con rol aprobador debe decidirla.";
    return (
      <div className="mensaje mensaje-info">
        <p>{texto}</p>
      </div>
    );
  }

  function rechazar(e: FormEvent) {
    e.preventDefault();
    setIntentado(true);
    if (!motivoValido) return;
    decidir.mutate({ accion: "rechazar", motivo: motivo.trim() });
  }

  return (
    <section className="panel" aria-labelledby={`${id}-titulo`}>
      <h2 id={`${id}-titulo`}>Tu decisión</h2>
      <p className="secundario">
        {
          "Al aprobar se registra un pago por cada factura y los saldos bajan en una sola operación. "
        }
        Antes se vuelve a comprobar que ninguna factura tenga una barrera nueva.
      </p>
      {!rechazando ? (
        <div className="acciones">
          <button
            type="button"
            className="boton boton-primario"
            disabled={decidir.isPending}
            onClick={() => decidir.mutate({ accion: "aprobar" })}
          >
            {decidir.isPending
              ? "Registrando pagos"
              : `Aprobar y registrar ${p.renglones.length} pagos`}
          </button>
          <button
            type="button"
            className="boton boton-peligro"
            disabled={decidir.isPending}
            onClick={() => setRechazando(true)}
          >
            Rechazar propuesta
          </button>
        </div>
      ) : (
        <form onSubmit={rechazar} className="formulario-chat">
          <label className="campo" htmlFor={`${id}-motivo`}>
            Motivo del rechazo
            <span className="campo-ayuda">
              Lo verá quien creó la propuesta y queda en la bitácora.
            </span>
          </label>
          <textarea
            id={`${id}-motivo`}
            className="area-texto"
            value={motivo}
            maxLength={500}
            onChange={(e) => setMotivo(e.target.value)}
            aria-invalid={intentado && !motivoValido}
            aria-describedby={intentado && !motivoValido ? `${id}-error` : undefined}
          />
          {intentado && !motivoValido ? (
            <span id={`${id}-error`} className="campo-error">
              Escribe entre 5 y 500 caracteres.
            </span>
          ) : null}
          <div className="acciones">
            <button type="submit" className="boton boton-peligro" disabled={decidir.isPending}>
              Confirmar rechazo
            </button>
            <button type="button" className="boton" onClick={() => setRechazando(false)}>
              Volver
            </button>
          </div>
        </form>
      )}
      <ErrorAccion error={decidir.error} />
      {decidir.error?.codigo === "RENGLONES_INVALIDOS" ? (
        <ul className="motivos">
          {renglonesInvalidos(decidir.error.detalle).map((r) => (
            <li key={r.renglon_id}>{r.motivo}</li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}

export function PropuestaDetalle() {
  const { id } = useParams();
  const consulta = usePropuesta(Number(id));
  if (consulta.isPending) {
    return (
      <Vista titulo="Propuesta" migas={<Link to="/propuestas">Propuestas</Link>}>
        <Cargando texto="Cargando la propuesta" />
      </Vista>
    );
  }
  if (consulta.isError) {
    return (
      <Vista titulo="Propuesta" migas={<Link to="/propuestas">Propuestas</Link>}>
        <EstadoError titulo="No pudimos abrir esta propuesta" error={consulta.error} />
      </Vista>
    );
  }
  const p = consulta.data;
  return (
    <Vista
      titulo={`Propuesta ${p.id}`}
      migas={<Link to="/propuestas">Propuestas</Link>}
      descripcion={`Creada por ${p.creada_por.nombre} el ${formatearFechaHora(p.creado_en)}${
        p.origen === "asistente" ? ", a petición del asistente" : ""
      }.`}
      acciones={<InsigniaPropuesta estado={p.estado} />}
    >
      {p.estado === "aprobada" ? (
        <div className="mensaje mensaje-exito" role="status">
          <p>
            {`Aprobada por ${p.decidida_por?.nombre ?? "tesorería"}${
              p.decidida_en ? ` el ${formatearFechaHora(p.decidida_en)}` : ""
            }. Los pagos quedaron registrados y los saldos se actualizaron.`}
          </p>
        </div>
      ) : null}
      {p.estado === "rechazada" ? (
        <div className="mensaje mensaje-error" role="status">
          <p>
            {`Rechazada por ${p.decidida_por?.nombre ?? "tesorería"}${
              p.decidida_en ? ` el ${formatearFechaHora(p.decidida_en)}` : ""
            }. Motivo: ${p.motivo_rechazo ?? "sin motivo registrado"}`}
          </p>
        </div>
      ) : null}

      <section className="panel" aria-label="Montos de la propuesta">
        <dl className="cifras">
          <div>
            <dt>Total propuesto</dt>
            <dd>
              <Importe valor={p.total_mxn} />
            </dd>
          </div>
          <div>
            <dt>Presupuesto</dt>
            <dd>
              <Importe valor={p.presupuesto_mxn} />
            </dd>
          </div>
          <div>
            <dt>Pagar a más tardar</dt>
            <dd>{p.fecha_limite ? formatearFecha(p.fecha_limite) : "Sin fecha"}</dd>
          </div>
        </dl>
      </section>

      <Decision p={p} />

      <section className="panel" aria-labelledby="titulo-renglones">
        <h2 id="titulo-renglones">Facturas incluidas</h2>
        {p.renglones.length === 0 ? (
          <p className="secundario">Esta propuesta no tiene renglones.</p>
        ) : (
          <table className="tabla tabla-apilable">
            <caption className="solo-lectores">Renglones de la propuesta</caption>
            <thead>
              <tr>
                <th scope="col">Factura</th>
                <th scope="col">Vence</th>
                <th scope="col" className="num">
                  Saldo actual
                </th>
                <th scope="col" className="num">
                  A pagar
                </th>
                <th scope="col">Razón</th>
              </tr>
            </thead>
            <tbody>
              {p.renglones.map((r) => (
                <tr key={r.id}>
                  <td data-columna="Factura">
                    <Link to={`/facturas/${r.factura.id}`}>{nombreFactura(r.factura)}</Link>
                    <span className="secundario bloque">{r.factura.proveedor.nombre}</span>
                  </td>
                  <td data-columna="Vence" className="sin-corte">
                    {r.factura.vencimiento ? formatearFecha(r.factura.vencimiento) : "Sin fecha"}
                  </td>
                  <td data-columna="Saldo actual" className="num">
                    <Importe valor={r.factura.saldo_actual} moneda={r.factura.moneda} />
                  </td>
                  <td data-columna="A pagar" className="num">
                    <Importe valor={r.importe} moneda={r.factura.moneda} />
                    {r.factura.moneda !== "MXN" ? (
                      <span className="secundario bloque">
                        <Importe valor={r.importe_mxn} codigo />
                      </span>
                    ) : null}
                  </td>
                  <td data-columna="Razón">{r.razon}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      {p.excluidas.length > 0 ? (
        <section className="panel" aria-labelledby="titulo-excluidas">
          <h2 id="titulo-excluidas">Facturas que se dejaron fuera</h2>
          <ul className="lista-alertas">
            {p.excluidas.map((x) => (
              <li key={x.factura_id} className="mensaje mensaje-alerta">
                <p>
                  <Link to={`/facturas/${x.factura_id}`}>{`Factura ${x.factura_id}`}</Link>
                  {`: ${x.motivo}`}
                </p>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </Vista>
  );
}
