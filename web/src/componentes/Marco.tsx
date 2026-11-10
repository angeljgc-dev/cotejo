import { type ReactNode, useEffect, useRef, useState } from "react";
import { NavLink, useLocation } from "react-router";
import { useConfiguracion, useReiniciarDemo, useSalir } from "../api/consultas";
import { useUsuario } from "../api/contexto";
import { mensajeDeError } from "./Estados";

const SECCIONES = [
  { ruta: "/", texto: "Tablero" },
  { ruta: "/facturas", texto: "Facturas" },
  { ruta: "/proveedores", texto: "Proveedores" },
  { ruta: "/documentos", texto: "Documentos" },
  { ruta: "/propuestas", texto: "Propuestas" },
  { ruta: "/asistente", texto: "Asistente" },
  { ruta: "/bitacora", texto: "Bitácora" },
];

export const NOMBRE_ROL = {
  capturista: "Capturista",
  aprobador: "Aprobador",
} as const;

export function MarcaCotejo() {
  // Dos hojas encimadas: el comprobante y el documento contra el que se coteja.
  return (
    <svg width="26" height="26" viewBox="0 0 26 26" aria-hidden="true" focusable="false">
      <rect
        x="2"
        y="5"
        width="14"
        height="18"
        rx="1.5"
        fill="none"
        stroke="#17212b"
        strokeWidth="2"
      />
      <rect x="10" y="2" width="14" height="18" rx="1.5" fill="#0b5d52" />
      <path
        d="M13.5 11.5l2.6 2.6 4.6-5.2"
        fill="none"
        stroke="#ffffff"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function AvisoDemo() {
  const configuracion = useConfiguracion();
  const reiniciar = useReiniciarDemo();
  const [confirmado, setConfirmado] = useState<string | null>(null);
  if (!configuracion.data?.modo_demo) return null;
  return (
    <section className="aviso-demo" aria-label="Aviso de demostración">
      <p>
        {configuracion.data.aviso_demo ??
          "Demo con datos ficticios: empresas, RFC, facturas y contratos son inventados."}
      </p>
      <button
        type="button"
        className="boton"
        disabled={reiniciar.isPending}
        onClick={() =>
          reiniciar.mutate(undefined, {
            onSuccess: (r) =>
              setConfirmado(
                `Demo reiniciada: ${r.facturas} facturas y ${r.documentos} documentos.`,
              ),
            onError: () => setConfirmado(null),
          })
        }
      >
        {reiniciar.isPending ? "Reiniciando demo" : "Reiniciar demo"}
      </button>
      <p role="status" className="aviso-estado">
        {reiniciar.isError ? mensajeDeError(reiniciar.error) : (confirmado ?? "")}
      </p>
    </section>
  );
}

export function Marco({ children }: { children: ReactNode }) {
  const usuario = useUsuario();
  const configuracion = useConfiguracion();
  const salir = useSalir();
  const [menuAbierto, setMenuAbierto] = useState(false);
  const ubicacion = useLocation();
  const principal = useRef<HTMLElement>(null);
  const rutaAnterior = useRef(ubicacion.pathname);

  // Al cambiar de vista se cierra el menú y el foco va al contenido, como en una navegación real.
  useEffect(() => {
    if (rutaAnterior.current === ubicacion.pathname) return;
    rutaAnterior.current = ubicacion.pathname;
    setMenuAbierto(false);
    principal.current?.focus();
  }, [ubicacion.pathname]);

  return (
    <div className="marco">
      <a className="saltar" href="#principal">
        Saltar al contenido
      </a>
      <AvisoDemo />
      <aside className="lateral">
        <div className="lateral-fijo">
          <div className="lateral-cabecera">
            <div>
              <NavLink to="/" className="marca" aria-label="Cotejo, ir al tablero">
                <MarcaCotejo />
                Cotejo
              </NavLink>
              {configuracion.data ? (
                <p className="empresa">{configuracion.data.empresa_nombre}</p>
              ) : null}
            </div>
            <button
              type="button"
              className="boton boton-menu"
              aria-expanded={menuAbierto}
              aria-controls="navegacion"
              onClick={() => setMenuAbierto((v) => !v)}
            >
              {menuAbierto ? "Cerrar menú" : "Menú"}
            </button>
          </div>
          <nav
            id="navegacion"
            className="navegacion"
            aria-label="Secciones"
            data-abierta={menuAbierto}
          >
            <ul>
              {SECCIONES.map((s) => (
                <li key={s.ruta}>
                  <NavLink to={s.ruta} end={s.ruta === "/"}>
                    {s.texto}
                  </NavLink>
                </li>
              ))}
            </ul>
            <div className="cuenta">
              <div>
                <strong>{usuario.nombre}</strong>
                <div className="cuenta-rol">{`Rol ${NOMBRE_ROL[usuario.rol].toLowerCase()}`}</div>
              </div>
              <button
                type="button"
                className="boton"
                onClick={() => salir.mutate()}
                disabled={salir.isPending}
              >
                Salir
              </button>
            </div>
          </nav>
        </div>
      </aside>
      <main id="principal" className="principal" ref={principal} tabIndex={-1}>
        {children}
      </main>
    </div>
  );
}
