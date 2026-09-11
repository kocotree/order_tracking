"""Issue #90 detail dispatch integration tests."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.adapters.order_source import FakeFeishuOrderSource
from app.db.models import (
    AuditLog,
    Factory,
    Notification,
    Order,
    OrderAssignment,
    OrderChangePreview,
    OrderDetail,
    OutboxMessage,
    User,
)
from app.modules.notifications_audit import NotificationsAuditService
from app.modules.order_import import OrderImportService, SourceOrderRow
from app.modules.orders import OrderConflict, OrderNotFound, OrderValidationError
from app.modules.orders.dispatch import OrderDispatchService
from tests.integration.test_order_import import _seed_import_dependencies


def _row(record_id: str = "rec90", **kw: object) -> SourceOrderRow:
    base = SourceOrderRow(
        record_id,
        "90#",
        "6970000000001",
        "测试童帽",
        "蓝色 / 120",
        "童帽春夏",
        "测试工厂",
        100,
        20,
        80,
        "松子",
        None,
        date(2026, 12, 31),
        {"下单数": 100, "出货总数": 20},
    )
    return replace(base, **kw) if kw else base


def _seed_factory_b(engine: Engine) -> None:
    """Seed a second factory (测试工厂B) for cross-factory tests."""
    with Session(engine) as session, session.begin():
        fb = Factory(
            factory_id="factory-b",
            supplier_number="FB",
            factory_name="测试工厂B",
            factory_code="FB",
            is_enabled=True,
        )
        session.add(fb)
        session.flush()
        session.add(
            User(
                user_id="factory-b-user",
                role="factory",
                is_enabled=True,
                feishu_display_name="测试工厂B用户",
                factory_id=fb.factory_id,
                factory_position="owner",
            )
        )


def setup_dispatch_order(engine: Engine, *, rows: list[SourceOrderRow] | None = None) -> tuple:
    """Seed deps + import rows via the existing #88/#89 import pipeline."""
    _seed_import_dependencies(engine)
    rows = rows or [_row()]
    source = FakeFeishuOrderSource([rows])
    sessions = sessionmaker(engine, expire_on_commit=False)
    importer = OrderImportService(sessions)
    run = importer.create_or_reuse_run(actor_id="admin-order-import", request_id="seed90")
    importer.process_run(
        run_id=run.run_id,
        pages_read=1,
        rows=rows,
        source_scope=source.source_scope,
    )
    candidates, _ = importer.list_candidates(actor_id="admin-order-import")
    order_id = importer.confirm_candidate(
        actor_id="admin-order-import",
        candidate_id=candidates[0].candidate_id,
        request_id="import90",
    )
    return sessions, source, order_id


def test_dispatch_reports_execution_quantities_without_double_counting(
    test_database_engine: Engine,
):
    """Dispatch response shipped = initial baseline 20 (not 20+20=40)."""
    sessions, source, order_id = setup_dispatch_order(test_database_engine)
    now = datetime(2026, 9, 11, tzinfo=UTC)
    service = OrderDispatchService(sessions, source=source, clock=lambda: now)
    args = dict(actor_id="admin-order-import", order_id=order_id, request_id="t90")
    order = service.get(order_id=order_id)
    detail = order.details[0]
    assert detail.shipped_quantity == 20  # imported value

    preview = service.dispatch_preview(**args, version=order.version, detail_ids=[detail.detail_id])
    assert preview["requires_source_confirmation"] is False
    assert preview["all_ok"] is True

    result = service.dispatch_confirm(
        **args,
        version=order.version,
        preview_id=preview["preview_id"],
        idempotency_key="fix2",
    )
    d = result.details[0]
    assert d.shipped_quantity == 20, f"expected 20, got {d.shipped_quantity} — double-count bug"
    assert d.pending_quantity == 80
    assert d.dispatch_state == "ASSIGNED"

    # Reload via get(): same numbers
    reloaded = service.get(order_id=order_id)
    assert reloaded.details[0].shipped_quantity == 20
    assert reloaded.details[0].pending_quantity == 80
    assert reloaded.lifecycle == "PUBLISHED"
    assert reloaded.tracker == "松子"

    with Session(test_database_engine) as session:
        assignment = session.scalar(select(OrderAssignment))
        assert assignment is not None
        assert assignment.initial_shipped_quantity == 20
        assert assignment.assigned_quantity == 100
        assert assignment.is_active is True
        audit = session.scalar(select(AuditLog).where(AuditLog.action == "order.detail_dispatched"))
        assert audit is not None
        source_preview_id = audit.changes["sourcePreviewId"]
        source_preview = session.get(OrderChangePreview, source_preview_id)
        assert source_preview is not None
        assert source_preview.payload["updates"][detail.detail_id]["accepted_source_hash"]


