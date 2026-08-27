from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Cookie, Header, HTTPException, Query, Request
from pydantic import Field

from app.api.contracts import ApiModel
from app.modules.identity_access import (
    IdentityAccessService,
    PermissionDenied,
    ResourceNotFound,
    SessionInvalid,
)
from app.modules.identity_access.service import UserSnapshot
from app.modules.notifications_audit import (
    AuditSnapshot,
    NotificationsAuditService,
    NotificationSnapshot,
)


class NotificationResponse(ApiModel):
    notification_id: int
    category: str
    event_type: str
    target_type: str
    target_id: str
    title: str
    summary: str
    target_path: str
    read_at: datetime | None
    created_at: datetime


class NotificationListResponse(ApiModel):
    items: list[NotificationResponse]
    total: int
    page: int
    page_size: int
    request_id: str


class UnreadCountResponse(ApiModel):
    count: int
    request_id: str


class NotificationAuthorizationsWrite(ApiModel):
    results: dict[str, Literal["accepted", "rejected", "closed"]] = Field(min_length=1)


class NotificationAuthorizationsResponse(ApiModel):
    recorded: int
    request_id: str


class AuditResponse(ApiModel):
    audit_id: int
    action: str
    target_type: str
    target_id: str
    changes: dict[str, object]
    actor_id: str | None
    operator_name: str
    source_terminal: str | None
    created_at: datetime


class AuditListResponse(ApiModel):
    items: list[AuditResponse]
    total: int
    page: int
    page_size: int
    request_id: str


def _notification_response(item: NotificationSnapshot) -> NotificationResponse:
    return NotificationResponse.model_validate(item, from_attributes=True)


def _audit_response(item: AuditSnapshot) -> AuditResponse:
    return AuditResponse.model_validate(item, from_attributes=True)


