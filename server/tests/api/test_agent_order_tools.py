from dataclasses import replace
from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.adapters.identity import FakeFeishuIdentity
from app.db.models import Factory
from app.main import create_app
from app.modules.identity_access import FeishuProfile, IdentityAccessService
from tests.api.test_agent_oauth import _client, _code, _exchange, _login
from tests.api.test_order_api import _seed
from tests.integration.test_order_dispatch import _row, setup_dispatch_order


def _call(client: TestClient, token: str, name: str, arguments: dict[str, object]):
    response = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
              "params": {"name": name, "arguments": arguments}},
        headers={"Authorization": f"Bearer {token}",
                 "Accept": "application/json, text/event-stream"},
    )
    assert response.status_code == 200
    return response.json()["result"]


def test_agent_order_draft_publish_and_contract_qualification(
    test_database_engine: Engine, test_database_url: str, monkeypatch
) -> None:
    _seed(test_database_engine)
    monkeypatch.setenv("ORDER_TRACKING_APP_ENV", "local_demo")
    with _client(test_database_engine, test_database_url, monkeypatch) as client:
        _login(client)
        access = _exchange(client, _code(client)).json()["access_token"]
        listed = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
            headers={"Authorization": f"Bearer {access}",
                     "Accept": "application/json, text/event-stream"},
        ).json()["result"]["tools"]
        names = {tool["name"] for tool in listed}
        assert {"start_import_run", "list_import_candidates", "import_candidates",
                "create_order_draft", "update_order_details", "preview_source_refresh",
                "preview_dispatch", "confirm_dispatch", "list_order_contracts",
                "export_contract", "withdraw_factory_dispatch", "reopen_order"} <= names
        start_schema = next(tool for tool in listed if tool["name"] == "start_import_run")
        assert "idempotency_key" in start_schema["inputSchema"]["required"]
        started = _call(client, access, "start_import_run", {
            "idempotency_key": "mcp-153-import-run",
        })["structuredContent"]
        same_run = _call(client, access, "start_import_run", {
            "idempotency_key": "mcp-153-import-run",
        })["structuredContent"]
        assert started["runId"] == same_run["runId"]
        run = _call(client, access, "get_import_run", {
            "run_id": started["runId"],
        })["structuredContent"]
        assert run["runId"] == started["runId"]

        created = _call(client, access, "create_order_draft", {
            "order_no": "MCP-153", "order_date": "2026-09-21", "tracker": "松子",
            "lines": [{"variantId": "order-api-variant", "orderQuantity": 10,
                       "assignments": [{"factoryId": "order-api-factory-a",
                                        "quantity": 10,
                                        "contractShipDate": "2026-09-30"}]}],
        })
        assert created.get("isError") is not True
        draft = created["structuredContent"]
        assert draft["orderNo"] == "MCP-153"
        order_id = draft["orderId"]

        published = _call(client, access, "publish_order_draft", {
            "order_id": order_id, "version": draft["version"],
            "idempotency_key": "mcp-153-publish",
        })
        assert published.get("isError") is not True
        assert published["structuredContent"]["lifecycle"] == "PUBLISHED"
        repeated = _call(client, access, "publish_order_draft", {
            "order_id": order_id, "version": draft["version"],
            "idempotency_key": "mcp-153-publish",
        })
        assert repeated["structuredContent"]["version"] == published["structuredContent"]["version"]

        contracts = _call(client, access, "list_order_contracts", {"order_id": order_id})
        assert contracts.get("isError") is not True
        statuses = contracts["structuredContent"]["result"]["items"]
        assert statuses[0]["factoryId"] == "order-api-factory-a"
        assert statuses[0]["contractReady"] is False

        with Session(test_database_engine) as session, session.begin():
            factory = session.get(Factory, "order-api-factory-a")
            assert factory is not None
            factory.factory_code = "MCP"
            factory.legal_name = "MCP 测试工厂"
            factory.address = "测试地址"
            factory.legal_representative = "测试法人"
        ready = _call(client, access, "list_order_contracts", {"order_id": order_id})
        assert ready["structuredContent"]["result"]["items"][0]["eligible"] is True
        exported = _call(client, access, "export_contract", {
            "order_id": order_id, "factory_id": "order-api-factory-a",
            "signing_date": "2026-09-21", "idempotency_key": "mcp-153-export-1",
        })
        assert exported.get("isError") is not True
        first = exported["structuredContent"]["result"]
        assert first["status"] == "READY"
        repeated_export = _call(client, access, "export_contract", {
            "order_id": order_id, "factory_id": "order-api-factory-a",
            "idempotency_key": "mcp-153-export-2",
        })
        assert repeated_export["structuredContent"]["result"]["contractNo"] == first["contractNo"]

        blocked = _call(client, access, "complete_order", {
            "order_id": order_id, "idempotency_key": "mcp-153-complete",
        })
        assert blocked["isError"] is True


