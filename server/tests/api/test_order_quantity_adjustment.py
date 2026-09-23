from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.db.models import AuditLog, OrderAssignment, OrderCompletionRecord, QuantityLedger
from app.main import create_app
from app.modules.identity_access import IdentityAccessService
from app.modules.orders.dispatch import OrderDispatchService
from tests.integration.test_order_dispatch import _row, setup_dispatch_order


def test_admin_adjusts_assigned_quantity_below_shipment_total(
    test_database_engine: Engine, test_database_url: str
) -> None:
    sessions, source, order_id = setup_dispatch_order(test_database_engine)
    service = OrderDispatchService(sessions, source=source)
    order = service.get(order_id=order_id)
    detail = order.details[0]
    preview = service.dispatch_preview(
        actor_id="admin-order-import", order_id=order_id, version=order.version,
        detail_ids=[detail.detail_id], request_id="adjust-preview",
    )
    dispatched = service.dispatch_confirm(
        actor_id="admin-order-import", order_id=order_id, version=order.version,
        preview_id=preview["preview_id"], idempotency_key="adjust-dispatch",
        request_id="adjust-dispatch",
    )
    with Session(test_database_engine) as session, session.begin():
        assignment = session.scalar(select(OrderAssignment))
        assert assignment is not None
        session.add(QuantityLedger(
            order_assignment_id=assignment.order_assignment_id, source_type="SHIPMENT",
            source_id="existing-shipment", quantity_delta=50,
            actor_id="factory-import-user", created_at=datetime.now(UTC),
        ))

    identity = IdentityAccessService(sessions, token_secret=b"adjust-quantity")
    admin = identity.issue_session(user_id="admin-order-import", terminal="web")
    factory = identity.issue_session(user_id="factory-import-user", terminal="mini")
    factory_web = identity.issue_session(user_id="factory-import-user", terminal="web")
    app = create_app(
        database_url=test_database_url, identity_service=identity, order_source=source,
    )
    url = f"/api/v1/admin/orders/{order_id}/details"
    with TestClient(app, base_url="https://testserver") as client:
        client.cookies.set("ot_web_session", admin.access_token)
        response = client.patch(
            url,
            json={"version": dispatched.version, "lines": [{
                "detailId": detail.detail_id,
                "detailVersion": dispatched.details[0].version,
                "shippedQuantity": 10,
            }]},
            headers={"X-CSRF-Token": admin.csrf_token},
        )
        assert response.status_code == 200, response.text
        changed = response.json()
        assert changed["shippedQuantity"] == 10
        assert changed["pendingQuantity"] == 90
        assert changed["details"][0]["shippedQuantity"] == 10
        assert client.get(f"/api/v1/orders/{order_id}").json()["shippedQuantity"] == 10
        assert client.patch(url, json={"version": changed["version"], "lines": [{
            "detailId": detail.detail_id,
            "detailVersion": changed["details"][0]["version"],
            "shippedQuantity": 9,
        }]}).status_code == 403
        assert client.patch(url, json={"version": changed["version"], "lines": [{
            "detailId": detail.detail_id,
            "detailVersion": changed["details"][0]["version"],
            "factoryId": "factory-import",
        }]}, headers={"X-CSRF-Token": admin.csrf_token}).status_code == 409
        assert client.patch(url, json={"version": changed["version"], "lines": [{
            "detailId": detail.detail_id,
            "detailVersion": changed["details"][0]["version"],
            "shippedQuantity": -1,
        }]}, headers={"X-CSRF-Token": admin.csrf_token}).status_code == 422
        assert client.patch(url, json={"version": dispatched.version, "lines": [{
            "detailId": detail.detail_id,
            "detailVersion": changed["details"][0]["version"],
            "shippedQuantity": 9,
        }]}, headers={"X-CSRF-Token": admin.csrf_token}).status_code == 409

    with TestClient(app, base_url="https://testserver") as client:
        visible = client.get(
            f"/api/v1/orders/{order_id}",
            headers={"Authorization": f"Bearer {factory.access_token}"},
        )
        assert visible.status_code == 200, visible.text
        assert visible.json()["shippedQuantity"] == 10
        assert visible.json()["pendingQuantity"] == 90
        client.cookies.set("ot_web_session", factory_web.access_token)
        forbidden = client.patch(url, json={"version": changed["version"], "lines": [{
            "detailId": detail.detail_id,
            "detailVersion": changed["details"][0]["version"],
            "shippedQuantity": 120,
        }]}, headers={"X-CSRF-Token": factory_web.csrf_token})
        assert forbidden.status_code == 403

    with Session(test_database_engine) as session:
        assignment = session.scalar(select(OrderAssignment))
        assert assignment is not None
        assert assignment.initial_shipped_quantity == 20
        shipment = session.scalar(
            select(QuantityLedger).where(QuantityLedger.source_type == "SHIPMENT")
        )
        assert shipment is not None and shipment.quantity_delta == 50
        adjustment = session.scalar(
            select(QuantityLedger).where(QuantityLedger.source_type == "ADMIN_ADJUSTMENT")
        )
        assert adjustment is not None and adjustment.quantity_delta == -60
        audit = session.scalar(select(AuditLog).where(AuditLog.action == "order.detail_updated"))
        assert audit is not None and audit.changes["shippedQuantity"] == {"before": 70, "after": 10}

    with TestClient(app, base_url="https://testserver") as client:
        client.cookies.set("ot_web_session", admin.access_token)
        over = client.patch(url, json={"version": changed["version"], "lines": [{
            "detailId": detail.detail_id,
            "detailVersion": changed["details"][0]["version"],
            "shippedQuantity": 120,
        }]}, headers={"X-CSRF-Token": admin.csrf_token})
        assert over.status_code == 200, over.text
        assert over.json()["shippedQuantity"] == 120
        assert over.json()["pendingQuantity"] == 0
        assert over.json()["overQuantity"] == 20


