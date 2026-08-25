import secrets
from collections.abc import Awaitable, Callable, Sequence
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.adapters.avatar import DisabledAvatarStore, FakeAvatarStore
from app.adapters.errors import ExternalAdapterUnavailable
from app.adapters.identity import (
    AppCredentialFeishuIdentity,
    DisabledFeishuIdentity,
    FeishuIdentity,
    FeishuIdentityConfig,
)
from app.adapters.private_files import (
    DisabledPrivateFileStore,
    FakePrivateFileStore,
    MinioPrivateFileStore,
    PrivateFileStore,
)
from app.adapters.wechat import DisabledWechatIdentity
from app.api.contracts import create_contract_router
from app.api.factory_access import create_factory_router
from app.api.identity import create_identity_router
from app.api.order_import import create_order_import_router
from app.api.orders import create_order_router
from app.api.products import create_product_router
from app.api.shipments import create_shipment_router
from app.api.router import api_router
from app.db.session import create_database_engine, create_session_factory
from app.local_demo import (
    LOCAL_DEMO_FEISHU_SCOPE,
    LocalDemoFeishuIdentity,
    LocalDemoWechatIdentity,
    create_local_demo_router,
)
from app.logging import StructuredLogger, configure_uvicorn_access_log_redaction
from app.modules.contracts import (
    ContractConflict,
    ContractError,
    ContractGenerationError,
    ContractNotFound,
    ContractPermissionDenied,
    ContractService,
    ContractValidationError,
)
from app.modules.contracts.workbook import ContractWorkbookRenderer
from app.modules.factory_access import FactoryAccessService
from app.modules.identity_access import (
    ApplicationConflict,
    AvatarInvalid,
    IdentityAccessError,
    OAuthStateInvalid,
    PermissionDenied,
    ResourceNotFound,
    SessionInvalid,
    SmsRateLimited,
    VerificationInvalid,
)
from app.modules.identity_access.service import IdentityAccessService
from app.modules.order_import import OrderImportService
from app.modules.orders import (
    OrderConflict,
    OrderError,
    OrderNotFound,
    OrderPermissionDenied,
    OrderService,
    OrderValidationError,
)
from app.modules.product_sync import ProductCatalogService
from app.modules.shipments import (
    ShipmentError,
    ShipmentNotFound,
    ShipmentPermissionDenied,
    ShipmentService,
)
from app.product_demo import seed_local_demo_products
from app.settings.config import Settings


