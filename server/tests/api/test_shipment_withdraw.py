import base64
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, event, select
from sqlalchemy.orm import Session, sessionmaker

from app.adapters.private_files import FakePrivateFileStore
from app.db.models import Order, OrderCompletionRecord, User
from app.main import create_app
from app.modules.identity_access import IdentityAccessService
from app.modules.notifications_audit import NotificationsAuditService
from app.modules.shipments.service import ShipmentService
from tests.api.test_shipment_api import (
    ADMIN_ID,
    FACTORY_IDS,
    ORDER_ID,
    SAME_FACTORY_USER_ID,
    USER_IDS,
    _seed,
)


def test_withdraw_restores_shared_draft_without_overwriting_formal_history(
    test_database_engine: Engine,
    test_database_url: str,
) -> None:
    assignment = _seed(test_database_engine)
    identity = IdentityAccessService(
        sessionmaker(test_database_engine, class_=Session, expire_on_commit=False),
        token_secret=b"withdraw-test",
        phone_encryption_secret=b"withdraw-test",
        phone_digest_secret=b"withdraw-test",
    )
    tokens = {
        u: identity.issue_session(user_id=u, terminal="mini").access_token
        for u in [*USER_IDS, SAME_FACTORY_USER_ID]
    }
    with TestClient(create_app(database_url=test_database_url, identity_service=identity)) as c:
        c.headers["Authorization"] = f"Bearer {tokens[USER_IDS[0]]}"
        draft = c.post("/api/v1/factory/shipments/drafts", json={}).json()

        def save(sid: str, version: int, quantity: int):
            return c.put(
                f"/api/v1/factory/shipments/drafts/{sid}",
                json={
                    "version": version,
                    "note": "saved",
                    "boxes": [
                        {"boxNo": 1, "items": [{"assignmentId": assignment, "quantity": quantity}]}
                    ],
                },
            )

        draft = save(draft["shipmentId"], draft["version"], 12).json()
        original = c.post(
            f"/api/v1/factory/shipments/drafts/{draft['shipmentId']}/submit",
            headers={"Idempotency-Key": "first"},
        ).json()
        sid = original["shipmentId"]
        normal = c.post("/api/v1/factory/shipments/drafts", json={}).json()
        c.headers["Authorization"] = f"Bearer {tokens[SAME_FACTORY_USER_ID]}"
        response = c.post(
            f"/api/v1/factory/shipments/{sid}/withdraw",
            json={"reason": "wrong count", "version": original["version"]},
            headers={"Idempotency-Key": "withdraw-1"},
        )
        assert response.status_code == 200, response.text
        withdrawn = response.json()
        assert withdrawn["status"] == "WITHDRAWN"
        edit = c.get(f"/api/v1/factory/shipments/{sid}/withdraw-draft").json()
        assert edit["shipmentNo"] == original["shipmentNo"]
        assert save(edit["shipmentId"], edit["version"], 9).status_code == 200
        formal = c.get(f"/api/v1/factory/shipments/{sid}").json()
        assert formal["totalQuantity"] == 12
        assert c.get("/api/v1/factory/shipment-catalog").json()["items"][0]["shippedQuantity"] == 0
        c.headers["Authorization"] = f"Bearer {tokens[USER_IDS[0]]}"
        assert (
            c.get("/api/v1/factory/shipments/drafts/current").json()["shipmentId"]
            == normal["shipmentId"]
        )
        assert save(edit["shipmentId"], edit["version"], 8).status_code == 409
        edit = c.get(f"/api/v1/factory/shipments/{sid}/withdraw-draft").json()
        result = c.post(
            f"/api/v1/factory/shipments/drafts/{edit['shipmentId']}/submit?version={edit['version']}",
            headers={"Idempotency-Key": "resubmit-1"},
        )
        assert result.status_code == 200, result.text
        assert result.json()["shipmentId"] == sid
        assert result.json()["shipmentNo"] == original["shipmentNo"]
        assert result.json()["totalQuantity"] == 9
        assert c.get("/api/v1/factory/shipments").json()["total"] == 1
        assert c.get("/api/v1/factory/shipment-catalog").json()["items"][0]["shippedQuantity"] == 9
        assert save(edit["shipmentId"], edit["version"], 7).status_code == 409


