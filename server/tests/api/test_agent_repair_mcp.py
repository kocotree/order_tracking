from hashlib import sha256
from io import BytesIO

from openpyxl import load_workbook
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from app.db.models import OutboxMessage
from app.modules.repairs.periods import RepairPeriodService
from app.modules.repairs.workflow import XLSX_MIME
from tests.api.test_agent_oauth import _client, _code, _exchange, _login
from tests.integration.test_repair_periods import workbook
from tests.integration.test_repair_returns import seed_return_repair


def _call(client, token, name, arguments, call_id=2):
    response = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": call_id,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    return response.json()["result"]


def test_repair_tools_reject_internal_file_source_before_creating_preview(
    test_database_engine, test_database_url, monkeypatch
):
    with _client(test_database_engine, test_database_url, monkeypatch) as client:
        _login(client)
        token = _exchange(client, _code(client)).json()["access_token"]
        tools = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
            headers={"Authorization": f"Bearer {token}"},
        ).json()["result"]["tools"]
        names = {tool["name"] for tool in tools}
        assert {
            "list_repair_periods", "get_repair", "upload_repair_workbook",
            "get_repair_preview", "confirm_repair_previews", "archive_repair_period",
            "get_repair_download",
        } <= names
        upload = next(tool for tool in tools if tool["name"] == "upload_repair_workbook")
        assert upload["_meta"]["openai/fileParams"] == ["files"]
        result = _call(client, token, "upload_repair_workbook", {
            "files": [{
                "download_url": "https://127.0.0.1/private.xlsx",
                "file_id": "file-1",
                "file_name": "private.xlsx",
            }],
        })
        assert result["structuredContent"]["items"][0]["status"] == "ERROR"
        assert result["structuredContent"]["canConfirmAll"] is False
        preflight = _call(client, token, "confirm_repair_previews", {
            "items": [{"previewId": "missing", "idempotencyKey": "key-1"}],
        }, call_id=3)
        assert preflight["structuredContent"]["items"][0]["status"] == "INVALID"
        client.cookies.clear()
        download = client.get("/api/v1/agent-files/123/download", follow_redirects=False)
        assert download.status_code == 303
        assert download.headers["location"] == (
            "/login?returnTo=%2Fapi%2Fv1%2Fagent-files%2F123%2Fdownload"
        )
    with test_database_engine.connect() as connection:
        assert connection.exec_driver_sql("SELECT COUNT(*) FROM repair_orders").scalar() == 0


def test_repair_mcp_upload_confirm_period_and_authorized_download(
    test_database_engine, test_database_url, monkeypatch
):
    seed_return_repair(test_database_engine)
    source = workbook(12)
    invalid_book = load_workbook(BytesIO(source))
    invalid_book["Sheet1"]["B2"] = "不存在的工厂"
    invalid_output = BytesIO()
    invalid_book.save(invalid_output)
    monkeypatch.setenv("ORDER_TRACKING_APP_ENV", "local_demo")
    monkeypatch.setenv("ORDER_TRACKING_MCP_FILE_HOSTS", "files.example.test")
    monkeypatch.setattr(
        "app.mcp.repairs.fetch_file",
        lambda file, _hosts: source if file.file_id == "file-1" else invalid_output.getvalue(),
    )
    with _client(test_database_engine, test_database_url, monkeypatch) as client:
        _login(client)
        token = _exchange(client, _code(client)).json()["access_token"]
        upload = _call(client, token, "upload_repair_workbook", {
            "files": [{
                "download_url": "https://files.example.test/input.xlsx",
                "file_id": "file-1",
                "file_name": "input.xlsx",
                "mime_type": XLSX_MIME,
            }, {
                "download_url": "https://files.example.test/invalid.xlsx",
                "file_id": "file-2",
                "file_name": "invalid.xlsx",
                "mime_type": XLSX_MIME,
            }],
        })["structuredContent"]
        assert upload["canConfirmAll"] is False
        assert upload["items"][1]["status"] == "INVALID"
        preview_id = upload["items"][0]["previewId"]
        items = [
            {"previewId": preview_id, "idempotencyKey": "repair-mcp-1"},
            {"previewId": upload["items"][1]["previewId"], "idempotencyKey": "repair-mcp-2"},
        ]
        stopped = _call(client, token, "confirm_repair_previews", {
            "items": items,
        }, call_id=3)["structuredContent"]
        assert [item["status"] for item in stopped["items"]] == [
            "NOT_ATTEMPTED", "INVALID",
        ]
        confirmed = _call(client, token, "confirm_repair_previews", {
            "items": items, "allow_partial": True,
        }, call_id=6)["structuredContent"]
        assert confirmed["items"][0]["status"] == "CREATED"
        assert confirmed["items"][1]["status"] == "INVALID"
        repair_id = confirmed["items"][0]["repairId"]
        repeated = _call(client, token, "confirm_repair_previews", {
            "items": [items[0]],
        }, call_id=7)["structuredContent"]
        assert repeated["items"][0]["repairId"] == repair_id
        period = _call(client, token, "get_repair", {"repair_id": repair_id}, call_id=4)
        assert period["structuredContent"]["warehouseReturnQuantity"] == 12
        file_id = period["structuredContent"]["attachments"][0]["fileId"]
        descriptor = _call(client, token, "get_repair_download", {
            "repair_id": repair_id, "file_id": file_id,
        }, call_id=5)["structuredContent"]
        assert descriptor["sizeBytes"] == len(source)
        assert descriptor["sha256"] == sha256(source).hexdigest()
        downloaded = client.get(descriptor["downloadUrl"])
        assert downloaded.status_code == 200
        assert downloaded.content == source
    factory_rows, total = RepairPeriodService(sessionmaker(test_database_engine)).page(
        factory_id="return-factory"
    )
    assert total == 1
    assert factory_rows[0]["warehouse_return_quantity"] == 12
    with sessionmaker(test_database_engine)() as session:
        assert session.scalar(select(func.count()).select_from(OutboxMessage).where(
            OutboxMessage.event_type == "repair.created"
        )) == 1
