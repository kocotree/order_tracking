from datetime import UTC, datetime, timedelta

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, select, text
from sqlalchemy.orm import sessionmaker

from app.adapters.errors import ExternalAdapterUnavailable
from app.adapters.order_source import FakeFeishuOrderSource
from app.db.models import AuditLog, BackgroundJob, Order, OrderDetail, OrderImportRun, OutboxMessage
from app.modules.order_import import OrderImportService
from app.modules.order_import.auto_sync import OrderAutoSync
from app.modules.orders.dispatch import OrderDispatchService
from tests.integration.test_order_dispatch import _row, _seed_factory_b, setup_dispatch_order
from tests.integration.test_order_import import _seed_import_dependencies


def test_upgrade_pauses_historical_withdrawals_only(
    test_database_engine: Engine, test_database_url: str,
) -> None:
    sessions, source, order_id = setup_dispatch_order(
        test_database_engine, rows=[_row(), _row("never-dispatched")]
    )
    service = OrderDispatchService(sessions, source=source)
    args = dict(actor_id="admin-order-import", order_id=order_id, request_id="migration")
    order = service.get(order_id=order_id)
    preview = service.dispatch_preview(
        **args, version=order.version, detail_ids=[order.details[0].detail_id]
    )
    order = service.dispatch_confirm(
        **args, version=order.version, preview_id=preview["preview_id"], idempotency_key="first"
    )
    service.withdraw_factory(
        **args, factory_id=order.details[0].matched_factory_id,
        version=order.version, idempotency_key="withdraw",
    )
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", test_database_url)
    command.downgrade(config, "20260924_0045")
    command.upgrade(config, "head")
    with sessions() as session:
        details = list(session.scalars(select(OrderDetail).order_by(OrderDetail.sort_order)))
        assert [row.auto_dispatch_paused for row in details] == [True, False]
    service.refresh_automatically(order_id=order_id, request_id="post-migration")
    result = service.dispatch_automatically(order_id=order_id, request_id="post-migration")
    assert result["dispatched_groups"] == 0


def complete_cycle(sync: OrderAutoSync, run_id: str) -> None:
    for _ in range(100):
        if sync.run_step({"runId": run_id}):
            return
    raise AssertionError("同步任务未完成")


def test_new_order_purchase_failure_is_isolated(test_database_engine: Engine) -> None:
    class Source(FakeFeishuOrderSource):
        def read_pages(self, *, modified_since=None, include_purchase=True):
            if include_purchase:
                raise ExternalAdapterUnavailable("jst_purchase_source_unavailable")
            yield [_row("bad", order_no="BAD"), _row("good", order_no="GOOD")]

        def read_records(self, record_ids, *, purchase_links=None):
            if "bad" in record_ids:
                raise ExternalAdapterUnavailable("jst_purchase_source_unavailable")
            return [_row("good", order_no="GOOD")]

    _seed_import_dependencies(test_database_engine)
    sessions = sessionmaker(test_database_engine, expire_on_commit=False)
    sync = OrderAutoSync(sessions, source=Source([]))
    run_id = sync.ensure_due()
    assert run_id
    complete_cycle(sync, run_id)
    with sessions() as session:
        assert list(session.scalars(select(Order.order_no))) == ["GOOD"]
        assert session.scalar(select(Order.lifecycle)) == "PUBLISHED"


def test_existing_candidate_overrides_and_exclusion_survive(test_database_engine: Engine) -> None:
    _seed_import_dependencies(test_database_engine)
    sessions = sessionmaker(test_database_engine, expire_on_commit=False)
    source = FakeFeishuOrderSource([[_row(), _row("excluded", order_no="EXCLUDED")]])
    importer = OrderImportService(sessions)
    run = importer.create_or_reuse_run(actor_id="admin-order-import", request_id="old")
    importer.process_run(run_id=run.run_id, rows=list(source.read_pages())[0], pages_read=1,
                         source_scope=source.source_scope)
    candidates, _ = importer.list_candidates(actor_id="admin-order-import")
    for candidate in candidates:
        if candidate.order_no == "EXCLUDED":
            importer.exclude_candidate(actor_id="admin-order-import",
                                       candidate_id=candidate.candidate_id, request_id="exclude")
        else:
            importer.save_candidate_fields(
                actor_id="admin-order-import", candidate_id=candidate.candidate_id,
                candidate_line_id=candidate.lines[0].candidate_line_id, version=candidate.version,
                changes={"shipped_quantity": 0, "contract_ship_date": None}, request_id="override",
            )
    sync = OrderAutoSync(sessions, source=source)
    run_id = sync.ensure_due()
    assert run_id
    complete_cycle(sync, run_id)
    with sessions() as session:
        assert list(session.scalars(select(Order.order_no))) == ["90#"]
        detail = session.scalar(select(OrderDetail))
        assert detail.shipped_override_enabled and detail.date_override_enabled
        assert detail.source_shipped_quantity == 0 and detail.contract_ship_date is None
        assert detail.dispatch_state == "UNASSIGNED"
        assert session.scalar(select(AuditLog).where(AuditLog.request_id == "override"))


