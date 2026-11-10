"""La base de pruebas tolera varias sesiones de pytest a la vez (decisión 7) y nunca toca una base ajena."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import textwrap

from sqlalchemy import Engine, create_engine, text

from cotejo.db import normalizar_url
from tests.apoyo import pg_local

RAIZ = pg_local.RAIZ
PRUEBA_CORTA = "tests/integracion/test_migraciones.py::test_modelos_y_migracion_coinciden"


def _entorno(**cambios: str | None) -> dict[str, str]:
    entorno = {**os.environ, "PYTHONUTF8": "1"}
    for clave, valor in cambios.items():
        if valor is None:
            entorno.pop(clave, None)
        else:
            entorno[clave] = valor
    return entorno


def _bases(motor_admin: Engine) -> set[str]:
    with motor_admin.connect() as c:
        return set(c.execute(text("SELECT datname FROM pg_database")).scalars())


def test_se_niega_a_correr_contra_una_base_sin_test() -> None:
    proceso = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", PRUEBA_CORTA],
        cwd=RAIZ,
        env=_entorno(DATABASE_URL="postgresql://nadie@127.0.0.1:9/produccion"),
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    salida = proceso.stdout + proceso.stderr
    assert proceso.returncode == 3, salida
    assert "Se niega a correr" in salida and "'produccion'" in salida


def test_otra_sesion_usa_su_propia_base_y_la_borra(base_prueba: pg_local.BasePrueba) -> None:
    """Corre una sesión de pytest completa en paralelo a esta: no comparte base ni apaga el servidor."""
    motor_admin = create_engine(pg_local.url_admin_de(base_prueba), isolation_level="AUTOCOMMIT")
    try:
        proceso = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", PRUEBA_CORTA],
            cwd=RAIZ,
            env=_entorno(),
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
        assert proceso.returncode == 0, proceso.stdout + proceso.stderr
        encontrado = re.search(r"\[base de pruebas\] base (\S+) \((local|externa)\)", proceso.stdout)
        assert encontrado, proceso.stdout
        base_hija = encontrado.group(1)
        assert base_hija != base_prueba.nombre
        assert "test" in base_hija
        bases = _bases(motor_admin)
        assert base_hija not in bases  # la sesión hija borró su base al terminar
        assert base_prueba.nombre in bases  # y el servidor sigue vivo para esta sesión
        motor = create_engine(base_prueba.url)
        with motor.connect() as c:
            assert c.execute(text("SELECT 1")).scalar_one() == 1
        motor.dispose()
    finally:
        motor_admin.dispose()


def test_servidor_local_se_comparte_entre_procesos() -> None:
    """Un segundo proceso toma y suelta el servidor local; como este proceso lo sigue usando, no se detiene."""
    servidor = pg_local.servidor_local()
    url = normalizar_url(servidor.get_uri(database="postgres"))
    guion = textwrap.dedent(
        """
        import json, os, sys
        from tests.apoyo import pg_local
        s = pg_local.servidor_local()
        print(json.dumps({"uri": s.get_uri(database="postgres"), "pid": os.getpid()}))
        s.cleanup()
        """
    )
    proceso = subprocess.run(
        [sys.executable, "-c", guion],
        cwd=RAIZ,
        env=_entorno(),
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert proceso.returncode == 0, proceso.stderr
    assert servidor.get_uri(database="postgres") in proceso.stdout  # el mismo servidor, no uno nuevo
    motor = create_engine(url)
    try:
        with motor.connect() as c:
            assert c.execute(text("SELECT 1")).scalar_one() == 1
    finally:
        motor.dispose()
    pids = (pg_local.PGDATA / ".handle_pids.json").read_text(encoding="utf-8")
    assert str(os.getpid()) in pids
