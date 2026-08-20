import secrets
from collections.abc import Awaitable, Callable, Sequence
from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.adapters.avatar import DisabledAvatarStore, FakeAvatarStore
from app.adapters.errors import ExternalAdapterUnavailable
from app.adapters.identity import DisabledFeishuIdentity
from app.adapters.sms import DisabledSmsSender, FakeSmsSender
from app.adapters.wechat import DisabledWechatIdentity
from app.api.identity import create_identity_router
from app.api.router import api_router
from app.db.session import create_database_engine, create_session_factory
from app.local_demo import (
    LOCAL_DEMO_FEISHU_SCOPE,
    LOCAL_DEMO_VERIFICATION_CODE,
    LocalDemoFeishuIdentity,
    LocalDemoWechatIdentity,
    create_local_demo_router,
)
from app.logging import StructuredLogger, configure_uvicorn_access_log_redaction
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
from app.settings.config import Settings


def create_app(
    *,
    database_url: str | None = None,
    event_logger: StructuredLogger | None = None,
    identity_service: IdentityAccessService | None = None,
    extra_routers: Sequence[APIRouter] = (),
) -> FastAPI:
    settings = Settings(database_url=database_url) if database_url is not None else Settings()
    resolved_database_url = settings.database_url
    engine = create_database_engine(resolved_database_url)
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
        feishu_identity = (
            LocalDemoFeishuIdentity()
            if local_demo_enabled
            else DisabledFeishuIdentity(scope=settings.feishu_identity_scope)
        )
        sms_sender = FakeSmsSender() if local_demo_enabled else DisabledSmsSender()
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
            create_session_factory(engine),
            feishu_identity=feishu_identity,
            sms_sender=sms_sender,
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
            verification_code_factory=(
                (lambda: LOCAL_DEMO_VERIFICATION_CODE) if local_demo_enabled else None
            ),
        )
        if local_demo_enabled:
            identity_service.bootstrap_super_admin(
                scope=LOCAL_DEMO_FEISHU_SCOPE,
                profile=LocalDemoFeishuIdentity().exchange_code(code="super"),
                operator_source="local-demo-startup",
                request_id="local-demo-bootstrap",
            )
    app.include_router(
        create_identity_router(
            identity_service,
            secure_web_cookies=not local_demo_enabled,
        )
    )
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
