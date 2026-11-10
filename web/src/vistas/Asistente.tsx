import {
  type FormEvent,
  Fragment,
  type ReactNode,
  useEffect,
  useId,
  useRef,
  useState,
} from "react";
import { Link } from "react-router";
import type { ErrorApi } from "../api/cliente";
import { useEnviarMensaje, useEstadoAsistente, useFragmento } from "../api/consultas";
import type { Cita, MensajeChat } from "../api/tipos";
import { Cargando, ErrorAccion, EstadoError } from "../componentes/Estados";
import { Importe } from "../componentes/Importe";
import { nombreFactura } from "../componentes/Insignias";
import { Vista } from "../componentes/Vista";
import { clavesUnicas } from "../utilidades/claves";

type Turno =
  | { clave: string; tipo: "usuario"; texto: string }
  | { clave: string; tipo: "asistente"; mensaje: MensajeChat }
  | { clave: string; tipo: "error"; error: ErrorApi };

const SUGERENCIAS = [
  "¿A qué proveedor le debemos más y cuánto?",
  "¿Qué facturas vencen esta semana?",
  "¿Qué dicen los contratos sobre pagos tardíos?",
  "Propón los pagos de esta semana con presupuesto de 300 mil",
];

const MARCA_CITA = /\[F:(\d+)\]/g;

/** Sustituye cada marca [F:123] del texto por un botón que abre ese fragmento. */
function TextoConCitas({
  texto,
  citas,
  abrir,
}: {
  texto: string;
  citas: Cita[];
  abrir: (id: number) => void;
}) {
  const partes: ReactNode[] = [];
  let ultimo = 0;
  for (const m of texto.matchAll(MARCA_CITA)) {
    const inicio = m.index ?? 0;
    partes.push(<Fragment key={`texto-${ultimo}`}>{texto.slice(ultimo, inicio)}</Fragment>);
    const fragmentoId = Number(m[1]);
    const indice = citas.findIndex((c) => c.fragmento_id === fragmentoId);
    const cita = citas[indice];
    if (cita) {
      partes.push(
        <button
          key={`cita-${inicio}`}
          type="button"
          className="cita"
          onClick={() => abrir(fragmentoId)}
          aria-label={`Fuente ${indice + 1}: ${cita.documento}, página ${cita.pagina}`}
        >
          {indice + 1}
        </button>,
      );
    } else {
      partes.push(<Fragment key={`marca-${inicio}`}>{m[0]}</Fragment>);
    }
    ultimo = inicio + m[0].length;
  }
  partes.push(<Fragment key={`texto-${ultimo}`}>{texto.slice(ultimo)}</Fragment>);
  return <p>{partes}</p>;
}

