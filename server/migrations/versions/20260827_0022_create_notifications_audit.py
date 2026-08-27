"""Create S11 notifications, authorization history, and delivery state.

Revision ID: 20260827_0022
Revises: 20260827_0021
Create Date: 2026-08-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "20260827_0022"
down_revision: str | None = "20260827_0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "notification_authorizations",
        sa.Column("authorization_id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("template_key", sa.String(100), nullable=False),
        sa.Column("result", sa.String(32), nullable=False),
        sa.Column("authorized_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("consumed_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=6),
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "result IN ('accepted', 'rejected', 'closed')",
            name="ck_notification_authorizations_result",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("authorization_id"),
    )
    op.create_index(
        "ix_notification_authorizations_available",
        "notification_authorizations",
        ["user_id", "template_key", "result", "consumed_at", "authorization_id"],
    )

    op.create_table(
        "notifications",
        sa.Column("notification_id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("recipient_id", sa.String(36), nullable=False),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("target_type", sa.String(64), nullable=False),
        sa.Column("target_id", sa.String(100), nullable=False),
        sa.Column("title", sa.String(191), nullable=False),
        sa.Column("summary", sa.String(500), nullable=False),
        sa.Column("target_path", sa.String(500), nullable=False),
        sa.Column("dedupe_key", sa.String(191), nullable=False),
        sa.Column("read_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=6),
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["recipient_id"], ["users.user_id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("notification_id"),
        sa.UniqueConstraint("recipient_id", "dedupe_key", name="uq_notifications_recipient_dedupe"),
    )
    op.create_index(
        "ix_notifications_recipient_created",
        "notifications",
        ["recipient_id", "created_at", "notification_id"],
    )
    op.create_index(
        "ix_notifications_recipient_unread",
        "notifications",
        ["recipient_id", "read_at", "created_at", "notification_id"],
    )

    op.add_column(
        "outbox_messages",
        sa.Column("message_kind", sa.String(32), server_default="business_event", nullable=False),
    )
    op.add_column("outbox_messages", sa.Column("channel", sa.String(32), nullable=True))
    op.add_column("outbox_messages", sa.Column("recipient_id", sa.String(36), nullable=True))
    op.add_column("outbox_messages", sa.Column("source_event_id", sa.BigInteger(), nullable=True))
    op.add_column("outbox_messages", sa.Column("locked_by", sa.String(100), nullable=True))
    op.add_column(
        "outbox_messages", sa.Column("locked_at", mysql.DATETIME(fsp=6), nullable=True)
    )
    op.add_column(
        "outbox_messages", sa.Column("last_error_code", sa.String(100), nullable=True)
    )
    op.add_column(
        "outbox_messages", sa.Column("last_error_summary", sa.String(500), nullable=True)
    )
    op.add_column(
        "outbox_messages", sa.Column("failed_at", mysql.DATETIME(fsp=6), nullable=True)
    )
    op.add_column(
        "outbox_messages", sa.Column("completed_at", mysql.DATETIME(fsp=6), nullable=True)
    )
    op.add_column(
        "outbox_messages",
        sa.Column("manual_review_required", sa.Boolean(), server_default="0", nullable=False),
    )
    op.add_column(
        "outbox_messages", sa.Column("alert_status", sa.String(32), nullable=True)
    )
    op.add_column(
        "outbox_messages", sa.Column("alert_error_code", sa.String(100), nullable=True)
    )
    op.create_foreign_key(
        "fk_outbox_messages_recipient",
        "outbox_messages",
        "users",
        ["recipient_id"],
        ["user_id"],
        ondelete="RESTRICT",
    )
    op.drop_index("ix_outbox_messages_publish", table_name="outbox_messages")
    op.create_index(
        "ix_outbox_messages_claim",
        "outbox_messages",
        ["message_kind", "status", "available_at", "id"],
    )
    op.create_index(
        "ix_outbox_messages_recipient",
        "outbox_messages",
        ["recipient_id", "channel", "status", "id"],
    )

    op.create_index(
        "ix_audit_logs_target_created",
        "audit_logs",
        ["target_type", "target_id", "created_at", "id"],
    )
    op.create_index(
        "ix_audit_logs_actor_created",
        "audit_logs",
        ["actor_id", "created_at", "id"],
    )
    op.create_index(
        "ix_audit_logs_terminal_created",
        "audit_logs",
        ["source_terminal", "created_at", "id"],
    )


def downgrade() -> None:
    op.drop_index("ix_audit_logs_terminal_created", table_name="audit_logs")
    op.drop_index("ix_audit_logs_actor_created", table_name="audit_logs")
    op.drop_index("ix_audit_logs_target_created", table_name="audit_logs")
    op.drop_constraint("fk_outbox_messages_recipient", "outbox_messages", type_="foreignkey")
    op.drop_index("ix_outbox_messages_recipient", table_name="outbox_messages")
    op.drop_index("ix_outbox_messages_claim", table_name="outbox_messages")
    op.create_index(
        "ix_outbox_messages_publish",
        "outbox_messages",
        ["status", "available_at", "id"],
    )
    op.drop_column("outbox_messages", "alert_error_code")
    op.drop_column("outbox_messages", "alert_status")
    op.drop_column("outbox_messages", "manual_review_required")
    op.drop_column("outbox_messages", "completed_at")
    op.drop_column("outbox_messages", "failed_at")
    op.drop_column("outbox_messages", "last_error_summary")
    op.drop_column("outbox_messages", "last_error_code")
    op.drop_column("outbox_messages", "locked_at")
    op.drop_column("outbox_messages", "locked_by")
    op.drop_column("outbox_messages", "source_event_id")
    op.drop_column("outbox_messages", "recipient_id")
    op.drop_column("outbox_messages", "channel")
    op.drop_column("outbox_messages", "message_kind")
    op.drop_table("notifications")
    op.drop_table("notification_authorizations")
