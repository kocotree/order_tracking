import json
import os
import select
import signal
import subprocess
import sys
from datetime import UTC, datetime
from multiprocessing import get_context
from multiprocessing.synchronize import Event as ProcessEvent

import pytest
from sqlalchemy import Engine
from sqlalchemy import select as sql_select
from sqlalchemy.orm import Session, sessionmaker

from app.adapters.notifications import DeliveryRequest, FakeWechatNotifier
from app.db.models import OutboxMessage
from app.db.session import create_database_engine
from app.modules.infrastructure import InfrastructureStore
from app.modules.notifications_audit import NotificationsAuditService
from app.worker.runtime import Worker


def _run_job(database_url: str, job_type: str, started: ProcessEvent,
             release: ProcessEvent) -> None:
    engine = create_database_engine(database_url)
    store = InfrastructureStore(sessionmaker(engine, class_=Session))

    def handler(_payload: dict[str, object]) -> None:
        started.set()
        assert release.wait(20)

    Worker(store=store, worker_id=job_type, handlers={job_type: handler}).run_once()
    engine.dispose()


def _run_notification(database_url: str, done: ProcessEvent) -> None:
    engine = create_database_engine(database_url)
    sessions = sessionmaker(engine, class_=Session)
    store = InfrastructureStore(sessions)

    class FakeFeishu:
        def send(self, request: DeliveryRequest) -> None:
            assert request.file_id == 17
            done.set()

    def deliver() -> bool:
        return NotificationsAuditService(sessions).deliver_next(
            worker_id="notification", wechat_notifier=FakeWechatNotifier(),
            feishu_notifier=FakeFeishu(), enabled_channels={"feishu"},
        )

    Worker(store=store, worker_id="notification", handlers={},
           work_sources=[deliver]).run_once()
    engine.dispose()


@pytest.mark.parametrize("blocked_type,free_type", [
    ("order_import", "incoming_diff.recognize"),
    ("incoming_diff.recognize", None),
])
def test_blocked_role_does_not_hold_other_roles(
    test_database_engine: Engine, test_database_url: str,
    blocked_type: str, free_type: str | None,
) -> None:
    store = InfrastructureStore(sessionmaker(test_database_engine, class_=Session))
    now = datetime.now(UTC).replace(tzinfo=None)
    store.enqueue_job(job_type=blocked_type, dedupe_key=f"blocked-{blocked_type}",
                      payload={}, available_at=now)
    if free_type is not None:
        free_id = store.enqueue_job(job_type=free_type, dedupe_key="free-incoming",
                                    payload={}, available_at=now)
    with Session(test_database_engine) as session, session.begin():
        session.add(OutboxMessage(
            event_type="incoming_diff.bot_reply", aggregate_type="incoming_diff_batch",
            aggregate_id="test-batch", dedupe_key="issue206-test-reply",
            payload={"recipientOpenId": "test-open-id", "templateKey": "incoming_diff_bot",
                     "title": "来货出入", "summary": "核对表", "targetType": "incoming_diff_batch",
                     "targetId": "test-batch", "targetPath": "", "fileId": 17},
            message_kind="delivery", channel="feishu", status="pending",
            available_at=now,
        ))
    context = get_context("spawn")
    started, release, free_started, free_release, delivery_done = (
        context.Event() for _ in range(5)
    )
    blocked = context.Process(target=_run_job,
                              args=(test_database_url, blocked_type, started, release))
    free = context.Process(target=_run_job, args=(
        test_database_url, free_type, free_started, free_release,
    )) if free_type is not None else None
    notification = context.Process(target=_run_notification,
                                   args=(test_database_url, delivery_done))
    try:
        blocked.start()
        assert started.wait(15)
        if free is not None:
            free_release.set()
            free.start()
        notification.start()
        assert delivery_done.wait(15)
        notification.join(15)
        assert notification.exitcode == 0
        with Session(test_database_engine) as session:
            delivery = session.scalar(sql_select(OutboxMessage).where(
                OutboxMessage.dedupe_key == "issue206-test-reply"
            ))
            assert delivery is not None and delivery.status == "completed"
        if free is not None:
            assert free_started.wait(15)
            free.join(15)
            assert free.exitcode == 0
            assert store.get_job(job_id=free_id).status == "completed"
        assert blocked.is_alive()
    finally:
        release.set()
        blocked.join(15)
        if blocked.is_alive():
            blocked.kill()
            blocked.join()
        if free is not None and free.is_alive():
            free.kill()
            free.join()
        if notification.is_alive():
            notification.kill()
            notification.join()
    assert blocked.exitcode == 0


@pytest.mark.parametrize("crash", [False, True])
def test_supervisor_stops_and_reaps_real_children(
    test_database_engine: Engine, test_database_url: str, crash: bool,
) -> None:
    env = os.environ.copy()
    env["ORDER_TRACKING_DATABASE_URL"] = test_database_url
    process = subprocess.Popen(
        [sys.executable, "-m", "app.worker"], env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    child_pids: dict[str, int] = {}
    try:
        assert process.stdout is not None
        while len(child_pids) < 3:
            readable, _, _ = select.select([process.stdout], [], [], 20)
            assert readable, "worker children did not start"
            line = process.stdout.readline()
            assert line, "worker supervisor exited before starting children"
            event = json.loads(line)
            if event["event"] == "worker.child_started":
                child_pids[event["role"]] = event["pid"]
        assert set(child_pids) == {"sync", "incoming", "notification"}
        if crash:
            os.kill(child_pids["sync"], signal.SIGKILL)
        else:
            process.send_signal(signal.SIGTERM)
        assert process.wait(timeout=20) == (1 if crash else 0)
        for pid in child_pids.values():
            with pytest.raises(ProcessLookupError):
                os.kill(pid, 0)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        process.stdout.close()
