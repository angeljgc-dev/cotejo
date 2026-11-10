"""Crear, aprobar y rechazar propuestas de pago (D3, D4, D5).

Crear una propuesta nunca mueve dinero: deja renglones en estado `pendiente`. Aprobar es una operación aparte,
sin modelo de lenguaje, que solo puede hacer una persona con rol aprobador distinta de quien la pidió, y que
registra los pagos y actualiza los saldos en una sola transacción. La API, el asistente y el servidor MCP
pasan todos por estas mismas funciones.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from cotejo import bitacora
from cotejo.cxp import consultas, saldos
from cotejo.cxp.consultas import FacturaElegible
from cotejo.dinero import cuantizar, texto
from cotejo.fechas import HORIZONTES, rango_horizonte
from cotejo.modelos import Factura, Propuesta, RenglonPropuesta, Usuario
from cotejo.propuestas import barreras
from cotejo.propuestas.seleccion import Exclusion, Seleccion, seleccionar

Origen = Literal["asistente", "mcp", "api"]

MAX_FACTURAS_PEDIDAS = 100
PRESUPUESTO_MAXIMO = Decimal("999999999999.99")


class ErrorPropuesta(Exception):
    """Error del dominio de propuestas, con el estado HTTP y el código del contrato de la API."""

    def __init__(self, estado: int, codigo: str, mensaje: str, detalle: dict[str, object] | None = None) -> None:
        super().__init__(mensaje)
        self.estado = estado
        self.codigo = codigo
        self.mensaje = mensaje
        self.detalle: dict[str, object] = detalle or {}


def _exigir_rol(usuario: Usuario, rol: str, accion: str) -> None:
    # Se comprueba aquí además de en la ruta: ningún camino (asistente, MCP, API) puede saltárselo.
    if usuario.rol != rol or not usuario.activo:
        raise ErrorPropuesta(403, "ROL_INSUFICIENTE", f"{accion} es solo para el rol {rol}.")


def _validar_presupuesto(presupuesto_mxn: Decimal) -> Decimal:
    if not presupuesto_mxn.is_finite() or presupuesto_mxn <= 0:
        raise ErrorPropuesta(422, "PRESUPUESTO_INVALIDO", "El presupuesto debe ser mayor que cero.")
    if presupuesto_mxn != cuantizar(presupuesto_mxn) or presupuesto_mxn > PRESUPUESTO_MAXIMO:
        raise ErrorPropuesta(
            422, "PRESUPUESTO_INVALIDO", "El presupuesto debe ser un importe en pesos con máximo dos decimales."
        )
    return cuantizar(presupuesto_mxn)


def _fecha_de_corte(horizonte: str | None, fecha_limite: date | None, hoy: date) -> date:
    if horizonte is not None and fecha_limite is not None:
        raise ErrorPropuesta(422, "HORIZONTE_O_FECHA", "Indica un horizonte o una fecha límite, no ambos.")
    if horizonte is not None:
        if horizonte not in HORIZONTES:
            raise ErrorPropuesta(
                422, "HORIZONTE_INVALIDO", f"Horizonte desconocido. Opciones: {', '.join(HORIZONTES)}."
            )
        return rango_horizonte(horizonte, hoy)[1]
    if fecha_limite is not None:
        return fecha_limite
    return hoy


def _bloquear_facturas(sesion: Session, ids: Sequence[int]) -> None:
    """Bloquea las facturas en orden de id: dos operaciones simultáneas sobre la misma factura se ponen en fila."""
    if ids:
        sesion.execute(select(Factura.id).where(Factura.id.in_(ids)).order_by(Factura.id).with_for_update()).all()


def _candidatas(
    sesion: Session, *, hasta: date, factura_ids: Sequence[int] | None, hoy: date
) -> tuple[list[FacturaElegible], list[Exclusion]]:
    """Facturas a considerar, leídas con las filas bloqueadas, y las pedidas que no existen."""
    if factura_ids is not None:
        pedidas = list(dict.fromkeys(factura_ids))
    else:
        # Sin límite inferior: lo ya vencido también entra, y por orden de vencimiento va primero.
        pedidas = [f.factura_id for f in consultas.facturas_elegibles(sesion, hasta=hasta, ids=None, hoy=hoy)]
    _bloquear_facturas(sesion, pedidas)
    # Segunda lectura ya con el bloqueo: saldo, alertas y propuestas pendientes son los vigentes.
    actuales = consultas.facturas_elegibles(sesion, hasta=None, ids=pedidas, hoy=hoy) if pedidas else []
    encontradas = {f.factura_id for f in actuales}
    faltantes = [
        Exclusion(
            factura_id=i, codigo=barreras.FACTURA_NO_ENCONTRADA, motivo="No existe una factura con ese identificador."
        )
        for i in pedidas
        if i not in encontradas
    ]
    return actuales, faltantes


def crear_propuesta(
    sesion: Session,
    *,
    usuario: Usuario,
    presupuesto_mxn: Decimal,
    origen: Origen,
    hoy: date,
    horizonte: str | None = None,
    fecha_limite: date | None = None,
    factura_ids: Sequence[int] | None = None,
    mensaje_id: int | None = None,
    nota: str | None = None,
) -> Propuesta:
    """Arma una propuesta `pendiente` con las facturas que pasan las barreras y caben en el presupuesto.

    Las facturas las elige el código: todas las que tienen saldo y vencen a más tardar en la fecha de corte
    (incluidas las ya vencidas), o las `factura_ids` indicadas. No hace commit ni modifica ningún saldo.
    Lanza `ErrorPropuesta` (422 PROPUESTA_VACIA) si ninguna factura pasa las barreras.
    """
    _exigir_rol(usuario, "capturista", "Crear propuestas de pago")
    presupuesto = _validar_presupuesto(presupuesto_mxn)
    corte = _fecha_de_corte(horizonte, fecha_limite, hoy)
    if factura_ids is not None and len(factura_ids) > MAX_FACTURAS_PEDIDAS:
        raise ErrorPropuesta(
            422, "DEMASIADAS_FACTURAS", f"Una propuesta admite como máximo {MAX_FACTURAS_PEDIDAS} facturas."
        )

    candidatas, faltantes = _candidatas(sesion, hasta=corte, factura_ids=factura_ids, hoy=hoy)
    seleccion: Seleccion = seleccionar(candidatas, presupuesto, hoy)
    excluidas = [*seleccion.excluidas, *faltantes]
    if not seleccion.renglones:
        raise ErrorPropuesta(
            422,
            "PROPUESTA_VACIA",
            "Ninguna factura se puede incluir en la propuesta."
            if excluidas
            else "No hay facturas con saldo que venzan en ese periodo.",
            {"excluidas": [e.a_json() for e in excluidas], "presupuesto_mxn": texto(presupuesto)},
        )

    propuesta = Propuesta(
        estado="pendiente",
        presupuesto_mxn=presupuesto,
        total_mxn=seleccion.total_mxn,
        fecha_limite=corte,
        origen=origen,
        mensaje_id=mensaje_id,
        creada_por=usuario.id,
        excluidas=[e.a_json() for e in excluidas],
    )
    sesion.add(propuesta)
    sesion.flush()
    for elegido in seleccion.renglones:
        sesion.add(
            RenglonPropuesta(
                propuesta_id=propuesta.id,
                factura_id=elegido.factura.factura_id,
                importe=elegido.importe,
                importe_mxn=elegido.importe_mxn,
                razon=elegido.razon,
            )
        )
    bitacora.registrar(
        sesion,
        usuario_id=usuario.id,
        accion="PROPUESTA_CREADA",
        entidad="propuesta",
        entidad_id=propuesta.id,
        detalle={
            "origen": origen,
            "presupuesto_mxn": presupuesto,
            "total_mxn": seleccion.total_mxn,
            "fecha_limite": corte,
            "horizonte": horizonte,
            "nota": nota,
            "facturas": [r.factura.factura_id for r in seleccion.renglones],
            "excluidas": [{"factura_id": e.factura_id, "codigo": e.codigo} for e in excluidas],
        },
    )
    sesion.flush()
    sesion.refresh(propuesta, attribute_names=["renglones"])
    return propuesta


def _propuesta_bloqueada(sesion: Session, propuesta_id: int) -> Propuesta:
    propuesta = sesion.execute(
        select(Propuesta).where(Propuesta.id == propuesta_id).with_for_update()
    ).scalar_one_or_none()
    if propuesta is None:
        raise ErrorPropuesta(404, "PROPUESTA_NO_ENCONTRADA", "La propuesta no existe.")
    # Otra petición pudo decidirla mientras esta esperaba el bloqueo: se relee el estado vigente.
    sesion.refresh(propuesta)
    return propuesta


def _exigir_decision_valida(propuesta: Propuesta, usuario: Usuario, accion: str) -> None:
    _exigir_rol(usuario, "aprobador", accion)
    if propuesta.creada_por == usuario.id:
        raise ErrorPropuesta(
            403, "MISMO_USUARIO", "Quien pidió la propuesta no puede decidirla: debe hacerlo otra persona."
        )
    if propuesta.estado != "pendiente":
        raise ErrorPropuesta(
            409, "PROPUESTA_NO_PENDIENTE", f"La propuesta ya fue {propuesta.estado} y no se puede volver a decidir."
        )


def _renglones_invalidos(sesion: Session, propuesta: Propuesta, hoy: date) -> list[dict[str, object]]:
    """Vuelve a pasar cada renglón por las barreras contra el estado actual de la base."""
    renglones = list(propuesta.renglones)
    ids = [r.factura_id for r in renglones]
    _bloquear_facturas(sesion, ids)
    actuales = {f.factura_id: f for f in consultas.facturas_elegibles(sesion, hasta=None, ids=ids, hoy=hoy)}
    invalidos: list[dict[str, object]] = []
    total = Decimal(0)
    for renglon in renglones:
        factura = actuales.get(renglon.factura_id)
        if factura is None:
            invalidos.append(
                {
                    "renglon_id": renglon.id,
                    "codigo": barreras.FACTURA_NO_ENCONTRADA,
                    "motivo": "La factura ya no existe.",
                }
            )
            continue
        incumplimiento = barreras.revisar(factura, importe=renglon.importe, propuesta_propia=propuesta.id)
        if incumplimiento is not None:
            invalidos.append(
                {"renglon_id": renglon.id, "codigo": incumplimiento.codigo, "motivo": incumplimiento.motivo}
            )
        total += renglon.importe_mxn
    if total > propuesta.presupuesto_mxn and renglones:
        invalidos.append(
            {
                "renglon_id": renglones[-1].id,
                "codigo": barreras.EXCEDE_PRESUPUESTO,
                "motivo": "El total de la propuesta rebasa su presupuesto.",
            }
        )
    return invalidos


def aprobar(sesion: Session, *, propuesta_id: int, usuario: Usuario, hoy: date) -> Propuesta:
    """Aprueba la propuesta: registra un pago por renglón y actualiza los saldos, todo o nada. No hace commit.

    Si algún renglón ya no pasa las barreras (la factura se pagó, se bloqueó o su saldo bajó), no se aplica
    ninguno y se lanza `ErrorPropuesta` 409 RENGLONES_INVALIDOS con el detalle de cada uno.
    """
    propuesta = _propuesta_bloqueada(sesion, propuesta_id)
    _exigir_decision_valida(propuesta, usuario, "Aprobar propuestas")
    invalidos = _renglones_invalidos(sesion, propuesta, hoy)
    if invalidos:
        raise ErrorPropuesta(
            409,
            "RENGLONES_INVALIDOS",
            "La propuesta ya no se puede aprobar tal como está: algunos renglones dejaron de ser válidos. "
            "Recházala y pide una nueva.",
            {"renglones": invalidos},
        )
    try:
        # Savepoint: si un pago falla a la mitad, los anteriores se deshacen aquí mismo.
        with sesion.begin_nested():
            for renglon in propuesta.renglones:
                saldo_antes = saldos.saldo(sesion, renglon.factura_id, bloquear=True)
                saldos.aplicar(
                    sesion,
                    factura_id=renglon.factura_id,
                    importe=renglon.importe,
                    origen=saldos.ORIGEN_PROPUESTA,
                    fecha=hoy,
                    renglon_propuesta_id=renglon.id,
                    usuario_id=usuario.id,
                )
                bitacora.registrar(
                    sesion,
                    usuario_id=usuario.id,
                    accion="PAGO_REGISTRADO",
                    entidad="factura",
                    entidad_id=renglon.factura_id,
                    detalle={
                        "propuesta_id": propuesta.id,
                        "renglon_id": renglon.id,
                        "importe": renglon.importe,
                        "importe_mxn": renglon.importe_mxn,
                        "saldo_antes": cuantizar(saldo_antes),
                        "saldo_despues": cuantizar(saldo_antes - renglon.importe),
                    },
                )
            propuesta.estado = "aprobada"
            propuesta.decidida_por = usuario.id
            propuesta.decidida_en = datetime.now(UTC)
            bitacora.registrar(
                sesion,
                usuario_id=usuario.id,
                accion="PROPUESTA_APROBADA",
                entidad="propuesta",
                entidad_id=propuesta.id,
                detalle={
                    "total_mxn": propuesta.total_mxn,
                    "renglones": len(propuesta.renglones),
                    "creada_por": propuesta.creada_por,
                },
            )
            sesion.flush()
    except saldos.ErrorAplicacion as exc:
        sesion.refresh(propuesta)
        raise ErrorPropuesta(
            409,
            "RENGLONES_INVALIDOS",
            "No se aplicó ningún pago: un renglón dejó de ser válido mientras se aprobaba.",
            {"renglones": [{"renglon_id": None, "codigo": barreras.EXCEDE_SALDO, "motivo": str(exc)}]},
        ) from exc
    return propuesta


def rechazar(sesion: Session, *, propuesta_id: int, usuario: Usuario, motivo: str) -> Propuesta:
    """Rechaza la propuesta con un motivo. No toca saldos. No hace commit."""
    propuesta = _propuesta_bloqueada(sesion, propuesta_id)
    _exigir_decision_valida(propuesta, usuario, "Rechazar propuestas")
    motivo = motivo.strip()
    propuesta.estado = "rechazada"
    propuesta.motivo_rechazo = motivo
    propuesta.decidida_por = usuario.id
    propuesta.decidida_en = datetime.now(UTC)
    bitacora.registrar(
        sesion,
        usuario_id=usuario.id,
        accion="PROPUESTA_RECHAZADA",
        entidad="propuesta",
        entidad_id=propuesta.id,
        detalle={"motivo": motivo, "total_mxn": propuesta.total_mxn, "creada_por": propuesta.creada_por},
    )
    sesion.flush()
    return propuesta
