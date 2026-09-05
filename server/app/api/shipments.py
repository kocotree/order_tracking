from datetime import date, datetime
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Cookie, File, Header, Query, Request, Response, UploadFile
from pydantic import BaseModel, ConfigDict, Field, StrictInt

from app.modules.identity_access import IdentityAccessService, PermissionDenied, SessionInvalid
from app.modules.identity_access.service import UserSnapshot
from app.modules.shipments import (
    DraftBoxInput,
    DraftItemInput,
    ShipmentDraftSnapshot,
    ShipmentReturnEventSnapshot,
    ShipmentReturnInput,
    ShipmentService,
    ShipmentValidationError,
    ShipmentVoidRequestSnapshot,
)
from app.modules.shipments.service import SHIPMENT_FILE_MAX_BYTES


def to_camel(value: str) -> str:
    first, *rest = value.split("_")
    return first + "".join(part.capitalize() for part in rest)


class ApiModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class DraftCreate(ApiModel):
    preferred_order_id: str | None = None


class ShipmentVoidRequestResponse(ApiModel):
    request_id: str
    shipment_id: str
    status: str
    reason: str
    requested_by: str
    requested_by_name: str
    requested_at: datetime
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    review_comment: str | None = None


class ShipmentDraftResponse(ApiModel):
    version: int = 1
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
    files: list["ShipmentFileResponse"] = []
    void_request: ShipmentVoidRequestResponse | None = None
    return_events: list["ShipmentReturnEventResponse"] = []


class DraftItemWrite(ApiModel):
    assignment_id: StrictInt = Field(gt=0)
    quantity: StrictInt = Field(gt=0)


class DraftBoxWrite(ApiModel):
    box_no: StrictInt = Field(gt=0)
    group_key: str | None = None
    items: list[DraftItemWrite] = []


class DraftSave(ApiModel):
    version: StrictInt = Field(default=1, ge=1)
    boxes: list[DraftBoxWrite] = Field(min_length=1)
    note: str = Field(default="", max_length=500)


class VoidRequestCreate(ApiModel):
    reason: str = Field(min_length=1, max_length=500)


class VoidReviewWrite(ApiModel):
    comment: str = Field(default="", max_length=500)


class ShipmentReturnLineWrite(ApiModel):
    shipment_line_id: StrictInt = Field(gt=0)
    quantity: StrictInt = Field(gt=0)


class ShipmentReturnWrite(ApiModel):
    reason: str = Field(min_length=1, max_length=500)
    lines: list[ShipmentReturnLineWrite] = Field(min_length=1)


class ShipmentLineResponse(ApiModel):
    assignment_id: int
    order_id: str
    order_no: str
    sku_id: str
    product_name: str
    properties_value: str
    quantity: int
    line_id: int | None = None
    returned_quantity: int = 0
    returnable_quantity: int = 0


class ShipmentReturnLineResponse(ApiModel):
    shipment_line_id: int
    order_no: str
    sku_id: str
    product_name: str
    properties_value: str
    quantity: int
    before_shipped_quantity: int
    after_shipped_quantity: int


class ShipmentReturnEventResponse(ApiModel):
    event_id: str
    shipment_id: str
    return_date: date
    reason: str
    returned_by: str
    returned_at: datetime
    lines: list[ShipmentReturnLineResponse]


class ShipmentBoxResponse(ApiModel):
    box_no: int
    group_key: str | None
    items: list[ShipmentLineResponse]


class ShipmentFileResponse(ApiModel):
    file_id: int
    filename: str
    mime_type: str
    size_bytes: int
    content_sha256: str
    display_order: int
    content_url: str


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


def _void_request_response(
    request: ShipmentVoidRequestSnapshot,
) -> ShipmentVoidRequestResponse:
    return ShipmentVoidRequestResponse.model_validate(request, from_attributes=True)


