from urllib.parse import quote

from fastapi import APIRouter, Cookie, Header, Request, Response
from pydantic import BaseModel, ConfigDict

from app.modules.box_labels import BoxLabelService
from app.modules.identity_access import IdentityAccessService, PermissionDenied, SessionInvalid


class ApiModel(BaseModel):
    model_config = ConfigDict(alias_generator=lambda name: name.split("_")[0] + "".join(
        part.capitalize() for part in name.split("_")[1:]
    ), populate_by_name=True)


class BoxLabelRow(ApiModel):
    group_id: str
    factory_id: str
    factory_name: str
    product_name: str
    color: str
    eligible: bool
    ineligible_reason: str | None


class BoxLabelList(ApiModel):
    items: list[BoxLabelRow]
    request_id: str


class BoxLabelExportResponse(ApiModel):
    export_id: str
    filename: str
    download_url: str
    request_id: str


def create_box_label_router(service: BoxLabelService, identity: IdentityAccessService) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["box-label-admin"])

    def admin(token: str | None, csrf: str | None = None, *, write: bool = False) -> str:
        if not token:
            raise SessionInvalid("web session is missing")
        actor = identity.authenticate_session(
            token=token, terminal="web", csrf_token=csrf, require_csrf=write
        )
        if actor.role != "admin":
            raise PermissionDenied("administrator role required")
        return actor.user_id

    @router.get("/admin/orders/{order_id}/box-labels", response_model=BoxLabelList)
    def list_labels(
        order_id: str, request: Request, ot_web_session: str | None = Cookie(default=None)
    ) -> BoxLabelList:
        rows = service.list_for_order(actor_id=admin(ot_web_session), order_id=order_id)
        return BoxLabelList(
            items=[BoxLabelRow.model_validate(row, from_attributes=True) for row in rows],
            request_id=request.state.request_id,
        )

    @router.post(
        "/admin/orders/{order_id}/box-labels/{group_id}/exports",
        response_model=BoxLabelExportResponse,
        status_code=201,
    )
    def export_label(
        order_id: str,
        group_id: str,
        request: Request,
        ot_web_session: str | None = Cookie(default=None),
        x_csrf_token: str | None = Header(default=None),
    ) -> BoxLabelExportResponse:
        export_id, filename = service.export(
            actor_id=admin(ot_web_session, x_csrf_token, write=True),
            order_id=order_id,
            selected_group_id=group_id,
        )
        return BoxLabelExportResponse(
            export_id=export_id,
            filename=filename,
            download_url=f"/api/v1/admin/box-label-exports/{export_id}/download",
            request_id=request.state.request_id,
        )

    @router.get("/admin/box-label-exports/{export_id}/download")
    def download_label(
        export_id: str, ot_web_session: str | None = Cookie(default=None)
    ) -> Response:
        filename, content, mime = service.download(
            actor_id=admin(ot_web_session), export_id=export_id
        )
        return Response(
            content=content,
            media_type=mime,
            headers={
                "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}",
                "X-Content-Type-Options": "nosniff",
            },
        )

    return router
