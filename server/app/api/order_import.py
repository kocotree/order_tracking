from datetime import date, datetime
from typing import Annotated

from fastapi import APIRouter, Cookie, Header, HTTPException, Query, Request, Response
from pydantic import Field

from app.api.orders import ApiModel
from app.modules.identity_access import IdentityAccessService, PermissionDenied, SessionInvalid
from app.modules.identity_access.service import UserSnapshot
from app.modules.order_import import (
    BatchConfirmItem,
    CandidateSnapshot,
    ImportRunSnapshot,
    OrderImportService,
)


class ImportRunResponse(ApiModel):
    run_id: str
    status: str
    started_at: datetime
    finished_at: datetime | None
    pages_read: int
    records_read: int
    candidates_created: int
    candidates_updated: int
    skipped_records: int
    failed_records: int
    error_code: str | None
    request_id: str = ""


class CandidateLineResponse(ApiModel):
    candidate_line_id: int
    source_sku_id: str | None
    product_name: str | None
    properties_value: str | None
    category: str | None
    factory_name: str | None
    order_quantity: int | None
    shipped_quantity: int
    pending_quantity: int
    validation_issues: list[str]


class CandidateResponse(ApiModel):
    candidate_id: str
    order_no: str
    status: str
    validation_state: str
    validation_issues: list[str]
    order_date: date | None
    tracker: str | None
    contract_ship_date: date | None
    category: str | None
    total_quantity: int
    shipped_quantity: int
    pending_quantity: int
    imported_order_id: str | None
    lines: list[CandidateLineResponse]
    updated_at: datetime


class CandidateListResponse(ApiModel):
    items: list[CandidateResponse]
    total: int
    page: int
    page_size: int
    request_id: str


class BatchConfirmWrite(ApiModel):
    candidate_ids: list[str] = Field(min_length=1, max_length=100)


class BatchConfirmItemResponse(ApiModel):
    candidate_id: str
    succeeded: bool
    order_id: str | None
    error: str | None


class BatchConfirmResponse(ApiModel):
    items: list[BatchConfirmItemResponse]
    request_id: str


def _run_response(item: ImportRunSnapshot, request_id: str) -> ImportRunResponse:
    return ImportRunResponse.model_validate(item, from_attributes=True).model_copy(
        update={"request_id": request_id}
    )


def _candidate_response(item: CandidateSnapshot) -> CandidateResponse:
    return CandidateResponse.model_validate(item, from_attributes=True)


def _batch_item(item: BatchConfirmItem) -> BatchConfirmItemResponse:
    return BatchConfirmItemResponse.model_validate(item, from_attributes=True)


