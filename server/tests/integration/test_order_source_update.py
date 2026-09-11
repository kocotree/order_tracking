from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.adapters.order_source import FakeFeishuOrderSource
from app.db.models import OrderDetail
from app.modules.order_import import OrderImportService, SourceOrderRow
from app.modules.orders import OrderConflict
from app.modules.orders.source_update import OrderSourceUpdateService
from tests.integration.test_order_import import _seed_import_dependencies


def setup_order(test_database_engine: Engine, *, two_rows: bool = False):
    _seed_import_dependencies(test_database_engine)
    sessions = sessionmaker(test_database_engine, expire_on_commit=False)
    importer = OrderImportService(sessions)
    row = SourceOrderRow(
        "rec89",
        "89#",
        "6970000000001",
        "测试童帽",
        "蓝色 / 120",
        "童帽春夏",
        "测试工厂",
        100,
        0,
        100,
        "松子",
        None,
        date(2026, 12, 31),
        {"出货总数": 0},
    )
    rows = [row, replace(row, record_id="rec90")] if two_rows else [row]
    source = FakeFeishuOrderSource([rows])
    run = importer.create_or_reuse_run(actor_id="admin-order-import", request_id="seed89")
    importer.process_run(
        run_id=run.run_id, pages_read=1, rows=rows, source_scope=source.source_scope
    )
    candidates, _ = importer.list_candidates(actor_id="admin-order-import")
    order_id = importer.confirm_candidate(
        actor_id="admin-order-import",
        candidate_id=candidates[0].candidate_id,
        request_id="import89",
    )
    return sessions, row, source, order_id


def test_source_preview_date_protection_versions_and_idempotency(test_database_engine: Engine):
    sessions, row, source, order_id = setup_order(test_database_engine)
    now = datetime(2026, 9, 11, tzinfo=UTC)
    service = OrderSourceUpdateService(sessions, source=source, clock=lambda: now)
    args = dict(actor_id="admin-order-import", order_id=order_id, request_id="test89")
    order = service.get(order_id=order_id)
    detail = order.details[0]
    source._pages = [[replace(row, shipped_quantity=20, raw_fields={"出货总数": 20})]]
    preview = service.preview(**args, version=order.version)
    assert service.get(order_id=order_id).shipped_quantity == 0
    saved = service.save_date(
        **args,
        version=order.version,
        detail_id=detail.detail_id,
        detail_version=detail.version,
        contract_ship_date=None,
    )
    with pytest.raises(OrderConflict):
        service.confirm(
            **args, version=order.version, preview_id=preview["preview_id"], idempotency_key="stale"
        )
    preview = service.preview(**args, version=saved.version)
    result = service.confirm(
        **args, version=saved.version, preview_id=preview["preview_id"], idempotency_key="once"
    )
    assert result.shipped_quantity == 20
    assert result.details[0].contract_ship_date is None
    source._fail_on_page = 1
    retry = service.confirm(
        **args, version=saved.version, preview_id=preview["preview_id"], idempotency_key="once"
    )
    assert retry == result
    source._fail_on_page = None
    with pytest.raises(OrderConflict):
        service.confirm(
            **args, version=result.version, preview_id=preview["preview_id"], idempotency_key="once"
        )
    newer = service.preview(**args, version=result.version)
    now += timedelta(minutes=6)
    with pytest.raises(OrderConflict):
        service.confirm(
            **args,
            version=result.version,
            preview_id=newer["preview_id"],
            idempotency_key="expired",
        )
    with Session(test_database_engine) as session:
        stored = session.scalar(select(OrderDetail).where(OrderDetail.order_id == order_id))
        assert stored.date_override_enabled
        assert stored.source_contract_ship_date == date(2026, 12, 31)


