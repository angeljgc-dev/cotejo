"""B3: grupos de antigüedad en los bordes, y la misma regla en Python y en SQL."""

from __future__ import annotations

from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from cotejo.cxp.antiguedad import GRUPOS, agrupar, grupo_de


@pytest.mark.parametrize(
    ("dias", "grupo"),
    [
        (-15, "por_vencer"),
        (0, "por_vencer"),
        (1, "1_30"),
        (30, "1_30"),
        (31, "31_60"),
        (60, "31_60"),
        (61, "61_90"),
        (90, "61_90"),
        (91, "mas_90"),
        (400, "mas_90"),
    ],
)
def test_bordes(dias: int, grupo: str) -> None:
    assert grupo_de(dias) == grupo


@given(
    st.lists(
        st.tuples(
            st.integers(min_value=-400, max_value=400),
            st.decimals(min_value=Decimal("0.01"), max_value=Decimal("9999999.99"), places=2),
        ),
        max_size=60,
    )
)
def test_suma_de_grupos_igual_al_total(saldos: list[tuple[int, Decimal]]) -> None:
    grupos = agrupar(saldos)
    assert list(grupos) == [clave for clave, _ in GRUPOS]
    assert sum((suma for suma, _ in grupos.values()), Decimal(0)) == sum((s for _, s in saldos), Decimal(0))
    assert sum(cuenta for _, cuenta in grupos.values()) == len(saldos)
