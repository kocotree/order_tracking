from datetime import date, datetime

from fastapi import APIRouter, Cookie, Header, Request, Response
from pydantic import BaseModel, ConfigDict, Field, StrictInt

from app.modules.identity_access import IdentityAccessService, PermissionDenied, SessionInvalid
from app.modules.identity_access.service import UserSnapshot
from app.modules.shipments import (
    DraftBoxInput,
    DraftItemInput,
    ShipmentDraftSnapshot,
    ShipmentService,
    ShipmentValidationError,
)


def to_camel(value: str) -> str:
    first, *rest = value.split("_")
    return first + "".join(part.capitalize() for part in rest)


class ApiModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class DraftCreate(ApiModel):
    preferred_order_id: str | None = None


class ShipmentDraftResponse(ApiModel):
    shipment_id: str
    status: str
    factory_id: str
    factory_name: str = ""
    created_by: str
    preferred_order_id: str | None
    shipment_no: str | None = None
    business_date: date | None = None
    note: str = ""
    total_boxes: int = 0
    total_quantity: int = 0
    created_at: datetime
    submitted_at: datetime | None = None
    lines: list["ShipmentLineResponse"] = []
    boxes: list["ShipmentBoxResponse"] = []


class DraftItemWrite(ApiModel):
    assignment_id: StrictInt = Field(gt=0)
    quantity: StrictInt = Field(gt=0)


class DraftBoxWrite(ApiModel):
    box_no: StrictInt = Field(gt=0)
    group_key: str | None = None
    items: list[DraftItemWrite] = Field(min_length=1)


class DraftSave(ApiModel):
    boxes: list[DraftBoxWrite] = Field(min_length=1)
    note: str = Field(default="", max_length=500)


class ShipmentLineResponse(ApiModel):
    assignment_id: int
    order_id: str
    order_no: str
    sku_id: str
    product_name: str
    properties_value: str
    quantity: int


class ShipmentBoxResponse(ApiModel):
    box_no: int
    group_key: str | None
    items: list[ShipmentLineResponse]


class ShipmentListResponse(ApiModel):
    items: list[ShipmentDraftResponse]
    total: int


class ShipmentCatalogItemResponse(ApiModel):
    assignment_id: int
    order_id: str
    order_no: str
    contract_ship_date: date
    product_name: str
    properties_value: str
    assigned_quantity: int
    shipped_quantity: int
    pending_quantity: int


class ShipmentCatalogResponse(ApiModel):
    items: list[ShipmentCatalogItemResponse]
    total: int


def _draft_response(draft: ShipmentDraftSnapshot) -> ShipmentDraftResponse:
    return ShipmentDraftResponse.model_validate(draft, from_attributes=True)


