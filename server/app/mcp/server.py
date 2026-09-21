from collections.abc import Callable
from datetime import UTC, date
from typing import Any, cast
from uuid import uuid4

from anyio import to_thread
from mcp.server import MCPServer
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from pydantic import AnyHttpUrl
from sqlalchemy.orm import Session, sessionmaker

from app.adapters.private_files import PrivateFileStore
from app.api.identity import _user_response
from app.api.orders import (
    AuditLogListResponse,
    DashboardResponse,
    OrderListResponse,
    _audit_response,
    _order_response,
)
from app.mcp.directory import register_directory_tools
from app.mcp.order_tools import register_order_tools
from app.mcp.repairs import register_repair_tools
from app.mcp.shipments import register_shipment_tools
from app.modules.contracts import ContractService
from app.modules.factory_access import FactoryAccessService
from app.modules.identity_access.agent_oauth import AgentOAuthService
from app.modules.identity_access.service import IdentityAccessService
from app.modules.notifications_audit import NotificationsAuditService
from app.modules.order_import import OrderImportService
from app.modules.orders import OrderService
from app.modules.orders.dispatch import OrderDispatchService
from app.modules.orders.source_update import OrderSourceUpdateService
from app.modules.product_sync import ProductCatalogService
from app.modules.repairs.confirmation import RepairConfirmationService
from app.modules.repairs.preview import RepairPreviewService
from app.modules.repairs.returns import RepairReturnService
from app.modules.repairs.workflow import RepairWorkflowService
from app.modules.shipments import ShipmentService


class AgentTokenVerifier(TokenVerifier):
    def __init__(self, oauth: AgentOAuthService) -> None:
        self.oauth = oauth

    async def verify_token(self, token: str) -> AccessToken | None:
        checked = await to_thread.run_sync(self.oauth.verify_access, token)
        if checked is None:
            return None
        user_id, auth_id, client_id, expires_at = checked
        return AccessToken(
            token=token, client_id=client_id, scopes=["order_tracking.admin"],
            resource=self.oauth.resource, subject=user_id,
            expires_at=int(expires_at.replace(tzinfo=UTC).timestamp()),
            claims={"auth_id": auth_id},
        )


