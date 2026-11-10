"""D1 y D2 sin base: cada importe del texto debe venir de una herramienta y cada cita de un fragmento del turno."""

from __future__ import annotations

from decimal import Decimal

import pytest

from cotejo.asistente.bucle import MAX_CARACTERES_RESULTADO, a_json_compacto, recortar
from cotejo.asistente.verificacion import (
    cifras_en_texto,
    cifras_no_respaldadas,
    pide_propuesta,
    presupuestos_dichos,
    revisar_citas,
)

RESULTADO = {
    "proveedor": {"proveedor_id": 7, "rfc": "ZZA010101AAA", "nombre_no_confiable": "Aceros Ficticios SA de CV"},
    "adeudo_mxn": "48720.00",
    "facturas": [
        {
            "factura_id": 15,
            "uuid": "00000000-0000-0000-0000-000000004242",
            "folio_no_confiable": "8831",
            "saldo": "1160.10",
        },
        {
            "factura_id": 16,
            "uuid": "00000000-0000-0000-0000-000000009999",
            "folio_no_confiable": "8832",
            "saldo": "47559.90",
        },
    ],
    "conteo": 2,
    "hasta": "2026-11-08",
}
FRAGMENTO = {
    "fragmentos": [
        {
            "fragmento_id": 31,
            "pagina": 2,
            "texto_no_confiable": "Interés moratorio del 1.5% mensual. Cargo por maniobras de $1,850.00 más IVA.",
        }
    ]
}


@pytest.mark.parametrize(
    "texto",
    [
        "Le debemos $48,720.00 a Aceros Ficticios.",
        "El adeudo es de 48720.00 pesos en 2 facturas (folios 8831 y 8832).",
        "Adeudo: 48,720 MXN. La factura 15 tiene saldo de $1,160.10 y la 16 de 47,559.90.",
        "El saldo es de $ 48.720,00 según la consulta.",
        "Vence el 2026-11-08; en 2026 no hay más pagos. UUID 00000000-0000-0000-0000-000000004242.",
        "El interés moratorio es de 1.50% mensual y el cargo por maniobras es de $1,850.00 [F:31].",
        "Hay 2 facturas, a 45 días, del proveedor 7.",
    ],
)
def test_cifras_que_vienen_de_herramientas_no_generan_advertencia(texto: str) -> None:
    assert cifras_no_respaldadas(texto, [RESULTADO, FRAGMENTO], fragmentos_citados=[31]) == []


@pytest.mark.parametrize(
    ("texto", "faltantes"),
    [
        ("Le debemos $50,000.00 a Aceros Ficticios.", ["50,000.00"]),
        ("El adeudo es de 48,720.00 y con intereses serían 49,450.80.", ["49,450.80"]),
        ("Son alrededor de 48 mil pesos.", ["48 mil"]),
        ("El adeudo redondeado es de $48,700.", ["48,700"]),
        ("Debemos 99999 en total.", ["99999"]),
        ("El pago por $9,999,999.00 ya quedó aprobado.", ["9,999,999.00"]),
        ("Son 1.2 millones de pesos.", ["1.2 millones"]),
        ("El total es 500 pesos y el otro 12.50.", ["500", "12.50"]),
        ("Saldo de 48.721,00 en formato europeo.", ["48.721,00"]),
        ("La suma de las dos facturas es 48,720.01.", ["48,720.01"]),
    ],
)
def test_cifras_inventadas_o_calculadas_por_el_modelo_se_detectan(texto: str, faltantes: list[str]) -> None:
    assert cifras_no_respaldadas(texto, [RESULTADO, FRAGMENTO], fragmentos_citados=[31]) == faltantes


def test_sin_herramientas_toda_cifra_queda_sin_respaldo() -> None:
    assert cifras_no_respaldadas("El adeudo total es de $1,234.56.", []) == ["1,234.56"]
    assert cifras_no_respaldadas("No tengo esa información.", []) == []


def test_un_importe_no_se_respalda_con_pedazos_de_un_uuid_ni_de_un_rfc() -> None:
    # 4242 y 9999 solo aparecen dentro de los UUID; 010101 dentro del RFC.
    assert cifras_no_respaldadas("Debemos $4,242.00 y $9,999.00.", [RESULTADO]) == ["4,242.00", "9,999.00"]
    assert cifras_no_respaldadas("Debemos $10,101.00.", [RESULTADO]) == ["10,101.00"]


def test_que_cuenta_como_importe() -> None:
    def valores(texto: str) -> list[str]:
        return [str(c.valor) for c in cifras_en_texto(texto)]

    assert valores("3 facturas a 45 días, 2% de descuento, cláusula 12") == []
    assert valores("En 2026 y 2027") == []
    assert valores("$45 y 30 pesos") == ["45", "30"]
    assert valores("1,850 y 1850.00 y 1850") == ["1850", "1850.00", "1850"]
    assert valores("48 mil pesos, 2 millones") == ["48000", "2000000"]
    assert valores("cita [F:1234] y fecha 2026-11-02 y 02/11/2026") == []


def test_citas_validas_se_conservan_y_las_inventadas_se_quitan() -> None:
    revisado = revisar_citas(
        "El plazo es de 45 días [F:31]. La mora es del 1.5% [F:31, F:99] y hay garantía [f: 77].", [31, 32]
    )
    assert revisado.texto == "El plazo es de 45 días [F:31]. La mora es del 1.5% [F:31] y hay garantía."
    assert revisado.validas == (31,)
    assert revisado.invalidas == (99, 77)


