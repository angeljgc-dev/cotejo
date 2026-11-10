"""Base de datos de pruebas.

Regla: si DATABASE_URL está definida (CI) se usa ese servidor; si no, se levanta PostgreSQL 16 + pgvector local
con pixeltable-pgserver en `<repo>/.pgtest`. En ambos casos cada sesión de pytest crea su propia base con nombre
único (contiene "test") y la borra al terminar, así varias sesiones pueden correr a la vez.

El servidor local se comparte entre procesos: pixeltable-pgserver anota el PID de cada proceso que lo usa en
`.pgtest/.handle_pids.json` bajo un candado entre procesos, y solo el último en salir lo detiene. Nunca se detiene
un servidor matando procesos por nombre.
"""

from __future__ import annotations

import os
import re
import secrets
import time
from dataclasses import dataclass, field
from pathlib import Path

from pixeltable_pgserver.postgres_server import PostgresServer, get_server
from sqlalchemy import create_engine, make_url, text

from cotejo.db import es_base_de_pruebas, normalizar_url

RAIZ = Path(__file__).resolve().parents[2]
PGDATA = RAIZ / ".pgtest"
# Bases de sesiones que murieron sin limpiar: se borran si tienen más de estas horas.
HORAS_PARA_BASE_HUERFANA = 6
_PATRON_SUFIJO = re.compile(r"_(\d{10})_[0-9a-f]{6}$")


class BaseNoEsDePruebas(RuntimeError):
    pass


@dataclass
class BasePrueba:
    url: str
    nombre: str
    origen: str  # "local" o "externa"
    tiempos: dict[str, float] = field(default_factory=dict)
    servidor: PostgresServer | None = None

    def resumen(self) -> str:
        partes = ", ".join(f"{k} {v:.2f} s" for k, v in self.tiempos.items())
        return f"base {self.nombre} ({self.origen}): {partes}"


def _nombre_unico(prefijo: str) -> str:
    sufijo = f"_{int(time.time())}_{secrets.token_hex(3)}"
    return prefijo[: 63 - len(sufijo)] + sufijo


def _con_base(url: str, nombre: str) -> str:
    return make_url(url).set(database=nombre).render_as_string(hide_password=False)


def _borrar_huerfanas(url_admin: str, prefijo: str) -> None:
    limite = time.time() - HORAS_PARA_BASE_HUERFANA * 3600
    motor = create_engine(url_admin, isolation_level="AUTOCOMMIT")
    try:
        with motor.connect() as c:
            nombres = c.execute(
                text("SELECT datname FROM pg_database WHERE datname LIKE :p"), {"p": f"{prefijo}\\_%"}
            ).scalars()
            for nombre in list(nombres):
                encontrado = _PATRON_SUFIJO.search(nombre)
                if encontrado and int(encontrado.group(1)) < limite and "test" in nombre:
                    c.execute(text(f'DROP DATABASE IF EXISTS "{nombre}" WITH (FORCE)'))
    finally:
        motor.dispose()


def crear_base(url_admin: str, prefijo: str) -> tuple[str, str]:
    """Crea una base nueva y vacía (la extensión vector la crea la migración). Devuelve (url, nombre)."""
    nombre = _nombre_unico(prefijo)
    if "test" not in nombre:
        raise BaseNoEsDePruebas(nombre)
    motor = create_engine(url_admin, isolation_level="AUTOCOMMIT")
    try:
        with motor.connect() as c:
            c.execute(text(f'CREATE DATABASE "{nombre}"'))
    finally:
        motor.dispose()
    return _con_base(url_admin, nombre), nombre


def borrar_base(url_admin: str, nombre: str) -> None:
    if "test" not in nombre:
        raise BaseNoEsDePruebas(nombre)
    motor = create_engine(url_admin, isolation_level="AUTOCOMMIT")
    try:
        with motor.connect() as c:
            c.execute(text(f'DROP DATABASE IF EXISTS "{nombre}" WITH (FORCE)'))
    finally:
        motor.dispose()


def servidor_local() -> PostgresServer:
    return get_server(PGDATA, cleanup_mode="stop")


def preparar() -> BasePrueba:
    """Obtiene un servidor y crea la base única de esta sesión. Lanza BaseNoEsDePruebas ante una URL ajena."""
    t0 = time.perf_counter()
    externa = os.environ.get("DATABASE_URL", "").strip()
    servidor: PostgresServer | None = None
    if externa:
        if not es_base_de_pruebas(externa):
            nombre = make_url(normalizar_url(externa)).database
            raise BaseNoEsDePruebas(f"DATABASE_URL apunta a la base {nombre!r}; su nombre debe contener 'test'.")
        url_admin = normalizar_url(externa)
        prefijo = make_url(url_admin).database or "cotejo_test"
        origen = "externa"
    else:
        servidor = servidor_local()
        url_admin = normalizar_url(servidor.get_uri(database="postgres"))
        prefijo = "cotejo_test"
        origen = "local"
    t1 = time.perf_counter()
    _borrar_huerfanas(url_admin, prefijo)
    url, nombre = crear_base(url_admin, prefijo)
    t2 = time.perf_counter()
    base = BasePrueba(url=url, nombre=nombre, origen=origen, servidor=servidor)
    base.tiempos = {"servidor": t1 - t0, "crear_base": t2 - t1}
    return base


def url_admin_de(base: BasePrueba) -> str:
    externa = os.environ.get("DATABASE_URL", "").strip()
    if externa:
        return normalizar_url(externa)
    assert base.servidor is not None
    return normalizar_url(base.servidor.get_uri(database="postgres"))


def liberar(base: BasePrueba) -> None:
    """Borra la base de la sesión y suelta el servidor local (solo se detiene si nadie más lo usa)."""
    try:
        borrar_base(url_admin_de(base), base.nombre)
    finally:
        if base.servidor is not None:
            base.servidor.cleanup()
