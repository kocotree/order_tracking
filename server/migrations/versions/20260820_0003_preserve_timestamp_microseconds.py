"""Preserve timestamp microseconds.

Revision ID: 20260820_0003
Revises: 20260820_0002
Create Date: 2026-08-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "20260820_0003"
down_revision: str | None = "20260820_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "idempotency_records",
        "created_at",
        existing_type=sa.DateTime(),
        type_=mysql.DATETIME(fsp=6),
        existing_nullable=False,
        existing_server_default=sa.text("CURRENT_TIMESTAMP"),
        server_default=sa.text("CURRENT_TIMESTAMP(6)"),
    )
    for column_name in ("available_at", "locked_at"):
        op.alter_column(
            "background_jobs",
            column_name,
            existing_type=sa.DateTime(),
            type_=mysql.DATETIME(fsp=6),
            existing_nullable=column_name == "locked_at",
        )
    for column_name in ("created_at", "updated_at"):
        op.alter_column(
            "background_jobs",
            column_name,
            existing_type=sa.DateTime(),
            type_=mysql.DATETIME(fsp=6),
            existing_nullable=False,
            existing_server_default=sa.text("CURRENT_TIMESTAMP"),
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
        )
    for column_name in ("available_at", "sent_at"):
        op.alter_column(
            "outbox_messages",
            column_name,
            existing_type=sa.DateTime(),
            type_=mysql.DATETIME(fsp=6),
            existing_nullable=column_name == "sent_at",
        )
    op.alter_column(
        "outbox_messages",
        "created_at",
        existing_type=sa.DateTime(),
        type_=mysql.DATETIME(fsp=6),
        existing_nullable=False,
        existing_server_default=sa.text("CURRENT_TIMESTAMP"),
        server_default=sa.text("CURRENT_TIMESTAMP(6)"),
    )
    op.alter_column(
        "audit_logs",
        "created_at",
        existing_type=sa.DateTime(),
        type_=mysql.DATETIME(fsp=6),
        existing_nullable=False,
        existing_server_default=sa.text("CURRENT_TIMESTAMP"),
        server_default=sa.text("CURRENT_TIMESTAMP(6)"),
    )


def downgrade() -> None:
    op.alter_column(
        "audit_logs",
        "created_at",
        existing_type=mysql.DATETIME(fsp=6),
        type_=sa.DateTime(),
        existing_nullable=False,
        existing_server_default=sa.text("CURRENT_TIMESTAMP(6)"),
        server_default=sa.text("CURRENT_TIMESTAMP"),
    )
    op.alter_column(
        "outbox_messages",
        "created_at",
        existing_type=mysql.DATETIME(fsp=6),
        type_=sa.DateTime(),
        existing_nullable=False,
        existing_server_default=sa.text("CURRENT_TIMESTAMP(6)"),
        server_default=sa.text("CURRENT_TIMESTAMP"),
    )
    for column_name in ("available_at", "sent_at"):
        op.alter_column(
            "outbox_messages",
            column_name,
            existing_type=mysql.DATETIME(fsp=6),
            type_=sa.DateTime(),
            existing_nullable=column_name == "sent_at",
        )
    for column_name in ("created_at", "updated_at"):
        op.alter_column(
            "background_jobs",
            column_name,
            existing_type=mysql.DATETIME(fsp=6),
            type_=sa.DateTime(),
            existing_nullable=False,
            existing_server_default=sa.text("CURRENT_TIMESTAMP(6)"),
            server_default=sa.text("CURRENT_TIMESTAMP"),
        )
    for column_name in ("available_at", "locked_at"):
        op.alter_column(
            "background_jobs",
            column_name,
            existing_type=mysql.DATETIME(fsp=6),
            type_=sa.DateTime(),
            existing_nullable=column_name == "locked_at",
        )
    op.alter_column(
        "idempotency_records",
        "created_at",
        existing_type=mysql.DATETIME(fsp=6),
        type_=sa.DateTime(),
        existing_nullable=False,
        existing_server_default=sa.text("CURRENT_TIMESTAMP(6)"),
        server_default=sa.text("CURRENT_TIMESTAMP"),
    )
