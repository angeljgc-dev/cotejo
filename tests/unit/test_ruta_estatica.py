"""La ruta de un archivo estático se valida como texto antes de tocar el disco."""

from __future__ import annotations

import pytest

from cotejo.api.app import es_ruta_estatica_segura


@pytest.mark.parametrize("ruta", ["index.html", "assets/app.js", "assets/fuentes/a-b_c.woff2", "favicon.svg"])
def test_acepta_rutas_relativas_simples(ruta: str) -> None:
    assert es_ruta_estatica_segura(ruta)


@pytest.mark.parametrize(
    "ruta",
    [
        "",
        "/servidor/recurso/archivo.txt",  # llega así cuando piden //servidor/recurso/archivo.txt
        "//servidor/recurso/archivo.txt",
        "\\\\servidor\\recurso\\archivo.txt",
        "assets\\app.js",
        "C:/Windows/win.ini",
        "assets/C:archivo",
        "../secreto.txt",
        "assets/../../secreto.txt",
        "assets/./app.js",
        "assets//app.js",
        "assets/app.js\x00.png",
    ],
)
def test_rechaza_rutas_absolutas_de_red_o_con_saltos(ruta: str) -> None:
    assert not es_ruta_estatica_segura(ruta)
