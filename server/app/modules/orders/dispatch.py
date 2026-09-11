"""Detail-level dispatch: preview, validate, confirm for #90.

Reuses source_update._read() for pre-dispatch source checks.
Creates OrderLine/OrderAssignment per dispatched detail in one transaction.
"""

import json
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.adapters.errors import ExternalAdapterUnavailable
from app.adapters.order_source import FeishuOrderSource
from app.db.models import (
    Factory,
    IdempotencyRecord,
    Order,
    OrderAssignment,
    OrderChangePreview,
    OrderDetail,
    OrderLine,
    OutboxMessage,
    Product,
    ProductVariant,
    User,
)

from pydantic import TypeAdapter
from app.modules.order_import import OrderImportService
from app.modules.orders.service import (
    TRACKERS, OrderConflict, OrderService, OrderSnapshot, OrderValidationError,
)

_SNAPSHOT = TypeAdapter(OrderSnapshot)

FIELDS = {
    "source_sku_id": "产品编码",
    "product_name": "产品名称",
    "properties_value": "颜色/规格",
    "category": "分类",
    "factory_name": "工厂",
    "matched_variant_id": "产品匹配",
    "matched_factory_id": "工厂匹配",
    "order_quantity": "下单数量",
    "source_shipped_quantity": "已发数量",
    "source_tracker": "跟单人员",
    "contract_ship_date": "合同出货时间",
}


def _hash(value: object) -> str:
    return sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


def _check_source(session: Session, row: OrderDetail, fetched_row: Any) -> list[str]:
    """Return validation issues for a single detail row against its latest source."""
    variant, factory, parse_issues = OrderImportService.match_source_row(session, fetched_row)
    problems: list[str] = []
    if variant is None:
        problems.append("产品资料未匹配")
    if row.matched_factory_id is None:
        problems.append("工厂未匹配")
    elif factory is None or not factory.is_enabled:
        problems.append("工厂未启用或无有效资料")
    else:
        enabled_account = session.scalar(
            select(User.user_id)
            .where(
                User.role == "factory",
                User.factory_id == factory.factory_id,
                User.is_enabled.is_(True),
            )
            .limit(1)
        )
        if enabled_account is None:
            problems.append("工厂无审核通过且已启用账号")
    if row.contract_ship_date is None:
        problems.append("缺合同出货时间")
    quantity = OrderImportService._quantity(fetched_row.order_quantity, minimum=1)
    if quantity is None:
        problems.append("下单数量须为正整数")
    shipped = OrderImportService._quantity(fetched_row.shipped_quantity)
    if shipped is None:
        problems.append("初始已发数量须为非负整数")
    tracker = (fetched_row.tracker or "").strip()
    if not tracker:
        problems.append("跟单人员缺失")
    return problems


