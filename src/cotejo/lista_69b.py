"""Lista 69-B del SAT (contribuyentes con operaciones presuntamente inexistentes).

Lee el CSV con las columnas del listado oficial, reemplaza la lista guardada y vuelve a evaluar a los
proveedores: abre una alerta bloqueante para los que aparecen como Presunto o Definitivo y cierra la de los que
ya no aparecen así. No se guarda el nombre del contribuyente, solo su RFC y su situación.
"""

from __future__ import annotations

import csv
import io
import unicodedata
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import delete, func, insert, select
from sqlalchemy.orm import Session

from cotejo.cfdi import codigos, rfc
from cotejo.cfdi.codigos import Motivo
from cotejo.cxp import alertas
from cotejo.modelos import Alerta, Lista69b, Proveedor

SITUACIONES = ("Presunto", "Definitivo", "Desvirtuado", "Sentencia Favorable")
SITUACIONES_QUE_BLOQUEAN = frozenset({"Presunto", "Definitivo"})
MAX_BYTES = 20 * 1024 * 1024
NOTA_CIERRE = "El proveedor ya no aparece como Presunto o Definitivo en la lista 69-B cargada."

_COLUMNA_RFC = "rfc"
_COLUMNA_SITUACION = "situacion del contribuyente"
_SITUACION_POR_CLAVE = {
    "presunto": "Presunto",
    "definitivo": "Definitivo",
    "desvirtuado": "Desvirtuado",
    "sentencia favorable": "Sentencia Favorable",
}


class CsvInvalido(Exception):
    def __init__(self, mensaje: str, *, linea: int, columna: str | None) -> None:
        super().__init__(mensaje)
        self.mensaje = mensaje
        self.linea = linea
        self.columna = columna


@dataclass(frozen=True)
class RegistroLista:
    rfc: str
    situacion: str


@dataclass(frozen=True)
class ResumenLista:
    registros: int
    por_situacion: dict[str, int]
    proveedores_afectados: int
    alertas_creadas: int
    alertas_cerradas: int
    cargado_en: datetime


def _clave(texto: str) -> str:
    """Minúsculas sin acentos ni espacios repetidos, para comparar encabezados y situaciones."""
    sin_acentos = "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn")
    return " ".join(sin_acentos.lower().split())


def _decodificar(contenido: bytes) -> str:
    # El listado oficial se publica en Latin-1; los archivos propios suelen venir en UTF-8.
    try:
        return contenido.decode("utf-8-sig")
    except UnicodeDecodeError:
        return contenido.decode("cp1252", errors="replace")


def leer_csv(contenido: bytes) -> list[RegistroLista]:
    """Registros del CSV. Acepta los renglones de título que el listado oficial trae antes del encabezado."""
    filas = list(csv.reader(io.StringIO(_decodificar(contenido), newline="")))
    indice_encabezado = None
    for indice, fila in enumerate(filas):
        if _COLUMNA_RFC in [_clave(celda) for celda in fila]:
            indice_encabezado = indice
            break
    if indice_encabezado is None:
        raise CsvInvalido("El archivo no tiene la columna RFC del listado 69-B.", linea=1, columna="RFC")
    encabezado = [_clave(celda) for celda in filas[indice_encabezado]]
    linea_encabezado = indice_encabezado + 1
    columna_rfc = encabezado.index(_COLUMNA_RFC)
    if _COLUMNA_SITUACION not in encabezado:
        raise CsvInvalido(
            "El archivo no tiene la columna Situación del contribuyente.",
            linea=linea_encabezado,
            columna="Situación del contribuyente",
        )
    columna_situacion = encabezado.index(_COLUMNA_SITUACION)

    registros: dict[str, RegistroLista] = {}
    for numero, fila in enumerate(filas[indice_encabezado + 1 :], start=linea_encabezado + 1):
        if not any(celda.strip() for celda in fila):
            continue
        if len(fila) <= max(columna_rfc, columna_situacion):
            faltante = "RFC" if len(fila) <= columna_rfc else "Situación del contribuyente"
            raise CsvInvalido(f"Al renglón {numero} le falta la columna {faltante}.", linea=numero, columna=faltante)
        clave_rfc = rfc.normalizar(fila[columna_rfc])
        if not clave_rfc:
            raise CsvInvalido(f"El renglón {numero} no tiene RFC.", linea=numero, columna="RFC")
        situacion = _SITUACION_POR_CLAVE.get(_clave(fila[columna_situacion]))
        if situacion is None:
            raise CsvInvalido(
                f"El renglón {numero} tiene una situación desconocida. Se esperaba una de: {', '.join(SITUACIONES)}.",
                linea=numero,
                columna="Situación del contribuyente",
            )
        registros[clave_rfc] = RegistroLista(rfc=clave_rfc, situacion=situacion)
    if not registros:
        raise CsvInvalido("El archivo no tiene ningún contribuyente.", linea=linea_encabezado + 1, columna="RFC")
    return list(registros.values())


