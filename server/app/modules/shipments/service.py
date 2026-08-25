from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import Select, delete, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import (
    AuditLog,
    Factory,
    IdempotencyRecord,
    Order,
    OrderAssignment,
    OrderLine,
    OutboxMessage,
    QuantityLedger,
    Shipment,
    ShipmentBox,
    ShipmentBoxItem,
    ShipmentLine,
    ShipmentNumberCounter,
)

BUSINESS_TIME_ZONE = ZoneInfo("Asia/Shanghai")


class ShipmentError(Exception):
    pass


class ShipmentNotFound(ShipmentError):
    pass


class ShipmentPermissionDenied(ShipmentError):
    pass


class ShipmentConflict(ShipmentError):
    pass


class ShipmentValidationError(ShipmentError):
    pass


@dataclass(frozen=True)
class DraftItemInput:
    assignment_id: int
    quantity: int


@dataclass(frozen=True)
class DraftBoxInput:
    box_no: int
    group_key: str | None
    items: list[DraftItemInput]


@dataclass(frozen=True)
class ShipmentLineSnapshot:
    assignment_id: int
    order_id: str
    order_no: str
    sku_id: str
    product_name: str
    properties_value: str
    quantity: int


@dataclass(frozen=True)
class ShipmentBoxSnapshot:
    box_no: int
    group_key: str | None
    items: list[ShipmentLineSnapshot]


@dataclass(frozen=True)
class ShipmentDraftSnapshot:
    shipment_id: str
    status: str
    factory_id: str
    created_by: str
    preferred_order_id: str | None
    created_at: datetime
    factory_name: str = ""
    submitted_at: datetime | None = None
    shipment_no: str | None = None
    business_date: date | None = None
    note: str = ""
    total_boxes: int = 0
    total_quantity: int = 0
    lines: list[ShipmentLineSnapshot] = field(default_factory=list)
    boxes: list[ShipmentBoxSnapshot] = field(default_factory=list)