def test_purchase_change_without_feishu_timestamp_change_retries_new_order(
    test_database_engine: Engine,
) -> None:
    _seed_import_dependencies(test_database_engine)
    sessions = sessionmaker(test_database_engine, expire_on_commit=False)
    now = datetime(2026, 9, 28, tzinfo=UTC)
    modified = now.replace(tzinfo=None)
    source = FakeFeishuOrderSource([[_row(shipped_quantity=95, source_modified_at=modified)]])
    sync = OrderAutoSync(sessions, source=source, clock=lambda: now)
    run_id = sync.ensure_due()
    assert run_id
    complete_cycle(sync, run_id)
    with sessions() as session:
        assert session.scalar(select(Order)) is None
    now += timedelta(minutes=20)
    source._pages = [[_row(shipped_quantity=94, source_modified_at=modified),
                      _row("full", shipped_quantity=100, source_modified_at=modified)]]
    run_id = sync.ensure_due()
    assert run_id
    complete_cycle(sync, run_id)
    with sessions() as session:
        assert session.scalar(select(Order.lifecycle)) == "PUBLISHED"
        assert len(list(session.scalars(select(OrderDetail)))) == 2
        assert sorted(session.scalars(select(OrderDetail.source_shipped_quantity))) == [94, 100]


def test_restart_after_dispatch_commit_does_not_repeat_notifications(
    test_database_engine: Engine, monkeypatch: pytest.MonkeyPatch,
) -> None:
    sessions, source, order_id = setup_dispatch_order(test_database_engine)
    sync = OrderAutoSync(sessions, source=source)
    run_id = sync.ensure_due()
    assert run_id
    while True:
        with sessions() as session:
            if session.get(OrderImportRun, run_id).sync_result["phase"] == "orders":
                break
        sync.run_step({"runId": run_id})
    original = sync._enqueue

    def crash(session, run):
        raise RuntimeError("simulated_checkpoint_failure")

    monkeypatch.setattr(sync, "_enqueue", crash)
    with pytest.raises(RuntimeError, match="simulated_checkpoint_failure"):
        sync.run_step({"runId": run_id})
    monkeypatch.setattr(sync, "_enqueue", original)
    complete_cycle(sync, run_id)
    with sessions() as session:
        assert session.get(Order, order_id).lifecycle == "PUBLISHED"
        assert len(list(session.scalars(select(OutboxMessage).where(
            OutboxMessage.event_type == "order_detail_dispatched"
        )))) == 1
        assert session.get(OrderImportRun, run_id).sync_result["dispatched_groups"] == 1


def test_partial_order_refreshes_only_unassigned_and_completed_order_is_skipped(
    test_database_engine: Engine,
) -> None:
    sessions, source, order_id = setup_dispatch_order(test_database_engine, rows=[
        _row(), _row("other", factory_name="测试工厂B", contract_ship_date=None),
    ])
    _seed_factory_b(test_database_engine)
    now = datetime(2026, 9, 28, tzinfo=UTC)
    sync = OrderAutoSync(sessions, source=source, clock=lambda: now)
    run_id = sync.ensure_due()
    assert run_id
    complete_cycle(sync, run_id)
    source._pages = [[_row(shipped_quantity=99), _row(
        "other", factory_name="测试工厂B", contract_ship_date=None, shipped_quantity=30,
    )]]
    now += timedelta(minutes=20)
    run_id = sync.ensure_due()
    assert run_id
    complete_cycle(sync, run_id)
    with sessions() as session, session.begin():
        details = list(session.scalars(select(OrderDetail).order_by(OrderDetail.sort_order)))
        assert [row.dispatch_state for row in details] == ["ASSIGNED", "UNASSIGNED"]
        assert [row.source_shipped_quantity for row in details] == [20, 30]
        session.get(Order, order_id).lifecycle = "COMPLETED"
        version = session.get(Order, order_id).version
    now += timedelta(minutes=20)
    source._pages = [[_row(), _row("other", factory_name="测试工厂B", shipped_quantity=40)]]
    run_id = sync.ensure_due()
    assert run_id
    complete_cycle(sync, run_id)
    with sessions() as session:
        assert session.get(Order, order_id).version == version
        assert list(session.scalars(select(OrderDetail.source_shipped_quantity).order_by(
            OrderDetail.sort_order
        ))) == [20, 30]