@pytest.fixture
def withdrawal_clients(
    test_database_engine: Engine, test_database_url: str
) -> Iterator[tuple[TestClient, TestClient, TestClient, TestClient, TestClient, str]]:
    assignment = _seed(test_database_engine, initial_shipped_quantity=5)
    with Session(test_database_engine) as session, session.begin():
        session.add(
            User(
                user_id="withdraw-observer",
                feishu_display_name="Observer",
                role="factory",
                is_enabled=True,
                factory_id=FACTORY_IDS[0],
                factory_position="employee",
            )
        )
    identity = IdentityAccessService(
        sessionmaker(test_database_engine, class_=Session, expire_on_commit=False),
        token_secret=b"withdraw-test",
        phone_encryption_secret=b"withdraw-test",
        phone_digest_secret=b"withdraw-test",
    )
    app = create_app(
        database_url=test_database_url,
        identity_service=identity,
        private_file_store=FakePrivateFileStore(bucket="withdraw-test"),
    )
    with ExitStack() as stack:
        clients = []
        for uid in [ADMIN_ID, USER_IDS[0], SAME_FACTORY_USER_ID, "withdraw-observer", USER_IDS[1]]:
            c = stack.enter_context(TestClient(app, base_url="https://testserver"))
            login = identity.issue_session(
                user_id=uid, terminal="web" if uid == ADMIN_ID else "mini"
            )
            if uid == ADMIN_ID:
                c.cookies.set("ot_web_session", login.access_token)
                c.headers["X-CSRF-Token"] = login.csrf_token
            else:
                c.headers["Authorization"] = f"Bearer {login.access_token}"
            c.headers["Idempotency-Key"] = "test-default"
            clients.append(c)
        admin, factory, colleague, observer, foreign = clients
        draft = factory.post("/api/v1/factory/shipments/drafts", json={}).json()
        sid = draft["shipmentId"]
        factory.put(
            f"/api/v1/factory/shipments/drafts/{sid}",
            json={
                "version": 1,
                "boxes": [{"boxNo": 1, "items": [{"assignmentId": assignment, "quantity": 12}]}],
            },
        )
        factory.post(f"/api/v1/factory/shipments/drafts/{sid}/submit")
        yield admin, factory, colleague, observer, foreign, sid


def withdraw(c: TestClient, sid: str, key: str = "withdraw-1"):
    version = c.get(f"/api/v1/factory/shipments/{sid}").json()["version"]
    return c.post(
        f"/api/v1/factory/shipments/{sid}/withdraw",
        json={"reason": "wrong count", "version": version},
        headers={"Idempotency-Key": key},
    )


