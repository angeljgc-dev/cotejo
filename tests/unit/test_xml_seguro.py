"""A6: XML malicioso. Ningún archivo local se lee, no hay red y la memoria no se dispara (medida en otro proceso)."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest
from lxml import etree

from cotejo.cfdi import parser, xml_seguro
from tests.apoyo.cfdi import FIXTURES

MALICIOSOS = FIXTURES / "maliciosos"
CENTINELA = "CENTINELA-QUE-NO-DEBE-APARECER-7f3a"
BUENO = (FIXTURES / "validos" / "ingreso_mxn.xml").read_bytes()
# Margen de memoria por archivo: un CFDI legítimo de 2 MB cabe con mucho; una expansión de entidades no.
LIMITE_MEMORIA_MB = 40

# Proceso aparte: mide el pico de memoria del proceso antes y después de leer cada archivo.
_MEDIDOR = r"""
import json, sys, time
from pathlib import Path

def pico():
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes
        class Contadores(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                        ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]
        c = Contadores(); c.cb = ctypes.sizeof(c)
        proceso = ctypes.windll.kernel32.GetCurrentProcess()
        ctypes.windll.psapi.GetProcessMemoryInfo(proceso, ctypes.byref(c), c.cb)
        return c.PeakWorkingSetSize
    import resource
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024

from lxml import etree
from cotejo.cfdi import parser, xml_seguro
modo, ruta = sys.argv[1], sys.argv[2]
datos = Path(ruta).read_bytes()
antes = pico()
t = time.perf_counter()
codigo = "ACEPTADO"
if modo == "cotejo":
    try:
        parser.leer(datos)
    except (xml_seguro.XmlRechazado, parser.CfdiRechazado) as exc:
        codigo = exc.codigo
else:
    lector = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False, dtd_validation=False,
                             huge_tree=False, remove_comments=True, remove_pis=True, collect_ids=False)
    try:
        etree.fromstring(datos, lector)
    except etree.XMLSyntaxError:
        codigo = "XMLSyntaxError"
print(json.dumps({"codigo": codigo, "mb": (pico() - antes) / 2**20, "ms": (time.perf_counter() - t) * 1000}))
"""


def _medir(modo: str, ruta: Path) -> dict[str, float | str]:
    salida = subprocess.run(
        [sys.executable, "-c", _MEDIDOR, modo, str(ruta)], capture_output=True, text=True, check=True, timeout=60
    )
    resultado: dict[str, float | str] = json.loads(salida.stdout)
    return resultado


@pytest.fixture
def xxe_local(tmp_path: Path) -> bytes:
    secreto = tmp_path / "secreto.txt"
    secreto.write_text(CENTINELA, encoding="utf-8")
    plantilla = (MALICIOSOS / "xxe_archivo_local.xml").read_bytes()
    return plantilla.replace(b"file:///RUTA_DEL_CENTINELA", secreto.as_uri().encode())


def _rechazo(datos: bytes) -> xml_seguro.XmlRechazado:
    with pytest.raises(xml_seguro.XmlRechazado) as info:
        xml_seguro.parsear(datos)
    return info.value


def test_xxe_a_archivo_local_se_rechaza_sin_leerlo(xxe_local: bytes) -> None:
    exc = _rechazo(xxe_local)
    assert exc.codigo == "XML_DTD_PROHIBIDO"
    assert CENTINELA not in exc.mensaje


def test_xxe_en_utf16_tambien_se_rechaza(xxe_local: bytes) -> None:
    utf16 = xxe_local.decode("utf-8").replace("UTF-8", "UTF-16").encode("utf-16")
    assert _rechazo(utf16).codigo == "XML_DTD_PROHIBIDO"
    assert _rechazo(xxe_local.replace(b"<!DOCTYPE", b"<!doctype")).codigo == "XML_DTD_PROHIBIDO"


def test_segunda_capa_sola_tampoco_expande_la_entidad(xxe_local: bytes) -> None:
    """Sin el rechazo previo, el lector endurecido no lee el archivo: el centinela no aparece en ningún lado."""
    lector = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False, huge_tree=False)
    with pytest.raises(etree.XMLSyntaxError) as info:
        etree.fromstring(xxe_local, lector)
    assert "external entity" in str(info.value)
    assert CENTINELA not in str(info.value)


@pytest.mark.parametrize("nombre", ["xxe_red.xml", "dtd_externo.xml", "bomba_expansion.xml"])
def test_dtd_red_y_bomba_se_rechazan(nombre: str) -> None:
    assert _rechazo((MALICIOSOS / nombre).read_bytes()).codigo == "XML_DTD_PROHIBIDO"


def test_bom_utf16_valido_se_acepta() -> None:
    utf16 = BUENO.decode("utf-8").replace("UTF-8", "UTF-16").encode("utf-16")
    assert parser.leer(utf16).uuid == parser.leer(BUENO).uuid


def test_atributo_enorme_dentro_del_limite_se_procesa_en_tiempo_acotado() -> None:
    inicio = time.perf_counter()
    with pytest.raises(parser.CfdiRechazado):
        parser.leer(b'<a b="' + b"x" * 1_900_000 + b'"/>')
    assert time.perf_counter() - inicio < 1.0


@pytest.mark.parametrize("nombre", ["bomba_expansion.xml", "xxe_red.xml", "dtd_externo.xml"])
def test_memoria_acotada_con_xml_malicioso(nombre: str) -> None:
    con_cotejo = _medir("cotejo", MALICIOSOS / nombre)
    assert con_cotejo["codigo"] == "XML_DTD_PROHIBIDO"
    assert float(con_cotejo["mb"]) < LIMITE_MEMORIA_MB, con_cotejo
    # Aun sin la primera capa, el lector de lxml corta la expansión antes de agotar la memoria.
    solo_lector = _medir("lector", MALICIOSOS / nombre)
    assert float(solo_lector["mb"]) < LIMITE_MEMORIA_MB, solo_lector


def test_memoria_acotada_con_atributo_enorme(tmp_path: Path) -> None:
    ruta = tmp_path / "enorme.xml"
    ruta.write_bytes(b'<a b="' + b"x" * 1_900_000 + b'"/>')
    medido = _medir("cotejo", ruta)
    assert float(medido["mb"]) < LIMITE_MEMORIA_MB, medido
