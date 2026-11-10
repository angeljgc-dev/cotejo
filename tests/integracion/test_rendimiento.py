"""G7: el tablero responde por HTTP en menos de 500 ms con 2,000 facturas (mediana de 5 peticiones)."""

from __future__ import annotations

import statistics
import sys
import time
from collections.abc import Callable
from datetime import date, datetime, timedelta
from datetime import time as hora
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import insert
from sqlalchemy.orm import Session

from cotejo.modelos import Alerta
from tests.apoyo.fabricas import crear_carga_archivo, crear_proveedor, crear_usuario
from tests.apoyo.masivo import FacturaMasiva, insertar

HOY = date(2026, 11, 2)
FACTURAS = 2000
PROVEEDORES = 40
LIMITE_MS = 500


def test_g7_tablero_con_2000_facturas(cliente: TestClient, sesion: Session, entrar_como: Callable[[int], None]) -> None:
    proveedores = [crear_proveedor(sesion, dias_credito=(15, 30, 45, 60)[n % 4]) for n in range(PROVEEDORES)]
    archivo = crear_carga_archivo(sesion)
    facturas = []
    for n in range(FACTURAS):
        proveedor = proveedores[n % PROVEEDORES]
        en_dolares = n % 25 == 0
        facturas.append(
            FacturaMasiva(
                proveedor_id=proveedor.id,
                proveedor_rfc=proveedor.rfc,
                total=Decimal(1000 + (n * 37) % 90000) + Decimal("0.16"),
                fecha_emision=datetime.combine(HOY - timedelta(days=n % 200), hora(10)),
                moneda="USD" if en_dolares else "MXN",
                tipo_cambio=Decimal("18.250000") if en_dolares else None,
            )
        )
    ids = insertar(sesion, facturas, carga_archivo_id=archivo.id)
    sesion.execute(
        insert(Alerta),
        [
            {"factura_id": i, "codigo": "POSIBLE_DUPLICADO", "severidad": "bloqueante", "mensaje": "Prueba"}
            for i in ids[::20]
        ],
    )
    sesion.commit()
    entrar_como(crear_usuario(sesion).id)

    assert cliente.get("/api/tablero").status_code == 200
    tiempos = []
    for _ in range(5):
        inicio = time.perf_counter()
        r = cliente.get("/api/tablero")
        tiempos.append((time.perf_counter() - inicio) * 1000)
        assert r.status_code == 200
    mediana = statistics.median(tiempos)
    sys.stderr.write(f"\n[G7] tablero con {FACTURAS} facturas: mediana {mediana:.1f} ms, todas {tiempos}\n")
    assert sum(g["facturas"] for g in r.json()["antiguedad"]) == FACTURAS
    assert mediana < LIMITE_MS, f"mediana {mediana:.1f} ms"
