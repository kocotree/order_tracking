from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.db.models import OrderAssignment
from app.modules.orders import OrderConflict
from app.modules.orders.dispatch import OrderDispatchService
from tests.integration.test_order_dispatch import _row, setup_dispatch_order

ACTOR = "admin-order-import"
NOW = datetime(2026, 9, 11, tzinfo=UTC)


def test_local_demo_wires_saved_demo_source_for_dispatch(test_database_engine: Engine, monkeypatch):
    from fastapi.testclient import TestClient

    from app.db.models import OrderImportSourceRecord
    from app.main import create_app
    from app.modules.identity_access import IdentityAccessService

    sessions, _, oid = setup_dispatch_order(test_database_engine)
    with sessions() as session, session.begin():
        for record in session.scalars(select(OrderImportSourceRecord)):
            record.source_scope = "local-demo-import"
    monkeypatch.setenv("ORDER_TRACKING_APP_ENV", "local_demo")
    identity = IdentityAccessService(sessions)
    web = identity.issue_session(user_id=ACTOR, terminal="web")
    app = create_app(identity_service=identity)
    with TestClient(app, base_url="https://testserver") as client:
        client.cookies.set("ot_web_session", web.access_token)
        client.cookies.set("ot_csrf", web.csrf_token or "")
        order = client.get(f"/api/v1/orders/{oid}").json()
        result = client.post(
            f"/api/v1/admin/orders/{oid}/dispatch/preview",
            json={"version": order["version"], "detailIds": [order["details"][0]["detailId"]]},
            headers={"X-CSRF-Token": web.csrf_token or ""},
        )
        assert result.status_code == 200
        assert result.json()["allOk"] is True


def dispatch(service, order_id, ids, key):
    order = service.get(order_id=order_id)
    args = dict(actor_id=ACTOR, order_id=order_id, version=order.version, request_id=key)
    preview = service.dispatch_preview(**args, detail_ids=ids)
    assert preview["all_ok"], preview
    return service.dispatch_confirm(**args, preview_id=preview["preview_id"], idempotency_key=key)


def test_source_overdue_filter_count_and_completion(test_database_engine: Engine):
    sessions, source, oid = setup_dispatch_order(
        test_database_engine,
        rows=[
            _row("a", shipped_quantity=110, pending_quantity=0),
            _row("b", contract_ship_date=date(2026, 9, 1)),
        ],
    )
    service = OrderDispatchService(sessions, source=source, clock=lambda: NOW)
    order = service.get(order_id=oid)
    order = dispatch(service, oid, [order.details[0].detail_id], "a")
    assert order.pending_quantity == 80
    assert order.display_status == "已逾期"
    found, count = service.list_visible(
        actor_id=ACTOR, status="已逾期", page_size=1, ship_date_to=date(2026, 9, 2)
    )
    assert count == 1 and found[0].order_id == oid
    assert service.dashboard_counts(actor_id=ACTOR)[0] == 1
    with pytest.raises(OrderConflict):
        service.complete(actor_id=ACTOR, order_id=oid, request_id="complete", idempotency_key="c")


def test_withdraw_preserves_and_redispatches_execution(test_database_engine: Engine):
    sessions, source, oid = setup_dispatch_order(test_database_engine)
    service = OrderDispatchService(sessions, source=source, clock=lambda: NOW)
    order = service.get(order_id=oid)
    detail_id = order.details[0].detail_id
    order = dispatch(service, oid, [detail_id], "first")
    with Session(test_database_engine) as session:
        old = session.scalar(select(OrderAssignment))
        old_id, factory = old.order_assignment_id, old.factory_id
    args = dict(
        actor_id=ACTOR,
        order_id=oid,
        factory_id=factory,
        version=order.version,
        request_id="withdraw",
        idempotency_key="withdraw",
    )
    withdrawn = service.withdraw_factory(**args)
    assert withdrawn.lifecycle == "DRAFT"
    assert withdrawn.details[0].dispatch_state == "UNASSIGNED"
    assert withdrawn.shipped_quantity == 20
    assert service.withdraw_factory(**args) == withdrawn
    order = dispatch(service, oid, [detail_id], "again")
    assert order.total_quantity == 100 and order.shipped_quantity == 20
    with Session(test_database_engine) as session:
        assignments = list(session.scalars(select(OrderAssignment)))
        assert len(assignments) == 2
        assert session.get(OrderAssignment, old_id).is_active is False
        assert sum(a.is_active for a in assignments) == 1
        assert all(a.detail_id == detail_id for a in assignments)


