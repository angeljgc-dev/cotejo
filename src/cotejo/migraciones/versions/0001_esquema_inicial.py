"""Esquema inicial completo: extensión vector, todas las tablas, índices, restricciones y triggers.

Revision ID: 0001
Revises:
Create Date: 2026-11-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# La bitácora solo admite INSERT. TRUNCATE no dispara triggers de renglón: el reinicio de la demo lo usa a propósito.
# Una propuesta decidida (aprobada o rechazada) y sus renglones ya no se modifican ni se borran.
TRIGGERS = (
    """
    CREATE FUNCTION bitacora_solo_agregar() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        RAISE EXCEPTION 'La bitácora solo admite agregar registros (operación % rechazada).', TG_OP;
    END;
    $$
    """,
    """
    CREATE TRIGGER bitacora_solo_agregar BEFORE UPDATE OR DELETE ON bitacora
    FOR EACH ROW EXECUTE FUNCTION bitacora_solo_agregar()
    """,
    """
    CREATE FUNCTION propuestas_inmutables() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        IF OLD.estado <> 'pendiente' THEN
            RAISE EXCEPTION 'La propuesta % ya fue decidida (%) y no se modifica.', OLD.id, OLD.estado;
        END IF;
        IF TG_OP = 'DELETE' THEN
            RETURN OLD;
        END IF;
        RETURN NEW;
    END;
    $$
    """,
    """
    CREATE TRIGGER propuestas_inmutables BEFORE UPDATE OR DELETE ON propuestas
    FOR EACH ROW EXECUTE FUNCTION propuestas_inmutables()
    """,
    """
    CREATE FUNCTION renglones_propuesta_inmutables() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE
        estado_actual text;
        id_propuesta bigint;
    BEGIN
        IF TG_OP = 'INSERT' THEN
            id_propuesta := NEW.propuesta_id;
        ELSE
            id_propuesta := OLD.propuesta_id;
        END IF;
        SELECT estado INTO estado_actual FROM propuestas WHERE id = id_propuesta;
        IF estado_actual IS DISTINCT FROM 'pendiente' THEN
            RAISE EXCEPTION 'Los renglones de la propuesta % no se modifican: está %.', id_propuesta, estado_actual;
        END IF;
        IF TG_OP = 'DELETE' THEN
            RETURN OLD;
        END IF;
        RETURN NEW;
    END;
    $$
    """,
    """
    CREATE TRIGGER renglones_propuesta_inmutables BEFORE INSERT OR UPDATE OR DELETE ON renglones_propuesta
    FOR EACH ROW EXECUTE FUNCTION renglones_propuesta_inmutables()
    """,
)

QUITAR_TRIGGERS = (
    "DROP TRIGGER IF EXISTS renglones_propuesta_inmutables ON renglones_propuesta",
    "DROP FUNCTION IF EXISTS renglones_propuesta_inmutables()",
    "DROP TRIGGER IF EXISTS propuestas_inmutables ON propuestas",
    "DROP FUNCTION IF EXISTS propuestas_inmutables()",
    "DROP TRIGGER IF EXISTS bitacora_solo_agregar ON bitacora",
    "DROP FUNCTION IF EXISTS bitacora_solo_agregar()",
)


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "cuota_uso",
        sa.Column("clave", sa.Text(), nullable=False),
        sa.Column("dia", sa.Date(), nullable=False),
        sa.Column("contador", sa.Integer(), nullable=False),
        sa.CheckConstraint("contador >= 0", name=op.f("ck_cuota_uso_contador_no_negativo")),
        sa.PrimaryKeyConstraint("clave", "dia", name=op.f("pk_cuota_uso")),
    )
    op.create_table(
        "lista_69b",
        sa.Column("rfc", sa.Text(), nullable=False),
        sa.Column("situacion", sa.Text(), nullable=False),
        sa.Column("cargado_en", sa.DateTime(timezone=True), nullable=False),
        sa.Column("archivo", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "situacion in ('Presunto','Definitivo','Desvirtuado','Sentencia Favorable')",
            name=op.f("ck_lista_69b_situacion_valida"),
        ),
        sa.PrimaryKeyConstraint("rfc", name=op.f("pk_lista_69b")),
    )
    op.create_table(
        "proveedores",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("rfc", sa.Text(), nullable=False),
        sa.Column("nombre", sa.Text(), nullable=False),
        sa.Column("dias_credito", sa.Integer(), server_default=sa.text("30"), nullable=False),
        sa.Column("rfc_formato_valido", sa.Boolean(), nullable=False),
        sa.Column("rfc_digito_valido", sa.Boolean(), nullable=True),
        sa.Column("creado_en", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("actualizado_en", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("dias_credito between 0 and 365", name=op.f("ck_proveedores_dias_credito_rango")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_proveedores")),
        sa.UniqueConstraint("rfc", name=op.f("uq_proveedores_rfc")),
    )
    op.create_table(
        "usuarios",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("usuario", sa.Text(), nullable=False),
        sa.Column("nombre", sa.Text(), nullable=False),
        sa.Column("rol", sa.Text(), nullable=False),
        sa.Column("hash_contrasena", sa.Text(), nullable=True),
        sa.Column("es_demo", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("activo", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("creado_en", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("rol in ('capturista','aprobador')", name=op.f("ck_usuarios_rol_valido")),
        sa.CheckConstraint("usuario ~ '^[a-z0-9._-]{3,40}$'", name=op.f("ck_usuarios_usuario_formato")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_usuarios")),
        sa.UniqueConstraint("usuario", name=op.f("uq_usuarios_usuario")),
    )
    op.create_table(
        "bitacora",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("ocurrido_en", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("usuario_id", sa.BigInteger(), nullable=True),
        sa.Column("accion", sa.Text(), nullable=False),
        sa.Column("entidad", sa.Text(), nullable=False),
        sa.Column("entidad_id", sa.Text(), nullable=True),
        sa.Column(
            "detalle", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.CheckConstraint(
            "accion in ('SESION_INICIADA','CARGA_CFDI','CARGA_DOCUMENTO','LISTA_69B_CARGADA','PROVEEDOR_EDITADO',"
            "'ALERTA_RESUELTA','PROPUESTA_CREADA','PROPUESTA_APROBADA','PROPUESTA_RECHAZADA','PAGO_REGISTRADO',"
            "'DEMO_REINICIADA')",
            name=op.f("ck_bitacora_accion_valida"),
        ),
        sa.ForeignKeyConstraint(["usuario_id"], ["usuarios.id"], name=op.f("fk_bitacora_usuario_id_usuarios")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_bitacora")),
    )
    op.create_index("ix_bitacora_entidad", "bitacora", ["entidad", "entidad_id"], unique=False)
    op.create_index("ix_bitacora_ocurrido_en", "bitacora", [sa.literal_column("ocurrido_en DESC")], unique=False)
    op.create_table(
        "cargas",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("usuario_id", sa.BigInteger(), nullable=False),
        sa.Column("tipo", sa.Text(), nullable=False),
        sa.Column("creado_en", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("tipo in ('cfdi','documento','lista_69b')", name=op.f("ck_cargas_tipo_valido")),
        sa.ForeignKeyConstraint(["usuario_id"], ["usuarios.id"], name=op.f("fk_cargas_usuario_id_usuarios")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_cargas")),
    )
    op.create_table(
        "conversaciones",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("usuario_id", sa.BigInteger(), nullable=False),
        sa.Column("visitante", sa.Text(), nullable=False),
        sa.Column("creado_en", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["usuario_id"], ["usuarios.id"], name=op.f("fk_conversaciones_usuario_id_usuarios")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_conversaciones")),
    )
    op.create_index("ix_conversaciones_usuario", "conversaciones", ["usuario_id"], unique=False)
    op.create_table(
        "documentos",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("nombre", sa.Text(), nullable=False),
        sa.Column("tipo", sa.Text(), nullable=False),
        sa.Column("sha256", sa.CHAR(length=64), nullable=False),
        sa.Column("proveedor_id", sa.BigInteger(), nullable=True),
        sa.Column("paginas", sa.Integer(), nullable=False),
        sa.Column("estado", sa.Text(), nullable=False),
        sa.Column("explicacion", sa.Text(), nullable=True),
        sa.Column("subido_por", sa.BigInteger(), nullable=False),
        sa.Column("creado_en", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "estado <> 'sin_texto' or explicacion is not null", name=op.f("ck_documentos_sin_texto_explicado")
        ),
        sa.CheckConstraint("estado in ('indexado','sin_texto')", name=op.f("ck_documentos_estado_valido")),
        sa.CheckConstraint("tipo in ('pdf','txt','md')", name=op.f("ck_documentos_tipo_valido")),
        sa.CheckConstraint("paginas >= 0", name=op.f("ck_documentos_paginas_no_negativas")),
        sa.ForeignKeyConstraint(
            ["proveedor_id"], ["proveedores.id"], name=op.f("fk_documentos_proveedor_id_proveedores")
        ),
        sa.ForeignKeyConstraint(["subido_por"], ["usuarios.id"], name=op.f("fk_documentos_subido_por_usuarios")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_documentos")),
        sa.UniqueConstraint("sha256", name=op.f("uq_documentos_sha256")),
    )
    op.create_table(
        "carga_archivos",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("carga_id", sa.BigInteger(), nullable=False),
        sa.Column("nombre_archivo", sa.Text(), nullable=False),
        sa.Column("sha256", sa.CHAR(length=64), nullable=False),
        sa.Column("tamano_bytes", sa.Integer(), nullable=False),
        sa.Column("resultado", sa.Text(), nullable=False),
        sa.Column(
            "motivos", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False
        ),
        sa.Column("factura_id", sa.BigInteger(), nullable=True),
        sa.Column("documento_id", sa.BigInteger(), nullable=True),
        sa.Column("creado_en", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "resultado in ('aceptada','aceptada_con_alertas','rechazada','duplicada','indexado','sin_texto')",
            name=op.f("ck_carga_archivos_resultado_valido"),
        ),
        sa.ForeignKeyConstraint(
            ["carga_id"], ["cargas.id"], name=op.f("fk_carga_archivos_carga_id_cargas"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["documento_id"], ["documentos.id"], name=op.f("fk_carga_archivos_documento_id_documentos")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_carga_archivos")),
    )
    op.create_index("ix_carga_archivos_carga", "carga_archivos", ["carga_id"], unique=False)
    op.create_table(
        "fragmentos",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("documento_id", sa.BigInteger(), nullable=False),
        sa.Column("pagina", sa.Integer(), nullable=False),
        sa.Column("orden", sa.Integer(), nullable=False),
        sa.Column("texto", sa.Text(), nullable=False),
        sa.Column("texto_normalizado", sa.Text(), nullable=False),
        sa.Column("tsv", postgresql.TSVECTOR(), nullable=False),
        sa.Column("embedding", Vector(384), nullable=False),
        sa.CheckConstraint("pagina >= 1", name=op.f("ck_fragmentos_pagina_positiva")),
        sa.ForeignKeyConstraint(
            ["documento_id"], ["documentos.id"], name=op.f("fk_fragmentos_documento_id_documentos"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_fragmentos")),
        sa.UniqueConstraint("documento_id", "pagina", "orden", name=op.f("uq_fragmentos_documento_id_pagina_orden")),
    )
    op.create_index("ix_fragmentos_documento", "fragmentos", ["documento_id"], unique=False)
    op.create_index(
        "ix_fragmentos_embedding_hnsw",
        "fragmentos",
        ["embedding"],
        unique=False,
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.create_index("ix_fragmentos_tsv", "fragmentos", ["tsv"], unique=False, postgresql_using="gin")
    op.create_table(
        "mensajes_chat",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("conversacion_id", sa.Uuid(), nullable=False),
        sa.Column("rol", sa.Text(), nullable=False),
        sa.Column("texto", sa.Text(), nullable=False),
        sa.Column(
            "herramientas",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("facturas_base", sa.ARRAY(sa.BigInteger()), server_default=sa.text("'{}'::bigint[]"), nullable=False),
        sa.Column(
            "citas", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False
        ),
        sa.Column(
            "advertencias",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("propuesta_id", sa.BigInteger(), nullable=True),
        sa.Column("modelo", sa.Text(), nullable=True),
        sa.Column("version_prompt", sa.Text(), nullable=True),
        sa.Column("pasos", sa.Integer(), nullable=True),
        sa.Column("tokens_entrada", sa.Integer(), nullable=True),
        sa.Column("tokens_salida", sa.Integer(), nullable=True),
        sa.Column("latencia_ms", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("creado_en", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("rol in ('usuario','asistente')", name=op.f("ck_mensajes_chat_rol_valido")),
        sa.ForeignKeyConstraint(
            ["conversacion_id"],
            ["conversaciones.id"],
            name=op.f("fk_mensajes_chat_conversacion_id_conversaciones"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_mensajes_chat")),
    )
    op.create_index("ix_mensajes_chat_conversacion", "mensajes_chat", ["conversacion_id"], unique=False)
    op.create_table(
        "facturas",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("uuid", sa.CHAR(length=36), nullable=False),
        sa.Column("tipo", sa.CHAR(length=1), nullable=False),
        sa.Column("version", sa.Text(), nullable=False),
        sa.Column("serie", sa.Text(), nullable=True),
        sa.Column("folio", sa.Text(), nullable=True),
        sa.Column("fecha_emision", sa.DateTime(), nullable=False),
        sa.Column("fecha_timbrado", sa.DateTime(), nullable=False),
        sa.Column("proveedor_id", sa.BigInteger(), nullable=False),
        sa.Column("emisor_rfc", sa.Text(), nullable=False),
        sa.Column("emisor_nombre", sa.Text(), nullable=False),
        sa.Column("emisor_regimen", sa.Text(), nullable=False),
        sa.Column("receptor_rfc", sa.Text(), nullable=False),
        sa.Column("receptor_nombre", sa.Text(), nullable=False),
        sa.Column("receptor_uso_cfdi", sa.Text(), nullable=False),
        sa.Column("subtotal", sa.Numeric(precision=20, scale=6), nullable=False),
        sa.Column("descuento", sa.Numeric(precision=20, scale=6), server_default=sa.text("0"), nullable=False),
        sa.Column("total_impuestos_trasladados", sa.Numeric(precision=20, scale=6), nullable=True),
        sa.Column("total_impuestos_retenidos", sa.Numeric(precision=20, scale=6), nullable=True),
        sa.Column("impuestos_locales_trasladados", sa.Numeric(precision=20, scale=6), nullable=True),
        sa.Column("impuestos_locales_retenidos", sa.Numeric(precision=20, scale=6), nullable=True),
        sa.Column("total", sa.Numeric(precision=20, scale=6), nullable=False),
        sa.Column("moneda", sa.CHAR(length=3), nullable=False),
        sa.Column("tipo_cambio", sa.Numeric(precision=18, scale=6), nullable=True),
        sa.Column("metodo_pago", sa.Text(), nullable=True),
        sa.Column("forma_pago", sa.Text(), nullable=True),
        sa.Column("condiciones_pago", sa.Text(), nullable=True),
        sa.Column("exportacion", sa.Text(), nullable=False),
        sa.Column("lugar_expedicion", sa.Text(), nullable=False),
        sa.Column("resultado", sa.Text(), nullable=False),
        sa.Column("xml_original", sa.Text(), nullable=False),
        sa.Column("xml_sha256", sa.CHAR(length=64), nullable=False),
        sa.Column("carga_archivo_id", sa.BigInteger(), nullable=False),
        sa.Column("creado_en", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "metodo_pago is null or metodo_pago in ('PUE','PPD')", name=op.f("ck_facturas_metodo_pago_valido")
        ),
        sa.CheckConstraint(
            "resultado in ('aceptada','aceptada_con_alertas')", name=op.f("ck_facturas_resultado_valido")
        ),
        sa.CheckConstraint("tipo in ('I','E','P')", name=op.f("ck_facturas_tipo_valido")),
        sa.CheckConstraint("version = '4.0'", name=op.f("ck_facturas_version_40")),
        sa.CheckConstraint("descuento >= 0", name=op.f("ck_facturas_descuento_no_negativo")),
        sa.CheckConstraint("subtotal >= 0", name=op.f("ck_facturas_subtotal_no_negativo")),
        sa.CheckConstraint("tipo_cambio is null or tipo_cambio > 0", name=op.f("ck_facturas_tipo_cambio_positivo")),
        sa.CheckConstraint("total >= 0", name=op.f("ck_facturas_total_no_negativo")),
        sa.ForeignKeyConstraint(
            ["carga_archivo_id"], ["carga_archivos.id"], name=op.f("fk_facturas_carga_archivo_id_carga_archivos")
        ),
        sa.ForeignKeyConstraint(
            ["proveedor_id"], ["proveedores.id"], name=op.f("fk_facturas_proveedor_id_proveedores")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_facturas")),
        sa.UniqueConstraint("uuid", name=op.f("uq_facturas_uuid")),
    )
    op.create_index("ix_facturas_proveedor_serie_folio", "facturas", ["proveedor_id", "serie", "folio"], unique=False)
    op.create_index("ix_facturas_proveedor_tipo", "facturas", ["proveedor_id", "tipo"], unique=False)
    op.create_index("ix_facturas_proveedor_total", "facturas", ["proveedor_id", "total"], unique=False)
    op.create_index("ix_facturas_tipo_fecha", "facturas", ["tipo", "fecha_emision"], unique=False)
    op.create_table(
        "propuestas",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("estado", sa.Text(), server_default=sa.text("'pendiente'"), nullable=False),
        sa.Column("presupuesto_mxn", sa.Numeric(precision=20, scale=2), nullable=False),
        sa.Column("total_mxn", sa.Numeric(precision=20, scale=2), nullable=False),
        sa.Column("fecha_limite", sa.Date(), nullable=False),
        sa.Column("origen", sa.Text(), nullable=False),
        sa.Column("mensaje_id", sa.BigInteger(), nullable=True),
        sa.Column("creada_por", sa.BigInteger(), nullable=False),
        sa.Column("decidida_por", sa.BigInteger(), nullable=True),
        sa.Column("decidida_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column("motivo_rechazo", sa.Text(), nullable=True),
        sa.Column(
            "excluidas", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False
        ),
        sa.Column("creado_en", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "(estado = 'pendiente') = (decidida_en is null)", name=op.f("ck_propuestas_fecha_decision_coherente")
        ),
        sa.CheckConstraint(
            "(estado = 'pendiente') = (decidida_por is null)", name=op.f("ck_propuestas_decision_coherente")
        ),
        sa.CheckConstraint(
            "(estado = 'rechazada') = (motivo_rechazo is not null)", name=op.f("ck_propuestas_rechazo_con_motivo")
        ),
        sa.CheckConstraint("estado in ('pendiente','aprobada','rechazada')", name=op.f("ck_propuestas_estado_valido")),
        sa.CheckConstraint("origen in ('asistente','mcp','api')", name=op.f("ck_propuestas_origen_valido")),
        sa.CheckConstraint(
            "decidida_por is null or decidida_por <> creada_por", name=op.f("ck_propuestas_decide_otra_persona")
        ),
        sa.CheckConstraint("presupuesto_mxn > 0", name=op.f("ck_propuestas_presupuesto_positivo")),
        sa.CheckConstraint(
            "total_mxn >= 0 and total_mxn <= presupuesto_mxn", name=op.f("ck_propuestas_total_en_presupuesto")
        ),
        sa.ForeignKeyConstraint(["creada_por"], ["usuarios.id"], name=op.f("fk_propuestas_creada_por_usuarios")),
        sa.ForeignKeyConstraint(["decidida_por"], ["usuarios.id"], name=op.f("fk_propuestas_decidida_por_usuarios")),
        sa.ForeignKeyConstraint(
            ["mensaje_id"], ["mensajes_chat.id"], name=op.f("fk_propuestas_mensaje_id_mensajes_chat")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_propuestas")),
    )
    op.create_index("ix_propuestas_estado", "propuestas", ["estado"], unique=False)
    op.create_table(
        "alertas",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("factura_id", sa.BigInteger(), nullable=True),
        sa.Column("proveedor_id", sa.BigInteger(), nullable=True),
        sa.Column("codigo", sa.Text(), nullable=False),
        sa.Column("severidad", sa.Text(), nullable=False),
        sa.Column("mensaje", sa.Text(), nullable=False),
        sa.Column(
            "detalle", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column("factura_relacionada_id", sa.BigInteger(), nullable=True),
        sa.Column("estado", sa.Text(), server_default=sa.text("'abierta'"), nullable=False),
        sa.Column("resuelta_por", sa.BigInteger(), nullable=True),
        sa.Column("resuelta_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column("nota_resolucion", sa.Text(), nullable=True),
        sa.Column("creado_en", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "(estado = 'resuelta') = (resuelta_en is not null)", name=op.f("ck_alertas_resolucion_coherente")
        ),
        sa.CheckConstraint("estado in ('abierta','resuelta')", name=op.f("ck_alertas_estado_valido")),
        sa.CheckConstraint("severidad in ('alerta','bloqueante')", name=op.f("ck_alertas_severidad_valida")),
        sa.ForeignKeyConstraint(
            ["factura_id"], ["facturas.id"], name=op.f("fk_alertas_factura_id_facturas"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["factura_relacionada_id"], ["facturas.id"], name=op.f("fk_alertas_factura_relacionada_id_facturas")
        ),
        sa.ForeignKeyConstraint(["proveedor_id"], ["proveedores.id"], name=op.f("fk_alertas_proveedor_id_proveedores")),
        sa.ForeignKeyConstraint(["resuelta_por"], ["usuarios.id"], name=op.f("fk_alertas_resuelta_por_usuarios")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_alertas")),
        sa.UniqueConstraint(
            "factura_id",
            "proveedor_id",
            "codigo",
            "factura_relacionada_id",
            name="uq_alertas_idempotencia",
            postgresql_nulls_not_distinct=True,
        ),
    )
    op.create_index(
        "ix_alertas_abiertas", "alertas", ["factura_id"], unique=False, postgresql_where=sa.text("estado = 'abierta'")
    )
    op.create_table(
        "cfdi_relacionados",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("factura_id", sa.BigInteger(), nullable=False),
        sa.Column("tipo_relacion", sa.CHAR(length=2), nullable=False),
        sa.Column("uuid_relacionado", sa.CHAR(length=36), nullable=False),
        sa.ForeignKeyConstraint(
            ["factura_id"], ["facturas.id"], name=op.f("fk_cfdi_relacionados_factura_id_facturas"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_cfdi_relacionados")),
        sa.UniqueConstraint(
            "factura_id",
            "tipo_relacion",
            "uuid_relacionado",
            name=op.f("uq_cfdi_relacionados_factura_id_tipo_relacion_uuid_relacionado"),
        ),
    )
    op.create_index("ix_cfdi_relacionados_uuid", "cfdi_relacionados", ["uuid_relacionado"], unique=False)
    op.create_table(
        "conceptos",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("factura_id", sa.BigInteger(), nullable=False),
        sa.Column("orden", sa.Integer(), nullable=False),
        sa.Column("clave_prod_serv", sa.Text(), nullable=False),
        sa.Column("no_identificacion", sa.Text(), nullable=True),
        sa.Column("cantidad", sa.Numeric(precision=24, scale=6), nullable=False),
        sa.Column("clave_unidad", sa.Text(), nullable=False),
        sa.Column("unidad", sa.Text(), nullable=True),
        sa.Column("descripcion", sa.Text(), nullable=False),
        sa.Column("valor_unitario", sa.Numeric(precision=24, scale=6), nullable=False),
        sa.Column("importe", sa.Numeric(precision=20, scale=6), nullable=False),
        sa.Column("descuento", sa.Numeric(precision=20, scale=6), nullable=True),
        sa.Column("objeto_imp", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["factura_id"], ["facturas.id"], name=op.f("fk_conceptos_factura_id_facturas"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_conceptos")),
        sa.UniqueConstraint("factura_id", "orden", name=op.f("uq_conceptos_factura_id_orden")),
    )
    op.create_table(
        "factura_impuestos",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("factura_id", sa.BigInteger(), nullable=False),
        sa.Column("clase", sa.Text(), nullable=False),
        sa.Column("impuesto", sa.Text(), nullable=False),
        sa.Column("tipo_factor", sa.Text(), nullable=True),
        sa.Column("tasa_o_cuota", sa.Numeric(precision=12, scale=6), nullable=True),
        sa.Column("base", sa.Numeric(precision=20, scale=6), nullable=True),
        sa.Column("importe", sa.Numeric(precision=20, scale=6), nullable=True),
        sa.CheckConstraint("clase in ('traslado','retencion')", name=op.f("ck_factura_impuestos_clase_valida")),
        sa.ForeignKeyConstraint(
            ["factura_id"], ["facturas.id"], name=op.f("fk_factura_impuestos_factura_id_facturas"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_factura_impuestos")),
    )
    op.create_index("ix_factura_impuestos_factura", "factura_impuestos", ["factura_id"], unique=False)
    op.create_table(
        "renglones_propuesta",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("propuesta_id", sa.BigInteger(), nullable=False),
        sa.Column("factura_id", sa.BigInteger(), nullable=False),
        sa.Column("importe", sa.Numeric(precision=20, scale=2), nullable=False),
        sa.Column("importe_mxn", sa.Numeric(precision=20, scale=2), nullable=False),
        sa.Column("razon", sa.Text(), nullable=False),
        sa.CheckConstraint("importe > 0", name=op.f("ck_renglones_propuesta_importe_positivo")),
        sa.CheckConstraint("importe_mxn > 0", name=op.f("ck_renglones_propuesta_importe_mxn_positivo")),
        sa.ForeignKeyConstraint(
            ["factura_id"], ["facturas.id"], name=op.f("fk_renglones_propuesta_factura_id_facturas")
        ),
        sa.ForeignKeyConstraint(
            ["propuesta_id"], ["propuestas.id"], name=op.f("fk_renglones_propuesta_propuesta_id_propuestas")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_renglones_propuesta")),
        sa.UniqueConstraint("propuesta_id", "factura_id", name=op.f("uq_renglones_propuesta_propuesta_id_factura_id")),
    )
    op.create_index("ix_renglones_propuesta_factura", "renglones_propuesta", ["factura_id"], unique=False)
    op.create_table(
        "aplicaciones",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("factura_id", sa.BigInteger(), nullable=False),
        sa.Column("origen", sa.Text(), nullable=False),
        sa.Column("origen_factura_id", sa.BigInteger(), nullable=True),
        sa.Column("renglon_propuesta_id", sa.BigInteger(), nullable=True),
        sa.Column("num_parcialidad", sa.Integer(), nullable=True),
        sa.Column("importe_solicitado", sa.Numeric(precision=20, scale=6), nullable=False),
        sa.Column("importe", sa.Numeric(precision=20, scale=6), nullable=False),
        sa.Column("fecha", sa.Date(), nullable=False),
        sa.Column("registrado_por", sa.BigInteger(), nullable=True),
        sa.Column("creado_en", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "(origen = 'pago_aprobado') = (renglon_propuesta_id is not null)",
            name=op.f("ck_aplicaciones_coherencia_propuesta"),
        ),
        sa.CheckConstraint(
            "(origen in ('complemento_pago','nota_credito')) = (origen_factura_id is not null)",
            name=op.f("ck_aplicaciones_coherencia_documento"),
        ),
        sa.CheckConstraint(
            "origen in ('complemento_pago','nota_credito','pago_aprobado')", name=op.f("ck_aplicaciones_origen_valido")
        ),
        sa.CheckConstraint(
            "importe > 0 and importe <= importe_solicitado", name=op.f("ck_aplicaciones_importe_valido")
        ),
        sa.ForeignKeyConstraint(["factura_id"], ["facturas.id"], name=op.f("fk_aplicaciones_factura_id_facturas")),
        sa.ForeignKeyConstraint(
            ["origen_factura_id"], ["facturas.id"], name=op.f("fk_aplicaciones_origen_factura_id_facturas")
        ),
        sa.ForeignKeyConstraint(
            ["registrado_por"], ["usuarios.id"], name=op.f("fk_aplicaciones_registrado_por_usuarios")
        ),
        sa.ForeignKeyConstraint(
            ["renglon_propuesta_id"],
            ["renglones_propuesta.id"],
            name=op.f("fk_aplicaciones_renglon_propuesta_id_renglones_propuesta"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_aplicaciones")),
        sa.UniqueConstraint("renglon_propuesta_id", name=op.f("uq_aplicaciones_renglon_propuesta_id")),
    )
    op.create_index("ix_aplicaciones_factura", "aplicaciones", ["factura_id"], unique=False)
    op.create_index(
        "uq_aplicaciones_documento",
        "aplicaciones",
        ["origen_factura_id", "factura_id", "num_parcialidad"],
        unique=True,
        postgresql_nulls_not_distinct=True,
        postgresql_where=sa.text("origen_factura_id is not null"),
    )
    op.create_table(
        "doctos_pago",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("factura_pago_id", sa.BigInteger(), nullable=False),
        sa.Column("pago_indice", sa.Integer(), nullable=False),
        sa.Column("fecha_pago", sa.DateTime(), nullable=False),
        sa.Column("id_documento", sa.CHAR(length=36), nullable=False),
        sa.Column("moneda_dr", sa.CHAR(length=3), nullable=False),
        sa.Column("equivalencia_dr", sa.Numeric(precision=20, scale=10), nullable=True),
        sa.Column("num_parcialidad", sa.Integer(), nullable=False),
        sa.Column("imp_saldo_ant", sa.Numeric(precision=20, scale=6), nullable=False),
        sa.Column("imp_pagado", sa.Numeric(precision=20, scale=6), nullable=False),
        sa.Column("imp_saldo_insoluto", sa.Numeric(precision=20, scale=6), nullable=False),
        sa.Column("aplicacion_id", sa.BigInteger(), nullable=True),
        sa.CheckConstraint("imp_pagado > 0", name=op.f("ck_doctos_pago_pagado_positivo")),
        sa.CheckConstraint("num_parcialidad > 0", name=op.f("ck_doctos_pago_parcialidad_positiva")),
        sa.ForeignKeyConstraint(
            ["aplicacion_id"], ["aplicaciones.id"], name=op.f("fk_doctos_pago_aplicacion_id_aplicaciones")
        ),
        sa.ForeignKeyConstraint(
            ["factura_pago_id"],
            ["facturas.id"],
            name=op.f("fk_doctos_pago_factura_pago_id_facturas"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_doctos_pago")),
        sa.UniqueConstraint(
            "factura_pago_id",
            "pago_indice",
            "id_documento",
            name=op.f("uq_doctos_pago_factura_pago_id_pago_indice_id_documento"),
        ),
    )
    op.create_index(
        "ix_doctos_pago_pendientes",
        "doctos_pago",
        ["id_documento"],
        unique=False,
        postgresql_where=sa.text("aplicacion_id is null"),
    )
    # Llaves de los dos ciclos (facturas <-> carga_archivos y propuestas <-> mensajes_chat): van al final.
    op.create_foreign_key(
        op.f("fk_carga_archivos_factura_id_facturas"), "carga_archivos", "facturas", ["factura_id"], ["id"]
    )
    op.create_foreign_key(
        op.f("fk_mensajes_chat_propuesta_id_propuestas"), "mensajes_chat", "propuestas", ["propuesta_id"], ["id"]
    )
    for sentencia in TRIGGERS:
        op.execute(sentencia)


def downgrade() -> None:
    for sentencia in QUITAR_TRIGGERS:
        op.execute(sentencia)
    op.drop_constraint(op.f("fk_mensajes_chat_propuesta_id_propuestas"), "mensajes_chat", type_="foreignkey")
    op.drop_constraint(op.f("fk_carga_archivos_factura_id_facturas"), "carga_archivos", type_="foreignkey")
    op.drop_index(
        "ix_doctos_pago_pendientes", table_name="doctos_pago", postgresql_where=sa.text("aplicacion_id is null")
    )
    op.drop_table("doctos_pago")
    op.drop_index(
        "uq_aplicaciones_documento",
        table_name="aplicaciones",
        postgresql_nulls_not_distinct=True,
        postgresql_where=sa.text("origen_factura_id is not null"),
    )
    op.drop_index("ix_aplicaciones_factura", table_name="aplicaciones")
    op.drop_table("aplicaciones")
    op.drop_index("ix_renglones_propuesta_factura", table_name="renglones_propuesta")
    op.drop_table("renglones_propuesta")
    op.drop_index("ix_factura_impuestos_factura", table_name="factura_impuestos")
    op.drop_table("factura_impuestos")
    op.drop_table("conceptos")
    op.drop_index("ix_cfdi_relacionados_uuid", table_name="cfdi_relacionados")
    op.drop_table("cfdi_relacionados")
    op.drop_index("ix_alertas_abiertas", table_name="alertas", postgresql_where=sa.text("estado = 'abierta'"))
    op.drop_table("alertas")
    op.drop_index("ix_propuestas_estado", table_name="propuestas")
    op.drop_table("propuestas")
    op.drop_index("ix_facturas_tipo_fecha", table_name="facturas")
    op.drop_index("ix_facturas_proveedor_total", table_name="facturas")
    op.drop_index("ix_facturas_proveedor_tipo", table_name="facturas")
    op.drop_index("ix_facturas_proveedor_serie_folio", table_name="facturas")
    op.drop_table("facturas")
    op.drop_index("ix_mensajes_chat_conversacion", table_name="mensajes_chat")
    op.drop_table("mensajes_chat")
    op.drop_index("ix_fragmentos_tsv", table_name="fragmentos", postgresql_using="gin")
    op.drop_index(
        "ix_fragmentos_embedding_hnsw",
        table_name="fragmentos",
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.drop_index("ix_fragmentos_documento", table_name="fragmentos")
    op.drop_table("fragmentos")
    op.drop_index("ix_carga_archivos_carga", table_name="carga_archivos")
    op.drop_table("carga_archivos")
    op.drop_table("documentos")
    op.drop_index("ix_conversaciones_usuario", table_name="conversaciones")
    op.drop_table("conversaciones")
    op.drop_table("cargas")
    op.drop_index("ix_bitacora_ocurrido_en", table_name="bitacora")
    op.drop_index("ix_bitacora_entidad", table_name="bitacora")
    op.drop_table("bitacora")
    op.drop_table("usuarios")
    op.drop_table("proveedores")
    op.drop_table("lista_69b")
    op.drop_table("cuota_uso")
    op.execute("DROP EXTENSION IF EXISTS vector")
