from typing import Any

import pytest

from app.adapters.errors import ExternalAdapterUnavailable
from app.adapters.order_source import AppCredentialFeishuOrderSource, FeishuOrderSourceConfig
from app.adapters.product import ProductSourceError, SourcePurchaseItem


class PurchaseSource:
    requested: list[str]

    def fetch_purchase_items(self, po_ids: list[str]) -> list[SourcePurchaseItem]:
        self.requested = po_ids
        return [
            SourcePurchaseItem("1596185", "manual-child", "SKU-1", 550, 0, None),
            SourcePurchaseItem("1596185", "mapped-child", "SKU-2", 650, 419, 7),
        ]


class FailingPurchaseSource:
    def fetch_purchase_items(self, _po_ids: list[str]) -> list[SourcePurchaseItem]:
        raise ProductSourceError("unavailable")


class Response:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self.payload


class Client:
    requests: list[dict[str, object]]

    def __init__(self) -> None:
        self.requests = []

    def post(self, _path: str, **_kwargs: object) -> Response:
        self.requests.append(_kwargs)
        return Response({
            "code": 0,
            "data": {
                "items": [
                    {"fields": {"采购子订单号": "manual-child", "采购主订单号": "1596185"}},
                    {"fields": {"采购子订单号": "mapped-child", "采购主订单号": "1596185"}},
                ],
                "has_more": False,
            },
        })


def row(record_id: str, sku: str, fields: dict[str, object]):
    return AppCredentialFeishuOrderSource._parse_record({
        "record_id": record_id,
        "last_modified_time": 1788486123000,
        "fields": {
            "订单编号": "438#",
            "产品编码": sku,
            "下单数": 650 if sku == "SKU-2" else 550,
            **fields,
        },
    })


def test_purchase_quantity_uses_manual_then_mapping_and_deduplicates_main_order() -> None:
    purchase = PurchaseSource()
    source = AppCredentialFeishuOrderSource(
        FeishuOrderSourceConfig(
            app_id="app", app_secret="secret", app_token="base",
            table_id="orders", view_id="view", purchase_detail_table_id="purchases",
        ),
        purchase,
    )
    rows = [
        row("one", "SKU-1", {
            "采购子订单号-映射": "wrong-child",
            "采购子订单号-人工确认": "manual-child",
        }),
        row("two", "SKU-2", {"采购子订单号-映射": "mapped-child", "下单数": 999}),
    ]

    client = Client()
    actual = source._enrich_purchase_quantities(client, {}, rows)  # type: ignore[arg-type]

    assert purchase.requested == ["1596185"]
    assert client.requests[0]["params"] == {"page_size": 500}
    assert [
        (item.order_quantity, item.shipped_quantity, item.pending_quantity)
        for item in actual
    ] == [
        (550, 0, 550),
        (650, 419, 231),
    ]
    assert actual[1].raw_fields["_purchase"]["childOrderId"] == "mapped-child"  # type: ignore[index]


def test_empty_purchase_number_defaults_to_unshipped_without_external_query() -> None:
    source = AppCredentialFeishuOrderSource(
        FeishuOrderSourceConfig(
            app_id="app", app_secret="secret", app_token="base",
            table_id="orders", view_id="view",
        )
    )

    actual = source._enrich_purchase_quantities(Client(), {}, [row("one", "SKU-1", {})])  # type: ignore[arg-type]

    assert actual[0].shipped_quantity == 0
    assert actual[0].pending_quantity == 550


def test_purchase_api_failure_aborts_refresh_instead_of_replacing_saved_quantity() -> None:
    source = AppCredentialFeishuOrderSource(
        FeishuOrderSourceConfig(
            app_id="app", app_secret="secret", app_token="base",
            table_id="orders", view_id="view", purchase_detail_table_id="purchases",
        ),
        FailingPurchaseSource(),
    )

    with pytest.raises(ExternalAdapterUnavailable, match="jst_purchase_source_unavailable"):
        source._enrich_purchase_quantities(  # type: ignore[arg-type]
            Client(), {}, [row("one", "SKU-1", {"采购子订单号-映射": "mapped-child"})]
        )
