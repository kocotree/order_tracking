"""Create S06 processing contract tables.

Revision ID: 20260824_0014
Revises: 20260822_0013
Create Date: 2026-08-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "20260824_0014"
down_revision: str | None = "20260822_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamp(name: str, *, nullable: bool = False) -> sa.Column:
    return sa.Column(name, mysql.DATETIME(fsp=6), nullable=nullable)


def upgrade() -> None:
    op.create_table(
        "processing_contracts",
        sa.Column("contract_id", sa.String(36), primary_key=True),
        sa.Column("order_id", sa.String(36), nullable=False),
        sa.Column("factory_id", sa.String(36), nullable=False),
        sa.Column("signing_date", sa.Date(), nullable=False),
        sa.Column("daily_sequence", sa.Integer(), nullable=False),
        sa.Column("contract_no", sa.String(191), nullable=False),
        sa.Column("contract_snapshot", sa.JSON(), nullable=False),
        sa.Column("template_version", sa.String(32), nullable=False),
        sa.Column("created_by", sa.String(36), nullable=False),
        _timestamp("created_at"),
        sa.ForeignKeyConstraint(["order_id"], ["orders.order_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["factory_id"], ["factories.factory_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.user_id"], ondelete="RESTRICT"),
        sa.UniqueConstraint(
            "order_id", "factory_id", name="uq_processing_contract_order_factory"
        ),
        sa.UniqueConstraint("contract_no", name="uq_processing_contract_no"),
        sa.UniqueConstraint(
            "signing_date",
            "factory_id",
            "daily_sequence",
            name="uq_processing_contract_daily_sequence",
        ),
    )
    op.create_index(
        "ix_processing_contract_order",
        "processing_contracts",
        ["order_id", "factory_id"],
    )
    op.create_table(
        "contract_number_counters",
        sa.Column("signing_date", sa.Date(), primary_key=True),
        sa.Column("factory_id", sa.String(36), primary_key=True),
        sa.Column("next_sequence", sa.Integer(), nullable=False),
        _timestamp("updated_at"),
        sa.ForeignKeyConstraint(
            ["factory_id"], ["factories.factory_id"], ondelete="RESTRICT"
        ),
    )
    op.create_table(
        "contract_exports",
        sa.Column("export_id", sa.String(36), primary_key=True),
        sa.Column("contract_id", sa.String(36), nullable=False),
        sa.Column("exported_by", sa.String(36), nullable=False),
        sa.Column("idempotency_key", sa.String(191), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("export_snapshot", sa.JSON(), nullable=False),
        sa.Column("template_version", sa.String(32), nullable=False),
        sa.Column("stored_file_id", sa.BigInteger()),
        sa.Column("error_code", sa.String(100)),
        sa.Column("error_message", sa.String(255)),
        _timestamp("created_at"),
        _timestamp("completed_at", nullable=True),
        sa.ForeignKeyConstraint(
            ["contract_id"], ["processing_contracts.contract_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["exported_by"], ["users.user_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["stored_file_id"], ["stored_files.file_id"], ondelete="RESTRICT"
        ),
        sa.UniqueConstraint(
            "exported_by",
            "idempotency_key",
            name="uq_contract_export_actor_idempotency",
        ),
    )
    op.create_index(
        "ix_contract_exports_contract",
        "contract_exports",
        ["contract_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("contract_exports")
    op.drop_table("contract_number_counters")
    op.drop_table("processing_contracts")
