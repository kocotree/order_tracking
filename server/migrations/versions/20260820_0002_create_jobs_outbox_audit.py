"""Create background jobs, outbox messages, and audit logs.

Revision ID: 20260820_0002
Revises: 20260820_0001
Create Date: 2026-08-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260820_0002"
down_revision: str | None = "20260820_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "background_jobs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("job_type", sa.String(length=100), nullable=False),
        sa.Column("dedupe_key", sa.String(length=191), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="pending", nullable=False),
        sa.Column("available_at", sa.DateTime(), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("locked_by", sa.String(length=100), nullable=True),
        sa.Column("locked_at", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_type", "dedupe_key", name="uq_background_job_type_dedupe"),
    )
    op.create_index(
        "ix_background_jobs_claim",
        "background_jobs",
        ["status", "available_at", "id"],
    )
    op.create_table(
        "outbox_messages",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("aggregate_type", sa.String(length=100), nullable=False),
        sa.Column("aggregate_id", sa.String(length=100), nullable=False),
        sa.Column("dedupe_key", sa.String(length=191), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="pending", nullable=False),
        sa.Column("available_at", sa.DateTime(), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dedupe_key", name="uq_outbox_dedupe_key"),
    )
    op.create_index(
        "ix_outbox_messages_publish",
        "outbox_messages",
        ["status", "available_at", "id"],
    )
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("request_id", sa.String(length=64), nullable=False),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("target_type", sa.String(length=100), nullable=False),
        sa.Column("target_id", sa.String(length=100), nullable=False),
        sa.Column("changes", sa.JSON(), nullable=False),
        sa.Column("actor_id", sa.String(length=64), nullable=True),
        sa.Column("source_terminal", sa.String(length=32), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_logs_request_id", "audit_logs", ["request_id"])


def downgrade() -> None:
    op.drop_index("ix_audit_logs_request_id", table_name="audit_logs")
    op.drop_table("audit_logs")
    op.drop_index("ix_outbox_messages_publish", table_name="outbox_messages")
    op.drop_table("outbox_messages")
    op.drop_index("ix_background_jobs_claim", table_name="background_jobs")
    op.drop_table("background_jobs")
