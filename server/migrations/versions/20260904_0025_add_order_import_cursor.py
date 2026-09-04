"""Add reliable Feishu order import cursor and normalized source snapshots.

Revision ID: 20260904_0025
Revises: 20260901_0024
Create Date: 2026-09-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "20260904_0025"
down_revision: str | None = "20260901_0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "order_import_source_records",
        sa.Column("normalized_fields", sa.JSON(), nullable=True),
    )
    op.create_table(
        "order_import_source_cursors",
        sa.Column("source_scope", sa.String(191), primary_key=True),
        sa.Column(
            "successful_modified_at", mysql.DATETIME(fsp=6), nullable=False
        ),
        sa.Column("successful_run_id", sa.String(36), nullable=False),
        sa.Column("successful_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.ForeignKeyConstraint(
            ["successful_run_id"], ["order_import_runs.run_id"], ondelete="RESTRICT"
        ),
    )


def downgrade() -> None:
    op.drop_table("order_import_source_cursors")
    op.drop_column("order_import_source_records", "normalized_fields")
