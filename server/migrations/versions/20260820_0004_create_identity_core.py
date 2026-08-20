"""Create internal users and scoped external identities.

Revision ID: 20260820_0004
Revises: 20260820_0003
Create Date: 2026-08-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "20260820_0004"
down_revision: str | None = "20260820_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=True),
        sa.Column("is_super_admin", sa.Boolean(), server_default="0", nullable=False),
        sa.Column("is_enabled", sa.Boolean(), server_default="1", nullable=False),
        sa.Column("feishu_display_name", sa.String(length=100), nullable=False),
        sa.Column("feishu_avatar_url", sa.String(length=500), nullable=True),
        sa.Column("phone_encrypted", sa.Text(), nullable=True),
        sa.Column("phone_digest", sa.String(length=64), nullable=True),
        sa.Column("phone_masked", sa.String(length=32), nullable=True),
        sa.Column("mini_avatar_file_id", sa.BigInteger(), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
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
            "is_super_admin = 0 OR role = 'admin'",
            name="ck_users_super_admin_role",
        ),
        sa.PrimaryKeyConstraint("user_id"),
        sa.UniqueConstraint("phone_digest", name="uq_users_phone_digest"),
    )
    op.create_table(
        "external_identities",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("platform", sa.String(length=32), nullable=False),
        sa.Column("scope", sa.String(length=191), nullable=False),
        sa.Column("platform_subject", sa.String(length=191), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column(
            "bound_at",
            mysql.DATETIME(fsp=6),
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.Column(
            "last_login_at",
            mysql.DATETIME(fsp=6),
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "platform",
            "scope",
            "platform_subject",
            name="uq_external_identity_scope_subject",
        ),
    )
    op.create_index(
        "ix_external_identities_user",
        "external_identities",
        ["user_id"],
    )


def downgrade() -> None:
    op.drop_table("external_identities")
    op.drop_table("users")
