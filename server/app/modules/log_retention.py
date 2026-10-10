import gzip
import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Any, cast

from sqlalchemy import Table, and_, exists, not_, or_, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.adapters.private_files import PrivateFileStore
from app.db.models import (
    AuditLog,
    BackgroundJob,
    LogArchiveEntry,
    OrderImportRun,
    OutboxMessage,
    ProductSyncRun,
    ProductSyncStagedVariant,
)
from app.modules.infrastructure import utc_now

TABLES: dict[str, Table] = {
    model.__tablename__: cast(Table, model.__table__)
    for model in (AuditLog, OrderImportRun, ProductSyncRun, BackgroundJob, OutboxMessage)
}
PREFIX = "log-archives/v1/"
PROTECTED_ACTIONS = (
    "shipment_withdrawn", "shipment_submitted", "shipment_resubmitted",
    "shipment_writeback.execute",
)
COMPLETED_JOB_TYPES = (
    "order_auto_sync", "order_import", "order_import_revalidate", "product-image-cache",
    "notification_due_scan", "shipment_writeback",
    "product-sync-initial", "product-sync-incremental",
    "incoming_diff.recognize", "incoming_diff.import", "incoming_diff.confirm",
    "incoming_diff.regenerate", "incoming_diff.decision",
)


def display_cutoff(now: datetime | None = None) -> datetime:
    return (now or utc_now()) - timedelta(days=30)


def eligibility(name: str) -> Any:
    table = TABLES[name]
    if name == "audit_logs":
        return and_(
            table.c.action.not_in(PROTECTED_ACTIONS),
            ~exists(select(OrderImportRun.run_id).where(
                OrderImportRun.request_id == table.c.request_id,
                OrderImportRun.status != "SUCCEEDED",
            )),
        )
    if name == "order_import_runs":
        return and_(table.c.status == "SUCCEEDED", table.c.active_key.is_(None),
                    table.c.finished_at.is_not(None), table.c.archived_at.is_(None))
    if name == "product_sync_runs":
        latest = select(ProductSyncRun.run_id).where(
            ProductSyncRun.status == "succeeded",
            ProductSyncRun.run_type.in_(("initial", "incremental")),
        ).order_by(ProductSyncRun.finished_at.desc(), ProductSyncRun.run_id.desc()).limit(1)
        latest_id = latest.correlate(None).scalar_subquery()
        return and_(
            table.c.status == "succeeded", table.c.active_key.is_(None),
            table.c.finished_at.is_not(None),
            or_(latest_id.is_(None), table.c.run_id != latest_id),
            ~exists(select(ProductSyncStagedVariant.staged_id).where(
                ProductSyncStagedVariant.run_id == table.c.run_id,
            )),
        )
    if name == "background_jobs":
        return and_(table.c.status == "completed", table.c.locked_by.is_(None),
                    table.c.job_type.in_(COMPLETED_JOB_TYPES), table.c.archived_at.is_(None))
    deliveries = OutboxMessage.__table__.alias("dependent_delivery")
    return and_(
        table.c.status == "completed", table.c.manual_review_required.is_(False),
        table.c.locked_by.is_(None), table.c.archived_at.is_(None),
        not_(and_(table.c.message_kind == "business_event",
                  table.c.event_type.in_(("shipment.submitted", "shipment.withdrawn")))),
        ~exists(select(deliveries.c.id).where(
            deliveries.c.source_event_id == table.c.id,
            or_(deliveries.c.status != "completed", deliveries.c.manual_review_required.is_(True)),
        )),
    )


