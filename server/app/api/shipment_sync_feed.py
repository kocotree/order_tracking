from datetime import date, datetime
from secrets import compare_digest
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Response
from pydantic import AwareDatetime, BaseModel

from app.modules.shipment_writeback.service import ShipmentWriteback


class ShipmentSyncFeedRow(BaseModel):
    record_id: str
    order_no: str
    detail_id: str
    quantity: int


class ShipmentSyncFeed(BaseModel):
    table_id: str
    stage: str
    cutoff: str
    field: str
    rows: list[ShipmentSyncFeedRow]


class ShipmentNetFeed(BaseModel):
    activation: str
    cutoff: str
    snapshots: list[ShipmentSyncFeed]


def create_shipment_sync_feed_router(
    service: ShipmentWriteback, *, table_id: str, token: str, start: date | None,
    returns_from: datetime | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/integrations/shipment-sync")

    @router.get("/feed", response_model=ShipmentSyncFeed | None)
    def get_feed(
        response: Response, authorization: Annotated[str | None, Header()] = None,
        final: bool = False,
    ) -> dict[str, object] | None:
        if start is None:
            raise HTTPException(status_code=404, detail="shipment sync feed is disabled")
        if not token or not compare_digest(
            (authorization or "").encode(), f"Bearer {token}".encode(),
        ):
            raise HTTPException(status_code=401, detail="invalid integration credential")
        response.headers["Cache-Control"] = "no-store"
        try:
            result = service.feed(start=start, final=final)
            return None if result is None else {"table_id": table_id, **result}
        except ValueError as error:
            raise HTTPException(status_code=503, detail="shipment snapshot unavailable") from error

    @router.get("/net-feed", response_model=ShipmentNetFeed)
    def get_net_feed(
        response: Response, authorization: Annotated[str | None, Header()] = None,
        after: AwareDatetime | None = None,
    ) -> dict[str, object]:
        if start is None or returns_from is None:
            raise HTTPException(status_code=404, detail="net shipment feed is disabled")
        if not token or not compare_digest(
            (authorization or "").encode(), f"Bearer {token}".encode(),
        ):
            raise HTTPException(status_code=401, detail="invalid integration credential")
        response.headers["Cache-Control"] = "no-store"
        try:
            result = service.net_feed(start=start, activation=returns_from, after=after)
            return {**result, "snapshots": [
                {"table_id": table_id, **snapshot} for snapshot in result["snapshots"]
            ]}
        except ValueError as error:
            raise HTTPException(
                status_code=503, detail="net shipment snapshot unavailable",
            ) from error

    return router
