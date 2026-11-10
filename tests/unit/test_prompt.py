"""Instrucciones de sistema del asistente (D1, D2 y D4)."""

from __future__ import annotations

from datetime import date

from cotejo.asistente.herramientas import herramientas_por_nombre
from cotejo.asistente.prompt import prompt_de_sistema

HOY = date(2026, 11, 2)


def _prompt(rol: str) -> str:
    # El texto va partido en renglones; aquí importan las frases, no los saltos.
    return " ".join(prompt_de_sistema("Empresa Ficticia", HOY, rol).split())


def test_dice_el_rol_de_quien_pregunta() -> None:
    capturista = _prompt("capturista")
    aprobador = _prompt("aprobador")
    assert "tiene el rol capturista" in capturista
    assert "tiene el rol aprobador" in aprobador
    assert capturista != aprobador


def test_una_propuesta_solo_existe_si_la_creo_la_herramienta() -> None:
    texto = _prompt("aprobador")
    assert "Solo el rol capturista puede pedir una propuesta" in texto
    assert "nunca armes una lista de pagos por tu cuenta" in texto


def test_el_adeudo_de_un_proveedor_se_responde_con_sus_facturas() -> None:
    texto = _prompt("capturista")
    assert "usa adeudo_proveedor" in texto
    descripcion = herramientas_por_nombre()["buscar_proveedores"].descripcion
    assert "adeudo_proveedor" in descripcion


def test_sin_respuesta_en_documentos_no_se_cita() -> None:
    texto = _prompt("capturista")
    assert "No lo encontré en los documentos cargados." in texto
    assert "no cites fragmentos que no responden la pregunta" in texto


def test_lo_que_no_se_puede_hacer_desde_el_chat_dice_donde_se_hace() -> None:
    texto = _prompt("aprobador")
    assert "no puedes aprobar, rechazar, pagar, resolver alertas ni modificar datos" in texto
    assert '"No puedo hacer eso desde el chat."' in texto
    assert "aprobar y rechazar, en la pantalla Propuestas con rol aprobador" in texto
    assert "resolver alertas, en el detalle de la factura con rol aprobador" in texto


def test_el_adeudo_total_de_la_empresa_tiene_su_herramienta() -> None:
    assert "para el adeudo total de la empresa usa antiguedad_saldos" in _prompt("capturista")


def test_una_peticion_mixta_crea_la_propuesta_pendiente_y_aclara_el_resto() -> None:
    texto = _prompt("capturista")
    assert "crea la propuesta pendiente y aclara que lo demás no se puede" in texto
