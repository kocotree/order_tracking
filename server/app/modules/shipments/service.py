from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4

from sqlalchemy import Select, select
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import Order, OrderAssignment, OrderLine, Shipment


class ShipmentError(Exception):
    pass


class ShipmentNotFound(ShipmentError):
    pass


class ShipmentPermissionDenied(ShipmentError):
    pass


@dataclass(frozen=True)
class ShipmentDraftSnapshot:
    shipment_id: str
    status: str
    factory_id: str
    created_by: str
    preferred_order_id: str | None
    created_at: datetime


class ShipmentService:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self._sessions = sessions

    def create_or_reuse_draft(
        self,
        *,
        actor_id: str,
        factory_id: str,
        preferred_order_id: str | None,
    ) -> tuple[ShipmentDraftSnapshot, bool]:
        with self._sessions.begin() as session:
            existing = session.scalar(
                select(Shipment).where(
                    Shipment.active_draft_owner_id == actor_id,
                    Shipment.status == "DRAFT",
                    Shipment.deleted_at.is_(None),
                )
            )
            if existing is not None:
                return self._snapshot(existing), False

            if preferred_order_id is not None and not session.scalar(
                self._preferred_order_query(
                    order_id=preferred_order_id,
                    factory_id=factory_id,
                )
            ):
                raise ShipmentNotFound("preferred order is not available to this factory")

            draft = Shipment(
                shipment_id=str(uuid4()),
                factory_id=factory_id,
                status="DRAFT",
                preferred_order_id=preferred_order_id,
                created_by=actor_id,
                active_draft_owner_id=actor_id,
            )
            session.add(draft)
            session.flush()
            return self._snapshot(draft), True

    @staticmethod
    def _preferred_order_query(*, order_id: str, factory_id: str) -> Select[tuple[str]]:
        return (
            select(Order.order_id)
            .join(OrderLine, OrderLine.order_id == Order.order_id)
            .join(OrderAssignment, OrderAssignment.order_line_id == OrderLine.order_line_id)
            .where(
                Order.order_id == order_id,
                Order.lifecycle == "PUBLISHED",
                Order.deleted_at.is_(None),
                OrderAssignment.factory_id == factory_id,
            )
            .limit(1)
        )

    @staticmethod
    def _snapshot(shipment: Shipment) -> ShipmentDraftSnapshot:
        return ShipmentDraftSnapshot(
            shipment_id=shipment.shipment_id,
            status=shipment.status,
            factory_id=shipment.factory_id,
            created_by=shipment.created_by,
            preferred_order_id=shipment.preferred_order_id,
            created_at=shipment.created_at,
        )
