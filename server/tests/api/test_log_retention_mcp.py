from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.db.models import AuditLog
from tests.api.test_agent_oauth import _client, _code, _exchange, _login
from tests.api.test_agent_repair_mcp import _call
from tests.api.test_shipment_api import ORDER_ID, _seed


def test_web_and_mcp_share_log_window(test_database_engine, test_database_url, monkeypatch):
    now = datetime(2026, 10, 10, 12)
    monkeypatch.setattr("app.modules.log_retention.utc_now", lambda: now)
    _seed(test_database_engine)
    with Session(test_database_engine) as session, session.begin():
        for number, when in enumerate((now - timedelta(days=31), now - timedelta(days=30), now)):
            session.add(AuditLog(request_id=str(number), action=f"test-{number}",
                                 target_type="order", target_id=ORDER_ID, changes={},
                                 created_at=when))
    with _client(test_database_engine, test_database_url, monkeypatch) as client:
        _login(client)
        token = _exchange(client, _code(client)).json()["access_token"]
        web = client.get(f"/api/v1/admin/orders/{ORDER_ID}/audit-logs")
        assert web.status_code == 200
        agent = _call(client, token, "get_order_audit", {"order_id": ORDER_ID})
        assert agent["structuredContent"]["total"] == web.json()["total"] == 2
        assert agent["structuredContent"]["items"] == web.json()["items"]