class OrderDispatchService(OrderService):
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        source: FeishuOrderSource,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        super().__init__(session_factory, clock=clock)
        self._source = source

    def _read(
        self, order_id: str, actor_id: str, version: int, detail_ids: list[str]
    ) -> tuple[dict[str, int], dict[str, Any]]:
        """Read latest source for given unassigned detail IDs; reuses source_update._read.

        Imported inline to avoid a direct dependency on OrderSourceUpdateService.
        """
        return OrderDispatchSourceRead(
            self._session_factory, self._source, self._require_admin
        ).read(order_id, actor_id, version, detail_ids)

    def preview(
        self,
        *,
        actor_id: str,
        order_id: str,
        version: int,
        detail_ids: list[str],
        request_id: str,
    ) -> dict[str, Any]:
        """Generate a dispatch preview with source check and validation.

        1. Read latest source for selected unassigned details.
        2. Compare against current accepted values.
        3. Validate each detail against dispatch rules.
        """
        if not detail_ids:
            raise OrderConflict("请至少选择一条未派工明细")
        if len(detail_ids) != len(set(detail_ids)):
            raise OrderConflict("明细选择不能重复")

        # Step 1: lock order, read current details, verify all are UNASSIGNED
        try:
            versions, fetched = self._read(order_id, actor_id, version, detail_ids)
        except OrderConflict:
            raise
        except ExternalAdapterUnavailable:
            raise OrderConflict("来源读取失败，暂不能派工，请稍后重试")

        with self._session_factory() as session, session.begin():
            self._require_admin(session, actor_id)
            order = self._locked_order(session, order_id)
            if not order.detail_mode:
                raise OrderConflict("当前订单不支持明细派工")
            if order.version != version:
                raise OrderConflict("订单版本已变化，请重新加载后重试")

            rows = list(
                session.scalars(
                    select(OrderDetail)
                    .where(OrderDetail.order_id == order_id)
                    .order_by(OrderDetail.sort_order, OrderDetail.detail_id)
                )
            )
            selected = {row.detail_id: row for row in rows if row.detail_id in detail_ids}
            if set(selected) != set(detail_ids):
                raise OrderConflict("所选明细已变化，请重新加载")

            for detail_id, row in selected.items():
                if row.dispatch_state != "UNASSIGNED":
                    raise OrderConflict("所选明细包含已派工行，请重新选择")
                if row.version != versions.get(detail_id):
                    raise OrderConflict("明细版本已变化，请重新加载")

            # Step 2: compare sources, collect differences
            source_differences: list[dict[str, Any]] = []
            for detail_id, row in selected.items():
                values = OrderDispatchSourceRead._source_values(session, fetched[detail_id], row)
                for key, label in FIELDS.items():
                    if key == "contract_ship_date" and row.date_override_enabled:
                        continue
                    before = getattr(row, key)
                    after = values[key]
                    if isinstance(before, date):
                        before = before.isoformat()
                    if before != after:
                        source_differences.append(
                            {
                                "detail_id": detail_id,
                                "label": f"第{row.sort_order}条 · {row.properties_value or '—'}",
                                "field": label,
                                "before": before,
                                "after": after,
                            }
                        )

            # Step 3: validate each selected detail
            validations: list[dict[str, Any]] = []
            all_ok = True
            for detail_id, row in sorted(
                selected.items(), key=lambda item: (item[1].sort_order, item[1].detail_id)
            ):
                problems = _check_source(session, row, fetched[detail_id])
                # Lock tracker: first dispatch sets order.tracker
                if order.tracker_locked_at is not None:
                    expected_tracker = order.tracker
                    fetched_tracker = (fetched[detail_id].tracker or "").strip()
                    if fetched_tracker and fetched_tracker != expected_tracker:
                        problems.append("跟单人员与已有执行快照不一致")
                validations.append(
                    {
                        "detail_id": detail_id,
                        "label": f"第{row.sort_order}条 · {row.properties_value or '—'}",
                        "factory_name": row.factory_name or "—",
                        "passes": len(problems) == 0,
                        "issues": problems,
                    }
                )
                if problems:
                    all_ok = False

            now = self._now()
            preview = OrderChangePreview(
                preview_id=str(uuid4()),
                order_id=order_id,
                actor_id=actor_id,
                version=version,
                created_at=now,
                expires_at=now + timedelta(minutes=5),
                payload={
                    "detail_ids": detail_ids,
                    "versions": versions,
                    "source_values": {
                        detail_id: OrderDispatchSourceRead._source_values(
                            session, fetched[detail_id], selected[detail_id]
                        )
                        for detail_id in detail_ids
                    },
                    "source_differences": source_differences,
                    "validations": validations,
                    "all_ok": all_ok,
                },
            )
            session.add(preview)
            return {
                "preview_id": preview.preview_id,
                "version": version,
                "expires_at": preview.expires_at,
                "source_differences": source_differences,
                "validations": validations,
                "all_ok": all_ok,
            }

    def confirm(
        self,
        *,
        actor_id: str,
        order_id: str,
        version: int,
        preview_id: str,
        idempotency_key: str,
        request_id: str,
    ) -> OrderSnapshot:
        """Commit the dispatch in one transaction.

        - Re-read source, re-validate.
        - Create/update OrderLine per SKU.
        - Create OrderAssignment per detail.
        - Link detail ← assignment.
        - First dispatch → PUBLISHED.
        - Write outbox events per factory.
        """
        if not idempotency_key.strip() or len(idempotency_key) > 191:
            raise OrderConflict("请提供有效的幂等标识")
        scope = f"order.dispatch:{actor_id}:{order_id}"
        request_hash = _hash([preview_id, version])

        with self._session_factory() as session:
            self._require_admin(session, actor_id)
            repeated = session.scalar(
                select(IdempotencyRecord).where(
                    IdempotencyRecord.scope == scope,
                    IdempotencyRecord.idempotency_key == idempotency_key,
                )
            )
            if repeated:
                if repeated.request_hash != request_hash:
                    raise OrderConflict("同一幂等标识不能用于不同派工")
                return _SNAPSHOT.validate_python(repeated.result)
            pending = session.get(OrderChangePreview, preview_id)
            if (
                pending is None
                or pending.order_id != order_id
                or pending.actor_id != actor_id
                or pending.version != version
                or pending.consumed_at is not None
                or pending.expires_at <= self._now()
            ):
                raise OrderConflict("派工预览已失效，请重新检查")
            detail_ids: list[str] = pending.payload["detail_ids"]

        # Re-read sources outside the write transaction
        try:
            _, fetched = self._read(order_id, actor_id, version, detail_ids)
        except (OrderConflict, ExternalAdapterUnavailable):
            with self._session_factory() as session:
                repeated = session.scalar(
                    select(IdempotencyRecord).where(
                        IdempotencyRecord.scope == scope,
                        IdempotencyRecord.idempotency_key == idempotency_key,
                    )
                )
                if repeated and repeated.request_hash == request_hash:
                    return _SNAPSHOT.validate_python(repeated.result)
            raise

        with self._session_factory() as session, session.begin():
            self._require_admin(session, actor_id)
            order = self._locked_order(session, order_id)

            # Idempotency check under lock
            repeated = session.scalar(
                select(IdempotencyRecord)
                .where(
                    IdempotencyRecord.scope == scope,
                    IdempotencyRecord.idempotency_key == idempotency_key,
                )
                .with_for_update()
            )
            if repeated:
                if repeated.request_hash != request_hash:
                    raise OrderConflict("同一幂等标识不能用于不同派工")
                return _SNAPSHOT.validate_python(repeated.result)

            if not order.detail_mode:
                raise OrderConflict("当前订单不支持明细派工")
            if order.version != version:
                raise OrderConflict("订单版本已变化，请重新加载")

            preview = session.get(OrderChangePreview, preview_id)
            if (
                preview is None
                or preview.order_id != order_id
                or preview.actor_id != actor_id
                or preview.version != version
                or preview.consumed_at is not None
                or preview.expires_at <= self._now()
            ):
                raise OrderConflict("派工预览已失效，请重新检查")

            rows = list(
                session.scalars(
                    select(OrderDetail)
                    .where(OrderDetail.order_id == order_id)
                    .order_by(OrderDetail.sort_order, OrderDetail.detail_id)
                )
            )
            selected = {row.detail_id: row for row in rows if row.detail_id in detail_ids}
            if set(selected) != set(detail_ids):
                raise OrderConflict("所选明细已变化")

            # Validate every row before writing anything
            errors: list[dict[str, Any]] = []
            for detail_id in detail_ids:
                row = selected[detail_id]
                if row.dispatch_state != "UNASSIGNED":
                    errors.append({"detail_id": detail_id, "reason": "已派工"})
                    continue
                if row.version != preview.payload["versions"].get(detail_id):
                    errors.append({"detail_id": detail_id, "reason": "版本已变化"})
                    continue
                # Re-validate with current source
                problems = _check_source(session, row, fetched[detail_id])
                if order.tracker_locked_at is not None:
                    fetched_tracker = (fetched[detail_id].tracker or "").strip()
                    if fetched_tracker and fetched_tracker != order.tracker:
                        problems.append("跟单人员与已有执行快照不一致")
                if problems:
                    errors.append(
                        {"detail_id": detail_id, "label": f"第{row.sort_order}条", "issues": problems}
                    )
            if errors:
                raise OrderValidationError(
                    "所选明细存在未通过项：\n"
                    + "\n".join(
                        f"{err.get('label', err['detail_id'])}：{'；'.join(err.get('issues', [err['reason']]))}"
                        for err in errors
                    )
                )

            now = self._now()
            dispatch_batch_id = str(uuid4())
            factory_ids: set[str] = set()
            created_assignment_ids: list[int] = []

            # Lock tracker on first dispatch
            tracker_locked = order.tracker_locked_at is not None
            if not tracker_locked:
                trackers = {row.source_tracker for row in selected.values()}
                tracker = next(iter(trackers)) if len(trackers) == 1 and trackers <= TRACKERS else None
                if tracker is None:
                    raise OrderConflict("来源跟单信息不一致或无效，不能首次派工")
                order.tracker = tracker
                order.tracker_locked_at = now

            # Cache product variants and factories
            variant_cache: dict[str, ProductVariant] = {}
            factory_cache: dict[str, Factory] = {}

            for detail_id in detail_ids:
                row = selected[detail_id]
                variant_id = row.matched_variant_id
                factory_id = row.matched_factory_id
                if variant_id is None or factory_id is None:
                    # Should have been caught by _check_source above
                    raise OrderValidationError(f"明细 {row.sort_order} 缺少匹配的产品或工厂")

                if variant_id not in variant_cache:
                    variant_cache[variant_id] = session.get(ProductVariant, variant_id)
                variant_or_none = variant_cache[variant_id]
                if variant_or_none is None or not variant_or_none.is_available:
                    raise OrderValidationError(f"产品 {row.source_sku_id or '—'} 不可用")
                variant = variant_or_none
                product: Product | None = session.get(Product, variant.product_id)

                if factory_id not in factory_cache:
                    factory_cache[factory_id] = session.get(Factory, factory_id)
                factory_or_none = factory_cache[factory_id]
                if factory_or_none is None:
                    raise OrderValidationError(f"工厂 {row.factory_name or '—'} 不存在")
                factory = factory_or_none

                quantity = row.order_quantity
                shipped = row.source_shipped_quantity
                if quantity is None or quantity <= 0:
                    raise OrderValidationError(f"明细 {row.sort_order} 下单数量无效")
                if shipped is None or shipped < 0:
                    raise OrderValidationError(f"明细 {row.sort_order} 初始已发数量无效")

                # Find or create OrderLine for this SKU
                existing_line = session.scalar(
                    select(OrderLine)
                    .where(
                        OrderLine.order_id == order_id,
                        OrderLine.product_variant_id == variant_id,
                    )
                    .with_for_update()
                    .limit(1)
                )
                if existing_line:
                    order_line = existing_line
                    order_line.order_quantity += quantity
                else:
                    order_line = OrderLine(
                        order_id=order_id,
                        product_variant_id=variant_id,
                        order_quantity=quantity,
                        sku_id_snapshot=variant.source_sku_id,
                        product_name_snapshot=product.name if product else (row.source_sku_id or ""),
                        properties_value_snapshot=row.properties_value or "",
                        category_snapshot=row.category,
                        image_object_key_snapshot=None,
                        created_at=now,
                        updated_at=now,
                    )
                    session.add(order_line)
                    session.flush()

                # Create assignment
                assignment = OrderAssignment(
                    order_line_id=order_line.order_line_id,
                    factory_id=factory_id,
                    detail_id=detail_id,
                    is_active=True,
                    contract_ship_date=row.contract_ship_date,
                    assigned_quantity=quantity,
                    initial_shipped_quantity=shipped,
                    factory_name_snapshot=row.factory_name or factory.factory_name,
                    created_at=now,
                    updated_at=now,
                )
                session.add(assignment)
                session.flush()

                # Link detail → assignment
                row.assignment_id = assignment.order_assignment_id
                row.dispatch_batch_id = dispatch_batch_id
                row.dispatch_state = "ASSIGNED"
                row.version += 1
                row.updated_at = now

                factory_ids.add(factory_id)
                created_assignment_ids.append(assignment.order_assignment_id)

            # Transition lifecycle on first dispatch
            before_lifecycle = order.lifecycle
            if order.lifecycle == "DRAFT":
                order.lifecycle = "PUBLISHED"
                order.published_at = now
                order.published_by = actor_id

            order.version += 1
            order.updated_at = now
            order.updated_by = actor_id
            # 2026-09-15 guaranteed: upload artifact on session disk
            preview.consumed_at = now

            # Write audit
            self._add_audit(
                session,
                request_id=request_id,
                action="order.detail_dispatched",
                order_id=order_id,
                actor_id=actor_id,
                changes={
                    "batchId": dispatch_batch_id,
                    "detailIds": detail_ids,
                    "factoryIds": sorted(factory_ids),
                    "assignmentIds": created_assignment_ids,
                    "lifecycleBefore": before_lifecycle,
                    "lifecycleAfter": order.lifecycle,
                },
            )

            # Write outbox for each factory (inline, avoiding signature conflict with parent)
            for factory_id in sorted(factory_ids):
                session.add(
                    OutboxMessage(
                        event_type="order_detail_dispatched",
                        aggregate_type="order",
                        aggregate_id=order_id,
                        dedupe_key=f"order_detail_dispatched:{order_id}:{order.version}:{factory_id}",
                        payload={"orderId": order_id, "factoryId": factory_id,
                                 "batchId": dispatch_batch_id},
                        available_at=now,
                    )
                )

            # Re-read all details for snapshot
            all_rows = list(
                session.scalars(
                    select(OrderDetail)
                    .where(OrderDetail.order_id == order_id)
                    .order_by(OrderDetail.sort_order, OrderDetail.detail_id)
                )
            )

            result = self._dispatch_snapshot(session, order, all_rows)
            session.add(
                IdempotencyRecord(
                    scope=scope,
                    idempotency_key=idempotency_key,
                    status="completed",
                    request_hash=request_hash,
                    result=json.loads(
_SNAPSHOT.dump_json(result)
                    ),
                )
            )
            return result

    def _dispatch_snapshot(
        self, session: Session, order: Order, rows: list[OrderDetail]
    ) -> OrderSnapshot:
        """Full snapshot mixing assigned (execution) and unassigned (source) details."""
        from app.modules.orders.service import DetailSnapshot, LineSnapshot, AssignmentSnapshot, FactoryProgressSnapshot

        details: list[DetailSnapshot] = []
        for row in sorted(rows, key=lambda detail: (detail.sort_order, detail.detail_id)):
            if row.dispatch_state == "ASSIGNED" and row.assignment_id:
                assignment = session.get(OrderAssignment, row.assignment_id)
                if assignment is not None:
                    system_shipped = OrderService._assignment_shipped(session, assignment)
                    shipped = assignment.initial_shipped_quantity + system_shipped
                    pending = max(assignment.assigned_quantity - shipped, 0)
                    progress = (
                        round(shipped * 100 / assignment.assigned_quantity)
                        if assignment.assigned_quantity
                        else None
                    )
                    details.append(
                        DetailSnapshot(
                            detail_id=row.detail_id,
                            origin=row.origin,
                            source_sku_id=row.source_sku_id,
                            product_name=row.product_name,
                            properties_value=row.properties_value,
                            category=row.category,
                            factory_name=row.factory_name,
                            matched_variant_id=row.matched_variant_id,
                            matched_factory_id=row.matched_factory_id,
                            order_quantity=assignment.assigned_quantity,
                            shipped_quantity=shipped,
                            pending_quantity=pending,
                            progress_percent=progress,
                            source_tracker=row.source_tracker,
                            contract_ship_date=row.contract_ship_date,
                            dispatch_state=row.dispatch_state,
                            version=row.version,
                            raw_fields=row.accepted_raw_fields,
                        )
                    )
                    continue
            # Unassigned detail
            uq = row.order_quantity
            us = row.source_shipped_quantity
            valid = uq is not None and uq > 0 and us is not None and us >= 0
            u_pending: int | None = (
                max(uq - us, 0) if valid and uq is not None and us is not None else None
            )
            u_progress: int | None = (
                round(us * 100 / uq)
                if valid and uq is not None and uq and us is not None
                else None
            )
            details.append(
                DetailSnapshot(
                    detail_id=row.detail_id,
                    origin=row.origin,
                    source_sku_id=row.source_sku_id,
                    product_name=row.product_name,
                    properties_value=row.properties_value,
                    category=row.category,
                    factory_name=row.factory_name,
                    matched_variant_id=row.matched_variant_id,
                    matched_factory_id=row.matched_factory_id,
                    order_quantity=uq,
                    shipped_quantity=us,
                    pending_quantity=u_pending,
                    progress_percent=u_progress,
                    source_tracker=row.source_tracker,
                    contract_ship_date=row.contract_ship_date,
                    dispatch_state=row.dispatch_state,
                    version=row.version,
                    raw_fields=row.accepted_raw_fields,
                )
            )

        def total(values: list[int | None]) -> int | None:
            return (
                None
                if any(value is None for value in values)
                else sum(value for value in values if value is not None)
            )

        quantity = total([item.order_quantity for item in details])
        shipped = total([item.shipped_quantity for item in details])
        pending = total([item.pending_quantity for item in details])
        dates = sorted({item.contract_ship_date for item in details if item.contract_ship_date})

        # Compute line/assignment/factory snapshots in the same style as _snapshot
        from app.db.models import QuantityLedger
        from sqlalchemy import func as _fn

        line_rows = list(
            session.scalars(
                select(OrderLine)
                .where(OrderLine.order_id == order.order_id)
                .order_by(OrderLine.order_line_id)
            )
        )
        assignment_rows = list(
            session.scalars(
                select(OrderAssignment)
                .join(OrderLine, OrderLine.order_line_id == OrderAssignment.order_line_id)
                .where(OrderLine.order_id == order.order_id, OrderAssignment.is_active.is_(True))
                .order_by(OrderAssignment.order_assignment_id)
            )
        )
        ledger_totals: dict[int, int] = {}
        if assignment_rows:
            for aid, qty in session.execute(
                select(QuantityLedger.order_assignment_id, _fn.sum(QuantityLedger.quantity_delta))
                .where(
                    QuantityLedger.order_assignment_id.in_(
                        [a.order_assignment_id for a in assignment_rows]
                    )
                )
                .group_by(QuantityLedger.order_assignment_id)
            ):
                ledger_totals[aid] = int(qty)

        line_snapshots: list[LineSnapshot] = []
        factory_totals: dict[str, tuple[str, int, int]] = {}
        for line in line_rows:
            line_assignments = [a for a in assignment_rows if a.order_line_id == line.order_line_id]
            assignment_snapshots: list[AssignmentSnapshot] = []
            for a in line_assignments:
                system_qty = ledger_totals.get(a.order_assignment_id, 0)
                shipped_qty = a.initial_shipped_quantity + system_qty
                pending_qty = max(a.assigned_quantity - shipped_qty, 0)
                over_qty = max(shipped_qty - a.assigned_quantity, 0)
                short_qty = max(a.assigned_quantity - shipped_qty, 0)
                progress = round(shipped_qty * 100 / a.assigned_quantity) if a.assigned_quantity else 0
                assignment_snapshots.append(
                    AssignmentSnapshot(
                        assignment_id=a.order_assignment_id,
                        contract_ship_date=a.contract_ship_date,
                        factory_id=a.factory_id,
                        factory_name=a.factory_name_snapshot,
                        assigned_quantity=a.assigned_quantity,
                        shipped_quantity=shipped_qty,
                        pending_quantity=pending_qty,
                        over_quantity=over_qty,
                        short_quantity=short_qty,
                        progress_percent=progress,
                    )
                )
                if a.factory_id not in factory_totals:
                    factory_totals[a.factory_id] = (a.factory_name_snapshot, 0, 0)
                name, q, s = factory_totals[a.factory_id]
                factory_totals[a.factory_id] = (name, q + a.assigned_quantity, s + shipped_qty)

            line_shipped = sum(a.shipped_quantity for a in assignment_snapshots)
            line_pending = sum(a.pending_quantity for a in assignment_snapshots)
            line_over = sum(a.over_quantity for a in assignment_snapshots)
            line_progress = (
                round(line_shipped * 100 / line.order_quantity)
                if line.order_quantity
                else 0
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
                    order_quantity=line.order_quantity,
                    shipped_quantity=line_shipped,
                    pending_quantity=line_pending,
                    over_quantity=line_over,
                    short_quantity=line_pending,
                    progress_percent=line_progress,
                    assignments=assignment_snapshots,
                )
            )

        factory_progress = [
            FactoryProgressSnapshot(
                factory_id=fid,
                factory_name=name,
                order_quantity=q,
                shipped_quantity=s,
                pending_quantity=max(q - s, 0),
                over_quantity=max(s - q, 0),
                short_quantity=max(q - s, 0),
                progress_percent=round(s * 100 / q) if q else 0,
            )
            for fid, (name, q, s) in factory_totals.items()
        ]

        return OrderSnapshot(
            order_id=order.order_id,
            order_no=order.order_no,
            source=order.source,
            order_date=order.order_date,
            tracker=order.tracker,
            contract_ship_date=dates[0] if dates else None,
            contract_ship_dates=dates,
            lifecycle=order.lifecycle,
            display_status=OrderService._display_status(order, order.lifecycle == "PUBLISHED"),
            version=order.version,
            total_quantity=quantity,
            shipped_quantity=shipped,
            pending_quantity=pending,
            over_quantity=None,
            short_quantity=pending,
            progress_percent=(
                round(shipped * 100 / quantity)
                if quantity and shipped is not None
                else None
            ),
            detail_mode=True,
            details=details,
            lines=line_snapshots,
            factory_progress=factory_progress,
            validation_issues=[],
            created_at=order.created_at,
            updated_at=order.updated_at,
        )




