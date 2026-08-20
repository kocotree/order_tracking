"""Create SMS challenges and administrator applications.

Revision ID: 20260820_0006
Revises: 20260820_0005
Create Date: 2026-08-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "20260820_0006"
down_revision: str | None = "20260820_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sms_challenges",
        sa.Column("challenge_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("phone_encrypted", sa.Text(), nullable=False),
        sa.Column("phone_digest", sa.String(length=64), nullable=False),
        sa.Column("phone_masked", sa.String(length=32), nullable=False),
        sa.Column("purpose", sa.String(length=64), nullable=False),
        sa.Column("code_digest", sa.String(length=64), nullable=False),
        sa.Column("expires_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("send_status", sa.String(length=32), nullable=False),
        sa.Column("failure_reason", sa.String(length=100), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("verified_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("invalidated_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("request_id", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=6),
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("challenge_id"),
    )
    op.create_index(
        "ix_sms_challenges_user_purpose_created",
        "sms_challenges",
        ["user_id", "purpose", "created_at"],
    )
    op.create_table(
        "admin_applications",
        sa.Column("application_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("pending_user_id", sa.String(length=36), nullable=True),
        sa.Column("feishu_display_name_snapshot", sa.String(length=100), nullable=False),
        sa.Column("feishu_avatar_url_snapshot", sa.String(length=500), nullable=True),
        sa.Column("phone_encrypted", sa.Text(), nullable=False),
        sa.Column("phone_digest", sa.String(length=64), nullable=False),
        sa.Column("phone_masked", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("submitted_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("reviewed_by", sa.String(length=36), nullable=True),
        sa.Column("reviewed_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("previous_application_id", sa.String(length=36), nullable=True),
        sa.ForeignKeyConstraint(
            ["previous_application_id"],
            ["admin_applications.application_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["reviewed_by"], ["users.user_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("application_id"),
        sa.UniqueConstraint("pending_user_id", name="uq_admin_applications_pending_user"),
    )
    op.create_index(
        "ix_admin_applications_status_submitted",
        "admin_applications",
        ["status", "submitted_at"],
    )


def downgrade() -> None:
    op.drop_table("admin_applications")
    op.drop_table("sms_challenges")
