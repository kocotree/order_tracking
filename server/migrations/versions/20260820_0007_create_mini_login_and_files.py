"""Create mini-program login attempts and private stored files.

Revision ID: 20260820_0007
Revises: 20260820_0006
Create Date: 2026-08-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "20260820_0007"
down_revision: str | None = "20260820_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "mini_login_attempts",
        sa.Column("attempt_id", sa.String(length=36), nullable=False),
        sa.Column("token_digest", sa.String(length=64), nullable=False),
        sa.Column("scope", sa.String(length=191), nullable=False),
        sa.Column("platform_subject", sa.String(length=191), nullable=False),
        sa.Column("wechat_avatar_url", sa.String(length=500), nullable=True),
        sa.Column("expires_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("used_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=6),
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("attempt_id"),
        sa.UniqueConstraint("token_digest", name="uq_mini_login_attempt_token"),
    )
    op.create_table(
        "stored_files",
        sa.Column("file_id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("bucket", sa.String(length=100), nullable=False),
        sa.Column("object_key", sa.String(length=191), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("mime_type", sa.String(length=100), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("uploaded_by", sa.String(length=36), nullable=False),
        sa.Column("idempotency_key", sa.String(length=191), nullable=True),
        sa.Column("replaced_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=6),
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["uploaded_by"], ["users.user_id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("file_id"),
        sa.UniqueConstraint("bucket", "object_key", name="uq_stored_files_object"),
        sa.UniqueConstraint(
            "uploaded_by",
            "idempotency_key",
            name="uq_stored_files_upload_request",
        ),
    )
    op.create_foreign_key(
        "fk_users_mini_avatar_file",
        "users",
        "stored_files",
        ["mini_avatar_file_id"],
        ["file_id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_users_mini_avatar_file", "users", type_="foreignkey")
    op.drop_table("stored_files")
    op.drop_table("mini_login_attempts")
