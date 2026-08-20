"""Add the WeChat fallback avatar URL.

Revision ID: 20260820_0008
Revises: 20260820_0007
Create Date: 2026-08-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260820_0008"
down_revision: str | None = "20260820_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("mini_avatar_external_url", sa.String(length=500), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "mini_avatar_external_url")
