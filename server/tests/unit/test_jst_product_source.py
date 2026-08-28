import json
from datetime import datetime
from hashlib import md5
from pathlib import Path
from urllib.parse import parse_qs
from zoneinfo import ZoneInfo

import httpx

from app.adapters.private_files import FakePrivateFileStore
from app.adapters.product import (
    AppCredentialJstProductSource,
    JstProductSourceConfig,
    PrivateProductImageStore,
)


def _expected_sign(form: dict[str, list[str]], app_secret: str) -> str:
    unsigned = {key: values[0] for key, values in form.items() if key != "sign"}
    source = app_secret + "".join(
        f"{key}{unsigned[key]}" for key in sorted(unsigned)
    )
    return md5(source.encode("utf-8"), usedforsecurity=False).hexdigest()


def test_jst_product_source_splits_sync_into_seven_day_windows(
    tmp_path: Path,
) -> None:
    requests: list[httpx.Request] = []
    business_requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        form = parse_qs(request.content.decode())
        assert form["sign"] == [_expected_sign(form, "app-secret")]
        if request.url.path == "/openWeb/auth/getInitToken":
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "access_token": "access-token",
                        "refresh_token": "refresh-token",
                        "expires_in": 2_592_000,
                    },
                },
            )

        business_requests.append(request)
        body = json.loads(form["biz"][0])
        if body["modified_begin"] == "2026-08-20 00:00:00":
            item = {
                "i_id": "ITEM-S12-001",
                "sku_id": "SKU-S12-001",
                "name": "测试产品甲",
                "properties_value": "蓝色 / 120",
                "pic": "https://img.example.test/product.jpg",
                "category": "童帽春夏",
                "enabled": 1,
                "modified": "2026-08-21 00:05:43",
            }
        else:
            item = {
                "i_id": "ITEM-S12-002",
                "sku_id": "SKU-S12-002",
                "name": "测试产品乙",
                "properties_value": "红色 / 130",
                "pic": None,
                "category": "童帽秋冬",
                "enabled": -1,
                "modified": "2026-08-27 12:00:00",
            }
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "datas": [item],
                    "page_index": 1,
                    "page_count": 1,
                    "has_next": False,
                },
            },
        )

    source = AppCredentialJstProductSource(
        JstProductSourceConfig(
            app_key="app-key",
            app_secret="app-secret",
            initial_sync_begin=datetime(
                2026, 8, 20, tzinfo=ZoneInfo("Asia/Shanghai")
            ),
            token_cache_path=tmp_path / "jst-token.json",
        ),
        transport=httpx.MockTransport(respond),
        clock=lambda: datetime(2026, 8, 28, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    first = source.fetch_initial_page(page_number=1)
    second = source.fetch_initial_page(page_number=2)

    assert first.has_next is True
    assert first.candidate_cursor == "2026-08-28T00:00:00+08:00"
    assert first.items[0].sku_id == "SKU-S12-001"
    assert first.items[0].category == "童帽春夏"
    assert first.items[0].enabled == 1
    assert second.has_next is False
    assert second.items[0].category == "童帽秋冬"
    assert second.items[0].enabled == -1
    assert [request.url.path for request in requests] == [
        "/openWeb/auth/getInitToken",
        "/open/sku/query",
        "/open/sku/query",
    ]
    assert [
        json.loads(parse_qs(request.content.decode())["biz"][0])
        for request in business_requests
    ] == [
        {
            "page_index": 1,
            "page_size": 50,
            "modified_begin": "2026-08-20 00:00:00",
            "modified_end": "2026-08-27 00:00:00",
        },
        {
            "page_index": 1,
            "page_size": 50,
            "modified_begin": "2026-08-27 00:00:00",
            "modified_end": "2026-08-28 00:00:00",
        },
    ]
    assert all(
        str(request.url) == "https://openapi.jushuitan.com/open/sku/query"
        for request in business_requests
    )
    assert all(
        request.headers["content-type"].startswith(
            "application/x-www-form-urlencoded"
        )
        for request in requests
    )
    forms = [parse_qs(request.content.decode()) for request in business_requests]
    assert all(form["app_key"] == ["app-key"] for form in forms)
    assert all(form["access_token"] == ["access-token"] for form in forms)
    assert all(form["version"] == ["2"] for form in forms)
    assert all(form["charset"] == ["utf-8"] for form in forms)
    assert all(len(form["sign"][0]) == 32 for form in forms)
    cached = json.loads((tmp_path / "jst-token.json").read_text(encoding="utf-8"))
    assert cached["app_key"] == "app-key"
    assert cached["access_token"] == "access-token"
    assert cached["refresh_token"] == "refresh-token"


def test_jst_product_source_refreshes_rejected_access_token(tmp_path: Path) -> None:
    paths: list[str] = []
    business_tokens: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        form = parse_qs(request.content.decode())
        if request.url.path == "/openWeb/auth/getInitToken":
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "access_token": "stale-access",
                        "refresh_token": "stale-refresh",
                        "expires_in": 2_592_000,
                    },
                },
            )
        if request.url.path == "/openWeb/auth/refreshToken":
            assert form["refresh_token"] == ["stale-refresh"]
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "access_token": "fresh-access",
                        "refresh_token": "fresh-refresh",
                        "expires_in": 2_592_000,
                    },
                },
            )

        business_tokens.append(form["access_token"][0])
        if form["access_token"] == ["stale-access"]:
            return httpx.Response(200, json={"code": 100, "msg": "expired"})
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "datas": [],
                    "page_count": 1,
                },
            },
        )

    source = AppCredentialJstProductSource(
        JstProductSourceConfig(
            app_key="app-key",
            app_secret="app-secret",
            initial_sync_begin=datetime(
                2026, 8, 27, tzinfo=ZoneInfo("Asia/Shanghai")
            ),
            token_cache_path=tmp_path / "jst-token.json",
        ),
        transport=httpx.MockTransport(respond),
        clock=lambda: datetime(2026, 8, 28, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    page = source.fetch_initial_page(page_number=1)

    assert page.items == ()
    assert business_tokens == ["stale-access", "fresh-access"]
    assert paths == [
        "/openWeb/auth/getInitToken",
        "/open/sku/query",
        "/openWeb/auth/refreshToken",
        "/open/sku/query",
    ]


def test_product_image_store_caches_public_https_image_in_private_storage() -> None:
    private_files = FakePrivateFileStore(bucket="shared-test-private")

    def respond(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://img.example.test/product.jpg"
        return httpx.Response(
            200,
            headers={"content-type": "image/jpeg"},
            content=b"safe-image-bytes",
        )

    store = PrivateProductImageStore(
        private_files,
        transport=httpx.MockTransport(respond),
        url_validator=lambda _url: True,
    )

    cached = store.cache(
        source_ref="https://img.example.test/product.jpg",
        object_key="products/sku-1/source.jpg",
    )

    assert cached.object_key == "products/sku-1/source.jpg"
    assert private_files.get(object_key=cached.object_key) == b"safe-image-bytes"