def create_agent_mcp(
    *,
    oauth: AgentOAuthService,
    identity: IdentityAccessService,
    orders: OrderService,
    imports: OrderImportService | None,
    shipments: ShipmentService,
    source_updates: OrderSourceUpdateService,
    dispatch: OrderDispatchService,
    contracts: ContractService,
    repair_workflow: RepairWorkflowService,
    repair_previews: RepairPreviewService,
    repair_confirmations: RepairConfirmationService,
    repair_returns: RepairReturnService,
    sessions: sessionmaker[Session],
    file_hosts: frozenset[str],
    factories: FactoryAccessService,
    products: ProductCatalogService,
    notifications: NotificationsAuditService,
    file_store: PrivateFileStore,
) -> tuple[MCPServer, TransportSecuritySettings]:
    origin = oauth.resource.removesuffix("/mcp")
    host = AnyHttpUrl(oauth.resource).host
    transport_security = TransportSecuritySettings(
        allowed_hosts=[host, f"{host}:*"], allowed_origins=[origin],
    )
    mcp = MCPServer(
        "跟单管理系统",
        token_verifier=AgentTokenVerifier(oauth),
        auth=AuthSettings(
            issuer_url=AnyHttpUrl(f"{origin}/"),
            resource_server_url=AnyHttpUrl(oauth.resource),
            required_scopes=["order_tracking.admin"],
            validate_token_resource=True,
        ),
    )

    def actor() -> tuple[str, str]:
        token = get_access_token()
        if token is None or token.subject is None or token.claims is None:
            raise ValueError("authorization required")
        auth_id = token.claims.get("auth_id")
        if not isinstance(auth_id, str):
            raise ValueError("authorization required")
        return token.subject, auth_id

    def read(name: str, callback: Callable[[str, str], Any]) -> dict[str, Any]:
        request_id = uuid4().hex
        user_id, auth_id = actor()
        result = callback(user_id, request_id)
        oauth.record_tool_success(
            auth_id=auth_id, user_id=user_id, tool=name, request_id=request_id
        )
        if hasattr(result, "model_dump"):
            payload = cast(dict[str, Any], result.model_dump(mode="json", by_alias=True))
            payload["requestId"] = request_id
            return payload
        if isinstance(result, dict):
            return {**result, "requestId": request_id}
        return {"requestId": request_id, "result": result}

    register_order_tools(
        mcp, read, orders=orders, imports=imports,
        source_updates=source_updates, dispatch=dispatch, contracts=contracts,
        origin=origin,
    )

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    def get_me() -> dict[str, Any]:
        """查询当前管理员身份及本人权限。"""
        return read("get_me", lambda user_id, _rid: _user_response(
            identity.get_user(user_id=user_id)
        ))

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    def get_dashboard(keyword: str = "", sort_by: str = "updatedDesc") -> dict[str, Any]:
        """查询管理员订单看板和最近订单。"""
        def query(user_id: str, request_id: str) -> DashboardResponse:
            items, total = orders.list_visible(
                actor_id=user_id, include_drafts=True, keyword=keyword,
                page_size=10, sort_by=sort_by,
            )
            overdue, shipments = orders.dashboard_counts(actor_id=user_id)
            return DashboardResponse(
                total_orders=total, overdue_orders=overdue,
                pending_import_orders=(
                    imports.pending_count(actor_id=user_id) if imports is not None else 0
                ),
                today_shipments=shipments,
                recent_orders=[_order_response(item, request_id) for item in items[:10]],
                request_id=request_id,
            )
        return read("get_dashboard", query)

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    def list_orders(
        keyword: str = "",
        status: str = "all",
        dispatch_status: str = "all",
        category: str | None = None,
        factory_id: str | None = None,
        factory_ids: list[str] | None = None,
        trackers: list[str] | None = None,
        ship_date_from: date | None = None,
        ship_date_to: date | None = None,
        sort_by: str = "priority",
        include_drafts: bool = False,
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]:
        """按网页相同筛选、排序和分页查询订单。"""
        def query(user_id: str, request_id: str) -> OrderListResponse:
            items, total = orders.list_visible(
                actor_id=user_id, keyword=keyword, status=status,
                dispatch_status=dispatch_status, category=category,
                factory_id=factory_id, factory_ids=factory_ids, trackers=trackers,
                ship_date_from=ship_date_from, ship_date_to=ship_date_to,
                sort_by=sort_by, include_drafts=include_drafts,
                page=page, page_size=page_size,
            )
            return OrderListResponse(
                items=[_order_response(item, request_id) for item in items],
                total=total, page=page, page_size=page_size, request_id=request_id,
            )
        return read("list_orders", query)

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    def get_order(order_id: str) -> dict[str, Any]:
        """按订单 ID 查询完整明细和关联发货信息。"""
        return read("get_order", lambda user_id, request_id: _order_response(
            orders.get_visible(actor_id=user_id, order_id=order_id), request_id
        ))

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    def get_order_audit(order_id: str) -> dict[str, Any]:
        """查询指定订单的操作记录。"""
        def query(user_id: str, request_id: str) -> AuditLogListResponse:
            items = orders.list_audit_logs(actor_id=user_id, order_id=order_id)
            return AuditLogListResponse(
                items=[_audit_response(item) for item in items],
                total=len(items), request_id=request_id,
            )
        return read("get_order_audit", query)

    @mcp.tool(annotations=ToolAnnotations(destructiveHint=True))
    def logout_shared_session() -> dict[str, Any]:
        """统一退出当前管理员的网页和 Codex，所有旧登录凭据立即失效。"""
        user_id, auth_id = actor()
        request_id = uuid4().hex
        identity.revoke_shared(auth_id=auth_id, user_id=user_id, request_id=request_id)
        return {"revoked": True, "requestId": request_id}

    register_repair_tools(
        mcp, read=read, workflow=repair_workflow, previews=repair_previews,
        confirmations=repair_confirmations, returns=repair_returns,
        sessions=sessions, origin=origin, file_hosts=file_hosts,
    )
    register_shipment_tools(mcp, shipments, read, origin=origin)
    register_directory_tools(
        mcp, read, identity=identity, factories=factories, products=products,
        notifications=notifications, file_store=file_store,
    )
    return mcp, transport_security
