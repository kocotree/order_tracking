import base64
from collections.abc import Callable
from io import BytesIO
from typing import Any, Literal

from mcp.server import MCPServer
from mcp.types import CallToolResult, ImageContent, TextContent, ToolAnnotations
from PIL import Image, UnidentifiedImageError

from app.adapters.private_files import PrivateFileStore, PrivateFileStoreUnavailable
from app.api.factory_access import _application_response, _factory_response
from app.api.identity import _factory_user_response, _user_response
from app.api.notifications_audit import _notification_response
from app.api.products import _item_response
from app.modules.factory_access import FactoryAccessService
from app.modules.identity_access import IdentityAccessService, PermissionDenied, ResourceNotFound
from app.modules.notifications_audit import NotificationsAuditService
from app.modules.product_sync import ProductCatalogService

ReadTool = Callable[[str, Callable[[str, str], Any]], dict[str, Any]]


def register_directory_tools(
    mcp: MCPServer,
    read: ReadTool,
    *,
    identity: IdentityAccessService,
    factories: FactoryAccessService,
    products: ProductCatalogService,
    notifications: NotificationsAuditService,
    file_store: PrivateFileStore,
) -> None:
    def page_args(page: int, page_size: int) -> None:
        if page < 1 or not 1 <= page_size <= 100:
            raise ValueError("page must be positive and page_size must be 1..100")

    def admin(user_id: str) -> None:
        user = identity.get_user(user_id=user_id)
        if user.role != "admin" or not user.is_enabled:
            raise PermissionDenied("administrator role required")

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    def list_factories(
        keyword: str = "", contract_status: str = "all", access_status: str = "all",
        page: int = 1, page_size: int = 10, sort_by: str = "", sort_order: str = "asc",
    ) -> dict[str, Any]:
        """按网页筛选、排序和分页查询工厂；写入时使用 factoryId。"""
        def query(user_id: str, _request_id: str) -> dict[str, Any]:
            page_args(page, page_size)
            rows, total = factories.page_factories(
                actor_id=user_id, keyword=keyword, contract_status=contract_status,
                access_status=access_status, page=page, page_size=page_size,
                sort_by=sort_by, sort_order=sort_order,
            )
            return {"items": [_factory_response(row).model_dump(by_alias=True) for row in rows],
                    "total": total, "page": page, "pageSize": page_size}
        return read("list_factories", query)

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    def get_factory(factory_id: str) -> dict[str, Any]:
        """按稳定 factoryId 查询工厂、联系人及合同资料。"""
        return read("get_factory", lambda user_id, _rid: _factory_response(
            factories.get_factory(actor_id=user_id, factory_id=factory_id)
        ))

    @mcp.tool()
    def create_factory(
        supplier_number: str, factory_name: str, factory_code: str,
        legal_name: str = "", address: str = "", legal_representative: str = "",
        contacts: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        """明确授权后新增工厂；供应商编号和工厂名称必须唯一，联系人传 name/phone。"""
        return read("create_factory", lambda user_id, request_id: _factory_response(
            factories.create_factory(
                actor_id=user_id, supplier_number=supplier_number, factory_name=factory_name,
                factory_code=factory_code, legal_name=legal_name, address=address,
                legal_representative=legal_representative,
                contacts=[(item["name"], item["phone"]) for item in contacts or []],
                request_id=request_id,
            )
        ))

    @mcp.tool()
    def update_factory(
        factory_id: str, version: int, factory_name: str, factory_code: str,
        legal_name: str = "", address: str = "", legal_representative: str = "",
        contacts: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        """明确授权后按 factoryId 和当前 version 更新工厂；供应商编号不可修改。"""
        return read("update_factory", lambda user_id, request_id: _factory_response(
            factories.update_factory(
                actor_id=user_id, factory_id=factory_id, expected_version=version,
                factory_name=factory_name, factory_code=factory_code, legal_name=legal_name,
                address=address, legal_representative=legal_representative,
                contacts=[(item["name"], item["phone"]) for item in contacts or []],
                request_id=request_id,
            )
        ))

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    def list_products(
        keyword: str = "", page: int = 1, page_size: int = 10,
        sort_by: Literal["iId", "skuId", "name", "propertiesValue"] = "iId",
        sort_order: Literal["asc", "desc"] = "asc",
    ) -> dict[str, Any]:
        """只读查询产品和规格；有图片时用 productId 与 imageVersion 读取。"""
        def query(user_id: str, _request_id: str) -> dict[str, Any]:
            admin(user_id)
            page_args(page, page_size)
            if len(keyword) > 255:
                raise ValueError("keyword is too long")
            result = products.list_available(
                keyword=keyword, page=page, page_size=page_size,
                sort_by=sort_by, sort_order=sort_order,
            )
            items = []
            for row in result.items:
                item = _item_response(row).model_dump(by_alias=True)
                item["productId"] = row.product_id
                item["imageVersion"] = row.image_version
                items.append(item)
            return {"items": items, "total": result.total,
                    "page": result.page, "pageSize": result.page_size}
        return read("list_products", query)

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    def get_product_image(product_id: str, image_version: str) -> CallToolResult:
        """按列表返回的 productId 和 imageVersion 受权读取私有产品图片。"""
        def query(user_id: str, _request_id: str) -> dict[str, Any]:
            admin(user_id)
            object_key = products.get_cached_image_object_key(
                product_id=product_id, image_version=image_version,
            )
            if object_key is None:
                raise ResourceNotFound("product image was not found")
            try:
                content = file_store.get(object_key=object_key)
                with Image.open(BytesIO(content)) as image:
                    media_type = image.get_format_mimetype()
            except (PrivateFileStoreUnavailable, UnidentifiedImageError, OSError) as error:
                raise ResourceNotFound("product image was not found") from error
            if media_type is None or not media_type.startswith("image/"):
                raise ResourceNotFound("product image was not found")
            return {"mimeType": media_type, "base64": base64.b64encode(content).decode()}
        payload = read("get_product_image", query)
        return CallToolResult(content=[
            ImageContent(type="image", data=payload["base64"], mime_type=payload["mimeType"]),
            TextContent(type="text", text=f"requestId: {payload['requestId']}"),
        ])

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    def list_factory_applications(
        status: str | None = None, page: int = 1, page_size: int = 10,
        sort_by: str = "", sort_order: str = "asc",
    ) -> dict[str, Any]:
        """按状态、排序和分页查询工厂申请；审核使用 applicationId。"""
        def query(user_id: str, _request_id: str) -> dict[str, Any]:
            page_args(page, page_size)
            allowed = {
                "", "realName", "position", "requestedFactoryName", "submittedAt", "status",
            }
            if sort_by not in allowed or sort_order not in {"asc", "desc"}:
                raise ValueError("invalid sort field")
            rows, total = factories.page_factory_applications(
                actor_id=user_id, status=status, page=page, page_size=page_size,
                sort_by=sort_by, sort_order=sort_order,
            )
            items = [_application_response(row).model_dump(mode="json", by_alias=True)
                     for row in rows]
            return {"items": items, "total": total, "page": page, "pageSize": page_size}
        return read("list_factory_applications", query)

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    def get_factory_application(application_id: str) -> dict[str, Any]:
        """按申请 ID 查询申请人、请求工厂、当前版本和状态。"""
        return read("get_factory_application", lambda user_id, _rid: _application_response(
            factories.get_factory_application(actor_id=user_id, application_id=application_id)
        ))

    @mcp.tool()
    def approve_factory_application(
        application_id: str, version: int, factory_id: str,
    ) -> dict[str, Any]:
        """仅在明确授权审核通过和绑定目标工厂后执行；需当前申请版本。"""
        return read(
            "approve_factory_application",
            lambda user_id, request_id: _application_response(
                factories.approve_factory_application(
                actor_id=user_id, application_id=application_id,
                expected_version=version, factory_id=factory_id, request_id=request_id,
                )
            ),
        )

    @mcp.tool()
    def reject_factory_application(
        application_id: str, version: int, reason: str,
    ) -> dict[str, Any]:
        """仅在明确授权拒绝申请及原因后执行；需当前申请版本。"""
        return read(
            "reject_factory_application",
            lambda user_id, request_id: _application_response(
                factories.reject_factory_application(
                actor_id=user_id, application_id=application_id,
                expected_version=version, reason=reason, request_id=request_id,
                )
            ),
        )

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    def list_users(
        role: Literal["factory", "admin"], factory_id: str | None = None,
        page: int = 1, page_size: int = 10, sort_by: str = "", sort_order: str = "asc",
    ) -> dict[str, Any]:
        """查询工厂用户；仅最高管理员可查询管理员。通过稳定 userId 和 version 操作。"""
        def query(user_id: str, _request_id: str) -> dict[str, Any]:
            page_args(page, page_size)
            allowed = {
                "", "displayName", "role", "phoneMasked", "isEnabled",
                "factoryName", "factoryPosition",
            }
            if sort_by not in allowed or sort_order not in {"asc", "desc"}:
                raise ValueError("invalid sort field")
            if role == "factory":
                factory_rows, total = factories.page_factory_users(
                    actor_id=user_id, factory_id=factory_id, page=page, page_size=page_size,
                    sort_by=sort_by, sort_order=sort_order,
                )
                items = [_factory_user_response(row).model_dump(mode="json", by_alias=True)
                         for row in factory_rows]
            else:
                if factory_id is not None:
                    raise ValueError("factory_id is only valid for factory users")
                admin_rows, total = identity.page_admin_users(
                    actor_id=user_id, page=page, page_size=page_size,
                    sort_by=sort_by, sort_order=sort_order,
                )
                items = [_user_response(row).model_dump(mode="json", by_alias=True)
                         for row in admin_rows]
            return {"items": items, "total": total, "page": page, "pageSize": page_size}
        return read("list_users", query)

    @mcp.tool(annotations=ToolAnnotations(destructiveHint=True))
    def set_user_enabled(
        target_user_id: str, version: int, enabled: bool,
    ) -> dict[str, Any]:
        """仅在明确授权启停指定 userId 后执行；管理员启停仅最高管理员可用，最高管理员不可停用。"""
        def change(user_id: str, request_id: str) -> Any:
            target = identity.get_user(user_id=target_user_id)
            if target.role == "factory":
                return _factory_user_response(factories.set_factory_user_enabled(
                    actor_id=user_id, target_user_id=target_user_id, enabled=enabled,
                    expected_version=version, request_id=request_id,
                ))
            return _user_response(identity.set_admin_enabled(
                actor_id=user_id, target_user_id=target_user_id, enabled=enabled,
                expected_version=version, request_id=request_id,
            ))
        return read("set_user_enabled", change)

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    def list_notifications(
        status: Literal["all", "unread"] = "all", page: int = 1, page_size: int = 10,
    ) -> dict[str, Any]:
        """查询本人通知及业务目标 targetType、targetId、targetPath。"""
        def query(user_id: str, _request_id: str) -> dict[str, Any]:
            admin(user_id)
            page_args(page, page_size)
            result = notifications.list_notifications(
                user_id=user_id, unread_only=status == "unread", page=page,
                page_size=page_size,
            )
            items = [_notification_response(row).model_dump(mode="json", by_alias=True)
                     for row in result.items]
            return {"items": items, "total": result.total,
                    "page": result.page, "pageSize": result.page_size}
        return read("list_notifications", query)

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    def get_unread_count() -> dict[str, Any]:
        """查询本人通知未读数。"""
        def query(user_id: str, _request_id: str) -> dict[str, Any]:
            admin(user_id)
            return {"count": notifications.unread_count(user_id=user_id)}
        return read("get_unread_count", query)

    @mcp.tool()
    def mark_notification_read(notification_id: int) -> dict[str, Any]:
        """按通知 ID 标记本人通知已读，并返回业务目标定位。"""
        def change(user_id: str, _request_id: str) -> Any:
            admin(user_id)
            try:
                return _notification_response(notifications.mark_read(
                    user_id=user_id, notification_id=notification_id,
                ))
            except KeyError as error:
                raise ResourceNotFound("notification not found") from error
        return read("mark_notification_read", change)
