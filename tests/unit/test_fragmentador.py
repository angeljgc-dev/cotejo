"""C1 y C3 sin base: normalización, extracción de texto por página y partición en fragmentos."""

from __future__ import annotations

import pytest

from cotejo.documentos.extraccion import (
    EXPLICACION_ESCANEADO,
    DocumentoRechazado,
    extraer,
)
from cotejo.documentos.fragmentador import MAXIMO, RESTO_MINIMO, TRASLAPE, fragmentar_pagina
from cotejo.documentos.normalizar import normalizar, quitar_controles
from cotejo.documentos.pdf_simple import pdf_de_texto, pdf_escaneado

ORACION = "El cliente pagará cada factura dentro de los treinta días naturales siguientes a su recepción. "


def test_normalizar_quita_acentos_y_conserva_la_enie() -> None:
    assert normalizar("  GARANTÍA   de\nPingüinos, Año 2026 ") == "garantia de pinguinos, año 2026"
    assert normalizar("garantia") == normalizar("Garantía")
    assert normalizar("ano") != normalizar("año")


def test_quitar_controles_elimina_nulos_y_caracteres_invisibles() -> None:
    assert quitar_controles("a\x00b\u200bc\nd\te") == "abc\nd\te"


def test_texto_corto_es_un_solo_fragmento() -> None:
    assert fragmentar_pagina("  Plazo de pago:   30 días.  ") == ["Plazo de pago: 30 días."]
    assert fragmentar_pagina("   \n  ") == []


def test_fragmentos_respetan_el_maximo_y_se_traslapan() -> None:
    # Oraciones numeradas: cada traslape es único y el texto se puede reconstruir sin ambigüedad.
    texto = " ".join(f"La cláusula número {i} fija el plazo de pago de la factura {i * 7}." for i in range(1, 80))
    fragmentos = fragmentar_pagina(texto)
    assert len(fragmentos) > 3
    # El último puede absorber un resto corto; los demás nunca pasan del máximo.
    assert all(len(f) <= MAXIMO for f in fragmentos[:-1])
    assert len(fragmentos[-1]) <= MAXIMO + RESTO_MINIMO
    reconstruido = fragmentos[0]
    for fragmento in fragmentos[1:]:
        comun = next(
            n for n in range(min(len(reconstruido), len(fragmento)), 0, -1) if reconstruido.endswith(fragmento[:n])
        )
        assert 20 <= comun <= TRASLAPE, "cada fragmento empieza repitiendo el final del anterior"
        reconstruido += fragmento[comun:]
    assert reconstruido == texto, "quitando lo repetido por el traslape se recupera el texto completo"


def test_corta_en_fin_de_oracion_y_no_parte_palabras() -> None:
    fragmentos = fragmentar_pagina(ORACION * 30)
    for fragmento in fragmentos[:-1]:
        assert fragmento.endswith("."), fragmento[-40:]
    palabras = set((ORACION * 2).split())
    for fragmento in fragmentos:
        assert fragmento.split()[0] in palabras
        assert fragmento.split()[-1] in palabras


def test_prefiere_cortar_en_fin_de_parrafo() -> None:
    parrafo_a = ("Primera cláusula sobre el plazo de pago. " * 15).strip()
    parrafo_b = ("Segunda cláusula sobre la pena por mora. " * 15).strip()
    fragmentos = fragmentar_pagina(parrafo_a + "\n\n" + parrafo_b)
    assert fragmentos[0] == parrafo_a


def test_un_resto_corto_se_une_al_fragmento_anterior() -> None:
    texto = ORACION * 9 + "Cola breve."
    fragmentos = fragmentar_pagina(texto)
    assert fragmentos[-1].endswith("Cola breve.")
    assert len(fragmentos[-1]) >= RESTO_MINIMO


def test_pdf_de_dos_paginas_extrae_el_texto_de_cada_una_con_acentos() -> None:
    pdf = pdf_de_texto(["Página uno: garantía de doce meses.", "Página dos: pena por mora del 2% mensual."])
    extraido = extraer("pdf", pdf)
    assert not extraido.sin_texto
    assert len(extraido.paginas) == 2
    assert "garantía de doce meses" in extraido.paginas[0]
    assert "pena por mora del 2% mensual" in extraido.paginas[1]
    assert extraido.paginas_con_texto == [1, 2]


def test_pdf_escaneado_queda_sin_texto_con_explicacion() -> None:
    extraido = extraer("pdf", pdf_escaneado(paginas=2))
    assert extraido.sin_texto
    assert extraido.explicacion_sin_texto == EXPLICACION_ESCANEADO
    assert len(extraido.paginas) == 2
    assert extraido.paginas_con_texto == []


def test_pdf_danado_se_rechaza_sin_reventar() -> None:
    with pytest.raises(DocumentoRechazado) as info:
        extraer("pdf", b"%PDF-1.4\nesto no es un pdf de verdad")
    assert info.value.codigo == "PDF_ILEGIBLE"


def test_texto_plano_cuenta_como_una_pagina_y_acepta_bom() -> None:
    extraido = extraer("md", "\ufeff# Política de pagos\n\nSe paga los viernes.".encode())
    assert extraido.paginas == ("# Política de pagos\n\nSe paga los viernes.",)


def test_texto_que_no_es_utf8_se_rechaza() -> None:
    with pytest.raises(DocumentoRechazado) as info:
        extraer("txt", "Política de pagos".encode("latin-1"))
    assert info.value.codigo == "TEXTO_NO_UTF8"


def test_texto_en_blanco_queda_sin_texto() -> None:
    assert extraer("txt", b"   \n\n  ").sin_texto
