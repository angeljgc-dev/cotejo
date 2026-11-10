"""RFC ficticios para datos de demostración y pruebas.

Todos empiezan con ZZ para que se note que no son de contribuyentes reales. Tienen el formato de persona moral
(tres letras, fecha y homoclave) y su dígito de verificación es correcto, salvo que se pida lo contrario.
"""

from __future__ import annotations

from datetime import date

from cotejo.cfdi.rfc import digito_verificador

PREFIJO = "ZZ"
_LETRAS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
_HOMOCLAVE = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"


def rfc_moral(letra: str, fecha: date, homoclave: str, *, digito_correcto: bool = True) -> str:
    """RFC de persona moral `ZZ<letra><AAMMDD><homoclave><dígito>`."""
    if len(letra) != 1 or letra not in _LETRAS:
        raise ValueError("La tercera letra debe ser una mayúscula de la A a la Z.")
    if len(homoclave) != 2 or any(c not in _HOMOCLAVE for c in homoclave):
        raise ValueError("La homoclave son dos caracteres alfanuméricos.")
    cuerpo = f"{PREFIJO}{letra}{fecha:%y%m%d}{homoclave}"
    digito = digito_verificador(cuerpo)
    if not digito_correcto:
        # Cualquier otro dígito permitido por el formato: el RFC sigue pareciendo válido a simple vista.
        digito = next(d for d in "0123456789A" if d != digito)
    return cuerpo + digito


def es_ficticio(rfc: str) -> bool:
    return rfc.startswith(PREFIJO)
