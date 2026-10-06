from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Event

import httpx
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, delete, event
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import (
    OrderAssignment,
    OrderDetail,
    OrderImportRun,
    OrderImportSourceRecord,
    OutboxMessage,
    ShipmentWritebackControl,
    ShipmentWritebackFact,
)
from app.modules.infrastructure import InfrastructureStore
from app.modules.notifications_audit import NotificationsAuditService
from app.modules.shipment_writeback.periods import month_stages
from app.modules.shipment_writeback.service import ShipmentWriteback
from app.modules.shipments.service import (
    DraftBoxInput,
    DraftItemInput,
    ReceiptItemInput,
    ShipmentReturnInput,
    ShipmentService,
)
from app.worker.runtime import Worker
from tests.api.test_shipment_api import ADMIN_ID, FACTORY_IDS, ORDER_ID, USER_IDS, _seed
from tests.unit.test_feishu_shipment_writeback import RemoteBase


def seed_source(engine: Engine) -> int:
    assignment = _seed(engine)
    now = datetime(2026, 10, 6)
    with Session(engine) as session, session.begin():
        session.add(OrderImportRun(run_id="writeback-seed", status="SUCCEEDED",
                                   started_at=now, request_id="writeback-seed"))
        session.flush()
        source = OrderImportSourceRecord(
            source_scope="test-source", source_record_id="record-a", source_detail_id="detail-a",
            order_no="S07-ORDER-A", raw_fields={}, parse_status="READY",
            first_seen_run_id="writeback-seed", last_seen_run_id="writeback-seed",
            first_seen_at=now, last_seen_at=now,
        )
        session.add(source)
        session.flush()
        session.add(OrderDetail(
            detail_id="detail-a", order_id=ORDER_ID, source_record_pk=source.source_record_pk,
            origin="feishu", sort_order=1, accepted_raw_fields={}, parse_issues=[],
            assignment_id=assignment, dispatch_state="ASSIGNED", created_at=now, updated_at=now,
        ))
        session.flush()
        session.get(OrderAssignment, assignment).detail_id = "detail-a"
    return assignment


def submit(service: ShipmentService, assignment: int, at: datetime, quantity: int = 12):
    draft, _ = service.create_or_reuse_draft(
        actor_id=USER_IDS[0], factory_id=FACTORY_IDS[0], preferred_order_id=None,
    )
    service.save_draft(
        actor_id=USER_IDS[0], factory_id=FACTORY_IDS[0], shipment_id=draft.shipment_id,
        boxes=[DraftBoxInput(box_no=1, group_key=None, items=[DraftItemInput(
            assignment_id=assignment, quantity=quantity,
        )])], note="",
    )
    return service.submit_draft(
        actor_id=USER_IDS[0], factory_id=FACTORY_IDS[0], shipment_id=draft.shipment_id,
        idempotency_key=draft.shipment_id, now=at,
    )


def test_submission_at_cutoff_enters_next_stage_without_duplicate(test_database_engine: Engine):
    assignment = seed_source(test_database_engine)
    sessions = sessionmaker(test_database_engine, expire_on_commit=False)
    shipments = ShipmentService(sessions)
    before = datetime(2026, 10, 11, 13, 59, 59, tzinfo=UTC)
    cutoff = datetime(2026, 10, 11, 14, tzinfo=UTC)
    submit(shipments, assignment, before, 12)
    submit(shipments, assignment, cutoff, 7)
    writer = ShipmentWriteback(sessions, source_scope="test-source")
    first, second, *_ = month_stages(2026, 10)
    assert writer.freeze(first, now=cutoff)["record-a"]["quantity"] == 12
    assert writer.freeze(first, now=cutoff)["record-a"]["quantity"] == 12
    assert writer.freeze(second, now=second.until)["record-a"]["quantity"] == 7


