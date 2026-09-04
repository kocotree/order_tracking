from datetime import datetime
from typing import Any

import app.adapters.order_source as order_source_module
from app.adapters.order_source import (
    AppCredentialFeishuOrderSource,
    FeishuOrderSourceConfig,
)


class _Response:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._payload


class _Client:
    requests: list[tuple[str, dict[str, object]]]

    def __init__(self) -> None:
        self.requests = []

    def __enter__(self) -> "_Client":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def post(self, _path: str, **_kwargs: object) -> _Response:
        return _Response({"code": 0, "tenant_access_token": "test-token"})

    def get(self, path: str, **_kwargs: object) -> _Response:
        self.requests.append((path, _kwargs))
        if path.endswith("/fields"):
            field_types = {
                "订单编号": 1,
                "商品名称": 3,
                "产品颜色&规格": 1,
                "工厂": 4,
                "下单数": 2,
                "跟单人员": 4,
                "下单时间": 5,
                "生产计划出货时间（提前或者推迟 的时间）": 5,
                "出货总数": 20,
                "未出数量": 20,
                "产品编码": 2,
                "一级分类": 20,
                "更新时间": 1002,
            }
            return _Response(
                {
                    "code": 0,
                    "data": {
                        "items": [
                            {"field_name": name, "type": field_type}
                            for name, field_type in field_types.items()
                        ]
                    },
                }
            )
        return _Response(
            {
                "code": 0,
                "data": {
                    "items": [
                        {
                            "record_id": "rec-test",
                            "last_modified_time": 1788486123000,
                            "fields": {
                                "订单编号": "E100",
                                "商品名称": "儿童防晒帽",
                            },
                        }
                    ],
                    "has_more": False,
                },
            }
        )


def test_feishu_order_source_accepts_single_select_product_name(monkeypatch: Any) -> None:
    client = _Client()
    monkeypatch.setattr(order_source_module.httpx, "Client", lambda **_kwargs: client)
    source = AppCredentialFeishuOrderSource(
        FeishuOrderSourceConfig(
            app_id="test-app",
            app_secret="test-secret",
            app_token="test-base",
            table_id="test-table",
            view_id="test-view",
            incremental_table_scope_confirmed=True,
        )
    )

    pages = list(source.read_pages())

    assert pages[0][0].order_no == "E100"
    assert pages[0][0].product_name == "儿童防晒帽"
    assert pages[0][0].source_modified_at == datetime(2026, 9, 4, 1, 42, 3)
    record_request = next(item for item in client.requests if item[0].endswith("/records"))
    assert record_request[1]["params"] == {
        "view_id": "test-view",
        "page_size": 500,
        "automatic_fields": "true",
    }


def test_feishu_order_source_rejects_incremental_table_read_without_scope_confirmation(
    monkeypatch: Any,
) -> None:
    client = _Client()
    monkeypatch.setattr(order_source_module.httpx, "Client", lambda **_kwargs: client)
    source = AppCredentialFeishuOrderSource(
        FeishuOrderSourceConfig(
            app_id="test-app",
            app_secret="test-secret",
            app_token="test-base",
            table_id="test-table",
            view_id="test-view",
        )
    )

    try:
        list(source.read_pages(modified_since=datetime(2026, 9, 4, 1, 0)))
    except Exception as error:
        assert str(error) == "feishu_order_incremental_scope_not_confirmed"
    else:
        raise AssertionError("incremental table reads require an explicit scope confirmation")


def test_feishu_order_source_uses_safe_modified_day_overlap(monkeypatch: Any) -> None:
    client = _Client()
    monkeypatch.setattr(order_source_module.httpx, "Client", lambda **_kwargs: client)
    source = AppCredentialFeishuOrderSource(
        FeishuOrderSourceConfig(
            app_id="test-app",
            app_secret="test-secret",
            app_token="test-base",
            table_id="test-table",
            view_id="test-view",
            incremental_table_scope_confirmed=True,
        )
    )

    list(source.read_pages(modified_since=datetime(2026, 9, 4, 1, 30)))

    record_request = next(item for item in client.requests if item[0].endswith("/records"))
    assert record_request[1]["params"] == {
        "filter": 'CurrentValue.[更新时间] >= TODATE("2026-09-04")',
        "page_size": 500,
        "automatic_fields": "true",
    }