@pytest.mark.parametrize("shipped,quantity,created,assigned", [
    (94, 100, True, True), (95, 100, False, False),
    (None, 100, True, False), (0, None, True, False),
])
def test_new_order_threshold_and_unknown_quantities(
    test_database_engine: Engine, shipped: int | None, quantity: int | None,
    created: bool, assigned: bool,
) -> None:
    _seed_import_dependencies(test_database_engine)
    sessions = sessionmaker(test_database_engine, expire_on_commit=False)
    source = FakeFeishuOrderSource([[_row(shipped_quantity=shipped, order_quantity=quantity)]])
    sync = OrderAutoSync(sessions, source=source)
    run_id = sync.ensure_due()
    assert run_id
    complete_cycle(sync, run_id)
    with sessions() as session:
        order = session.scalar(select(Order))
        assert (order is not None) == created
        if created:
            assert order.created_by is None
            assert (order.lifecycle == "PUBLISHED") == assigned
            assert len(list(session.scalars(select(OrderDetail)))) == 1


def test_failed_order_keeps_values_and_other_order_dispatches(
    test_database_engine: Engine,
) -> None:
    sessions, _, order_id = setup_dispatch_order(test_database_engine)
    # 原订单来源缺失；新订单仍可在同轮正常处理。
    source = FakeFeishuOrderSource([[_row("new", order_no="NEW187")]])
    sync = OrderAutoSync(sessions, source=source)
    run_id = sync.ensure_due()
    assert run_id
    complete_cycle(sync, run_id)
    service = OrderDispatchService(sessions, source=source)
    old = service.get(order_id=order_id)
    assert old.version == 1
    assert old.details[0].dispatch_state == "UNASSIGNED"
    assert old.details[0].shipped_quantity == 20
    with sessions() as session:
        new = session.scalar(select(Order).where(Order.order_no == "NEW187"))
        assert new.lifecycle == "PUBLISHED"
        assert session.get(OrderImportRun, run_id).sync_result["failed_orders"] == 1
        failure = session.scalar(select(AuditLog).where(
            AuditLog.action == "order_sync.step", AuditLog.target_id == order_id,
        ))
        assert failure.changes["reason"] == "来源明细缺失或重复，原资料保持不变"


def test_manual_zero_and_clear_date_survive_automatic_refresh(
    test_database_engine: Engine,
) -> None:
    sessions, source, order_id = setup_dispatch_order(test_database_engine)
    service = OrderDispatchService(sessions, source=source)
    order = service.get(order_id=order_id)
    detail = order.details[0]
    service.save_fields(
        actor_id="admin-order-import", order_id=order_id, version=order.version,
        detail_id=detail.detail_id, detail_version=detail.version,
        changes={"shipped_quantity": 0, "contract_ship_date": None}, request_id="manual",
    )
    service.refresh_automatically(order_id=order_id, request_id="automatic")
    updated = service.get(order_id=order_id)
    assert updated.details[0].shipped_quantity == 0
    assert updated.details[0].contract_ship_date is None
    result = service.dispatch_automatically(order_id=order_id, request_id="dispatch")
    assert result["dispatched_groups"] == 0


def test_unchanged_source_keeps_versions_and_records_check(test_database_engine: Engine) -> None:
    sessions, source, order_id = setup_dispatch_order(test_database_engine)
    service = OrderDispatchService(sessions, source=source)
    service.refresh_automatically(order_id=order_id, request_id="first-check")
    before = service.get(order_id=order_id)
    service.refresh_automatically(order_id=order_id, request_id="same-check")
    after = service.get(order_id=order_id)
    assert after.version == before.version
    assert after.details[0].version == before.details[0].version
    with sessions() as session:
        assert session.scalar(select(AuditLog.action).where(
            AuditLog.request_id == "same-check"
        )) == "order.source_checked"


