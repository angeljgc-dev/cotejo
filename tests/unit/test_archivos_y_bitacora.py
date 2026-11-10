"""Lectura segura de subidas (A6) y conversión del detalle de bitácora."""

from __future__ import annotations

import asyncio
import hashlib
import io
import uuid
from datetime import date, datetime
from decimal import Decimal

import pytest
from fastapi import UploadFile

from cotejo.bitacora import a_json
from cotejo.seguridad.archivos import (
    EXTENSIONES_CFDI,
    EXTENSIONES_DOCUMENTO,
    ArchivoRechazado,
    ArchivoSubido,
    leer_subida,
    nombre_para_mostrar,
)


def _leer(nombre: str | None, contenido: bytes, permitidas: frozenset[str], limite: int) -> ArchivoSubido:
    return asyncio.run(leer_subida(UploadFile(io.BytesIO(contenido), filename=nombre), permitidas, limite))


def test_lee_archivo_permitido_con_hash() -> None:
    subido = _leer("Factura A-1.XML", b"<x/>", EXTENSIONES_CFDI, 100)
    assert subido.nombre == "Factura A-1.XML"
    assert subido.extension == ".xml"
    assert subido.contenido == b"<x/>"
    assert subido.sha256 == hashlib.sha256(b"<x/>").hexdigest()


@pytest.mark.parametrize(
    ("nombre", "contenido", "permitidas", "limite", "codigo"),
    [
        ("factura.exe", b"MZ", EXTENSIONES_CFDI, 100, "EXTENSION_NO_PERMITIDA"),
        ("factura", b"<x/>", EXTENSIONES_CFDI, 100, "EXTENSION_NO_PERMITIDA"),
        ("factura.xml.exe", b"<x/>", EXTENSIONES_CFDI, 100, "EXTENSION_NO_PERMITIDA"),
        ("vacia.xml", b"", EXTENSIONES_CFDI, 100, "ARCHIVO_VACIO"),
        ("grande.xml", b"x" * 101, EXTENSIONES_CFDI, 100, "ARCHIVO_DEMASIADO_GRANDE"),
        ("falso.pdf", b"<html>", EXTENSIONES_DOCUMENTO, 100, "FIRMA_INVALIDA"),
    ],
)
def test_rechazos(nombre: str, contenido: bytes, permitidas: frozenset[str], limite: int, codigo: str) -> None:
    with pytest.raises(ArchivoRechazado) as exc:
        _leer(nombre, contenido, permitidas, limite)
    assert exc.value.codigo == codigo
    assert exc.value.mensaje


def test_justo_en_el_limite_se_acepta() -> None:
    assert len(_leer("a.xml", b"x" * 100, EXTENSIONES_CFDI, 100).contenido) == 100


def test_archivo_enorme_no_se_lee_completo() -> None:
    flujo = io.BytesIO(b"x" * (5 * 1024 * 1024))
    with pytest.raises(ArchivoRechazado):
        asyncio.run(leer_subida(UploadFile(flujo, filename="a.xml"), EXTENSIONES_CFDI, 1024))
    assert flujo.tell() == 1025


def test_pdf_valido() -> None:
    assert _leer("contrato.pdf", b"%PDF-1.7\n...", EXTENSIONES_DOCUMENTO, 100).extension == ".pdf"


@pytest.mark.parametrize(
    ("nombre", "esperado"),
    [
        ("../../etc/passwd.xml", "passwd.xml"),
        ("C:\\Windows\\system32\\a.xml", "a.xml"),
        ("ma\x00la\x1b.xml", "mala.xml"),
        (None, "sin_nombre"),
        ("", "sin_nombre"),
    ],
)
def test_nombre_para_mostrar(nombre: str | None, esperado: str) -> None:
    assert nombre_para_mostrar(nombre) == esperado


def test_bitacora_guarda_valores_exactos_como_texto() -> None:
    valor = a_json(
        {
            "importe": Decimal("1160.10"),
            "dia": date(2026, 11, 2),
            "momento": datetime.fromisoformat("2026-11-02T10:00:00-06:00"),
            "uuid": uuid.UUID(int=1),
            "lista": (1, "a", None),
            "anidado": {"x": Decimal("0.000001")},
        }
    )
    assert valor == {
        "importe": "1160.10",
        "dia": "2026-11-02",
        "momento": "2026-11-02T10:00:00-06:00",
        "uuid": "00000000-0000-0000-0000-000000000001",
        "lista": [1, "a", None],
        "anidado": {"x": "0.000001"},
    }


def test_bitacora_rechaza_tipos_desconocidos() -> None:
    with pytest.raises(TypeError):
        a_json({"x": object()})