def _mensaje(situacion: str) -> str:
    return (
        f"El proveedor aparece en la lista 69-B del SAT con situación {situacion}. No se puede proponer el pago de "
        "sus facturas mientras siga en la lista."
    )


def situacion_de(sesion: Session, clave_rfc: str) -> str | None:
    return sesion.execute(select(Lista69b.situacion).where(Lista69b.rfc == clave_rfc)).scalar_one_or_none()


def evaluar_proveedor(sesion: Session, proveedor: Proveedor) -> Motivo | None:
    """Abre la alerta del proveedor si está en la lista como Presunto o Definitivo. Se usa al registrar un CFDI."""
    situacion = situacion_de(sesion, proveedor.rfc)
    if situacion not in SITUACIONES_QUE_BLOQUEAN:
        return None
    detalle = {"rfc": proveedor.rfc, "situacion": situacion}
    alertas.abrir(
        sesion,
        codigo=codigos.LISTA_69B,
        severidad="bloqueante",
        mensaje=_mensaje(situacion),
        proveedor_id=proveedor.id,
        detalle=detalle,
        reabrir=True,
    )
    return codigos.alerta(codigos.LISTA_69B, _mensaje(situacion), detalle)


def reevaluar(sesion: Session) -> tuple[int, int, int]:
    """Alinea las alertas con la lista guardada. Devuelve (proveedores afectados, alertas creadas, cerradas)."""
    en_lista = sesion.execute(
        select(Proveedor.id, Proveedor.rfc, Lista69b.situacion)
        .join(Lista69b, Lista69b.rfc == Proveedor.rfc)
        .where(Lista69b.situacion.in_(SITUACIONES_QUE_BLOQUEAN))
        .order_by(Proveedor.id)
    ).all()
    creadas = 0
    for proveedor_id, clave_rfc, situacion in en_lista:
        nueva = alertas.abrir(
            sesion,
            codigo=codigos.LISTA_69B,
            severidad="bloqueante",
            mensaje=_mensaje(situacion),
            proveedor_id=proveedor_id,
            detalle={"rfc": clave_rfc, "situacion": situacion},
            reabrir=True,
        )
        creadas += int(nueva)
    afectados = [proveedor_id for proveedor_id, _, _ in en_lista]
    sobrantes = select(Alerta.id).where(
        Alerta.codigo == codigos.LISTA_69B, Alerta.estado == "abierta", Alerta.factura_id.is_(None)
    )
    if afectados:
        sobrantes = sobrantes.where(Alerta.proveedor_id.not_in(afectados))
    cerradas = alertas.cerrar_por_sistema(sesion, list(sesion.scalars(sobrantes)), NOTA_CIERRE)
    return len(afectados), creadas, cerradas


def cargar(sesion: Session, contenido: bytes, *, archivo: str, ahora: datetime) -> ResumenLista:
    """Reemplaza la lista completa y reevalúa a los proveedores, todo en la transacción en curso."""
    registros = leer_csv(contenido)
    sesion.execute(delete(Lista69b))
    sesion.execute(
        insert(Lista69b),
        [{"rfc": r.rfc, "situacion": r.situacion, "cargado_en": ahora, "archivo": archivo} for r in registros],
    )
    afectados, creadas, cerradas = reevaluar(sesion)
    por_situacion = dict.fromkeys(SITUACIONES, 0)
    for registro in registros:
        por_situacion[registro.situacion] += 1
    return ResumenLista(
        registros=len(registros),
        por_situacion=por_situacion,
        proveedores_afectados=afectados,
        alertas_creadas=creadas,
        alertas_cerradas=cerradas,
        cargado_en=ahora,
    )


@dataclass(frozen=True)
class EstadoLista:
    cargada: bool
    registros: int
    cargado_en: datetime | None
    archivo: str | None


def estado(sesion: Session) -> EstadoLista:
    registros, cargado_en, archivo = sesion.execute(
        select(func.count(), func.max(Lista69b.cargado_en), func.max(Lista69b.archivo))
    ).one()
    return EstadoLista(cargada=registros > 0, registros=registros, cargado_en=cargado_en, archivo=archivo)