@pytest.mark.parametrize("after_cutoff", [False, True])
def test_withdraw_resubmit_preserves_cutoff_snapshot_and_root_identity(
    test_database_engine: Engine, after_cutoff: bool,
):
    assignment = seed_source(test_database_engine)
    sessions = sessionmaker(test_database_engine, expire_on_commit=False)
    shipments = ShipmentService(sessions)
    original = submit(shipments, assignment, datetime(2026, 10, 10, 8, tzinfo=UTC))
    shipments.withdraw(
        actor_id=USER_IDS[0], factory_id=FACTORY_IDS[0], shipment_id=original.shipment_id,
        reason="修改数量", expected_version=original.version, idempotency_key="withdraw",
        now=datetime(2026, 10, 11, 15 if after_cutoff else 13, tzinfo=UTC),
    )
    draft = shipments.get_withdrawal_draft(
        shipment_id=original.shipment_id, actor_id=USER_IDS[0], factory_id=FACTORY_IDS[0],
    )
    draft = shipments.save_draft(
        actor_id=USER_IDS[0], factory_id=FACTORY_IDS[0], shipment_id=draft.shipment_id,
        expected_version=draft.version, note="",
        boxes=[DraftBoxInput(box_no=1, group_key=None, items=[DraftItemInput(
            assignment_id=assignment, quantity=9,
        )])],
    )
    shipments.submit_draft(
        actor_id=USER_IDS[0], factory_id=FACTORY_IDS[0], shipment_id=draft.shipment_id,
        expected_version=draft.version, idempotency_key="resubmit",
        now=datetime(2026, 10, 12, 8, tzinfo=UTC),
    )
    writer = ShipmentWriteback(sessions, source_scope="test-source")
    first, second, *_ = month_stages(2026, 10)
    assert writer.freeze(first, now=second.until)["record-a"]["quantity"] == (
        12 if after_cutoff else 0
    )
    result = writer.freeze(second, now=second.until)
    assert result == {} if after_cutoff else result["record-a"]["quantity"] == 9


def test_history_is_rebuilt_from_formal_evidence_before_freezing(test_database_engine: Engine):
    assignment = seed_source(test_database_engine)
    sessions = sessionmaker(test_database_engine, expire_on_commit=False)
    submit(ShipmentService(sessions), assignment, datetime(2026, 10, 8, tzinfo=UTC), 13)
    # 模拟部署前尚无汇总事实的已有正式单据。
    with sessions.begin() as session:
        session.execute(delete(ShipmentWritebackFact))
    writer = ShipmentWriteback(sessions, source_scope="test-source")
    writer.prepare_history()
    stage = month_stages(2026, 10)[0]
    assert writer.freeze(stage, now=stage.until)["record-a"]["quantity"] == 13


def test_worker_schedules_only_due_work_and_recovery_does_not_duplicate_jobs(
    test_database_engine: Engine,
):
    sessions = sessionmaker(test_database_engine, expire_on_commit=False)
    remote = RemoteBase()
    writer = ShipmentWriteback(sessions, source_scope="test-source", target=remote.writer())
    first = writer.ensure_due(now=datetime(2026, 10, 6, tzinfo=UTC))
    assert len(first) == 1
    assert writer.ensure_due(now=datetime(2026, 10, 6, tzinfo=UTC)) == first
    assert len(writer.ensure_due(now=datetime(2026, 10, 11, 14, tzinfo=UTC))) == 2
    worker = Worker(
        store=InfrastructureStore(sessions), worker_id="writeback-test",
        handlers={"shipment_writeback": lambda payload: writer.run(
            payload, now=datetime(2026, 10, 12, tzinfo=UTC),
        )},
    )
    assert worker.run_once(now=datetime(2026, 10, 12, tzinfo=UTC))
    assert worker.run_once(now=datetime(2026, 10, 12, tzinfo=UTC))
    assert not worker.run_once(now=datetime(2026, 10, 12, tzinfo=UTC))
    assert [entry["status"] for entry in writer.executions()] == ["SUCCEEDED", "SUCCEEDED"]


