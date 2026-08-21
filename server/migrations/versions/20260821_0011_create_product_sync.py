"""Create product synchronization tables.

Revision ID: 20260821_0011
Revises: 20260820_0010
Create Date: 2026-08-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "20260821_0011"
down_revision: str | None = "20260820_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "products",
        sa.Column("product_id", sa.String(length=36), nullable=False),
        sa.Column("source_i_id", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("is_available", sa.Boolean(), server_default=sa.text("0"), nullable=False),
        sa.Column("image_source_ref", sa.String(length=1000), nullable=True),
        sa.Column("image_object_key", sa.String(length=500), nullable=True),
        sa.Column(
            "image_cache_status", sa.String(length=32), server_default="missing", nullable=False
        ),
        sa.Column("image_cache_error", sa.String(length=100), nullable=True),
        sa.Column("source_modified_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("first_synced_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("last_synced_at", mysql.DATETIME(fsp=6), nullable=False),
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
        sa.PrimaryKeyConstraint("product_id"),
        sa.UniqueConstraint("source_i_id", name="uq_products_source_i_id"),
        sa.UniqueConstraint("name", name="uq_products_name"),
    )
    op.create_table(
        "product_variants",
        sa.Column("variant_id", sa.String(length=36), nullable=False),
        sa.Column("product_id", sa.String(length=36), nullable=False),
        sa.Column("source_sku_id", sa.String(length=100), nullable=False),
        sa.Column("properties_value", sa.String(length=255), nullable=False),
        sa.Column("source_category", sa.String(length=100), nullable=True),
        sa.Column("source_enabled", sa.Integer(), nullable=True),
        sa.Column("is_available", sa.Boolean(), server_default=sa.text("0"), nullable=False),
        sa.Column("source_modified_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("first_synced_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("last_synced_at", mysql.DATETIME(fsp=6), nullable=False),
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
        sa.ForeignKeyConstraint(["product_id"], ["products.product_id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("variant_id"),
        sa.UniqueConstraint("source_sku_id", name="uq_product_variants_source_sku_id"),
        sa.UniqueConstraint(
            "product_id", "properties_value", name="uq_product_variants_product_properties"
        ),
    )
    op.create_index(
        "ix_product_variants_available", "product_variants", ["is_available", "variant_id"]
    )
    op.create_table(
        "product_sync_runs",
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("run_type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("active_key", sa.String(length=64), nullable=True),
        sa.Column("start_cursor", sa.String(length=255), nullable=True),
        sa.Column("candidate_cursor", sa.String(length=255), nullable=True),
        sa.Column("success_cursor", sa.String(length=255), nullable=True),
        sa.Column("started_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("finished_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("worker_id", sa.String(length=100), nullable=False),
        sa.Column("request_id", sa.String(length=64), nullable=False),
        sa.Column("pages_read", sa.Integer(), server_default="0", nullable=False),
        sa.Column("records_read", sa.Integer(), server_default="0", nullable=False),
        sa.Column("included_records", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_records", sa.Integer(), server_default="0", nullable=False),
        sa.Column("updated_records", sa.Integer(), server_default="0", nullable=False),
        sa.Column("ignored_records", sa.Integer(), server_default="0", nullable=False),
        sa.Column("disabled_records", sa.Integer(), server_default="0", nullable=False),
        sa.Column("moved_out_records", sa.Integer(), server_default="0", nullable=False),
        sa.Column("image_jobs_created", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=6),
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("run_id"),
        sa.UniqueConstraint("active_key", name="uq_product_sync_runs_active_key"),
    )
    op.create_index("ix_product_sync_runs_success", "product_sync_runs", ["status", "finished_at"])


def downgrade() -> None:
    op.drop_index("ix_product_sync_runs_success", table_name="product_sync_runs")
    op.drop_table("product_sync_runs")
    op.drop_index("ix_product_variants_available", table_name="product_variants")
    op.drop_table("product_variants")
    op.drop_table("products")
