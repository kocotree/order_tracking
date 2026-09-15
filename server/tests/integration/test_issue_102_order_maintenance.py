from dataclasses import replace
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.adapters.order_source import FakeFeishuOrderSource
from app.db.models import AuditLog, Notification, OrderDetail, User
from app.modules.notifications_audit import NotificationsAuditService
from app.modules.order_import import OrderImportService
from app.modules.orders import OrderService
from app.modules.orders.dispatch import OrderDispatchService
from app.modules.orders.source_update import OrderSourceUpdateService
from tests.integration.test_order_dispatch import _row, _seed_factory_b, setup_dispatch_order
from tests.integration.test_order_import import _seed_import_dependencies
from tests.integration.test_order_source_update import setup_order


def test_candidate_field_overrides_survive_refresh_and_import(test_database_engine: Engine) -> None:
    _seed_import_dependencies(test_database_engine)
    _seed_factory_b(test_database_engine)
    sessions = sessionmaker(test_database_engine, expire_on_commit=False)
    service = OrderImportService(sessions)
    row = _row(record_id="candidate-102")
    source = FakeFeishuOrderSource([[row]])
    run = service.create_or_reuse_run(actor_id="admin-order-import", request_id="seed-102")
    service.process_run(
        run_id=run.run_id, rows=[row], pages_read=1, source_scope=source.source_scope
    )
    candidate = service.list_candidates(actor_id="admin-order-import")[0][0]
    saved = service.save_candidate_fields(
        actor_id="admin-order-import",
        candidate_id=candidate.candidate_id,
        candidate_line_id=candidate.lines[0].candidate_line_id,
        version=candidate.version,
        changes={
            "factory_id": "factory-b",
            "contract_ship_date": date(2026, 12, 20),
            "shipped_quantity": 30,
        },
        request_id="save-102",
    )
    assert (saved.lines[0].factory_name, saved.lines[0].shipped_quantity) == ("测试工厂B", 30)

    run = service.create_or_reuse_run(actor_id="admin-order-import", request_id="refresh-102")
    service.process_run(
        run_id=run.run_id,
        rows=[replace(row, shipped_quantity=90)],
        pages_read=1,
        source_scope=source.source_scope,
    )
    refreshed = service.get_candidate(
        actor_id="admin-order-import", candidate_id=candidate.candidate_id
    )
    assert (
        refreshed.lines[0].factory_name,
        refreshed.lines[0].contract_ship_date,
        refreshed.lines[0].shipped_quantity,
    ) == ("测试工厂B", date(2026, 12, 20), 30)

    order_id = service.confirm_candidate(
        actor_id="admin-order-import",
        candidate_id=candidate.candidate_id,
        version=refreshed.version,
        request_id="import-102",
    )
    with sessions() as session:
        detail = session.scalar(select(OrderDetail).where(OrderDetail.order_id == order_id))
        assert detail is not None
        assert detail.factory_override_enabled and detail.shipped_override_enabled
        assert detail.date_override_enabled
        assert (detail.factory_name, detail.source_shipped_quantity) == ("测试工厂B", 30)
    logs = OrderService(sessions).list_audit_logs(
        actor_id="admin-order-import", order_id=order_id
    )
    assert sum(log.action == "order_import.detail_updated" for log in logs) == 1


def test_candidate_batch_save_is_atomic(test_database_engine: Engine) -> None:
    _seed_import_dependencies(test_database_engine)
    _seed_factory_b(test_database_engine)
    sessions = sessionmaker(test_database_engine, expire_on_commit=False)
    service = OrderImportService(sessions)
    rows = [_row(record_id="batch-a"), _row(record_id="batch-b")]
    run = service.create_or_reuse_run(actor_id="admin-order-import", request_id="batch-seed")
    service.process_run(run_id=run.run_id, rows=rows, pages_read=1, source_scope="batch")
    candidate = service.list_candidates(actor_id="admin-order-import")[0][0]
    line_ids = [line.candidate_line_id for line in candidate.lines]

    with pytest.raises(ValueError, match="factory is unavailable"):
        service.save_candidate_lines(
            actor_id="admin-order-import", candidate_id=candidate.candidate_id,
            version=candidate.version, request_id="batch-invalid",
            updates=[
                (line_ids[0], {"shipped_quantity": 30}),
                (line_ids[1], {"factory_id": "missing"}),
            ],
        )
    unchanged = service.get_candidate(
        actor_id="admin-order-import", candidate_id=candidate.candidate_id
    )
    assert [line.shipped_quantity for line in unchanged.lines] == [20, 20]

    saved = service.save_candidate_lines(
        actor_id="admin-order-import", candidate_id=candidate.candidate_id,
        version=candidate.version, request_id="batch-valid",
        updates=[
            (line_ids[0], {"shipped_quantity": 30}),
            (line_ids[1], {"factory_id": "factory-b", "shipped_quantity": 40}),
        ],
    )
    assert [line.shipped_quantity for line in saved.lines] == [30, 40]
    with sessions() as session:
        logs = session.scalars(
            select(AuditLog).where(AuditLog.request_id == "batch-valid")
        ).all()
    assert len(logs) == 1