def test_completed_order_reopens_when_admin_creates_shortfall(
    test_database_engine: Engine, test_database_url: str
) -> None:
    sessions, source, order_id = setup_dispatch_order(test_database_engine)
    service = OrderDispatchService(sessions, source=source)
    order = service.get(order_id=order_id)
    preview = service.dispatch_preview(
        actor_id="admin-order-import", order_id=order_id, version=order.version,
        detail_ids=[order.details[0].detail_id], request_id="complete-preview",
    )
    dispatched = service.dispatch_confirm(
        actor_id="admin-order-import", order_id=order_id, version=order.version,
        preview_id=preview["preview_id"], idempotency_key="complete-dispatch",
        request_id="complete-dispatch",
    )
    identity = IdentityAccessService(sessions, token_secret=b"adjust-completed")
    admin = identity.issue_session(user_id="admin-order-import", terminal="web")
    app = create_app(database_url=test_database_url, identity_service=identity, order_source=source)
    url = f"/api/v1/admin/orders/{order_id}/details"
    headers = {"X-CSRF-Token": admin.csrf_token}
    with TestClient(app, base_url="https://testserver") as client:
        client.cookies.set("ot_web_session", admin.access_token)
        filled = client.patch(url, json={"version": dispatched.version, "lines": [{
            "detailId": dispatched.details[0].detail_id,
            "detailVersion": dispatched.details[0].version,
            "shippedQuantity": 100,
        }]}, headers=headers)
        assert filled.status_code == 200, filled.text
        current = service.complete(
            actor_id="admin-order-import", order_id=order_id,
            request_id="complete-order", idempotency_key="complete-order",
        )
        assert current.lifecycle == "COMPLETED"
        increased = client.patch(url, json={"version": current.version, "lines": [{
            "detailId": current.details[0].detail_id,
            "detailVersion": current.details[0].version,
            "shippedQuantity": 120,
        }]}, headers=headers)
        assert increased.status_code == 200, increased.text
        assert increased.json()["lifecycle"] == "COMPLETED"
        lowered = client.patch(url, json={"version": increased.json()["version"], "lines": [{
            "detailId": current.details[0].detail_id,
            "detailVersion": increased.json()["details"][0]["version"],
            "shippedQuantity": 99,
        }]}, headers=headers)
        assert lowered.status_code == 200, lowered.text
        assert lowered.json()["lifecycle"] == "PUBLISHED"
        assert lowered.json()["pendingQuantity"] == 1
        assert client.get(f"/api/v1/orders/{order_id}").json()["lifecycle"] == "PUBLISHED"

    with Session(test_database_engine) as session:
        records = list(
            session.scalars(select(OrderCompletionRecord).order_by(OrderCompletionRecord.record_id))
        )
        assert [record.action for record in records] == ["COMPLETE", "REOPEN"]
        assert records[-1].reason is None


def test_mixed_batch_rejects_stale_detail_without_partial_adjustment(
    test_database_engine: Engine, test_database_url: str
) -> None:
    sessions, source, order_id = setup_dispatch_order(
        test_database_engine, rows=[_row(), _row(record_id="rec91")],
    )
    service = OrderDispatchService(sessions, source=source)
    order = service.get(order_id=order_id)
    preview = service.dispatch_preview(
        actor_id="admin-order-import", order_id=order_id, version=order.version,
        detail_ids=[order.details[0].detail_id], request_id="batch-preview",
    )
    dispatched = service.dispatch_confirm(
        actor_id="admin-order-import", order_id=order_id, version=order.version,
        preview_id=preview["preview_id"], idempotency_key="batch-dispatch",
        request_id="batch-dispatch",
    )
    assigned, unassigned = dispatched.details
    identity = IdentityAccessService(sessions, token_secret=b"adjust-batch")
    admin = identity.issue_session(user_id="admin-order-import", terminal="web")
    app = create_app(database_url=test_database_url, identity_service=identity, order_source=source)
    url = f"/api/v1/admin/orders/{order_id}/details"
    headers = {"X-CSRF-Token": admin.csrf_token}
    with TestClient(app, base_url="https://testserver") as client:
        client.cookies.set("ot_web_session", admin.access_token)
        response = client.patch(url, json={"version": dispatched.version, "lines": [
            {
                "detailId": assigned.detail_id, "detailVersion": assigned.version,
                "shippedQuantity": 40,
            },
            {"detailId": unassigned.detail_id, "detailVersion": 999, "shippedQuantity": 30},
        ]}, headers=headers)
        assert response.status_code == 409
        unchanged = client.get(f"/api/v1/orders/{order_id}").json()
        assert unchanged["shippedQuantity"] == 40
        assert unchanged["details"][0]["shippedQuantity"] == 20
        assert unchanged["details"][1]["shippedQuantity"] == 20
        response = client.patch(url, json={"version": dispatched.version, "lines": [
            {
                "detailId": assigned.detail_id, "detailVersion": assigned.version,
                "shippedQuantity": 40,
            },
            {
                "detailId": unassigned.detail_id, "detailVersion": unassigned.version,
                "shippedQuantity": 30,
            },
        ]}, headers=headers)
        assert response.status_code == 200, response.text
        assert response.json()["shippedQuantity"] == 70
        assert response.json()["pendingQuantity"] == 130
        audit = client.get(f"/api/v1/admin/orders/{order_id}/audit-logs").json()["items"]
        saved = next(item for item in audit if item["action"] == "order.detail_updated")
        assert "20 → 40" in saved["content"]
        assert "20 → 30" in saved["content"]
