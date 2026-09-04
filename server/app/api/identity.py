from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Cookie, File, Header, Query, Request, UploadFile
from fastapi.responses import RedirectResponse, Response
from pydantic import BaseModel, ConfigDict

from app.modules.factory_access import FactoryAccessService, FactoryUserSnapshot
from app.modules.identity_access import (
    IdentityAccessService,
    MiniLoginResult,
    SessionInvalid,
    SessionTokens,
    UserSnapshot,
)


def to_camel(value: str) -> str:
    first, *rest = value.split("_")
    return first + "".join(part.capitalize() for part in rest)


class ApiModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class UserResponse(ApiModel):
    user_id: str
    role: str | None
    is_super_admin: bool
    is_enabled: bool
    display_name: str
    feishu_avatar_url: str | None
    mini_avatar_external_url: str | None
    mini_avatar_file_id: int | None
    phone_masked: str | None
    factory_id: str | None
    factory_position: str | None
    factory_name: str | None
    version: int
    capabilities: list[str]


class AdminUserListResponse(ApiModel):
    items: list[UserResponse]
    total: int


class UserVersionRequest(ApiModel):
    version: int


class WechatLoginRequest(ApiModel):
    code: str


class WechatPhoneRequest(ApiModel):
    binding_token: str
    phone_code: str


class MiniRefreshRequest(ApiModel):
    refresh_token: str


class SessionResponse(ApiModel):
    access_token: str
    refresh_token: str | None
    expires_at: datetime


class MiniLoginResponse(ApiModel):
    status: str
    binding_token: str | None
    user: UserResponse | None
    session: SessionResponse | None
    rejection_reason: str | None


class AvatarResponse(ApiModel):
    file_id: int
    mime_type: str
    size_bytes: int


def _capabilities(user: UserSnapshot) -> list[str]:
    if not user.is_enabled:
        return []
    if user.role is None:
        return [
            "factory_application.submit",
            "factory_application.read_own",
        ]
    if user.role == "factory":
        return ["factory_identity.read", "mini.use"]
    capabilities = ["business.read", "factory.manage", "factory_application.review", "mini.use"]
    if user.is_super_admin:
        capabilities.append("admin_user.manage")
    return capabilities


def _user_response(user: UserSnapshot) -> UserResponse:
    return UserResponse(
        user_id=user.user_id,
        role=user.role,
        is_super_admin=user.is_super_admin,
        is_enabled=user.is_enabled,
        display_name=user.display_name,
        feishu_avatar_url=user.feishu_avatar_url,
        mini_avatar_external_url=user.mini_avatar_external_url,
        mini_avatar_file_id=user.mini_avatar_file_id,
        phone_masked=user.phone_masked,
        factory_id=user.factory_id,
        factory_position=user.factory_position,
        factory_name=None,
        version=user.version,
        capabilities=_capabilities(user),
    )


def _session_response(session: SessionTokens) -> SessionResponse:
    return SessionResponse.model_validate(session, from_attributes=True)


def _factory_user_response(user: FactoryUserSnapshot) -> UserResponse:
    return UserResponse(
        user_id=user.user_id,
        role="factory",
        is_super_admin=False,
        is_enabled=user.is_enabled,
        display_name=user.real_name,
        feishu_avatar_url=None,
        mini_avatar_external_url=None,
        mini_avatar_file_id=None,
        phone_masked=user.phone_masked,
        factory_id=user.factory_id,
        factory_position=user.position,
        factory_name=user.factory_name,
        version=user.version,
        capabilities=["factory_identity.read", "mini.use"] if user.is_enabled else [],
    )


def _mini_login_response(result: MiniLoginResult) -> MiniLoginResponse:
    user = result.user
    session = result.session
    return MiniLoginResponse(
        status=result.status,
        binding_token=result.binding_token,
        user=_user_response(user) if user is not None else None,
        session=_session_response(session) if session is not None else None,
        rejection_reason=result.rejection_reason,
    )


