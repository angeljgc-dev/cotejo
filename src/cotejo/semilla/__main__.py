"""Carga los datos de demostración: `python -m cotejo.semilla` (solo si la base no tiene facturas).

Con `--reiniciar` borra los datos de negocio y vuelve a sembrar aunque la base ya tenga datos.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from cotejo.config import obtener_config
from cotejo.db import fabrica_sesiones
from cotejo.fechas import hoy
from cotejo.semilla import generador


def main(argumentos: Sequence[str] | None = None) -> int:
    lector = argparse.ArgumentParser(prog="python -m cotejo.semilla", description=__doc__)
    lector.add_argument("--reiniciar", action="store_true", help="vacía los datos de negocio antes de sembrar")
    lector.add_argument("--semilla", type=int, default=None, help="semilla del generador (por omisión SEMILLA)")
    opciones = lector.parse_args(argumentos)
    config = obtener_config()
    semilla = config.semilla if opciones.semilla is None else opciones.semilla
    with fabrica_sesiones()() as sesion:
        if opciones.reiniciar:
            resumen = generador.reiniciar_demo(sesion, semilla=semilla, fecha_base=hoy(config))
        elif generador.base_sin_facturas(sesion):
            resumen = generador.sembrar(sesion, semilla=semilla, fecha_base=hoy(config))
        else:
            sys.stdout.write("La base ya tiene facturas; no se sembró nada. Usa --reiniciar para empezar de cero.\n")
            return 0
        sesion.commit()
    sys.stdout.write(
        f"Demostración sembrada: {resumen.proveedores} proveedores, {resumen.facturas} facturas, "
        f"{resumen.notas_credito} notas de crédito, {resumen.complementos_pago} complementos de pago, "
        f"{resumen.documentos} documentos.\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