def _return_event_response(
    event: ShipmentReturnEventSnapshot,
) -> ShipmentReturnEventResponse:
    return ShipmentReturnEventResponse.model_validate(event, from_attributes=True)


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

    def web_admin(
        token: str | None,
        csrf_token: str | None,
        *,
        require_csrf: bool,
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

    @router.post(
        "/factory/shipments/drafts/{shipment_id}/files",
        response_model=ShipmentFileResponse,
        status_code=201,
        tags=["shipment-factory"],
    )
    async def upload_draft_file(
        shipment_id: str,
        file: Annotated[UploadFile, File()],
        response: Response,
        authorization: str | None = Header(default=None),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> ShipmentFileResponse:
        actor = factory_user(authorization)
        if not idempotency_key:
            raise ShipmentValidationError("Idempotency-Key is required")
        result, created = service.upload_file(
            actor_id=actor.user_id,
            factory_id=actor.factory_id or "",
            shipment_id=shipment_id,
            filename=file.filename or "shipment-evidence",
            declared_mime_type=file.content_type or "application/octet-stream",
            content=await file.read(SHIPMENT_FILE_MAX_BYTES + 1),
            idempotency_key=idempotency_key,
        )
        if not created:
            response.status_code = 200
        return ShipmentFileResponse.model_validate(result, from_attributes=True)

    @router.delete(
        "/factory/shipments/drafts/{shipment_id}/files/{file_id}",
        status_code=204,
        tags=["shipment-factory"],
    )
    def remove_draft_file(
        shipment_id: str,
        file_id: int,
        authorization: str | None = Header(default=None),
    ) -> Response:
        actor = factory_user(authorization)
        service.remove_file(
            actor_id=actor.user_id,
            factory_id=actor.factory_id or "",
            shipment_id=shipment_id,
            file_id=file_id,
        )
        return Response(status_code=204)

    @router.delete(
        "/factory/shipments/drafts/{shipment_id}",
        status_code=204,
        tags=["shipment-factory"],
    )
    def abandon_draft(
        shipment_id: str,
        version: Annotated[int, Query(ge=1)],
        authorization: str | None = Header(default=None),
    ) -> Response:
        actor = factory_user(authorization)
        service.abandon_draft(
            actor_id=actor.user_id, factory_id=actor.factory_id or "",
            shipment_id=shipment_id, expected_version=version,
        )
        return Response(status_code=204)

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
                expected_version=payload.version,
            )
        )

    @router.post(
        "/factory/shipments/drafts/{shipment_id}/submit",
        response_model=ShipmentDraftResponse,
        tags=["shipment-factory"],
    )
    def submit_draft(
        shipment_id: str,
        version: Annotated[int | None, Query(ge=1)] = None,
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
                expected_version=version,
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

    @router.post(
        "/factory/shipments/{shipment_id}/void-requests",
        response_model=ShipmentVoidRequestResponse,
        status_code=201,
        tags=["shipment-factory"],
    )
    def request_void(
        shipment_id: str,
        payload: VoidRequestCreate,
        authorization: str | None = Header(default=None),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> ShipmentVoidRequestResponse:
        actor = factory_user(authorization)
        if not idempotency_key:
            raise ShipmentValidationError("Idempotency-Key is required")
        return _void_request_response(
            service.request_void(
                actor_id=actor.user_id,
                factory_id=actor.factory_id or "",
                shipment_id=shipment_id,
                reason=payload.reason,
                idempotency_key=idempotency_key,
            )
        )

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

    @router.get(
        "/shipment-files/{file_id}/content",
        tags=["shipment-files"],
        response_class=Response,
        responses={
            200: {
                "content": {
                    "image/*": {"schema": {"type": "string", "format": "binary"}}
                }
            }
        },
    )
    def shipment_file_content(
        file_id: int,
        ot_web_session: str | None = Cookie(default=None),
        authorization: str | None = Header(default=None),
    ) -> Response:
        actor, _terminal = query_user(ot_web_session, authorization)
        result = service.get_file_content(
            file_id=file_id,
            actor_role=actor.role,
            actor_factory_id=actor.factory_id,
        )
        return Response(
            content=result.content,
            media_type=result.mime_type,
            headers={
                "Cache-Control": "private, no-store",
                "X-Content-Type-Options": "nosniff",
            },
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

    @router.get(
        "/admin/shipments/{shipment_id}/export",
        tags=["shipment-admin"],
    )
    def export_shipment(
        shipment_id: str,
        ot_web_session: str | None = Cookie(default=None),
    ) -> Response:
        web_admin(ot_web_session, None, require_csrf=False)
        result = service.export_shipment(shipment_id=shipment_id)
        encoded_filename = quote(result.filename)
        return Response(
            content=result.content,
            media_type=(
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            ),
            headers={
                "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}"
            },
        )

    @router.post(
        "/admin/shipments/{shipment_id}/returns",
        response_model=ShipmentReturnEventResponse,
        status_code=201,
        tags=["shipment-admin"],
    )
    def return_shipment(
        shipment_id: str,
        payload: ShipmentReturnWrite,
        response: Response,
        ot_web_session: str | None = Cookie(default=None),
        x_csrf_token: str | None = Header(default=None),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> ShipmentReturnEventResponse:
        actor = web_admin(ot_web_session, x_csrf_token, require_csrf=True)
        if not idempotency_key:
            raise ShipmentValidationError("Idempotency-Key is required")
        event, created = service.return_shipment(
            actor_id=actor.user_id,
            shipment_id=shipment_id,
            reason=payload.reason,
            lines=[
                ShipmentReturnInput(
                    shipment_line_id=line.shipment_line_id,
                    quantity=line.quantity,
                )
                for line in payload.lines
            ],
            idempotency_key=idempotency_key,
        )
        if not created:
            response.status_code = 200
        return _return_event_response(event)

    @router.post(
        "/admin/shipment-void-requests/{request_id}/approve",
        response_model=ShipmentVoidRequestResponse,
        tags=["shipment-admin"],
    )
    def approve_void_request(
        request_id: str,
        payload: VoidReviewWrite,
        ot_web_session: str | None = Cookie(default=None),
        x_csrf_token: str | None = Header(default=None),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> ShipmentVoidRequestResponse:
        actor = web_admin(ot_web_session, x_csrf_token, require_csrf=True)
        if not idempotency_key:
            raise ShipmentValidationError("Idempotency-Key is required")
        return _void_request_response(
            service.review_void(
                actor_id=actor.user_id,
                request_id=request_id,
                approve=True,
                comment=payload.comment,
                idempotency_key=idempotency_key,
            )
        )

    @router.post(
        "/admin/shipment-void-requests/{request_id}/reject",
        response_model=ShipmentVoidRequestResponse,
        tags=["shipment-admin"],
    )
    def reject_void_request(
        request_id: str,
        payload: VoidReviewWrite,
        ot_web_session: str | None = Cookie(default=None),
        x_csrf_token: str | None = Header(default=None),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> ShipmentVoidRequestResponse:
        actor = web_admin(ot_web_session, x_csrf_token, require_csrf=True)
        if not idempotency_key:
            raise ShipmentValidationError("Idempotency-Key is required")
        return _void_request_response(
            service.review_void(
                actor_id=actor.user_id,
                request_id=request_id,
                approve=False,
                comment=payload.comment,
                idempotency_key=idempotency_key,
            )
        )

    return router
