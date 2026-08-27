from datetime import UTC, datetime
from threading import Event

from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.modules.infrastructure import InfrastructureStore
from app.worker.runtime import Worker


def test_worker_processes_ready_job_and_marks_it_completed(test_database_engine: Engine) -> None:
    with test_database_engine.begin() as connection:
        connection.execute(text("DELETE FROM background_jobs"))
    store = InfrastructureStore(sessionmaker(test_database_engine, class_=Session))
    now = datetime.now(UTC).replace(tzinfo=None)
    job_id = store.enqueue_job(
        job_type="noop",
        dedupe_key="worker-001",
        payload={"value": 7},
        available_at=now,
    )
    handled: list[dict[str, int]] = []
    worker = Worker(store=store, worker_id="worker-test", handlers={"noop": handled.append})

    assert worker.run_once(now=now) is True
    assert handled == [{"value": 7}]
    assert store.get_job(job_id=job_id).status == "completed"


def test_worker_stops_without_claiming_when_stop_is_already_requested(
    test_database_engine: Engine,
) -> None:
    store = InfrastructureStore(sessionmaker(test_database_engine, class_=Session))
    stop_event = Event()
    stop_event.set()
    worker = Worker(store=store, worker_id="worker-test", handlers={})

    assert worker.run(stop_event=stop_event, poll_interval=0.01) == 0


def test_worker_runs_maintenance_and_persistent_work_sources_when_job_queue_is_empty(
    test_database_engine: Engine,
) -> None:
    store = InfrastructureStore(sessionmaker(test_database_engine, class_=Session))
    calls: list[str] = []
    worker = Worker(
        store=store,
        worker_id="worker-test",
        handlers={},
        maintenance=lambda: calls.append("maintenance"),
        work_sources=[lambda: calls.append("outbox") is None],
    )

    assert worker.run_once() is True
    assert calls == ["maintenance", "outbox"]