def create_identity_router(
    service: IdentityAccessService,
    *,
    factory_service: FactoryAccessService | None = None,
    secure_web_cookies: bool = True,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1")

    def set_web_session_cookies(
        response: Response,
        *,
        access_token: str,
        refresh_token: str,
        csrf_token: str,
    ) -> None:
        response.set_cookie(
            "ot_web_session",
            access_token,
            max_age=12 * 60 * 60,
            secure=secure_web_cookies,
            httponly=True,
            samesite="lax",
            path="/",
        )
        response.set_cookie(
            "ot_web_refresh",
            refresh_token,
            max_age=30 * 24 * 60 * 60,
            secure=secure_web_cookies,
            httponly=True,
            samesite="lax",
            path="/",
        )
        response.set_cookie(
            "ot_csrf",
            csrf_token,
            max_age=12 * 60 * 60,
            secure=secure_web_cookies,
            httponly=False,
            samesite="lax",
            path="/",
        )

    def web_user(
        *,
        web_session: str | None,
        csrf_token: str | None = None,
        require_csrf: bool = False,
    ) -> UserSnapshot:
        if not web_session:
            raise SessionInvalid("web session is missing")
        return service.authenticate_session(
            token=web_session,
            terminal="web",
            csrf_token=csrf_token,
            require_csrf=require_csrf,
        )

    def bearer_token(authorization: str | None) -> str:
        if not authorization or not authorization.startswith("Bearer "):
            raise SessionInvalid("mini-program session is missing")
        token = authorization.removeprefix("Bearer ").strip()
        if not token:
            raise SessionInvalid("mini-program session is missing")
        return token

    def mini_user(authorization: str | None) -> UserSnapshot:
        return service.authenticate_session(
            token=bearer_token(authorization),
            terminal="mini",
        )

    @router.get("/auth/feishu/start", tags=["identity"])
    def start_feishu_login(
        request: Request,
        return_to: str = Query(default="/", alias="returnTo"),
    ) -> RedirectResponse:
        started = service.start_feishu_login(
            return_to=return_to,
            request_id=request.state.request_id,
        )
        return RedirectResponse(started.authorization_url, status_code=307)

    @router.get("/auth/feishu/callback", tags=["identity"])
    def complete_feishu_login(
        request: Request,
        state: str,
        code: str,
    ) -> RedirectResponse:
        result = service.complete_feishu_login(
            state=state,
            code=code,
            request_id=request.state.request_id,
        )
        response = RedirectResponse(result.redirect_to, status_code=303)
        set_web_session_cookies(
            response,
            access_token=result.web_session_token,
            refresh_token=result.refresh_token,
            csrf_token=result.csrf_token,
        )
        return response

    @router.post("/auth/refresh", status_code=204, tags=["identity"])
    def refresh_web_session(
        ot_web_refresh: str | None = Cookie(default=None),
    ) -> Response:
        if not ot_web_refresh:
            raise SessionInvalid("web refresh token is missing")
        tokens = service.refresh_web_session(refresh_token=ot_web_refresh)
        if tokens.refresh_token is None or tokens.csrf_token is None:
            raise RuntimeError("web refresh did not return complete session tokens")
        response = Response(status_code=204)
        set_web_session_cookies(
            response,
            access_token=tokens.access_token,
            refresh_token=tokens.refresh_token,
            csrf_token=tokens.csrf_token,
        )
        return response

    @router.get("/me", response_model=UserResponse, tags=["identity"])
    def current_user(
        ot_web_session: str | None = Cookie(default=None),
        authorization: str | None = Header(default=None),
    ) -> UserResponse:
        user = (
            web_user(web_session=ot_web_session)
            if ot_web_session is not None
            else mini_user(authorization)
        )
        response = _user_response(user)
        if user.role == "factory" and user.factory_id is not None and factory_service:
            factory = factory_service.get_own_factory(
                user_id=user.user_id,
                factory_id=user.factory_id,
            )
            return response.model_copy(update={"factory_name": factory.factory_name})
        return response

    @router.post("/auth/logout", status_code=204, tags=["identity"])
    def web_logout(
        request: Request,
        ot_web_session: str | None = Cookie(default=None),
        x_csrf_token: str | None = Header(default=None),
    ) -> Response:
        web_user(
            web_session=ot_web_session,
            csrf_token=x_csrf_token,
            require_csrf=True,
        )
        service.logout_session(
            token=ot_web_session or "",
            terminal="web",
            request_id=request.state.request_id,
        )
        response = Response(status_code=204)
        response.delete_cookie(
            "ot_web_session",
            path="/",
            secure=secure_web_cookies,
            httponly=True,
        )
        response.delete_cookie(
            "ot_web_refresh",
            path="/",
            secure=secure_web_cookies,
            httponly=True,
        )
        response.delete_cookie("ot_csrf", path="/", secure=secure_web_cookies)
        return response

    @router.get(
        "/admin/users",
        response_model=AdminUserListResponse,
        tags=["identity-admin"],
    )
    def list_admin_users(
        role: str = Query(default="admin"),
        ot_web_session: str | None = Cookie(default=None),
    ) -> AdminUserListResponse:
        actor = web_user(web_session=ot_web_session)
        if role == "factory":
            if factory_service is None:
                return AdminUserListResponse(items=[], total=0)
            factory_users = factory_service.list_factory_users(actor_id=actor.user_id)
            factory_items = [_factory_user_response(user) for user in factory_users]
            return AdminUserListResponse(items=factory_items, total=len(factory_items))
        if role != "admin":
            return AdminUserListResponse(items=[], total=0)
        admin_users = service.list_admin_users(actor_id=actor.user_id)
        admin_items = [_user_response(user) for user in admin_users]
        return AdminUserListResponse(items=admin_items, total=len(admin_items))

    def set_user_enabled(
        *,
        target_user_id: str,
        payload: UserVersionRequest,
        request: Request,
        web_session: str | None,
        csrf_token: str | None,
        enabled: bool,
    ) -> UserResponse:
        actor = web_user(
            web_session=web_session,
            csrf_token=csrf_token,
            require_csrf=True,
        )
        target = service.get_user(user_id=target_user_id)
        if target.role == "factory" and factory_service is not None:
            return _factory_user_response(
                factory_service.set_factory_user_enabled(
                    actor_id=actor.user_id,
                    target_user_id=target_user_id,
                    enabled=enabled,
                    expected_version=payload.version,
                    request_id=request.state.request_id,
                )
            )
        return _user_response(
            service.set_admin_enabled(
                actor_id=actor.user_id,
                target_user_id=target_user_id,
                enabled=enabled,
                expected_version=payload.version,
                request_id=request.state.request_id,
            )
        )

    @router.post(
        "/admin/users/{target_user_id}/enable",
        response_model=UserResponse,
        tags=["identity-admin"],
    )
    def enable_admin_user(
        target_user_id: str,
        payload: UserVersionRequest,
        request: Request,
        ot_web_session: str | None = Cookie(default=None),
        x_csrf_token: str | None = Header(default=None),
    ) -> UserResponse:
        return set_user_enabled(
            target_user_id=target_user_id,
            payload=payload,
            request=request,
            web_session=ot_web_session,
            csrf_token=x_csrf_token,
            enabled=True,
        )

    @router.post(
        "/admin/users/{target_user_id}/disable",
        response_model=UserResponse,
        tags=["identity-admin"],
    )
    def disable_admin_user(
        target_user_id: str,
        payload: UserVersionRequest,
        request: Request,
        ot_web_session: str | None = Cookie(default=None),
        x_csrf_token: str | None = Header(default=None),
    ) -> UserResponse:
        return set_user_enabled(
            target_user_id=target_user_id,
            payload=payload,
            request=request,
            web_session=ot_web_session,
            csrf_token=x_csrf_token,
            enabled=False,
        )

    @router.post(
        "/mini/auth/wechat",
        response_model=MiniLoginResponse,
        tags=["identity-mini"],
    )
    def mini_wechat_login(
        payload: WechatLoginRequest,
        request: Request,
    ) -> MiniLoginResponse:
        return _mini_login_response(
            service.begin_wechat_login(
                login_code=payload.code,
                request_id=request.state.request_id,
            )
        )

    @router.post(
        "/mini/auth/phone",
        response_model=MiniLoginResponse,
        tags=["identity-mini"],
    )
    def mini_phone_binding(
        payload: WechatPhoneRequest,
        request: Request,
    ) -> MiniLoginResponse:
        return _mini_login_response(
            service.bind_wechat_phone(
                binding_token=payload.binding_token,
                phone_code=payload.phone_code,
                request_id=request.state.request_id,
            )
        )

    @router.post(
        "/mini/auth/refresh",
        response_model=SessionResponse,
        tags=["identity-mini"],
    )
    def mini_refresh(payload: MiniRefreshRequest) -> SessionResponse:
        return _session_response(
            service.refresh_mini_session(refresh_token=payload.refresh_token)
        )

    @router.post("/mini/auth/logout", status_code=204, tags=["identity-mini"])
    def mini_logout(
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> Response:
        token = bearer_token(authorization)
        mini_user(authorization)
        service.logout_session(
            token=token,
            terminal="mini",
            request_id=request.state.request_id,
        )
        return Response(status_code=204)

    @router.post(
        "/mini/me/avatar",
        response_model=AvatarResponse,
        tags=["identity-mini"],
    )
    async def replace_mini_avatar(
        request: Request,
        avatar: Annotated[UploadFile, File()],
        authorization: str | None = Header(default=None),
        idempotency_key: str = Header(alias="Idempotency-Key"),
    ) -> AvatarResponse:
        user = mini_user(authorization)
        content = await avatar.read()
        stored = service.replace_mini_avatar(
            user_id=user.user_id,
            original_filename=avatar.filename or "avatar",
            mime_type=avatar.content_type or "application/octet-stream",
            content=content,
            idempotency_key=idempotency_key,
            request_id=request.state.request_id,
        )
        return AvatarResponse.model_validate(stored, from_attributes=True)

    @router.get("/mini/me/avatar", tags=["identity-mini"])
    def get_mini_avatar(
        authorization: str | None = Header(default=None),
    ) -> Response:
        user = mini_user(authorization)
        avatar = service.get_mini_avatar(user_id=user.user_id)
        return Response(
            content=avatar.content,
            media_type=avatar.mime_type,
            headers={"Cache-Control": "private, no-store"},
        )

    return router
