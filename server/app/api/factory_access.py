from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Cookie, Header, Query, Request
from pydantic import BaseModel, ConfigDict

from app.modules.factory_access import (
    FactoryAccessService,
    FactoryApplicationSnapshot,
    FactorySnapshot,
)
from app.modules.identity_access import IdentityAccessService, SessionInvalid, UserSnapshot


def to_camel(value: str) -> str:
    first, *rest = value.split("_")
    return first + "".join(part.capitalize() for part in rest)


class ApiModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class ContactWrite(ApiModel):
    name: str
    phone: str


class ContactResponse(ContactWrite):
    display_order: int
    is_primary: bool


class FactoryWrite(ApiModel):
    supplier_number: str
    factory_name: str
    factory_code: str
    legal_name: str = ""
    address: str = ""
    legal_representative: str = ""
    contacts: list[ContactWrite] = []


class FactoryUpdate(ApiModel):
    version: int
    factory_name: str
    factory_code: str
    legal_name: str = ""
    address: str = ""
    legal_representative: str = ""
    contacts: list[ContactWrite] = []


class FactoryResponse(ApiModel):
    factory_id: str
    supplier_number: str
    factory_name: str
    factory_code: str
    legal_name: str | None
    address: str | None
    legal_representative: str | None
    is_enabled: bool
    version: int
    contract_complete: bool
    missing_contract_fields: list[str]
    contacts: list[ContactResponse]
    connected_users: int


class FactoryListResponse(ApiModel):
    items: list[FactoryResponse]
    total: int


class FactoryOptionResponse(ApiModel):
    factory_id: str
    supplier_number: str
    factory_name: str


class FactoryOptionListResponse(ApiModel):
    items: list[FactoryOptionResponse]
    total: int


class FactoryApplicationCreate(ApiModel):
    real_name: str
    position: str
    factory_id: str


class FactoryApplicationResponse(ApiModel):
    application_id: str
    user_id: str
    real_name: str
    phone_masked: str
    position: str
    requested_factory_id: str
    requested_factory_name: str
    bound_factory_id: str | None
    bound_factory_name: str | None
    status: str
    submitted_at: datetime
    reviewed_by: str | None
    reviewed_at: datetime | None
    rejection_reason: str | None
    version: int
    factory_contacts: list[ContactResponse]


class FactoryApplicationListResponse(ApiModel):
    items: list[FactoryApplicationResponse]
    total: int


class ApproveFactoryApplication(ApiModel):
    version: int
    factory_id: str


class RejectFactoryApplication(ApiModel):
    version: int
    reason: str


def _factory_response(factory: FactorySnapshot) -> FactoryResponse:
    return FactoryResponse.model_validate(factory, from_attributes=True)


def _application_response(
    application: FactoryApplicationSnapshot,
) -> FactoryApplicationResponse:
    return FactoryApplicationResponse.model_validate(application, from_attributes=True)


