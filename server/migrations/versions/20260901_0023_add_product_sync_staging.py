"""Add resumable product synchronization staging.

Revision ID: 20260901_0023
Revises: 20260827_0022
Create Date: 2026-09-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "20260901_0023"
down_revision: str | None = "20260827_0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "product_sync_runs",
        sa.Column("source_checkpoint", sa.Text(), nullable=True),
    )
    op.add_column(
        "product_sync_runs",
        sa.Column("next_page", sa.Integer(), server_default="1", nullable=False),
    )
    op.add_column(
        "product_sync_runs",
        sa.Column(
            "source_completed",
            sa.Boolean(),
            server_default=sa.text("0"),
            nullable=False,
        ),
    )
    op.create_table(
        "product_sync_staged_variants",
        sa.Column("staged_id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("source_i_id", sa.String(length=100), nullable=False),
        sa.Column("source_sku_id", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("properties_value", sa.String(length=255), nullable=True),
        sa.Column("pic", sa.String(length=1000), nullable=True),
        sa.Column("category", sa.String(length=100), nullable=True),
        sa.Column("enabled", sa.Integer(), nullable=True),
        sa.Column("source_modified_at", mysql.DATETIME(fsp=6), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["product_sync_runs.run_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("staged_id"),
        sa.UniqueConstraint(
            "run_id",
            "source_sku_id",
            name="uq_product_sync_staged_run_sku",
        ),
    )
    op.create_index(
        "ix_product_sync_staged_run",
        "product_sync_staged_variants",
        ["run_id", "staged_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_product_sync_staged_run",
        table_name="product_sync_staged_variants",
    )
    op.drop_table("product_sync_staged_variants")
    op.drop_column("product_sync_runs", "source_completed")
    op.drop_column("product_sync_runs", "next_page")
    op.drop_column("product_sync_runs", "source_checkpoint")
