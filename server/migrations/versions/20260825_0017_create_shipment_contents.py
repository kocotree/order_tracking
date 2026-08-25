"""Create S07 shipment contents and quantity ledger.

Revision ID: 20260825_0017
Revises: 20260825_0016
Create Date: 2026-08-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "20260825_0017"
down_revision: str | None = "20260825_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "shipment_boxes",
        sa.Column("box_id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("shipment_id", sa.String(36), nullable=False),
        sa.Column("box_no", sa.Integer(), nullable=False),
        sa.Column("group_key", sa.String(36)),
        sa.CheckConstraint("box_no > 0", name="ck_shipment_boxes_no_positive"),
        sa.ForeignKeyConstraint(["shipment_id"], ["shipments.shipment_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("box_id"),
        sa.UniqueConstraint("shipment_id", "box_no", name="uq_shipment_boxes_no"),
    )
    op.create_table(
        "shipment_box_items",
        sa.Column("item_id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("box_id", sa.BigInteger(), nullable=False),
        sa.Column("order_assignment_id", sa.BigInteger(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.CheckConstraint("quantity > 0", name="ck_shipment_box_items_quantity_positive"),
        sa.ForeignKeyConstraint(["box_id"], ["shipment_boxes.box_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["order_assignment_id"], ["order_assignments.order_assignment_id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("item_id"),
        sa.UniqueConstraint("box_id", "order_assignment_id", name="uq_shipment_box_items_line"),
    )
    op.create_table(
        "shipment_lines",
        sa.Column("line_id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("shipment_id", sa.String(36), nullable=False),
        sa.Column("order_assignment_id", sa.BigInteger(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("order_no_snapshot", sa.String(100), nullable=False),
        sa.Column("sku_id_snapshot", sa.String(100), nullable=False),
        sa.Column("product_name_snapshot", sa.String(255), nullable=False),
        sa.Column("properties_value_snapshot", sa.String(255), nullable=False),
        sa.CheckConstraint("quantity > 0", name="ck_shipment_lines_quantity_positive"),
        sa.ForeignKeyConstraint(["shipment_id"], ["shipments.shipment_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["order_assignment_id"], ["order_assignments.order_assignment_id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("line_id"),
        sa.UniqueConstraint(
            "shipment_id", "order_assignment_id", name="uq_shipment_lines_assignment"
        ),
    )
    op.create_table(
        "quantity_ledger",
        sa.Column("ledger_id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("order_assignment_id", sa.BigInteger(), nullable=False),
        sa.Column("source_type", sa.String(32), nullable=False),
        sa.Column("source_id", sa.String(36), nullable=False),
        sa.Column("quantity_delta", sa.Integer(), nullable=False),
        sa.Column("actor_id", sa.String(36), nullable=False),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.CheckConstraint("quantity_delta <> 0", name="ck_quantity_ledger_nonzero"),
        sa.ForeignKeyConstraint(
            ["order_assignment_id"], ["order_assignments.order_assignment_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["actor_id"], ["users.user_id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("ledger_id"),
        sa.UniqueConstraint(
            "source_type", "source_id", "order_assignment_id", name="uq_quantity_ledger_source"
        ),
    )
    op.create_index(
        "ix_quantity_ledger_assignment", "quantity_ledger", ["order_assignment_id", "created_at"]
    )
    op.create_table(
        "shipment_number_counters",
        sa.Column("business_date", sa.Date(), nullable=False),
        sa.Column("next_sequence", sa.Integer(), nullable=False),
        sa.Column("updated_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.PrimaryKeyConstraint("business_date"),
    )


def downgrade() -> None:
    op.drop_table("shipment_number_counters")
    op.drop_index("ix_quantity_ledger_assignment", table_name="quantity_ledger")
    op.drop_table("quantity_ledger")
    op.drop_table("shipment_lines")
    op.drop_table("shipment_box_items")
    op.drop_table("shipment_boxes")
