from urllib.parse import urlencode

from fastapi import APIRouter, Cookie, Form, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response

from app.api.identity import set_web_session_cookies
from app.modules.identity_access.agent_oauth import SCOPE, AgentOAuthService, OAuthInvalid
from app.modules.identity_access.service import IdentityAccessService, SessionInvalid


def create_agent_oauth_router(
    oauth: AgentOAuthService, identity: IdentityAccessService, *, secure_cookies: bool
) -> APIRouter:
    router = APIRouter()
    issuer = f"{oauth.resource.removesuffix('/mcp')}/"

    @router.get("/.well-known/oauth-authorization-server", include_in_schema=False)
    def metadata() -> dict[str, object]:
        return {
            "issuer": issuer,
            "authorization_endpoint": f"{issuer}oauth/authorize",
            "token_endpoint": f"{issuer}oauth/token",
            "revocation_endpoint": f"{issuer}oauth/revoke",
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code", "refresh_token"],
            "code_challenge_methods_supported": ["S256"],
            "token_endpoint_auth_methods_supported": ["none"],
            "scopes_supported": [SCOPE],
            "authorization_response_iss_parameter_supported": True,
        }

    @router.get("/oauth/authorize", include_in_schema=False)
    def authorize(
        request: Request,
        request_id: str | None = None,
        ot_agent_oauth: str | None = Cookie(default=None),
        ot_web_session: str | None = Cookie(default=None),
        ot_web_refresh: str | None = Cookie(default=None),
    ) -> RedirectResponse:
        if request_id is None:
            names = (
                "client_id", "redirect_uri", "resource", "scope", "state",
                "code_challenge", "code_challenge_method", "response_type",
            )
            values = {name: request.query_params.getlist(name) for name in names}
            if any(len(value) != 1 for name, value in values.items() if name != "resource"):
                raise OAuthInvalid()
            if not values["resource"] or len(set(values["resource"])) != 1:
                raise OAuthInvalid()
            pending_id, nonce = oauth.begin_authorization(**{
                name: value[0] for name, value in values.items()
            })
            response = RedirectResponse(
                f"/oauth/authorize?{urlencode({'request_id': pending_id})}", status_code=303
            )
            response.set_cookie(
                "ot_agent_oauth", nonce, max_age=300, secure=secure_cookies,
                httponly=True, samesite="lax", path="/oauth/",
            )
            return response
        if not ot_agent_oauth:
            raise OAuthInvalid()
        try:
            if not ot_web_session:
                raise SessionInvalid("web session is missing")
            user_id, auth_id = identity.web_authorization_id(token=ot_web_session)
        except SessionInvalid:
            if ot_web_refresh:
                try:
                    refreshed = identity.refresh_web_session(refresh_token=ot_web_refresh)
                except SessionInvalid:
                    pass
                else:
                    if refreshed.refresh_token is None or refreshed.csrf_token is None:
                        raise RuntimeError("web refresh returned incomplete credentials")
                    response = RedirectResponse(
                        f"/oauth/authorize?{urlencode({'request_id': request_id})}",
                        status_code=303,
                    )
                    set_web_session_cookies(
                        response, access_token=refreshed.access_token,
                        refresh_token=refreshed.refresh_token,
                        csrf_token=refreshed.csrf_token, secure=secure_cookies,
                    )
                    return response
            return_to = f"/oauth/authorize?{urlencode({'request_id': request_id})}"
            return RedirectResponse(
                f"/api/v1/auth/feishu/start?{urlencode({'returnTo': return_to})}",
                status_code=303,
            )
        redirect_uri, state, code = oauth.finish_authorization(
            request_id=request_id, browser_nonce=ot_agent_oauth,
            user_id=user_id, auth_id=auth_id,
        )
        response = RedirectResponse(
            f"{redirect_uri}?{urlencode({'code': code, 'state': state, 'iss': issuer})}",
            status_code=303,
        )
        response.delete_cookie("ot_agent_oauth", path="/oauth/", secure=secure_cookies)
        return response

    @router.post("/oauth/token", include_in_schema=False)
    def token(
        request: Request,
        grant_type: str = Form(),
        client_id: str = Form(),
        resource: str = Form(),
        code: str | None = Form(default=None),
        redirect_uri: str | None = Form(default=None),
        code_verifier: str | None = Form(default=None),
        refresh_token: str | None = Form(default=None),
        client_secret: str | None = Form(default=None),
    ) -> Response:
        if (
            request.headers.get("authorization")
            or "client_secret" in request.query_params
            or client_secret is not None
        ):
            raise OAuthInvalid("invalid_client")
        if grant_type == "authorization_code" and code and redirect_uri and code_verifier:
            result = oauth.exchange_code(
                code=code, client_id=client_id, redirect_uri=redirect_uri,
                verifier=code_verifier, resource=resource,
            )
        elif grant_type == "refresh_token" and refresh_token:
            result = oauth.refresh(
                refresh_token=refresh_token, client_id=client_id, resource=resource
            )
        else:
            raise OAuthInvalid("unsupported_grant_type")
        if "error" in result:
            return JSONResponse(result, status_code=400, headers={"Cache-Control": "no-store"})
        return JSONResponse(result, headers={"Cache-Control": "no-store", "Pragma": "no-cache"})

    @router.post("/oauth/revoke", status_code=200, include_in_schema=False)
    def revoke(raw_token: str = Form(alias="token"), client_id: str = Form()) -> Response:
        oauth.revoke(raw_token=raw_token, client_id=client_id)
        return Response(status_code=200)

    return router
