from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from typing import Any, Protocol
from urllib.parse import quote
from zoneinfo import ZoneInfo

import httpx

from app.adapters.errors import ExternalAdapterUnavailable
from app.adapters.product import JstPurchaseSource, ProductSourceError, SourcePurchaseItem
from app.modules.order_import import SourceOrderRow

BUSINESS_TZ = ZoneInfo("Asia/Shanghai")


class FeishuOrderSource(Protocol):
    @property
    def source_scope(self) -> str: ...

    def read_records(self, record_ids: list[str]) -> list[SourceOrderRow]: ...

    def read_pages(
        self, *, modified_since: datetime | None = None
    ) -> Iterable[list[SourceOrderRow]]: ...


class DisabledFeishuOrderSource:
    source_scope = "unconfigured-feishu-order-source"

    def read_records(self, record_ids: list[str]) -> list[SourceOrderRow]:
        raise ExternalAdapterUnavailable("feishu_order_source_not_configured")

    def read_pages(
        self, *, modified_since: datetime | None = None
    ) -> Iterable[list[SourceOrderRow]]:
        raise ExternalAdapterUnavailable("feishu_order_source_not_configured")


class FakeFeishuOrderSource:
    def __init__(
        self, pages: list[list[SourceOrderRow]], *, fail_on_page: int | None = None
    ) -> None:
        self._pages = pages
        self._fail_on_page = fail_on_page
        self.source_scope = "fake-feishu-order-source"
        self.modified_since_requests: list[datetime | None] = []

    def read_records(self, record_ids: list[str]) -> list[SourceOrderRow]:
        return [row for page in self.read_pages() for row in page if row.record_id in record_ids]

    def read_pages(
        self, *, modified_since: datetime | None = None
    ) -> Iterable[list[SourceOrderRow]]:
        self.modified_since_requests.append(modified_since)
        for page_number, page in enumerate(self._pages, start=1):
            if page_number == self._fail_on_page:
                raise ExternalAdapterUnavailable("fake_feishu_page_failed")
            yield page


@dataclass(frozen=True)
class FeishuOrderSourceConfig:
    app_id: str
    app_secret: str
    app_token: str
    table_id: str
    view_id: str
    purchase_detail_table_id: str = ""
    incremental_table_scope_confirmed: bool = False
    base_url: str = "https://open.feishu.cn"


