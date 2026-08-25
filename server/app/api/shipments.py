from datetime import date

from fastapi import APIRouter, Header, Request, Response
from pydantic import BaseModel, ConfigDict

from app.modules.identity_access import IdentityAccessService, PermissionDenied, SessionInvalid
from app.modules.identity_access.service import UserSnapshot
from app.modules.shipments import ShipmentDraftSnapshot, ShipmentService


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
    created_by: str
    preferred_order_id: str | None


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
            ShipmentCatalogItemResponse.model_validate(item, from_attributes=True)
            for item in items
        ]
        return ShipmentCatalogResponse(items=responses, total=len(responses))

    return router