def test_withdraw_permissions_files_versions_and_historical_visibility(withdrawal_clients):
    admin, factory, colleague, observer, foreign, sid = withdrawal_clients
    assert withdraw(colleague, sid).status_code == 200
    url = f"/api/v1/factory/shipments/{sid}/withdraw-draft"
    assert observer.get(url).status_code == 404
    assert foreign.get(url).status_code == 404
    assert admin.get(url).status_code == 401
    edit = factory.get(url).json()
    draft_url = f"/api/v1/factory/shipments/drafts/{edit['shipmentId']}"
    image = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
    )
    uploaded = colleague.post(
        draft_url + f"/files?version={edit['version']}",
        files={"file": ("proof.png", image, "image/png")},
        headers={"Idempotency-Key": "new-draft-photo"},
    )
    assert uploaded.status_code == 201, uploaded.text
    file_url = uploaded.json()["contentUrl"]
    assert factory.get(file_url).status_code == 200
    assert colleague.get(file_url).status_code == 200
    assert observer.get(file_url).status_code == 404
    assert admin.get(file_url).status_code == 404
    assert foreign.get(file_url).status_code == 404
    assert not admin.get(f"/api/v1/admin/shipments/{sid}").json()["files"]
    assert (
        factory.delete(draft_url + f"/files/{uploaded.json()['fileId']}?version=1").status_code
        == 409
    )
    assert factory.delete(draft_url + "?version=2").status_code == 409
    submitted = colleague.post(
        draft_url + "/submit?version=2", headers={"Idempotency-Key": "round1"}
    )
    assert submitted.status_code == 200, submitted.text
    assert admin.get(file_url).status_code == 200
    assert withdraw(observer, sid, "round2-withdraw").status_code == 200
    # Editing follows the latest submitter and withdrawer, not the first submitter.
    assert factory.get(url).status_code == 404
    second = colleague.get(url).json()
    assert observer.get(url).status_code == 200
    assert (
        observer.delete(
            f"/api/v1/factory/shipments/drafts/{second['shipmentId']}"
            f"/files/{uploaded.json()['fileId']}?version=1"
        ).status_code
        == 200
    )
    # Removing an editable reference does not remove a formal historical attachment.
    assert admin.get(file_url).status_code == 200
    assert admin.get(f"/api/v1/admin/shipments/{sid}").json()["files"]


def test_repeated_withdraw_resubmit_and_stale_pages_do_not_duplicate_quantities(
    withdrawal_clients, test_database_engine
):
    admin, factory, colleague, _, _, sid = withdrawal_clients
    service = ShipmentService(sessionmaker(test_database_engine, class_=Session))
    original = factory.get(f"/api/v1/factory/shipments/{sid}").json()
    receipt_url = f"/api/v1/admin/shipments/{sid}/receipt"
    receipt = admin.get(receipt_url).json()
    assert admin.put(receipt_url, json={"version": 0, "items": receipt["items"]}).status_code == 200
    for round_no in (1, 2):
        result = withdraw(colleague, sid, f"withdraw-{round_no}")
        assert result.status_code == 200
        assert not service.has_valid_shipments(order_id=ORDER_ID)
        assert withdraw(colleague, sid, f"withdraw-{round_no}").status_code == 200
        assert (
            factory.get("/api/v1/factory/shipment-catalog").json()["items"][0]["shippedQuantity"]
            == 5
        )
        assert (
            admin.put(receipt_url, json={"version": 1, "items": receipt["items"]}).status_code
            == 409
        )
        edit = factory.get(f"/api/v1/factory/shipments/{sid}/withdraw-draft").json()
        submit_url = (
            f"/api/v1/factory/shipments/drafts/{edit['shipmentId']}"
            f"/submit?version={edit['version']}"
        )
        submitted = factory.post(submit_url, headers={"Idempotency-Key": f"submit-{round_no}"})
        assert submitted.status_code == 200, submitted.text
        assert service.has_valid_shipments(order_id=ORDER_ID)
        assert submitted.json()["shipmentNo"] == original["shipmentNo"]
        assert (
            factory.post(submit_url, headers={"Idempotency-Key": f"submit-{round_no}"}).status_code
            == 200
        )
        assert (
            factory.get("/api/v1/factory/shipment-catalog").json()["items"][0]["shippedQuantity"]
            == 17
        )
        assert admin.post(receipt_url + "/confirm", json={"version": 1}).status_code == 409
    assert factory.get("/api/v1/factory/shipments").json()["total"] == 1
    assert len(admin.get(f"/api/v1/admin/shipments/{sid}").json()["operations"]) == 5


