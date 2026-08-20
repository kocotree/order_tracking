"""Create OAuth state and user session storage.

Revision ID: 20260820_0005
Revises: 20260820_0004
Create Date: 2026-08-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "20260820_0005"
down_revision: str | None = "20260820_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "oauth_states",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("state_digest", sa.String(length=64), nullable=False),
        sa.Column("terminal", sa.String(length=32), nullable=False),
        sa.Column("return_to", sa.String(length=500), nullable=False),
        sa.Column("expires_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("used_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=6),
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("state_digest", name="uq_oauth_states_digest"),
    )
    op.create_table(
        "user_sessions",
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("terminal", sa.String(length=32), nullable=False),
        sa.Column("token_digest", sa.String(length=64), nullable=False),
        sa.Column("refresh_token_digest", sa.String(length=64), nullable=True),
        sa.Column("csrf_digest", sa.String(length=64), nullable=True),
        sa.Column("expires_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("refresh_expires_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("last_activity_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("revoked_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=6),
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("session_id"),
        sa.UniqueConstraint("refresh_token_digest", name="uq_user_sessions_refresh_digest"),
        sa.UniqueConstraint("token_digest", name="uq_user_sessions_token_digest"),
    )
    op.create_index(
        "ix_user_sessions_user_terminal",
        "user_sessions",
        ["user_id", "terminal", "revoked_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_user_sessions_user_terminal", table_name="user_sessions")
    op.drop_table("user_sessions")
    op.drop_table("oauth_states")