def create_order_import_router(
    service: OrderImportService, identity: IdentityAccessService
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/admin", tags=["order-import"])

    def admin(
        token: str | None,
        csrf: str | None = None,
        *,
        write: bool = False,
    ) -> UserSnapshot:
        if not token:
            raise SessionInvalid("web session is missing")
        actor = identity.authenticate_session(
            token=token,
            terminal="web",
            csrf_token=csrf,
            require_csrf=write,
        )
        if actor.role != "admin":
            raise PermissionDenied("administrator role required")
        return actor

    @router.post("/import-runs", response_model=ImportRunResponse, status_code=202)
    def create_run(
        request: Request,
        idempotency_key: str = Header(alias="Idempotency-Key"),
        ot_web_session: str | None = Cookie(default=None),
        x_csrf_token: str | None = Header(default=None),
    ) -> ImportRunResponse:
        actor = admin(ot_web_session, x_csrf_token, write=True)
        return _run_response(
            service.create_or_reuse_run(
                actor_id=actor.user_id,
                request_id=request.state.request_id,
                idempotency_key=idempotency_key,
            ),
            request.state.request_id,
        )

    @router.get("/import-runs/latest", response_model=ImportRunResponse | None)
    def latest_run(
        request: Request, ot_web_session: str | None = Cookie(default=None)
    ) -> ImportRunResponse | None:
        actor = admin(ot_web_session)
        result = service.latest_run(actor_id=actor.user_id)
        return _run_response(result, request.state.request_id) if result else None

    @router.get("/import-runs/{run_id}", response_model=ImportRunResponse)
    def get_run(
        run_id: str,
        request: Request,
        ot_web_session: str | None = Cookie(default=None),
    ) -> ImportRunResponse:
        actor = admin(ot_web_session)
        try:
            return _run_response(
                service.get_run(actor_id=actor.user_id, run_id=run_id),
                request.state.request_id,
            )
        except ValueError as error:
            raise HTTPException(status_code=404) from error

    @router.get("/import-candidates", response_model=CandidateListResponse)
    def list_candidates(
        request: Request,
        status: str = "PENDING",
        keyword: str = Query(default="", max_length=255),
        category: str | None = None,
        factory_names: Annotated[list[str] | None, Query(alias="factoryNames")] = None,
        trackers: Annotated[list[str] | None, Query()] = None,
        validation_state: Annotated[str | None, Query(alias="validationState")] = None,
        sort_by: Annotated[str, Query(alias="sortBy")] = "default",
        sort_order: Annotated[str, Query(alias="sortOrder")] = "asc",
        page: int = Query(default=1, ge=1),
        page_size: Annotated[int, Query(alias="pageSize", ge=1, le=100)] = 20,
        ot_web_session: str | None = Cookie(default=None),
    ) -> CandidateListResponse:
        actor = admin(ot_web_session)
        try:
            items, total = service.list_candidates(
                actor_id=actor.user_id,
                status=status,
                keyword=keyword,
                category=category,
                factory_names=factory_names,
                trackers=trackers,
                validation_state=validation_state,
                sort_by=sort_by,
                sort_order=sort_order,
                page=page,
                page_size=page_size,
            )
        except ValueError as error:
            raise HTTPException(status_code=400) from error
        return CandidateListResponse(
            items=[_candidate_response(item) for item in items],
            total=total,
            page=page,
            page_size=page_size,
            request_id=request.state.request_id,
        )

    @router.post("/import-candidates/confirm", response_model=BatchConfirmResponse)
    def confirm_batch(
        payload: BatchConfirmWrite,
        request: Request,
        idempotency_key: str = Header(alias="Idempotency-Key"),
        ot_web_session: str | None = Cookie(default=None),
        x_csrf_token: str | None = Header(default=None),
    ) -> BatchConfirmResponse:
        del idempotency_key
        actor = admin(ot_web_session, x_csrf_token, write=True)
        items = service.confirm_candidates(
            actor_id=actor.user_id,
            candidate_ids=payload.candidate_ids,
            request_id=request.state.request_id,
        )
        return BatchConfirmResponse(
            items=[_batch_item(item) for item in items],
            request_id=request.state.request_id,
        )

    @router.get("/import-candidates/{candidate_id}", response_model=CandidateResponse)
    def get_candidate(
        candidate_id: str,
        ot_web_session: str | None = Cookie(default=None),
    ) -> CandidateResponse:
        actor = admin(ot_web_session)
        try:
            return _candidate_response(
                service.get_candidate(actor_id=actor.user_id, candidate_id=candidate_id)
            )
        except ValueError as error:
            raise HTTPException(status_code=404) from error

    @router.delete("/import-candidates/{candidate_id}", status_code=204)
    def exclude_candidate(
        candidate_id: str,
        request: Request,
        idempotency_key: str = Header(alias="Idempotency-Key"),
        ot_web_session: str | None = Cookie(default=None),
        x_csrf_token: str | None = Header(default=None),
    ) -> Response:
        del idempotency_key
        actor = admin(ot_web_session, x_csrf_token, write=True)
        try:
            service.exclude_candidate(
                actor_id=actor.user_id,
                candidate_id=candidate_id,
                request_id=request.state.request_id,
            )
        except ValueError as error:
            raise HTTPException(status_code=409) from error
        return Response(status_code=204)

    @router.post("/import-candidates/{candidate_id}/confirm", response_model=dict[str, str])
    def confirm_candidate(
        candidate_id: str,
        request: Request,
        idempotency_key: str = Header(alias="Idempotency-Key"),
        ot_web_session: str | None = Cookie(default=None),
        x_csrf_token: str | None = Header(default=None),
    ) -> dict[str, str]:
        del idempotency_key
        actor = admin(ot_web_session, x_csrf_token, write=True)
        try:
            order_id = service.confirm_candidate(
                actor_id=actor.user_id,
                candidate_id=candidate_id,
                request_id=request.state.request_id,
            )
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return {"orderId": order_id, "requestId": request.state.request_id}

    return router