@pytest.mark.parametrize("change", ["missing", "renumber", "identity", "failure", "duplicate"])
def test_invalid_source_keeps_all_business_data(test_database_engine: Engine, change: str):
    from app.adapters.errors import ExternalAdapterUnavailable
    from app.db.models import AuditLog, OrderChangePreview

    sessions, row, source, order_id = setup_order(test_database_engine)
    service = OrderSourceUpdateService(sessions, source=source)
    before = service.get(order_id=order_id)
    if change == "failure":
        source._fail_on_page = 1
    else:
        source._pages = [
            {
                "missing": [],
                "renumber": [replace(row, order_no="other")],
                "identity": [replace(row, source_detail_id="other")],
                "duplicate": [row, row],
            }[change]
        ]
    with pytest.raises((OrderConflict, ExternalAdapterUnavailable)):
        service.preview(
            actor_id="admin-order-import",
            order_id=order_id,
            version=before.version,
            request_id="bad89",
        )
    assert service.get(order_id=order_id) == before
    with sessions() as session:
        assert session.query(OrderChangePreview).count() == 0
        assert (
            session.query(AuditLog).filter(AuditLog.action == "order.source_refreshed").count() == 0
        )


def test_source_changes_again_and_transaction_rollback(test_database_engine: Engine):
    from sqlalchemy import event

    from app.db.models import AuditLog, IdempotencyRecord, OrderChangePreview

    sessions, row, source, order_id = setup_order(test_database_engine)
    service = OrderSourceUpdateService(sessions, source=source)
    args = dict(actor_id="admin-order-import", order_id=order_id, version=1, request_id="again89")
    source._pages = [[replace(row, shipped_quantity=10, raw_fields={"出货总数": 10})]]
    preview = service.preview(**args)
    source._pages = [[replace(row, shipped_quantity=11, raw_fields={"出货总数": 11})]]
    with pytest.raises(OrderConflict, match="来源资料"):
        service.confirm(**args, preview_id=preview["preview_id"], idempotency_key="changed")
    assert service.get(order_id=order_id).shipped_quantity == 0
    preview = service.preview(**args)

    def fail(_mapper, _connection, target):
        if target.action == "order.source_refreshed":
            raise RuntimeError("rollback89")

    event.listen(AuditLog, "before_insert", fail)
    try:
        with pytest.raises(RuntimeError, match="rollback89"):
            service.confirm(**args, preview_id=preview["preview_id"], idempotency_key="rollback")
    finally:
        event.remove(AuditLog, "before_insert", fail)
    assert service.get(order_id=order_id).shipped_quantity == 0
    with sessions() as session:
        assert session.get(OrderChangePreview, preview["preview_id"]).consumed_at is None
        assert session.query(IdempotencyRecord).count() == 0
    confirmed = service.confirm(
        **args, preview_id=preview["preview_id"], idempotency_key="rollback"
    )
    assert confirmed.details[0].contract_ship_date == date(2026, 12, 27)
    again = service.preview(**{**args, "version": confirmed.version})
    assert again["differences"] == []


def test_assigned_details_and_tracker_are_protected(test_database_engine: Engine):
    from app.db.models import Order

    sessions, row, source, order_id = setup_order(test_database_engine)
    with sessions() as session, session.begin():
        original = session.scalar(select(OrderDetail).where(OrderDetail.order_id == order_id))
        original.dispatch_state = "ASSIGNED"
        order = session.get(Order, order_id)
        order.lifecycle = "PUBLISHED"
        session.add(
            OrderDetail(
                detail_id="unassigned89",
                order_id=order_id,
                origin="legacy",
                sort_order=2,
                accepted_raw_fields={},
                parse_issues=[],
                dispatch_state="UNASSIGNED",
                source_tracker="青椒",
                date_override_enabled=False,
                created_at=order.created_at,
                updated_at=order.updated_at,
            )
        )
    service = OrderSourceUpdateService(sessions, source=source)
    args = dict(
        actor_id="admin-order-import", order_id=order_id, version=1, request_id="assigned89"
    )
    before = service.get(order_id=order_id)
    with pytest.raises(OrderConflict):
        service.save_date(
            **args,
            detail_id=before.details[0].detail_id,
            detail_version=1,
            contract_ship_date=date(2026, 10, 1),
        )
    with pytest.raises(OrderConflict, match="来源关联"):
        service.preview(**args)
    assert service.get(order_id=order_id) == before


