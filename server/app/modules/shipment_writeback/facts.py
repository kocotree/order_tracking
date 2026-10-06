from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.mysql import insert
from sqlalchemy.orm import Session

from app.db.models import (
    OrderAssignment,
    OrderDetail,
    OrderImportSourceRecord,
    Shipment,
    ShipmentLine,
    ShipmentWritebackControl,
    ShipmentWritebackFact,
)


def lock_facts(session: Session) -> ShipmentWritebackControl:
    # ponytail: 单表短事务串行；吞吐受限时按来源分锁，锁内禁止外部网络请求。
    session.execute(insert(ShipmentWritebackControl).values(id=1, history_ready=False, structure={})
                    .on_duplicate_key_update(id=1))
    return session.execute(select(ShipmentWritebackControl)
                           .where(ShipmentWritebackControl.id == 1).with_for_update()).scalar_one()


def utc_naive(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


def shipment_lines(session: Session, shipment_id: str) -> list[dict[str, Any]]:
    lines = []
    for line, _detail, source in session.execute(
        select(ShipmentLine, OrderDetail, OrderImportSourceRecord)
        .join(OrderAssignment,
              OrderAssignment.order_assignment_id == ShipmentLine.order_assignment_id)
        .outerjoin(OrderDetail, OrderDetail.detail_id == OrderAssignment.detail_id)
        .outerjoin(OrderImportSourceRecord,
                   OrderImportSourceRecord.source_record_pk == OrderDetail.source_record_pk)
        .where(ShipmentLine.shipment_id == shipment_id)
    ):
        lines.append({
            "assignment_id": line.order_assignment_id, "quantity": line.quantity,
            "order_no": line.order_no_snapshot,
            "detail_id": source.source_detail_id if source else None,
            "record_id": source.source_record_id if source else None,
            "source_scope": source.source_scope if source else None,
        })
    if not lines:
        raise ValueError("shipment_writeback_lines_missing")
    return lines


def capture(session: Session, shipment: Shipment, *, key: str, at: datetime) -> None:
    session.flush()
    session.add(ShipmentWritebackFact(
        root_id=shipment.shipment_id, event_key=key, status=shipment.status,
        occurred_at=utc_naive(at), lines=shipment_lines(session, shipment.shipment_id),
    ))
