"""Preserve relaxed import source details

Revision ID: 20260911_0034
Revises: 20260909_0033
Create Date: 2026-09-11 10:36:46.064960
"""

import json
import logging
from collections.abc import Sequence
from hashlib import sha256
from uuid import uuid4

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "20260911_0034"
down_revision: str | Sequence[str] | None = "20260909_0033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "order_details",
        sa.Column("detail_id", sa.String(length=36), nullable=False),
        sa.Column("order_id", sa.String(length=36), nullable=False),
        sa.Column("source_record_pk", sa.BigInteger(), nullable=True),
        sa.Column("origin", sa.String(length=16), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("accepted_raw_fields", sa.JSON(), nullable=False),
        sa.Column("accepted_source_modified_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("accepted_source_hash", sa.String(length=64), nullable=True),
        sa.Column("source_sku_id", sa.Text(), nullable=True),
        sa.Column("product_name", sa.Text(), nullable=True),
        sa.Column("properties_value", sa.Text(), nullable=True),
        sa.Column("category", sa.Text(), nullable=True),
        sa.Column("factory_name", sa.Text(), nullable=True),
        sa.Column("matched_variant_id", sa.String(length=36), nullable=True),
        sa.Column("matched_factory_id", sa.String(length=36), nullable=True),
        sa.Column("order_quantity", sa.Integer(), nullable=True),
        sa.Column("source_shipped_quantity", sa.Integer(), nullable=True),
        sa.Column("source_tracker", sa.Text(), nullable=True),
        sa.Column("source_contract_ship_date", sa.Date(), nullable=True),
        sa.Column("contract_ship_date", sa.Date(), nullable=True),
        sa.Column("date_override_enabled", sa.Boolean(), nullable=False),
        sa.Column("parse_issues", sa.JSON(), nullable=False),
        sa.Column("assignment_id", sa.BigInteger(), nullable=True),
        sa.Column("dispatch_state", sa.String(length=16), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("updated_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.ForeignKeyConstraint(
            ["assignment_id"], ["order_assignments.order_assignment_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["matched_factory_id"], ["factories.factory_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["matched_variant_id"], ["product_variants.variant_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["order_id"], ["orders.order_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["source_record_pk"],
            ["order_import_source_records.source_record_pk"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("detail_id"),
        sa.UniqueConstraint("assignment_id", name="uq_order_details_assignment"),
        sa.UniqueConstraint("source_record_pk", name="uq_order_details_source"),
    )
    op.create_index(
        "ix_order_details_order", "order_details", ["order_id", "sort_order"], unique=False
    )
    op.alter_column(
        "order_import_candidate_lines",
        "source_sku_id",
        existing_type=mysql.VARCHAR(length=100),
        type_=sa.Text(),
        existing_nullable=True,
    )
    op.alter_column(
        "order_import_candidate_lines",
        "product_name",
        existing_type=mysql.VARCHAR(length=255),
        type_=sa.Text(),
        existing_nullable=True,
    )
    op.alter_column(
        "order_import_candidate_lines",
        "properties_value",
        existing_type=mysql.VARCHAR(length=255),
        type_=sa.Text(),
        existing_nullable=True,
    )
    op.alter_column(
        "order_import_candidate_lines",
        "category",
        existing_type=mysql.VARCHAR(length=100),
        type_=sa.Text(),
        existing_nullable=True,
    )
    op.alter_column(
        "order_import_candidate_lines",
        "factory_name",
        existing_type=mysql.VARCHAR(length=100),
        type_=sa.Text(),
        existing_nullable=True,
    )
    op.alter_column(
        "order_import_candidate_lines",
        "shipped_quantity",
        existing_type=mysql.INTEGER(),
        type_=sa.BigInteger(),
        nullable=True,
        existing_server_default=sa.text("'0'"),
    )
    op.alter_column(
        "order_import_candidate_lines",
        "pending_quantity",
        existing_type=mysql.INTEGER(),
        type_=sa.BigInteger(),
        nullable=True,
        existing_server_default=sa.text("'0'"),
    )
    op.alter_column(
        "order_import_candidates",
        "tracker",
        existing_type=mysql.VARCHAR(length=32),
        type_=sa.Text(),
        existing_nullable=True,
    )
    op.alter_column(
        "order_import_candidates",
        "category",
        existing_type=mysql.VARCHAR(length=100),
        type_=sa.Text(),
        existing_nullable=True,
    )
    op.alter_column(
        "order_import_candidates",
        "total_quantity",
        existing_type=mysql.INTEGER(),
        type_=sa.BigInteger(),
        nullable=True,
        existing_server_default=sa.text("'0'"),
    )
    op.alter_column(
        "order_import_candidates",
        "shipped_quantity",
        existing_type=mysql.INTEGER(),
        type_=sa.BigInteger(),
        nullable=True,
        existing_server_default=sa.text("'0'"),
    )
    op.alter_column(
        "order_import_candidates",
        "pending_quantity",
        existing_type=mysql.INTEGER(),
        type_=sa.BigInteger(),
        nullable=True,
        existing_server_default=sa.text("'0'"),
    )
    op.add_column("orders", sa.Column("tracker_locked_at", mysql.DATETIME(fsp=6), nullable=True))
    op.add_column(
        "orders", sa.Column("detail_mode", sa.Boolean(), server_default="0", nullable=False)
    )
    op.alter_column("orders", "tracker", existing_type=mysql.VARCHAR(length=32), nullable=True)

    _backfill_legacy()
    # Force one full read after the 50% -> 95% rule and nullable parser change.
    op.get_bind().execute(sa.text("DELETE FROM order_import_source_cursors"))


def _backfill_legacy() -> None:
    # Snapshot execution identities, never reconstruct historical quantities from Feishu.
    bind = op.get_bind()
    rows = (
        bind.execute(
            sa.text("""
        SELECT a.order_assignment_id, a.assigned_quantity, a.initial_shipped_quantity,
               a.contract_ship_date, a.factory_id, a.factory_name_snapshot,
               l.created_at, l.updated_at, l.order_id, l.product_variant_id,
               l.sku_id_snapshot, l.product_name_snapshot, l.properties_value_snapshot,
               l.category_snapshot, l.order_quantity, o.tracker, o.lifecycle, o.deleted_at
        FROM order_lines l LEFT JOIN order_assignments a USING (order_line_id)
        JOIN orders o USING (order_id)
        ORDER BY l.order_id, a.order_assignment_id
    """)
        )
        .mappings()
        .all()
    )
    details = sa.table(
        "order_details",
        *[
            sa.column(name)
            for name in (
                "detail_id",
                "order_id",
                "origin",
                "sort_order",
                "source_sku_id",
                "product_name",
                "properties_value",
                "category",
                "factory_name",
                "matched_variant_id",
                "matched_factory_id",
                "order_quantity",
                "source_shipped_quantity",
                "source_tracker",
                "contract_ship_date",
                "date_override_enabled",
                "assignment_id",
                "dispatch_state",
                "created_at",
                "updated_at",
                "source_record_pk",
                "accepted_source_hash",
                "accepted_source_modified_at",
                "source_contract_ship_date",
            )
        ],
        sa.column("accepted_raw_fields", sa.JSON),
        sa.column("parse_issues", sa.JSON),
    )
    for index, row in enumerate(rows, 1):
        sources = (
            bind.execute(
                sa.text("""
            SELECT s.source_record_pk, s.raw_fields, s.source_modified_at,
                   c.order_quantity, c.shipped_quantity, c.source_contract_ship_date
            FROM order_import_candidates i
            JOIN order_import_candidate_lines c USING (candidate_id)
            JOIN order_import_source_records s USING (source_record_pk)
            JOIN orders o ON o.order_id = i.imported_order_id AND o.order_no = s.order_no
            WHERE i.imported_order_id = :order_id AND c.matched_variant_id = :variant
              AND c.matched_factory_id = :factory
        """),
                {
                    "order_id": row["order_id"],
                    "variant": row["product_variant_id"],
                    "factory": row["factory_id"],
                },
            )
            .mappings()
            .all()
        )
        source = (
            sources[0]
            if len(sources) == 1
            and sources[0]["order_quantity"] == row["assigned_quantity"]
            and sources[0]["shipped_quantity"] == row["initial_shipped_quantity"]
            else None
        )
        raw = (
            json.loads(source["raw_fields"])
            if source and isinstance(source["raw_fields"], str)
            else source["raw_fields"]
            if source
            else {}
        )
        if sources and source is None:
            logging.getLogger("alembic.runtime.migration").warning(
                "来源映射待核对：order_id=%s assignment_id=%s；保留legacy快照，不猜测绑定",
                row["order_id"],
                row["order_assignment_id"],
            )
        bind.execute(
            details.insert().values(
                detail_id=str(uuid4()),
                order_id=row["order_id"],
                origin="legacy",
                sort_order=index,
                source_sku_id=row["sku_id_snapshot"],
                product_name=row["product_name_snapshot"],
                properties_value=row["properties_value_snapshot"],
                category=row["category_snapshot"],
                factory_name=row["factory_name_snapshot"],
                matched_variant_id=row["product_variant_id"],
                matched_factory_id=row["factory_id"],
                order_quantity=row["assigned_quantity"]
                if row["assigned_quantity"] is not None
                else row["order_quantity"],
                source_shipped_quantity=row["initial_shipped_quantity"] or 0,
                source_tracker=row["tracker"],
                contract_ship_date=row["contract_ship_date"],
                date_override_enabled=True,
                assignment_id=row["order_assignment_id"],
                dispatch_state="ASSIGNED"
                if row["order_assignment_id"] is not None
                and row["lifecycle"] != "DRAFT"
                and not row["deleted_at"]
                else "UNASSIGNED",
                accepted_raw_fields=raw,
                source_record_pk=source["source_record_pk"] if source else None,
                accepted_source_modified_at=source["source_modified_at"] if source else None,
                source_contract_ship_date=source["source_contract_ship_date"] if source else None,
                accepted_source_hash=sha256(
                    json.dumps(
                        raw, sort_keys=True, ensure_ascii=False, separators=(",", ":")
                    ).encode()
                ).hexdigest()
                if source
                else None,
                parse_issues=["LEGACY_SOURCE_MAPPING_UNRESOLVED"]
                if sources and source is None
                else [],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
        )
    # Old grouped assignments are explicitly legacy snapshots, with no guessed source binding.
    # Their existing editing/dispatch protocol remains in force until #90 switches execution.


def downgrade() -> None:
    bind = op.get_bind()
    if (
        bind.execute(
            sa.text("SELECT COUNT(*) FROM orders WHERE detail_mode = 1 OR tracker IS NULL")
        ).scalar()
        or bind.execute(sa.text("SELECT COUNT(*) FROM order_import_candidates")).scalar()
        or bind.execute(
            sa.text("SELECT COUNT(*) FROM order_details WHERE origin <> 'legacy'")
        ).scalar()
    ):
        raise RuntimeError("存在新来源资料，拒绝有损回滚；请按已审核备份恢复方案处理")
    op.drop_table("order_details")
    op.drop_column("orders", "detail_mode")
    op.drop_column("orders", "tracker_locked_at")
    op.alter_column("orders", "tracker", existing_type=sa.String(32), nullable=False)
    for table, fields in (
        ("order_import_candidates", {"tracker": 32, "category": 100}),
        (
            "order_import_candidate_lines",
            {
                "source_sku_id": 100,
                "product_name": 255,
                "properties_value": 255,
                "category": 100,
                "factory_name": 100,
            },
        ),
    ):
        for field, length in fields.items():
            op.alter_column(
                table,
                field,
                existing_type=sa.Text(),
                type_=sa.String(length),
                existing_nullable=True,
            )
    for table, fields in (
        ("order_import_candidates", ["total_quantity", "shipped_quantity", "pending_quantity"]),
        ("order_import_candidate_lines", ["shipped_quantity", "pending_quantity"]),
    ):
        for field in fields:
            op.alter_column(
                table,
                field,
                existing_type=sa.BigInteger(),
                type_=sa.Integer(),
                nullable=False,
                server_default="0",
            )
