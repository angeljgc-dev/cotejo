"""A8 (lector): CSV con el formato oficial del SAT y el ficticio de la demostración."""

from __future__ import annotations

import pytest

from cotejo import lista_69b
from cotejo.semilla import catalogo

ENCABEZADO_OFICIAL = "No,RFC,Nombre del Contribuyente,Situación del contribuyente,Número y fecha de oficio\n"


def test_lista_ficticia_con_renglones_de_titulo() -> None:
    registros = lista_69b.leer_csv(catalogo.lista_69b_csv())
    assert {r.rfc: r.situacion for r in registros} == {r: s for r, _, s in catalogo.renglones_lista()}


def test_formato_oficial_en_latin1_sin_acentos_ni_mayusculas() -> None:
    contenido = (
        "Listado completo de contribuyentes\n"
        + ENCABEZADO_OFICIAL.replace("Situación", "SITUACION")
        + "1,ZZA010101AA8,Ficticio Uno,PRESUNTO,x\n"
        + "2,zzb020202bb1,Ficticio Dos,Sentencia favorable,x\n"
        + "\n"
    ).encode("cp1252")
    registros = lista_69b.leer_csv(contenido)
    assert [(r.rfc, r.situacion) for r in registros] == [
        ("ZZA010101AA8", "Presunto"),
        ("ZZB020202BB1", "Sentencia Favorable"),
    ]


def test_rfc_repetido_gana_el_ultimo() -> None:
    contenido = (ENCABEZADO_OFICIAL + "1,ZZA010101AA8,X,Presunto,\n2,ZZA010101AA8,X,Desvirtuado,\n").encode()
    assert [r.situacion for r in lista_69b.leer_csv(contenido)] == ["Desvirtuado"]


@pytest.mark.parametrize(
    ("contenido", "linea", "columna"),
    [
        (b"No,Nombre\n1,X\n", 1, "RFC"),
        (b"No,RFC,Nombre\n1,ZZA010101AA8,X\n", 1, "Situación del contribuyente"),
        ((ENCABEZADO_OFICIAL + "1,ZZA010101AA8,X,Inventada,\n").encode(), 2, "Situación del contribuyente"),
        ((ENCABEZADO_OFICIAL + "1\n").encode(), 2, "RFC"),
        (ENCABEZADO_OFICIAL.encode(), 2, "RFC"),
    ],
)
def test_csv_invalido_dice_linea_y_columna(contenido: bytes, linea: int, columna: str) -> None:
    with pytest.raises(lista_69b.CsvInvalido) as info:
        lista_69b.leer_csv(contenido)
    assert (info.value.linea, info.value.columna) == (linea, columna)
