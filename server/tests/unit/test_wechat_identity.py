from urllib.parse import parse_qs

import httpx
import pytest

from app.adapters.wechat import (
    AppCredentialWechatIdentity,
    WechatIdentityConfig,
    WechatUnavailable,
)


def test_wechat_identity_exchanges_login_code_for_scoped_openid() -> None:
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.method == "GET"
        assert request.url.copy_with(query=None) == httpx.URL(
            "https://api.weixin.qq.com/sns/jscode2session"
        )
        assert parse_qs(request.url.query.decode()) == {
            "appid": ["wx-test-app"],
            "secret": ["test-app-secret"],
            "js_code": ["one-time-login-code"],
            "grant_type": ["authorization_code"],
        }
        return httpx.Response(
            200,
            json={
                "openid": "openid-for-current-wechat-user",
                "session_key": "server-only-session-key",
            },
        )

    adapter = AppCredentialWechatIdentity(
        WechatIdentityConfig(app_id="wx-test-app", app_secret="test-app-secret"),
        transport=httpx.MockTransport(respond),
    )

    profile = adapter.exchange_login_code(code="one-time-login-code")

    assert profile.subject == "openid-for-current-wechat-user"
    assert profile.avatar_url is None
    assert adapter.scope.startswith("wechat-app/")
    assert "wx-test-app" not in adapter.scope
    assert len(requests) == 1


def test_wechat_identity_exchanges_phone_code_with_server_access_token() -> None:
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.copy_with(query=None) == httpx.URL(
            "https://api.weixin.qq.com/cgi-bin/token"
        ):
            assert request.method == "GET"
            assert parse_qs(request.url.query.decode()) == {
                "grant_type": ["client_credential"],
                "appid": ["wx-test-app"],
                "secret": ["test-app-secret"],
            }
            return httpx.Response(
                200,
                json={"access_token": "server-access-token", "expires_in": 7200},
            )

        assert request.url == httpx.URL(
            "https://api.weixin.qq.com/wxa/business/getuserphonenumber"
            "?access_token=server-access-token"
        )
        assert request.method == "POST"
        assert request.content == b'{"code":"one-time-phone-code"}'
        return httpx.Response(
            200,
            json={
                "errcode": 0,
                "errmsg": "ok",
                "phone_info": {
                    "phoneNumber": "+86 138-1234-5122",
                    "purePhoneNumber": "13812345122",
                    "countryCode": "86",
                },
            },
        )

    adapter = AppCredentialWechatIdentity(
        WechatIdentityConfig(app_id="wx-test-app", app_secret="test-app-secret"),
        transport=httpx.MockTransport(respond),
    )

    assert adapter.exchange_phone_code(code="one-time-phone-code") == "13812345122"
    assert len(requests) == 2


def test_wechat_identity_reuses_unexpired_server_access_token() -> None:
    token_requests = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal token_requests
        if request.url.path == "/cgi-bin/token":
            token_requests += 1
            return httpx.Response(
                200,
                json={"access_token": "server-access-token", "expires_in": 7200},
            )
        return httpx.Response(
            200,
            json={
                "errcode": 0,
                "phone_info": {"purePhoneNumber": "13812345122"},
            },
        )

    adapter = AppCredentialWechatIdentity(
        WechatIdentityConfig(app_id="wx-test-app", app_secret="test-app-secret"),
        transport=httpx.MockTransport(respond),
    )

    assert adapter.exchange_phone_code(code="first-phone-code") == "13812345122"
    assert adapter.exchange_phone_code(code="second-phone-code") == "13812345122"
    assert token_requests == 1


def test_wechat_identity_hides_upstream_login_credentials_and_rejects_missing_session_key(
) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "openid": "openid-without-session-key",
                "errmsg": "test-app-secret one-time-login-code server-session-key",
            },
            request=request,
        )

    adapter = AppCredentialWechatIdentity(
        WechatIdentityConfig(app_id="wx-test-app", app_secret="test-app-secret"),
        transport=httpx.MockTransport(respond),
    )

    with pytest.raises(
        WechatUnavailable,
        match="^wechat identity is unavailable$",
    ) as captured:
        adapter.exchange_login_code(code="one-time-login-code")

    rendered = str(captured.value)
    assert "test-app-secret" not in rendered
    assert "one-time-login-code" not in rendered
    assert "server-session-key" not in rendered