def create_notifications_audit_router(
    service: NotificationsAuditService,
    identity: IdentityAccessService,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1")

    def web_admin(
        token: str | None,
        csrf_token: str | None = None,
        *,
        require_csrf: bool = False,
    ) -> UserSnapshot:
        if not token:
            raise SessionInvalid("web session is missing")
        actor = identity.authenticate_session(
            token=token,
            terminal="web",
            csrf_token=csrf_token,
            require_csrf=require_csrf,
        )
        if actor.role != "admin":
            raise PermissionDenied("administrator role required")
        return actor

    def mini_user(authorization: str | None) -> UserSnapshot:
        if not authorization or not authorization.startswith("Bearer "):
            raise SessionInvalid("mini session is missing")
        token = authorization.removeprefix("Bearer ").strip()
        if not token:
            raise SessionInvalid("mini session is missing")
        return identity.authenticate_session(token=token, terminal="mini")

    def list_for_user(
        *,
        user_id: str,
        status: Literal["all", "unread"],
        page: int,
        page_size: int,
        request_id: str,
    ) -> NotificationListResponse:
        result = service.list_notifications(
            user_id=user_id,
            unread_only=status == "unread",
            page=page,
            page_size=page_size,
        )
        return NotificationListResponse(
            items=[_notification_response(item) for item in result.items],
            total=result.total,
            page=result.page,
            page_size=result.page_size,
            request_id=request_id,
        )

    @router.get("/admin/notifications", response_model=NotificationListResponse)
    def admin_notifications(
        request: Request,
        status: Literal["all", "unread"] = "all",
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=10, alias="pageSize", ge=1, le=100),
        ot_web_session: str | None = Cookie(default=None),
    ) -> NotificationListResponse:
        actor = web_admin(ot_web_session)
        return list_for_user(
            user_id=actor.user_id,
            status=status,
            page=page,
            page_size=page_size,
            request_id=request.state.request_id,
        )

    @router.get("/admin/notifications/unread-count", response_model=UnreadCountResponse)
    def admin_unread_count(
        request: Request,
        ot_web_session: str | None = Cookie(default=None),
    ) -> UnreadCountResponse:
        actor = web_admin(ot_web_session)
        return UnreadCountResponse(
            count=service.unread_count(user_id=actor.user_id),
            request_id=request.state.request_id,
        )

    @router.post(
        "/admin/notifications/{notification_id}/read", response_model=NotificationResponse
    )
    def admin_mark_read(
        notification_id: int,
        ot_web_session: str | None = Cookie(default=None),
        x_csrf_token: str | None = Header(default=None),
    ) -> NotificationResponse:
        actor = web_admin(ot_web_session, x_csrf_token, require_csrf=True)
        try:
            return _notification_response(
                service.mark_read(user_id=actor.user_id, notification_id=notification_id)
            )
        except KeyError as error:
            raise ResourceNotFound("notification not found") from error

    @router.get("/mini/notifications", response_model=NotificationListResponse)
    def mini_notifications(
        request: Request,
        status: Literal["all", "unread"] = "all",
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=10, alias="pageSize", ge=1, le=100),
        authorization: str | None = Header(default=None),
    ) -> NotificationListResponse:
        actor = mini_user(authorization)
        return list_for_user(
            user_id=actor.user_id,
            status=status,
            page=page,
            page_size=page_size,
            request_id=request.state.request_id,
        )

    @router.get("/mini/notifications/unread-count", response_model=UnreadCountResponse)
    def mini_unread_count(
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> UnreadCountResponse:
        actor = mini_user(authorization)
        return UnreadCountResponse(
            count=service.unread_count(user_id=actor.user_id),
            request_id=request.state.request_id,
        )

    @router.post("/mini/notifications/{notification_id}/read", response_model=NotificationResponse)
    def mini_mark_read(
        notification_id: int,
        authorization: str | None = Header(default=None),
    ) -> NotificationResponse:
        actor = mini_user(authorization)
        try:
            return _notification_response(
                service.mark_read(user_id=actor.user_id, notification_id=notification_id)
            )
        except KeyError as error:
            raise ResourceNotFound("notification not found") from error

    @router.post(
        "/mini/notification-authorizations",
        response_model=NotificationAuthorizationsResponse,
        status_code=201,
    )
    def record_authorizations(
        payload: NotificationAuthorizationsWrite,
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> NotificationAuthorizationsResponse:
        actor = mini_user(authorization)
        try:
            service.record_authorizations(user_id=actor.user_id, results=payload.results)
        except ValueError as error:
            raise HTTPException(status_code=422, detail="invalid authorization results") from error
        return NotificationAuthorizationsResponse(
            recorded=len(payload.results), request_id=request.state.request_id
        )

    @router.get("/admin/audit-logs", response_model=AuditListResponse)
    def audit_logs(
        request: Request,
        target_type: str | None = Query(default=None, alias="targetType"),
        target_id: str | None = Query(default=None, alias="targetId"),
        actor_id: str | None = Query(default=None, alias="actorId"),
        source_terminal: str | None = Query(default=None, alias="sourceTerminal"),
        created_from: Annotated[datetime | None, Query(alias="createdFrom")] = None,
        created_to: Annotated[datetime | None, Query(alias="createdTo")] = None,
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=20, alias="pageSize", ge=1, le=100),
        ot_web_session: str | None = Cookie(default=None),
    ) -> AuditListResponse:
        actor = web_admin(ot_web_session)
        result = service.list_audit_logs(
            actor_user_id=actor.user_id,
            target_type=target_type,
            target_id=target_id,
            filter_actor_id=actor_id,
            source_terminal=source_terminal,
            created_from=created_from,
            created_to=created_to,
            page=page,
            page_size=page_size,
        )
        return AuditListResponse(
            items=[_audit_response(item) for item in result.items],
            total=result.total,
            page=result.page,
            page_size=result.page_size,
            request_id=request.state.request_id,
        )

    return router
