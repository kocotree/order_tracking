import json
from datetime import datetime, timedelta

import pytest
from sqlalchemy import Engine, event, func, select, text
from sqlalchemy.orm import Session

from app.adapters.private_files import FakePrivateFileStore, PrivateFileStoreUnavailable
from app.db.models import (
    AuditLog,
    BackgroundJob,
    LogArchiveEntry,
    OrderImportRun,
    OrderImportSourceCursor,
    OutboxMessage,
    ProductSyncRun,
    ProductSyncStagedVariant,
    User,
)
from app.db.session import create_session_factory
from app.modules.infrastructure import InfrastructureStore
from app.modules.log_retention import LogRetention
from app.modules.notifications_audit.service import NotificationsAuditService
from scripts.log_archives import main

NOW = datetime(2026, 10, 10, 12)
OLD = NOW - timedelta(days=31)


def audit(action: str = "order.updated", *, created: datetime = OLD,
          request: str = "request") -> AuditLog:
    return AuditLog(request_id=request, action=action, target_type="order", target_id="order",
                    changes={"quantity": 23, "password": "redact"}, created_at=created)


def test_archive_boundaries_readback_expiry_and_idempotence(test_database_engine: Engine) -> None:
    sessions = create_session_factory(test_database_engine)
    store = FakePrivateFileStore(bucket="archive")
    service = LogRetention(sessions, store)
    with sessions.begin() as session:
        rows = [audit(created=NOW - timedelta(days=30)), audit(),
                audit(created=NOW - timedelta(days=180)), audit("shipment_withdrawn"),
                audit("shipment_submitted"), audit("shipment_writeback.execute")]
        session.add_all(rows)
    counts = service.run(now=NOW)
    assert counts["audit_logs"] == 2
    assert counts["expired"] == 1
    with sessions() as session:
        entry = session.scalars(select(LogArchiveEntry)).one()
        assert service.read(entry)["record"]["changes"]["quantity"] == 23
        assert entry.source_id == str(rows[1].id)
        assert session.scalar(select(func.count()).select_from(AuditLog)) == 4
    assert service.run(now=NOW)["audit_logs"] == 0
    assert store.object_count == 1


