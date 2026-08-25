"""Create S08 shipment reversal records.

Revision ID: 20260825_0018
Revises: 20260825_0017
Create Date: 2026-08-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "20260825_0018"
down_revision: str | None = "20260825_0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_shipments_status", "shipments", type_="check")
    op.create_check_constraint(
        "ck_shipments_status",
        "shipments",
        "status IN ('DRAFT', 'SHIPPED', 'VOID_PENDING', 'VOIDED')",
    )
    op.create_table(
        "shipment_void_requests",
        sa.Column("request_id", sa.String(36), nullable=False),
        sa.Column("shipment_id", sa.String(36), nullable=False),
        sa.Column("active_shipment_id", sa.String(36)),
        sa.Column("requested_by", sa.String(36), nullable=False),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("reviewed_by", sa.String(36)),
        sa.Column("reviewed_at", mysql.DATETIME(fsp=6)),
        sa.Column("review_comment", sa.String(500)),
        sa.Column("idempotency_key", sa.String(191), nullable=False),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.CheckConstraint(
            "status IN ('PENDING', 'APPROVED', 'REJECTED')",
            name="ck_shipment_void_requests_status",
        ),
        sa.ForeignKeyConstraint(["shipment_id"], ["shipments.shipment_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["active_shipment_id"], ["shipments.shipment_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["requested_by"], ["users.user_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["reviewed_by"], ["users.user_id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("request_id"),
        sa.UniqueConstraint(
            "requested_by",
            "idempotency_key",
            name="uq_shipment_void_request_actor_idempotency",
        ),
        sa.UniqueConstraint("active_shipment_id", name="uq_shipment_void_request_active"),
    )
    op.create_index(
        "ix_shipment_void_requests_shipment",
        "shipment_void_requests",
        ["shipment_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("shipment_void_requests")
    op.drop_constraint("ck_shipments_status", "shipments", type_="check")
    op.create_check_constraint(
        "ck_shipments_status", "shipments", "status IN ('DRAFT', 'SHIPPED')"
    )
