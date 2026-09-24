from datetime import datetime

from fastapi import APIRouter, Cookie, Header, Request
from pydantic import BaseModel, ConfigDict, Field

from app.modules.identity_access import IdentityAccessService, SessionInvalid
from app.modules.identity_access.service import UserSnapshot
from app.modules.incoming_differences import IncomingDifferenceService, IncomingDifferenceView


def to_camel(value: str) -> str:
    first, *rest = value.split("_")
    return first + "".join(part.capitalize() for part in rest)


class ApiModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class IncomingDifferenceResponse(ApiModel):
    sequence: int
    registered_at: datetime
    product_name: str
    spec: str
    quantity: int
    record_id: str | None = None
    purchase_order_id: str | None = None
    product_code: str | None = None
    version: int | None = None


class IncomingDifferenceListResponse(ApiModel):
    items: list[IncomingDifferenceResponse]
    total: int
    request_id: str


class IncomingDifferenceUpdateRequest(ApiModel):
    quantity: int
    version: int = Field(ge=1)


class IncomingDifferenceUpdateResponse(IncomingDifferenceResponse):
    record_id: str
    version: int
    request_id: str


def _item(view: IncomingDifferenceView) -> IncomingDifferenceResponse:
    return IncomingDifferenceResponse.model_validate(view, from_attributes=True)


def create_incoming_difference_router(
    service: IncomingDifferenceService, identity: IdentityAccessService
) -> APIRouter:
    router = APIRouter(prefix="/api/v1")

    def query_user(web_token: str | None, authorization: str | None) -> UserSnapshot:
        if web_token:
            return identity.authenticate_session(token=web_token, terminal="web")
        if authorization and authorization.startswith("Bearer "):
            token = authorization.removeprefix("Bearer ").strip()
            if token:
                return identity.authenticate_session(token=token, terminal="mini")
        raise SessionInvalid("session is missing")

    @router.get(
        "/orders/{order_id}/incoming-differences",
        response_model=IncomingDifferenceListResponse,
        response_model_exclude_none=True,
        tags=["orders"],
    )
    def list_incoming_differences(
        order_id: str,
        request: Request,
        ot_web_session: str | None = Cookie(default=None),
        authorization: str | None = Header(default=None),
    ) -> IncomingDifferenceListResponse:
        actor = query_user(ot_web_session, authorization)
        views = service.list_for_order(actor_id=actor.user_id, order_id=order_id)
        return IncomingDifferenceListResponse(
            items=[_item(view) for view in views],
            total=len(views),
            request_id=request.state.request_id,
        )

    @router.patch(
        "/admin/orders/{order_id}/incoming-differences/{record_id}",
        response_model=IncomingDifferenceUpdateResponse,
        tags=["orders"],
    )
    def update_incoming_difference_quantity(
        order_id: str,
        record_id: str,
        payload: IncomingDifferenceUpdateRequest,
        request: Request,
        ot_web_session: str | None = Cookie(default=None),
        authorization: str | None = Header(default=None),
    ) -> IncomingDifferenceUpdateResponse:
        actor = query_user(ot_web_session, authorization)
        view = service.adjust_quantity(
            actor_id=actor.user_id,
            order_id=order_id,
            record_id=record_id,
            quantity=payload.quantity,
            version=payload.version,
            request_id=request.state.request_id,
        )
        item = _item(view)
        return IncomingDifferenceUpdateResponse(
            **item.model_dump(), request_id=request.state.request_id
        )

    return router
