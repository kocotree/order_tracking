from datetime import date
from urllib.parse import quote

from fastapi import APIRouter, Cookie, Header, Request, Response
from pydantic import BaseModel, ConfigDict

from app.modules.contracts import ContractService
from app.modules.identity_access import IdentityAccessService, PermissionDenied, SessionInvalid
from app.modules.identity_access.service import UserSnapshot


def to_camel(value: str) -> str:
    first, *rest = value.split("_")
    return first + "".join(part.capitalize() for part in rest)


class ApiModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class ContractFactoryStatusResponse(ApiModel):
    factory_id: str
    factory_name: str
    contract_ready: bool
    missing_contract_fields: list[str]
    eligible: bool
    ineligible_reason: str | None
    contract_no: str | None
    signing_date: date | None


class ContractFactoryStatusListResponse(ApiModel):
    items: list[ContractFactoryStatusResponse]
    request_id: str


class ContractExportWrite(ApiModel):
    signing_date: date | None = None


class ContractExportResponse(ApiModel):
    export_id: str
    contract_id: str
    contract_no: str
    signing_date: date
    filename: str
    status: str
    download_url: str
    request_id: str


def create_contract_router(
    service: ContractService,
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

    @router.get(
        "/admin/orders/{order_id}/contracts",
        response_model=ContractFactoryStatusListResponse,
        tags=["contract-admin"],
    )
    def list_contracts(
        order_id: str,
        request: Request,
        ot_web_session: str | None = Cookie(default=None),
    ) -> ContractFactoryStatusListResponse:
        actor = web_admin(ot_web_session)
        items = service.list_for_order(actor_id=actor.user_id, order_id=order_id)
        return ContractFactoryStatusListResponse(
            items=[
                ContractFactoryStatusResponse.model_validate(item, from_attributes=True)
                for item in items
            ],
            request_id=request.state.request_id,
        )

    @router.post(
        "/admin/orders/{order_id}/contracts/{factory_id}/exports",
        response_model=ContractExportResponse,
        status_code=201,
        tags=["contract-admin"],
    )
    def create_export(
        order_id: str,
        factory_id: str,
        payload: ContractExportWrite,
        request: Request,
        idempotency_key: str = Header(alias="Idempotency-Key"),
        ot_web_session: str | None = Cookie(default=None),
        x_csrf_token: str | None = Header(default=None),
    ) -> ContractExportResponse:
        actor = web_admin(ot_web_session, x_csrf_token, require_csrf=True)
        result = service.create_export(
            actor_id=actor.user_id,
            order_id=order_id,
            factory_id=factory_id,
            signing_date=payload.signing_date,
            idempotency_key=idempotency_key,
            request_id=request.state.request_id,
        )
        return ContractExportResponse(
            export_id=result.export_id,
            contract_id=result.contract_id,
            contract_no=result.contract_no,
            signing_date=result.signing_date,
            filename=result.filename,
            status=result.status,
            download_url=f"/api/v1/admin/contract-exports/{result.export_id}/download",
            request_id=request.state.request_id,
        )

    @router.get(
        "/admin/contract-exports/{export_id}/download",
        tags=["contract-admin"],
    )
    def download_export(
        export_id: str,
        ot_web_session: str | None = Cookie(default=None),
    ) -> Response:
        actor = web_admin(ot_web_session)
        filename, content, content_type = service.download(
            actor_id=actor.user_id, export_id=export_id
        )
        encoded_filename = quote(filename)
        return Response(
            content=content,
            media_type=content_type,
            headers={
                "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}",
                "X-Content-Type-Options": "nosniff",
            },
        )

    return router
