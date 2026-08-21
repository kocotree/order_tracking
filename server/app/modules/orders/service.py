from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any, Protocol
from uuid import uuid4

from sqlalchemy import delete, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import (
    AuditLog,
    Factory,
    IdempotencyRecord,
    Order,
    OrderAssignment,
    OrderCompletionRecord,
    OrderLine,
    OutboxMessage,
    Product,
    ProductVariant,
    User,
)

TRACKERS = frozenset({"烧麦", "松子", "橄榄", "大葱", "青椒"})


class OrderError(ValueError):
    pass


class OrderValidationError(OrderError):
    pass


class OrderConflict(OrderError):
    pass


class OrderNotFound(OrderError):
    pass


class OrderPermissionDenied(OrderError):
    pass


class OrderExecutionGuard(Protocol):
    def has_valid_shipments(self, *, order_id: str) -> bool: ...

    def has_pending_void_requests(self, *, order_id: str) -> bool: ...


class EmptyOrderExecutionGuard:
    def has_valid_shipments(self, *, order_id: str) -> bool:
        return False

    def has_pending_void_requests(self, *, order_id: str) -> bool:
        return False


@dataclass(frozen=True)
class AssignmentInput:
    factory_id: str
    quantity: int


@dataclass(frozen=True)
class DraftLineInput:
    variant_id: str
    order_quantity: int
    assignments: list[AssignmentInput]


@dataclass(frozen=True)
class AssignmentSnapshot:
    assignment_id: int
    factory_id: str
    factory_name: str
    assigned_quantity: int
    shipped_quantity: int
    pending_quantity: int
    over_quantity: int
    short_quantity: int
    progress_percent: int


@dataclass(frozen=True)
class LineSnapshot:
    order_line_id: int
    variant_id: str
    sku_id: str
    product_name: str
    properties_value: str
    category: str | None
    image_object_key: str | None
    order_quantity: int
    shipped_quantity: int
    pending_quantity: int
    over_quantity: int
    short_quantity: int
    progress_percent: int
    assignments: list[AssignmentSnapshot]


@dataclass(frozen=True)
class FactoryProgressSnapshot:
    factory_id: str
    factory_name: str
    order_quantity: int
    shipped_quantity: int
    pending_quantity: int
    over_quantity: int
    short_quantity: int
    progress_percent: int


@dataclass(frozen=True)
class OrderSnapshot:
    order_id: str
    order_no: str
    source: str
    order_date: date
    tracker: str
    contract_ship_date: date
    lifecycle: str
    display_status: str
    version: int
    total_quantity: int
    shipped_quantity: int
    pending_quantity: int
    over_quantity: int
    short_quantity: int
    progress_percent: int
    lines: list[LineSnapshot]
    factory_progress: list[FactoryProgressSnapshot]
    validation_issues: list[str]
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class OrderAuditSnapshot:
    action: str
    changes: dict[str, object]
    actor_id: str | None
    source_terminal: str | None
    created_at: datetime