def test_long_running_step_prevents_recovery_and_overlap(test_database_engine: Engine) -> None:
    sessions = sessionmaker(test_database_engine, expire_on_commit=False)
    now = datetime(2026, 9, 28, tzinfo=UTC)
    sync = OrderAutoSync(sessions, source=FakeFeishuOrderSource([]), clock=lambda: now)
    run_id = sync.ensure_due()
    assert run_id
    with sessions() as session, session.begin():
        job = session.scalar(select(BackgroundJob))
        job.status = "running"
        job.locked_at = now.replace(tzinfo=None) - timedelta(minutes=30)
    with test_database_engine.connect() as connection:
        assert connection.scalar(text("SELECT GET_LOCK('order_tracking_auto_sync', 0)")) == 1
        try:
            assert sync.ensure_due() is None
            with sessions() as session:
                assert session.scalar(select(BackgroundJob)).status == "running"
        finally:
            connection.execute(text("SELECT RELEASE_LOCK('order_tracking_auto_sync')"))
    assert sync.ensure_due() == run_id
    with sessions() as session:
        assert session.scalar(select(BackgroundJob)).status == "pending"


def test_cycle_updates_existing_and_creates_new_orders_without_duplicates(
    test_database_engine: Engine,
) -> None:
    sessions, source, order_id = setup_dispatch_order(test_database_engine)
    sync = OrderAutoSync(sessions, source=source)
    run_id = sync.ensure_due()
    assert run_id is not None
    assert sync.ensure_due() == run_id
    for _ in range(20):
        if sync.run_step({"runId": run_id}):
            break
    else:
        raise AssertionError("同步任务未完成")
    order = OrderDispatchService(sessions, source=source).get(order_id=order_id)
    assert order.details[0].dispatch_state == "ASSIGNED"
    assert sync.ensure_due() is None


def test_automatic_dispatch_checks_entire_factory_and_uses_system_audit(
    test_database_engine: Engine,
) -> None:
    rows = [_row(), _row("bad", order_quantity=None, tracker="无效跟单"),
            _row("other", factory_name="测试工厂B")]
    sessions, source, order_id = setup_dispatch_order(test_database_engine, rows=rows)
    _seed_factory_b(test_database_engine)
    service = OrderDispatchService(sessions, source=source)
    service.refresh_automatically(order_id=order_id, request_id="auto-update")
    result = service.dispatch_automatically(order_id=order_id, request_id="auto-dispatch")
    order = service.get(order_id=order_id)
    assert [row.dispatch_state for row in order.details] == ["UNASSIGNED", "UNASSIGNED", "ASSIGNED"]
    assert result["dispatched_groups"] == 1
    service.dispatch_automatically(order_id=order_id, request_id="auto-repeat")
    with sessions() as session:
        events = list(session.scalars(select(OutboxMessage).where(
            OutboxMessage.event_type == "order_detail_dispatched"
        )))
        assert len(events) == 1
        audit = session.scalar(select(AuditLog).where(
            AuditLog.action == "order.detail_dispatched"
        ))
        assert audit.actor_id is None
        assert audit.source_terminal == "system"


def test_manual_withdrawal_pauses_auto_dispatch_until_manual_dispatch(
    test_database_engine: Engine,
) -> None:
    sessions, source, order_id = setup_dispatch_order(test_database_engine)
    service = OrderDispatchService(sessions, source=source)
    args = dict(actor_id="admin-order-import", order_id=order_id, request_id="pause")
    order = service.get(order_id=order_id)
    detail_ids = [row.detail_id for row in order.details]
    preview = service.dispatch_preview(**args, version=order.version, detail_ids=detail_ids)
    order = service.dispatch_confirm(
        **args, version=order.version, preview_id=preview["preview_id"], idempotency_key="first"
    )
    order = service.withdraw_factory(
        **args, factory_id=order.details[0].matched_factory_id,
        version=order.version, idempotency_key="withdraw",
    )
    with sessions() as session:
        detail = session.scalar(select(OrderDetail).where(OrderDetail.order_id == order_id))
        assert detail.auto_dispatch_paused is True
    preview = service.dispatch_preview(**args, version=order.version, detail_ids=detail_ids)
    service.dispatch_confirm(
        **args, version=order.version, preview_id=preview["preview_id"], idempotency_key="second"
    )
    with sessions() as session:
        detail = session.scalar(select(OrderDetail).where(OrderDetail.order_id == order_id))
        assert detail.auto_dispatch_paused is False
