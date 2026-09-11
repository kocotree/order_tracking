from datetime import datetime
from typing import Any

import pytest

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
                "合同出货时间": 20,
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


@pytest.mark.parametrize(
    "value, expected",
    [
        ({"type": 5, "value": [1798646400000]}, "2026-12-31"),
        ([{"text": "2026-12-31 00:00"}], "2026-12-31"),
        ("2026-12-30T16:00:00Z", "2026-12-31"),
        ({"value": ["2026-09-01", "2026-09-04"]}, None),
        ("2026-09-01、2026-09-04", None),
        ("2026-09-01,2026-09-04", None),
        (None, None),
        (True, None),
        ("invalid", None),
    ],
)
def test_source_reads_contract_formula_without_plan_date(
    monkeypatch: Any, value: Any, expected: str | None
) -> None:
    from datetime import date

    client = _Client()
    original_get = client.get

    def get(path: str, **kwargs: object) -> _Response:
        response = original_get(path, **kwargs)
        if path.endswith("/records"):
            response.json()["data"]["items"][0]["fields"].update(
                {
                    "合同出货时间": value,
                    "生产计划出货时间（提前或者推迟 的时间）": None,
                }
            )
        return response

    client.get = get
    monkeypatch.setattr(order_source_module.httpx, "Client", lambda **_kwargs: client)
    source = AppCredentialFeishuOrderSource(
        FeishuOrderSourceConfig(
            app_id="test", app_secret="test", app_token="test", table_id="test", view_id="test"
        )
    )
    row = list(source.read_pages())[0][0]
    assert row.contract_ship_date == (date.fromisoformat(expected) if expected else None)
    assert "合同出货时间" in row.raw_fields


@pytest.mark.parametrize(
    "raw", [None, "", "错误", "1.5", True, "Infinity", "NaN", "2147483648", ["1", "2"]]
)
def test_invalid_source_quantities_remain_unknown(raw: object) -> None:
    row = AppCredentialFeishuOrderSource._parse_record(
        {
            "record_id": "raw-quantity",
            "last_modified_time": 1788486123000,
            "fields": {"订单编号": "RAW", "下单数": raw, "出货总数": raw, "未出数量": raw},
        }
    )
    assert row.order_quantity is None
    assert row.shipped_quantity is None
    assert row.pending_quantity is None
    assert row.raw_fields["出货总数"] == raw


@pytest.mark.parametrize("raw", [True, "invalid", "Infinity", 10**30])
def test_invalid_order_date_does_not_abort_source_read(raw: object) -> None:
    row = AppCredentialFeishuOrderSource._parse_record(
        {
            "record_id": "raw-date",
            "last_modified_time": 1788486123000,
            "fields": {"订单编号": "RAW", "下单时间": raw},
        }
    )
    assert row.order_date is None
    assert row.raw_fields["下单时间"] == raw
