from datetime import date, datetime
from typing import Annotated
from urllib.parse import quote

from fastapi import (
    APIRouter,
    Cookie,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    Response,
    UploadFile,
)
from pydantic import BaseModel, ConfigDict, StrictInt
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.adapters.private_files import PrivateFileStore
from app.db.models import RepairPreview, StoredFile
from app.modules.identity_access import IdentityAccessService, PermissionDenied, SessionInvalid
from app.modules.identity_access.service import UserSnapshot
from app.modules.repairs.confirmation import (
    RepairConfirmationConflict,
    RepairConfirmationNotFound,
    RepairConfirmationService,
    RepairOrderView,
)
from app.modules.repairs.preview import (
    RepairPreviewExpired,
    RepairPreviewNotFound,
    RepairPreviewService,
    RepairPreviewView,
)
from app.modules.repairs.returns import (
    RepairArchiveView,
    RepairReturnConflict,
    RepairReturnLineInput,
    RepairReturnNotFound,
    RepairReturnService,
    RepairReturnValidationError,
)
from app.modules.repairs.workflow import RepairWorkflowService, RepairWorkflowValidationError


def to_camel(value: str) -> str:
    first, *rest = value.split("_")
    return first + "".join(part.capitalize() for part in rest)


class ApiModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class RepairPreviewLineResponse(ApiModel):
    line_id: int
    source_row: int
    source_order: int
    source_sku_id: str
    source_product_id: str
    product_name: str
    properties_value: str
    quantity: int
    box_number: str
    reason: str | None
    matched_product_id: str | None
    matched_variant_id: str | None


class RepairPreviewResponse(ApiModel):
    preview_id: str
    status: str
    expires_at: datetime
    original_file_id: int
    original_filename: str
    factory_id: str | None
    factory_name: str
    line_count: int
    box_count: int
    total_quantity: int
    validation_errors: list[dict[str, str | int]]
    lines: list[RepairPreviewLineResponse]


class RepairLineResponse(ApiModel):
    inspection_line_id: int
    source_row: int
    source_order: int
    box_number: str
    product_id: str
    variant_id: str
    source_sku_id: str
    source_product_id: str
    product_name: str
    properties_value: str
    warehouse_return_quantity: int
    reason: str | None


class RepairSpecResponse(ApiModel):
    variant_id: str
    source_sku_id: str
    source_product_id: str
    product_name: str
    properties_value: str
    warehouse_return_quantity: int
    repaired_quantity: int
    scrapped_quantity: int
    returned_quantity: int
    pending_quantity: int


class RepairReturnLineResponse(ApiModel):
    variant_id: str
    source_sku_id: str
    source_product_id: str
    product_name: str
    properties_value: str
    warehouse_return_quantity: int
    repaired_quantity: int
    scrapped_quantity: int
    returned_quantity: int


class RepairReturnBatchResponse(ApiModel):
    batch_id: str
    submitted_at: datetime
    return_date: date
    submitted_by: str
    lines: list[RepairReturnLineResponse]


class RepairResponse(ApiModel):
    repair_id: str
    repair_no: str
    status: str
    return_date: date
    factory_id: str
    factory_name: str
    warehouse_return_quantity: int
    repaired_quantity: int
    scrapped_quantity: int
    returned_quantity: int
    original_file_id: int
    original_filename: str
    original_size_bytes: int
    created_at: datetime
    lines: list[RepairLineResponse]
    specs: list[RepairSpecResponse]
    return_batches: list[RepairReturnBatchResponse]


class RepairListResponse(ApiModel):
    items: list[RepairResponse]
    total: int
    page: int
    page_size: int


class RepairReturnLineRequest(ApiModel):
    variant_id: str
    repaired_quantity: StrictInt
    scrapped_quantity: StrictInt


class RepairReturnRequest(ApiModel):
    lines: list[RepairReturnLineRequest]


class RepairArchiveResponse(ApiModel):
    repair_id: str
    archived_at: datetime
    archived_by: str


