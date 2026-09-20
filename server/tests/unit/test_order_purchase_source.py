from typing import Any

import pytest

import app.adapters.order_source as order_source_module
from app.adapters.errors import ExternalAdapterUnavailable
from app.adapters.order_source import AppCredentialFeishuOrderSource, FeishuOrderSourceConfig
from app.adapters.product import ProductSourceError, SourcePurchaseItem

FIELD_TYPES = {
    "下单明细ID": 1005,
    "订单编号": 1,
    "商品名称": 3,
    "产品颜色&规格": 1,
    "工厂": 4,
    "下单数": 2,
    "跟单人员": 4,
    "下单时间": 5,
    "合同出货时间": 20,
    "采购子订单号-映射": 20,
    "采购子订单号-人工确认": 1,
    "采购单号": 20,
    "产品编码": 2,
    "一级分类": 20,
}
FIELD_IDS = {name: f"fld-{index}" for index, name in enumerate(FIELD_TYPES)}


class PurchaseSource:
    def __init__(self) -> None:
        self.requested: list[str] = []

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
    def __init__(
        self,
        records: dict[str, dict[str, object]],
        *,
        field_names: dict[str, str] | None = None,
        field_types: dict[str, int] | None = None,
    ) -> None:
        self.records = records
        self.field_names = field_names or {}
        self.field_types = field_types or FIELD_TYPES
        self.requests: list[tuple[str, str]] = []

    def __enter__(self) -> "Client":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def post(self, path: str, **_kwargs: object) -> Response:
        self.requests.append(("POST", path))
        if path != "/open-apis/auth/v3/tenant_access_token/internal":
            raise AssertionError(f"unexpected Feishu POST: {path}")
        return Response({"code": 0, "tenant_access_token": "test-token"})

    def get(self, path: str, **_kwargs: object) -> Response:
        self.requests.append(("GET", path))
        if path.endswith("/fields"):
            return Response({
                "code": 0,
                "data": {
                    "items": [
                        {
                            "field_id": FIELD_IDS[name],
                            "field_name": self.field_names.get(name, name),
                            "type": field_type,
                        }
                        for name, field_type in self.field_types.items()
                    ]
                    + [{"field_id": "fld-modified", "field_name": "更新时间", "type": 1002}]
                },
            })
        record_id = path.rsplit("/", 1)[-1]
        return Response({
            "code": 0,
            "data": {
                "record": {
                    "record_id": record_id,
                    "last_modified_time": 1788486123000,
                    "fields": self.records[record_id],
                }
            },
        })


def config() -> FeishuOrderSourceConfig:
    return FeishuOrderSourceConfig(
        app_id="app",
        app_secret="secret",
        app_token="base",
        table_id="orders",
        view_id="view",
        field_ids=FIELD_IDS,
    )


def test_purchase_quantity_uses_main_order_from_order_table_without_detail_query(
    monkeypatch: Any,
) -> None:
    purchase = PurchaseSource()
    client = Client({
        "one": {
            "订单编号": "438#",
            "产品编码": "SKU-1",
            "下单数": 999,
            "采购子订单号-映射": "wrong-child",
            "采购子订单号-人工确认": "manual-child",
            "采购单号": "1596185",
        },
        "two": {
            "订单编号": "438#",
            "产品编码": "SKU-2",
            "下单数": 999,
            "采购子订单号-映射": "mapped-child",
            "采购单号": [{"text": "1596185"}],
        },
    })
    monkeypatch.setattr(order_source_module.httpx, "Client", lambda **_kwargs: client)

    actual = AppCredentialFeishuOrderSource(config(), purchase).read_records(["one", "two"])

    assert purchase.requested == ["1596185"]
    assert all("records/search" not in path for _, path in client.requests)
    assert [
        (item.order_quantity, item.shipped_quantity, item.pending_quantity)
        for item in actual
    ] == [(550, 0, 550), (650, 419, 231)]
    assert actual[0].raw_fields["_purchase"]["childOrderId"] == "manual-child"


def test_saved_purchase_link_is_used_when_order_table_link_is_ambiguous(
    monkeypatch: Any,
) -> None:
    purchase = PurchaseSource()
    client = Client({
        "one": {
            "订单编号": "438#",
            "产品编码": "SKU-1",
            "下单数": 999,
            "采购子订单号-映射": ["old-child", "other-child"],
            "采购单号": [],
        }
    })
    monkeypatch.setattr(order_source_module.httpx, "Client", lambda **_kwargs: client)

    actual = AppCredentialFeishuOrderSource(config(), purchase).read_records(
        ["one"], purchase_links={"one": ("1596185", "manual-child")}
    )

    assert purchase.requested == ["1596185"]
    assert actual[0].order_quantity == 550
    assert actual[0].raw_fields["_purchase"]["childOrderId"] == "manual-child"


def test_empty_purchase_link_defaults_to_unshipped_without_purchase_query(
    monkeypatch: Any,
) -> None:
    purchase = PurchaseSource()
    client = Client({"one": {"订单编号": "438#", "产品编码": "SKU-1", "下单数": 550}})
    monkeypatch.setattr(order_source_module.httpx, "Client", lambda **_kwargs: client)

    actual = AppCredentialFeishuOrderSource(config(), purchase).read_records(["one"])

    assert purchase.requested == []
    assert actual[0].shipped_quantity == 0
    assert actual[0].pending_quantity == 550


def test_purchase_api_failure_aborts_refresh_instead_of_replacing_saved_quantity(
    monkeypatch: Any,
) -> None:
    client = Client({
        "one": {
            "订单编号": "438#",
            "产品编码": "SKU-1",
            "下单数": 550,
            "采购子订单号-映射": "mapped-child",
            "采购单号": "1596185",
        }
    })
    monkeypatch.setattr(order_source_module.httpx, "Client", lambda **_kwargs: client)

    with pytest.raises(ExternalAdapterUnavailable, match="jst_purchase_source_unavailable"):
        AppCredentialFeishuOrderSource(config(), FailingPurchaseSource()).read_records(["one"])


def test_field_ids_survive_order_field_renames(monkeypatch: Any) -> None:
    purchase = PurchaseSource()
    renamed = {"订单编号": "订单号-已改名", "采购单号": "采购单号-已改名"}
    client = Client(
        {
            "one": {
                "订单号-已改名": "438#",
                "产品编码": "SKU-1",
                "下单数": 550,
                "采购子订单号-人工确认": "manual-child",
                "采购单号-已改名": "1596185",
            }
        },
        field_names=renamed,
    )
    monkeypatch.setattr(order_source_module.httpx, "Client", lambda **_kwargs: client)

    actual = AppCredentialFeishuOrderSource(config(), purchase).read_records(["one"])

    assert actual[0].order_no == "438#"
    assert actual[0].raw_fields["采购单号"] == "1596185"


def test_field_id_type_drift_fails_before_reading_records(monkeypatch: Any) -> None:
    field_types = {**FIELD_TYPES, "采购单号": 5}
    client = Client({}, field_types=field_types)
    monkeypatch.setattr(order_source_module.httpx, "Client", lambda **_kwargs: client)

    with pytest.raises(ExternalAdapterUnavailable, match="feishu_order_field_contract_drift"):
        AppCredentialFeishuOrderSource(config(), PurchaseSource()).read_records(["one"])
