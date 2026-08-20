from datetime import datetime
from typing import Any

from sqlalchemy import JSON, BigInteger, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.mysql import DATETIME
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"
    __table_args__ = (
        UniqueConstraint("scope", "idempotency_key", name="uq_idempotency_scope_key"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    scope: Mapped[str] = mapped_column(String(100), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(191), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default="in_progress")
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=6),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(6)"),
    )


class BackgroundJob(Base):
    __tablename__ = "background_jobs"
    __table_args__ = (
        UniqueConstraint("job_type", "dedupe_key", name="uq_background_job_type_dedupe"),
        Index("ix_background_jobs_claim", "status", "available_at", "id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    job_type: Mapped[str] = mapped_column(String(100), nullable=False)
    dedupe_key: Mapped[str] = mapped_column(String(191), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default="pending")
    available_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    locked_by: Mapped[str | None] = mapped_column(String(100))
    locked_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=6),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(6)"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=6),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(6)"),
    )


class OutboxMessage(Base):
    __tablename__ = "outbox_messages"
    __table_args__ = (
        UniqueConstraint("dedupe_key", name="uq_outbox_dedupe_key"),
        Index("ix_outbox_messages_publish", "status", "available_at", "id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    aggregate_type: Mapped[str] = mapped_column(String(100), nullable=False)
    aggregate_id: Mapped[str] = mapped_column(String(100), nullable=False)
    dedupe_key: Mapped[str] = mapped_column(String(191), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default="pending")
    available_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    sent_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=6),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(6)"),
    )


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_logs_request_id", "request_id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    request_id: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    target_type: Mapped[str] = mapped_column(String(100), nullable=False)
    target_id: Mapped[str] = mapped_column(String(100), nullable=False)
    changes: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String(64))
    source_terminal: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=6),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(6)"),
    )
