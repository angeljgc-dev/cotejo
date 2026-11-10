"""RFC: formato oficial (patrón t_RFC del XSD del SAT) y dígito de verificación.

El algoritmo del dígito es el que usa la biblioteca python-stdnum (módulo 11 sobre un alfabeto de 38 símbolos).
No hay una fuente primaria del SAT accesible, y una parte pequeña de los RFC en uso no lo cumple; por eso un
dígito que no coincide produce una alerta y nunca un rechazo.
"""

from __future__ import annotations

import re

PATRON_RFC = re.compile(r"[A-Z&Ñ]{3,4}[0-9]{2}(0[1-9]|1[012])(0[1-9]|[12][0-9]|3[01])[A-Z0-9]{2}[0-9A]")
# Público en general y residentes en el extranjero: claves genéricas que no llevan dígito calculable.
GENERICOS = frozenset({"XAXX010101000", "XEXX010101000"})
_ALFABETO = "0123456789ABCDEFGHIJKLMN&OPQRSTUVWXYZ Ñ"


def normalizar(rfc: str) -> str:
    return rfc.strip().upper()


def formato_valido(rfc: str) -> bool:
    return PATRON_RFC.fullmatch(rfc) is not None


def digito_verificador(cuerpo: str) -> str:
    """Dígito que corresponde a los 11 o 12 caracteres previos de un RFC."""
    relleno = cuerpo.rjust(12)
    suma = sum(_ALFABETO.index(caracter) * (13 - posicion) for posicion, caracter in enumerate(relleno))
    return _ALFABETO[(11 - suma) % 11]


def digito_valido(rfc: str) -> bool | None:
    """True o False si se puede calcular; None si el formato es inválido o el RFC es genérico."""
    if rfc in GENERICOS or not formato_valido(rfc):
        return None
    return digito_verificador(rfc[:-1]) == rfc[-1]
