from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from app.adapters.identity import (
    AppCredentialFeishuIdentity,
    ExternalIdentityUnavailable,
    FeishuIdentityConfig,
)


def test_feishu_identity_builds_authorization_url_with_registered_callback() -> None:
    adapter = AppCredentialFeishuIdentity(
        FeishuIdentityConfig(
            app_id="cli_test_app",
            app_secret="test-secret",
            redirect_uri="http://127.0.0.1:5175/api/v1/auth/feishu/callback",
        )
    )

    parsed = urlparse(adapter.authorization_url(state="state-123"))

    assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == (
        "https://accounts.feishu.cn/open-apis/authen/v1/authorize"
    )
    assert parse_qs(parsed.query) == {
        "client_id": ["cli_test_app"],
        "response_type": ["code"],
        "scope": ["contact:user.phone:readonly"],
        "redirect_uri": [
            "http://127.0.0.1:5175/api/v1/auth/feishu/callback"
        ],
        "state": ["state-123"],
    }


def test_feishu_identity_exchanges_code_and_returns_scoped_profile() -> None:
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url == httpx.URL("https://accounts.feishu.cn/oauth/v3/token"):
            assert request.method == "POST"
            assert request.headers["content-type"].startswith("application/json")
            assert request.content == (
                b'{"grant_type":"authorization_code","client_id":"cli_test_app",'
                b'"client_secret":"test-secret","code":"one-time-code",'
                b'"redirect_uri":"http://127.0.0.1:5175/api/v1/auth/feishu/callback"}'
            )
            return httpx.Response(
                200,
                json={"code": 0, "access_token": "user-access-token"},
            )
        assert request.url == httpx.URL(
            "https://open.feishu.cn/open-apis/authen/v1/user_info"
        )
        assert request.method == "GET"
        assert request.headers["authorization"] == "Bearer user-access-token"
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "open_id": "ou_test_user",
                    "tenant_key": "tenant_test",
                    "name": "测试用户",
                    "avatar_url": "https://example.invalid/avatar.png",
                    "mobile": "+86 138-1234-5122",
                },
            },
        )

    adapter = AppCredentialFeishuIdentity(
        FeishuIdentityConfig(
            app_id="cli_test_app",
            app_secret="test-secret",
            redirect_uri="http://127.0.0.1:5175/api/v1/auth/feishu/callback",
        ),
        transport=httpx.MockTransport(respond),
    )

    profile = adapter.exchange_code(code="one-time-code")

    assert profile.subject == "tenant_test:ou_test_user"
    assert profile.display_name == "测试用户"
    assert profile.avatar_url == "https://example.invalid/avatar.png"
    assert profile.phone == "13812345122"
    assert adapter.scope.startswith("feishu-app/")
    assert len(requests) == 2


def test_feishu_identity_hides_upstream_credentials_when_exchange_fails() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={"code": 20002, "error_description": "test-secret is invalid"},
            request=request,
        )

    adapter = AppCredentialFeishuIdentity(
        FeishuIdentityConfig(
            app_id="cli_test_app",
            app_secret="test-secret",
            redirect_uri="http://127.0.0.1:5175/api/v1/auth/feishu/callback",
        ),
        transport=httpx.MockTransport(respond),
    )

    with pytest.raises(
        ExternalIdentityUnavailable,
        match="^feishu identity is unavailable$",
    ):
        adapter.exchange_code(code="one-time-code")


def test_feishu_identity_rejects_profile_without_verified_phone() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        if request.url == httpx.URL("https://accounts.feishu.cn/oauth/v3/token"):
            return httpx.Response(200, json={"code": 0, "access_token": "token"})
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "open_id": "ou_test_user",
                    "tenant_key": "tenant_test",
                    "name": "测试用户",
                },
            },
        )

    adapter = AppCredentialFeishuIdentity(
        FeishuIdentityConfig(
            app_id="cli_test_app",
            app_secret="test-secret",
            redirect_uri="http://127.0.0.1:5175/api/v1/auth/feishu/callback",
        ),
        transport=httpx.MockTransport(respond),
    )

    with pytest.raises(
        ExternalIdentityUnavailable,
        match="^feishu identity is unavailable$",
    ):
        adapter.exchange_code(code="one-time-code")