def test_completion_requires_each_assigned_detail_and_keeps_reopen_log(
    test_database_engine: Engine,
):
    from app.db.models import OrderCompletionRecord, OrderDetail, QuantityLedger

    sessions, source, oid = setup_dispatch_order(
        test_database_engine,
        rows=[
            _row("a", shipped_quantity=120),
            _row("b", shipped_quantity=80),
        ],
    )
    service = OrderDispatchService(sessions, source=source, clock=lambda: NOW)
    order = dispatch(service, oid, [d.detail_id for d in service.get(order_id=oid).details], "all")
    args = dict(actor_id=ACTOR, order_id=oid, request_id="complete", idempotency_key="complete")
    assert order.pending_quantity == 20 and order.shipped_quantity == order.total_quantity
    with pytest.raises(OrderConflict):
        service.complete(**args)
    with sessions() as session, session.begin():
        detail = session.get(OrderDetail, order.details[1].detail_id)
        session.add(
            QuantityLedger(
                order_assignment_id=detail.assignment_id,
                source_type="shipment",
                source_id="fixture",
                quantity_delta=20,
                actor_id=ACTOR,
                created_at=NOW,
            )
        )
    assert service.get(order_id=oid).lifecycle == "PUBLISHED"
    assert service.complete(**args).lifecycle == "COMPLETED"
    assert (
        service.reopen(**{**args, "idempotency_key": "reopen"}, reason="重新核对").lifecycle
        == "PUBLISHED"
    )
    with sessions() as session:
        assert [
            r.action
            for r in session.scalars(
                select(OrderCompletionRecord).order_by(OrderCompletionRecord.record_id)
            )
        ] == ["COMPLETE", "REOPEN"]


def test_withdraw_transaction_concurrency_and_old_shipment_id(
    test_database_engine: Engine, monkeypatch
):
    from concurrent.futures import ThreadPoolExecutor

    from app.modules.shipments import (
        DraftBoxInput,
        DraftItemInput,
        ShipmentNotFound,
        ShipmentService,
    )

    sessions, source, oid = setup_dispatch_order(test_database_engine)
    service = OrderDispatchService(sessions, source=source, clock=lambda: NOW)
    order = dispatch(service, oid, [service.get(order_id=oid).details[0].detail_id], "first")
    with sessions() as session:
        assignment = session.scalar(select(OrderAssignment))
        aid, fid = assignment.order_assignment_id, assignment.factory_id
    args = dict(
        actor_id=ACTOR,
        order_id=oid,
        factory_id=fid,
        version=order.version,
        request_id="withdraw",
        idempotency_key="same",
    )
    shipments = ShipmentService(sessions)
    owner = dict(actor_id="factory-import-user", factory_id=fid)
    draft, _ = shipments.create_or_reuse_draft(**owner, preferred_order_id=oid)
    draft = shipments.save_draft(
        **owner,
        shipment_id=draft.shipment_id,
        boxes=[
            DraftBoxInput(
                box_no=1, group_key=None, items=[DraftItemInput(assignment_id=aid, quantity=5)]
            )
        ],
        note="",
    )
    original = service._add_audit

    def fail(*args, **kwargs):
        raise RuntimeError("rollback")

    monkeypatch.setattr(service, "_add_audit", fail)
    with pytest.raises(RuntimeError, match="rollback"):
        service.withdraw_factory(**args)
    with sessions() as session:
        assert session.get(OrderAssignment, aid).is_active
    monkeypatch.setattr(service, "_add_audit", original)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: service.withdraw_factory(**args), range(2)))
    assert results[0] == results[1]
    with pytest.raises(OrderConflict, match="幂等"):
        service.withdraw_factory(**{**args, "factory_id": "forged"})
    with pytest.raises(ShipmentNotFound):
        shipments.submit_draft(
            **owner,
            shipment_id=draft.shipment_id,
            idempotency_key="stale",
            expected_version=draft.version,
        )


