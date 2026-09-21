from collections.abc import Callable
from datetime import date
from hashlib import sha256
from typing import Any, Literal
from urllib.parse import quote

from mcp.server import MCPServer
from mcp.types import ToolAnnotations

from app.api.shipments import (
    ReceiptItemWrite,
    ShipmentReturnLineWrite,
    ShipmentSummaryResponse,
    _draft_response,
    _receipt_response,
    _return_event_response,
)
from app.mcp.files import download_descriptor
from app.modules.shipments import ShipmentReturnInput, ShipmentService, ShipmentValidationError
from app.modules.shipments.service import ReceiptItemInput


def register_shipment_tools(
    mcp: MCPServer,
    shipments: ShipmentService,
    execute: Callable[[str, Callable[[str, str], Any]], dict[str, Any]],
    *,
    origin: str,
) -> None:
    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    def list_shipments(
        keyword: str = "",
        factory: str = "",
        factories: list[str] | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        receipt_status: Literal["", "RECEIVED", "UNRECEIVED"] = "",
        sort_by: Literal[
            "", "shipmentNo", "orderNos", "factory", "productNames",
            "totalQuantity", "businessDate",
        ] = "",
        sort_order: Literal["asc", "desc"] = "asc",
        page: int = 1,
        page_size: int = 10,
        order_id: str | None = None,
    ) -> dict[str, Any]:
        """查询管理员发货列表。分页汇总显示当前收货确认量；order_id 查询关联订单的完整发货单。"""
        if order_id is not None:
            if not order_id:
                raise ShipmentValidationError("order_id is required")
            def related(_user: str, _request: str) -> dict[str, Any]:
                items = [_draft_response(item).model_dump(mode="json", by_alias=True)
                         for item in shipments.list_shipments(order_id=order_id)]
                return {
                    "items": items, "total": len(items),
                    "basis": "current_confirmed_or_original",
                }
            return execute("list_shipments", related)
        if page < 1 or page_size < 1 or page_size > 100:
            raise ShipmentValidationError("invalid pagination")
        def query(_user: str, _request: str) -> dict[str, Any]:
            rows, total = shipments.page_admin_shipments(
                keyword=keyword, factory=factory, factories=factories,
                date_from=date_from, date_to=date_to, receipt_status=receipt_status,
                sort_by=sort_by, sort_order=sort_order, page=page, page_size=page_size,
            )
            return {
                "items": [ShipmentSummaryResponse.model_validate(row).model_dump(
                    mode="json", by_alias=True,
                ) for row in rows],
                "total": total, "page": page, "pageSize": page_size,
                "basis": "current_confirmed_or_original",
            }
        return execute("list_shipments", query)

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    def get_shipment(shipment_id: str) -> dict[str, Any]:
        """按稳定发货单 ID 查询关联订单、箱内项、凭证、收货状态、退回与操作记录。"""
        return execute("get_shipment", lambda _user, _request: _draft_response(
            shipments.get_shipment(shipment_id=shipment_id)
        ))

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    def get_daily_shipment_summary(
        business_date: date, factory_id: str | None = None
    ) -> dict[str, Any]:
        """按上海业务日期查询各厂或指定工厂的有效发货原报数量；收货确认量单列。"""
        if factory_id is None:
            return execute("get_daily_shipment_summary", lambda _user, _request:
                           shipments.list_daily_shipment_summaries(business_date=business_date))
        return execute("get_daily_shipment_summary", lambda _user, _request:
                       shipments.get_daily_shipment_summary(
                           factory_id=factory_id, business_date=business_date,
                       ))

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    def export_shipment(shipment_id: str) -> dict[str, Any]:
        """生成单张发货清单，返回原报数量 Excel 和现有管理员下载路径。"""
        def query(_user: str, _request: str) -> dict[str, Any]:
            result = shipments.export_shipment(shipment_id=shipment_id)
            return {
                "shipmentId": shipment_id,
                "basis": "original_reported",
                **download_descriptor(
                    origin=origin,
                    path=f"/api/v1/agent-shipments/{quote(shipment_id, safe='')}/export",
                    filename=result.filename,
                    size_bytes=len(result.content),
                    sha256=sha256(result.content).hexdigest(),
                ),
            }
        return execute("export_shipment", query)

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    def export_daily_shipments(factory_id: str, business_date: date) -> dict[str, Any]:
        """生成同厂上海业务日期发货清单，返回原报数量 Excel 和现有管理员下载路径。"""
        def query(_user: str, _request: str) -> dict[str, Any]:
            result = shipments.export_daily_shipments(
                factory_id=factory_id, business_date=business_date,
            )
            return {
                "factoryId": factory_id,
                "businessDate": business_date.isoformat(),
                "basis": "original_reported",
                **download_descriptor(
                    origin=origin,
                    path=(
                        f"/api/v1/agent-shipments/daily-export/"
                        f"{quote(factory_id, safe='')}/{business_date}"
                    ),
                    filename=result.filename,
                    size_bytes=len(result.content),
                    sha256=sha256(result.content).hexdigest(),
                ),
            }
        return execute("export_daily_shipments", query)

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    def get_receipt(shipment_id: str) -> dict[str, Any]:
        """读取发货单逐箱收货核对草稿及版本，箱内项使用 boxItemId 定位。"""
        return execute("get_receipt", lambda _user, _request: _receipt_response(
            shipments.get_receipt(shipment_id=shipment_id)
        ))

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False))
    def save_receipt(
        shipment_id: str, version: int, items: list[ReceiptItemWrite]
    ) -> dict[str, Any]:
        """保存完整逐箱核对草稿；版本必须匹配，保存不会改变正式已发数量。"""
        return execute("save_receipt", lambda user_id, _request: _receipt_response(
            shipments.save_receipt(
                shipment_id=shipment_id, actor_id=user_id, expected_version=version,
                items=[ReceiptItemInput(item.box_item_id, item.quantity) for item in items],
                source_terminal="agent",
            )
        ))

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False))
    def confirm_receipt(
        shipment_id: str, version: int, idempotency_key: str
    ) -> dict[str, Any]:
        """整单确认收货并一次计入数量差额；需已读取的版本和本动作固定幂等键。"""
        if not idempotency_key or len(idempotency_key) > 191:
            raise ShipmentValidationError("invalid idempotency_key")
        return execute("confirm_receipt", lambda user_id, _request: _draft_response(
            shipments.confirm_receipt(
                shipment_id=shipment_id, actor_id=user_id, expected_version=version,
                idempotency_key=idempotency_key, source_terminal="agent",
            )
        ))

    @mcp.tool(annotations=ToolAnnotations(destructiveHint=True))
    def return_shipment(
        shipment_id: str,
        reason: str,
        lines: list[ShipmentReturnLineWrite],
        idempotency_key: str,
    ) -> dict[str, Any]:
        """按发货单规格退回已发数量；需明确退回授权、原因、数量和本动作固定幂等键。"""
        if not idempotency_key or len(idempotency_key) > 191:
            raise ShipmentValidationError("invalid idempotency_key")
        def write(user_id: str, _request: str) -> dict[str, Any]:
            event, created = shipments.return_shipment(
                actor_id=user_id, shipment_id=shipment_id, reason=reason,
                lines=[ShipmentReturnInput(line.shipment_line_id, line.quantity)
                       for line in lines],
                idempotency_key=idempotency_key, source_terminal="agent",
            )
            return {
                "event": _return_event_response(event).model_dump(mode="json", by_alias=True),
                "created": created,
            }
        return execute("return_shipment", write)
