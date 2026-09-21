from datetime import date
from hashlib import sha256
from urllib.parse import urlsplit

from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import Shipment
from app.modules.shipments import ShipmentService
from tests.api.test_agent_oauth import _client, _code, _exchange, _login
from tests.api.test_shipment_api import FACTORY_IDS
from tests.api.test_shipment_summary import seed_shipments

pytest_plugins = ("tests.api.test_shipment_receipt_api",)


def test_daily_summary_groups_factories_and_excludes_inactive_shipments(
    test_database_engine: Engine,
) -> None:
    seed_shipments(test_database_engine, 4)
    with Session(test_database_engine) as session, session.begin():
        for index in range(4):
            shipment = session.get(Shipment, f"list-{index:04}")
            assert shipment is not None
            shipment.business_date = date(2026, 9, 1)
            if index == 3:
                shipment.factory_id = FACTORY_IDS[1]
    service = ShipmentService(sessionmaker(test_database_engine, expire_on_commit=False))
    summary = service.list_daily_shipment_summaries(business_date=date(2026, 9, 1))
    assert summary["factoryCount"] == 2
    assert summary["shipmentCount"] == 2
    assert summary["totalOriginalQuantity"] == 12
    assert [factory["factoryId"] for factory in summary["factories"]] == FACTORY_IDS
    assert service.list_daily_shipment_summaries(business_date=date(2026, 9, 4))[
        "factories"
    ] == []


def _call(client: TestClient, access: str, name: str, arguments: dict) -> dict:
    response = client.post(
        "/mcp",
        headers={
            "Authorization": f"Bearer {access}",
            "Accept": "application/json, text/event-stream",
        },
        json={
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["result"]


def test_mcp_shipment_receipt_return_matches_web_and_original_daily_export(
    receipt_clients: tuple[TestClient, TestClient, str],
    test_database_engine: Engine,
    test_database_url: str,
    monkeypatch,
) -> None:
    admin, _factory, shipment_id = receipt_clients
    web_detail = admin.get(f"/api/v1/admin/shipments/{shipment_id}").json()
    with _client(test_database_engine, test_database_url, monkeypatch) as client:
        _login(client)
        access = _exchange(client, _code(client)).json()["access_token"]
        listed = _call(client, access, "list_shipments", {"page_size": 1})
        assert listed["structuredContent"]["total"] == 1
        assert listed["structuredContent"]["items"][0]["shipmentId"] == shipment_id
        detail = _call(client, access, "get_shipment", {"shipment_id": shipment_id})
        assert detail["structuredContent"]["boxes"] == web_detail["boxes"]
        daily_args = {
            "factory_id": web_detail["factoryId"],
            "business_date": web_detail["businessDate"],
        }
        daily = _call(client, access, "get_daily_shipment_summary", daily_args)
        summary = daily["structuredContent"]
        assert summary["basis"] == "original_reported"
        assert summary["timezone"] == "Asia/Shanghai"
        assert summary["totalOriginalQuantity"] == 30
        all_factories = _call(client, access, "get_daily_shipment_summary", {
            "business_date": web_detail["businessDate"],
        })["structuredContent"]
        assert all_factories["factoryCount"] == 1
        assert all_factories["totalOriginalQuantity"] == 30
        assert all_factories["factories"][0]["items"] == summary["items"]
        assert {item["boxItemId"] for item in summary["items"]} == {
            item["boxItemId"] for box in web_detail["boxes"] for item in box["items"]
        }
        single_export = _call(client, access, "export_shipment", {
            "shipment_id": shipment_id,
        })["structuredContent"]
        single_path = urlsplit(single_export["downloadUrl"]).path
        assert single_export["sha256"] == sha256(
            admin.get(single_path).content
        ).hexdigest()
        daily_export = _call(client, access, "export_daily_shipments", daily_args)[
            "structuredContent"
        ]
        daily_path = urlsplit(daily_export["downloadUrl"]).path
        assert daily_export["sha256"] == sha256(
            admin.get(daily_path).content
        ).hexdigest()
        client.cookies.clear()
        assert client.get(
            single_path, follow_redirects=False
        ).status_code == 303
        receipt = _call(client, access, "get_receipt", {"shipment_id": shipment_id})
        items = receipt["structuredContent"]["items"]
        items[0]["quantity"] = 0
        items[1]["quantity"] = 28
        save_args = {"shipment_id": shipment_id, "version": 0, "items": items}
        saved = _call(client, access, "save_receipt", save_args)
        assert saved["structuredContent"]["version"] == 1
        assert admin.get(f"/api/v1/admin/shipments/{shipment_id}").json()["totalQuantity"] == 30
        assert _call(client, access, "save_receipt", save_args)["isError"]
        confirm_args = {"shipment_id": shipment_id, "version": 1,
                        "idempotency_key": "agent-receipt-once"}
        confirmed = _call(client, access, "confirm_receipt", confirm_args)
        assert confirmed["structuredContent"]["totalQuantity"] == 28
        assert _call(client, access, "confirm_receipt", confirm_args)["structuredContent"][
            "totalQuantity"
        ] == 28
        after_daily = _call(client, access, "get_daily_shipment_summary", daily_args)[
            "structuredContent"
        ]
        assert after_daily["totalOriginalQuantity"] == 30
        assert [item["confirmedQuantity"] for item in after_daily["items"]] == [0, 28]
        assert admin.get(f"/api/v1/admin/shipments/{shipment_id}").json()["totalQuantity"] == 28
        line_id = confirmed["structuredContent"]["lines"][0]["lineId"]
        return_args = {
            "shipment_id": shipment_id,
            "reason": "仓库退回",
            "lines": [{"shipmentLineId": line_id, "quantity": 5}],
            "idempotency_key": "agent-return-once",
        }
        returned = _call(client, access, "return_shipment", return_args)
        assert returned["structuredContent"]["created"] is True
        assert _call(client, access, "return_shipment", return_args)["structuredContent"][
            "created"
        ] is False
        assert _call(client, access, "return_shipment", {
            **return_args, "reason": "修改后的原因",
        })["isError"]
        assert admin.get(f"/api/v1/admin/shipments/{shipment_id}").json()["lines"][0][
            "returnedQuantity"
        ] == 5