def test_failed_write_retries_frozen_snapshot_and_records_each_attempt(
    test_database_engine: Engine,
):
    assignment = seed_source(test_database_engine)
    sessions = sessionmaker(test_database_engine, expire_on_commit=False)
    shipments = ShipmentService(sessions)
    submit(shipments, assignment, datetime(2026, 10, 8, tzinfo=UTC), 13)
    remote = RemoteBase()
    remote.fields.extend([
        {"field_id": "order", "field_name": "订单编号", "type": 1},
        {"field_id": "detail", "field_name": "下单明细ID", "type": 1005},
    ])
    writer = ShipmentWriteback(sessions, source_scope="test-source", target=remote.writer())
    payload = {"month": "2026-10", "stage": "2026-10-06"}
    remote.fail_record = True
    with pytest.raises(httpx.ReadTimeout, match="simulated lost response"):
        writer.run(payload, now=datetime(2026, 10, 11, 14, tzinfo=UTC))
    submit(shipments, assignment, datetime(2026, 10, 12, tzinfo=UTC), 7)
    writer.run(payload, now=datetime(2026, 10, 12, tzinfo=UTC))
    stage = month_stages(2026, 10)[0]
    assert remote.records["record-a"][stage.name] == 13
    assert writer.results(stage)["record-a"]["verified"] is True
    assert [entry["status"] for entry in writer.executions()] == ["FAILED", "SUCCEEDED"]
    writer.prepare_history()
    assert writer.freeze(stage, now=stage.until)["record-a"]["quantity"] == 13


def test_later_stage_cannot_claim_before_preceding_snapshot(test_database_engine: Engine):
    sessions = sessionmaker(test_database_engine, expire_on_commit=False)
    writer = ShipmentWriteback(sessions, source_scope="test-source")
    second = month_stages(2026, 10)[1]
    with pytest.raises(ValueError, match="previous_stage_not_frozen"):
        writer.freeze(second, now=second.until)


def test_historical_assignment_keeps_source_when_detail_is_redispatched(
    test_database_engine: Engine,
):
    assignment = seed_source(test_database_engine)
    sessions = sessionmaker(test_database_engine, expire_on_commit=False)
    submit(ShipmentService(sessions), assignment, datetime(2026, 10, 8, tzinfo=UTC), 13)
    with sessions.begin() as session:
        session.get(OrderDetail, "detail-a").assignment_id = None
        session.execute(delete(ShipmentWritebackFact))
    writer = ShipmentWriteback(sessions, source_scope="test-source")
    stage = month_stages(2026, 10)[0]
    assert writer.freeze(stage, now=stage.until)["record-a"]["quantity"] == 13


def test_receipt_and_return_do_not_reduce_reported_quantity(test_database_engine: Engine):
    assignment = seed_source(test_database_engine)
    sessions = sessionmaker(test_database_engine, expire_on_commit=False)
    shipments = ShipmentService(sessions)
    original = submit(shipments, assignment, datetime(2026, 10, 8, tzinfo=UTC), 100)
    receipt = shipments.get_receipt(shipment_id=original.shipment_id)
    saved = shipments.save_receipt(
        shipment_id=original.shipment_id, actor_id=ADMIN_ID, expected_version=receipt.version,
        items=[ReceiptItemInput(box_item_id=original.boxes[0].items[0].box_item_id, quantity=95)],
    )
    shipments.confirm_receipt(shipment_id=original.shipment_id, actor_id=ADMIN_ID,
                              expected_version=saved.version, idempotency_key="receipt")
    shipments.return_shipment(
        actor_id=ADMIN_ID, shipment_id=original.shipment_id,
        lines=[ShipmentReturnInput(shipment_line_id=original.lines[0].line_id, quantity=10)],
        reason="退回", idempotency_key="return",
    )
    stage = month_stages(2026, 10)[0]
    assert ShipmentWriteback(sessions, source_scope="test-source").freeze(
        stage, now=stage.until,
    )["record-a"]["quantity"] == 100


def test_missing_history_blocks_instead_of_silently_skipping(test_database_engine: Engine):
    assignment = seed_source(test_database_engine)
    sessions = sessionmaker(test_database_engine, expire_on_commit=False)
    submit(ShipmentService(sessions), assignment, datetime(2026, 10, 8, tzinfo=UTC))
    with sessions.begin() as session:
        session.execute(delete(ShipmentWritebackFact))
        session.execute(delete(OutboxMessage))
    writer = ShipmentWriteback(sessions, source_scope="test-source")
    stage = month_stages(2026, 10)[0]
    with pytest.raises(ValueError, match="history_missing"):
        writer.freeze(stage, now=stage.until)
    assert writer.results(stage) == {}