def test_dispatch_api_enforces_web_auth_csrf_and_server_owned_fields(
    test_database_engine: Engine,
    test_database_url: str,
):
    from fastapi.testclient import TestClient

    from app.main import create_app
    from app.modules.identity_access import IdentityAccessService

    sessions, source, order_id = setup_dispatch_order(test_database_engine)
    identity = IdentityAccessService(sessions, token_secret=b"issue90")
    admin = identity.issue_session(user_id="admin-order-import", terminal="web")
    app = create_app(
        database_url=test_database_url,
        identity_service=identity,
        order_source=source,
    )
    order = OrderDispatchService(sessions, source=source).get(order_id=order_id)
    detail_id = order.details[0].detail_id
    preview_url = f"/api/v1/admin/orders/{order_id}/dispatch/preview"
    preview_body = {"version": order.version, "detailIds": [detail_id]}

    with TestClient(app, base_url="https://testserver") as client:
        assert client.post(preview_url, json=preview_body).status_code == 401
        client.cookies.set("ot_web_session", admin.access_token)
        assert client.post(preview_url, json=preview_body).status_code == 403
        headers = {"X-CSRF-Token": admin.csrf_token}
        assert (
            client.post(
                preview_url,
                json={**preview_body, "factoryId": "forged"},
                headers=headers,
            ).status_code
            == 422
        )
        preview_response = client.post(preview_url, json=preview_body, headers=headers)
        assert preview_response.status_code == 200, preview_response.text
        preview = preview_response.json()
        assert preview["allOk"] is True

        confirm_url = f"/api/v1/admin/orders/{order_id}/dispatch/confirm"
        confirm_body = {"version": order.version, "previewId": preview["previewId"]}
        assert client.post(confirm_url, json=confirm_body, headers=headers).status_code == 422
        confirmed = client.post(
            confirm_url,
            json=confirm_body,
            headers={**headers, "Idempotency-Key": "api-dispatch"},
        )
        assert confirmed.status_code == 200, confirmed.text
        assert confirmed.json()["lifecycle"] == "PUBLISHED"


def test_source_change_requires_independent_confirm_before_dispatch(
    test_database_engine: Engine,
):
    sessions, source, order_id = setup_dispatch_order(test_database_engine)
    service = OrderDispatchService(sessions, source=source)
    args = dict(actor_id="admin-order-import", order_id=order_id, request_id="t90")
    order = service.get(order_id=order_id)
    detail_id = order.details[0].detail_id

    # Fake source now reports shipped 20→25
    source._pages = [
        [
            replace(
                source._pages[0][0],
                shipped_quantity=25,
                raw_fields={"下单数": 100, "出货总数": 25},
            ),
        ]
    ]

    # dispatch_preview detects the difference
    preview = service.dispatch_preview(**args, version=order.version, detail_ids=[detail_id])
    assert preview["requires_source_confirmation"] is True
    assert preview["preview_id"] is None
    assert len(preview["source_preview"]["differences"]) > 0
    assert any(d["field"] == "已发数量" for d in preview["source_preview"]["differences"])

    # Confirm the source update independently via the #89 endpoint.
    source_saved = service.confirm(
        actor_id="admin-order-import",
        order_id=order_id,
        version=order.version,
        preview_id=preview["source_preview"]["preview_id"],
        idempotency_key="src90",
        request_id="confirm-src",
    )
    assert source_saved.details[0].shipped_quantity == 25
    # Cancelling dispatch (= not calling dispatch_confirm) does not undo the update.
    # The next step proves it: we proceed with dispatch.

    # Re-run dispatch preview with the new order version.
    source._pages = [
        [
            replace(
                source._pages[0][0],
                shipped_quantity=25,
                raw_fields={"下单数": 100, "出货总数": 25},
            )
        ]
    ]  # source still says 25 → no difference
    preview2 = service.dispatch_preview(
        **args,
        version=source_saved.version,
        detail_ids=[detail_id],
    )
    assert preview2["requires_source_confirmation"] is False
    assert preview2["all_ok"] is True

    result = service.dispatch_confirm(
        **args,
        version=source_saved.version,
        preview_id=preview2["preview_id"],
        idempotency_key="disp90",
    )
    assert result.details[0].shipped_quantity == 25
    assert result.details[0].pending_quantity == 75

    # Assignment initial baseline is 25
    with Session(test_database_engine) as session:
        a = session.scalar(select(OrderAssignment))
        assert a.initial_shipped_quantity == 25
        assert a.assigned_quantity == 100