@pytest.mark.parametrize("failure", ["put", "read", "corrupt"])
def test_upload_or_verification_failure_keeps_source_and_recovers(
    test_database_engine: Engine, failure: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    sessions = create_session_factory(test_database_engine)
    store = FakePrivateFileStore(bucket="archive")
    service = LogRetention(sessions, store)
    with sessions.begin() as session:
        row = audit()
        session.add(row)
    original = store.get

    def broken_get(*, object_key: str) -> bytes:
        if failure == "read":
            raise PrivateFileStoreUnavailable("interrupted")
        return b"corrupt"

    if failure == "put":
        monkeypatch.setattr(store, "_fail_put", True)
    else:
        monkeypatch.setattr(store, "get", broken_get)
    with pytest.raises((PrivateFileStoreUnavailable, ValueError)):
        service.run(now=NOW)
    with sessions() as session:
        assert session.get(AuditLog, row.id).changes["quantity"] == 23
        assert session.get(LogArchiveEntry, ("audit_logs", str(row.id))).status == "pending"
    monkeypatch.setattr(store, "_fail_put", False)
    monkeypatch.setattr(store, "get", original)
    service.run(now=NOW)
    with sessions() as session:
        assert session.get(AuditLog, row.id) is None
        assert session.get(LogArchiveEntry, ("audit_logs", str(row.id))).status == "completed"


def test_changed_candidate_is_not_deleted(test_database_engine: Engine) -> None:
    sessions = create_session_factory(test_database_engine)
    service = LogRetention(sessions, FakePrivateFileStore(bucket="archive"))
    with sessions.begin() as session:
        row = audit()
        session.add(row)
    assert service.prepare("audit_logs", row.id, NOW)
    with sessions.begin() as session:
        session.get(AuditLog, row.id).changes = {"quantity": 99}
    assert not service.finish("audit_logs", str(row.id), NOW)
    with sessions() as session:
        assert session.get(AuditLog, row.id).changes == {"quantity": 99}
    service.run(now=NOW)
    with sessions() as session:
        assert service.read(session.get(LogArchiveEntry, ("audit_logs", str(row.id))))[
            "record"]["changes"] == {"quantity": 99}


def test_jobs_keep_keys_and_failures_and_outbox_dependencies(test_database_engine: Engine) -> None:
    sessions = create_session_factory(test_database_engine)
    service = LogRetention(sessions, FakePrivateFileStore(bucket="archive"))
    infrastructure = InfrastructureStore(sessions)
    with sessions.begin() as session:
        jobs = [BackgroundJob(job_type="shipment_writeback", dedupe_key=status, status=status,
                              payload={"month": "2026-10"}, available_at=OLD, created_at=OLD)
                for status in ("completed", "failed", "pending", "running")]
        session.add_all(jobs)
        events = [OutboxMessage(event_type=kind, aggregate_type="order", aggregate_id="one",
                                dedupe_key=kind, payload={"factoryId": "keep"},
                                status="completed", available_at=OLD, created_at=OLD)
                  for kind in ("order_detail_dispatched", "shipment.submitted", "ordinary")]
        session.add_all(events)
        session.flush()
        session.add(OutboxMessage(event_type="delivery", aggregate_type="order", aggregate_id="one",
                                 dedupe_key="delivery", payload={}, status="manual_review",
                                 source_event_id=events[0].id, available_at=OLD, created_at=OLD))
    service.run(now=NOW)
    with sessions() as session:
        assert session.get(BackgroundJob, jobs[0].id).payload == {}
        for job in jobs[1:]:
            assert session.get(BackgroundJob, job.id).payload == {"month": "2026-10"}
        for event in events[:2]:
            assert session.get(OutboxMessage, event.id).payload == {"factoryId": "keep"}
        assert session.get(OutboxMessage, events[2].id).payload == {}
    assert infrastructure.enqueue_job(job_type="shipment_writeback", dedupe_key="completed",
                                      payload={"month": "2026-10"}, available_at=NOW) == jobs[0].id
    assert infrastructure.enqueue_outbox(event_type="ordinary", aggregate_type="order",
                                         aggregate_id="one", dedupe_key="ordinary", payload={}
                                         ) == events[2].id


def test_import_state_and_product_cursor_are_preserved(test_database_engine: Engine) -> None:
    sessions = create_session_factory(test_database_engine)
    service = LogRetention(sessions, FakePrivateFileStore(bucket="archive"))
    with sessions.begin() as session:
        for status in ("SUCCEEDED", "FAILED", "RUNNING"):
            session.add(OrderImportRun(run_id=status, status=status, request_id=status,
                                       started_at=OLD, finished_at=OLD, created_at=OLD,
                                       idempotency_key=status, sync_result={"step": 10}))
            session.add(audit(request=status))
        for number in range(3):
            session.add(ProductSyncRun(run_id=str(number), run_type="initial", status="succeeded",
                                       started_at=OLD, finished_at=OLD + timedelta(seconds=number),
                                       worker_id="w", request_id="r", success_cursor=str(number),
                                       created_at=OLD))
        session.flush()
        session.add(OrderImportSourceCursor(source_scope="scope", successful_modified_at=OLD,
                                            successful_run_id="SUCCEEDED", successful_at=OLD))
        session.add(ProductSyncStagedVariant(run_id="0", source_i_id="i", source_sku_id="sku",
                                             name="p", source_modified_at=OLD))
    service.run(now=NOW)
    with sessions() as session:
        assert session.get(OrderImportRun, "SUCCEEDED").sync_result == {}
        for status in ("FAILED", "RUNNING"):
            assert session.get(OrderImportRun, status).sync_result == {"step": 10}
        assert set(session.scalars(select(AuditLog.request_id))) == {"FAILED", "RUNNING"}
        assert session.get(ProductSyncRun, "0") is not None
        assert session.get(ProductSyncRun, "1") is None
        assert session.get(ProductSyncRun, "2").success_cursor == "2"
        assert session.get(OrderImportSourceCursor, "scope").successful_run_id == "SUCCEEDED"


def test_commit_interruption_keeps_source_and_verified_upload(test_database_engine: Engine) -> None:
    sessions = create_session_factory(test_database_engine)
    store = FakePrivateFileStore(bucket="archive")
    service = LogRetention(sessions, store)
    with sessions.begin() as session:
        row = audit()
        session.add(row)
    service.prepare("audit_logs", row.id, NOW)

    def interrupt(session: Session) -> None:
        if any(isinstance(item, LogArchiveEntry) and item.status == "completed"
               for item in session.dirty):
            raise RuntimeError("interrupted_commit")

    event.listen(sessions, "before_commit", interrupt)
    try:
        with pytest.raises(RuntimeError, match="interrupted_commit"):
            service.finish("audit_logs", str(row.id), NOW)
    finally:
        event.remove(sessions, "before_commit", interrupt)
    with sessions() as session:
        assert session.get(AuditLog, row.id) is not None
        assert session.get(LogArchiveEntry, ("audit_logs", str(row.id))).status == "pending"
    assert store.object_count == 1
    service.run(now=NOW)
    assert store.object_count == 1


def test_expiry_failure_retries_without_touching_unexpired_archive(
    test_database_engine: Engine, monkeypatch: pytest.MonkeyPatch,
) -> None:
    sessions = create_session_factory(test_database_engine)
    store = FakePrivateFileStore(bucket="archive")
    service = LogRetention(sessions, store)
    with sessions.begin() as session:
        session.add_all([audit(created=NOW - timedelta(days=179)), audit()])
    service.run(now=NOW)
    original = store.delete

    def broken_delete(*, object_key: str) -> None:
        raise PrivateFileStoreUnavailable("delete_failed")

    monkeypatch.setattr(store, "delete", broken_delete)
    with pytest.raises(PrivateFileStoreUnavailable):
        service.run(now=NOW + timedelta(days=1))
    monkeypatch.setattr(store, "delete", original)
    assert service.run(now=NOW + timedelta(days=1))["expired"] == 1
    assert store.object_count == 1


def test_expiry_covers_each_source_and_resumed_pending_batch(test_database_engine: Engine) -> None:
    sessions = create_session_factory(test_database_engine)
    store = FakePrivateFileStore(bucket="archive")
    service = LogRetention(sessions, store)
    expired = NOW - timedelta(days=180)
    with sessions.begin() as session:
        pending = audit(created=expired)
        session.add_all([pending, audit(created=expired), BackgroundJob(
            job_type="shipment_writeback", dedupe_key="expired", status="completed",
            payload={"month": "2026-04"}, available_at=expired, created_at=expired,
        )])
    assert service.prepare("audit_logs", pending.id, NOW)
    counts = service.run(now=NOW, limit=1)
    assert counts["audit_logs"] == 2
    assert counts["background_jobs"] == 1
    assert counts["expired"] == 3
    assert store.object_count == 0
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(LogArchiveEntry)) == 0


