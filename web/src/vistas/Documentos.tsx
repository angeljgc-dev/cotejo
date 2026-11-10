import { type FormEvent, useId, useRef, useState } from "react";
import { useSearchParams } from "react-router";
import {
  useConfiguracion,
  useDocumentos,
  useProveedoresParaSelector,
  useSubirDocumentos,
} from "../api/consultas";
import { useUsuario } from "../api/contexto";
import type { ResultadoDocumento } from "../api/tipos";
import { Cargando, ErrorAccion, EstadoError, EstadoVacio } from "../componentes/Estados";
import { Paginacion } from "../componentes/Paginacion";
import { Vista } from "../componentes/Vista";
import { formatearFechaHora } from "../utilidades/fechas";

const RESULTADO_DOC: Record<ResultadoDocumento["resultado"], { texto: string; clase: string }> = {
  indexado: { texto: "Listo para consultar", clase: "insignia insignia-exito" },
  sin_texto: { texto: "Sin texto", clase: "insignia insignia-alerta" },
  rechazado: { texto: "Rechazado", clase: "insignia insignia-bloqueante" },
  duplicado: { texto: "Ya existía", clase: "insignia" },
};

function SubirDocumentos() {
  const subir = useSubirDocumentos();
  const proveedores = useProveedoresParaSelector();
  const configuracion = useConfiguracion();
  const [archivos, setArchivos] = useState<File[]>([]);
  const [proveedor, setProveedor] = useState("");
  const entrada = useRef<HTMLInputElement>(null);
  const id = useId();
  const mb = configuracion.data?.limites.mb_por_documento ?? 10;

  function enviar(e: FormEvent) {
    e.preventDefault();
    if (archivos.length === 0) return;
    subir.mutate(
      { archivos, proveedorId: proveedor ? Number(proveedor) : null },
      {
        onSuccess: () => {
          setArchivos([]);
          if (entrada.current) entrada.current.value = "";
        },
      },
    );
  }

  return (
    <section className="panel" aria-labelledby="titulo-subir-doc">
      <h2 id="titulo-subir-doc">Subir contratos o políticas</h2>
      <form onSubmit={enviar} className="formulario-chat">
        <label className="campo" htmlFor={`${id}-archivos`}>
          Archivos
          <span className="campo-ayuda">
            {`PDF con texto, TXT o MD, hasta 10 archivos de ${mb} MB. Los PDF escaneados se guardan pero no se pueden consultar.`}
          </span>
        </label>
        <input
          ref={entrada}
          id={`${id}-archivos`}
          type="file"
          multiple
          accept=".pdf,.txt,.md,application/pdf,text/plain,text/markdown"
          onChange={(e) => {
            setArchivos(Array.from(e.target.files ?? []).slice(0, 10));
            subir.reset();
          }}
        />
        <label className="campo" htmlFor={`${id}-proveedor`}>
          Proveedor al que pertenece (opcional)
          <select
            id={`${id}-proveedor`}
            className="selector"
            value={proveedor}
            onChange={(e) => setProveedor(e.target.value)}
          >
            <option value="">Ninguno, aplica a todos</option>
            {proveedores.data?.elementos.map((p) => (
              <option key={p.id} value={p.id}>
                {p.nombre}
              </option>
            ))}
          </select>
        </label>
        <ErrorAccion error={subir.error} />
        <div>
          <button
            type="submit"
            className="boton boton-primario"
            disabled={archivos.length === 0 || subir.isPending}
          >
            {subir.isPending ? "Extrayendo texto" : "Subir documentos"}
          </button>
        </div>
      </form>
      {subir.data ? (
        <div aria-live="polite">
          <h3>Resultado</h3>
          <table className="tabla tabla-apilable">
            <caption className="solo-lectores">Resultado por documento</caption>
            <thead>
              <tr>
                <th scope="col">Archivo</th>
                <th scope="col">Resultado</th>
                <th scope="col">Detalle</th>
              </tr>
            </thead>
            <tbody>
              {subir.data.map((r) => (
                <tr key={`${r.nombre}-${r.documento_id ?? r.resultado}`}>
                  <td data-columna="Archivo">{r.nombre}</td>
                  <td data-columna="Resultado">
                    <span className={RESULTADO_DOC[r.resultado].clase}>
                      {RESULTADO_DOC[r.resultado].texto}
                    </span>
                  </td>
                  <td data-columna="Detalle">
                    {r.resultado === "indexado"
                      ? `${r.paginas ?? 0} páginas, ${r.fragmentos ?? 0} fragmentos indexados.`
                      : null}
                    {r.explicacion ? <p>{r.explicacion}</p> : null}
                    {r.motivos.length > 0 ? (
                      <ul className="motivos">
                        {r.motivos.map((m) => (
                          <li key={m.codigo}>{m.mensaje}</li>
                        ))}
                      </ul>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </section>
  );
}

export function Documentos() {
  const usuario = useUsuario();
  const [params, setParams] = useSearchParams();
  const pagina = Math.max(1, Number(params.get("pagina")) || 1);
  const consulta = useDocumentos({ pagina });

  return (
    <Vista
      titulo="Documentos"
      descripcion="Contratos y políticas de pago. El asistente los consulta y cita la página de donde sale cada respuesta."
    >
      {usuario.rol === "capturista" ? <SubirDocumentos /> : null}
      {consulta.isPending ? (
        <Cargando texto="Cargando documentos" />
      ) : consulta.isError ? (
        <EstadoError
          titulo="No pudimos cargar los documentos"
          error={consulta.error}
          reintentar={() => void consulta.refetch()}
        />
      ) : consulta.data.elementos.length === 0 ? (
        <EstadoVacio titulo="Todavía no hay documentos">
          {usuario.rol === "capturista"
            ? "Sube el contrato de un proveedor o tu política de pagos para que el asistente pueda citarlos."
            : "Cuando el capturista suba contratos o políticas, aparecerán aquí."}
        </EstadoVacio>
      ) : (
        <div className="panel">
          <table className="tabla tabla-apilable">
            <caption className="solo-lectores">Documentos</caption>
            <thead>
              <tr>
                <th scope="col">Documento</th>
                <th scope="col">Proveedor</th>
                <th scope="col">Estado</th>
                <th scope="col" className="num">
                  Páginas
                </th>
                <th scope="col">Subido</th>
              </tr>
            </thead>
            <tbody>
              {consulta.data.elementos.map((d) => (
                <tr key={d.id}>
                  <td data-columna="Documento">
                    {d.nombre}
                    {d.explicacion ? (
                      <span className="secundario bloque">{d.explicacion}</span>
                    ) : null}
                  </td>
                  <td data-columna="Proveedor">{d.proveedor?.nombre ?? "General"}</td>
                  <td data-columna="Estado">
                    <span className={RESULTADO_DOC[d.estado].clase}>
                      {RESULTADO_DOC[d.estado].texto}
                    </span>
                  </td>
                  <td data-columna="Páginas" className="num">
                    {d.paginas ?? "Sin dato"}
                    {d.estado === "indexado" && d.fragmentos !== null ? (
                      <span className="secundario bloque">{`${d.fragmentos} fragmentos`}</span>
                    ) : null}
                  </td>
                  <td data-columna="Subido">
                    {formatearFechaHora(d.creado_en)}
                    <span className="secundario bloque">{d.subido_por.nombre}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <Paginacion
            pagina={consulta.data.pagina}
            porPagina={consulta.data.por_pagina}
            total={consulta.data.total}
            singular="documento"
            sustantivo="documentos"
            cambiar={(n) => setParams(new URLSearchParams({ pagina: String(n) }))}
          />
        </div>
      )}
    </Vista>
  );
}
