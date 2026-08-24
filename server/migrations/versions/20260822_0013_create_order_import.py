"""Create S05 Feishu order import tables.

Revision ID: 20260822_0013
Revises: 20260821_0012
Create Date: 2026-08-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "20260822_0013"
down_revision: str | None = "20260821_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamp(name: str, *, nullable: bool = False) -> sa.Column:
    return sa.Column(name, mysql.DATETIME(fsp=6), nullable=nullable)


def upgrade() -> None:
    op.create_table(
        "order_import_runs",
        sa.Column("run_id", sa.String(36), primary_key=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("active_key", sa.String(64)),
        _timestamp("started_at"),
        _timestamp("finished_at", nullable=True),
        sa.Column("requested_by", sa.String(36), nullable=False),
        sa.Column("request_id", sa.String(64), nullable=False),
        sa.Column("idempotency_key", sa.String(191)),
        sa.Column("pages_read", sa.Integer(), server_default="0", nullable=False),
        sa.Column("records_read", sa.Integer(), server_default="0", nullable=False),
        sa.Column("candidates_created", sa.Integer(), server_default="0", nullable=False),
        sa.Column("candidates_updated", sa.Integer(), server_default="0", nullable=False),
        sa.Column("skipped_records", sa.Integer(), server_default="0", nullable=False),
        sa.Column("failed_records", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_code", sa.String(100)),
        sa.Column("error_message", sa.Text()),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=6),
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["requested_by"], ["users.user_id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("active_key", name="uq_order_import_runs_active_key"),
        sa.UniqueConstraint(
            "idempotency_key", name="uq_order_import_runs_idempotency_key"
        ),
    )
    op.create_index("ix_order_import_runs_latest", "order_import_runs", ["started_at", "run_id"])
    op.create_table(
        "order_import_source_records",
        sa.Column("source_record_pk", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("source_scope", sa.String(191), nullable=False),
        sa.Column("source_record_id", sa.String(100), nullable=False),
        sa.Column("source_detail_id", sa.String(100)),
        sa.Column("order_no", sa.String(100)),
        sa.Column("raw_fields", sa.JSON(), nullable=False),
        _timestamp("source_modified_at", nullable=True),
        sa.Column("parse_status", sa.String(32), nullable=False),
        sa.Column("error_code", sa.String(100)),
        sa.Column("error_message", sa.String(255)),
        sa.Column("first_seen_run_id", sa.String(36), nullable=False),
        sa.Column("last_seen_run_id", sa.String(36), nullable=False),
        _timestamp("first_seen_at"),
        _timestamp("last_seen_at"),
        sa.ForeignKeyConstraint(
            ["first_seen_run_id"], ["order_import_runs.run_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["last_seen_run_id"], ["order_import_runs.run_id"], ondelete="RESTRICT"
        ),
        sa.UniqueConstraint("source_scope", "source_record_id", name="uq_import_source_record"),
    )
    op.create_index(
        "ix_import_source_records_order",
        "order_import_source_records",
        ["order_no", "source_record_id"],
    )
    op.create_table(
        "order_import_candidates",
        sa.Column("candidate_id", sa.String(36), primary_key=True),
        sa.Column("order_no", sa.String(100), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("validation_state", sa.String(32), nullable=False),
        sa.Column("validation_issues", sa.JSON(), nullable=False),
        sa.Column("issue_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("source_record_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("order_date", sa.Date()),
        sa.Column("tracker", sa.String(32)),
        sa.Column("contract_ship_date", sa.Date()),
        sa.Column("category", sa.String(100)),
        sa.Column("total_quantity", sa.Integer(), server_default="0", nullable=False),
        sa.Column("shipped_quantity", sa.Integer(), server_default="0", nullable=False),
        sa.Column("pending_quantity", sa.Integer(), server_default="0", nullable=False),
        sa.Column("imported_order_id", sa.String(36)),
        sa.Column("imported_by", sa.String(36)),
        _timestamp("imported_at", nullable=True),
        sa.Column("excluded_by", sa.String(36)),
        _timestamp("excluded_at", nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        _timestamp("created_at"),
        _timestamp("updated_at"),
        sa.ForeignKeyConstraint(["imported_order_id"], ["orders.order_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["excluded_by"], ["users.user_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["imported_by"], ["users.user_id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("order_no", name="uq_order_import_candidates_order_no"),
    )
    op.create_index(
        "ix_order_import_candidates_list",
        "order_import_candidates",
        ["status", "validation_state", "updated_at"],
    )
    op.create_table(
        "order_import_candidate_lines",
        sa.Column("candidate_line_id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("candidate_id", sa.String(36), nullable=False),
        sa.Column("source_record_pk", sa.BigInteger(), nullable=False),
        sa.Column("source_sku_id", sa.String(100)),
        sa.Column("product_name", sa.String(255)),
        sa.Column("properties_value", sa.String(255)),
        sa.Column("category", sa.String(100)),
        sa.Column("factory_name", sa.String(100)),
        sa.Column("order_quantity", sa.Integer()),
        sa.Column("shipped_quantity", sa.Integer(), server_default="0", nullable=False),
        sa.Column("pending_quantity", sa.Integer(), server_default="0", nullable=False),
        sa.Column("matched_variant_id", sa.String(36)),
        sa.Column("matched_factory_id", sa.String(36)),
        sa.Column("image_object_key_snapshot", sa.String(500)),
        sa.Column("validation_issues", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ["candidate_id"], ["order_import_candidates.candidate_id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["source_record_pk"],
            ["order_import_source_records.source_record_pk"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["matched_variant_id"], ["product_variants.variant_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["matched_factory_id"], ["factories.factory_id"], ondelete="RESTRICT"
        ),
        sa.UniqueConstraint(
            "candidate_id", "source_record_pk", name="uq_import_candidate_line_source"
        ),
    )
    op.create_index(
        "ix_import_candidate_lines_candidate",
        "order_import_candidate_lines",
        ["candidate_id", "candidate_line_id"],
    )
    op.create_table(
        "order_import_validation_issues",
        sa.Column("issue_id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("candidate_id", sa.String(36), nullable=False),
        sa.Column("candidate_line_id", sa.BigInteger()),
        sa.Column("code", sa.String(100), nullable=False),
        sa.Column("field_name", sa.String(100)),
        sa.Column("message", sa.String(255), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["candidate_id"], ["order_import_candidates.candidate_id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["candidate_line_id"],
            ["order_import_candidate_lines.candidate_line_id"],
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_import_validation_issues_candidate",
        "order_import_validation_issues",
        ["candidate_id", "sort_order"],
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS order_import_validation_issues")
    op.drop_table("order_import_candidate_lines")
    op.drop_table("order_import_candidates")
    op.drop_table("order_import_source_records")
    op.drop_table("order_import_runs")