def test_agent_456_source_snapshot_date_and_dispatch(
    test_database_engine: Engine, test_database_url: str, monkeypatch
) -> None:
    sessions, source, order_id = setup_dispatch_order(test_database_engine, rows=[
        _row(record_id="rec456", order_no="456#", contract_ship_date=None)
    ])
    monkeypatch.setenv("ORDER_TRACKING_MCP_PUBLIC_URL", "http://testserver/mcp")
    monkeypatch.setenv("ORDER_TRACKING_MCP_CLIENT_ID", "codex-company-test")
    monkeypatch.setenv("ORDER_TRACKING_WEB_COOKIE_SECURE", "false")
    monkeypatch.setenv("ORDER_TRACKING_IDENTITY_TOKEN_SECRET", "agent-test-token-secret")
    identity = IdentityAccessService(
        sessionmaker(test_database_engine, class_=Session),
        feishu_identity=FakeFeishuIdentity(
            profiles={"agent-code": FeishuProfile(
                subject="agent-user", display_name="Test Admin", phone="13812345122",
            )}, scope="tenant-test/app-test",
        ),
        token_secret=b"agent-test-token-secret",
        phone_encryption_secret=b"agent-test-phone-encryption",
        phone_digest_secret=b"agent-test-phone-digest",
    )
    with TestClient(create_app(
        database_url=test_database_url, identity_service=identity, order_source=source,
    )) as client:
        _login(client)
        access = _exchange(client, _code(client)).json()["access_token"]
        candidates = _call(client, access, "list_import_candidates", {
            "status": "IMPORTED",
        })["structuredContent"]["result"]["items"]
        assert len(candidates) == 1
        audit = _call(client, access, "get_candidate_audit", {
            "candidate_id": candidates[0]["candidateId"],
        })["structuredContent"]
        assert audit["total"] > 0
        current = _call(client, access, "get_order", {"order_id": order_id})[
            "structuredContent"
        ]
        assert current["details"][0]["contractShipDate"] is None
        source._pages = [[replace(
            source._pages[0][0], shipped_quantity=25,
            raw_fields={"下单数": 100, "出货总数": 25},
        )]]
        preview = _call(client, access, "preview_source_refresh", {
            "order_id": order_id, "version": current["version"],
        })["structuredContent"]["result"]
        assert any(item["field"] == "已发数量" for item in preview["differences"])
        refreshed = _call(client, access, "confirm_source_refresh", {
            "order_id": order_id, "version": current["version"],
            "preview_id": preview["preview_id"], "idempotency_key": "mcp-153-source",
        })["structuredContent"]
        assert refreshed["details"][0]["shippedQuantity"] == 25
        detail = refreshed["details"][0]
        saved = _call(client, access, "update_order_details", {
            "order_id": order_id, "version": refreshed["version"],
            "lines": [{"detailId": detail["detailId"],
                       "detailVersion": detail["version"],
                       "contractShipDate": date(2026, 9, 30).isoformat()}],
        })["structuredContent"]
        assert saved["details"][0]["contractShipDate"] == "2026-09-30"
        dispatch_preview = _call(client, access, "preview_dispatch", {
            "order_id": order_id, "version": saved["version"],
            "detail_ids": [detail["detailId"]],
        })["structuredContent"]["result"]
        assert dispatch_preview["all_ok"] is True
        assigned = _call(client, access, "confirm_dispatch", {
            "order_id": order_id, "version": saved["version"],
            "preview_id": dispatch_preview["preview_id"],
            "idempotency_key": "mcp-153-dispatch",
        })["structuredContent"]
        assert assigned["details"][0]["dispatchState"] == "ASSIGNED"
        assert assigned["details"][0]["shippedQuantity"] == 25