function ComoLoCalcule({ m }: { m: MensajeChat }) {
  if (m.herramientas.length === 0 && m.facturas_base.length === 0) return null;
  return (
    <details className="calculo">
      <summary>Cómo lo calculé</summary>
      {m.herramientas.length > 0 ? (
        <>
          <p className="secundario">
            Las cifras salen de consultas a la base de Cotejo; el modelo no hace las cuentas.
          </p>
          <ol>
            {clavesUnicas(m.herramientas, (h) => h.nombre).map(([claveH, h]) => (
              <li key={claveH}>
                <strong>{h.nombre}</strong>
                {` (${h.duracion_ms} ms): ${h.resumen}`}
                {h.error ? <span className="campo-error bloque">{`Error: ${h.error}`}</span> : null}
              </li>
            ))}
          </ol>
        </>
      ) : null}
      {m.facturas_base.length > 0 ? (
        <table className="tabla tabla-apilable">
          <caption>Facturas en que se basa la respuesta</caption>
          <thead>
            <tr>
              <th scope="col">Factura</th>
              <th scope="col">Proveedor</th>
              <th scope="col" className="num">
                Saldo
              </th>
            </tr>
          </thead>
          <tbody>
            {m.facturas_base.map((f) => (
              <tr key={f.id}>
                <td data-columna="Factura">
                  <Link to={`/facturas/${f.id}`}>{nombreFactura(f)}</Link>
                </td>
                <td data-columna="Proveedor">{f.proveedor.nombre}</td>
                <td data-columna="Saldo" className="num">
                  <Importe valor={f.saldo} moneda={f.moneda} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
    </details>
  );
}

function RespuestaAsistente({ m, abrir }: { m: MensajeChat; abrir: (id: number) => void }) {
  return (
    <div className="turno-asistente">
      <TextoConCitas texto={m.texto} citas={m.citas} abrir={abrir} />
      {m.advertencias.map((a) => (
        <div key={a.codigo} className="mensaje mensaje-alerta">
          <p>{a.mensaje}</p>
        </div>
      ))}
      {m.propuesta_id !== null ? (
        <p>
          <Link className="boton" to={`/propuestas/${m.propuesta_id}`}>
            {`Abrir la propuesta ${m.propuesta_id}`}
          </Link>
        </p>
      ) : null}
      {m.citas.length > 0 ? (
        <div>
          <h3 className="secundario">Fuentes</h3>
          <ol className="motivos">
            {m.citas.map((c) => (
              <li key={c.fragmento_id}>
                <button type="button" className="boton-texto" onClick={() => abrir(c.fragmento_id)}>
                  {`${c.documento}, página ${c.pagina}`}
                </button>
              </li>
            ))}
          </ol>
        </div>
      ) : null}
      <ComoLoCalcule m={m} />
    </div>
  );
}

function PanelFragmento({
  id,
  cerrar,
  cambiar,
}: {
  id: number;
  cerrar: () => void;
  cambiar: (id: number) => void;
}) {
  const consulta = useFragmento(id);
  const titulo = useRef<HTMLHeadingElement>(null);

  // El foco salta al fragmento al abrirlo para que teclado y lector de pantalla lleguen a él.
  useEffect(() => {
    if (consulta.data?.id === id) titulo.current?.focus();
  }, [consulta.data?.id, id]);

  return (
    <aside className="panel fragmento" aria-labelledby="titulo-fragmento">
      {consulta.isPending ? (
        <Cargando texto="Abriendo el fragmento citado" />
      ) : consulta.isError ? (
        <EstadoError titulo="No pudimos abrir la cita" error={consulta.error} />
      ) : (
        <>
          <h2 id="titulo-fragmento" ref={titulo} tabIndex={-1}>
            {consulta.data.documento.nombre}
          </h2>
          <p className="secundario">{`Página ${consulta.data.pagina}`}</p>
          <blockquote>{consulta.data.texto}</blockquote>
          <div className="acciones">
            <button
              type="button"
              className="boton"
              disabled={consulta.data.anterior_id === null}
              onClick={() =>
                consulta.data.anterior_id !== null && cambiar(consulta.data.anterior_id)
              }
            >
              Fragmento anterior
            </button>
            <button
              type="button"
              className="boton"
              disabled={consulta.data.siguiente_id === null}
              onClick={() =>
                consulta.data.siguiente_id !== null && cambiar(consulta.data.siguiente_id)
              }
            >
              Fragmento siguiente
            </button>
          </div>
        </>
      )}
      <div>
        <button type="button" className="boton" onClick={cerrar}>
          Cerrar fragmento
        </button>
      </div>
    </aside>
  );
}

export function Asistente() {
  const estado = useEstadoAsistente();
  const enviar = useEnviarMensaje();
  const [turnos, setTurnos] = useState<Turno[]>([]);
  const [texto, setTexto] = useState("");
  const [conversacion, setConversacion] = useState<string | null>(null);
  const [fragmento, setFragmento] = useState<number | null>(null);
  const id = useId();
  const contador = useRef(0);

  function clave() {
    contador.current += 1;
    return `t${contador.current}`;
  }

  function preguntar(pregunta: string) {
    const limpia = pregunta.trim();
    if (!limpia || enviar.isPending) return;
    setTurnos((t) => [...t, { clave: clave(), tipo: "usuario", texto: limpia }]);
    setTexto("");
    enviar.mutate(
      { conversacionId: conversacion, texto: limpia },
      {
        onSuccess: (m) => {
          setConversacion(m.conversacion_id);
          setTurnos((t) => [...t, { clave: clave(), tipo: "asistente", mensaje: m }]);
        },
        onError: (error) => setTurnos((t) => [...t, { clave: clave(), tipo: "error", error }]),
      },
    );
  }

  function alEnviar(e: FormEvent) {
    e.preventDefault();
    preguntar(texto);
  }

  const descripcion =
    "Pregunta por adeudos, vencimientos o lo que dicen tus contratos. Las cifras salen de la base y cada cita abre el texto original.";

  if (estado.isPending) {
    return (
      <Vista titulo="Asistente" descripcion={descripcion}>
        <Cargando texto="Revisando si el asistente está disponible" />
      </Vista>
    );
  }
  if (estado.isError) {
    return (
      <Vista titulo="Asistente" descripcion={descripcion}>
        <EstadoError
          titulo="No pudimos consultar el estado del asistente"
          error={estado.error}
          reintentar={() => void estado.refetch()}
        />
      </Vista>
    );
  }

  const e = estado.data;
  const sinCuota = e.disponible && e.restantes_hoy <= 0;
  const bloqueado = !e.disponible || sinCuota;

  return (
    <Vista titulo="Asistente" descripcion={descripcion}>
      {!e.disponible ? (
        <div className="mensaje mensaje-info" role="status">
          <p>
            <strong>El asistente no está disponible.</strong>{" "}
            {e.motivo ?? "No hay un modelo de lenguaje configurado en esta instalación."}
          </p>
          <p>
            {"Mientras tanto puedes consultar el "}
            <Link to="/">tablero</Link>
            {", las "}
            <Link to="/facturas">facturas</Link>
            {" y los "}
            <Link to="/documentos">documentos</Link>.
          </p>
        </div>
      ) : (
        <p className="cuota" role="status">
          {sinCuota
            ? `Ya usaste las ${e.limite_dia} preguntas de hoy. La cuota se renueva a medianoche, hora del centro de México.`
            : `Te quedan ${e.restantes_hoy} de ${e.limite_dia} preguntas hoy.`}
        </p>
      )}

      <div className="chat" data-con-fragmento={fragmento !== null}>
        <div className="contenido">
          {turnos.length === 0 && !bloqueado ? (
            <section aria-labelledby={`${id}-sugerencias`}>
              <h2 id={`${id}-sugerencias`} className="secundario">
                Prueba con una de estas preguntas
              </h2>
              <div className="sugerencias">
                {SUGERENCIAS.map((s) => (
                  <button key={s} type="button" className="boton" onClick={() => preguntar(s)}>
                    {s}
                  </button>
                ))}
              </div>
            </section>
          ) : null}

          {turnos.length > 0 ? (
            <ol className="conversacion" aria-label="Conversación" aria-live="polite">
              {turnos.map((t) => (
                <li key={t.clave} className={t.tipo === "usuario" ? "turno-usuario" : undefined}>
                  {t.tipo === "usuario" ? (
                    <>
                      <span className="solo-lectores">Tú: </span>
                      {t.texto}
                    </>
                  ) : t.tipo === "asistente" ? (
                    <RespuestaAsistente m={t.mensaje} abrir={setFragmento} />
                  ) : (
                    <ErrorAccion error={t.error} />
                  )}
                </li>
              ))}
            </ol>
          ) : null}
          {enviar.isPending ? <Cargando texto="Consultando la base y los documentos" /> : null}

          <form className="formulario-chat" onSubmit={alEnviar}>
            <label className="campo" htmlFor={`${id}-pregunta`}>
              Tu pregunta
            </label>
            <textarea
              id={`${id}-pregunta`}
              className="area-texto"
              value={texto}
              maxLength={2000}
              disabled={bloqueado}
              onChange={(ev) => setTexto(ev.target.value)}
              onKeyDown={(ev) => {
                if (ev.key === "Enter" && !ev.shiftKey) {
                  ev.preventDefault();
                  preguntar(texto);
                }
              }}
            />
            <div className="acciones">
              <button
                type="submit"
                className="boton boton-primario"
                disabled={bloqueado || enviar.isPending || texto.trim() === ""}
              >
                Preguntar
              </button>
              <span className="secundario">Enter envía; Mayús + Enter agrega un renglón.</span>
            </div>
          </form>
        </div>
        {fragmento !== null ? (
          <PanelFragmento id={fragmento} cerrar={() => setFragmento(null)} cambiar={setFragmento} />
        ) : null}
      </div>
    </Vista>
  );
}
