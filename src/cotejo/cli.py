"""Tareas de administración: `python -m cotejo.cli crear-usuario --usuario ana --nombre "Ana" --rol aprobador`.

La contraseña se pide sin eco en la terminal (o por la variable COTEJO_CONTRASENA en instalaciones automáticas);
nunca se pasa como argumento para que no quede en el historial del intérprete de comandos.
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from collections.abc import Sequence

from sqlalchemy import select

from cotejo.db import fabrica_sesiones
from cotejo.modelos import Usuario
from cotejo.seguridad.contrasenas import hash_contrasena

LARGO_MINIMO_CONTRASENA = 12


class ErrorCli(Exception):
    pass


def _contrasena() -> str:
    valor = os.environ.get("COTEJO_CONTRASENA")
    if valor is None:
        valor = getpass.getpass("Contraseña: ")
        if getpass.getpass("Repite la contraseña: ") != valor:
            raise ErrorCli("Las contraseñas no coinciden.")
    if len(valor) < LARGO_MINIMO_CONTRASENA:
        raise ErrorCli(f"La contraseña debe tener al menos {LARGO_MINIMO_CONTRASENA} caracteres.")
    return valor


def crear_usuario(usuario: str, nombre: str, rol: str, contrasena: str) -> int:
    with fabrica_sesiones()() as sesion:
        if sesion.scalar(select(Usuario.id).where(Usuario.usuario == usuario)) is not None:
            raise ErrorCli(f"Ya existe el usuario {usuario}.")
        nuevo = Usuario(
            usuario=usuario, nombre=nombre, rol=rol, hash_contrasena=hash_contrasena(contrasena), es_demo=False
        )
        sesion.add(nuevo)
        sesion.commit()
        return nuevo.id


def main(argumentos: Sequence[str] | None = None) -> int:
    lector = argparse.ArgumentParser(prog="python -m cotejo.cli", description="Administración de Cotejo.")
    ordenes = lector.add_subparsers(dest="orden", required=True)
    alta = ordenes.add_parser("crear-usuario", help="crea un usuario con contraseña")
    alta.add_argument("--usuario", required=True)
    alta.add_argument("--nombre", required=True)
    alta.add_argument("--rol", required=True, choices=("capturista", "aprobador"))
    opciones = lector.parse_args(argumentos)
    try:
        if opciones.orden == "crear-usuario":
            nuevo_id = crear_usuario(opciones.usuario, opciones.nombre, opciones.rol, _contrasena())
            sys.stdout.write(f"Usuario {opciones.usuario} creado con id {nuevo_id}.\n")
    except ErrorCli as exc:
        sys.stderr.write(f"{exc}\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
