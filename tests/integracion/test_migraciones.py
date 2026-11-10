"""G5: la migración 0001 crea exactamente el esquema de los modelos, y baja y sube en una base vacía."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Engine, create_engine, inspect, text

from cotejo import migraciones
from cotejo.modelos import Base
from tests.apoyo import pg_local

TABLAS = {
    "usuarios",
    "proveedores",
    "lista_69b",
    "cargas",
    "carga_archivos",
    "facturas",
    "conceptos",
    "factura_impuestos",
    "cfdi_relacionados",
    "doctos_pago",
    "aplicaciones",
    "alertas",
    "documentos",
    "fragmentos",
    "propuestas",
    "renglones_propuesta",
    "bitacora",
    "conversaciones",
    "mensajes_chat",
    "cuota_uso",
}


def _diferencias(motor: Engine) -> list[object]:
    with motor.connect() as conexion:
        contexto = MigrationContext.configure(conexion, opts={"compare_type": True})
        return list(compare_metadata(contexto, Base.metadata))


def test_modelos_y_migracion_coinciden(motor: Engine) -> None:
    assert _diferencias(motor) == []


def test_metadatos_tienen_todas_las_tablas_del_diseno() -> None:
    assert set(Base.metadata.tables) == TABLAS


def test_extension_indices_y_restricciones_existen(motor: Engine) -> None:
    insp = inspect(motor)
    assert set(insp.get_table_names()) >= TABLAS
    with motor.connect() as c:
        assert c.execute(text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")).scalar_one()
        definicion = c.execute(
            text("SELECT indexdef FROM pg_indexes WHERE indexname = 'ix_fragmentos_embedding_hnsw'")
        ).scalar_one()
        unicos = c.execute(
            text("SELECT indexdef FROM pg_indexes WHERE indexname = 'uq_aplicaciones_documento'")
        ).scalar_one()
        triggers = set(c.execute(text("SELECT tgname FROM pg_trigger WHERE NOT tgisinternal")).scalars())
    assert "hnsw" in definicion and "vector_cosine_ops" in definicion and "m='16'" in definicion
    assert "NULLS NOT DISTINCT" in unicos and "WHERE (origen_factura_id IS NOT NULL)" in unicos
    assert {"bitacora_solo_agregar", "propuestas_inmutables", "renglones_propuesta_inmutables"} <= triggers
    checks = {ck["name"] for ck in insp.get_check_constraints("aplicaciones")}
    assert {"ck_aplicaciones_coherencia_propuesta", "ck_aplicaciones_coherencia_documento"} <= checks


@pytest.fixture
def base_vacia(base_prueba: pg_local.BasePrueba) -> Iterator[str]:
    url_admin = pg_local.url_admin_de(base_prueba)
    url, nombre = pg_local.crear_base(url_admin, "cotejo_test_migra")
    try:
        yield url
    finally:
        pg_local.borrar_base(url_admin, nombre)


def test_arriba_abajo_arriba_en_base_vacia(base_vacia: str) -> None:
    motor = create_engine(base_vacia)
    try:
        migraciones.aplicar(base_vacia)
        assert set(inspect(motor).get_table_names()) >= TABLAS
        migraciones.revertir(base_vacia)
        restantes = set(inspect(motor).get_table_names()) - {"alembic_version"}
        assert restantes == set()
        with motor.connect() as c:
            assert c.execute(text("SELECT count(*) FROM pg_extension WHERE extname = 'vector'")).scalar_one() == 0
        migraciones.aplicar(base_vacia)
        assert _diferencias(motor) == []
    finally:
        motor.dispose()
