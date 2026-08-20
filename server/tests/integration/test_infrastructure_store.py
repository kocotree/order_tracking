from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.modules.infrastructure import InfrastructureStore


@pytest.fixture(autouse=True)
def clean_infrastructure_tables(test_database_engine: Engine) -> None:
    with test_database_engine.begin() as connection:
        connection.execute(text("DELETE FROM audit_logs"))
        connection.execute(text("DELETE FROM outbox_messages"))
        connection.execute(text("DELETE FROM background_jobs"))
        connection.execute(text("DELETE FROM idempotency_records"))


def test_idempotency_reservation_rejects_duplicate_key(test_database_engine: Engine) -> None:
    store = InfrastructureStore(sessionmaker(test_database_engine, class_=Session))

    assert store.reserve_idempotency(scope="manual-order-fetch", key="request-001") is True
    assert store.reserve_idempotency(scope="manual-order-fetch", key="request-001") is False


def test_job_queue_claims_only_ready_work_and_recovers_stale_claim(
    test_database_engine: Engine,
) -> None:
    store = InfrastructureStore(sessionmaker(test_database_engine, class_=Session))
    now = datetime.now(UTC).replace(tzinfo=None)
    ready_id = store.enqueue_job(
        job_type="product-sync",
        dedupe_key="sync-001",
        payload={"source": "jushuitan"},
        available_at=now,
    )
    duplicate_id = store.enqueue_job(
        job_type="product-sync",
        dedupe_key="sync-001",
        payload={"source": "jushuitan"},
        available_at=now,
    )
    store.enqueue_job(
        job_type="product-sync",
        dedupe_key="sync-later",
        payload={"source": "jushuitan"},
        available_at=now + timedelta(hours=1),
    )

    assert duplicate_id == ready_id
    claimed = store.claim_next_job(worker_id="worker-a", now=now)
    assert claimed is not None
    assert claimed.id == ready_id
    assert claimed.status == "running"
    assert store.claim_next_job(worker_id="worker-a", now=now) is None

    assert store.recover_stale_jobs(before=now + timedelta(minutes=1)) == 1
    recovered = store.claim_next_job(worker_id="worker-b", now=now + timedelta(minutes=1))
    assert recovered is not None
    assert recovered.id == ready_id
    assert recovered.locked_by == "worker-b"


def test_outbox_and_audit_public_entries_are_deduplicated_and_retrievable(
    test_database_engine: Engine,
) -> None:
    store = InfrastructureStore(sessionmaker(test_database_engine, class_=Session))
    first_outbox_id = store.enqueue_outbox(
        event_type="order.published",
        aggregate_type="order",
        aggregate_id="order-001",
        dedupe_key="order-001-published-v1",
        payload={"orderId": "order-001"},
    )
    duplicate_outbox_id = store.enqueue_outbox(
        event_type="order.published",
        aggregate_type="order",
        aggregate_id="order-001",
        dedupe_key="order-001-published-v1",
        payload={"orderId": "order-001"},
    )
    store.append_audit_log(
        request_id="req-001",
        action="infrastructure.test",
        target_type="system",
        target_id="baseline",
        changes={"result": "ok"},
    )

    assert duplicate_outbox_id == first_outbox_id
    audit_entries = store.list_audit_logs(request_id="req-001")
    assert len(audit_entries) == 1
    assert audit_entries[0].action == "infrastructure.test"
    assert audit_entries[0].changes == {"result": "ok"}