@pytest.mark.parametrize("change", ["withdraw", "permission"])
def test_delayed_reminders_and_dispatch_recheck_tasks_and_permission(
    test_database_engine: Engine, change: str
):
    from app.adapters.notifications import FakeFeishuBusinessNotifier, FakeWechatNotifier
    from app.db.models import OutboxMessage, User
    from app.modules.notifications_audit import NotificationsAuditService

    sessions, source, oid = setup_dispatch_order(
        test_database_engine, rows=[_row(contract_ship_date=date(2026, 9, 18))]
    )
    service = OrderDispatchService(sessions, source=source, clock=lambda: NOW)
    notice = NotificationsAuditService(sessions)
    notice.record_authorizations(
        user_id="factory-import-user",
        results={"factory_status": "accepted", "factory_due": "accepted"},
        authorized_at=NOW.replace(tzinfo=None),
    )
    with sessions() as session, session.begin():
        session.get(User, ACTOR).feishu_display_name = "松子"
    order = dispatch(service, oid, [service.get(order_id=oid).details[0].detail_id], "first")
    assert notice.consume_next_business_event(worker_id="test", now=NOW.replace(tzinfo=None))
    assert (
        notice.scan_due_reminders(business_date=date(2026, 9, 11), now=NOW.replace(tzinfo=None)) > 0
    )
    if change == "withdraw":
        service.withdraw_factory(
            actor_id=ACTOR,
            order_id=oid,
            factory_id="factory-import",
            version=order.version,
            request_id="w",
            idempotency_key="w",
        )
    else:
        with sessions() as session, session.begin():
            session.get(User, "factory-import-user").factory_id = None
            session.get(User, ACTOR).feishu_display_name = "不再负责"
    assert notice.scan_due_reminders(business_date=date(2026, 9, 11)) == 0
    wechat, feishu = FakeWechatNotifier(), FakeFeishuBusinessNotifier()
    while notice.deliver_next(
        worker_id="test",
        wechat_notifier=wechat,
        feishu_notifier=feishu,
        now=NOW.replace(tzinfo=None),
    ):
        pass
    assert not wechat.sent and not feishu.sent
    with sessions() as session:
        deliveries = list(
            session.scalars(select(OutboxMessage).where(OutboxMessage.message_kind == "delivery"))
        )
        assert len(deliveries) == 3
        assert all(row.last_error_code == "task_or_permission_changed" for row in deliveries)


def test_factory_withdrawal_isolated_from_shipped_factory_and_contract(
    test_database_engine: Engine,
):
    from app.adapters.private_files import FakePrivateFileStore
    from app.db.models import Factory, OrderDetail, ProcessingContract, Shipment, ShipmentLine
    from app.modules.contracts import ContractService
    from app.modules.contracts.workbook import ContractWorkbookRenderer
    from tests.integration.test_order_dispatch import _seed_factory_b

    sessions, source, oid = setup_dispatch_order(
        test_database_engine,
        rows=[
            _row("a"),
            _row("b", factory_name="测试工厂B"),
            _row("c"),
        ],
    )
    _seed_factory_b(test_database_engine)
    with sessions() as session, session.begin():
        session.scalar(
            select(OrderDetail).where(OrderDetail.factory_name == "测试工厂B")
        ).matched_factory_id = "factory-b"
    service = OrderDispatchService(sessions, source=source, clock=lambda: NOW)
    order = dispatch(
        service, oid, [d.detail_id for d in service.get(order_id=oid).details[:2]], "two"
    )
    with sessions() as session, session.begin():
        for factory in session.scalars(select(Factory)):
            factory.legal_name, factory.address, factory.legal_representative = (
                "合同工厂",
                "地址",
                "法人",
            )
        assignment = session.scalar(
            select(OrderAssignment).where(OrderAssignment.factory_id == "factory-b")
        )
        aid = assignment.order_assignment_id
        session.add(
            Shipment(
                shipment_id="shipped",
                factory_id="factory-b",
                status="SHIPPED",
                created_by="factory-b-user",
            )
        )
        session.flush()
        session.add(
            ShipmentLine(
                shipment_id="shipped",
                order_assignment_id=aid,
                quantity=5,
                order_no_snapshot="90#",
                sku_id_snapshot="6970000000001",
                product_name_snapshot="测试童帽",
                properties_value_snapshot="蓝色 / 120",
            )
        )
    contracts = ContractService(
        sessions,
        file_store=FakePrivateFileStore(bucket="test"),
        workbook_renderer=ContractWorkbookRenderer(
            template_path=Path("app/templates/processing_contract_v1.xlsx")
        ),
    )
    exported = contracts.create_export(
        actor_id=ACTOR,
        order_id=oid,
        factory_id="factory-b",
        signing_date=date(2026, 9, 11),
        idempotency_key="contract",
        request_id="contract",
    )
    with sessions() as session:
        snapshot = dict(session.scalar(select(ProcessingContract)).contract_snapshot)
        assert len(snapshot["lines"]) == 1 and snapshot["lines"][0]["quantity"] == 100
    factories = {
        f["factory_id"]: f for f in service.withdrawal_factories(actor_id=ACTOR, order_id=oid)
    }
    assert factories["factory-b"]["blocked"] and not factories["factory-import"]["blocked"]
    args = dict(
        actor_id=ACTOR, order_id=oid, version=order.version, idempotency_key="w", request_id="w"
    )
    with pytest.raises(OrderConflict, match="有效系统发货"):
        service.withdraw_factory(**args, factory_id="factory-b")
    result = service.withdraw_factory(**args, factory_id="factory-import")
    assert result.lifecycle == "PUBLISHED"
    assert [d.dispatch_state for d in result.details] == ["UNASSIGNED", "ASSIGNED", "UNASSIGNED"]
    assert [c.factory_id for c in contracts.list_for_order(actor_id=ACTOR, order_id=oid)] == [
        "factory-b"
    ]
    repeated = contracts.create_export(
        actor_id=ACTOR,
        order_id=oid,
        factory_id="factory-b",
        signing_date=None,
        idempotency_key="export-again",
        request_id="again",
    )
    assert repeated.contract_no == exported.contract_no
    with sessions() as session:
        assert session.get(OrderAssignment, aid).is_active
        assert session.get(Shipment, "shipped").status == "SHIPPED"
        assert session.scalar(select(ProcessingContract)).contract_snapshot == snapshot


