"""Create shipment evidence file relationships.

Revision ID: 20260904_0026
Revises: 20260904_0025
Create Date: 2026-09-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "20260904_0026"
down_revision: str | None = "20260904_0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "shipment_files",
        sa.Column("shipment_file_id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("shipment_id", sa.String(length=36), nullable=False),
        sa.Column("stored_file_id", sa.BigInteger(), nullable=False),
        sa.Column("display_order", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=6),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
        ),
        sa.CheckConstraint(
            "display_order >= 0 AND display_order < 3",
            name="ck_shipment_files_display_order",
        ),
        sa.ForeignKeyConstraint(
            ["shipment_id"], ["shipments.shipment_id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["stored_file_id"], ["stored_files.file_id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("shipment_file_id"),
        sa.UniqueConstraint("shipment_id", "display_order", name="uq_shipment_files_order"),
        sa.UniqueConstraint("stored_file_id", name="uq_shipment_files_stored_file"),
    )
    op.create_index(
        "ix_shipment_files_shipment",
        "shipment_files",
        ["shipment_id", "display_order"],
    )


def downgrade() -> None:
    op.drop_index("ix_shipment_files_shipment", table_name="shipment_files")
    op.drop_table("shipment_files")