def test_display_cutoff_count_permissions_and_redaction(
    test_database_engine: Engine, monkeypatch: pytest.MonkeyPatch,
) -> None:
    sessions = create_session_factory(test_database_engine)
    monkeypatch.setattr("app.modules.log_retention.utc_now", lambda: NOW)
    with sessions.begin() as session:
        session.add(User(user_id="admin", role="admin", is_enabled=True, feishu_display_name="A"))
        session.add_all([audit(), audit(created=NOW - timedelta(days=30)), audit(created=NOW)])
    service = NotificationsAuditService(sessions)
    page = service.list_audit_logs(actor_user_id="admin", page_size=1,
                                   created_from=NOW - timedelta(days=100))
    assert page.total == 2
    assert len(page.items) == 1
    assert page.items[0].changes == {"quantity": 23}
    with pytest.raises(PermissionError):
        service.list_audit_logs(actor_user_id="unknown")


def test_mutual_exclusion(test_database_engine: Engine) -> None:
    sessions = create_session_factory(test_database_engine)
    service = LogRetention(sessions, FakePrivateFileStore(bucket="archive"))
    with sessions() as session:
        assert session.scalar(text("SELECT GET_LOCK('log_retention', 0)")) == 1
        try:
            with pytest.raises(RuntimeError, match="busy"):
                service.run(now=NOW)
        finally:
            session.execute(text("SELECT RELEASE_LOCK('log_retention')"))


def test_wrong_bucket_cannot_discard_pending_or_expired_manifest(
    test_database_engine: Engine,
) -> None:
    sessions = create_session_factory(test_database_engine)
    service = LogRetention(sessions, FakePrivateFileStore(bucket="archive"))
    with sessions.begin() as session:
        row = audit()
        session.add(row)
    service.prepare("audit_logs", row.id, NOW)
    wrong = LogRetention(sessions, FakePrivateFileStore(bucket="wrong"))
    with pytest.raises(ValueError, match="bucket_or_prefix"):
        wrong.run(now=NOW)
    service.run(now=NOW)
    with pytest.raises(ValueError, match="bucket_or_prefix"):
        wrong.run(now=NOW + timedelta(days=180))
    with sessions() as session:
        assert session.get(LogArchiveEntry, ("audit_logs", str(row.id))) is not None


def test_inventory_uses_strict_mysql_grouping_without_exposing_content(
    test_database_engine: Engine, test_database_url: str, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    sessions = create_session_factory(test_database_engine)
    with sessions.begin() as session:
        session.add(audit())
    monkeypatch.setattr("scripts.log_archives.utc_now", lambda: NOW)
    monkeypatch.setattr("sys.argv", ["log_archives", "inventory"])
    for name, value in {"DATABASE_URL": test_database_url, "OSS_ENDPOINT": "https://example.invalid",
                        "OSS_REGION": "test", "OSS_BUCKET": "archive",
                        "OSS_ACCESS_KEY_ID": "fake", "OSS_ACCESS_KEY_SECRET": "fake"}.items():
        monkeypatch.setenv("LOG_ARCHIVE_" + name, value)
    main()
    output = capsys.readouterr().out
    row = json.loads(output)
    assert row["table"] == "audit_logs" and row["count"] == 1
    assert row["age"] == "30-180d" and row["protection"] == "eligible"
    assert row["detailBytes"] > 0
    assert "password" not in output and "quantity" not in output
