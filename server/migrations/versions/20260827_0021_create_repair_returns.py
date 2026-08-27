"""Create S10 repair return batches and lines.

Revision ID: 20260827_0021
Revises: 20260826_0020
Create Date: 2026-08-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "20260827_0021"
down_revision: str | None = "20260826_0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "repair_return_batches",
        sa.Column("batch_id", sa.String(36), nullable=False),
        sa.Column("repair_id", sa.String(36), nullable=False),
        sa.Column("submitted_by", sa.String(36), nullable=False),
        sa.Column("submitted_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("idempotency_key", sa.String(191), nullable=False),
        sa.Column("request_sha256", sa.String(64), nullable=False),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=6),
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["repair_id"], ["repair_orders.repair_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["submitted_by"], ["users.user_id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("batch_id"),
        sa.UniqueConstraint(
            "submitted_by",
            "idempotency_key",
            name="uq_repair_return_batches_submitter_key",
        ),
    )
    op.create_index(
        "ix_repair_return_batches_repair",
        "repair_return_batches",
        ["repair_id", "submitted_at", "batch_id"],
    )
    op.create_table(
        "repair_return_lines",
        sa.Column("return_line_id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("batch_id", sa.String(36), nullable=False),
        sa.Column("line_order", sa.Integer(), nullable=False),
        sa.Column("variant_id", sa.String(36), nullable=False),
        sa.Column("repaired_quantity", sa.Integer(), nullable=False),
        sa.Column("scrapped_quantity", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=6),
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "repaired_quantity >= 0 AND scrapped_quantity >= 0",
            name="ck_repair_return_lines_nonnegative",
        ),
        sa.CheckConstraint(
            "repaired_quantity + scrapped_quantity > 0",
            name="ck_repair_return_lines_positive_total",
        ),
        sa.ForeignKeyConstraint(
            ["batch_id"], ["repair_return_batches.batch_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["variant_id"], ["product_variants.variant_id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("return_line_id"),
        sa.UniqueConstraint("batch_id", "line_order", name="uq_repair_return_lines_order"),
        sa.UniqueConstraint("batch_id", "variant_id", name="uq_repair_return_lines_variant"),
    )
    op.create_index(
        "ix_repair_return_lines_batch",
        "repair_return_lines",
        ["batch_id", "line_order"],
    )
    op.create_check_constraint(
        "ck_repair_orders_return_sum",
        "repair_orders",
        "returned_quantity = repaired_quantity + scrapped_quantity",
    )
    op.create_check_constraint(
        "ck_repair_orders_return_not_exceeded",
        "repair_orders",
        "returned_quantity <= warehouse_return_quantity",
    )


def downgrade() -> None:
    op.drop_constraint("ck_repair_orders_return_not_exceeded", "repair_orders", type_="check")
    op.drop_constraint("ck_repair_orders_return_sum", "repair_orders", type_="check")
    op.drop_index("ix_repair_return_lines_batch", table_name="repair_return_lines")
    op.drop_table("repair_return_lines")
    op.drop_index("ix_repair_return_batches_repair", table_name="repair_return_batches")
    op.drop_table("repair_return_batches")
