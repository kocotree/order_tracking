"""Create S09 repair upload previews.

Revision ID: 20260826_0020
Revises: 20260825_0019
Create Date: 2026-08-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "20260826_0020"
down_revision: str | None = "20260825_0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "repair_previews",
        sa.Column("preview_id", sa.String(36), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("original_file_id", sa.BigInteger(), nullable=False),
        sa.Column("source_sha256", sa.String(64), nullable=False),
        sa.Column("uploaded_by", sa.String(36), nullable=False),
        sa.Column("factory_id", sa.String(36), nullable=True),
        sa.Column("line_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("box_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("total_quantity", sa.Integer(), server_default="0", nullable=False),
        sa.Column("validation_errors", sa.JSON(), nullable=False),
        sa.Column("validation_warnings", sa.JSON(), nullable=False),
        sa.Column("expires_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("confirmed_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("confirmed_repair_id", sa.String(36), nullable=True),
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
            "status IN ('READY', 'INVALID', 'CONFIRMED')",
            name="ck_repair_previews_status",
        ),
        sa.ForeignKeyConstraint(["factory_id"], ["factories.factory_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["original_file_id"], ["stored_files.file_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["uploaded_by"], ["users.user_id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("preview_id"),
    )
    op.create_index("ix_repair_previews_expiry", "repair_previews", ["status", "expires_at"])
    op.create_index("ix_repair_previews_source_sha256", "repair_previews", ["source_sha256"])
    op.create_table(
        "repair_preview_lines",
        sa.Column("line_id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("preview_id", sa.String(36), nullable=False),
        sa.Column("source_sheet", sa.String(100), nullable=False),
        sa.Column("source_row", sa.Integer(), nullable=False),
        sa.Column("source_order", sa.Integer(), nullable=False),
        sa.Column("box_number", sa.String(100), nullable=False),
        sa.Column("supplier_number", sa.String(32), nullable=False),
        sa.Column("factory_name", sa.String(100), nullable=False),
        sa.Column("source_sku_id", sa.String(100), nullable=False),
        sa.Column("source_product_id", sa.String(100), nullable=False),
        sa.Column("product_name", sa.String(255), nullable=False),
        sa.Column("properties_value", sa.String(255), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("matched_product_id", sa.String(36), nullable=True),
        sa.Column("matched_variant_id", sa.String(36), nullable=True),
        sa.Column("validation_errors", sa.JSON(), nullable=False),
        sa.Column("validation_warnings", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=6),
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.CheckConstraint("quantity > 0", name="ck_repair_preview_lines_quantity_positive"),
        sa.ForeignKeyConstraint(
            ["matched_product_id"], ["products.product_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["matched_variant_id"],
            ["product_variants.variant_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["preview_id"], ["repair_previews.preview_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("line_id"),
        sa.UniqueConstraint("preview_id", "source_order", name="uq_repair_preview_lines_order"),
        sa.UniqueConstraint(
            "preview_id",
            "source_sheet",
            "source_row",
            name="uq_repair_preview_lines_source_row",
        ),
    )
    op.create_index(
        "ix_repair_preview_lines_preview",
        "repair_preview_lines",
        ["preview_id", "source_order"],
    )
    op.create_table(
        "repair_orders",
        sa.Column("repair_id", sa.String(36), nullable=False),
        sa.Column("repair_no", sa.String(32), nullable=False),
        sa.Column("factory_id", sa.String(36), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("warehouse_return_quantity", sa.Integer(), nullable=False),
        sa.Column("repaired_quantity", sa.Integer(), server_default="0", nullable=False),
        sa.Column("scrapped_quantity", sa.Integer(), server_default="0", nullable=False),
        sa.Column("returned_quantity", sa.Integer(), server_default="0", nullable=False),
        sa.Column("return_date", sa.Date(), nullable=False),
        sa.Column("original_file_id", sa.BigInteger(), nullable=False),
        sa.Column("source_sha256", sa.String(64), nullable=False),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("archived_by", sa.String(36), nullable=True),
        sa.Column("archived_at", mysql.DATETIME(fsp=6), nullable=True),
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
        sa.CheckConstraint("status IN ('INCOMPLETE', 'COMPLETED')", name="ck_repair_orders_status"),
        sa.CheckConstraint(
            "warehouse_return_quantity > 0", name="ck_repair_orders_warehouse_positive"
        ),
        sa.CheckConstraint(
            "repaired_quantity >= 0 AND scrapped_quantity >= 0 AND returned_quantity >= 0",
            name="ck_repair_orders_return_counts_nonnegative",
        ),
        sa.ForeignKeyConstraint(["factory_id"], ["factories.factory_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["original_file_id"], ["stored_files.file_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.user_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["archived_by"], ["users.user_id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("repair_id"),
        sa.UniqueConstraint("repair_no", name="uq_repair_orders_no"),
        sa.UniqueConstraint("source_sha256", name="uq_repair_orders_source_sha256"),
    )
    op.create_index(
        "ix_repair_orders_list", "repair_orders", ["status", "return_date", "repair_id"]
    )
    op.create_index(
        "ix_repair_orders_factory", "repair_orders", ["factory_id", "status", "return_date"]
    )
    op.create_table(
        "repair_inspection_lines",
        sa.Column("inspection_line_id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("repair_id", sa.String(36), nullable=False),
        sa.Column("source_sheet", sa.String(100), nullable=False),
        sa.Column("source_row", sa.Integer(), nullable=False),
        sa.Column("source_order", sa.Integer(), nullable=False),
        sa.Column("box_number", sa.String(100), nullable=False),
        sa.Column("product_id", sa.String(36), nullable=False),
        sa.Column("variant_id", sa.String(36), nullable=False),
        sa.Column("source_sku_id", sa.String(100), nullable=False),
        sa.Column("source_product_id", sa.String(100), nullable=False),
        sa.Column("product_name", sa.String(255), nullable=False),
        sa.Column("properties_value", sa.String(255), nullable=False),
        sa.Column("warehouse_return_quantity", sa.Integer(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=6),
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "warehouse_return_quantity > 0", name="ck_repair_inspection_lines_quantity_positive"
        ),
        sa.ForeignKeyConstraint(["repair_id"], ["repair_orders.repair_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["product_id"], ["products.product_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["variant_id"], ["product_variants.variant_id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("inspection_line_id"),
        sa.UniqueConstraint("repair_id", "source_order", name="uq_repair_inspection_lines_order"),
        sa.UniqueConstraint(
            "repair_id", "source_sheet", "source_row", name="uq_repair_inspection_lines_source_row"
        ),
    )
    op.create_index(
        "ix_repair_inspection_lines_repair",
        "repair_inspection_lines",
        ["repair_id", "source_order"],
    )
    op.create_table(
        "repair_number_counters",
        sa.Column("business_date", sa.Date(), nullable=False),
        sa.Column("next_sequence", sa.Integer(), nullable=False),
        sa.Column("updated_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.CheckConstraint("next_sequence > 0", name="ck_repair_number_counters_positive"),
        sa.PrimaryKeyConstraint("business_date"),
    )


def downgrade() -> None:
    op.execute(sa.text("DROP TABLE IF EXISTS repair_number_counters"))
    op.execute(sa.text("DROP TABLE IF EXISTS repair_inspection_lines"))
    op.execute(sa.text("DROP TABLE IF EXISTS repair_orders"))
    op.execute(sa.text("DROP TABLE IF EXISTS repair_preview_lines"))
    op.drop_table("repair_previews")