def test_unassigned_order_fields_are_protected_without_duplicate_audit(
    test_database_engine: Engine,
) -> None:
    sessions, row, source, order_id = setup_order(test_database_engine)
    _seed_factory_b(test_database_engine)
    service = OrderSourceUpdateService(sessions, source=source)
    order = service.get(order_id=order_id)
    detail = order.details[0]
    saved = service.save_fields(
        actor_id="admin-order-import",
        order_id=order_id,
        version=order.version,
        detail_id=detail.detail_id,
        detail_version=detail.version,
        changes={
            "factory_id": "factory-b",
            "contract_ship_date": date(2026, 12, 20),
            "shipped_quantity": 30,
        },
        request_id="save-order-102",
    )
    unchanged = service.save_fields(
        actor_id="admin-order-import",
        order_id=order_id,
        version=saved.version,
        detail_id=detail.detail_id,
        detail_version=saved.details[0].version,
        changes={
            "factory_id": "factory-b",
            "contract_ship_date": date(2026, 12, 20),
            "shipped_quantity": 30,
        },
        request_id="same-order-102",
    )
    assert unchanged.version == saved.version

    source._pages = [[replace(row, factory_name="测试工厂", shipped_quantity=90)]]
    preview = service.preview(
        actor_id="admin-order-import",
        order_id=order_id,
        version=saved.version,
        request_id="preview-order-102",
    )
    refreshed = service.confirm(
        actor_id="admin-order-import",
        order_id=order_id,
        version=saved.version,
        preview_id=preview["preview_id"],
        idempotency_key="refresh-order-102",
        request_id="refresh-order-102",
    )
    assert (
        refreshed.details[0].factory_name,
        refreshed.details[0].contract_ship_date,
        refreshed.details[0].shipped_quantity,
    ) == ("测试工厂B", date(2026, 12, 20), 30)
    with Session(test_database_engine) as session:
        assert len(
            session.scalars(
                select(AuditLog).where(AuditLog.action == "order.detail_updated")
            ).all()
        ) == 1


def test_unassigned_order_batch_save_is_atomic(test_database_engine: Engine) -> None:
    sessions, _, source, order_id = setup_order(test_database_engine, two_rows=True)
    _seed_factory_b(test_database_engine)
    service = OrderSourceUpdateService(sessions, source=source)
    order = service.get(order_id=order_id)
    first, second = order.details

    with pytest.raises(ValueError, match="工厂不存在或已停用"):
        service.save_fields_batch(
            actor_id="admin-order-import", order_id=order_id, version=order.version,
            request_id="batch-order-invalid",
            updates=[
                (first.detail_id, first.version, {"shipped_quantity": 30}),
                (second.detail_id, second.version, {"factory_id": "missing"}),
            ],
        )
    unchanged = service.get(order_id=order_id)
    assert [detail.shipped_quantity for detail in unchanged.details] == [0, 0]

    saved = service.save_fields_batch(
        actor_id="admin-order-import", order_id=order_id, version=order.version,
        request_id="batch-order-valid",
        updates=[
            (first.detail_id, first.version, {"shipped_quantity": 30}),
            (second.detail_id, second.version, {
                "factory_id": "factory-b", "contract_ship_date": date(2026, 12, 20),
            }),
        ],
    )
    assert [detail.shipped_quantity for detail in saved.details] == [30, 0]
    assert saved.details[1].factory_name == "测试工厂B"
    with sessions() as session:
        logs = session.scalars(
            select(AuditLog).where(AuditLog.request_id == "batch-order-valid")
        ).all()
    assert len(logs) == 1


def test_three_trackers_filter_and_dispatch_as_one_order(test_database_engine: Engine) -> None:
    rows = [
        replace(_row("tracker-a"), trackers=("松子", "青椒")),
        replace(_row("tracker-b"), tracker="烧麦", trackers=("烧麦", "松子")),
    ]
    sessions, source, order_id = setup_dispatch_order(test_database_engine, rows=rows)
    order_service = OrderService(sessions)
    matched, total = order_service.list_visible(
        actor_id="admin-order-import",
        include_drafts=True,
        trackers=["青椒"],
        page=1,
        page_size=10,
    )
    assert total == 1 and matched[0].trackers == ["松子", "青椒", "烧麦"]

    dispatch = OrderDispatchService(sessions, source=source)
    order = dispatch.get(order_id=order_id)
    preview = dispatch.dispatch_preview(
        actor_id="admin-order-import",
        order_id=order_id,
        version=order.version,
        detail_ids=[detail.detail_id for detail in order.details],
        request_id="dispatch-trackers-102",
    )
    assert preview["all_ok"]
    result = dispatch.dispatch_confirm(
        actor_id="admin-order-import",
        order_id=order_id,
        version=order.version,
        preview_id=preview["preview_id"],
        idempotency_key="dispatch-trackers-102",
        request_id="dispatch-trackers-102",
    )
    assert result.trackers == ["松子", "青椒", "烧麦"]

    with sessions() as session, session.begin():
        session.add_all([
            User(user_id="admin-green-102", role="admin", is_enabled=True,
                 feishu_display_name="青椒"),
            User(user_id="admin-shaomai-102", role="admin", is_enabled=True,
                 feishu_display_name="烧麦"),
        ])
    NotificationsAuditService(sessions).scan_due_reminders(
        business_date=date(2026, 12, 17),
        now=datetime(2026, 12, 17, tzinfo=UTC),
    )
    with sessions() as session:
        recipients = set(session.scalars(
            select(Notification.recipient_id).where(
                Notification.event_type == "order.due_reminder"
            )
        ))
    assert {"admin-order-import", "admin-green-102", "admin-shaomai-102"} <= recipients