def encode(name: str, row: dict[str, Any]) -> bytes:
    fields = {key: value.isoformat(timespec="microseconds") if isinstance(value, datetime)
              else value for key, value in row.items()}
    return gzip.compress(json.dumps(
        {"version": 1, "table": name, "count": 1, "record": fields},
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode(), mtime=0)


class LogRetention:
    def __init__(self, sessions: sessionmaker[Session], store: PrivateFileStore) -> None:
        self.sessions = sessions
        self.store = store

    @contextmanager
    def lock(self) -> Iterator[None]:
        with self.sessions() as session:
            if session.scalar(text("SELECT GET_LOCK('log_retention', 0)")) != 1:
                raise RuntimeError("log_retention_busy")
            try:
                yield
            finally:
                session.execute(text("SELECT RELEASE_LOCK('log_retention')"))

    def run(self, *, now: datetime | None = None, limit: int = 100) -> dict[str, int]:
        if not 1 <= limit <= 10000:
            raise ValueError("archive_limit_out_of_range")
        current = now or utc_now()
        counts = {name: 0 for name in TABLES}
        with self.lock():
            with self.sessions() as session:
                pending = list(session.execute(select(
                    LogArchiveEntry.source_table, LogArchiveEntry.source_id,
                ).where(LogArchiveEntry.status == "pending").limit(limit)))
            for name, source_id in pending:
                counts[name] += int(self.finish(name, source_id, current))
            for name, table in TABLES.items():
                primary = list(table.primary_key)[0]
                with self.sessions() as session:
                    ids = list(session.scalars(select(primary).where(
                        table.c.created_at < current - timedelta(days=30), eligibility(name),
                    ).order_by(table.c.created_at, primary).limit(limit)))
                for source_id in ids:
                    if self.prepare(name, source_id, current):
                        counts[name] += int(self.finish(name, str(source_id), current))
            counts["expired"] = self.expire(current, limit * (len(TABLES) + 1))
        return counts

    def prepare(self, name: str, source_id: Any, now: datetime) -> bool:
        table = TABLES[name]
        primary = list(table.primary_key)[0]
        with self.sessions() as session, session.begin():
            row = session.execute(select(table).where(
                primary == source_id, eligibility(name),
                table.c.created_at < now - timedelta(days=30),
            ).with_for_update()).mappings().one_or_none()
            if row is None:
                return False
            content = encode(name, dict(row))
            checksum = hashlib.sha256(content).hexdigest()
            if session.get(LogArchiveEntry, (name, str(source_id))) is None:
                session.add(LogArchiveEntry(
                    source_table=name, source_id=str(source_id), source_created_at=row.created_at,
                    object_key=(f"{PREFIX}{self.store.bucket}/{name}/{row.created_at:%Y-%m-%d}/"
                                f"{source_id}-{checksum}.json.gz"),
                    sha256=checksum, size_bytes=len(content), format_version=1, status="pending",
                    expires_at=row.created_at + timedelta(days=180),
                ))
            return True

    def finish(self, name: str, source_id: str, now: datetime) -> bool:
        table = TABLES[name]
        primary = list(table.primary_key)[0]
        with self.sessions() as session, session.begin():
            entry = session.get(LogArchiveEntry, (name, source_id), with_for_update=True)
            if entry is None or entry.status != "pending":
                return False
            self.validate_location(entry)
            row = session.execute(select(table).where(
                primary == source_id, eligibility(name),
                table.c.created_at < now - timedelta(days=30),
            ).with_for_update()).mappings().one_or_none()
            if row is None and session.execute(select(primary).where(
                primary == source_id,
            )).first() is None:
                raise ValueError("archive_pending_source_missing")
            if row is None or hashlib.sha256(encode(name, dict(row))).hexdigest() != entry.sha256:
                # 来源仍在数据库，废弃旧候选后由下一轮重新评估。
                self.store.delete(object_key=entry.object_key)
                session.delete(entry)
                return False
            content = encode(name, dict(row))
            self.store.put(object_key=entry.object_key, content=content,
                           content_type="application/gzip")
            self.read(entry)
            if name in {"audit_logs", "product_sync_runs"}:
                session.execute(table.delete().where(primary == source_id))
            else:
                changes: dict[str, Any] = {"archived_at": now}
                if name == "order_import_runs":
                    changes.update(sync_result={}, error_message=None)
                elif name == "background_jobs":
                    changes.update(payload={}, last_error=None)
                else:
                    changes.update(payload={}, last_error_summary=None)
                session.execute(table.update().where(primary == source_id).values(**changes))
            entry.status = "completed"
            return True

    def validate_location(self, entry: LogArchiveEntry) -> None:
        if not entry.object_key.startswith(f"{PREFIX}{self.store.bucket}/"):
            raise ValueError("archive_bucket_or_prefix_mismatch")

    def read(self, entry: LogArchiveEntry) -> dict[str, Any]:
        self.validate_location(entry)
        content = self.store.get(object_key=entry.object_key)
        if len(content) != entry.size_bytes or hashlib.sha256(content).hexdigest() != entry.sha256:
            raise ValueError("archive_checksum_mismatch")
        document: dict[str, Any] = json.loads(gzip.decompress(content))
        primary = list(TABLES[entry.source_table].primary_key)[0].name
        if (document["version"] != entry.format_version or document["count"] != 1
                or document["table"] != entry.source_table
                or str(document["record"][primary]) != entry.source_id
                or document["record"]["created_at"] != entry.source_created_at.isoformat(
                    timespec="microseconds")):
            raise ValueError("archive_identity_mismatch")
        return document

    def expire(self, now: datetime, limit: int) -> int:
        with self.sessions() as session, session.begin():
            entries = session.scalars(select(LogArchiveEntry).where(
                LogArchiveEntry.status == "completed", LogArchiveEntry.expires_at <= now,
            ).order_by(LogArchiveEntry.expires_at).limit(limit).with_for_update()).all()
            for entry in entries:
                self.validate_location(entry)
                self.store.delete(object_key=entry.object_key)
                session.delete(entry)
            return len(entries)