def create_app(
    *,
    database_url: str | None = None,
    event_logger: StructuredLogger | None = None,
    identity_service: IdentityAccessService | None = None,
    factory_service: FactoryAccessService | None = None,
    product_service: ProductCatalogService | None = None,
    order_service: OrderService | None = None,
    order_import_service: OrderImportService | None = None,
    contract_service: ContractService | None = None,
    shipment_service: ShipmentService | None = None,
    extra_routers: Sequence[APIRouter] = (),
) -> FastAPI:
    settings = Settings(database_url=database_url) if database_url is not None else Settings()
    resolved_database_url = settings.database_url
    engine = create_database_engine(resolved_database_url)
    session_factory = create_session_factory(engine)
    logger = event_logger or StructuredLogger()
    configure_uvicorn_access_log_redaction()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):  # type: ignore[no-untyped-def]
        yield
        engine.dispose()

    app = FastAPI(title="Order Tracking API", version="0.1.0", lifespan=lifespan)
    app.include_router(api_router)
    local_demo_enabled = settings.app_env == "local_demo"
    if identity_service is None:
        feishu_identity: FeishuIdentity
        feishu_identity_app_id = (
            settings.feishu_identity_app_id or settings.feishu_order_app_id
        )
        feishu_identity_app_secret = (
            settings.feishu_identity_app_secret or settings.feishu_order_app_secret
        )
        if local_demo_enabled:
            feishu_identity = LocalDemoFeishuIdentity()
        elif all(
            (
                feishu_identity_app_id,
                feishu_identity_app_secret,
                settings.feishu_identity_redirect_uri,
            )
        ):
            feishu_identity = AppCredentialFeishuIdentity(
                FeishuIdentityConfig(
                    app_id=feishu_identity_app_id,
                    app_secret=feishu_identity_app_secret,
                    redirect_uri=settings.feishu_identity_redirect_uri,
                )
            )
        else:
            feishu_identity = DisabledFeishuIdentity(
                scope=settings.feishu_identity_scope
            )
        wechat_identity = (
            LocalDemoWechatIdentity()
            if local_demo_enabled
            else DisabledWechatIdentity(scope=settings.wechat_identity_scope)
        )
        avatar_store = (
            FakeAvatarStore(bucket="local-demo-private-avatar")
            if local_demo_enabled
            else DisabledAvatarStore(bucket=settings.avatar_bucket)
        )
        identity_service = IdentityAccessService(
            session_factory,
            feishu_identity=feishu_identity,
            wechat_identity=wechat_identity,
            avatar_store=avatar_store,
            token_secret=(
                settings.identity_token_secret.encode()
                if settings.identity_token_secret
                else secrets.token_bytes(32)
            ),
            phone_encryption_secret=(
                settings.phone_encryption_secret.encode()
                if settings.phone_encryption_secret
                else secrets.token_bytes(32)
            ),
            phone_digest_secret=(
                settings.phone_digest_secret.encode()
                if settings.phone_digest_secret
                else secrets.token_bytes(32)
            ),
        )
        if local_demo_enabled:
            identity_service.bootstrap_super_admin(
                scope=LOCAL_DEMO_FEISHU_SCOPE,
                profile=LocalDemoFeishuIdentity().exchange_code(code="super"),
                operator_source="local-demo-startup",
                request_id="local-demo-bootstrap",
            )
    if factory_service is None:
        factory_service = FactoryAccessService(session_factory)
    if product_service is None:
        product_service = ProductCatalogService(session_factory)
    if order_service is None:
        order_service = OrderService(session_factory)
    if order_import_service is None:
        order_import_service = OrderImportService(session_factory)
    if contract_service is None:
        private_file_store: PrivateFileStore
        if local_demo_enabled:
            private_file_store = FakePrivateFileStore(bucket="local-demo-contract-files")
        elif all(
            (
                settings.private_file_endpoint,
                settings.private_file_access_key,
                settings.private_file_secret_key,
            )
        ):
            private_file_store = MinioPrivateFileStore(
                endpoint=settings.private_file_endpoint,
                access_key=settings.private_file_access_key,
                secret_key=settings.private_file_secret_key,
                bucket=settings.private_file_bucket,
                secure=settings.private_file_secure,
            )
        else:
            private_file_store = DisabledPrivateFileStore(
                bucket=settings.private_file_bucket
            )
        contract_service = ContractService(
            session_factory,
            workbook_renderer=ContractWorkbookRenderer(
                template_path=(
                    Path(__file__).resolve().parent
                    / "templates/processing_contract_v1.xlsx"
                ),
                image_loader=lambda object_key: private_file_store.get(
                    object_key=object_key
                ),
            ),
            file_store=private_file_store,
        )
    if shipment_service is None:
        shipment_service = ShipmentService(session_factory)
    if local_demo_enabled:
        seed_local_demo_products(session_factory)
    app.include_router(
        create_identity_router(
            identity_service,
            factory_service=factory_service,
            secure_web_cookies=(
                settings.web_cookie_secure if not local_demo_enabled else False
            ),
        )
    )
    app.include_router(create_factory_router(factory_service, identity_service))
    app.include_router(create_product_router(product_service, identity_service))
    app.include_router(
        create_order_router(
            order_service, identity_service, order_import_service=order_import_service
        )
    )
    app.include_router(create_order_import_router(order_import_service, identity_service))
    app.include_router(create_contract_router(contract_service, identity_service))
    app.include_router(create_shipment_router(shipment_service, identity_service))
    if local_demo_enabled:
        app.include_router(create_local_demo_router())

    @app.middleware("http")
    async def attach_request_id(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request_id = uuid4().hex
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        logger.event(
            "request.completed",
            request_id=request_id,
            fields={
                "method": request.method,
                "path": request.url.path,
                "statusCode": response.status_code,
            },
        )
        return response

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, _error: Exception) -> JSONResponse:
        request_id = request.state.request_id
        logger.event(
            "request.failed",
            request_id=request_id,
            fields={"method": request.method, "path": request.url.path, "statusCode": 500},
        )
        return JSONResponse(
            status_code=500,
            headers={"X-Request-ID": request_id},
            content={
                "code": "internal_error",
                "message": "服务器内部错误",
                "requestId": request_id,
            },
        )

    @app.exception_handler(IdentityAccessError)
    async def handle_identity_error(
        request: Request,
        error: IdentityAccessError,
    ) -> JSONResponse:
        if isinstance(error, SessionInvalid):
            status_code, code, message = 401, "session_invalid", "登录状态无效或已失效"
        elif isinstance(error, PermissionDenied):
            status_code, code, message = 403, "permission_denied", "没有权限执行该操作"
        elif isinstance(error, ResourceNotFound):
            status_code, code, message = 404, "not_found", "资源不存在"
        elif isinstance(error, ApplicationConflict):
            status_code, code, message = 409, "conflict", "数据状态已变化，请刷新后重试"
        elif isinstance(error, SmsRateLimited):
            status_code, code, message = 429, "rate_limited", "操作过于频繁，请稍后重试"
        elif isinstance(error, OAuthStateInvalid):
            status_code, code, message = 422, "oauth_state_invalid", "登录状态校验失败"
        elif isinstance(error, (VerificationInvalid, AvatarInvalid)):
            status_code, code, message = 422, "validation_failed", "提交内容校验失败"
        else:
            status_code, code, message = 422, "identity_error", "身份操作失败"
        return JSONResponse(
            status_code=status_code,
            content={
                "code": code,
                "message": message,
                "requestId": request.state.request_id,
            },
        )

    @app.exception_handler(ExternalAdapterUnavailable)
    async def handle_external_adapter_error(
        request: Request,
        _error: ExternalAdapterUnavailable,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content={
                "code": "external_service_unavailable",
                "message": "外部服务暂不可用",
                "requestId": request.state.request_id,
            },
        )

    @app.exception_handler(OrderError)
    async def handle_order_error(request: Request, error: OrderError) -> JSONResponse:
        if isinstance(error, OrderPermissionDenied):
            status_code, code, message = 403, "permission_denied", "没有权限执行该操作"
        elif isinstance(error, OrderNotFound):
            status_code, code, message = 404, "not_found", "订单不存在"
        elif isinstance(error, OrderConflict):
            status_code, code, message = 409, "conflict", "订单状态已变化，请刷新后重试"
        elif isinstance(error, OrderValidationError):
            status_code, code, message = 400, "validation_failed", str(error)
        else:
            status_code, code, message = 400, "order_error", "订单操作失败"
        return JSONResponse(
            status_code=status_code,
            content={"code": code, "message": message, "requestId": request.state.request_id},
        )

    @app.exception_handler(ContractError)
    async def handle_contract_error(
        request: Request, error: ContractError
    ) -> JSONResponse:
        if isinstance(error, ContractPermissionDenied):
            status_code, code, message = 403, "permission_denied", "没有权限执行该操作"
        elif isinstance(error, ContractNotFound):
            status_code, code, message = 404, "not_found", "合同或导出文件不存在"
        elif isinstance(error, ContractConflict):
            status_code, code, message = 409, "conflict", str(error)
        elif isinstance(error, ContractValidationError):
            status_code, code, message = 422, "validation_failed", str(error)
        elif isinstance(error, ContractGenerationError):
            status_code, code, message = 500, "contract_generation_failed", "合同文件生成失败"
        else:
            status_code, code, message = 400, "contract_error", "合同操作失败"
        return JSONResponse(
            status_code=status_code,
            content={"code": code, "message": message, "requestId": request.state.request_id},
        )

    @app.exception_handler(ShipmentError)
    async def handle_shipment_error(
        request: Request, error: ShipmentError
    ) -> JSONResponse:
        if isinstance(error, ShipmentPermissionDenied):
            status_code, code, message = 403, "permission_denied", "没有权限执行该操作"
        elif isinstance(error, ShipmentNotFound):
            status_code, code, message = 404, "not_found", "发货单或订单不存在"
        else:
            status_code, code, message = 400, "shipment_error", "发货单操作失败"
        return JSONResponse(
            status_code=status_code,
            content={"code": code, "message": message, "requestId": request.state.request_id},
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(request: Request, error: StarletteHTTPException) -> JSONResponse:
        not_found = error.status_code == 404
        return JSONResponse(
            status_code=error.status_code,
            content={
                "code": "not_found" if not_found else "http_error",
                "message": "资源不存在" if not_found else "请求失败",
                "requestId": request.state.request_id,
            },
        )

    @app.get("/health/live", tags=["health"])
    def liveness(request: Request) -> dict[str, Any]:
        return {"status": "ok", "requestId": request.state.request_id}

    @app.get("/health/ready", tags=["health"])
    def readiness(request: Request) -> Response:
        request_id = request.state.request_id
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
        except SQLAlchemyError:
            return JSONResponse(
                status_code=503,
                content={
                    "code": "service_unavailable",
                    "message": "数据库暂不可用",
                    "requestId": request_id,
                },
            )
        return JSONResponse(content={"status": "ready", "requestId": request_id})

    for router in extra_routers:
        app.include_router(router)

    return app
