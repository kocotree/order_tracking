import base64
import hashlib
import json
from datetime import UTC, datetime

import httpx
import pytest
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.adapters.notifications import (
    AppCredentialFeishuBusinessNotifier,
    AppCredentialFeishuSender,
    DeliveryRequest,
    FeishuNotificationConfig,
)
from app.api.feishu_bot import create_feishu_bot_router
from app.modules.incoming_differences.bot import FeishuBotService, FeishuCallbackVerifier

NOW = datetime(2026, 9, 24, tzinfo=UTC)
KEY = "local-test-encrypt-key"


def _callback(
    payload: dict[str, object], *, timestamp: str = "1790208000"
) -> tuple[dict[str, str], bytes]:
    raw = json.dumps(payload, ensure_ascii=False).encode()
    headers = {
        "x-lark-request-timestamp": timestamp,
        "x-lark-request-nonce": "nonce-1",
        "x-lark-signature": hashlib.sha256(
            (timestamp + "nonce-1" + KEY).encode() + raw
        ).hexdigest(),
    }
    return headers, raw


def test_signed_encrypted_challenge_and_rejections() -> None:
    verifier = FeishuCallbackVerifier(KEY, "local-test-token", now=lambda: NOW)
    plaintext = json.dumps({"type": "url_verification", "challenge": "abc",
                            "token": "local-test-token"}).encode()
    padding = 16 - len(plaintext) % 16
    encryptor = Cipher(
        algorithms.AES(hashlib.sha256(KEY.encode()).digest()), modes.CBC(b"0" * 16)
    ).encryptor()
    encrypted = base64.b64encode(
        b"0" * 16 + encryptor.update(plaintext + bytes([padding]) * padding)
        + encryptor.finalize()
    ).decode()
    headers, body = _callback({"encrypt": encrypted})
    assert verifier.verify(headers, body)["challenge"] == "abc"
    with pytest.raises(ValueError, match="token"):
        FeishuCallbackVerifier(KEY, "wrong-token", now=lambda: NOW).verify(headers, body)

    with pytest.raises(ValueError, match="signature"):
        verifier.verify({**headers, "x-lark-signature": "0" * 64}, body)
    with pytest.raises(ValueError, match="timestamp"):
        old_headers, old_body = _callback({"encrypt": encrypted}, timestamp="1")
        verifier.verify(old_headers, old_body)
    bad_headers, bad_body = _callback({"encrypt": "invalid"})
    with pytest.raises(ValueError, match="decrypt"):
        verifier.verify(bad_headers, bad_body)


def test_callback_routes_are_disabled_by_default() -> None:
    app = FastAPI()
    app.include_router(create_feishu_bot_router(service=None, verifier=None))
    client = TestClient(app)
    for path in ("events", "card-actions"):
        response = client.post(f"/api/v1/integrations/feishu/{path}", json={})
        assert response.status_code == 503
        assert response.json() == {"code": "feishu_bot_disabled"}


def test_callback_route_rejects_bad_signature_before_service() -> None:
    class Stub:
        def event(self, payload: dict[str, object]) -> dict[str, object]:
            return {"challenge": payload["challenge"]}

        def card_action(self, payload: dict[str, object]) -> dict[str, object]:
            return {}

    app = FastAPI()
    app.include_router(create_feishu_bot_router(
        service=Stub(), verifier=FeishuCallbackVerifier(KEY, "token", now=lambda: NOW)
    ))
    client = TestClient(app)
    headers, body = _callback({"encrypt": "invalid"})
    assert client.post("/api/v1/integrations/feishu/events", headers=headers,
                       content=body).status_code == 401


def test_failed_handler_releases_event_for_feishu_retry() -> None:
    class Verifier:
        def verify(self, headers: dict[str, str], body: bytes) -> dict[str, object]:
            return {"header": {"event_id": "event-1"}}

    class Stub:
        def __init__(self) -> None:
            self.attempts = 0
            self.released = 0

        def event(self, payload: dict[str, object]) -> dict[str, object]:
            self.attempts += 1
            if self.attempts == 1:
                raise RuntimeError("temporary")
            return {}

        def release_failed_event(self, payload: dict[str, object]) -> None:
            self.released += 1

    stub = Stub()
    app = FastAPI()
    app.include_router(create_feishu_bot_router(service=stub, verifier=Verifier()))
    client = TestClient(app, raise_server_exceptions=False)
    assert client.post("/api/v1/integrations/feishu/events").status_code == 500
    assert stub.released == 1
    assert client.post("/api/v1/integrations/feishu/events").status_code == 200


def test_user_uploaded_workbook_uses_message_resource_endpoint() -> None:
    requested: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("tenant_access_token/internal"):
            return httpx.Response(200, json={"code": 0,
                                             "tenant_access_token": "fake-token",
                                             "expire": 7200})
        requested.append(str(request.url))
        assert request.headers["Authorization"] == "Bearer fake-token"
        return httpx.Response(200, content=b"workbook-bytes")

    config = FeishuNotificationConfig(
        app_id="fake-app", app_secret="fake-secret", admin_web_base_url="",
        ops_alert_recipient_user_id="",
    )
    media = AppCredentialFeishuSender(
        config, sessionmaker(), transport=httpx.MockTransport(respond)
    )
    assert media.download_resource("msg-1", "file-1", "file") == b"workbook-bytes"
    assert requested == [
        "https://open.feishu.cn/open-apis/im/v1/messages/msg-1/"
        "resources/file-1?type=file"
    ]


def test_bot_card_uses_v2_callback_button_structure() -> None:
    sent: list[dict[str, object]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("tenant_access_token/internal"):
            return httpx.Response(200, json={"code": 0,
                                             "tenant_access_token": "fake-token",
                                             "expire": 7200})
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={"code": 0})

    notifier = AppCredentialFeishuBusinessNotifier(
        FeishuNotificationConfig(app_id="fake-app", app_secret="fake-secret",
                                 admin_web_base_url="", ops_alert_recipient_user_id=""),
        sessionmaker(), transport=httpx.MockTransport(respond),
    )
    notifier.send(DeliveryRequest(
        delivery_id=1, recipient_id="admin", recipient_open_id="open-1",
        channel="feishu", template_key="incoming_diff_bot", title="来货出入",
        summary="请确认", target_type="incoming_diff_batch", target_id="batch-1",
        target_path="", template_data={}, buttons=({"text": "确认登记",
            "action": "confirm", "value": {"batchId": "batch-1", "version": 1}},),
    ))
    assert sent[0]["msg_type"] == "interactive"
    card = json.loads(sent[0]["content"])
    button = card["body"]["elements"][1]["columns"][0]["elements"][0]
    assert card["schema"] == "2.0"
    assert button["behaviors"] == [{"type": "callback", "value": {
        "action": "confirm", "batchId": "batch-1", "version": 1,
    }}]


def test_workbook_missing_field_reply_names_the_field() -> None:
    assert FeishuBotService._workbook_errors("IN20260924-01", [
        {"code": "required_field", "sheet": "工厂A", "row": 3,
         "message": "名称和规格不能为空", "field": "规格"},
    ]) == "工厂A 第 3 行缺少 规格，已标记待确认。系统不会替你猜测，请补全后重新发送。"
