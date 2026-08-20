"""Create factory applications.

Revision ID: 20260820_0010
Revises: 20260820_0009
Create Date: 2026-08-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "20260820_0010"
down_revision: str | None = "20260820_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "factory_applications",
        sa.Column("application_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("pending_user_id", sa.String(length=36), nullable=True),
        sa.Column("real_name", sa.String(length=100), nullable=False),
        sa.Column("phone_encrypted", sa.Text(), nullable=False),
        sa.Column("phone_digest", sa.String(length=64), nullable=False),
        sa.Column("phone_masked", sa.String(length=32), nullable=False),
        sa.Column("position", sa.String(length=32), nullable=False),
        sa.Column("requested_factory_id", sa.String(length=36), nullable=False),
        sa.Column("bound_factory_id", sa.String(length=36), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("submitted_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("reviewed_by", sa.String(length=36), nullable=True),
        sa.Column("reviewed_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("previous_application_id", sa.String(length=36), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["requested_factory_id"], ["factories.factory_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["bound_factory_id"], ["factories.factory_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["reviewed_by"], ["users.user_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["previous_application_id"],
            ["factory_applications.application_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("application_id"),
        sa.UniqueConstraint("pending_user_id", name="uq_factory_applications_pending_user"),
    )
    op.create_index(
        "ix_factory_applications_status_submitted",
        "factory_applications",
        ["status", "submitted_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_factory_applications_status_submitted", table_name="factory_applications"
    )
    op.drop_table("factory_applications")
