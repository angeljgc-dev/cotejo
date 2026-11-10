"""Propiedades de la carga: el orden de llegada no cambia los saldos y repetir un lote deja la base idéntica."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy.orm import Session

from cotejo.cxp import saldos
from cotejo.ingesta.servicio import ArchivoPorIngerir, ingerir_lote
from cotejo.semilla.cfdi_ficticio import construir_xml
from tests.apoyo.cfdi import AHORA, docto, factura_de, huella_tablas, ingreso, nota, pago
from tests.apoyo.fabricas import EMPRESA_RFC, crear_usuario

UNO = ingreso(Decimal("2320.00"), fecha=datetime.fromisoformat("2026-09-01T10:00:00"))
DOS = ingreso(Decimal("3480.00"), fecha=datetime.fromisoformat("2026-09-20T10:00:00"))
COMPROBANTES = (
    UNO,
    DOS,
    nota(Decimal("100.00"), UNO.uuid),
    pago((datetime.fromisoformat("2026-10-01T12:00:00"), (docto(UNO, 1, Decimal("2204.00"), Decimal("1000.00")),))),
    pago((datetime.fromisoformat("2026-10-15T12:00:00"), (docto(UNO, 2, Decimal("1204.00"), Decimal("500.00")),))),
    pago((datetime.fromisoformat("2026-10-02T12:00:00"), (docto(DOS, 1, Decimal("3480.00"), Decimal("480.00")),))),
)
ESPERADO = {UNO.uuid: Decimal("704.00"), DOS.uuid: Decimal("3000.00")}


def test_orden_de_llegada_no_cambia_saldos_y_repetir_no_cambia_nada(sesion: Session) -> None:
    usuario = crear_usuario(sesion)
    archivos = {c.uuid: ArchivoPorIngerir(nombre=f"{c.uuid}.xml", contenido=construir_xml(c)) for c in COMPROBANTES}

    def cargar(orden: list[str], tamano_lote: int) -> None:
        for inicio in range(0, len(orden), tamano_lote):
            ingerir_lote(
                sesion,
                usuario_id=usuario.id,
                entradas=[archivos[u] for u in orden[inicio : inicio + tamano_lote]],
                empresa_rfc=EMPRESA_RFC,
                ahora=AHORA,
            )
        sesion.flush()

    @settings(max_examples=30, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    @given(orden=st.permutations([c.uuid for c in COMPROBANTES]), tamano_lote=st.integers(min_value=1, max_value=6))
    def caso(orden: list[str], tamano_lote: int) -> None:
        punto = sesion.begin_nested()
        try:
            cargar(orden, tamano_lote)
            for cfdi in (UNO, DOS):
                assert saldos.saldo(sesion, factura_de(sesion, cfdi).id) == ESPERADO[cfdi.uuid]
            antes = huella_tablas(sesion)
            cargar(orden, tamano_lote)
            assert huella_tablas(sesion) == antes
        finally:
            punto.rollback()

    caso()
