import json
from io import StringIO

from fastapi import APIRouter
from fastapi.testclient import TestClient

from app.logging import StructuredLogger
from app.main import create_app


def test_liveness_returns_status_and_request_id() -> None:
    stream = StringIO()
    with TestClient(create_app(event_logger=StructuredLogger(stream=stream))) as client:
        response = client.get("/health/live")

    assert response.status_code == 200
    payload = response.json()
    assert payload == {"status": "ok", "requestId": payload["requestId"]}
    assert payload["requestId"]
    assert response.headers["X-Request-ID"] == payload["requestId"]
    log_entry = json.loads(stream.getvalue())
    assert log_entry["event"] == "request.completed"
    assert log_entry["requestId"] == payload["requestId"]


def test_unhandled_error_uses_safe_response_with_request_id() -> None:
    router = APIRouter()

    @router.get("/boom")
    def boom() -> None:
        raise RuntimeError("database password=should-not-leak")

    with TestClient(create_app(extra_routers=[router]), raise_server_exceptions=False) as client:
        response = client.get("/boom")

    assert response.status_code == 500
    payload = response.json()
    assert payload == {
        "code": "internal_error",
        "message": "服务器内部错误",
        "requestId": payload["requestId"],
    }
    assert response.headers["X-Request-ID"] == payload["requestId"]
    assert "password" not in response.text
    assert "should-not-leak" not in response.text


def test_unknown_route_uses_unified_not_found_response() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/missing")

    assert response.status_code == 404
    payload = response.json()
    assert payload == {
        "code": "not_found",
        "message": "资源不存在",
        "requestId": payload["requestId"],
    }
    assert response.headers["X-Request-ID"] == payload["requestId"]


def test_readiness_succeeds_when_mysql_is_available(test_database_url: str) -> None:
    with TestClient(create_app(database_url=test_database_url)) as client:
        response = client.get("/health/ready")

    assert response.status_code == 200
    payload = response.json()
    assert payload == {"status": "ready", "requestId": payload["requestId"]}


def test_readiness_fails_clearly_when_mysql_is_unavailable() -> None:
    unavailable_url = "mysql+pymysql://unavailable:unavailable@127.0.0.1:3399/unavailable"
    with TestClient(create_app(database_url=unavailable_url)) as client:
        response = client.get("/health/ready")

    assert response.status_code == 503
    payload = response.json()
    assert payload == {
        "code": "service_unavailable",
        "message": "数据库暂不可用",
        "requestId": payload["requestId"],
    }
    assert "127.0.0.1" not in response.text
    assert "3399" not in response.text
