import { type FormEvent, useEffect, useState } from "react";
import { useEntrar, useEntrarDemo } from "../api/consultas";
import type { Rol } from "../api/tipos";
import { ErrorAccion } from "../componentes/Estados";
import { MarcaCotejo } from "../componentes/Marco";

const ROLES: { rol: Rol; titulo: string; puede: string[] }[] = [
  {
    rol: "capturista",
    titulo: "Capturista de cuentas por pagar",
    puede: [
      "Sube facturas CFDI y contratos",
      "Consulta adeudos y vencimientos",
      "Pide al asistente propuestas de pago",
    ],
  },
  {
    rol: "aprobador",
    titulo: "Aprobador de tesorería",
    puede: [
      "Aprueba o rechaza propuestas de pago",
      "Resuelve alertas de facturas",
      "No puede aprobar lo que él mismo propuso",
    ],
  },
];

export function Entrar() {
  const demo = useEntrarDemo();
  const entrar = useEntrar();
  const [usuario, setUsuario] = useState("");
  const [contrasena, setContrasena] = useState("");

  useEffect(() => {
    document.title = "Entrar | Cotejo";
  }, []);

  const demoDeshabilitada = demo.error?.codigo === "DEMO_DESHABILITADA";

  function enviar(e: FormEvent) {
    e.preventDefault();
    entrar.mutate({ usuario, contrasena });
  }

  return (
    <main className="entrar">
      <div className="entrar-caja">
        <header>
          <div className="marca">
            <MarcaCotejo />
            <span>Cotejo</span>
          </div>
          <h1>Cuentas por pagar cotejadas contra el CFDI y el contrato</h1>
          <p className="entrar-lema">
            Valida tus CFDI, calcula lo que debes y a quién, y responde preguntas citando el
            contrato. Ningún pago sale sin que una persona lo apruebe.
          </p>
        </header>

        <div className="mensaje mensaje-alerta">
          <p>
            <strong>Esta es una demo con datos ficticios.</strong> Empresas, RFC, facturas y
            contratos son inventados. Puedes probar todo sin miedo: la demo se reinicia cada noche y
            también desde el botón Reiniciar demo.
          </p>
        </div>

        <section aria-labelledby="titulo-roles" className="roles">
          <h2 id="titulo-roles" className="solo-lectores">
            Elige con qué rol entrar
          </h2>
          {ROLES.map((r) => (
            <div key={r.rol} className="rol">
              <div>
                <h3>{r.titulo}</h3>
                <ul>
                  {r.puede.map((p) => (
                    <li key={p}>{p}</li>
                  ))}
                </ul>
              </div>
              <button
                type="button"
                className="boton boton-primario"
                disabled={demo.isPending}
                onClick={() => demo.mutate(r.rol)}
              >
                {`Entrar como ${r.rol}`}
              </button>
            </div>
          ))}
        </section>
        {demoDeshabilitada ? (
          <div className="mensaje mensaje-info" role="alert">
            <p>Esta instalación no tiene la demo activada. Entra con tu usuario y contraseña.</p>
          </div>
        ) : (
          <ErrorAccion error={demo.error} />
        )}

        <details>
          <summary className="boton-texto">Tengo usuario y contraseña</summary>
          <form className="panel" onSubmit={enviar}>
            <label className="campo">
              Usuario
              <input
                className="entrada"
                autoComplete="username"
                value={usuario}
                onChange={(e) => setUsuario(e.target.value)}
                required
              />
            </label>
            <label className="campo">
              Contraseña
              <input
                className="entrada"
                type="password"
                autoComplete="current-password"
                value={contrasena}
                onChange={(e) => setContrasena(e.target.value)}
                required
              />
            </label>
            <ErrorAccion error={entrar.error} />
            <div>
              <button type="submit" className="boton boton-primario" disabled={entrar.isPending}>
                Entrar
              </button>
            </div>
          </form>
        </details>
      </div>
    </main>
  );
}