def test_api_rejects_other_fields_and_wrong_terminal(
    test_database_engine: Engine, test_database_url: str
):
    from fastapi.testclient import TestClient

    from app.main import create_app
    from app.modules.identity_access import IdentityAccessService

    sessions, row, source, order_id = setup_order(test_database_engine)
    identity = IdentityAccessService(sessions, token_secret=b"issue89")
    admin = identity.issue_session(user_id="admin-order-import", terminal="web")
    mini = identity.issue_session(user_id="admin-order-import", terminal="mini")
    app = create_app(database_url=test_database_url, identity_service=identity, order_source=source)
    service = OrderSourceUpdateService(sessions, source=source)
    detail_id = service.get(order_id=order_id).details[0].detail_id
    url = f"/api/v1/admin/orders/{order_id}/details/{detail_id}/contract-date"
    payload = dict(version=1, detailVersion=1, contractShipDate=None)
    with TestClient(app, base_url="https://testserver") as client:
        assert client.patch(url, json=payload).status_code == 401
        assert (
            client.patch(
                url, json=payload, headers={"Authorization": f"Bearer {mini.access_token}"}
            ).status_code
            == 401
        )
        client.cookies.set("ot_web_session", admin.access_token)
        headers = {"X-CSRF-Token": admin.csrf_token}
        assert client.patch(url, json=payload).status_code == 403
        for field in ("factoryId", "orderQuantity", "sourceTracker", "initialShippedQuantity"):
            assert (
                client.patch(url, json={**payload, field: "forged"}, headers=headers).status_code
                == 422
            )
        response = client.patch(url, json=payload, headers=headers)
        assert response.status_code == 200, response.text
        assert response.json()["details"][0]["contractShipDate"] is None
        assert client.patch(url, json=payload, headers=headers).status_code == 409


def test_partial_refresh_protects_assigned_snapshot_and_locked_tracker(
    test_database_engine: Engine,
):
    from app.db.models import Order, OutboxMessage

    sessions, row, source, order_id = setup_order(test_database_engine, two_rows=True)
    with sessions() as session, session.begin():
        details = list(session.scalars(select(OrderDetail).order_by(OrderDetail.sort_order)))
        assigned_id, pending_id = [d.detail_id for d in details]
        details[0].dispatch_state = "ASSIGNED"
        session.get(Order, order_id).lifecycle = "PUBLISHED"
    requested = []

    def read(ids):
        requested.extend(ids)
        return [replace(row, record_id="rec90", shipped_quantity=30, tracker="青椒")]

    source.read_records = read
    service = OrderSourceUpdateService(sessions, source=source)
    args = dict(actor_id="admin-order-import", order_id=order_id, version=1, request_id="partial89")
    preview = service.preview(**args)
    result = service.confirm(**args, preview_id=preview["preview_id"], idempotency_key="partial")
    assert requested == ["rec90", "rec90"]
    assert result.tracker == "松子"
    with sessions() as session:
        assert session.get(OrderDetail, assigned_id).source_shipped_quantity == 0
        assert session.get(OrderDetail, assigned_id).version == 1
        assert session.get(OrderDetail, pending_id).source_shipped_quantity == 30
        assert session.query(OutboxMessage).count() == 0


