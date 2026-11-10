/**
 * Claves de React estables para listas que pueden repetir valores (dos archivos con el mismo
 * nombre, dos llamadas a la misma herramienta): el valor más su número de aparición.
 */
export function clavesUnicas<T>(lista: T[], base: (x: T) => string): [string, T][] {
  const vistos = new Map<string, number>();
  return lista.map((x) => {
    const b = base(x);
    const n = (vistos.get(b) ?? 0) + 1;
    vistos.set(b, n);
    return [`${b}#${n}`, x];
  });
}