def test_deactivated_account_blocks_dispatch_at_confirm_time(
    test_database_engine: Engine,
):
    sessions, source, order_id = setup_dispatch_order(test_database_engine)
    service = OrderDispatchService(sessions, source=source)
    args = dict(actor_id="admin-order-import", order_id=order_id, request_id="t90")
    order = service.get(order_id=order_id)
    detail_id = order.details[0].detail_id

    preview = service.dispatch_preview(**args, version=order.version, detail_ids=[detail_id])
    assert preview["all_ok"] is True

    # Disable the factory user BETWEEN preview and confirm.
    with Session(test_database_engine) as session:
        user = session.get(User, "factory-import-user")
        user.is_enabled = False
        session.commit()

    with pytest.raises(OrderValidationError, match="工厂无审核通过"):
        service.dispatch_confirm(
            **args,
            version=order.version,
            preview_id=preview["preview_id"],
            idempotency_key="deact",
        )

    # Zero business writes.
    with Session(test_database_engine) as session:
        assert session.query(OrderAssignment).count() == 0
        assert session.query(OutboxMessage).count() == 0
        detail = session.scalar(select(OrderDetail).where(OrderDetail.detail_id == detail_id))
        assert detail.dispatch_state == "UNASSIGNED"
        assert session.get(OrderChangePreview, preview["preview_id"]).consumed_at is None
        assert session.get(Order, order_id).lifecycle == "DRAFT"


def test_invalid_row_blocks_whole_batch_cleanly(test_database_engine: Engine):
    sessions, source, order_id = setup_dispatch_order(test_database_engine)
    service = OrderDispatchService(sessions, source=source)
    args = dict(actor_id="admin-order-import", order_id=order_id, request_id="t90")
    order = service.get(order_id=order_id)
    detail_id = order.details[0].detail_id

    # Clear the contract_ship_date => detail gets validated as "缺合同出货时间".
    # But the SOURCE still has the date → that's a source difference!
    # Instead: make the date null directly in DB AND turn on date_override_enabled
    # so the source-comparison loop skips the date field.
    with Session(test_database_engine) as session:
        detail = session.scalar(select(OrderDetail).where(OrderDetail.detail_id == detail_id))
        detail.contract_ship_date = None
        detail.date_override_enabled = True  # tells source comparison to skip date
        session.commit()
    order = service.get(order_id=order_id)
    assert order.details[0].contract_ship_date is None

    preview = service.dispatch_preview(**args, version=order.version, detail_ids=[detail_id])
    assert preview["source_preview"] is None  # no source differences
    assert preview["all_ok"] is False
    assert not preview["validations"][0]["passes"]
    assert any("缺合同出货时间" in issue for issue in preview["validations"][0]["issues"])

    with pytest.raises(OrderValidationError, match="缺合同出货时间"):
        service.dispatch_confirm(
            **args,
            version=order.version,
            preview_id=preview["preview_id"],
            idempotency_key="invalid",
        )

    with Session(test_database_engine) as session:
        assert session.query(OrderAssignment).count() == 0
        assert session.query(OutboxMessage).count() == 0
        detail = session.scalar(select(OrderDetail).where(OrderDetail.detail_id == detail_id))
        assert detail.dispatch_state == "UNASSIGNED"