def _preview_response(preview: RepairPreviewView) -> RepairPreviewResponse:
    return RepairPreviewResponse.model_validate(preview, from_attributes=True)


def _repair_response(repair: RepairOrderView) -> RepairResponse:
    return RepairResponse.model_validate(repair, from_attributes=True)


def _archive_response(archive: RepairArchiveView) -> RepairArchiveResponse:
    return RepairArchiveResponse.model_validate(archive, from_attributes=True)


def _admin_can_download_repair_file(*, terminal: str, formal_repair: bool) -> bool:
    return terminal == "web" or (terminal == "mini" and formal_repair)


def create_repair_router(
    *,
    workflow: RepairWorkflowService,
    previews: RepairPreviewService,
    confirmations: RepairConfirmationService,
    returns: RepairReturnService,
    identity: IdentityAccessService,
    file_store: PrivateFileStore,
    session_factory: sessionmaker[Session],
) -> APIRouter:
    router = APIRouter(prefix="/api/v1")

    def actor(
        web_token: str | None,
        authorization: str | None,
        csrf_token: str | None = None,
        *,
        require_web: bool = False,
        require_csrf: bool = False,
    ) -> tuple[UserSnapshot, str]:
        if web_token:
            user = identity.authenticate_session(
                token=web_token,
                terminal="web",
                csrf_token=csrf_token,
                require_csrf=require_csrf,
            )
            return user, "web"
        if not require_web and authorization and authorization.startswith("Bearer "):
            token = authorization.removeprefix("Bearer ").strip()
            if token:
                return identity.authenticate_session(token=token, terminal="mini"), "mini"
        raise SessionInvalid("session is missing")

    def admin(user: UserSnapshot) -> None:
        if user.role != "admin":
            raise PermissionDenied("administrator role required")

    def translate(error: Exception) -> HTTPException:
        if isinstance(error, RepairReturnNotFound):
            return HTTPException(status_code=404, detail=str(error))
        if isinstance(error, RepairReturnConflict):
            return HTTPException(status_code=409, detail=str(error))
        if isinstance(error, RepairReturnValidationError):
            return HTTPException(status_code=422, detail=str(error))
        if isinstance(error, (RepairPreviewNotFound, RepairConfirmationNotFound)):
            return HTTPException(status_code=404, detail=str(error))
        if isinstance(error, RepairPreviewExpired):
            return HTTPException(status_code=409, detail=str(error))
        if isinstance(error, RepairConfirmationConflict):
            return HTTPException(status_code=409, detail=str(error))
        if isinstance(error, RepairWorkflowValidationError):
            return HTTPException(status_code=422, detail=str(error))
        return HTTPException(status_code=409, detail=str(error))

    @router.post(
        "/admin/repair-previews",
        response_model=RepairPreviewResponse,
        status_code=201,
        tags=["repair-admin-web"],
    )
    async def create_preview(
        file: Annotated[UploadFile, File()],
        replaces_preview_id: Annotated[str | None, Form(alias="replacesPreviewId")] = None,
        web_token: str | None = Cookie(default=None, alias="ot_web_session"),
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
    ) -> RepairPreviewResponse:
        user, _terminal = actor(
            web_token,
            None,
            csrf_token,
            require_web=True,
            require_csrf=True,
        )
        admin(user)
        content = await file.read()
        try:
            return _preview_response(
                workflow.create_preview(
                    content=content,
                    filename=file.filename or "inspection.xlsx",
                    mime_type=file.content_type or "",
                    uploaded_by=user.user_id,
                    replaces_preview_id=replaces_preview_id,
                )
            )
        except Exception as error:
            raise translate(error) from error

    @router.get(
        "/admin/repair-previews/{preview_id}",
        response_model=RepairPreviewResponse,
        tags=["repair-admin-web"],
    )
    def get_preview(
        preview_id: str,
        web_token: str | None = Cookie(default=None, alias="ot_web_session"),
    ) -> RepairPreviewResponse:
        user, _terminal = actor(web_token, None, require_web=True)
        admin(user)
        try:
            return _preview_response(previews.get(preview_id))
        except Exception as error:
            raise translate(error) from error

    @router.post(
        "/admin/repair-previews/{preview_id}/confirm",
        response_model=RepairResponse,
        tags=["repair-admin-web"],
    )
    def confirm_preview(
        preview_id: str,
        idempotency_key: str = Header(alias="Idempotency-Key"),
        web_token: str | None = Cookie(default=None, alias="ot_web_session"),
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
    ) -> RepairResponse:
        user, _terminal = actor(
            web_token,
            None,
            csrf_token,
            require_web=True,
            require_csrf=True,
        )
        admin(user)
        try:
            return _repair_response(
                confirmations.confirm(
                    preview_id=preview_id,
                    confirmed_by=user.user_id,
                    idempotency_key=idempotency_key,
                )
            )
        except Exception as error:
            raise translate(error) from error

    def filtered_repairs(
        *,
        factory_id: str | None,
        keyword: str,
        status: str,
        return_from: date | None,
        return_to: date | None,
    ) -> list[RepairOrderView]:
        values = list(returns.list_all(factory_id=factory_id))
        normalized = keyword.strip().lower()
        return [
            item
            for item in values
            if (not normalized or normalized in f"{item.repair_no} {item.factory_name}".lower())
            and (status == "all" or item.status == status)
            and (return_from is None or item.return_date >= return_from)
            and (return_to is None or item.return_date <= return_to)
        ]

    @router.get(
        "/admin/repairs",
        response_model=RepairListResponse,
        tags=["repair-admin"],
    )
    def list_admin_repairs(
        keyword: str = "",
        status: str = "all",
        return_from: Annotated[date | None, Query(alias="returnFrom")] = None,
        return_to: Annotated[date | None, Query(alias="returnTo")] = None,
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[int, Query(alias="pageSize", ge=1, le=100)] = 10,
        web_token: str | None = Cookie(default=None, alias="ot_web_session"),
        authorization: str | None = Header(default=None),
    ) -> RepairListResponse:
        user, _terminal = actor(web_token, authorization)
        admin(user)
        values = filtered_repairs(
            factory_id=None,
            keyword=keyword,
            status=status,
            return_from=return_from,
            return_to=return_to,
        )
        start = (page - 1) * page_size
        return RepairListResponse(
            items=[_repair_response(item) for item in values[start : start + page_size]],
            total=len(values),
            page=page,
            page_size=page_size,
        )

    @router.get(
        "/admin/repairs/{repair_id}",
        response_model=RepairResponse,
        tags=["repair-admin"],
    )
    def get_admin_repair(
        repair_id: str,
        web_token: str | None = Cookie(default=None, alias="ot_web_session"),
        authorization: str | None = Header(default=None),
    ) -> RepairResponse:
        user, _terminal = actor(web_token, authorization)
        admin(user)
        try:
            return _repair_response(returns.get(repair_id))
        except Exception as error:
            raise translate(error) from error

    @router.get(
        "/factory/repairs",
        response_model=RepairListResponse,
        tags=["repair-factory"],
    )
    def list_factory_repairs(
        keyword: str = "",
        status: str = "all",
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[int, Query(alias="pageSize", ge=1, le=100)] = 20,
        authorization: str | None = Header(default=None),
    ) -> RepairListResponse:
        user, terminal = actor(None, authorization)
        if terminal != "mini" or user.role != "factory" or user.factory_id is None:
            raise PermissionDenied("factory role required")
        values = filtered_repairs(
            factory_id=user.factory_id,
            keyword=keyword,
            status=status,
            return_from=None,
            return_to=None,
        )
        start = (page - 1) * page_size
        return RepairListResponse(
            items=[_repair_response(item) for item in values[start : start + page_size]],
            total=len(values),
            page=page,
            page_size=page_size,
        )

    @router.get(
        "/factory/repairs/{repair_id}",
        response_model=RepairResponse,
        tags=["repair-factory"],
    )
    def get_factory_repair(
        repair_id: str,
        authorization: str | None = Header(default=None),
    ) -> RepairResponse:
        user, terminal = actor(None, authorization)
        if terminal != "mini" or user.role != "factory" or user.factory_id is None:
            raise PermissionDenied("factory role required")
        try:
            repair = returns.get(repair_id)
        except Exception as error:
            raise translate(error) from error
        if repair.factory_id != user.factory_id:
            raise HTTPException(status_code=404, detail="返修单不存在")
        return _repair_response(repair)

    @router.post(
        "/factory/repairs/{repair_id}/return-batches",
        response_model=RepairResponse,
        status_code=201,
        tags=["repair-factory"],
    )
    def submit_factory_repair_return(
        repair_id: str,
        payload: RepairReturnRequest,
        idempotency_key: str = Header(alias="Idempotency-Key"),
        authorization: str | None = Header(default=None),
    ) -> RepairResponse:
        user, terminal = actor(None, authorization)
        if terminal != "mini" or user.role != "factory" or user.factory_id is None:
            raise PermissionDenied("factory role required")
        try:
            return _repair_response(
                returns.submit(
                    repair_id=repair_id,
                    factory_id=user.factory_id,
                    submitted_by=user.user_id,
                    idempotency_key=idempotency_key,
                    lines=tuple(
                        RepairReturnLineInput(
                            variant_id=line.variant_id,
                            repaired_quantity=line.repaired_quantity,
                            scrapped_quantity=line.scrapped_quantity,
                        )
                        for line in payload.lines
                    ),
                )
            )
        except Exception as error:
            raise translate(error) from error

    @router.post(
        "/admin/repairs/{repair_id}/archive",
        response_model=RepairArchiveResponse,
        tags=["repair-admin-web"],
    )
    def archive_admin_repair(
        repair_id: str,
        idempotency_key: str = Header(alias="Idempotency-Key"),
        web_token: str | None = Cookie(default=None, alias="ot_web_session"),
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
    ) -> RepairArchiveResponse:
        user, _terminal = actor(
            web_token,
            None,
            csrf_token,
            require_web=True,
            require_csrf=True,
        )
        admin(user)
        try:
            return _archive_response(
                returns.archive(
                    repair_id=repair_id,
                    archived_by=user.user_id,
                    idempotency_key=idempotency_key,
                )
            )
        except Exception as error:
            raise translate(error) from error

    @router.get("/files/{file_id}/download", tags=["repair-files"])
    def download_file(
        file_id: int,
        web_token: str | None = Cookie(default=None, alias="ot_web_session"),
        authorization: str | None = Header(default=None),
    ) -> Response:
        user, terminal = actor(web_token, authorization)
        orders = returns.list_all()
        matched = next(
            (order for order in orders if order.original_file_id == file_id),
            None,
        )
        preview_file = False
        if matched is None and user.role == "admin" and terminal == "web":
            with session_factory() as session:
                preview_file = bool(
                    session.scalar(
                        select(RepairPreview.preview_id)
                        .where(RepairPreview.original_file_id == file_id)
                        .limit(1)
                    )
                )
        if matched is None and not preview_file:
            raise HTTPException(status_code=404, detail="文件不存在")
        if user.role == "factory":
            if matched is None:
                raise HTTPException(status_code=404, detail="文件不存在")
            if terminal != "mini" or user.factory_id != matched.factory_id:
                raise HTTPException(status_code=404, detail="文件不存在")
            if matched.original_file_id != file_id:
                raise HTTPException(status_code=404, detail="文件不存在")
        elif user.role == "admin":
            if not _admin_can_download_repair_file(
                terminal=terminal,
                formal_repair=matched is not None,
            ):
                raise PermissionDenied("administrator terminal required")
        else:
            raise PermissionDenied("file permission denied")
        with session_factory() as session:
            stored = session.get(StoredFile, file_id)
            if stored is None:
                raise HTTPException(status_code=404, detail="文件不存在")
            content = file_store.get(object_key=stored.object_key)
            return Response(
                content=content,
                media_type=stored.mime_type,
                headers={
                    "Content-Disposition": (
                        "attachment; filename*=UTF-8''" + quote(stored.original_filename)
                    )
                },
            )

    return router
