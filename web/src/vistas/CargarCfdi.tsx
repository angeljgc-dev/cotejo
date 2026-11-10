import { type FormEvent, useId, useRef, useState } from "react";
import { Link } from "react-router";
import { useCargarCfdi, useConfiguracion } from "../api/consultas";
import { useUsuario } from "../api/contexto";
import type { ArchivoCargado, ResultadoArchivoCfdi } from "../api/tipos";
import { ErrorAccion } from "../componentes/Estados";
import { Vista } from "../componentes/Vista";
import { clavesUnicas } from "../utilidades/claves";

const RESULTADO: Record<ResultadoArchivoCfdi, { texto: string; clase: string }> = {
  aceptada: { texto: "Aceptada", clase: "insignia insignia-exito" },
  aceptada_con_alertas: { texto: "Aceptada con alertas", clase: "insignia insignia-alerta" },
  rechazada: { texto: "Rechazada", clase: "insignia insignia-bloqueante" },
  duplicada: { texto: "Ya existía", clase: "insignia" },
};

function FilaResultado({ a }: { a: ArchivoCargado }) {
  const r = RESULTADO[a.resultado];
  return (
    <tr>
      <td data-columna="Archivo">{a.nombre}</td>
      <td data-columna="Resultado">
        <span className={r.clase}>{r.texto}</span>
      </td>
      <td data-columna="Detalle">
        {a.resultado === "duplicada" ? (
          <p>
            {"Este UUID ya estaba registrado; no se volvió a guardar. "}
            {a.factura_id !== null ? (
              <Link to={`/facturas/${a.factura_id}`}>Ver la factura</Link>
            ) : null}
          </p>
        ) : null}
        {a.motivos.length > 0 ? (
          <ul className="motivos">
            {a.motivos.map((m) => (
              <li key={`${m.codigo}-${m.mensaje}`}>{m.mensaje}</li>
            ))}
          </ul>
        ) : null}
        {a.resultado === "aceptada" ? <p className="secundario">Sin observaciones.</p> : null}
        {a.factura_id !== null && a.resultado !== "duplicada" ? (
          <Link to={`/facturas/${a.factura_id}`}>Abrir la factura</Link>
        ) : null}
      </td>
    </tr>
  );
}

export function CargarCfdi() {
  const usuario = useUsuario();
  const configuracion = useConfiguracion();
  const carga = useCargarCfdi();
  const [archivos, setArchivos] = useState<File[]>([]);
  const [avisoSeleccion, setAvisoSeleccion] = useState<string | null>(null);
  const entrada = useRef<HTMLInputElement>(null);
  const id = useId();
  const maximo = configuracion.data?.limites.archivos_por_carga ?? 50;
  const mb = configuracion.data?.limites.mb_por_xml ?? 2;

  function elegir(lista: FileList | null) {
    const todos = Array.from(lista ?? []);
    if (todos.length > maximo) {
      setAvisoSeleccion(
        `Se tomaron los primeros ${maximo} archivos; el límite por carga es ${maximo}.`,
      );
    } else {
      setAvisoSeleccion(null);
    }
    setArchivos(todos.slice(0, maximo));
    carga.reset();
  }

  function enviar(e: FormEvent) {
    e.preventDefault();
    if (archivos.length === 0) return;
    carga.mutate(archivos, {
      onSuccess: () => {
        setArchivos([]);
        if (entrada.current) entrada.current.value = "";
      },
    });
  }

  if (usuario.rol !== "capturista") {
    return (
      <Vista titulo="Cargar CFDI" migas={<Link to="/facturas">Facturas</Link>}>
        <div className="mensaje mensaje-info">
          <p>Solo el rol capturista carga facturas. Entra como capturista para probar la carga.</p>
        </div>
      </Vista>
    );
  }

  const resultado = carga.data;

  return (
    <Vista
      titulo="Cargar CFDI"
      migas={<Link to="/facturas">Facturas</Link>}
      descripcion="Sube uno o varios XML de CFDI 4.0. Cada archivo se valida por separado: uno malo no detiene a los demás."
    >
      <form onSubmit={enviar} className="panel">
        <div className="zona-carga">
          <label className="campo" htmlFor={`${id}-xml`}>
            Archivos XML
            <span className="campo-ayuda">
              {`Hasta ${maximo} archivos por carga y ${mb} MB por XML.`}
            </span>
          </label>
          <input
            ref={entrada}
            id={`${id}-xml`}
            type="file"
            accept=".xml,application/xml,text/xml"
            multiple
            onChange={(e) => elegir(e.target.files)}
          />
          <p role="status" className="secundario">
            {archivos.length === 0
              ? "Ningún archivo elegido."
              : archivos.length === 1
                ? "1 archivo listo para cargar."
                : `${archivos.length} archivos listos para cargar.`}
          </p>
          {avisoSeleccion ? <p className="campo-error">{avisoSeleccion}</p> : null}
        </div>
        <ErrorAccion error={carga.error} />
        <div>
          <button
            type="submit"
            className="boton boton-primario"
            disabled={archivos.length === 0 || carga.isPending}
          >
            {carga.isPending ? "Validando archivos" : "Validar y cargar"}
          </button>
        </div>
      </form>

      {resultado ? (
        <section className="panel" aria-labelledby="titulo-resultado" aria-live="polite">
          <h2 id="titulo-resultado">{`Resultado de la carga ${resultado.carga_id}`}</h2>
          <div className="resumen-carga">
            <span className="insignia insignia-exito">{`${resultado.resumen.aceptadas} aceptadas`}</span>
            <span className="insignia insignia-alerta">
              {`${resultado.resumen.con_alertas} con alertas`}
            </span>
            <span className="insignia insignia-bloqueante">
              {`${resultado.resumen.rechazadas} rechazadas`}
            </span>
            <span className="insignia">{`${resultado.resumen.duplicadas} ya existían`}</span>
          </div>
          <table className="tabla tabla-apilable">
            <caption className="solo-lectores">Resultado por archivo</caption>
            <thead>
              <tr>
                <th scope="col">Archivo</th>
                <th scope="col">Resultado</th>
                <th scope="col">Detalle</th>
              </tr>
            </thead>
            <tbody>
              {clavesUnicas(resultado.archivos, (a) => a.nombre).map(([clave, a]) => (
                <FilaResultado key={clave} a={a} />
              ))}
            </tbody>
          </table>
        </section>
      ) : null}
    </Vista>
  );
}