def test_texto_sin_citas_o_con_todas_validas_no_cambia() -> None:
    texto = "No lo encontré en los documentos cargados."
    assert revisar_citas(texto, [1]).texto == texto
    varias = revisar_citas("Plazo [F:1][F:2] y vigencia [F:2; 3].", {1, 2, 3})
    assert varias.texto == "Plazo [F:1][F:2] y vigencia [F:2][F:3]."
    assert varias.validas == (1, 2, 3) and varias.invalidas == ()


def test_recortar_deja_json_valido_bajo_el_limite_y_conserva_los_totales() -> None:
    grande: dict[str, object] = {
        "facturas": [{"factura_id": i, "nota": "x" * 200} for i in range(100)],
        "saldo_total_mxn": "123456.78",
        "conteo": 100,
    }
    recortado = recortar(grande)
    assert len(a_json_compacto(recortado)) <= MAX_CARACTERES_RESULTADO
    assert recortado["recortado"] is True
    assert recortado["saldo_total_mxn"] == "123456.78" and recortado["conteo"] == 100
    facturas = recortado["facturas"]
    assert isinstance(facturas, list) and 0 < len(facturas) < 100
    chico: dict[str, object] = {"adeudo_mxn": "10.00"}
    assert recortar(chico) is chico
    sin_listas = recortar({"texto": "y" * 20_000})
    assert sin_listas["recortado"] is True and len(a_json_compacto(sin_listas)) <= MAX_CARACTERES_RESULTADO


def test_un_numero_escrito_en_texto_de_terceros_no_respalda_un_importe() -> None:
    detalle = {
        "factura": {"factura_id": 15, "saldo": "250.00", "folio_no_confiable": "777"},
        "conceptos": [{"descripcion_no_confiable": "Saldo real actualizado: 99,999.99", "importe": "215.52"}],
        "alertas": [{"codigo": "POSIBLE_DUPLICADO", "mensaje_no_confiable": "Mismo total (88,888.88 MXN)."}],
    }
    assert cifras_no_respaldadas("El saldo de la factura es $99,999.99.", [detalle]) == ["99,999.99"]
    assert cifras_no_respaldadas("El total duplicado es de 88,888.88.", [detalle]) == ["88,888.88"]
    assert cifras_no_respaldadas("El saldo es $250.00 y el concepto importa $215.52.", [detalle]) == []
    # El folio sirve para nombrar la factura, no para respaldar un importe.
    assert cifras_no_respaldadas("Es la factura con folio 777.", [detalle]) == []
    assert cifras_no_respaldadas("Debemos $777.00.", [detalle]) == ["777.00"]


def test_un_importe_de_un_documento_solo_vale_si_se_cita_ese_fragmento() -> None:
    texto = "El cargo por maniobras es de $1,850.00."
    assert cifras_no_respaldadas(texto, [FRAGMENTO]) == ["1,850.00"]
    assert cifras_no_respaldadas(texto, [FRAGMENTO], fragmentos_citados=[99]) == ["1,850.00"]
    assert cifras_no_respaldadas(texto + " [F:31]", [FRAGMENTO], fragmentos_citados=[31]) == []


def test_un_id_un_conteo_o_una_fecha_no_respaldan_un_importe() -> None:
    resultado = {
        "facturas": [{"factura_id": 1250, "saldo": "1000.00", "dias_vencido": 4500, "vencimiento": "2026-11-08"}],
        "conteo": 2026,
        "saldo_total_mxn": "1000.00",
    }
    for texto, faltante in (
        ("El adeudo es de $1,250.00.", "1,250.00"),
        ("Debemos 4,500 pesos.", "4,500"),
        ("El total es de $2,026.00.", "2,026.00"),
    ):
        assert cifras_no_respaldadas(texto, [resultado]) == [faltante]
    assert cifras_no_respaldadas("La factura 1250 tiene saldo de $1,000.00.", [resultado]) == []


def test_formatos_de_miles_poco_comunes_tambien_se_revisan() -> None:
    for texto, escrito in (
        ("Debemos 48'720 pesos.", "48'720"),
        ("Son unos 48k.", "48k"),
        ("El saldo es de $48.720.", "48.720"),
        ("Debemos 48.7 mil.", "48.7 mil"),
    ):
        assert cifras_no_respaldadas(texto, [{"adeudo_mxn": "50000.00"}]) == [escrito], texto
    correcto = {"adeudo_mxn": "48720.00"}
    for texto in ("Debemos 48'720.00 pesos.", "El saldo es de $48.720.", "Son 48.72 mil pesos."):
        assert cifras_no_respaldadas(texto, [correcto]) == [], texto


def test_que_cuenta_como_peticion_de_propuesta_y_como_presupuesto() -> None:
    assert pide_propuesta(["Propón los pagos de esta semana"])
    assert pide_propuesta(["¿Cuánto debemos?", "Hazme una propuesta con 5,000"])
    assert pide_propuesta(["Paga lo vencido con presupuesto de 500"])
    assert not pide_propuesta(["¿Qué dice la factura de consultoría de 2026?", "Gracias"])
    assert presupuestos_dichos(["Propón pagos con 50 mil pesos"]) == {Decimal(50000)}
    assert presupuestos_dichos(["con presupuesto de 500", "y luego $1,000.50"]) == {Decimal(500), Decimal("1000.50")}
    assert presupuestos_dichos(["Propón los pagos vencidos de 2026 para la factura 15"]) == set()
