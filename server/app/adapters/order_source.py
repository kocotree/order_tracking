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
ORDER_FIELD_TYPES = {
    "下单明细ID": {1, 19, 20, 1005},
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
    "采购单号": {1, 2, 19, 20},
    "产品编码": {1, 2, 19, 20},
    "一级分类": {1, 3, 4, 19, 20},
}


class FeishuOrderSource(Protocol):
    @property
    def source_scope(self) -> str: ...

    def read_records(
        self,
        record_ids: list[str],
        *,
        purchase_links: dict[str, tuple[str, str]] | None = None,
    ) -> list[SourceOrderRow]: ...

    def read_pages(
        self, *, modified_since: datetime | None = None
    ) -> Iterable[list[SourceOrderRow]]: ...


class DisabledFeishuOrderSource:
    source_scope = "unconfigured-feishu-order-source"

    def read_records(
        self,
        record_ids: list[str],
        *,
        purchase_links: dict[str, tuple[str, str]] | None = None,
    ) -> list[SourceOrderRow]:
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

    def read_records(
        self,
        record_ids: list[str],
        *,
        purchase_links: dict[str, tuple[str, str]] | None = None,
    ) -> list[SourceOrderRow]:
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
    field_ids: dict[str, str]
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

    def read_records(
        self,
        record_ids: list[str],
        *,
        purchase_links: dict[str, tuple[str, str]] | None = None,
    ) -> list[SourceOrderRow]:
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
                field_names, _ = self._validate_fields(client, headers)
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
                    rows.append(self._parse_record(payload["data"]["record"], field_names))
                return self._enrich_purchase_quantities(rows, purchase_links=purchase_links)
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
                field_names, modified_field_name = self._validate_fields(client, headers)
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
                        [self._parse_record(item, field_names) for item in items]
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

    def _validate_fields(
        self, client: httpx.Client, headers: dict[str, str]
    ) -> tuple[dict[str, str], str]:
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
        items = (payload.get("data") or {}).get("items", [])
        fields_by_id = {item.get("field_id"): item for item in items}
        configured_ids = [self._config.field_ids.get(name) for name in ORDER_FIELD_TYPES]
        if any(not field_id for field_id in configured_ids) or len(set(configured_ids)) != len(
            configured_ids
        ):
            raise ExternalAdapterUnavailable("feishu_order_field_contract_drift")
        field_names: dict[str, str] = {}
        for name, allowed_types in ORDER_FIELD_TYPES.items():
            field = fields_by_id.get(self._config.field_ids[name])
            current_name = field.get("field_name") if field else None
            if (
                field is None
                or field.get("type") not in allowed_types
                or not isinstance(current_name, str)
                or not current_name
            ):
                raise ExternalAdapterUnavailable("feishu_order_field_contract_drift")
            field_names[name] = current_name
        if len(set(field_names.values())) != len(field_names):
            raise ExternalAdapterUnavailable("feishu_order_field_contract_drift")
        modified_fields = [
            item.get("field_name") for item in items if item.get("type") == 1002
        ]
        if len(modified_fields) != 1 or not isinstance(modified_fields[0], str):
            raise ExternalAdapterUnavailable("feishu_order_modified_time_field_missing")
        return field_names, modified_fields[0]

    @classmethod
    def _parse_record(
        cls, item: dict[str, Any], field_names: dict[str, str] | None = None
    ) -> SourceOrderRow:
        fields = item.get("fields") or {}
        names = field_names or {}

        def value(name: str) -> Any:
            return fields.get(names.get(name, name))

        trackers = cls._tracker_names(value("跟单人员"))
        allowed_fields = {
            name: value(name)
            for name in (
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
                "采购单号",
                "产品编码",
                "一级分类",
            )
        }
        return SourceOrderRow(
            record_id=str(item.get("record_id") or ""),
            order_no=cls._text(value("订单编号")),
            source_sku_id=cls._code(value("产品编码")),
            product_name=cls._text(value("商品名称")),
            properties_value=cls._text(value("产品颜色&规格")),
            category=cls._text(value("一级分类")),
            factory_name=cls._text(value("工厂")),
            order_quantity=cls._integer(value("下单数")),
            shipped_quantity=None,
            pending_quantity=None,
            tracker=trackers[0] if trackers else None,
            order_date=cls._date(value("下单时间")),
            contract_ship_date=cls._contract_date(value("合同出货时间")),
            raw_fields=allowed_fields,
            source_detail_id=cls._text(value("下单明细ID")),
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
        rows: list[SourceOrderRow],
        *,
        purchase_links: dict[str, tuple[str, str]] | None = None,
    ) -> list[SourceOrderRow]:
        links: dict[int, tuple[str, str]] = {}
        result = list(rows)
        for index, row in enumerate(rows):
            link = self._purchase_link(row.raw_fields)
            if link is None and purchase_links is not None:
                link = purchase_links.get(row.record_id)
            if link is None:
                if not self._has_purchase_number(row.raw_fields):
                    result[index] = replace(
                        row,
                        shipped_quantity=0,
                        pending_quantity=(
                            row.order_quantity if row.order_quantity is not None else None
                        ),
                    )
                continue
            links[index] = link
        if not links:
            return result
        if self._purchase_source is None:
            return result
        try:
            items = self._purchase_source.fetch_purchase_items(
                list(dict.fromkeys(po_id for po_id, _ in links.values()))
            )
        except ProductSourceError as error:
            raise ExternalAdapterUnavailable("jst_purchase_source_unavailable") from error
        by_identity: dict[tuple[str, str], list[SourcePurchaseItem]] = {}
        for item in items:
            by_identity.setdefault((item.po_id, item.poi_id), []).append(item)
        read_at = datetime.now(UTC).replace(tzinfo=None).isoformat()
        for index, (po_id, child_id) in links.items():
            matched = by_identity.get((po_id, child_id), [])
            if len(matched) != 1:
                continue
            item = matched[0]
            row = result[index]
            if item.sku_id and row.source_sku_id and item.sku_id != row.source_sku_id:
                continue
            remaining = item.qty - item.in_qty
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
                order_quantity=item.qty,
                shipped_quantity=item.in_qty,
                pending_quantity=remaining,
                raw_fields=raw,
            )
        return result

    @classmethod
    def _purchase_identifier(cls, value: object) -> str | None:
        value = cls._text(value)
        if not value or any(separator in value for separator in (",", "，", "、")):
            return None
        return value.strip()

    @classmethod
    def _purchase_link(cls, fields: dict[str, object]) -> tuple[str, str] | None:
        child_id = cls._purchase_identifier(fields.get("采购子订单号-人工确认"))
        if child_id is None and not cls._text(fields.get("采购子订单号-人工确认")):
            child_id = cls._purchase_identifier(fields.get("采购子订单号-映射"))
        po_id = cls._purchase_identifier(fields.get("采购单号"))
        return (po_id, child_id) if po_id and child_id else None

    @classmethod
    def _has_purchase_number(cls, fields: dict[str, object]) -> bool:
        return bool(
            cls._text(fields.get("采购子订单号-人工确认"))
            or cls._text(fields.get("采购子订单号-映射"))
            or cls._text(fields.get("采购单号"))
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
