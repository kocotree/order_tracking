from datetime import UTC, datetime, timedelta
from multiprocessing import get_context

import httpx
import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import sessionmaker

from app.db.models import OrderImportSourceRecord
from app.modules.infrastructure import InfrastructureStore
from app.modules.shipment_writeback import service as writeback_service
from app.modules.shipment_writeback.service import ShipmentWriteback
from app.modules.shipments.service import ShipmentService
from app.settings.config import Settings
from app.worker import __main__ as entry
from app.worker.runtime import Worker
from tests.integration.test_shipment_writeback import seed_source, submit
from tests.integration.test_worker_processes import _run_job
from tests.unit.test_feishu_shipment_writeback import BASELINE, RemoteBase


@pytest.fixture
def shipment_environment(monkeypatch: pytest.MonkeyPatch):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 10, 11, 14, tzinfo=UTC).astimezone(tz)

    monkeypatch.setattr(entry, "datetime", Clock)
    monkeypatch.setattr(writeback_service, "datetime", Clock)
    remote = RemoteBase()
    http_client = httpx.Client
    requests = []

    def request(value):
        requests.append(value)
        return remote.request(value)

    def client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(request)
        return http_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "Client", client)
    settings = Settings(
        shipment_writeback_enabled=True,
        feishu_order_app_id="app", feishu_order_app_secret="secret",
        feishu_order_app_token="base", feishu_order_table_id="table",
        feishu_order_view_id="view",
        feishu_order_field_ids={"订单编号": "order", "下单明细ID": "detail"},
        shipment_writeback_total_field_id="total",
        shipment_writeback_baseline_formula=BASELINE,
    )
    return settings, remote, requests


def test_shipment_scans_and_executes_while_sync_is_blocked(
    test_database_engine: Engine, test_database_url: str, shipment_environment,
):
    settings, remote, _ = shipment_environment
    sessions = sessionmaker(test_database_engine, expire_on_commit=False)
    store = InfrastructureStore(sessions)
    now = datetime(2026, 10, 11, 14)
    queued_id = store.enqueue_job(
        job_type="shipment_writeback", dedupe_key="month:2026-10",
        payload={"month": "2026-10"}, available_at=now,
    )
    sync_handlers, _, _, _ = entry.sync_role(settings, sessions, "sync-test")
    assert not Worker(store=store, worker_id="sync-test", handlers=sync_handlers).run_once(now=now)
    assert store.get_job(job_id=queued_id).status == "pending"
    handlers, _, maintenance, _ = entry.shipment_role(settings, sessions)
    assert set(handlers) == {"shipment_writeback"}
    assert len(sync_handlers) == 6
    store.enqueue_job(job_type="order_import", dedupe_key="blocked-sync",
                      payload={}, available_at=datetime(2026, 10, 6))
    other_ids = [store.enqueue_job(job_type=kind, dedupe_key=kind, payload={}, available_at=now)
                 for kind in ("incoming_diff.recognize", "notification_due_scan")]
    context = get_context("spawn")
    started, release = context.Event(), context.Event()
    blocked = context.Process(target=_run_job,
                              args=(test_database_url, "order_import", started, release))
    try:
        blocked.start()
        assert started.wait(15)
        worker = Worker(store=store, worker_id="shipment-test", handlers=handlers,
                        maintenance=maintenance)
        assert worker.run_once(now=now)
        assert worker.run_once(now=now)
        assert not worker.run_once(now=now)
        assert store.get_job(job_id=queued_id).status == "completed"
        logs = ShipmentWriteback(sessions, source_scope="unused").executions()
        assert [(log["stage"], log["status"]) for log in logs] == [
            (None, "SUCCEEDED"), ("2026-10-06", "SUCCEEDED"),
        ]
        assert len(remote.fields) == 5
        restarted_handlers, _, restarted_scan, _ = entry.shipment_role(settings, sessions)
        assert not Worker(store=store, worker_id="shipment-restarted",
                          handlers=restarted_handlers, maintenance=restarted_scan).run_once(now=now)
        assert ShipmentWriteback(sessions, source_scope="unused").executions() == logs
        assert all(store.get_job(job_id=job_id).status == "pending" for job_id in other_ids)
        assert blocked.is_alive()
    finally:
        release.set()
        blocked.join(15)
        if blocked.is_alive():
            blocked.kill()
            blocked.join()
    assert blocked.exitcode == 0


