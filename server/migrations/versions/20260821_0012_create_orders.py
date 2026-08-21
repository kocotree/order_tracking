"""Create S04 order lifecycle tables.

Revision ID: 20260821_0012
Revises: 20260821_0011
Create Date: 2026-08-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "20260821_0012"
down_revision: str | None = "20260821_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamp(name: str, *, nullable: bool = False) -> sa.Column:
    return sa.Column(name, mysql.DATETIME(fsp=6), nullable=nullable)


def upgrade() -> None:
    op.create_table(
        "orders",
        sa.Column("order_id", sa.String(36), nullable=False),
        sa.Column("order_no", sa.String(100), nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("order_date", sa.Date(), nullable=False),
        sa.Column("tracker", sa.String(32), nullable=False),
        sa.Column("contract_ship_date", sa.Date(), nullable=False),
        sa.Column("lifecycle", sa.String(32), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        _timestamp("published_at", nullable=True),
        sa.Column("published_by", sa.String(36), nullable=True),
        _timestamp("completed_at", nullable=True),
        sa.Column("completed_by", sa.String(36), nullable=True),
        _timestamp("deleted_at", nullable=True),
        sa.Column("deleted_by", sa.String(36), nullable=True),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("updated_by", sa.String(36), nullable=False),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=6),
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            mysql.DATETIME(fsp=6),
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.CheckConstraint("source IN ('manual', 'feishu')", name="ck_orders_source"),
        sa.CheckConstraint(
            "lifecycle IN ('DRAFT', 'PUBLISHED', 'COMPLETED')",
            name="ck_orders_lifecycle",
        ),
        sa.ForeignKeyConstraint(["published_by"], ["users.user_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["completed_by"], ["users.user_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["deleted_by"], ["users.user_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["users.user_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.user_id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("order_id"),
        sa.UniqueConstraint("order_no", name="uq_orders_order_no"),
    )
    op.create_index(
        "ix_orders_visible_status",
        "orders",
        ["deleted_at", "lifecycle", "contract_ship_date"],
    )
    op.create_table(
        "order_lines",
        sa.Column("order_line_id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("order_id", sa.String(36), nullable=False),
        sa.Column("product_variant_id", sa.String(36), nullable=False),
        sa.Column("order_quantity", sa.Integer(), nullable=False),
        sa.Column("sku_id_snapshot", sa.String(100), nullable=False),
        sa.Column("product_name_snapshot", sa.String(255), nullable=False),
        sa.Column("properties_value_snapshot", sa.String(255), nullable=False),
        sa.Column("category_snapshot", sa.String(100), nullable=True),
        sa.Column("image_object_key_snapshot", sa.String(500), nullable=True),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=6),
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            mysql.DATETIME(fsp=6),
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.CheckConstraint("order_quantity > 0", name="ck_order_lines_quantity_positive"),
        sa.ForeignKeyConstraint(["order_id"], ["orders.order_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["product_variant_id"], ["product_variants.variant_id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("order_line_id"),
        sa.UniqueConstraint("order_id", "product_variant_id", name="uq_order_lines_variant"),
    )
    op.create_index("ix_order_lines_order", "order_lines", ["order_id", "order_line_id"])
    op.create_table(
        "order_assignments",
        sa.Column("order_assignment_id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("order_line_id", sa.BigInteger(), nullable=False),
        sa.Column("factory_id", sa.String(36), nullable=False),
        sa.Column("assigned_quantity", sa.Integer(), nullable=False),
        sa.Column("factory_name_snapshot", sa.String(100), nullable=False),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=6),
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            mysql.DATETIME(fsp=6),
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "assigned_quantity > 0", name="ck_order_assignments_quantity_positive"
        ),
        sa.ForeignKeyConstraint(
            ["order_line_id"], ["order_lines.order_line_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["factory_id"], ["factories.factory_id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("order_assignment_id"),
        sa.UniqueConstraint(
            "order_line_id", "factory_id", name="uq_order_assignments_line_factory"
        ),
    )
    op.create_index(
        "ix_order_assignments_factory",
        "order_assignments",
        ["factory_id", "order_line_id"],
    )
    op.create_table(
        "order_completion_records",
        sa.Column("record_id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("order_id", sa.String(36), nullable=False),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("actor_id", sa.String(36), nullable=False),
        sa.Column("source_terminal", sa.String(32), nullable=False),
        sa.Column("before_lifecycle", sa.String(32), nullable=False),
        sa.Column("after_lifecycle", sa.String(32), nullable=False),
        sa.Column("quantity_snapshot", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=6),
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "action IN ('COMPLETE', 'REOPEN')", name="ck_order_completion_action"
        ),
        sa.ForeignKeyConstraint(["order_id"], ["orders.order_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["actor_id"], ["users.user_id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("record_id"),
    )
    op.create_index(
        "ix_order_completion_order",
        "order_completion_records",
        ["order_id", "record_id"],
    )


def downgrade() -> None:
    op.drop_table("order_completion_records")
    op.drop_table("order_assignments")
    op.drop_table("order_lines")
    op.drop_table("orders")
