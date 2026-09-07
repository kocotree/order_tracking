"""Store receipt verification separately from original shipment facts."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "20260907_0029"
down_revision: str | None = "20260905_0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "shipment_receipts",
        sa.Column(
            "shipment_id",
            sa.String(36),
            sa.ForeignKey("shipments.shipment_id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("saved_by", sa.String(36), sa.ForeignKey("users.user_id"), nullable=False),
        sa.Column("saved_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("confirmed_by", sa.String(36), sa.ForeignKey("users.user_id")),
        sa.Column("confirmed_at", mysql.DATETIME(fsp=6)),
        sa.CheckConstraint("status IN ('DRAFT', 'CONFIRMED')", name="ck_shipment_receipts_status"),
        sa.CheckConstraint("version >= 0", name="ck_shipment_receipts_version"),
    )
    op.create_table(
        "shipment_receipt_items",
        sa.Column(
            "box_item_id",
            sa.BigInteger(),
            sa.ForeignKey("shipment_box_items.item_id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column(
            "shipment_id",
            sa.String(36),
            sa.ForeignKey("shipment_receipts.shipment_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.CheckConstraint("quantity >= 0", name="ck_shipment_receipt_items_quantity"),
    )


def downgrade() -> None:
    if op.get_bind().scalar(sa.text("SELECT COUNT(*) FROM shipment_receipts")):
        raise RuntimeError("Receipt records must be preserved; cannot downgrade")
    op.drop_table("shipment_receipt_items")
    op.drop_table("shipment_receipts")