def test_over_shipment_dispatches_with_zero_pending(test_database_engine: Engine):
    rows = [
        _row("rec-a", order_quantity=100, shipped_quantity=0),  # 0% → pull order
        _row("rec-b", order_quantity=900, shipped_quantity=915),  # already over-shipped
    ]
    sessions, source, order_id = setup_dispatch_order(test_database_engine, rows=rows)
    service = OrderDispatchService(sessions, source=source)
    args = dict(actor_id="admin-order-import", order_id=order_id, request_id="t90")
    order = service.get(order_id=order_id)
    assert len(order.details) == 2
    rec_b = next(d for d in order.details if d.order_quantity == 900)
    assert rec_b.shipped_quantity == 915

    # dispatch both
    detail_ids = [d.detail_id for d in order.details]
    preview = service.dispatch_preview(**args, version=order.version, detail_ids=detail_ids)
    assert preview["all_ok"] is True
    result = service.dispatch_confirm(
        **args,
        version=order.version,
        preview_id=preview["preview_id"],
        idempotency_key="over",
    )
    b = next(d for d in result.details if d.order_quantity == 900)
    assert b.pending_quantity == 0
    assert b.progress_percent is not None and b.progress_percent > 100

    # The over-shipped assignment must NOT enter the shipment catalog
    from app.modules.shipments import ShipmentService

    sessions_local = sessionmaker(test_database_engine, expire_on_commit=False)
    catalog = ShipmentService(sessions_local).list_catalog(factory_id="factory-import")
    catalog_qty = {c.assigned_quantity: c.pending_quantity for c in catalog}
    assert 900 not in catalog_qty
    assert 100 in catalog_qty
    assert catalog_qty[100] > 0


def test_inactive_assignment_is_hidden_from_factory_order_and_shipment_views(
    test_database_engine: Engine,
):
    sessions, source, order_id = setup_dispatch_order(test_database_engine)
    service = OrderDispatchService(sessions, source=source)
    order = service.get(order_id=order_id)
    preview = service.dispatch_preview(
        actor_id="admin-order-import",
        order_id=order_id,
        request_id="inactive-preview",
        version=order.version,
        detail_ids=[order.details[0].detail_id],
    )
    service.dispatch_confirm(
        actor_id="admin-order-import",
        order_id=order_id,
        request_id="inactive-confirm",
        version=order.version,
        preview_id=preview["preview_id"],
        idempotency_key="inactive",
    )

    assert (
        service.get_visible(actor_id="factory-import-user", order_id=order_id).order_id == order_id
    )
    with Session(test_database_engine) as session:
        assignment = session.scalar(select(OrderAssignment))
        assert assignment is not None
        assignment.is_active = False
        session.commit()

    with pytest.raises(OrderNotFound):
        service.get_visible(actor_id="factory-import-user", order_id=order_id)
    assert service.list_visible(actor_id="factory-import-user") == ([], 0)

    from app.modules.shipments import ShipmentService

    assert ShipmentService(sessions).list_catalog(factory_id="factory-import") == []


def test_same_sku_factory_details_dispatch_independently(test_database_engine: Engine):
    rows = [_row("rec-a"), _row("rec-b")]
    sessions, source, order_id = setup_dispatch_order(test_database_engine, rows=rows)
    service = OrderDispatchService(sessions, source=source)
    args = dict(actor_id="admin-order-import", order_id=order_id, request_id="t90")
    order = service.get(order_id=order_id)
    a_id, b_id = [d.detail_id for d in order.details]
    initial_version = order.version

    # Dispatch detail A only.
    preview = service.dispatch_preview(**args, version=order.version, detail_ids=[a_id])
    assert preview["all_ok"] is True
    service.dispatch_confirm(
        **args,
        version=order.version,
        preview_id=preview["preview_id"],
        idempotency_key="first",
    )

    # Dispatch detail B separately (previously blocked by unique constraint).
    order = service.get(order_id=order_id)
    preview = service.dispatch_preview(**args, version=order.version, detail_ids=[b_id])
    assert preview["all_ok"] is True
    service.dispatch_confirm(
        **args,
        version=order.version,
        preview_id=preview["preview_id"],
        idempotency_key="second",
    )

    with Session(test_database_engine) as session:
        assignments = session.scalars(select(OrderAssignment)).all()
        assert len(assignments) == 2
        assert len({a.order_line_id for a in assignments}) == 1  # same line
        assert {a.detail_id for a in assignments} == {a_id, b_id}
        for a in assignments:
            assert a.is_active is True
            assert a.initial_shipped_quantity == 20
        order_row = session.get(Order, order_id)
        assert order_row.version == initial_version + 2