def test_freeze_waits_for_submission_transaction_and_does_not_omit_it(test_database_engine: Engine):
    assignment = seed_source(test_database_engine)
    sessions = sessionmaker(test_database_engine, expire_on_commit=False)
    entered, release, freezing = Event(), Event(), Event()

    def hold_commit(_connection, _cursor, statement, _parameters, _context, _many):
        if statement.startswith("INSERT INTO shipment_writeback_facts"):
            entered.set()
            assert release.wait(10)
        if statement.startswith("INSERT INTO shipment_writeback_control") and entered.is_set():
            freezing.set()

    event.listen(test_database_engine, "before_cursor_execute", hold_commit)
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            submitted = executor.submit(submit, ShipmentService(sessions), assignment,
                                        datetime(2026, 10, 11, 13, 59, 59, tzinfo=UTC), 17)
            assert entered.wait(10)
            stage = month_stages(2026, 10)[0]
            frozen = executor.submit(ShipmentWriteback(sessions, source_scope="test-source").freeze,
                                     stage, now=stage.until)
            try:
                assert freezing.wait(10)
                assert not frozen.done()
            finally:
                release.set()
            submitted.result(timeout=10)
            assert frozen.result(timeout=10)["record-a"]["quantity"] == 17
    finally:
        release.set()
        event.remove(test_database_engine, "before_cursor_execute", hold_commit)


def test_history_uses_business_events_and_detects_missing_withdrawal(test_database_engine: Engine):
    assignment = seed_source(test_database_engine)
    sessions = sessionmaker(test_database_engine, expire_on_commit=False)
    shipments = ShipmentService(sessions)
    original = submit(shipments, assignment, datetime(2026, 10, 8, tzinfo=UTC))
    shipments.withdraw(
        actor_id=USER_IDS[0], factory_id=FACTORY_IDS[0], shipment_id=original.shipment_id,
        reason="修改", expected_version=original.version, idempotency_key="withdraw",
        now=datetime(2026, 10, 10, tzinfo=UTC),
    )
    draft = shipments.get_withdrawal_draft(
        shipment_id=original.shipment_id, actor_id=USER_IDS[0], factory_id=FACTORY_IDS[0],
    )
    shipments.submit_draft(
        actor_id=USER_IDS[0], factory_id=FACTORY_IDS[0], shipment_id=draft.shipment_id,
        expected_version=draft.version, idempotency_key="resubmit",
        now=datetime(2026, 10, 12, tzinfo=UTC),
    )
    notifications = NotificationsAuditService(sessions)
    while notifications.consume_next_business_event(worker_id="history-test"):
        pass
    with sessions.begin() as session:
        session.execute(delete(ShipmentWritebackFact))
    writer = ShipmentWriteback(sessions, source_scope="test-source")
    writer.prepare_history()
    with sessions.begin() as session:
        session.execute(delete(ShipmentWritebackFact))
        session.execute(delete(OutboxMessage).where(
            OutboxMessage.event_type == "shipment.withdrawn",
            OutboxMessage.message_kind == "business_event",
        ))
        session.get(ShipmentWritebackControl, 1).history_ready = False
    with pytest.raises(ValueError, match="history_missing"):
        writer.prepare_history()


def test_migration_refuses_to_erase_captured_facts(
    test_database_engine: Engine, test_database_url: str,
):
    assignment = seed_source(test_database_engine)
    sessions = sessionmaker(test_database_engine, expire_on_commit=False)
    submit(ShipmentService(sessions), assignment, datetime(2026, 10, 8, tzinfo=UTC))
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", test_database_url)
    with pytest.raises(RuntimeError, match="汇总事实"):
        command.downgrade(config, "20261006_0050")
    stage = month_stages(2026, 10)[0]
    assert ShipmentWriteback(sessions, source_scope="test-source").freeze(
        stage, now=stage.until,
    )["record-a"]["quantity"] == 12
