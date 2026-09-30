from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import OrderAssignment, OrderDetail, QuantityLedger


def pending_totals(session: Session, detail_ids: Sequence[str]) -> dict[str, int]:
    return {row[0]: int(row[1]) for row in session.execute(
        select(QuantityLedger.order_detail_id, func.sum(QuantityLedger.quantity_delta))
        .where(QuantityLedger.order_detail_id.in_(detail_ids))
        .group_by(QuantityLedger.order_detail_id)
    )}


def active_assignment(session: Session, detail: OrderDetail) -> OrderAssignment | None:
    assignment = session.get(OrderAssignment, detail.assignment_id, with_for_update=True) \
        if detail.assignment_id else None
    return assignment if (assignment and assignment.is_active
                          and detail.dispatch_state == "ASSIGNED") else None


def detail_shipped(session: Session, detail: OrderDetail) -> int | None:
    assignment = active_assignment(session, detail)
    if assignment:
        delta = session.scalar(select(func.sum(QuantityLedger.quantity_delta)).where(
            QuantityLedger.order_assignment_id == assignment.order_assignment_id
        ).with_for_update()) or 0
        return assignment.initial_shipped_quantity + int(delta)
    if detail.source_shipped_quantity is None:
        return None
    delta = session.scalar(select(func.sum(QuantityLedger.quantity_delta)).where(
        QuantityLedger.order_detail_id == detail.detail_id
    ).with_for_update()) or 0
    return detail.source_shipped_quantity + int(delta)
