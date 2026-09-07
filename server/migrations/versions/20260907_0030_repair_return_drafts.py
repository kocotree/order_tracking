"""Persist per-user repair return drafts without changing repair quantities."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260907_0030"
down_revision: str | None = "20260907_0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "repair_return_drafts",
        sa.Column(
            "repair_id",
            sa.String(36),
            sa.ForeignKey("repair_orders.repair_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "user_id",
            sa.String(36),
            sa.ForeignKey("users.user_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("entries", sa.JSON(), nullable=False),
        sa.Column("submission_key", sa.String(36), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("repair_return_drafts")