class OrderService:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        execution_guard: OrderExecutionGuard | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock
        self._execution_guard = execution_guard or EmptyOrderExecutionGuard()

    def create_draft(
        self,
        *,
        actor_id: str,
        order_no: str,
        order_date: date,
        tracker: str,
        contract_ship_date: date,
        lines: list[DraftLineInput],
        request_id: str,
    ) -> OrderSnapshot:
        normalized_order_no = self._normalize_order_no(order_no)
        self._validate_header(tracker=tracker, lines=lines)
        now = self._now()
        order_id = str(uuid4())
        try:
            with self._session_factory() as session, session.begin():
                self._require_admin(session, actor_id)
                order = Order(
                    order_id=order_id,
                    order_no=normalized_order_no,
                    source="manual",
                    order_date=order_date,
                    tracker=tracker,
                    contract_ship_date=contract_ship_date,
                    lifecycle="DRAFT",
                    version=1,
                    created_by=actor_id,
                    updated_by=actor_id,
                    created_at=now,
                    updated_at=now,
                )
                session.add(order)
                session.flush()
                self._replace_lines(session, order=order, lines=lines, now=now)
                self._add_audit(
                    session,
                    request_id=request_id,
                    action="order.draft_created",
                    order_id=order_id,
                    actor_id=actor_id,
                    changes={"orderNo": normalized_order_no, "source": "manual"},
                )
        except IntegrityError as error:
            raise OrderConflict("order number already exists") from error
        return self.get(order_id=order_id, today=now.date())

    def save_draft(
        self,
        *,
        actor_id: str,
        order_id: str,
        version: int,
        order_no: str,
        order_date: date,
        tracker: str,
        contract_ship_date: date,
        lines: list[DraftLineInput],
        request_id: str,
    ) -> OrderSnapshot:
        normalized_order_no = self._normalize_order_no(order_no)
        self._validate_header(tracker=tracker, lines=lines)
        now = self._now()
        try:
            with self._session_factory() as session, session.begin():
                self._require_admin(session, actor_id)
                order = self._locked_order(session, order_id)
                if order.lifecycle != "DRAFT" or order.version != version:
                    raise OrderConflict("order state or version changed")
                order.order_no = normalized_order_no
                order.order_date = order_date
                order.tracker = tracker
                order.contract_ship_date = contract_ship_date
                order.version += 1
                order.updated_by = actor_id
                order.updated_at = now
                self._replace_lines(session, order=order, lines=lines, now=now)
                self._add_audit(
                    session,
                    request_id=request_id,
                    action="order.draft_updated",
                    order_id=order_id,
                    actor_id=actor_id,
                    changes={"version": order.version},
                )
                session.flush()
                result = self._snapshot(session, order, now.date())
        except IntegrityError as error:
            raise OrderConflict("order number already exists") from error
        return result

    def publish(
        self,
        *,
        actor_id: str,
        order_id: str,
        version: int,
        request_id: str,
        idempotency_key: str,
    ) -> OrderSnapshot:
        now = self._now()
        with self._session_factory() as session, session.begin():
            self._require_admin(session, actor_id)
            existing = self._idempotency_exists(
                session, scope=f"order.publish:{order_id}", key=idempotency_key
            )
            if existing:
                return self._snapshot(session, self._require_order(session, order_id), now.date())
            order = self._locked_order(session, order_id)
            if order.lifecycle != "DRAFT" or order.version != version:
                raise OrderConflict("order state or version changed")
            factory_ids = self._validate_publish(session, order)
            before_version = order.version
            order.lifecycle = "PUBLISHED"
            order.version += 1
            order.published_at = now
            order.published_by = actor_id
            order.updated_at = now
            order.updated_by = actor_id
            self._add_idempotency(
                session, scope=f"order.publish:{order_id}", key=idempotency_key
            )
            self._add_factory_events(
                session,
                order_id=order_id,
                factory_ids=factory_ids,
                event_type="order_published",
                event_version=before_version,
                now=now,
            )
            self._add_audit(
                session,
                request_id=request_id,
                action="order.published",
                order_id=order_id,
                actor_id=actor_id,
                changes={"before": "DRAFT", "after": "PUBLISHED"},
            )
            session.flush()
            return self._snapshot(session, order, now.date())

    def withdraw(
        self,
        *,
        actor_id: str,
        order_id: str,
        request_id: str,
        idempotency_key: str,
    ) -> OrderSnapshot:
        now = self._now()
        with self._session_factory() as session, session.begin():
            self._require_admin(session, actor_id)
            scope = f"order.withdraw:{order_id}"
            if self._idempotency_exists(session, scope=scope, key=idempotency_key):
                return self._snapshot(session, self._require_order(session, order_id), now.date())
            order = self._locked_order(session, order_id)
            if order.lifecycle != "PUBLISHED":
                raise OrderConflict("only published orders can be withdrawn")
            if self._execution_guard.has_valid_shipments(order_id=order_id):
                raise OrderConflict("order has valid shipments")
            factory_ids = self._factory_ids(session, order_id)
            order.lifecycle = "DRAFT"
            order.version += 1
            order.updated_at = now
            order.updated_by = actor_id
            self._add_idempotency(session, scope=scope, key=idempotency_key)
            self._add_factory_events(
                session,
                order_id=order_id,
                factory_ids=factory_ids,
                event_type="order_withdrawn",
                event_version=order.version,
                now=now,
            )
            self._add_audit(
                session,
                request_id=request_id,
                action="order.withdrawn",
                order_id=order_id,
                actor_id=actor_id,
                changes={"before": "PUBLISHED", "after": "DRAFT"},
            )
            session.flush()
            return self._snapshot(session, order, now.date())

    def delete(
        self,
        *,
        actor_id: str,
        order_id: str,
        request_id: str,
        idempotency_key: str,
    ) -> None:
        now = self._now()
        with self._session_factory() as session, session.begin():
            self._require_admin(session, actor_id)
            scope = f"order.delete:{order_id}"
            if self._idempotency_exists(session, scope=scope, key=idempotency_key):
                return
            order = self._locked_order(session, order_id)
            if order.lifecycle == "COMPLETED":
                raise OrderConflict("completed orders cannot be deleted")
            if order.lifecycle == "PUBLISHED" and self._execution_guard.has_valid_shipments(
                order_id=order_id
            ):
                raise OrderConflict("order has valid shipments")
            factory_ids = self._factory_ids(session, order_id)
            prior_lifecycle = order.lifecycle
            order.deleted_at = now
            order.deleted_by = actor_id
            order.version += 1
            order.updated_at = now
            order.updated_by = actor_id
            self._add_idempotency(session, scope=scope, key=idempotency_key)
            if prior_lifecycle == "PUBLISHED":
                self._add_factory_events(
                    session,
                    order_id=order_id,
                    factory_ids=factory_ids,
                    event_type="order_deleted",
                    event_version=order.version,
                    now=now,
                )
            self._add_audit(
                session,
                request_id=request_id,
                action="order.deleted",
                order_id=order_id,
                actor_id=actor_id,
                changes={"lifecycle": prior_lifecycle},
            )

    def complete(
        self,
        *,
        actor_id: str,
        order_id: str,
        request_id: str,
        idempotency_key: str,
    ) -> OrderSnapshot:
        return self._set_completion(
            actor_id=actor_id,
            order_id=order_id,
            action="COMPLETE",
            reason=None,
            request_id=request_id,
            idempotency_key=idempotency_key,
        )

    def reopen(
        self,
        *,
        actor_id: str,
        order_id: str,
        reason: str,
        request_id: str,
        idempotency_key: str,
    ) -> OrderSnapshot:
        normalized_reason = reason.strip()
        if not normalized_reason:
            raise OrderValidationError("reopen reason is required")
        return self._set_completion(
            actor_id=actor_id,
            order_id=order_id,
            action="REOPEN",
            reason=normalized_reason,
            request_id=request_id,
            idempotency_key=idempotency_key,
        )

    def get(self, *, order_id: str, today: date | None = None) -> OrderSnapshot:
        with self._session_factory() as session:
            return self._snapshot(
                session, self._require_order(session, order_id), today or self._now().date()
            )

    def get_visible(
        self, *, actor_id: str, order_id: str, today: date | None = None
    ) -> OrderSnapshot:
        with self._session_factory() as session:
            user = self._require_enabled_user(session, actor_id)
            order = self._require_order(session, order_id)
            if user.role == "admin":
                return self._snapshot(session, order, today or self._now().date())
            if user.role != "factory" or user.factory_id is None:
                raise OrderPermissionDenied("order access is not available")
            visible = session.scalar(
                select(OrderAssignment.order_assignment_id)
                .join(OrderLine, OrderLine.order_line_id == OrderAssignment.order_line_id)
                .where(
                    OrderLine.order_id == order_id,
                    OrderAssignment.factory_id == user.factory_id,
                )
                .limit(1)
            )
            if visible is None or order.lifecycle == "DRAFT":
                raise OrderNotFound("order not found")
            return self._snapshot(
                session,
                order,
                today or self._now().date(),
                factory_id=user.factory_id,
            )

    def list_visible(
        self,
        *,
        actor_id: str,
        include_drafts: bool = False,
        keyword: str = "",
        status: str = "all",
        factory_id: str | None = None,
        trackers: list[str] | None = None,
        ship_date_from: date | None = None,
        ship_date_to: date | None = None,
        sort_by: str = "priority",
        page: int = 1,
        page_size: int = 20,
        today: date | None = None,
    ) -> tuple[list[OrderSnapshot], int]:
        if page < 1 or page_size < 1 or page_size > 100:
            raise OrderValidationError("invalid pagination")
        allowed_sorts = {
            "priority",
            "shipDateAsc",
            "shipDateDesc",
            "orderDateDesc",
            "updatedDesc",
        }
        if sort_by not in allowed_sorts:
            raise OrderValidationError("invalid sort option")
        business_today = today or self._now().date()
        with self._session_factory() as session:
            user = self._require_enabled_user(session, actor_id)
            query = select(Order).where(Order.deleted_at.is_(None))
            scoped_factory: str | None = None
            if user.role == "factory":
                if user.factory_id is None:
                    raise OrderPermissionDenied("factory is not bound")
                scoped_factory = user.factory_id
                query = (
                    query.join(OrderLine, OrderLine.order_id == Order.order_id)
                    .join(
                        OrderAssignment,
                        OrderAssignment.order_line_id == OrderLine.order_line_id,
                    )
                    .where(
                        OrderAssignment.factory_id == scoped_factory,
                        Order.lifecycle.in_(["PUBLISHED", "COMPLETED"]),
                    )
                    .distinct()
                )
            elif user.role == "admin":
                if not include_drafts:
                    query = query.where(Order.lifecycle != "DRAFT")
                if factory_id:
                    query = (
                        query.join(OrderLine, OrderLine.order_id == Order.order_id)
                        .join(
                            OrderAssignment,
                            OrderAssignment.order_line_id == OrderLine.order_line_id,
                        )
                        .where(OrderAssignment.factory_id == factory_id)
                        .distinct()
                    )
            else:
                raise OrderPermissionDenied("order access is not available")
            if keyword.strip():
                pattern = f"%{keyword.strip()}%"
                matching_lines = select(OrderLine.order_id).where(
                    or_(
                        OrderLine.product_name_snapshot.like(pattern),
                        OrderLine.properties_value_snapshot.like(pattern),
                    )
                )
                query = query.where(
                    or_(Order.order_no.like(pattern), Order.order_id.in_(matching_lines))
                )
            if trackers:
                query = query.where(Order.tracker.in_(trackers))
            if ship_date_from:
                query = query.where(Order.contract_ship_date >= ship_date_from)
            if ship_date_to:
                query = query.where(Order.contract_ship_date <= ship_date_to)
            if status == "草稿":
                query = query.where(Order.lifecycle == "DRAFT")
            elif status == "已完成":
                query = query.where(Order.lifecycle == "COMPLETED")
            elif status == "已逾期":
                query = query.where(
                    Order.lifecycle == "PUBLISHED",
                    Order.contract_ship_date < business_today,
                )
            elif status == "未完成":
                query = query.where(
                    Order.lifecycle == "PUBLISHED",
                    Order.contract_ship_date >= business_today,
                )
            elif status != "all":
                raise OrderValidationError("invalid status")
            orders = list(session.scalars(query))
            snapshots = [
                self._snapshot(session, item, business_today, factory_id=scoped_factory)
                for item in orders
            ]
            snapshots.sort(key=self._sort_key(sort_by, business_today))
            total = len(snapshots)
            start = (page - 1) * page_size
            return snapshots[start : start + page_size], total

    def list_audit_logs(
        self, *, actor_id: str, order_id: str
    ) -> list[OrderAuditSnapshot]:
        with self._session_factory() as session:
            self._require_admin(session, actor_id)
            self._require_order(session, order_id)
            entries = session.scalars(
                select(AuditLog)
                .where(
                    AuditLog.target_type == "order",
                    AuditLog.target_id == order_id,
                )
                .order_by(AuditLog.id.desc())
            )
            return [
                OrderAuditSnapshot(
                    action=item.action,
                    changes=item.changes,
                    actor_id=item.actor_id,
                    source_terminal=item.source_terminal,
                    created_at=item.created_at,
                )
                for item in entries
            ]

    def _set_completion(
        self,
        *,
        actor_id: str,
        order_id: str,
        action: str,
        reason: str | None,
        request_id: str,
        idempotency_key: str,
    ) -> OrderSnapshot:
        now = self._now()
        scope = f"order.{action.lower()}:{order_id}"
        with self._session_factory() as session, session.begin():
            self._require_admin(session, actor_id)
            if self._idempotency_exists(session, scope=scope, key=idempotency_key):
                return self._snapshot(session, self._require_order(session, order_id), now.date())
            order = self._locked_order(session, order_id)
            expected = "PUBLISHED" if action == "COMPLETE" else "COMPLETED"
            target = "COMPLETED" if action == "COMPLETE" else "PUBLISHED"
            if order.lifecycle != expected:
                raise OrderConflict("order lifecycle changed")
            if action == "COMPLETE" and self._execution_guard.has_pending_void_requests(
                order_id=order_id
            ):
                raise OrderConflict("order has pending shipment void requests")
            quantity = self._quantity_summary(session, order_id)
            order.lifecycle = target
            order.version += 1
            order.updated_at = now
            order.updated_by = actor_id
            if action == "COMPLETE":
                order.completed_at = now
                order.completed_by = actor_id
            else:
                order.completed_at = None
                order.completed_by = None
            session.add(
                OrderCompletionRecord(
                    order_id=order_id,
                    action=action,
                    reason=reason,
                    actor_id=actor_id,
                    source_terminal="web",
                    before_lifecycle=expected,
                    after_lifecycle=target,
                    quantity_snapshot=quantity,
                    created_at=now,
                )
            )
            self._add_idempotency(session, scope=scope, key=idempotency_key)
            self._add_audit(
                session,
                request_id=request_id,
                action=f"order.{action.lower()}",
                order_id=order_id,
                actor_id=actor_id,
                changes={"before": expected, "after": target, "reason": reason},
            )
            session.flush()
            return self._snapshot(session, order, now.date())

    def _replace_lines(
        self,
        session: Session,
        *,
        order: Order,
        lines: list[DraftLineInput],
        now: datetime,
    ) -> None:
        existing_line_ids = select(OrderLine.order_line_id).where(
            OrderLine.order_id == order.order_id
        )
        session.execute(
            delete(OrderAssignment).where(
                OrderAssignment.order_line_id.in_(existing_line_ids)
            )
        )
        session.execute(delete(OrderLine).where(OrderLine.order_id == order.order_id))
        merged: dict[str, DraftLineInput] = {}
        for item in lines:
            self._require_positive_integer(item.order_quantity, "order quantity")
            if item.variant_id in merged:
                previous = merged[item.variant_id]
                merged[item.variant_id] = DraftLineInput(
                    variant_id=item.variant_id,
                    order_quantity=previous.order_quantity + item.order_quantity,
                    assignments=previous.assignments + item.assignments,
                )
            else:
                merged[item.variant_id] = item
        for item in merged.values():
            variant = session.get(ProductVariant, item.variant_id)
            if variant is None or not variant.is_available:
                raise OrderValidationError("product variant is unavailable")
            product = session.get(Product, variant.product_id)
            if product is None or not product.is_available:
                raise OrderValidationError("product is unavailable")
            line = OrderLine(
                order_id=order.order_id,
                product_variant_id=variant.variant_id,
                order_quantity=item.order_quantity,
                sku_id_snapshot=variant.source_sku_id,
                product_name_snapshot=product.name,
                properties_value_snapshot=variant.properties_value,
                category_snapshot=variant.source_category,
                image_object_key_snapshot=product.image_object_key,
                created_at=now,
                updated_at=now,
            )
            session.add(line)
            session.flush()
            assignments: dict[str, int] = {}
            for assignment in item.assignments:
                self._require_positive_integer(assignment.quantity, "assignment quantity")
                assignments[assignment.factory_id] = (
                    assignments.get(assignment.factory_id, 0) + assignment.quantity
                )
            for factory_id, quantity in assignments.items():
                factory = session.get(Factory, factory_id)
                if factory is None:
                    raise OrderValidationError("factory does not exist")
                session.add(
                    OrderAssignment(
                        order_line_id=line.order_line_id,
                        factory_id=factory_id,
                        assigned_quantity=quantity,
                        factory_name_snapshot=factory.factory_name,
                        created_at=now,
                        updated_at=now,
                    )
                )

    def _validate_publish(self, session: Session, order: Order) -> set[str]:
        if not order.order_no.strip() or order.tracker not in TRACKERS:
            raise OrderValidationError("order header is incomplete")
        lines = list(
            session.scalars(select(OrderLine).where(OrderLine.order_id == order.order_id))
        )
        if not lines:
            raise OrderValidationError("order requires at least one line")
        factory_ids: set[str] = set()
        for line in lines:
            variant = session.get(ProductVariant, line.product_variant_id)
            if variant is None or not variant.is_available:
                raise OrderValidationError("product variant is unavailable")
            assignments = list(
                session.scalars(
                    select(OrderAssignment).where(
                        OrderAssignment.order_line_id == line.order_line_id
                    )
                )
            )
            assigned_total = sum(item.assigned_quantity for item in assignments)
            if not assignments or assigned_total != line.order_quantity:
                raise OrderValidationError("assignment total must equal order quantity")
            factory_ids.update(item.factory_id for item in assignments)
        for factory_id in factory_ids:
            factory = session.get(Factory, factory_id)
            enabled_user = session.scalar(
                select(User.user_id)
                .where(
                    User.role == "factory",
                    User.factory_id == factory_id,
                    User.is_enabled.is_(True),
                )
                .limit(1)
            )
            if factory is None or not factory.is_enabled or enabled_user is None:
                raise OrderValidationError("factory must be enabled and connected")
        return factory_ids

    def _snapshot(
        self,
        session: Session,
        order: Order,
        today: date,
        *,
        factory_id: str | None = None,
    ) -> OrderSnapshot:
        rows = list(
            session.scalars(
                select(OrderLine)
                .where(OrderLine.order_id == order.order_id)
                .order_by(OrderLine.order_line_id)
            )
        )
        line_snapshots: list[LineSnapshot] = []
        factory_totals: dict[str, tuple[str, int]] = {}
        validation_issues: list[str] = []
        for line in rows:
            assignments = list(
                session.scalars(
                    select(OrderAssignment)
                    .where(OrderAssignment.order_line_id == line.order_line_id)
                    .order_by(OrderAssignment.order_assignment_id)
                )
            )
            if factory_id is not None:
                assignments = [item for item in assignments if item.factory_id == factory_id]
                if not assignments:
                    continue
                visible_quantity = sum(item.assigned_quantity for item in assignments)
            else:
                visible_quantity = line.order_quantity
                assigned_total = sum(item.assigned_quantity for item in assignments)
                if assigned_total != line.order_quantity:
                    validation_issues.append(
                        f"产品 {line.product_name_snapshot} 的派工合计必须等于订单数量"
                    )
            assignment_snapshots = []
            for item in assignments:
                shipped = 0
                pending = item.assigned_quantity
                assignment_snapshots.append(
                    AssignmentSnapshot(
                        assignment_id=item.order_assignment_id,
                        factory_id=item.factory_id,
                        factory_name=item.factory_name_snapshot,
                        assigned_quantity=item.assigned_quantity,
                        shipped_quantity=shipped,
                        pending_quantity=pending,
                        over_quantity=0,
                        short_quantity=pending,
                        progress_percent=0,
                    )
                )
                current = factory_totals.get(item.factory_id)
                factory_totals[item.factory_id] = (
                    item.factory_name_snapshot,
                    item.assigned_quantity + (current[1] if current else 0),
                )
            line_snapshots.append(
                LineSnapshot(
                    order_line_id=line.order_line_id,
                    variant_id=line.product_variant_id,
                    sku_id=line.sku_id_snapshot,
                    product_name=line.product_name_snapshot,
                    properties_value=line.properties_value_snapshot,
                    category=line.category_snapshot,
                    image_object_key=line.image_object_key_snapshot,
                    order_quantity=visible_quantity,
                    shipped_quantity=0,
                    pending_quantity=visible_quantity,
                    over_quantity=0,
                    short_quantity=visible_quantity,
                    progress_percent=0,
                    assignments=assignment_snapshots,
                )
            )
        total = sum(item.order_quantity for item in line_snapshots)
        factory_progress = [
            FactoryProgressSnapshot(
                factory_id=key,
                factory_name=value[0],
                order_quantity=value[1],
                shipped_quantity=0,
                pending_quantity=value[1],
                over_quantity=0,
                short_quantity=value[1],
                progress_percent=0,
            )
            for key, value in sorted(factory_totals.items())
        ]
        return OrderSnapshot(
            order_id=order.order_id,
            order_no=order.order_no,
            source=order.source,
            order_date=order.order_date,
            tracker=order.tracker,
            contract_ship_date=order.contract_ship_date,
            lifecycle=order.lifecycle,
            display_status=self._display_status(order, today),
            version=order.version,
            total_quantity=total,
            shipped_quantity=0,
            pending_quantity=total,
            over_quantity=0,
            short_quantity=total,
            progress_percent=0,
            lines=line_snapshots,
            factory_progress=factory_progress,
            validation_issues=validation_issues,
            created_at=order.created_at,
            updated_at=order.updated_at,
        )

    def _quantity_summary(self, session: Session, order_id: str) -> dict[str, int]:
        total = int(
            session.scalar(
                select(func.coalesce(func.sum(OrderLine.order_quantity), 0)).where(
                    OrderLine.order_id == order_id
                )
            )
            or 0
        )
        return {
            "orderQuantity": total,
            "shippedQuantity": 0,
            "pendingQuantity": total,
            "overQuantity": 0,
            "shortQuantity": total,
        }

    def _factory_ids(self, session: Session, order_id: str) -> set[str]:
        return set(
            session.scalars(
                select(OrderAssignment.factory_id)
                .join(OrderLine, OrderLine.order_line_id == OrderAssignment.order_line_id)
                .where(OrderLine.order_id == order_id)
            )
        )

    @staticmethod
    def _sort_key(
        sort_by: str, today: date
    ) -> Callable[[OrderSnapshot], tuple[Any, ...]]:
        if sort_by == "shipDateAsc":
            return lambda item: (item.contract_ship_date, item.order_no)
        if sort_by == "shipDateDesc":
            return lambda item: (-item.contract_ship_date.toordinal(), item.order_no)
        if sort_by == "orderDateDesc":
            return lambda item: (-item.order_date.toordinal(), item.order_no)
        if sort_by == "updatedDesc":
            return lambda item: (-item.updated_at.timestamp(), item.order_no)
        return lambda item: (
            0
            if item.lifecycle == "PUBLISHED" and item.contract_ship_date < today
            else 1
            if item.lifecycle == "PUBLISHED"
            else 2
            if item.lifecycle == "COMPLETED"
            else 3,
            item.contract_ship_date,
            item.order_no,
        )

    @staticmethod
    def _display_status(order: Order, today: date) -> str:
        if order.lifecycle == "DRAFT":
            return "草稿"
        if order.lifecycle == "COMPLETED":
            return "已完成"
        return "已逾期" if today > order.contract_ship_date else "未完成"

    @staticmethod
    def _normalize_order_no(value: str) -> str:
        normalized = value.strip().upper()
        if not normalized:
            raise OrderValidationError("order number is required")
        return normalized

    @staticmethod
    def _validate_header(*, tracker: str, lines: list[DraftLineInput]) -> None:
        if tracker not in TRACKERS:
            raise OrderValidationError("tracker is invalid")
        if not lines:
            raise OrderValidationError("order requires at least one line")

    @staticmethod
    def _require_positive_integer(value: int, name: str) -> None:
        if type(value) is not int or value <= 0:
            raise OrderValidationError(f"{name} must be a positive integer")

    @staticmethod
    def _require_enabled_user(session: Session, actor_id: str) -> User:
        actor = session.get(User, actor_id)
        if actor is None or not actor.is_enabled:
            raise OrderPermissionDenied("enabled user required")
        return actor

    @classmethod
    def _require_admin(cls, session: Session, actor_id: str) -> User:
        actor = cls._require_enabled_user(session, actor_id)
        if actor.role != "admin":
            raise OrderPermissionDenied("administrator role required")
        return actor

    @staticmethod
    def _require_order(session: Session, order_id: str) -> Order:
        order = session.get(Order, order_id)
        if order is None or order.deleted_at is not None:
            raise OrderNotFound("order not found")
        return order

    @classmethod
    def _locked_order(cls, session: Session, order_id: str) -> Order:
        order = session.scalar(
            select(Order).where(Order.order_id == order_id).with_for_update()
        )
        if order is None or order.deleted_at is not None:
            raise OrderNotFound("order not found")
        return order

    @staticmethod
    def _idempotency_exists(session: Session, *, scope: str, key: str) -> bool:
        if not key.strip():
            raise OrderValidationError("idempotency key is required")
        return (
            session.scalar(
                select(IdempotencyRecord.id).where(
                    IdempotencyRecord.scope == scope,
                    IdempotencyRecord.idempotency_key == key,
                )
            )
            is not None
        )

    @staticmethod
    def _add_idempotency(session: Session, *, scope: str, key: str) -> None:
        session.add(
            IdempotencyRecord(scope=scope, idempotency_key=key, status="completed")
        )

    @staticmethod
    def _add_audit(
        session: Session,
        *,
        request_id: str,
        action: str,
        order_id: str,
        actor_id: str,
        changes: dict[str, object],
    ) -> None:
        session.add(
            AuditLog(
                request_id=request_id,
                action=action,
                target_type="order",
                target_id=order_id,
                changes=changes,
                actor_id=actor_id,
                source_terminal="web",
            )
        )

    @staticmethod
    def _add_factory_events(
        session: Session,
        *,
        order_id: str,
        factory_ids: set[str],
        event_type: str,
        event_version: int,
        now: datetime,
    ) -> None:
        for factory_id in sorted(factory_ids):
            session.add(
                OutboxMessage(
                    event_type=event_type,
                    aggregate_type="order",
                    aggregate_id=order_id,
                    dedupe_key=(
                        f"{event_type}:{order_id}:{event_version}:{factory_id}"
                    ),
                    payload={"orderId": order_id, "factoryId": factory_id},
                    available_at=now,
                )
            )

    def _now(self) -> datetime:
        value = self._clock()
        return value.astimezone(UTC).replace(tzinfo=None) if value.tzinfo else value
