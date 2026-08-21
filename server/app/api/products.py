from typing import Annotated, Literal

from fastapi import APIRouter, Cookie, Query
from pydantic import BaseModel, ConfigDict

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


class ProductListResponse(ApiModel):
    items: list[ProductListItemResponse]
    total: int
    page: int
    page_size: int


def _item_response(item: ProductListItem) -> ProductListItemResponse:
    return ProductListItemResponse.model_validate(item, from_attributes=True)


def create_product_router(
    service: ProductCatalogService,
    identity: IdentityAccessService,
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

    return router