def test_file_retry_cannot_adopt_another_edit_version(withdrawal_clients):
    _, factory, colleague, _, _, sid = withdrawal_clients
    assert withdraw(colleague, sid).status_code == 200
    edit = factory.get(f"/api/v1/factory/shipments/{sid}/withdraw-draft").json()
    url = f"/api/v1/factory/shipments/drafts/{edit['shipmentId']}"
    image = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
    )

    def upload():
        return colleague.post(
            url + "/files?version=1",
            files={"file": ("proof.png", image, "image/png")},
            headers={"Idempotency-Key": "retry-photo"},
        )

    assert upload().status_code == 201
    retry = upload()
    assert retry.status_code == 200
    assert retry.json()["draftVersion"] == 2
    saved = factory.put(
        url,
        json={
            "version": 2,
            "note": "someone else's saved change",
            "boxes": [
                {
                    "boxNo": box["boxNo"],
                    "items": [
                        {"assignmentId": item["assignmentId"], "quantity": item["quantity"]}
                        for item in box["items"]
                    ],
                }
                for box in edit["boxes"]
            ],
        },
    )
    assert saved.status_code == 200, saved.text
    assert upload().status_code == 409


def test_withdraw_reopens_completed_order_and_preserves_submission_history(
    withdrawal_clients, test_database_engine
):
    admin, factory, colleague, _, foreign, sid = withdrawal_clients
    assert (
        foreign.post(
            f"/api/v1/factory/shipments/{sid}/withdraw",
            json={"reason": "wrong factory", "version": 1},
        ).status_code
        == 404
    )
    original = factory.get(f"/api/v1/factory/shipments/{sid}").json()
    with Session(test_database_engine) as session, session.begin():
        order = session.get(Order, ORDER_ID)
        order.lifecycle = "COMPLETED"
    result = withdraw(colleague, sid)
    assert result.status_code == 200, result.text
    operations = result.json()["operations"]
    assert operations[0]["action"] == "shipment_submitted"
    assert operations[0]["createdAt"].removesuffix("Z") == original["submittedAt"].removesuffix("Z")
    with Session(test_database_engine) as session:
        assert session.get(Order, ORDER_ID).lifecycle == "PUBLISHED"
        record = session.scalar(
            select(OrderCompletionRecord).where(
                OrderCompletionRecord.order_id == ORDER_ID,
                OrderCompletionRecord.action == "REOPEN",
            )
        )
        assert record is not None
    assert admin.get(f"/api/v1/admin/shipments/{sid}").json()["totalQuantity"] == 12


def test_withdraw_rejects_returned_and_retired_approval_routes(withdrawal_clients):
    admin, factory, _, _, _, sid = withdrawal_clients
    formal = admin.get(f"/api/v1/admin/shipments/{sid}").json()
    returned = admin.post(
        f"/api/v1/admin/shipments/{sid}/returns",
        json={
            "reason": "return",
            "lines": [{"shipmentLineId": formal["lines"][0]["lineId"], "quantity": 1}],
        },
    )
    assert returned.status_code == 201
    assert withdraw(factory, sid).status_code == 409
    assert (
        factory.post(
            f"/api/v1/factory/shipments/{sid}/void-requests", json={"reason": "old app"}
        ).status_code
        == 404
    )
    assert (
        admin.post("/api/v1/admin/shipment-void-requests/unknown/approve", json={}).status_code
        == 404
    )
    assert (
        factory.get("/api/v1/factory/shipment-catalog").json()["items"][0]["shippedQuantity"] == 16
    )


def test_concurrent_saves_have_one_winner(withdrawal_clients):
    _, factory, colleague, _, _, sid = withdrawal_clients
    assert withdraw(colleague, sid).status_code == 200
    draft = factory.get(f"/api/v1/factory/shipments/{sid}/withdraw-draft").json()
    url = f"/api/v1/factory/shipments/drafts/{draft['shipmentId']}"

    def save(pair):
        c, quantity = pair
        return c.put(
            url,
            json={
                "version": draft["version"],
                "boxes": [
                    {
                        "boxNo": 1,
                        "items": [
                            {
                                "assignmentId": draft["lines"][0]["assignmentId"],
                                "quantity": quantity,
                            }
                        ],
                    }
                ],
            },
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(save, [(factory, 8), (colleague, 9)]))
    assert sorted(r.status_code for r in responses) == [200, 409]
    winner = next(r.json()["totalQuantity"] for r in responses if r.status_code == 200)
    assert (
        factory.get(f"/api/v1/factory/shipments/{sid}/withdraw-draft").json()["totalQuantity"]
        == winner
    )


