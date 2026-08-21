from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import AuditLog, BackgroundJob, IdempotencyRecord, OutboxMessage


@dataclass(frozen=True)
class ClaimedJob:
    id: int
    job_type: str
    payload: dict[str, Any]
    status: str
    locked_by: str
    attempts: int


@dataclass(frozen=True)
class AuditEntry:
    request_id: str
    action: str
    target_type: str
    target_id: str
    changes: dict[str, Any]


@dataclass(frozen=True)
class JobSnapshot:
    id: int
    status: str
    attempts: int
    locked_by: str | None


def utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class InfrastructureStore:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def reserve_idempotency(self, *, scope: str, key: str) -> bool:
        with self._session_factory() as session:
            session.add(IdempotencyRecord(scope=scope, idempotency_key=key))
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
                existing = session.scalar(
                    select(IdempotencyRecord.id).where(
                        IdempotencyRecord.scope == scope,
                        IdempotencyRecord.idempotency_key == key,
                    )
                )
                if existing is None:
                    raise
                return False
        return True

    def enqueue_job(
        self,
        *,
        job_type: str,
        dedupe_key: str,
        payload: dict[str, Any],
        available_at: datetime,
    ) -> int:
        with self._session_factory() as session:
            job = BackgroundJob(
                job_type=job_type,
                dedupe_key=dedupe_key,
                payload=payload,
                available_at=available_at,
            )
            session.add(job)
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
                existing_id = session.scalar(
                    select(BackgroundJob.id).where(
                        BackgroundJob.job_type == job_type,
                        BackgroundJob.dedupe_key == dedupe_key,
                    )
                )
                if existing_id is None:
                    raise
                return existing_id
            return job.id

    def claim_next_job(self, *, worker_id: str, now: datetime) -> ClaimedJob | None:
        with self._session_factory() as session, session.begin():
            job = session.scalar(
                select(BackgroundJob)
                .where(
                    BackgroundJob.status == "pending",
                    BackgroundJob.available_at <= now,
                )
                .order_by(BackgroundJob.id)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if job is None:
                return None
            job.status = "running"
            job.locked_by = worker_id
            job.locked_at = now
            job.attempts += 1
            job.updated_at = now
            return ClaimedJob(
                id=job.id,
                job_type=job.job_type,
                payload=job.payload,
                status=job.status,
                locked_by=worker_id,
                attempts=job.attempts,
            )

    def recover_stale_jobs(self, *, before: datetime) -> int:
        with self._session_factory() as session, session.begin():
            result = cast(
                CursorResult[Any],
                session.execute(
                    update(BackgroundJob)
                    .where(
                        BackgroundJob.status == "running",
                        BackgroundJob.locked_at < before,
                    )
                    .values(
                        status="pending",
                        locked_by=None,
                        locked_at=None,
                        updated_at=utc_now(),
                    )
                ),
            )
            return int(result.rowcount or 0)

    def complete_job(self, *, job_id: int, now: datetime | None = None) -> None:
        completed_at = now or utc_now()
        with self._session_factory() as session, session.begin():
            session.execute(
                update(BackgroundJob)
                .where(BackgroundJob.id == job_id, BackgroundJob.status == "running")
                .values(
                    status="completed",
                    locked_by=None,
                    locked_at=None,
                    updated_at=completed_at,
                )
            )

    def fail_job(self, *, job_id: int, error_code: str, now: datetime | None = None) -> None:
        failed_at = now or utc_now()
        with self._session_factory() as session, session.begin():
            session.execute(
                update(BackgroundJob)
                .where(BackgroundJob.id == job_id, BackgroundJob.status == "running")
                .values(
                    status="failed",
                    locked_by=None,
                    locked_at=None,
                    last_error=error_code,
                    updated_at=failed_at,
                )
            )

    def retry_job(
        self,
        *,
        job_id: int,
        error_code: str,
        available_at: datetime,
    ) -> None:
        with self._session_factory() as session, session.begin():
            session.execute(
                update(BackgroundJob)
                .where(BackgroundJob.id == job_id, BackgroundJob.status == "running")
                .values(
                    status="pending",
                    available_at=available_at,
                    locked_by=None,
                    locked_at=None,
                    last_error=error_code,
                    updated_at=utc_now(),
                )
            )

    def get_job(self, *, job_id: int) -> JobSnapshot:
        with self._session_factory() as session:
            job = session.get(BackgroundJob, job_id)
            if job is None:
                raise KeyError(job_id)
            return JobSnapshot(
                id=job.id,
                status=job.status,
                attempts=job.attempts,
                locked_by=job.locked_by,
            )

    def enqueue_outbox(
        self,
        *,
        event_type: str,
        aggregate_type: str,
        aggregate_id: str,
        dedupe_key: str,
        payload: dict[str, Any],
    ) -> int:
        with self._session_factory() as session:
            message = OutboxMessage(
                event_type=event_type,
                aggregate_type=aggregate_type,
                aggregate_id=aggregate_id,
                dedupe_key=dedupe_key,
                payload=payload,
                available_at=utc_now(),
            )
            session.add(message)
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
                existing_id = session.scalar(
                    select(OutboxMessage.id).where(OutboxMessage.dedupe_key == dedupe_key)
                )
                if existing_id is None:
                    raise
                return existing_id
            return message.id

    def append_audit_log(
        self,
        *,
        request_id: str,
        action: str,
        target_type: str,
        target_id: str,
        changes: dict[str, Any],
        actor_id: str | None = None,
        source_terminal: str | None = None,
    ) -> int:
        with self._session_factory() as session:
            entry = AuditLog(
                request_id=request_id,
                action=action,
                target_type=target_type,
                target_id=target_id,
                changes=changes,
                actor_id=actor_id,
                source_terminal=source_terminal,
            )
            session.add(entry)
            session.commit()
            return entry.id

    def list_audit_logs(self, *, request_id: str) -> list[AuditEntry]:
        with self._session_factory() as session:
            entries = session.scalars(
                select(AuditLog).where(AuditLog.request_id == request_id).order_by(AuditLog.id)
            ).all()
            return [
                AuditEntry(
                    request_id=entry.request_id,
                    action=entry.action,
                    target_type=entry.target_type,
                    target_id=entry.target_id,
                    changes=entry.changes,
                )
                for entry in entries
            ]