def test_concurrent_confirm_writes_once(test_database_engine: Engine):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from app.db.models import AuditLog

    sessions, row, source, order_id = setup_order(test_database_engine)
    source._pages = [[replace(row, shipped_quantity=40)]]
    service = OrderSourceUpdateService(sessions, source=source)
    args = dict(
        actor_id="admin-order-import", order_id=order_id, version=1, request_id="concurrent89"
    )
    preview = service.preview(**args)
    barrier = Barrier(2)
    original = source.read_records

    def read(ids):
        result = original(ids)
        barrier.wait(timeout=10)
        return result

    source.read_records = read

    def confirm():
        return service.confirm(**args, preview_id=preview["preview_id"], idempotency_key="same89")

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: confirm(), range(2)))
    assert [result.version for result in results] == [2, 2]
    with sessions() as session:
        assert (
            session.query(AuditLog).filter(AuditLog.action == "order.source_refreshed").count() == 1
        )


def test_saved_detail_order_stays_stable(test_database_engine: Engine):
    sessions, row, source, order_id = setup_order(test_database_engine, two_rows=True)
    with sessions() as session, session.begin():
        rows = list(session.scalars(select(OrderDetail).order_by(OrderDetail.detail_id.desc())))
        for index, detail in enumerate(rows, 1):
            detail.sort_order = index
    service = OrderSourceUpdateService(sessions, source=source)
    before = service.get(order_id=order_id)
    first = before.details[0]
    saved = service.save_date(
        actor_id="admin-order-import",
        order_id=order_id,
        version=1,
        detail_id=first.detail_id,
        detail_version=1,
        contract_ship_date=date(2026, 12, 25),
        request_id="stable89",
    )
    assert [d.detail_id for d in saved.details] == [d.detail_id for d in before.details]
    assert saved.details[0].contract_ship_date == date(2026, 12, 25)


def test_invalid_raw_quantity_changes_are_visible(test_database_engine: Engine):
    sessions, row, source, order_id = setup_order(test_database_engine)
    with sessions() as session, session.begin():
        detail = session.scalar(select(OrderDetail))
        detail.order_quantity = None
        detail.accepted_raw_fields = {"下单数": "待补"}
    source._pages = [[replace(row, order_quantity=None, raw_fields={"下单数": "未知"})]]
    service = OrderSourceUpdateService(sessions, source=source)
    preview = service.preview(
        actor_id="admin-order-import", order_id=order_id, version=1, request_id="raw89"
    )
    change = next(d for d in preview["differences"] if d["field"] == "下单数量")
    assert (change["before"], change["after"]) == ("待补", "未知")


def test_confirmed_refresh_downgrade_keeps_idempotent_result(
    test_database_engine: Engine, test_database_url: str
):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import inspect

    sessions, row, source, order_id = setup_order(test_database_engine)
    service = OrderSourceUpdateService(sessions, source=source)
    source._pages = [[replace(row, shipped_quantity=20)]]
    args = dict(
        actor_id="admin-order-import", order_id=order_id, version=1, request_id="migration89"
    )
    preview = service.preview(**args)
    result = service.confirm(
        **args, preview_id=preview["preview_id"], idempotency_key="migration89"
    )
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", test_database_url)
    with pytest.raises(RuntimeError, match="拒绝有损回滚"):
        command.downgrade(config, "20260911_0034")
    assert inspect(test_database_engine).has_table("order_change_previews")
    assert (
        service.confirm(**args, preview_id=preview["preview_id"], idempotency_key="migration89")
        == result
    )


def test_refresh_preserves_explicitly_locked_tracker(test_database_engine: Engine):
    from app.db.models import Order

    sessions, row, source, order_id = setup_order(test_database_engine)
    with sessions() as session, session.begin():
        session.get(Order, order_id).tracker_locked_at = datetime(2026, 9, 11)
    service = OrderSourceUpdateService(sessions, source=source)
    source._pages = [[replace(row, tracker="青椒")]]
    args = dict(actor_id="admin-order-import", order_id=order_id, version=1, request_id="tracker89")
    preview = service.preview(**args)
    result = service.confirm(**args, preview_id=preview["preview_id"], idempotency_key="tracker89")
    assert result.tracker == "松子"
    assert result.details[0].source_tracker == "青椒"