def test_receipt_confirmation_and_withdrawal_cannot_both_succeed(withdrawal_clients):
    admin, factory, _, _, _, sid = withdrawal_clients
    version = factory.get(f"/api/v1/factory/shipments/{sid}").json()["version"]

    def act(kind):
        if kind == "receipt":
            return admin.post(f"/api/v1/admin/shipments/{sid}/receipt/confirm", json={"version": 0})
        return factory.post(
            f"/api/v1/factory/shipments/{sid}/withdraw",
            json={"version": version, "reason": "concurrent"},
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(act, ["receipt", "withdraw"]))
    assert sorted(r.status_code for r in responses) == [200, 409]
    result = admin.get(f"/api/v1/admin/shipments/{sid}").json()
    quantity = factory.get("/api/v1/factory/shipment-catalog").json()["items"][0]["shippedQuantity"]
    assert quantity == (5 if result["status"] == "WITHDRAWN" else 17)


def test_transaction_failure_keeps_original_quantity_and_no_draft(withdrawal_clients):
    admin, factory, _, _, _, sid = withdrawal_clients

    def fail_outbox(conn, cursor, statement, parameters, context, executemany):
        if statement.startswith("INSERT INTO outbox_messages"):
            raise RuntimeError("injected transaction failure")

    event.listen(Engine, "before_cursor_execute", fail_outbox)
    try:
        with pytest.raises(RuntimeError, match="injected transaction failure"):
            withdraw(factory, sid)
    finally:
        event.remove(Engine, "before_cursor_execute", fail_outbox)
    assert admin.get(f"/api/v1/admin/shipments/{sid}").json()["status"] == "SHIPPED"
    assert factory.get(f"/api/v1/factory/shipments/{sid}/withdraw-draft").status_code == 404
    assert (
        factory.get("/api/v1/factory/shipment-catalog").json()["items"][0]["shippedQuantity"] == 17
    )


def test_delayed_notifications_use_each_submission_fact(withdrawal_clients, test_database_engine):
    _, factory, colleague, _, _, sid = withdrawal_clients
    assert withdraw(colleague, sid).status_code == 200
    draft = factory.get(f"/api/v1/factory/shipments/{sid}/withdraw-draft").json()
    draft_url = f"/api/v1/factory/shipments/drafts/{draft['shipmentId']}"
    saved = factory.put(
        draft_url,
        json={
            "version": draft["version"],
            "boxes": [
                {
                    "boxNo": 1,
                    "items": [{"assignmentId": draft["lines"][0]["assignmentId"], "quantity": 9}],
                }
            ],
        },
    ).json()
    assert factory.post(draft_url + f"/submit?version={saved['version']}").status_code == 200
    notifications = NotificationsAuditService(
        sessionmaker(test_database_engine, expire_on_commit=False)
    )
    for _ in range(3):
        assert notifications.consume_next_business_event(worker_id="withdraw-test")
    assert not notifications.consume_next_business_event(worker_id="withdraw-test")
    values = notifications.list_notifications(
        user_id=ADMIN_ID, unread_only=False, page=1, page_size=20
    )
    summaries = [n.summary for n in values.items]
    assert len(summaries) == 3
    assert any("总计12件" in text for text in summaries)
    assert any("总计9件" in text for text in summaries)
    assert any("扣回12件" in text for text in summaries)
    assert all("等待审核" not in text for text in summaries)
