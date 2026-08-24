from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from typing import Any, Protocol
from zoneinfo import ZoneInfo

import httpx

from app.adapters.errors import ExternalAdapterUnavailable
from app.modules.order_import import SourceOrderRow

BUSINESS_TZ = ZoneInfo("Asia/Shanghai")


class FeishuOrderSource(Protocol):
    @property
    def source_scope(self) -> str: ...

    def read_pages(self) -> Iterable[list[SourceOrderRow]]: ...


class DisabledFeishuOrderSource:
    source_scope = "unconfigured-feishu-order-source"

    def read_pages(self) -> Iterable[list[SourceOrderRow]]:
        raise ExternalAdapterUnavailable("feishu_order_source_not_configured")


class FakeFeishuOrderSource:
    def __init__(
        self, pages: list[list[SourceOrderRow]], *, fail_on_page: int | None = None
    ) -> None:
        self._pages = pages
        self._fail_on_page = fail_on_page
        self.source_scope = "fake-feishu-order-source"

    def read_pages(self) -> Iterable[list[SourceOrderRow]]:
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
    base_url: str = "https://open.feishu.cn"


class AppCredentialFeishuOrderSource:
    """Read the configured Base view with tenant app credentials only."""

    def __init__(self, config: FeishuOrderSourceConfig) -> None:
        self._config = config
        scope = f"{config.app_token}:{config.table_id}:{config.view_id}".encode()
        self.source_scope = f"feishu:{sha256(scope).hexdigest()[:32]}"

    def read_pages(self) -> Iterable[list[SourceOrderRow]]:
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
                self._validate_fields(client, headers)
                page_token: str | None = None
                while True:
                    params: dict[str, str | int] = {
                        "view_id": self._config.view_id,
                        "page_size": 500,
                    }
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
                    yield [self._parse_record(item) for item in items]
                    if not data.get("has_more"):
                        break
                    page_token = data.get("page_token")
                    if not isinstance(page_token, str) or not page_token:
                        raise ExternalAdapterUnavailable("feishu_base_page_token_missing")
        except (httpx.HTTPError, ValueError, TypeError) as error:
            if isinstance(error, ExternalAdapterUnavailable):
                raise
            raise ExternalAdapterUnavailable("feishu_order_source_unavailable") from error

    def _validate_fields(self, client: httpx.Client, headers: dict[str, str]) -> None:
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
            "商品名称": {1, 19, 20},
            "产品颜色&规格": {1, 19, 20},
            "工厂": {1, 3, 4, 19, 20},
            "下单数": {2, 19, 20},
            "跟单人员": {1, 3, 4, 19, 20},
            "下单时间": {5, 19, 20},
            "生产计划出货时间（提前或者推迟 的时间）": {5, 19, 20},
            "出货总数": {2, 19, 20},
            "未出数量": {2, 19, 20},
            "产品编码": {1, 2, 19, 20},
            "一级分类": {1, 3, 4, 19, 20},
        }
        if any(
            name not in fields or fields[name].get("type") not in allowed_types
            for name, allowed_types in compatible_types.items()
        ):
            raise ExternalAdapterUnavailable("feishu_order_field_contract_drift")

    @classmethod
    def _parse_record(cls, item: dict[str, Any]) -> SourceOrderRow:
        fields = item.get("fields") or {}
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
                "生产计划出货时间（提前或者推迟 的时间）",
                "出货总数",
                "未出数量",
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
            shipped_quantity=cls._integer(fields.get("出货总数")) or 0,
            pending_quantity=cls._integer(fields.get("未出数量")) or 0,
            tracker=cls._text(fields.get("跟单人员")),
            order_date=cls._date(fields.get("下单时间")),
            contract_ship_date=cls._date(fields.get("生产计划出货时间（提前或者推迟 的时间）")),
            raw_fields=allowed_fields,
            source_detail_id=cls._text(fields.get("下单明细ID")),
        )

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
        return int(number) if number == number.to_integral_value() else None

    @staticmethod
    def _date(value: Any) -> date | None:
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value / 1000, tz=UTC).astimezone(BUSINESS_TZ).date()
        text = AppCredentialFeishuOrderSource._text(value)
        if text is None:
            return None
        try:
            return date.fromisoformat(text[:10])
        except ValueError:
            return None
