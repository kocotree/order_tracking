from datetime import date, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Cookie, Header, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field, StrictInt

from app.modules.identity_access import IdentityAccessService, PermissionDenied, SessionInvalid
from app.modules.identity_access.service import UserSnapshot
from app.modules.orders import (
    AssignmentInput,
    DraftLineInput,
    OrderAuditSnapshot,
    OrderNotFound,
    OrderService,
    OrderSnapshot,
)


def to_camel(value: str) -> str:
    first, *rest = value.split("_")
    return first + "".join(part.capitalize() for part in rest)


class ApiModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class AssignmentWrite(ApiModel):
    factory_id: str = Field(min_length=1)
    quantity: StrictInt = Field(gt=0)


class DraftLineWrite(ApiModel):
    variant_id: str = Field(min_length=1)
    order_quantity: StrictInt = Field(gt=0)
    assignments: list[AssignmentWrite] = []


class DraftCreate(ApiModel):
    order_no: str = Field(min_length=1, max_length=100)
    order_date: date
    tracker: Literal["烧麦", "松子", "橄榄", "大葱", "青椒"]
    contract_ship_date: date
    lines: list[DraftLineWrite] = Field(min_length=1)


class DraftUpdate(DraftCreate):
    version: StrictInt = Field(gt=0)


class VersionWrite(ApiModel):
    version: StrictInt = Field(gt=0)


class ReopenWrite(ApiModel):
    reason: str = Field(min_length=1, max_length=500)


class AssignmentResponse(ApiModel):
    assignment_id: int
    factory_id: str
    factory_name: str
    assigned_quantity: int
    shipped_quantity: int
    pending_quantity: int
    over_quantity: int
    short_quantity: int
    progress_percent: int


class OrderLineResponse(ApiModel):
    order_line_id: int
    variant_id: str
    sku_id: str
    product_name: str
    properties_value: str
    category: str | None
    image_object_key: str | None
    order_quantity: int
    shipped_quantity: int
    pending_quantity: int
    over_quantity: int
    short_quantity: int
    progress_percent: int
    assignments: list[AssignmentResponse]


class FactoryProgressResponse(ApiModel):
    factory_id: str
    factory_name: str
    order_quantity: int
    shipped_quantity: int
    pending_quantity: int
    over_quantity: int
    short_quantity: int
    progress_percent: int


class OrderResponse(ApiModel):
    order_id: str
    order_no: str
    source: str
    order_date: date
    tracker: str
    contract_ship_date: date
    lifecycle: str
    display_status: str
    version: int
    total_quantity: int
    shipped_quantity: int
    pending_quantity: int
    over_quantity: int
    short_quantity: int
    progress_percent: int
    lines: list[OrderLineResponse]
    factory_progress: list[FactoryProgressResponse]
    validation_issues: list[str]
    created_at: datetime
    updated_at: datetime
    request_id: str = ""


class OrderListResponse(ApiModel):
    items: list[OrderResponse]
    total: int
    page: int
    page_size: int
    request_id: str


class DashboardResponse(ApiModel):
    overdue_orders: int
    pending_import_orders: int
    today_shipments: int
    recent_orders: list[OrderResponse]
    request_id: str


class AuditLogResponse(ApiModel):
    action: str
    changes: dict[str, object]
    actor_id: str | None
    source_terminal: str | None
    created_at: datetime


class AuditLogListResponse(ApiModel):
    items: list[AuditLogResponse]
    total: int
    request_id: str


def _draft_lines(items: list[DraftLineWrite]) -> list[DraftLineInput]:
    return [
        DraftLineInput(
            variant_id=item.variant_id,
            order_quantity=item.order_quantity,
            assignments=[
                AssignmentInput(factory_id=value.factory_id, quantity=value.quantity)
                for value in item.assignments
            ],
        )
        for item in items
    ]


def _order_response(order: OrderSnapshot, request_id: str) -> OrderResponse:
    payload = OrderResponse.model_validate(order, from_attributes=True)
    return payload.model_copy(update={"request_id": request_id})


def _audit_response(item: OrderAuditSnapshot) -> AuditLogResponse:
    return AuditLogResponse.model_validate(item, from_attributes=True)