@dataclass(frozen=True)
class ShipmentCatalogItem:
    assignment_id: int
    order_id: str
    order_no: str
    contract_ship_date: date
    product_name: str
    properties_value: str
    assigned_quantity: int
    shipped_quantity: int
    pending_quantity: int


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

    def list_catalog(self, *, factory_id: str) -> list[ShipmentCatalogItem]:
        with self._sessions() as session:
            ledger = (
                select(
                    QuantityLedger.order_assignment_id.label("assignment_id"),
                    func.coalesce(func.sum(QuantityLedger.quantity_delta), 0).label("quantity"),
                )
                .group_by(QuantityLedger.order_assignment_id)
                .subquery()
            )
            rows = session.execute(
                select(OrderAssignment, OrderLine, Order, func.coalesce(ledger.c.quantity, 0))
                .join(OrderLine, OrderLine.order_line_id == OrderAssignment.order_line_id)
                .join(Order, Order.order_id == OrderLine.order_id)
                .outerjoin(ledger, ledger.c.assignment_id == OrderAssignment.order_assignment_id)
                .where(
                    OrderAssignment.factory_id == factory_id,
                    Order.lifecycle == "PUBLISHED",
                    Order.deleted_at.is_(None),
                )
                .order_by(
                    Order.contract_ship_date,
                    Order.order_no,
                    OrderLine.order_line_id,
                )
            ).all()
            return [
                ShipmentCatalogItem(
                    assignment_id=assignment.order_assignment_id,
                    order_id=order.order_id,
                    order_no=order.order_no,
                    contract_ship_date=order.contract_ship_date,
                    product_name=line.product_name_snapshot,
                    properties_value=line.properties_value_snapshot,
                    assigned_quantity=assignment.assigned_quantity,
                    shipped_quantity=assignment.initial_shipped_quantity + int(system_quantity),
                    pending_quantity=max(
                        assignment.assigned_quantity
                        - assignment.initial_shipped_quantity
                        - int(system_quantity),
                        0,
                    ),
                )
                for assignment, line, order, system_quantity in rows
            ]

    def save_draft(
        self,
        *,
        actor_id: str,
        factory_id: str,
        shipment_id: str,
        boxes: list[DraftBoxInput],
        note: str,
    ) -> ShipmentDraftSnapshot:
        with self._sessions.begin() as session:
            shipment = self._owned_shipment(session, shipment_id, actor_id, factory_id, lock=True)
            if shipment.status != "DRAFT":
                raise ShipmentConflict("submitted shipment cannot be edited")
            self._validate_boxes(boxes)
            assignment_ids = {item.assignment_id for box in boxes for item in box.items}
            self._load_assignments(session, assignment_ids, factory_id)
            box_ids = select(ShipmentBox.box_id).where(ShipmentBox.shipment_id == shipment_id)
            session.execute(delete(ShipmentBoxItem).where(ShipmentBoxItem.box_id.in_(box_ids)))
            session.execute(delete(ShipmentBox).where(ShipmentBox.shipment_id == shipment_id))
            for box_input in sorted(boxes, key=lambda item: item.box_no):
                box = ShipmentBox(
                    shipment_id=shipment_id,
                    box_no=box_input.box_no,
                    group_key=box_input.group_key,
                )
                session.add(box)
                session.flush()
                for item in box_input.items:
                    session.add(
                        ShipmentBoxItem(
                            box_id=box.box_id,
                            order_assignment_id=item.assignment_id,
                            quantity=item.quantity,
                        )
                    )
            shipment.note = note.strip() or None
            session.flush()
            return self._detail_snapshot(session, shipment)

    def get_current_draft(self, *, actor_id: str, factory_id: str) -> ShipmentDraftSnapshot:
        with self._sessions() as session:
            shipment = session.scalar(
                select(Shipment).where(
                    Shipment.active_draft_owner_id == actor_id,
                    Shipment.factory_id == factory_id,
                    Shipment.status == "DRAFT",
                    Shipment.deleted_at.is_(None),
                )
            )
            if shipment is None:
                raise ShipmentNotFound("draft not found")
            return self._detail_snapshot(session, shipment)

    def submit_draft(
        self,
        *,
        actor_id: str,
        factory_id: str,
        shipment_id: str,
        idempotency_key: str,
        now: datetime | None = None,
    ) -> ShipmentDraftSnapshot:
        current = now or datetime.now(UTC)
        business_date = current.astimezone(BUSINESS_TIME_ZONE).date()
        with self._sessions.begin() as session:
            shipment = self._owned_shipment(session, shipment_id, actor_id, factory_id, lock=True)
            if shipment.status == "SHIPPED":
                return self._detail_snapshot(session, shipment)
            boxes = self._box_inputs(session, shipment_id)
            self._validate_boxes(boxes)
            totals: dict[int, int] = defaultdict(int)
            for box in boxes:
                for item in box.items:
                    totals[item.assignment_id] += item.quantity
            assignments = self._load_assignments(session, set(totals), factory_id, lock=True)
            scope = f"shipment.submit:{actor_id}"
            existing_key = session.scalar(
                select(IdempotencyRecord).where(
                    IdempotencyRecord.scope == scope,
                    IdempotencyRecord.idempotency_key == idempotency_key,
                )
            )
            if existing_key is not None:
                return self._detail_snapshot(session, shipment)
            session.add(
                IdempotencyRecord(scope=scope, idempotency_key=idempotency_key, status="completed")
            )
            counter = session.get(ShipmentNumberCounter, business_date, with_for_update=True)
            if counter is None:
                counter = ShipmentNumberCounter(
                    business_date=business_date, next_sequence=2, updated_at=current
                )
                session.add(counter)
                sequence = 1
            else:
                sequence = counter.next_sequence
                counter.next_sequence += 1
                counter.updated_at = current
            shipment.shipment_no = f"FH{business_date:%Y%m%d}-{sequence:03d}"
            shipment.business_date = business_date
            shipment.status = "SHIPPED"
            shipment.submitted_by = actor_id
            shipment.submitted_at = current
            shipment.active_draft_owner_id = None
            for assignment_id, quantity in totals.items():
                assignment, line, order = assignments[assignment_id]
                session.add(
                    ShipmentLine(
                        shipment_id=shipment_id,
                        order_assignment_id=assignment_id,
                        quantity=quantity,
                        order_no_snapshot=order.order_no,
                        sku_id_snapshot=line.sku_id_snapshot,
                        product_name_snapshot=line.product_name_snapshot,
                        properties_value_snapshot=line.properties_value_snapshot,
                    )
                )
                session.add(
                    QuantityLedger(
                        order_assignment_id=assignment_id,
                        source_type="SHIPMENT",
                        source_id=shipment_id,
                        quantity_delta=quantity,
                        actor_id=actor_id,
                        created_at=current,
                    )
                )
                session.add(
                    AuditLog(
                        request_id=idempotency_key[:64],
                        action="shipment_submitted",
                        target_type="order",
                        target_id=order.order_id,
                        changes={"shipmentId": shipment_id, "quantity": quantity},
                        actor_id=actor_id,
                        source_terminal="factory-mini",
                    )
                )
            session.add(
                OutboxMessage(
                    event_type="shipment.submitted",
                    aggregate_type="shipment",
                    aggregate_id=shipment_id,
                    dedupe_key=f"shipment:{shipment_id}:submitted",
                    payload={"shipmentId": shipment_id, "shipmentNo": shipment.shipment_no},
                    status="pending",
                    available_at=current,
                )
            )
            session.flush()
            return self._detail_snapshot(session, shipment)

    def list_shipments(self, *, factory_id: str | None = None) -> list[ShipmentDraftSnapshot]:
        with self._sessions() as session:
            query = select(Shipment).where(
                Shipment.status == "SHIPPED", Shipment.deleted_at.is_(None)
            )
            if factory_id is not None:
                query = query.where(Shipment.factory_id == factory_id)
            shipments = list(
                session.scalars(query.order_by(Shipment.submitted_at.desc(), Shipment.shipment_id))
            )
            return [self._detail_snapshot(session, item) for item in shipments]

    def get_shipment(
        self, *, shipment_id: str, factory_id: str | None = None
    ) -> ShipmentDraftSnapshot:
        with self._sessions() as session:
            shipment = session.get(Shipment, shipment_id)
            if shipment is None or shipment.status != "SHIPPED" or shipment.deleted_at is not None:
                raise ShipmentNotFound("shipment not found")
            if factory_id is not None and shipment.factory_id != factory_id:
                raise ShipmentNotFound("shipment not found")
            return self._detail_snapshot(session, shipment)

    def has_valid_shipments(self, *, order_id: str) -> bool:
        with self._sessions() as session:
            return bool(
                session.scalar(
                    select(ShipmentLine.line_id)
                    .join(
                        OrderAssignment,
                        OrderAssignment.order_assignment_id == ShipmentLine.order_assignment_id,
                    )
                    .join(OrderLine, OrderLine.order_line_id == OrderAssignment.order_line_id)
                    .join(Shipment, Shipment.shipment_id == ShipmentLine.shipment_id)
                    .where(OrderLine.order_id == order_id, Shipment.status == "SHIPPED")
                    .limit(1)
                )
            )

    def has_pending_void_requests(self, *, order_id: str) -> bool:
        del order_id
        return False

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

    @staticmethod
    def _validate_boxes(boxes: list[DraftBoxInput]) -> None:
        if not boxes or len({box.box_no for box in boxes}) != len(boxes):
            raise ShipmentValidationError("box numbers must be unique")
        for box in boxes:
            if type(box.box_no) is not int or box.box_no <= 0 or not box.items:
                raise ShipmentValidationError("each box requires contents")
            if len({item.assignment_id for item in box.items}) != len(box.items):
                raise ShipmentValidationError("duplicate assignment in box")
            if any(type(item.quantity) is not int or item.quantity <= 0 for item in box.items):
                raise ShipmentValidationError("box quantities must be positive integers")

    @staticmethod
    def _owned_shipment(
        session: Session, shipment_id: str, actor_id: str, factory_id: str, *, lock: bool
    ) -> Shipment:
        query = select(Shipment).where(
            Shipment.shipment_id == shipment_id,
            Shipment.created_by == actor_id,
            Shipment.factory_id == factory_id,
            Shipment.deleted_at.is_(None),
        )
        if lock:
            query = query.with_for_update()
        shipment = session.scalar(query)
        if shipment is None:
            raise ShipmentNotFound("shipment not found")
        return shipment

    @staticmethod
    def _load_assignments(
        session: Session,
        assignment_ids: set[int],
        factory_id: str,
        *,
        lock: bool = False,
        require_published: bool = True,
    ) -> dict[int, tuple[OrderAssignment, OrderLine, Order]]:
        if not assignment_ids:
            raise ShipmentValidationError("shipment requires contents")
        query = (
            select(OrderAssignment, OrderLine, Order)
            .join(OrderLine, OrderLine.order_line_id == OrderAssignment.order_line_id)
            .join(Order, Order.order_id == OrderLine.order_id)
            .where(
                OrderAssignment.order_assignment_id.in_(assignment_ids),
                OrderAssignment.factory_id == factory_id,
                Order.deleted_at.is_(None),
            )
        )
        if require_published:
            query = query.where(Order.lifecycle == "PUBLISHED")
        if lock:
            query = query.with_for_update()
        rows = session.execute(query).all()
        result = {
            assignment.order_assignment_id: (assignment, line, order)
            for assignment, line, order in rows
        }
        if set(result) != assignment_ids:
            raise ShipmentNotFound("assignment is not available to this factory")
        return result

    @staticmethod
    def _box_inputs(session: Session, shipment_id: str) -> list[DraftBoxInput]:
        boxes = list(
            session.scalars(
                select(ShipmentBox)
                .where(ShipmentBox.shipment_id == shipment_id)
                .order_by(ShipmentBox.box_no)
            )
        )
        return [
            DraftBoxInput(
                box_no=box.box_no,
                group_key=box.group_key,
                items=[
                    DraftItemInput(assignment_id=item.order_assignment_id, quantity=item.quantity)
                    for item in session.scalars(
                        select(ShipmentBoxItem)
                        .where(ShipmentBoxItem.box_id == box.box_id)
                        .order_by(ShipmentBoxItem.item_id)
                    )
                ],
            )
            for box in boxes
        ]

    def _detail_snapshot(self, session: Session, shipment: Shipment) -> ShipmentDraftSnapshot:
        box_inputs = self._box_inputs(session, shipment.shipment_id)
        assignment_ids = {item.assignment_id for box in box_inputs for item in box.items}
        assignments = (
            self._load_assignments(
                session,
                assignment_ids,
                shipment.factory_id,
                require_published=shipment.status == "DRAFT",
            )
            if assignment_ids
            else {}
        )
        factory = session.get(Factory, shipment.factory_id)
        boxes: list[ShipmentBoxSnapshot] = []
        totals: dict[int, int] = defaultdict(int)
        for box in box_inputs:
            items = []
            for item in box.items:
                assignment, line, order = assignments[item.assignment_id]
                value = ShipmentLineSnapshot(
                    assignment_id=item.assignment_id,
                    order_id=order.order_id,
                    order_no=order.order_no,
                    sku_id=line.sku_id_snapshot,
                    product_name=line.product_name_snapshot,
                    properties_value=line.properties_value_snapshot,
                    quantity=item.quantity,
                )
                items.append(value)
                totals[item.assignment_id] += item.quantity
            boxes.append(
                ShipmentBoxSnapshot(box_no=box.box_no, group_key=box.group_key, items=items)
            )
        lines = []
        for assignment_id, quantity in totals.items():
            _assignment, line, order = assignments[assignment_id]
            lines.append(
                ShipmentLineSnapshot(
                    assignment_id=assignment_id,
                    order_id=order.order_id,
                    order_no=order.order_no,
                    sku_id=line.sku_id_snapshot,
                    product_name=line.product_name_snapshot,
                    properties_value=line.properties_value_snapshot,
                    quantity=quantity,
                )
            )
        return ShipmentDraftSnapshot(
            shipment_id=shipment.shipment_id,
            shipment_no=shipment.shipment_no,
            status=shipment.status,
            factory_id=shipment.factory_id,
            factory_name=factory.factory_name if factory is not None else "",
            created_by=shipment.created_by,
            preferred_order_id=shipment.preferred_order_id,
            business_date=shipment.business_date,
            note=shipment.note or "",
            total_boxes=len(boxes),
            total_quantity=sum(totals.values()),
            lines=lines,
            boxes=boxes,
            created_at=shipment.created_at,
            submitted_at=shipment.submitted_at,
        )