class AppCredentialFeishuOrderSource:
    """Read the configured Base view with tenant app credentials only."""

    def __init__(
        self, config: FeishuOrderSourceConfig, purchase_source: JstPurchaseSource | None = None
    ) -> None:
        self._config = config
        self._purchase_source = purchase_source
        scope = f"{config.app_token}:{config.table_id}:{config.view_id}".encode()
        self.source_scope = f"feishu:{sha256(scope).hexdigest()[:32]}"

    def read_records(self, record_ids: list[str]) -> list[SourceOrderRow]:
        try:
            with httpx.Client(base_url=self._config.base_url, timeout=30) as client:
                response = client.post(
                    "/open-apis/auth/v3/tenant_access_token/internal",
                    json={
                        "app_id": self._config.app_id,
                        "app_secret": self._config.app_secret,
                    },
                )
                response.raise_for_status()
                payload = response.json()
                token = payload.get("tenant_access_token")
                if payload.get("code") != 0 or not isinstance(token, str):
                    raise ExternalAdapterUnavailable("feishu_app_auth_failed")
                headers = {"Authorization": f"Bearer {token}"}
                self._validate_fields(client, headers)
                rows = []
                for record_id in record_ids:
                    response = client.get(
                        f"/open-apis/bitable/v1/apps/{self._config.app_token}"
                        f"/tables/{self._config.table_id}/records/{quote(record_id, safe='')}",
                        params={"automatic_fields": "true"},
                        headers=headers,
                    )
                    response.raise_for_status()
                    payload = response.json()
                    if payload.get("code") != 0:
                        raise ExternalAdapterUnavailable("feishu_source_record_missing")
                    rows.append(self._parse_record(payload["data"]["record"]))
                return self._enrich_purchase_quantities(client, headers, rows)
        except (httpx.HTTPError, ValueError, TypeError, KeyError) as error:
            raise ExternalAdapterUnavailable("feishu_order_source_unavailable") from error

    def read_pages(
        self, *, modified_since: datetime | None = None
    ) -> Iterable[list[SourceOrderRow]]:
        if modified_since is not None and not self._config.incremental_table_scope_confirmed:
            raise ExternalAdapterUnavailable(
                "feishu_order_incremental_scope_not_confirmed"
            )
        try:
            with httpx.Client(base_url=self._config.base_url, timeout=30) as client:
                token_response = client.post(
                    "/open-apis/auth/v3/tenant_access_token/internal",
                    json={
                        "app_id": self._config.app_id,
                        "app_secret": self._config.app_secret,
                    },
                )
                token_response.raise_for_status()
                token_payload = token_response.json()
                token = token_payload.get("tenant_access_token")
                if token_payload.get("code") != 0 or not isinstance(token, str):
                    raise ExternalAdapterUnavailable("feishu_app_auth_failed")
                headers = {"Authorization": f"Bearer {token}"}
                modified_field_name = self._validate_fields(client, headers)
                page_token: str | None = None
                while True:
                    params: dict[str, str | int] = {
                        "page_size": 500,
                        "automatic_fields": "true",
                    }
                    if modified_since is None:
                        params["view_id"] = self._config.view_id
                    else:
                        local_date = (
                            modified_since.replace(tzinfo=UTC)
                            .astimezone(BUSINESS_TZ)
                            .date()
                            .isoformat()
                        )
                        if "]" in modified_field_name:
                            raise ExternalAdapterUnavailable(
                                "feishu_order_modified_time_field_invalid"
                            )
                        params["filter"] = (
                            f'CurrentValue.[{modified_field_name}] >= TODATE("{local_date}")'
                        )
                    if page_token:
                        params["page_token"] = page_token
                    response = client.get(
                        f"/open-apis/bitable/v1/apps/{self._config.app_token}"
                        f"/tables/{self._config.table_id}/records",
                        params=params,
                        headers=headers,
                    )
                    response.raise_for_status()
                    payload = response.json()
                    if payload.get("code") != 0:
                        raise ExternalAdapterUnavailable("feishu_base_read_failed")
                    data = payload.get("data") or {}
                    items = data.get("items") or []
                    yield self._enrich_purchase_quantities(
                        client, headers, [self._parse_record(item) for item in items]
                    )
                    if not data.get("has_more"):
                        break
                    page_token = data.get("page_token")
                    if not isinstance(page_token, str) or not page_token:
                        raise ExternalAdapterUnavailable("feishu_base_page_token_missing")
        except (httpx.HTTPError, ValueError, TypeError) as error:
            if isinstance(error, ExternalAdapterUnavailable):
                raise
            raise ExternalAdapterUnavailable("feishu_order_source_unavailable") from error

    def _validate_fields(self, client: httpx.Client, headers: dict[str, str]) -> str:
        response = client.get(
            f"/open-apis/bitable/v1/apps/{self._config.app_token}"
            f"/tables/{self._config.table_id}/fields",
            params={"page_size": 500},
            headers=headers,
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("code") != 0:
            raise ExternalAdapterUnavailable("feishu_base_field_read_failed")
        fields = {
            item.get("field_name"): item
            for item in (payload.get("data") or {}).get("items", [])
        }
        compatible_types = {
            "订单编号": {1, 19, 20, 1005},
            "商品名称": {1, 3, 19, 20},
            "产品颜色&规格": {1, 19, 20},
            "工厂": {1, 3, 4, 19, 20},
            "下单数": {2, 19, 20},
            "跟单人员": {1, 3, 4, 19, 20},
            "下单时间": {5, 19, 20},
            "合同出货时间": {5, 19, 20},
            "采购子订单号-映射": {1, 2, 19, 20},
            "采购子订单号-人工确认": {1, 2, 19, 20},
            "产品编码": {1, 2, 19, 20},
            "一级分类": {1, 3, 4, 19, 20},
        }
        if any(
            name not in fields or fields[name].get("type") not in allowed_types
            for name, allowed_types in compatible_types.items()
        ):
            raise ExternalAdapterUnavailable("feishu_order_field_contract_drift")
        modified_fields = [
            name for name, item in fields.items() if item.get("type") == 1002
        ]
        if len(modified_fields) != 1 or not isinstance(modified_fields[0], str):
            raise ExternalAdapterUnavailable("feishu_order_modified_time_field_missing")
        return modified_fields[0]

    @classmethod
    def _parse_record(cls, item: dict[str, Any]) -> SourceOrderRow:
        fields = item.get("fields") or {}
        trackers = cls._tracker_names(fields.get("跟单人员"))
        allowed_fields = {
            name: fields.get(name)
            for name in {
                "下单明细ID",
                "订单编号",
                "商品名称",
                "产品颜色&规格",
                "工厂",
                "下单数",
                "跟单人员",
                "下单时间",
                "合同出货时间",
                "采购子订单号-映射",
                "采购子订单号-人工确认",
                "产品编码",
                "一级分类",
            }
        }
        return SourceOrderRow(
            record_id=str(item.get("record_id") or ""),
            order_no=cls._text(fields.get("订单编号")),
            source_sku_id=cls._code(fields.get("产品编码")),
            product_name=cls._text(fields.get("商品名称")),
            properties_value=cls._text(fields.get("产品颜色&规格")),
            category=cls._text(fields.get("一级分类")),
            factory_name=cls._text(fields.get("工厂")),
            order_quantity=cls._integer(fields.get("下单数")),
            shipped_quantity=None,
            pending_quantity=None,
            tracker=trackers[0] if trackers else None,
            order_date=cls._date(fields.get("下单时间")),
            contract_ship_date=cls._contract_date(fields.get("合同出货时间")),
            raw_fields=allowed_fields,
            source_detail_id=cls._text(fields.get("下单明细ID")),
            source_modified_at=cls._modified_at(item.get("last_modified_time")),
            trackers=tuple(trackers),
        )

    @classmethod
    def _tracker_names(cls, value: Any) -> list[str]:
        values = value if isinstance(value, list) else [value]
        result: list[str] = []
        for item in values:
            text = cls._text(item)
            if not text:
                continue
            for name in text.replace("，", ",").replace("、", ",").split(","):
                name = name.strip()
                if name and name not in result:
                    result.append(name)
        return result

    def _enrich_purchase_quantities(
        self,
        client: httpx.Client,
        headers: dict[str, str],
        rows: list[SourceOrderRow],
    ) -> list[SourceOrderRow]:
        child_ids: dict[str, list[int]] = {}
        result = list(rows)
        for index, row in enumerate(rows):
            child_id = self._purchase_child_id(row.raw_fields)
            if child_id is None:
                if not self._has_purchase_number(row.raw_fields):
                    result[index] = replace(
                        row,
                        shipped_quantity=0,
                        pending_quantity=(
                            row.order_quantity if row.order_quantity is not None else None
                        ),
                    )
                continue
            child_ids.setdefault(child_id, []).append(index)
        if not child_ids:
            return result
        if not self._config.purchase_detail_table_id or self._purchase_source is None:
            return result
        main_orders = self._lookup_main_orders(client, headers, list(child_ids))
        try:
            items = self._purchase_source.fetch_purchase_items(
                list(dict.fromkeys(main_orders.values()))
            )
        except ProductSourceError as error:
            raise ExternalAdapterUnavailable("jst_purchase_source_unavailable") from error
        by_identity: dict[tuple[str, str], list[SourcePurchaseItem]] = {}
        for item in items:
            by_identity.setdefault((item.po_id, item.poi_id), []).append(item)
        read_at = datetime.now(UTC).replace(tzinfo=None).isoformat()
        for child_id, indexes in child_ids.items():
            po_id = main_orders.get(child_id)
            matched = by_identity.get((po_id, child_id), []) if po_id else []
            if len(matched) != 1:
                continue
            item = matched[0]
            for index in indexes:
                row = result[index]
                if item.sku_id and row.source_sku_id and item.sku_id != row.source_sku_id:
                    continue
                remaining = item.qty - item.in_qty + (item.return_qty or 0)
                shipped = (
                    row.order_quantity - remaining if row.order_quantity is not None else None
                )
                raw = dict(row.raw_fields)
                raw["_purchase"] = {
                    "childOrderId": child_id,
                    "mainOrderId": po_id,
                    "skuId": item.sku_id,
                    "qty": item.qty,
                    "inQty": item.in_qty,
                    "returnQty": item.return_qty,
                    "readAt": read_at,
                }
                result[index] = replace(
                    row,
                    shipped_quantity=shipped,
                    pending_quantity=remaining,
                    raw_fields=raw,
                )
        return result

    def _lookup_main_orders(
        self, client: httpx.Client, headers: dict[str, str], child_ids: list[str]
    ) -> dict[str, str]:
        matches: dict[str, set[str]] = {value: set() for value in child_ids}
        path = (
            f"/open-apis/bitable/v1/apps/{self._config.app_token}/tables/"
            f"{self._config.purchase_detail_table_id}/records/search"
        )
        for start in range(0, len(child_ids), 50):
            chunk = child_ids[start : start + 50]
            page_token: str | None = None
            while True:
                body: dict[str, object] = {
                    "automatic_fields": True,
                    "filter": {
                        "conjunction": "or",
                        "conditions": [
                            {
                                "field_name": "采购子订单号",
                                "operator": "is",
                                "value": [child_id],
                            }
                            for child_id in chunk
                        ],
                    },
                }
                params: dict[str, str | int] = {"page_size": 500}
                if page_token:
                    params["page_token"] = page_token
                response = client.post(path, params=params, json=body, headers=headers)
                response.raise_for_status()
                payload = response.json()
                if payload.get("code") != 0:
                    raise ExternalAdapterUnavailable("feishu_purchase_mapping_failed")
                data = payload.get("data") or {}
                for record in data.get("items") or []:
                    fields = record.get("fields") or {}
                    child = self._text(fields.get("采购子订单号"))
                    main = self._text(fields.get("采购主订单号"))
                    if child in matches and main:
                        matches[child].add(main)
                if not data.get("has_more"):
                    break
                page_token = data.get("page_token")
                if not isinstance(page_token, str) or not page_token:
                    raise ExternalAdapterUnavailable("feishu_base_page_token_missing")
        return {child: next(iter(values)) for child, values in matches.items() if len(values) == 1}

    @classmethod
    def _purchase_child_id(cls, fields: dict[str, object]) -> str | None:
        value = cls._text(fields.get("采购子订单号-人工确认")) or cls._text(
            fields.get("采购子订单号-映射")
        )
        if not value or any(separator in value for separator in (",", "，", "、")):
            return None
        return value.strip()

    @classmethod
    def _has_purchase_number(cls, fields: dict[str, object]) -> bool:
        return bool(
            cls._text(fields.get("采购子订单号-人工确认"))
            or cls._text(fields.get("采购子订单号-映射"))
        )

    @classmethod
    def _contract_date(cls, value: Any) -> date | None:
        # Formula/lookup responses may wrap a single date in value/list/text.
        # Reject ambiguous multi-values before parsing; never truncate them.
        if isinstance(value, dict):
            return cls._contract_date(value.get("value", value.get("text")))
        if isinstance(value, list):
            return cls._contract_date(value[0]) if len(value) == 1 else None
        if isinstance(value, bool) or value is None:
            return None
        try:
            if isinstance(value, (int, float)):
                return datetime.fromtimestamp(value / 1000, tz=UTC).astimezone(BUSINESS_TZ).date()
            if isinstance(value, str):
                text = value.strip()
                if text.isdigit():
                    return cls._contract_date(int(text))
                if len(text) == 10:
                    return date.fromisoformat(text)
                parsed = datetime.fromisoformat(text)
                return parsed.astimezone(BUSINESS_TZ).date() if parsed.tzinfo else parsed.date()
        except (ValueError, OverflowError, OSError):
            return None
        return None

    @staticmethod
    def _modified_at(value: Any) -> datetime:
        if isinstance(value, bool) or not isinstance(value, (int, float, str)):
            raise ValueError("feishu record last_modified_time is missing")
        milliseconds = int(value)
        return datetime.fromtimestamp(milliseconds / 1000, tz=UTC).replace(tzinfo=None)

    @staticmethod
    def _text(value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, list):
            parts = [AppCredentialFeishuOrderSource._text(item) for item in value]
            return "、".join(part for part in parts if part) or None
        if isinstance(value, dict):
            for key in ("text", "name", "value"):
                if key in value:
                    return AppCredentialFeishuOrderSource._text(value[key])
            return None
        text = str(value).strip()
        return text or None

    @staticmethod
    def _code(value: Any) -> str | None:
        if isinstance(value, int):
            return str(value)
        if isinstance(value, float) and value.is_integer():
            return str(int(value))
        return AppCredentialFeishuOrderSource._text(value)

    @staticmethod
    def _integer(value: Any) -> int | None:
        text = AppCredentialFeishuOrderSource._text(value)
        if text is None:
            return None
        try:
            number = Decimal(text.replace(",", ""))
        except InvalidOperation:
            return None
        if not number.is_finite() or not -2147483648 <= number <= 2147483647:
            return None
        return int(number) if number == number.to_integral_value() else None

    @classmethod
    def _date(cls, value: Any) -> date | None:
        return cls._contract_date(value)
