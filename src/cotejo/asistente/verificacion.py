"""Verificación de la respuesta del modelo antes de entregarla (D1, D2) y de lo que pidió la persona.

Comprobaciones en código, sin otro modelo:

- Cada importe del texto debe estar en un campo de importe de algún resultado de herramienta de este turno. Un
  número que solo aparece en texto de terceros (un concepto, un nombre) no respalda nada, salvo que esté en un
  fragmento de documento que la respuesta cita. Un id, un folio o una fecha tampoco respaldan un importe.
- Cada cita debe apuntar a un fragmento devuelto en este turno; las demás se quitan del texto.
- Una propuesta solo procede si la persona la pidió y escribió el presupuesto en sus mensajes recientes.

Límite conocido: las cantidades escritas con palabras ("cuarenta y ocho mil") no se reconocen como importes.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from cotejo.documentos.normalizar import normalizar

CIFRA_NO_RESPALDADA = "CIFRA_NO_RESPALDADA"
CITA_INVALIDA = "CITA_INVALIDA"
LIMITE_PASOS = "LIMITE_PASOS"

_CITA = re.compile(r"\[\s*F\s*:\s*\d+(?:\s*[,;]\s*(?:F\s*:\s*)?\d+)*\s*\]", flags=re.IGNORECASE)
_UUID = re.compile(r"\b[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\b")
_FECHA = re.compile(r"\b\d{4}-\d{2}-\d{2}(?:T[\d:.+\-Z]+)?\b|\b\d{1,2}/\d{1,2}/\d{2,4}\b")
_EUROPEO_CON_CENTAVOS = re.compile(r"\d{1,3}(?:\.\d{3})+,\d{2}")
_PUNTOS_DE_MILLAR = re.compile(r"\d{1,3}(?:\.\d{3})+")
# Un número con sus separadores: 48,720.00, 48'720, 48720.5, 1,850 o, en formato europeo, 48.720,00.
_NUMERO = re.compile(
    r"(?<![\w.,'])"
    r"(?P<num>\d{1,3}(?:\.\d{3})+,\d{2}(?!\d)|\d{1,3}(?:[,']\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
    r"(?P<k>[kK](?!\w))?"
    r"(?![\w]|[.,']\d)"
)
_MONEDA_ANTES = re.compile(r"(?:\$|US\$|MXN|USD|MN)\s*$", flags=re.IGNORECASE)
_DESPUES = re.compile(
    r"^\s*(?:(?P<mult>mill[oó]n(?:es)?|miles|mil|mdp)\b)?\s*(?:de\s+)?(?P<moneda>pesos|mxn|usd|d[oó]lares|m\.n\.)?",
    flags=re.IGNORECASE,
)
_MULTIPLOS = {"mil": Decimal(1000), "miles": Decimal(1000), "mdp": Decimal(1_000_000)}
_UMBRAL_ENTERO = Decimal(1000)
_DOS_DECIMALES = Decimal("0.01")
# Campos de los resultados de herramientas que traen dinero calculado por la base.
_CLAVES_DE_IMPORTE = frozenset(
    {"saldo", "total", "importe", "subtotal", "impuestos_trasladados", "impuestos_retenidos"}
)
_SUFIJO_NO_CONFIABLE = "no_confiable"
# Texto de terceros que funciona como identificador: respalda que se mencione un folio, nunca un importe.
_CLAVES_DE_IDENTIFICADOR = frozenset({"folio_no_confiable", "serie_no_confiable"})
_INTENCION_DE_PROPUESTA = re.compile(r"\b(propon\w*|propong\w*|proponer\w*|propuesta\w*|presupuesto)\b")
_TRAS_PRESUPUESTO = re.compile(r"\bpresupuesto\b\D{0,25}$")


@dataclass(frozen=True)
class Cifra:
    """Un número encontrado en un texto: como se escribió, lo que puede valer y si se presenta como dinero."""

    escrito: str
    # Casi siempre un solo valor; "48.720" puede ser 48.72 o cuarenta y ocho mil setecientos veinte.
    valores: tuple[Decimal, ...]
    monetaria: bool
    # Verdadero si debe verificarse: es dinero o un entero de mil o más que no parece un año.
    es_importe: bool
    tras_presupuesto: bool = False

    @property
    def valor(self) -> Decimal:
        return self.valores[-1]


def _a_decimal(numero: str) -> Decimal | None:
    if _EUROPEO_CON_CENTAVOS.fullmatch(numero):
        limpio = numero.replace(".", "").replace(",", ".")
    else:
        limpio = numero.replace(",", "").replace("'", "")
    try:
        return Decimal(limpio)
    except InvalidOperation:
        return None


def _sin_identificadores(texto: str) -> str:
    """Quita lo que tiene dígitos pero no es una cantidad: citas, folios fiscales y fechas."""
    return _FECHA.sub(" ", _UUID.sub(" ", _CITA.sub(" ", texto)))


def _numeros(texto: str) -> list[Cifra]:
    """Todos los números de un texto, con "mil", "millones" y "k" ya aplicados."""
    limpio = _sin_identificadores(texto)
    encontrados: list[Cifra] = []
    for coincidencia in _NUMERO.finditer(limpio):
        numero = coincidencia.group("num")
        valor = _a_decimal(numero)
        if valor is None:
            continue
        escrito = numero
        antes = limpio[max(0, coincidencia.start() - 30) : coincidencia.start()]
        despues = _DESPUES.match(limpio[coincidencia.end() : coincidencia.end() + 24])
        multiplo = (despues.group("mult") or "").lower() if despues else ""
        con_moneda = bool(_MONEDA_ANTES.search(antes)) or bool(despues and despues.group("moneda"))
        valores = [valor]
        if _PUNTOS_DE_MILLAR.fullmatch(numero):
            # Tres decimales exactos: también puede ser un separador de miles a la europea.
            valores.append(Decimal(numero.replace(".", "")))
        if coincidencia.group("k"):
            valores = [v * 1000 for v in valores]
            escrito = f"{escrito}k"
        if multiplo:
            valores = [v * _MULTIPLOS.get(multiplo, Decimal(1_000_000)) for v in valores]
            escrito = f"{escrito} {multiplo}"
        con_miles = "," in numero or "'" in numero
        dos_decimales = re.search(r"[.,]\d{2}$", numero) is not None
        monetaria = con_moneda or bool(multiplo) or bool(coincidencia.group("k")) or con_miles or dos_decimales
        principal = valores[-1]
        es_entero = principal == principal.to_integral_value()
        parece_anio = es_entero and not monetaria and Decimal(1900) <= principal <= Decimal(2100)
        entero_grande = es_entero and principal >= _UMBRAL_ENTERO and not parece_anio
        encontrados.append(
            Cifra(
                escrito=escrito,
                valores=tuple(valores),
                monetaria=monetaria,
                es_importe=monetaria or entero_grande,
                tras_presupuesto=_TRAS_PRESUPUESTO.search(normalizar(antes)) is not None,
            )
        )
    return encontrados


def cifras_en_texto(texto: str) -> list[Cifra]:
    """Importes que afirma el texto.

    Cuenta como importe un número con signo de pesos o nombre de moneda, con separador de miles, con
    exactamente dos decimales, seguido de "mil", "millones" o "k", o un entero de mil o más que no parezca un
    año. Los enteros chicos sueltos (3 facturas, 45 días) no son importes.
    """
    return [c for c in _numeros(texto) if c.es_importe]


def numeros_en_texto(texto: str) -> set[Decimal]:
    """Todos los valores numéricos que aparecen en un texto, en cualquiera de sus lecturas."""
    return {valor for cifra in _numeros(texto) for valor in cifra.valores}


@dataclass
class _Respaldo:
    importes: set[Decimal] = field(default_factory=set)
    identificadores: set[Decimal] = field(default_factory=set)


def _recorrer(dato: object, clave: str, respaldo: _Respaldo, citados: Collection[int]) -> None:
    if isinstance(dato, Mapping):
        citado = dato.get("fragmento_id") in citados
        for nombre, valor in dato.items():
            nombre = str(nombre)
            if nombre.endswith(_SUFIJO_NO_CONFIABLE):
                if nombre in _CLAVES_DE_IDENTIFICADOR and isinstance(valor, str):
                    respaldo.identificadores |= numeros_en_texto(valor)
                elif citado and isinstance(valor, str):
                    # Un importe de un contrato vale si la respuesta cita el fragmento que lo dice.
                    respaldo.importes |= numeros_en_texto(valor)
                continue
            _recorrer(valor, nombre, respaldo, citados)
    elif isinstance(dato, str):
        if _FECHA.fullmatch(dato) or _UUID.fullmatch(dato):
            return
        valores = numeros_en_texto(dato)
        respaldo.identificadores |= valores
        if clave.endswith("_mxn") or clave in _CLAVES_DE_IMPORTE:
            respaldo.importes |= valores
    elif isinstance(dato, bool) or dato is None:
        return
    elif isinstance(dato, int | float | Decimal):
        respaldo.identificadores.add(Decimal(str(dato)))
    elif isinstance(dato, Sequence):
        for elemento in dato:
            _recorrer(elemento, clave, respaldo, citados)


def _esta(valor: Decimal, respaldo: set[Decimal], a_centavos: set[Decimal]) -> bool:
    return valor in respaldo or (valor == valor.quantize(_DOS_DECIMALES) and valor in a_centavos)


def cifras_no_respaldadas(
    texto: str, resultados: Sequence[Mapping[str, object]], fragmentos_citados: Collection[int] = ()
) -> list[str]:
    """Importes del texto que no salen de ningún resultado de herramienta del turno, como se escribieron.

    Un importe está respaldado si algún campo de importe trae ese mismo valor (48,720.00 y "48720.00" son el
    mismo), o si está en un fragmento de documento que la respuesta cita. Un total que el modelo sumó o
    redondeó por su cuenta, o un número copiado de un concepto de factura, no lo está.
    """
    respaldo = _Respaldo()
    for resultado in resultados:
        _recorrer(resultado, "", respaldo, fragmentos_citados)
    importes_a_centavos = {v.quantize(_DOS_DECIMALES) for v in respaldo.importes if v.is_finite()}
    cualquiera = respaldo.importes | respaldo.identificadores
    faltantes: list[str] = []
    for cifra in cifras_en_texto(texto):
        if cifra.monetaria:
            respaldada = any(_esta(v, respaldo.importes, importes_a_centavos) for v in cifra.valores)
        else:
            # Un entero suelto puede ser un folio o un id: basta con que venga de algún resultado.
            respaldada = any(v in cualquiera for v in cifra.valores)
        if not respaldada and cifra.escrito not in faltantes:
            faltantes.append(cifra.escrito)
    return faltantes


def pide_propuesta(mensajes: Iterable[str]) -> bool:
    """La persona habló de proponer pagos o de un presupuesto en alguno de esos mensajes."""
    return any(_INTENCION_DE_PROPUESTA.search(normalizar(m)) is not None for m in mensajes)


def presupuestos_dichos(mensajes: Iterable[str]) -> set[Decimal]:
    """Importes que la persona escribió y que pueden ser un presupuesto.

    Vale un importe reconocible (con moneda, separador de miles, decimales o de mil en adelante) o el número
    que sigue a la palabra "presupuesto". Un año o un número suelto no es un presupuesto.
    """
    dichos: set[Decimal] = set()
    for mensaje in mensajes:
        for cifra in _numeros(mensaje):
            if cifra.es_importe or cifra.tras_presupuesto:
                dichos.update(cifra.valores)
    return dichos


@dataclass(frozen=True)
class CitasRevisadas:
    texto: str
    validas: tuple[int, ...]
    invalidas: tuple[int, ...]


def revisar_citas(texto: str, fragmentos_del_turno: Iterable[int]) -> CitasRevisadas:
    """Deja en el texto solo las citas [F:id] a fragmentos devueltos en este turno; las demás se quitan."""
    permitidos = set(fragmentos_del_turno)
    validas: list[int] = []
    invalidas: list[int] = []

    def _reemplazo(coincidencia: re.Match[str]) -> str:
        conservadas: list[int] = []
        for numero in re.findall(r"\d+", coincidencia.group(0)):
            fragmento_id = int(numero)
            if fragmento_id in permitidos:
                conservadas.append(fragmento_id)
                if fragmento_id not in validas:
                    validas.append(fragmento_id)
            elif fragmento_id not in invalidas:
                invalidas.append(fragmento_id)
        return "".join(f"[F:{i}]" for i in conservadas)

    limpio = _CITA.sub(_reemplazo, texto)
    if invalidas:
        limpio = re.sub(r"[ \t]+([.,;:])", r"\1", re.sub(r"[ \t]{2,}", " ", limpio)).strip()
    return CitasRevisadas(texto=limpio, validas=tuple(validas), invalidas=tuple(invalidas))


def advertencia(codigo: str, mensaje: str) -> dict[str, str]:
    return {"codigo": codigo, "mensaje": mensaje}