def create_shipment_router(
    service: ShipmentService,
    identity: IdentityAccessService,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1")

    def factory_user(authorization: str | None) -> UserSnapshot:
        if not authorization or not authorization.startswith("Bearer "):
            raise SessionInvalid("mini-program session is missing")
        token = authorization.removeprefix("Bearer ").strip()
        if not token:
            raise SessionInvalid("mini-program session is missing")
        actor = identity.authenticate_session(token=token, terminal="mini")
        if actor.role != "factory" or actor.factory_id is None:
            raise PermissionDenied("factory role required")
        return actor

    def query_user(web_token: str | None, authorization: str | None) -> tuple[UserSnapshot, str]:
        if web_token:
            return identity.authenticate_session(token=web_token, terminal="web"), "web"
        if authorization and authorization.startswith("Bearer "):
            token = authorization.removeprefix("Bearer ").strip()
            if token:
                return identity.authenticate_session(token=token, terminal="mini"), "mini"
        raise SessionInvalid("session is missing")

    @router.post(
        "/factory/shipments/drafts",
        response_model=ShipmentDraftResponse,
        status_code=201,
        tags=["shipment-factory"],
    )
    def create_draft(
        payload: DraftCreate,
        request: Request,
        response: Response,
        authorization: str | None = Header(default=None),
    ) -> ShipmentDraftResponse:
        del request
        actor = factory_user(authorization)
        draft, created = service.create_or_reuse_draft(
            actor_id=actor.user_id,
            factory_id=actor.factory_id or "",
            preferred_order_id=payload.preferred_order_id,
        )
        if not created:
            response.status_code = 200
        return _draft_response(draft)

    @router.get(
        "/factory/shipment-catalog",
        response_model=ShipmentCatalogResponse,
        tags=["shipment-factory"],
    )
    def shipment_catalog(
        authorization: str | None = Header(default=None),
    ) -> ShipmentCatalogResponse:
        actor = factory_user(authorization)
        items = service.list_catalog(factory_id=actor.factory_id or "")
        responses = [
            ShipmentCatalogItemResponse.model_validate(item, from_attributes=True) for item in items
        ]
        return ShipmentCatalogResponse(items=responses, total=len(responses))

    @router.get(
        "/factory/shipments/drafts/current",
        response_model=ShipmentDraftResponse,
        tags=["shipment-factory"],
    )
    def current_draft(authorization: str | None = Header(default=None)) -> ShipmentDraftResponse:
        actor = factory_user(authorization)
        return _draft_response(
            service.get_current_draft(actor_id=actor.user_id, factory_id=actor.factory_id or "")
        )

    @router.put(
        "/factory/shipments/drafts/{shipment_id}",
        response_model=ShipmentDraftResponse,
        tags=["shipment-factory"],
    )
    def save_draft(
        shipment_id: str, payload: DraftSave, authorization: str | None = Header(default=None)
    ) -> ShipmentDraftResponse:
        actor = factory_user(authorization)
        boxes = [
            DraftBoxInput(
                box_no=box.box_no,
                group_key=box.group_key,
                items=[
                    DraftItemInput(assignment_id=item.assignment_id, quantity=item.quantity)
                    for item in box.items
                ],
            )
            for box in payload.boxes
        ]
        return _draft_response(
            service.save_draft(
                actor_id=actor.user_id,
                factory_id=actor.factory_id or "",
                shipment_id=shipment_id,
                boxes=boxes,
                note=payload.note,
            )
        )

    @router.post(
        "/factory/shipments/drafts/{shipment_id}/submit",
        response_model=ShipmentDraftResponse,
        tags=["shipment-factory"],
    )
    def submit_draft(
        shipment_id: str,
        authorization: str | None = Header(default=None),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> ShipmentDraftResponse:
        actor = factory_user(authorization)
        if not idempotency_key:
            raise ShipmentValidationError("Idempotency-Key is required")
        return _draft_response(
            service.submit_draft(
                actor_id=actor.user_id,
                factory_id=actor.factory_id or "",
                shipment_id=shipment_id,
                idempotency_key=idempotency_key,
            )
        )

    @router.get(
        "/factory/shipments", response_model=ShipmentListResponse, tags=["shipment-factory"]
    )
    def factory_shipments(authorization: str | None = Header(default=None)) -> ShipmentListResponse:
        actor = factory_user(authorization)
        items = [
            _draft_response(item) for item in service.list_shipments(factory_id=actor.factory_id)
        ]
        return ShipmentListResponse(items=items, total=len(items))

    @router.get(
        "/factory/shipments/{shipment_id}",
        response_model=ShipmentDraftResponse,
        tags=["shipment-factory"],
    )
    def factory_shipment(
        shipment_id: str, authorization: str | None = Header(default=None)
    ) -> ShipmentDraftResponse:
        actor = factory_user(authorization)
        return _draft_response(
            service.get_shipment(shipment_id=shipment_id, factory_id=actor.factory_id)
        )

    @router.get("/admin/shipments", response_model=ShipmentListResponse, tags=["shipment-admin"])
    def admin_shipments(
        ot_web_session: str | None = Cookie(default=None),
        authorization: str | None = Header(default=None),
    ) -> ShipmentListResponse:
        actor, _terminal = query_user(ot_web_session, authorization)
        if actor.role != "admin":
            raise PermissionDenied("administrator role required")
        items = [_draft_response(item) for item in service.list_shipments()]
        return ShipmentListResponse(items=items, total=len(items))

    @router.get(
        "/admin/shipments/{shipment_id}",
        response_model=ShipmentDraftResponse,
        tags=["shipment-admin"],
    )
    def admin_shipment(
        shipment_id: str,
        ot_web_session: str | None = Cookie(default=None),
        authorization: str | None = Header(default=None),
    ) -> ShipmentDraftResponse:
        actor, _terminal = query_user(ot_web_session, authorization)
        if actor.role != "admin":
            raise PermissionDenied("administrator role required")
        return _draft_response(service.get_shipment(shipment_id=shipment_id))

    return router
