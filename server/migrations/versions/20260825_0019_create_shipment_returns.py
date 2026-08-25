"""Create S08 shipment return events and lines.

Revision ID: 20260825_0019
Revises: 20260825_0018
Create Date: 2026-08-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "20260825_0019"
down_revision: str | None = "20260825_0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "shipment_return_events",
        sa.Column("event_id", sa.String(36), nullable=False),
        sa.Column("shipment_id", sa.String(36), nullable=False),
        sa.Column("returned_by", sa.String(36), nullable=False),
        sa.Column("return_date", sa.Date(), nullable=False),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("idempotency_key", sa.String(191), nullable=False),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.ForeignKeyConstraint(["shipment_id"], ["shipments.shipment_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["returned_by"], ["users.user_id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("event_id"),
        sa.UniqueConstraint(
            "returned_by",
            "idempotency_key",
            name="uq_shipment_return_actor_idempotency",
        ),
    )
    op.create_index(
        "ix_shipment_return_events_shipment",
        "shipment_return_events",
        ["shipment_id", "created_at"],
    )
    op.create_table(
        "shipment_return_lines",
        sa.Column("return_line_id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("event_id", sa.String(36), nullable=False),
        sa.Column("shipment_line_id", sa.BigInteger(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("before_shipped_quantity", sa.Integer(), nullable=False),
        sa.Column("after_shipped_quantity", sa.Integer(), nullable=False),
        sa.CheckConstraint("quantity > 0", name="ck_shipment_return_lines_quantity_positive"),
        sa.ForeignKeyConstraint(
            ["event_id"], ["shipment_return_events.event_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["shipment_line_id"], ["shipment_lines.line_id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("return_line_id"),
        sa.UniqueConstraint(
            "event_id", "shipment_line_id", name="uq_shipment_return_lines_event_line"
        ),
    )
    op.create_index(
        "ix_shipment_return_lines_shipment_line",
        "shipment_return_lines",
        ["shipment_line_id"],
    )


def downgrade() -> None:
    op.drop_table("shipment_return_lines")
    op.drop_table("shipment_return_events")