def create_order_router(
    service: OrderService,
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

    def query_user(
        web_token: str | None, authorization: str | None
    ) -> tuple[UserSnapshot, str]:
        if web_token:
            return identity.authenticate_session(token=web_token, terminal="web"), "web"
        if authorization and authorization.startswith("Bearer "):
            token = authorization.removeprefix("Bearer ").strip()
            if token:
                return identity.authenticate_session(token=token, terminal="mini"), "mini"
        raise SessionInvalid("session is missing")

    @router.post(
        "/admin/orders",
        response_model=OrderResponse,
        status_code=201,
        tags=["order-admin"],
    )
    def create_draft(
        payload: DraftCreate,
        request: Request,
        ot_web_session: str | None = Cookie(default=None),
        x_csrf_token: str | None = Header(default=None),
    ) -> OrderResponse:
        actor = web_admin(ot_web_session, x_csrf_token, require_csrf=True)
        result = service.create_draft(
            actor_id=actor.user_id,
            order_no=payload.order_no,
            order_date=payload.order_date,
            tracker=payload.tracker,
            contract_ship_date=payload.contract_ship_date,
            lines=_draft_lines(payload.lines),
            request_id=request.state.request_id,
        )
        return _order_response(result, request.state.request_id)

    @router.put(
        "/admin/orders/{order_id}",
        response_model=OrderResponse,
        tags=["order-admin"],
    )
    def save_draft(
        order_id: str,
        payload: DraftUpdate,
        request: Request,
        ot_web_session: str | None = Cookie(default=None),
        x_csrf_token: str | None = Header(default=None),
    ) -> OrderResponse:
        actor = web_admin(ot_web_session, x_csrf_token, require_csrf=True)
        result = service.save_draft(
            actor_id=actor.user_id,
            order_id=order_id,
            version=payload.version,
            order_no=payload.order_no,
            order_date=payload.order_date,
            tracker=payload.tracker,
            contract_ship_date=payload.contract_ship_date,
            lines=_draft_lines(payload.lines),
            request_id=request.state.request_id,
        )
        return _order_response(result, request.state.request_id)

    @router.post(
        "/admin/orders/{order_id}/publish",
        response_model=OrderResponse,
        tags=["order-admin"],
    )
    def publish(
        order_id: str,
        payload: VersionWrite,
        request: Request,
        idempotency_key: str = Header(alias="Idempotency-Key"),
        ot_web_session: str | None = Cookie(default=None),
        x_csrf_token: str | None = Header(default=None),
    ) -> OrderResponse:
        actor = web_admin(ot_web_session, x_csrf_token, require_csrf=True)
        result = service.publish(
            actor_id=actor.user_id,
            order_id=order_id,
            version=payload.version,
            request_id=request.state.request_id,
            idempotency_key=idempotency_key,
        )
        return _order_response(result, request.state.request_id)

    def transition_actor(
        ot_web_session: str | None, x_csrf_token: str | None
    ) -> UserSnapshot:
        return web_admin(ot_web_session, x_csrf_token, require_csrf=True)

    @router.post(
        "/admin/orders/{order_id}/withdraw",
        response_model=OrderResponse,
        tags=["order-admin"],
    )
    def withdraw(
        order_id: str,
        request: Request,
        idempotency_key: str = Header(alias="Idempotency-Key"),
        ot_web_session: str | None = Cookie(default=None),
        x_csrf_token: str | None = Header(default=None),
    ) -> OrderResponse:
        actor = transition_actor(ot_web_session, x_csrf_token)
        result = service.withdraw(
            actor_id=actor.user_id,
            order_id=order_id,
            request_id=request.state.request_id,
            idempotency_key=idempotency_key,
        )
        return _order_response(result, request.state.request_id)

    @router.delete(
        "/admin/orders/{order_id}",
        status_code=204,
        tags=["order-admin"],
    )
    def delete_order(
        order_id: str,
        request: Request,
        idempotency_key: str = Header(alias="Idempotency-Key"),
        ot_web_session: str | None = Cookie(default=None),
        x_csrf_token: str | None = Header(default=None),
    ) -> Response:
        actor = transition_actor(ot_web_session, x_csrf_token)
        service.delete(
            actor_id=actor.user_id,
            order_id=order_id,
            request_id=request.state.request_id,
            idempotency_key=idempotency_key,
        )
        return Response(status_code=204)

    @router.post(
        "/admin/orders/{order_id}/complete",
        response_model=OrderResponse,
        tags=["order-admin"],
    )
    def complete(
        order_id: str,
        request: Request,
        idempotency_key: str = Header(alias="Idempotency-Key"),
        ot_web_session: str | None = Cookie(default=None),
        x_csrf_token: str | None = Header(default=None),
    ) -> OrderResponse:
        actor = transition_actor(ot_web_session, x_csrf_token)
        result = service.complete(
            actor_id=actor.user_id,
            order_id=order_id,
            request_id=request.state.request_id,
            idempotency_key=idempotency_key,
        )
        return _order_response(result, request.state.request_id)

    @router.post(
        "/admin/orders/{order_id}/reopen",
        response_model=OrderResponse,
        tags=["order-admin"],
    )
    def reopen(
        order_id: str,
        payload: ReopenWrite,
        request: Request,
        idempotency_key: str = Header(alias="Idempotency-Key"),
        ot_web_session: str | None = Cookie(default=None),
        x_csrf_token: str | None = Header(default=None),
    ) -> OrderResponse:
        actor = transition_actor(ot_web_session, x_csrf_token)
        result = service.reopen(
            actor_id=actor.user_id,
            order_id=order_id,
            reason=payload.reason,
            request_id=request.state.request_id,
            idempotency_key=idempotency_key,
        )
        return _order_response(result, request.state.request_id)

    @router.get("/orders", response_model=OrderListResponse, tags=["orders"])
    def list_orders(
        request: Request,
        keyword: str = Query(default="", max_length=255),
        status: str = Query(default="all"),
        factory_id: Annotated[str | None, Query(alias="factoryId")] = None,
        trackers: Annotated[list[str] | None, Query()] = None,
        ship_date_from: Annotated[date | None, Query(alias="shipDateFrom")] = None,
        ship_date_to: Annotated[date | None, Query(alias="shipDateTo")] = None,
        sort_by: Annotated[str, Query(alias="sortBy")] = "priority",
        include_drafts: Annotated[bool, Query(alias="includeDrafts")] = False,
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[int, Query(alias="pageSize", ge=1, le=100)] = 20,
        ot_web_session: str | None = Cookie(default=None),
        authorization: str | None = Header(default=None),
    ) -> OrderListResponse:
        actor, terminal = query_user(ot_web_session, authorization)
        allow_drafts = terminal == "web" and actor.role == "admin" and include_drafts
        items, total = service.list_visible(
            actor_id=actor.user_id,
            include_drafts=allow_drafts,
            keyword=keyword,
            status=status,
            factory_id=factory_id,
            trackers=trackers,
            ship_date_from=ship_date_from,
            ship_date_to=ship_date_to,
            sort_by=sort_by,
            page=page,
            page_size=page_size,
        )
        return OrderListResponse(
            items=[_order_response(item, request.state.request_id) for item in items],
            total=total,
            page=page,
            page_size=page_size,
            request_id=request.state.request_id,
        )

    @router.get("/orders/{order_id}", response_model=OrderResponse, tags=["orders"])
    def get_order(
        order_id: str,
        request: Request,
        ot_web_session: str | None = Cookie(default=None),
        authorization: str | None = Header(default=None),
    ) -> OrderResponse:
        actor, terminal = query_user(ot_web_session, authorization)
        result = service.get_visible(actor_id=actor.user_id, order_id=order_id)
        if terminal == "mini" and result.lifecycle == "DRAFT":
            raise OrderNotFound("order not found")
        return _order_response(result, request.state.request_id)

    @router.get(
        "/admin/dashboard/orders",
        response_model=DashboardResponse,
        tags=["order-admin"],
    )
    def dashboard(
        request: Request,
        ot_web_session: str | None = Cookie(default=None),
    ) -> DashboardResponse:
        actor = web_admin(ot_web_session)
        items, _ = service.list_visible(
            actor_id=actor.user_id,
            include_drafts=False,
            page_size=100,
            sort_by="updatedDesc",
        )
        return DashboardResponse(
            overdue_orders=sum(item.display_status == "已逾期" for item in items),
            pending_import_orders=0,
            today_shipments=0,
            recent_orders=[
                _order_response(item, request.state.request_id) for item in items[:5]
            ],
            request_id=request.state.request_id,
        )

    @router.get(
        "/admin/orders/{order_id}/audit-logs",
        response_model=AuditLogListResponse,
        tags=["order-admin"],
    )
    def audit_logs(
        order_id: str,
        request: Request,
        ot_web_session: str | None = Cookie(default=None),
    ) -> AuditLogListResponse:
        actor = web_admin(ot_web_session)
        items = service.list_audit_logs(actor_id=actor.user_id, order_id=order_id)
        return AuditLogListResponse(
            items=[_audit_response(item) for item in items],
            total=len(items),
            request_id=request.state.request_id,
        )

    return router