class OrderDispatchSourceRead:
    """Stateless source reader, separated so OrderDispatchService can call it
    without inheriting from OrderSourceUpdateService."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        source: FeishuOrderSource,
        require_admin: Callable,
    ) -> None:
        self._session_factory = session_factory
        self._source = source
        self._require_admin = require_admin

    def read(
        self, order_id: str, actor_id: str, version: int, detail_ids: list[str]
    ) -> tuple[dict[str, int], dict[str, Any]]:
        """Read latest source for given unassigned detail IDs."""
        from app.db.models import OrderImportSourceRecord

        with self._session_factory() as session:
            self._require_admin(session, actor_id)
            # Non-locking check
            rows = list(
                session.scalars(
                    select(OrderDetail)
                    .where(OrderDetail.order_id == order_id)
                    .order_by(OrderDetail.sort_order, OrderDetail.detail_id)
                )
            )
            selected = [
                row
                for row in rows
                if row.dispatch_state == "UNASSIGNED" and row.detail_id in detail_ids
            ]
            if {r.detail_id for r in selected} != set(detail_ids):
                raise OrderConflict("所选明细不可用")
            identities: dict[str, tuple[str, str]] = {}
            versions: dict[str, int] = {}
            for row in selected:
                source = (
                    session.get(OrderImportSourceRecord, row.source_record_pk)
                    if row.source_record_pk
                    else None
                )
                if source is None or source.source_scope != self._source.source_scope:
                    raise OrderConflict("明细没有可靠的来源关联，不能派工")
                identities[source.source_record_id] = (row.detail_id, source.source_detail_id)
                versions[row.detail_id] = row.version
            order_obj = session.get(Order, order_id)
            order_no = order_obj.order_no if order_obj else ""

        fetched = self._source.read_records(list(identities))
        if len(fetched) != len(identities) or {r.record_id for r in fetched} != set(identities):
            raise OrderConflict("来源明细缺失或重复，不能派工")
        result: dict[str, Any] = {}
        for fetched_row in fetched:
            detail_id, source_detail_id = identities[fetched_row.record_id]
            if (fetched_row.order_no or "").strip().upper() != order_no or fetched_row.source_detail_id != source_detail_id:
                raise OrderConflict("来源订单号或明细身份变化，不能派工")
            result[detail_id] = fetched_row
        return versions, result

    @staticmethod
    def _source_values(session: Session, row: Any, detail: OrderDetail) -> dict[str, Any]:
        """Compute latest source values from a fetched row and detail."""
        from datetime import date as _date_type, timedelta as _td

        variant, factory, issues = OrderImportService.match_source_row(session, row)
        source_date = row.contract_ship_date
        effective_date = (
            detail.contract_ship_date
            if detail.date_override_enabled
            else (
                source_date - _td(days=4)
                if source_date and source_date >= _date_type(1, 1, 5)
                else None
            )
        )
        return {
            "source_sku_id": row.source_sku_id,
            "product_name": row.product_name,
            "properties_value": row.properties_value,
            "category": row.category,
            "factory_name": row.factory_name,
            "matched_variant_id": variant.variant_id if variant else None,
            "matched_factory_id": factory.factory_id if factory else None,
            "order_quantity": OrderImportService._quantity(row.order_quantity, minimum=1),
            "source_shipped_quantity": OrderImportService._quantity(row.shipped_quantity),
            "source_tracker": row.tracker,
            "contract_ship_date": effective_date.isoformat() if effective_date else None,
            "accepted_raw_fields": row.raw_fields,
            "accepted_source_hash": _hash(row.raw_fields),
            "accepted_source_modified_at": row.source_modified_at.isoformat()
            if row.source_modified_at
            else None,
        }