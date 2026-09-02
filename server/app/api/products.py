from io import BytesIO
from typing import Annotated, Literal

from fastapi import APIRouter, Cookie, HTTPException, Query, Response
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict

from app.adapters.private_files import PrivateFileStore, PrivateFileStoreUnavailable
from app.modules.identity_access import IdentityAccessService, PermissionDenied, SessionInvalid
from app.modules.product_sync import ProductCatalogService, ProductListItem


def to_camel(value: str) -> str:
    first, *rest = value.split("_")
    return first + "".join(part.capitalize() for part in rest)


class ApiModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class ProductListItemResponse(ApiModel):
    variant_id: str
    i_id: str
    sku_id: str
    name: str
    properties_value: str
    image_available: bool
    image_url: str | None


class ProductListResponse(ApiModel):
    items: list[ProductListItemResponse]
    total: int
    page: int
    page_size: int


def _item_response(item: ProductListItem) -> ProductListItemResponse:
    image_url = None
    if item.image_version is not None:
        image_url = (
            f"/api/v1/admin/products/{item.product_id}/image"
            f"?v={item.image_version}"
        )
    return ProductListItemResponse(
        variant_id=item.variant_id,
        i_id=item.i_id,
        sku_id=item.sku_id,
        name=item.name,
        properties_value=item.properties_value,
        image_available=item.image_available,
        image_url=image_url,
    )


def create_product_router(
    service: ProductCatalogService,
    identity: IdentityAccessService,
    *,
    file_store: PrivateFileStore,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1")

    @router.get(
        "/admin/products",
        response_model=ProductListResponse,
        tags=["product-admin"],
    )
    def list_products(
        keyword: str = Query(default="", max_length=255),
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[int, Query(alias="pageSize", ge=1, le=100)] = 10,
        sort_by: Annotated[
            Literal["iId", "skuId", "name", "propertiesValue"],
            Query(alias="sortBy"),
        ] = "iId",
        sort_order: Annotated[
            Literal["asc", "desc"],
            Query(alias="sortOrder"),
        ] = "asc",
        ot_web_session: str | None = Cookie(default=None),
    ) -> ProductListResponse:
        if not ot_web_session:
            raise SessionInvalid("web session is missing")
        actor = identity.authenticate_session(token=ot_web_session, terminal="web")
        if actor.role != "admin":
            raise PermissionDenied("administrator role required")
        result = service.list_available(
            keyword=keyword,
            page=page,
            page_size=page_size,
            sort_by=sort_by,
            sort_order=sort_order,
        )
        return ProductListResponse(
            items=[_item_response(item) for item in result.items],
            total=result.total,
            page=result.page,
            page_size=result.page_size,
        )

    @router.get(
        "/admin/products/{product_id}/image",
        tags=["product-admin"],
        response_class=Response,
        responses={
            200: {
                "content": {
                    "image/*": {"schema": {"type": "string", "format": "binary"}}
                }
            }
        },
    )
    def get_product_image(
        product_id: str,
        v: Annotated[str, Query(min_length=1, max_length=64)],
        ot_web_session: str | None = Cookie(default=None),
    ) -> Response:
        if not ot_web_session:
            raise SessionInvalid("web session is missing")
        actor = identity.authenticate_session(token=ot_web_session, terminal="web")
        if actor.role != "admin":
            raise PermissionDenied("administrator role required")
        object_key = service.get_cached_image_object_key(
            product_id=product_id,
            image_version=v,
        )
        if object_key is None:
            raise HTTPException(status_code=404, detail="产品图片不存在")
        try:
            content = file_store.get(object_key=object_key)
            with Image.open(BytesIO(content)) as image:
                media_type = image.get_format_mimetype()
        except (PrivateFileStoreUnavailable, UnidentifiedImageError, OSError):
            raise HTTPException(status_code=404, detail="产品图片不存在") from None
        if media_type is None or not media_type.startswith("image/"):
            raise HTTPException(status_code=404, detail="产品图片不存在")
        return Response(
            content=content,
            media_type=media_type,
            headers={
                "Cache-Control": "private, max-age=31536000, immutable",
                "Vary": "Cookie",
                "X-Content-Type-Options": "nosniff",
            },
        )

    return router
