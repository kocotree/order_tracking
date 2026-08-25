"""Create the S07 shipment draft root.

Revision ID: 20260825_0016
Revises: 20260825_0015
Create Date: 2026-08-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "20260825_0016"
down_revision: str | None = "20260825_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "shipments",
        sa.Column("shipment_id", sa.String(length=36), nullable=False),
        sa.Column("shipment_no", sa.String(length=32), nullable=True),
        sa.Column("factory_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("business_date", sa.Date(), nullable=True),
        sa.Column("preferred_order_id", sa.String(length=36), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(length=36), nullable=False),
        sa.Column("active_draft_owner_id", sa.String(length=36), nullable=True),
        sa.Column("submitted_by", sa.String(length=36), nullable=True),
        sa.Column("submitted_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("deleted_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=6),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
        ),
        sa.Column(
            "updated_at",
            mysql.DATETIME(fsp=6),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
        ),
        sa.CheckConstraint("status IN ('DRAFT', 'SHIPPED')", name="ck_shipments_status"),
        sa.ForeignKeyConstraint(["factory_id"], ["factories.factory_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["preferred_order_id"], ["orders.order_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["users.user_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["active_draft_owner_id"], ["users.user_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["submitted_by"], ["users.user_id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("shipment_id"),
        sa.UniqueConstraint("shipment_no", name="uq_shipments_no"),
        sa.UniqueConstraint(
            "active_draft_owner_id", name="uq_shipments_active_draft_owner"
        ),
    )
    op.create_index(
        "ix_shipments_factory_status",
        "shipments",
        ["factory_id", "status", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_shipments_factory_status", table_name="shipments")
    op.drop_table("shipments")