def test_mixed_source_global_filters_and_sort_before_pagination(test_database_engine: Engine):
    from app.db.models import Order, OrderDetail

    sessions, source, oid = setup_dispatch_order(test_database_engine)
    service = OrderDispatchService(sessions, source=source, clock=lambda: NOW)
    dispatch(service, oid, [service.get(order_id=oid).details[0].detail_id], "active")
    with sessions() as session, session.begin():
        for index in range(25):
            session.add(
                Order(
                    order_id=f"source-{index}",
                    order_no=f"S-{index:02}",
                    source="feishu",
                    detail_mode=True,
                    lifecycle="PUBLISHED",
                    tracker="松子",
                    created_by=ACTOR,
                    updated_by=ACTOR,
                )
            )
        session.flush()
        for index in range(25):
            session.add(
                OrderDetail(
                    detail_id=f"detail-{index}",
                    order_id=f"source-{index}",
                    origin="source",
                    sort_order=1,
                    product_name=f"商品{index:02}",
                    factory_name="测试工厂",
                    matched_factory_id="factory-import",
                    category="童帽春夏",
                    order_quantity=100,
                    source_shipped_quantity=index,
                    dispatch_state="UNASSIGNED",
                    source_tracker="松子",
                    contract_ship_date=date(2026, 9, 1),
                    accepted_raw_fields={},
                    parse_issues=[],
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
    for sort in ["shippedQuantityDesc", "progressPercentDesc", "productNameDesc"]:
        rows, count = service.list_visible(
            actor_id=ACTOR,
            include_drafts=True,
            status="已逾期",
            sort_by=sort,
            page=2,
            page_size=10,
            factory_ids=["factory-import"],
            keyword="商品",
            ship_date_to=date(2026, 9, 1),
        )
        assert count == 25
        assert [row.order_no for row in rows] == [f"S-{i:02}" for i in range(14, 4, -1)]
    assert service.dashboard_counts(actor_id=ACTOR)[0] == 25
    with sessions() as session, session.begin():
        for order in session.scalars(select(Order).where(Order.order_id.like("source-%"))):
            order.lifecycle = "DRAFT"

    from fastapi.testclient import TestClient

    from app.main import create_app
    from app.modules.identity_access import IdentityAccessService

    identity = IdentityAccessService(sessions)
    web = identity.issue_session(user_id=ACTOR, terminal="web")
    with TestClient(create_app(identity_service=identity, order_service=service)) as client:
        client.cookies.set("ot_web_session", web.access_token)
        result = client.get(
            "/api/v1/admin/dashboard/orders",
            params={"keyword": "商品", "sortBy": "productNameDesc"},
        )
        assert result.status_code == 200
        data = result.json()
        assert data["totalOrders"] == 25 and data["overdueOrders"] == 0
        assert [row["orderNo"] for row in data["recentOrders"]] == [
            f"S-{i:02}" for i in range(24, 14, -1)
        ]
        assert all(row["lifecycle"] == "DRAFT" for row in data["recentOrders"])


def test_legacy_withdrawal_redispatch_uses_retained_snapshot(test_database_engine: Engine):
    from sqlalchemy.orm import sessionmaker

    from app.adapters.order_source import FakeFeishuOrderSource
    from app.modules.orders import AssignmentInput, DraftLineInput
    from tests.integration.test_order_lifecycle import _seed_order_dependencies

    actor, factory, _, variant = _seed_order_dependencies(test_database_engine)
    sessions = sessionmaker(test_database_engine, expire_on_commit=False)
    source = FakeFeishuOrderSource([])
    service = OrderDispatchService(sessions, source=source, clock=lambda: NOW)
    order = service.create_draft(
        actor_id=actor,
        order_no="LEGACY",
        order_date=None,
        tracker="松子",
        request_id="legacy",
        lines=[
            DraftLineInput(
                variant_id=variant,
                order_quantity=100,
                assignments=[
                    AssignmentInput(
                        factory_id=factory,
                        quantity=100,
                        initial_shipped_quantity=20,
                        contract_ship_date=date(2026, 12, 31),
                    )
                ],
            )
        ],
    )
    order = service.publish(
        actor_id=actor,
        order_id=order.order_id,
        version=order.version,
        request_id="publish",
        idempotency_key="publish",
    )
    order = service.withdraw_factory(
        actor_id=actor,
        order_id=order.order_id,
        factory_id=factory,
        version=order.version,
        request_id="withdraw",
        idempotency_key="withdraw",
    )
    args = dict(
        actor_id=actor, order_id=order.order_id, version=order.version, request_id="redispatch"
    )
    preview = service.dispatch_preview(**args, detail_ids=[order.details[0].detail_id])
    assert preview["all_ok"]
    order = service.dispatch_confirm(
        **args, preview_id=preview["preview_id"], idempotency_key="redispatch"
    )
    assert order.shipped_quantity == 20 and order.total_quantity == 100


def test_withdraw_api_requires_web_admin_csrf_and_current_version(test_database_engine: Engine):
    from fastapi.testclient import TestClient

    from app.main import create_app
    from app.modules.identity_access import IdentityAccessService

    sessions, source, oid = setup_dispatch_order(test_database_engine)
    service = OrderDispatchService(sessions, source=source, clock=lambda: NOW)
    order = dispatch(service, oid, [service.get(order_id=oid).details[0].detail_id], "first")
    identity = IdentityAccessService(sessions)
    web = identity.issue_session(user_id=ACTOR, terminal="web")
    app = create_app(identity_service=identity, order_service=service)
    with TestClient(app, base_url="https://testserver") as client:
        path = f"/api/v1/admin/orders/{oid}/dispatch/withdraw"
        payload = {"factoryId": "factory-import", "version": order.version}
        assert (
            client.post(path, json=payload, headers={"Idempotency-Key": "api-w"}).status_code == 401
        )
        client.cookies.set("ot_web_session", web.access_token)
        client.cookies.set("ot_csrf", web.csrf_token or "")
        assert (
            client.post(path, json=payload, headers={"Idempotency-Key": "api-w"}).status_code == 403
        )
        headers = {"X-CSRF-Token": web.csrf_token or "", "Idempotency-Key": "api-w"}
        assert (
            client.post(f"/api/v1/admin/orders/{oid}/withdraw", headers=headers).status_code == 404
        )
        assert (
            client.post(
                path, json={**payload, "version": order.version - 1}, headers=headers
            ).status_code
            == 409
        )
        assert (
            client.post(path, json={**payload, "reason": "extra"}, headers=headers).status_code
            == 422
        )
        assert client.post(path, json=payload, headers=headers).json()["lifecycle"] == "DRAFT"
        assert client.get(f"/api/v1/admin/orders/{oid}/dispatch/factories").json() == []