def test_dispatch_idempotency_same_key_reuses_result(test_database_engine: Engine):
    sessions, source, order_id = setup_dispatch_order(test_database_engine)
    service = OrderDispatchService(sessions, source=source)
    args = dict(actor_id="admin-order-import", order_id=order_id, request_id="t90")
    order = service.get(order_id=order_id)
    detail_id = order.details[0].detail_id
    preview = service.dispatch_preview(**args, version=order.version, detail_ids=[detail_id])
    other_preview = service.dispatch_preview(**args, version=order.version, detail_ids=[detail_id])
    result = service.dispatch_confirm(
        **args,
        version=order.version,
        preview_id=preview["preview_id"],
        idempotency_key="idem",
    )
    # Re-run with the same key → returns identical result, no duplicate.
    retry = service.dispatch_confirm(
        **args,
        version=order.version,
        preview_id=preview["preview_id"],
        idempotency_key="idem",
    )
    assert retry == result
    with Session(test_database_engine) as session:
        assert session.query(OrderAssignment).count() == 1

    with pytest.raises(OrderConflict, match="同一幂等标识不能用于不同派工"):
        service.dispatch_confirm(
            **args,
            version=order.version,
            preview_id=other_preview["preview_id"],
            idempotency_key="idem",
        )

    # Different key on same preview → second dispatch is blocked (preview consumed).
    with pytest.raises(OrderConflict, match="派工预览已失效"):
        service.dispatch_confirm(
            **args,
            version=order.version,
            preview_id=preview["preview_id"],
            idempotency_key="other",
        )

    # Re-dispatch of already ASSIGNED detail → blocked at preview (version or state).
    with pytest.raises(OrderConflict):
        service.dispatch_preview(**args, version=order.version, detail_ids=[detail_id])


def test_concurrent_dispatch_previews_create_only_one_assignment(test_database_engine: Engine):
    sessions, source, order_id = setup_dispatch_order(test_database_engine)
    with Session(test_database_engine) as session:
        session.add(
            User(
                user_id="admin-order-import-2",
                role="admin",
                is_enabled=True,
                feishu_display_name="烧麦",
            )
        )
        session.commit()
    service = OrderDispatchService(sessions, source=source)
    order = service.get(order_id=order_id)
    detail_ids = [order.details[0].detail_id]
    actors = ("admin-order-import", "admin-order-import-2")
    previews = {
        actor: service.dispatch_preview(
            actor_id=actor,
            order_id=order_id,
            request_id=f"preview-{actor}",
            version=order.version,
            detail_ids=detail_ids,
        )["preview_id"]
        for actor in actors
    }

    def confirm(actor: str) -> str:
        try:
            service.dispatch_confirm(
                actor_id=actor,
                order_id=order_id,
                request_id=f"confirm-{actor}",
                version=order.version,
                preview_id=previews[actor],
                idempotency_key=f"dispatch-{actor}",
            )
            return "success"
        except OrderConflict:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(confirm, actors)) == ["conflict", "success"]
    with Session(test_database_engine) as session:
        assert session.query(OrderAssignment).count() == 1
        assert session.query(OutboxMessage).count() == 1


def test_concurrent_same_key_retry_reuses_one_dispatch_result(test_database_engine: Engine):
    sessions, source, order_id = setup_dispatch_order(test_database_engine)
    service = OrderDispatchService(sessions, source=source)
    order = service.get(order_id=order_id)
    preview = service.dispatch_preview(
        actor_id="admin-order-import",
        order_id=order_id,
        request_id="concurrent-preview",
        version=order.version,
        detail_ids=[order.details[0].detail_id],
    )

    def confirm(_: int):
        return service.dispatch_confirm(
            actor_id="admin-order-import",
            order_id=order_id,
            request_id="concurrent-confirm",
            version=order.version,
            preview_id=preview["preview_id"],
            idempotency_key="concurrent-same-key",
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(confirm, range(2)))
    assert results[0] == results[1]
    with Session(test_database_engine) as session:
        assert session.query(OrderAssignment).count() == 1
        assert session.query(OutboxMessage).count() == 1