def create_factory_router(
    service: FactoryAccessService,
    identity: IdentityAccessService,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1")

    def web_user(
        web_session: str | None,
        csrf_token: str | None = None,
        *,
        require_csrf: bool = False,
    ) -> UserSnapshot:
        if not web_session:
            raise SessionInvalid("web session is missing")
        return identity.authenticate_session(
            token=web_session,
            terminal="web",
            csrf_token=csrf_token,
            require_csrf=require_csrf,
        )

    def mini_user(authorization: str | None) -> UserSnapshot:
        if not authorization or not authorization.startswith("Bearer "):
            raise SessionInvalid("mini-program session is missing")
        token = authorization.removeprefix("Bearer ").strip()
        if not token:
            raise SessionInvalid("mini-program session is missing")
        return identity.authenticate_session(token=token, terminal="mini")

    @router.get("/factories", response_model=FactoryOptionListResponse, tags=["factory-mini"])
    def list_factory_options(
        keyword: str = Query(default=""),
        authorization: str | None = Header(default=None),
    ) -> FactoryOptionListResponse:
        mini_user(authorization)
        factories = service.list_factory_options(keyword=keyword)
        items = [
            FactoryOptionResponse(
                factory_id=factory.factory_id,
                supplier_number=factory.supplier_number,
                factory_name=factory.factory_name,
            )
            for factory in factories
        ]
        return FactoryOptionListResponse(items=items, total=len(items))

    @router.post(
        "/factory-applications",
        response_model=FactoryApplicationResponse,
        status_code=201,
        tags=["factory-mini"],
    )
    def submit_factory_application(
        payload: FactoryApplicationCreate,
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> FactoryApplicationResponse:
        user = mini_user(authorization)
        return _application_response(
            service.submit_factory_application(
                user_id=user.user_id,
                real_name=payload.real_name,
                position=payload.position,
                factory_id=payload.factory_id,
                request_id=request.state.request_id,
            )
        )

    @router.get(
        "/factory-applications/me",
        response_model=FactoryApplicationResponse | None,
        tags=["factory-mini"],
    )
    def my_factory_application(
        authorization: str | None = Header(default=None),
    ) -> FactoryApplicationResponse | None:
        user = mini_user(authorization)
        application = service.get_my_factory_application(user_id=user.user_id)
        return _application_response(application) if application is not None else None

    @router.get(
        "/admin/factories", response_model=FactoryListResponse, tags=["factory-admin"]
    )
    def list_factories(
        keyword: str = Query(default=""),
        contract_status: Annotated[
            str, Query(alias="contractStatus")
        ] = "all",
        access_status: Annotated[str, Query(alias="accessStatus")] = "all",
        ot_web_session: str | None = Cookie(default=None),
    ) -> FactoryListResponse:
        actor = web_user(ot_web_session)
        factories = service.list_factories(
            actor_id=actor.user_id,
            keyword=keyword,
            contract_status=contract_status,
            access_status=access_status,
        )
        items = [_factory_response(factory) for factory in factories]
        return FactoryListResponse(items=items, total=len(items))

    @router.post(
        "/admin/factories",
        response_model=FactoryResponse,
        status_code=201,
        tags=["factory-admin"],
    )
    def create_factory(
        payload: FactoryWrite,
        request: Request,
        ot_web_session: str | None = Cookie(default=None),
        x_csrf_token: str | None = Header(default=None),
    ) -> FactoryResponse:
        actor = web_user(ot_web_session, x_csrf_token, require_csrf=True)
        return _factory_response(
            service.create_factory(
                actor_id=actor.user_id,
                supplier_number=payload.supplier_number,
                factory_name=payload.factory_name,
                factory_code=payload.factory_code,
                legal_name=payload.legal_name,
                address=payload.address,
                legal_representative=payload.legal_representative,
                contacts=[(item.name, item.phone) for item in payload.contacts],
                request_id=request.state.request_id,
            )
        )

    @router.get(
        "/admin/factories/{factory_id}",
        response_model=FactoryResponse,
        tags=["factory-admin"],
    )
    def get_factory(
        factory_id: str,
        ot_web_session: str | None = Cookie(default=None),
    ) -> FactoryResponse:
        actor = web_user(ot_web_session)
        return _factory_response(
            service.get_factory(actor_id=actor.user_id, factory_id=factory_id)
        )

    @router.patch(
        "/admin/factories/{factory_id}",
        response_model=FactoryResponse,
        tags=["factory-admin"],
    )
    def update_factory(
        factory_id: str,
        payload: FactoryUpdate,
        request: Request,
        ot_web_session: str | None = Cookie(default=None),
        x_csrf_token: str | None = Header(default=None),
    ) -> FactoryResponse:
        actor = web_user(ot_web_session, x_csrf_token, require_csrf=True)
        return _factory_response(
            service.update_factory(
                actor_id=actor.user_id,
                factory_id=factory_id,
                expected_version=payload.version,
                factory_name=payload.factory_name,
                factory_code=payload.factory_code,
                legal_name=payload.legal_name,
                address=payload.address,
                legal_representative=payload.legal_representative,
                contacts=[(item.name, item.phone) for item in payload.contacts],
                request_id=request.state.request_id,
            )
        )

    @router.get(
        "/admin/factory-applications",
        response_model=FactoryApplicationListResponse,
        tags=["factory-admin"],
    )
    def list_factory_applications(
        status: str | None = Query(default=None),
        ot_web_session: str | None = Cookie(default=None),
    ) -> FactoryApplicationListResponse:
        actor = web_user(ot_web_session)
        applications = service.list_factory_applications(
            actor_id=actor.user_id, status=status
        )
        items = [_application_response(item) for item in applications]
        return FactoryApplicationListResponse(items=items, total=len(items))

    @router.get(
        "/admin/factory-applications/{application_id}",
        response_model=FactoryApplicationResponse,
        tags=["factory-admin"],
    )
    def get_factory_application(
        application_id: str,
        ot_web_session: str | None = Cookie(default=None),
    ) -> FactoryApplicationResponse:
        actor = web_user(ot_web_session)
        return _application_response(
            service.get_factory_application(
                actor_id=actor.user_id, application_id=application_id
            )
        )

    @router.post(
        "/admin/factory-applications/{application_id}/approve",
        response_model=FactoryApplicationResponse,
        tags=["factory-admin"],
    )
    def approve_factory_application(
        application_id: str,
        payload: ApproveFactoryApplication,
        request: Request,
        ot_web_session: str | None = Cookie(default=None),
        x_csrf_token: str | None = Header(default=None),
    ) -> FactoryApplicationResponse:
        actor = web_user(ot_web_session, x_csrf_token, require_csrf=True)
        return _application_response(
            service.approve_factory_application(
                actor_id=actor.user_id,
                application_id=application_id,
                expected_version=payload.version,
                factory_id=payload.factory_id,
                request_id=request.state.request_id,
            )
        )

    @router.post(
        "/admin/factory-applications/{application_id}/reject",
        response_model=FactoryApplicationResponse,
        tags=["factory-admin"],
    )
    def reject_factory_application(
        application_id: str,
        payload: RejectFactoryApplication,
        request: Request,
        ot_web_session: str | None = Cookie(default=None),
        x_csrf_token: str | None = Header(default=None),
    ) -> FactoryApplicationResponse:
        actor = web_user(ot_web_session, x_csrf_token, require_csrf=True)
        return _application_response(
            service.reject_factory_application(
                actor_id=actor.user_id,
                application_id=application_id,
                expected_version=payload.version,
                reason=payload.reason,
                request_id=request.state.request_id,
            )
        )

    return router