def test_shipment_recovery_retries_original_job_and_frozen_quantity_only(
    test_database_engine: Engine, shipment_environment,
):
    settings, remote, requests = shipment_environment
    assignment = seed_source(test_database_engine)
    sessions = sessionmaker(test_database_engine, expire_on_commit=False)
    scope = entry.AppCredentialFeishuOrderSource(entry.order_config(settings)).source_scope
    with sessions.begin() as session:
        source = session.query(OrderImportSourceRecord).one()
        source.source_scope = scope
    shipments = ShipmentService(sessions)
    submit(shipments, assignment, datetime(2026, 10, 8, tzinfo=UTC), 13)
    remote.fields.extend([
        {"field_id": "order", "field_name": "订单编号", "type": 1},
        {"field_id": "detail", "field_name": "下单明细ID", "type": 1005},
    ])
    store = InfrastructureStore(sessions)
    now = datetime(2026, 10, 11, 14)
    writer = ShipmentWriteback(sessions, source_scope=scope)
    month_id, stage_id = writer.ensure_due(now=now.replace(tzinfo=UTC))
    handlers, _, maintenance, _ = entry.shipment_role(settings, sessions)
    worker = Worker(store=store, worker_id="shipment", handlers=handlers,
                    maintenance=maintenance, retry_limits={"shipment_writeback": 3})
    assert worker.run_once(now=now)
    remote.fail_record = True
    assert worker.run_once(now=now)
    assert store.get_job(job_id=month_id).status == "completed"
    assert store.get_job(job_id=stage_id).status == "pending"
    assert not worker.run_once(now=now + timedelta(seconds=29))
    submit(shipments, assignment, datetime(2026, 10, 12, tzinfo=UTC), 7)

    other_ids = []
    for role, kind in (("sync", "order_import"), ("incoming", "incoming_diff.recognize"),
                       ("notification", "notification_due_scan")):
        job_id = store.enqueue_job(job_type=kind, dedupe_key=role, payload={}, available_at=now)
        assert store.claim_next_job(worker_id=role, now=now, job_types=entry.ROLE_JOB_TYPES[role])
        other_ids.append(job_id)
    interrupted = store.claim_next_job(worker_id="old-sync", now=now + timedelta(seconds=30),
                                       job_types=("shipment_writeback",))
    assert interrupted is not None and interrupted.id == stage_id
    assert store.recover_stale_jobs(before=now + timedelta(minutes=6),
                                    job_types=entry.ROLE_JOB_TYPES["sync"]) == 1
    assert store.get_job(job_id=stage_id).status == "running"
    assert store.recover_stale_jobs(before=now + timedelta(minutes=6),
                                    job_types=entry.ROLE_JOB_TYPES["shipment"]) == 1
    assert [store.get_job(job_id=i).status for i in other_ids] == ["pending", "running", "running"]
    restarted_handlers, _, restarted_scan, _ = entry.shipment_role(settings, sessions)
    restarted = Worker(store=store, worker_id="shipment-restarted", handlers=restarted_handlers,
                       maintenance=restarted_scan, retry_limits={"shipment_writeback": 3})
    assert restarted.run_once(now=now + timedelta(minutes=7))
    assert not restarted.run_once(now=now + timedelta(minutes=7))
    job = store.get_job(job_id=stage_id)
    assert job.status == "completed" and job.attempts == 3
    assert remote.records["record-a"]["26.10.06-10.11出货"] == 13
    assert len([r for r in requests if r.method == "PUT" and "/records/" in r.url.path]) == 1
    assert [(log["job_id"], log["status"]) for log in writer.executions()] == [
        (month_id, "SUCCEEDED"), (stage_id, "FAILED"), (stage_id, "SUCCEEDED"),
    ]


def test_disabled_shipment_does_not_schedule_or_write_existing_jobs(
    test_database_engine: Engine, shipment_environment,
):
    settings, remote, requests = shipment_environment
    settings.shipment_writeback_enabled = False
    sessions = sessionmaker(test_database_engine, expire_on_commit=False)
    store = InfrastructureStore(sessions)
    handlers, _, maintenance, _ = entry.shipment_role(settings, sessions)
    worker = Worker(store=store, worker_id="shipment-disabled", handlers=handlers,
                    maintenance=maintenance)
    assert not worker.run_once()
    job_id = store.enqueue_job(job_type="shipment_writeback", dedupe_key="month:2026-10",
                               payload={"month": "2026-10"}, available_at=datetime(2026, 10, 6))
    assert worker.run_once()
    assert store.get_job(job_id=job_id).status == "failed"
    logs = ShipmentWriteback(sessions, source_scope="unused").executions()
    assert len(logs) == 1
    assert logs[0]["error"] == "shipment_writeback_target_not_configured"
    assert len(remote.fields) == 2
    assert remote.fields[1]["property"]["formula_expression"] == BASELINE
    assert requests == []


def test_sync_maintenance_does_not_schedule_shipment(
    test_database_engine: Engine, shipment_environment,
):
    settings, _, _ = shipment_environment
    sessions = sessionmaker(test_database_engine, expire_on_commit=False)
    store = InfrastructureStore(sessions)
    _, _, maintenance, _ = entry.sync_role(settings, sessions, "sync-test")
    assert maintenance is not None
    maintenance()
    assert store.claim_next_job(worker_id="shipment", now=datetime(2026, 10, 12),
                                job_types=("shipment_writeback",)) is None
    assert store.claim_next_job(worker_id="sync", now=datetime(2026, 10, 12),
                                job_types=("order_auto_sync",)) is not None