def test_source_changed_after_dispatch_preview_requires_re_preview(
    test_database_engine: Engine,
):
    sessions, source, order_id = setup_dispatch_order(test_database_engine)
    service = OrderDispatchService(sessions, source=source)
    args = dict(actor_id="admin-order-import", order_id=order_id, request_id="t90")
    order = service.get(order_id=order_id)
    detail_id = order.details[0].detail_id
    preview = service.dispatch_preview(**args, version=order.version, detail_ids=[detail_id])
    assert preview["all_ok"] is True

    # Source changes between preview and confirm.
    source._pages = [
        [
            replace(
                source._pages[0][0],
                shipped_quantity=30,
                raw_fields={"下单数": 100, "出货总数": 30},
            )
        ]
    ]
    with pytest.raises(OrderConflict, match="来源资料或匹配结果已变化"):
        service.dispatch_confirm(
            **args,
            version=order.version,
            preview_id=preview["preview_id"],
            idempotency_key="race",
        )

    with Session(test_database_engine) as session:
        details = list(session.scalars(select(OrderDetail).where(OrderDetail.order_id == order_id)))
        for d in details:
            assert d.dispatch_state == "UNASSIGNED"
        assert session.query(OrderAssignment).count() == 0


def test_dispatch_notifies_factory_users_and_re_consume_skips(
    test_database_engine: Engine,
):
    sessions, source, order_id = setup_dispatch_order(test_database_engine)
    now = datetime(2026, 9, 11, 5, 0, tzinfo=UTC)
    service = OrderDispatchService(sessions, source=source, clock=lambda: now)
    args = dict(actor_id="admin-order-import", order_id=order_id, request_id="t90")
    order = service.get(order_id=order_id)
    preview = service.dispatch_preview(
        **args,
        version=order.version,
        detail_ids=[order.details[0].detail_id],
    )
    service.dispatch_confirm(
        **args,
        version=order.version,
        preview_id=preview["preview_id"],
        idempotency_key="notif",
    )

    # Seed wechat authorization for the factory user.
    notices = NotificationsAuditService(sessions)
    notices.record_authorizations(
        user_id="factory-import-user",
        results={"factory_status": "accepted"},
    )

    consumed = notices.consume_next_business_event(worker_id="test", now=now)
    assert consumed is True, "expected one business event to be consumed"

    with Session(test_database_engine) as session:
        nf = session.scalar(
            select(Notification).where(Notification.recipient_id == "factory-import-user")
        )
        assert nf is not None
        assert nf.event_type == "order_detail_dispatched"
        assert nf.category == "NEW_ORDER"
        assert nf.title == "新订单任务"
        assert "新派工 1 条明细" in nf.summary

        # A second consume should return False (outbox already completed).
    assert notices.consume_next_business_event(worker_id="test", now=now) is False

    # The notification was created once only.
    with Session(test_database_engine) as session:
        assert (
            session.query(Notification).filter_by(recipient_id="factory-import-user").count() == 1
        )

        # Delivery outbox message was created.
        deliveries = session.scalars(
            select(OutboxMessage).where(
                OutboxMessage.message_kind == "delivery",
                OutboxMessage.aggregate_id == order_id,
            )
        ).all()
        assert len(deliveries) >= 1


def test_cross_factory_dispatch_notifies_only_own_factory(test_database_engine: Engine):
    _seed_factory_b(test_database_engine)
    rows = [
        _row("rec-a"),  # factory "测试工厂"
        SourceOrderRow(
            "rec-b",
            "90#",
            "6970000000001",
            "测试童帽",
            "蓝色 / 120",
            "童帽春夏",
            "测试工厂B",
            50,
            0,
            50,
            "松子",
            None,
            date(2026, 12, 31),
            {"下单数": 50, "出货总数": 0},
        ),
    ]
    sessions, source, order_id = setup_dispatch_order(test_database_engine, rows=rows)
    now = datetime(2026, 9, 11, 5, 0, tzinfo=UTC)
    service = OrderDispatchService(sessions, source=source, clock=lambda: now)
    args = dict(actor_id="admin-order-import", order_id=order_id, request_id="t90")
    order = service.get(order_id=order_id)
    a_id = next(d.detail_id for d in order.details if d.factory_name == "测试工厂")

    # Dispatch only the A-factory detail.
    preview = service.dispatch_preview(**args, version=order.version, detail_ids=[a_id])
    assert preview["all_ok"] is True
    service.dispatch_confirm(
        **args,
        version=order.version,
        preview_id=preview["preview_id"],
        idempotency_key="cross",
    )

    notices = NotificationsAuditService(sessions)
    notices.record_authorizations(
        user_id="factory-import-user",
        results={"factory_status": "accepted"},
    )
    notices.record_authorizations(
        user_id="factory-b-user",
        results={"factory_status": "accepted"},
    )

    notices.consume_next_business_event(worker_id="test", now=now)

    with Session(test_database_engine) as session:
        nf_a = session.scalar(
            select(Notification).where(
                Notification.recipient_id == "factory-import-user",
            )
        )
        assert nf_a is not None
        nf_b = session.scalar(
            select(Notification).where(
                Notification.recipient_id == "factory-b-user",
            )
        )
        assert nf_b is None, "factory B must not be notified for A's dispatch"


