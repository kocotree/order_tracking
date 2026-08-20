from collections.abc import Awaitable, Callable, Sequence
from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.router import api_router
from app.db.session import create_database_engine
from app.logging import StructuredLogger
from app.settings.config import Settings


def create_app(
    *,
    database_url: str | None = None,
    event_logger: StructuredLogger | None = None,
    extra_routers: Sequence[APIRouter] = (),
) -> FastAPI:
    resolved_database_url = database_url or Settings().database_url
    engine = create_database_engine(resolved_database_url)
    logger = event_logger or StructuredLogger()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):  # type: ignore[no-untyped-def]
        yield
        engine.dispose()

    app = FastAPI(title="Order Tracking API", version="0.1.0", lifespan=lifespan)
    app.include_router(api_router)

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
