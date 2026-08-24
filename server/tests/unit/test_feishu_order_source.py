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
    def __enter__(self) -> "_Client":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def post(self, _path: str, **_kwargs: object) -> _Response:
        return _Response({"code": 0, "tenant_access_token": "test-token"})

    def get(self, path: str, **_kwargs: object) -> _Response:
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
    monkeypatch.setattr(order_source_module.httpx, "Client", lambda **_kwargs: _Client())
    source = AppCredentialFeishuOrderSource(
        FeishuOrderSourceConfig(
            app_id="test-app",
            app_secret="test-secret",
            app_token="test-base",
            table_id="test-table",
            view_id="test-view",
        )
    )

    pages = list(source.read_pages())

    assert pages[0][0].order_no == "E100"
    assert pages[0][0].product_name == "儿童防晒帽"