@pytest.mark.parametrize("invalidated", ["deleted_order", "inactive_assignment"])
def test_dispatch_notification_skips_invalidated_task(
    test_database_engine: Engine,
    invalidated: str,
):
    sessions, source, order_id = setup_dispatch_order(test_database_engine)
    now = datetime(2026, 9, 11, 5, 0, tzinfo=UTC)
    service = OrderDispatchService(sessions, source=source, clock=lambda: now)
    order = service.get(order_id=order_id)
    preview = service.dispatch_preview(
        actor_id="admin-order-import",
        order_id=order_id,
        request_id="deleted-preview",
        version=order.version,
        detail_ids=[order.details[0].detail_id],
    )
    service.dispatch_confirm(
        actor_id="admin-order-import",
        order_id=order_id,
        request_id="deleted-confirm",
        version=order.version,
        preview_id=preview["preview_id"],
        idempotency_key="deleted-notification",
    )
    with Session(test_database_engine) as session:
        if invalidated == "deleted_order":
            stored = session.get(Order, order_id)
            assert stored is not None
            stored.deleted_at = now
        else:
            assignment = session.scalar(select(OrderAssignment))
            assert assignment is not None
            assignment.is_active = False
        session.commit()

    notices = NotificationsAuditService(sessions)
    notices.record_authorizations(
        user_id="factory-import-user", results={"factory_status": "accepted"}
    )
    assert notices.consume_next_business_event(worker_id="test", now=now) is True
    with Session(test_database_engine) as session:
        assert session.scalar(select(Notification)) is None


def test_detail_mode_order_cannot_complete_or_withdraw(test_database_engine: Engine):
    sessions, source, order_id = setup_dispatch_order(test_database_engine)
    service = OrderDispatchService(sessions, source=source)
    args = dict(actor_id="admin-order-import", order_id=order_id, request_id="t90")
    order = service.get(order_id=order_id)

    # Dispatch first to make it PUBLISHED.
    preview = service.dispatch_preview(
        **args,
        version=order.version,
        detail_ids=[order.details[0].detail_id],
    )
    result = service.dispatch_confirm(
        **args,
        version=order.version,
        preview_id=preview["preview_id"],
        idempotency_key="guard",
    )
    assert result.lifecycle == "PUBLISHED"

    # Complete → blocked.
    from app.modules.orders import OrderService

    order_svc = OrderService(sessions)
    with pytest.raises(OrderConflict, match="暂不支持"):
        order_svc.complete(
            actor_id="admin-order-import",
            order_id=order_id,
            request_id="t90",
            idempotency_key="complete",
        )
    # Withdraw → blocked.
    with pytest.raises(OrderConflict, match="暂不支持"):
        order_svc.withdraw(
            actor_id="admin-order-import",
            order_id=order_id,
            request_id="t90",
            idempotency_key="withdraw",
        )


def test_migration_downgrade_rejects_dispatch_assignments(
    test_database_engine: Engine,
    test_database_url: str,
):
    from alembic import command as alembic_cmd
    from alembic.config import Config

    sessions, source, order_id = setup_dispatch_order(test_database_engine)
    service = OrderDispatchService(sessions, source=source)
    args = dict(actor_id="admin-order-import", order_id=order_id, request_id="t90")
    order = service.get(order_id=order_id)
    preview = service.dispatch_preview(
        **args,
        version=order.version,
        detail_ids=[order.details[0].detail_id],
    )
    service.dispatch_confirm(
        **args,
        version=order.version,
        preview_id=preview["preview_id"],
        idempotency_key="migrate",
    )

    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", test_database_url)
    with pytest.raises(RuntimeError, match="拒绝有损回滚"):
        alembic_cmd.downgrade(config, "20260911_0035")

    with Session(test_database_engine) as session:
        assert session.query(OrderAssignment).count() == 1
        assert session.scalar(select(Order).where(Order.order_id == order_id))
