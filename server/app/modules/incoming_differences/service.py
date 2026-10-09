"""Incoming-difference registration service: candidate matching, whole-batch confirm, query."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import (
    AuditLog,
    Factory,
    IdempotencyRecord,
    IncomingDiffAdjustment,
    IncomingDiffBatch,
    IncomingDiffImage,
    IncomingDiffImportFile,
    IncomingDiffRecord,
    IncomingDiffWorkbook,
    Order,
    OrderAssignment,
    OrderDetail,
    OutboxMessage,
    Product,
    ProductVariant,
    QuantityLedger,
    User,
)
from app.modules.incoming_differences.duplicates import duplicate_evidence
from app.modules.orders.quantities import active_assignment, detail_shipped, pending_totals

BUSINESS_TIME_ZONE = ZoneInfo("Asia/Shanghai")
CONFIRM_SCOPE = "incoming_diff_confirm"
LEDGER_SOURCE_TYPE = "INCOMING_DIFF"
REGISTERED_EVENT_TYPE = "incoming_diff.registered"
ADJUSTED_EVENT_TYPE = "incoming_diff.adjusted"


class IncomingDifferenceError(Exception):
    """Base error for incoming-difference registration."""


class IncomingDifferenceNotFound(IncomingDifferenceError):
    """Batch, workbook or order does not exist."""


class IncomingDifferencePermissionDenied(IncomingDifferenceError):
    """Actor may not perform the operation."""


class IncomingDifferenceConflict(IncomingDifferenceError):
    """Batch state or workbook version does not allow confirmation."""


class IncomingDifferenceValidationError(IncomingDifferenceError):
    """At least one workbook line cannot be registered; the whole batch is rejected."""

    def __init__(self, message: str, issues: list[dict[str, Any]]) -> None:
        super().__init__(message)
        self.issues = issues


@dataclass(frozen=True)
class BatchView:
    batch_id: str
    batch_no: str
    status: str


@dataclass(frozen=True)
class ConfirmResult:
    batch_id: str
    batch_no: str
    record_count: int
    factory_count: int
    confirmed_at: datetime
    confirmed_by: str
    replayed: bool


@dataclass(frozen=True)
class IncomingDifferenceView:
    sequence: int
    registered_at: datetime
    product_name: str
    spec: str
    quantity: int
    record_id: str | None
    purchase_order_id: str | None
    product_code: str | None
    version: int | None


@dataclass(frozen=True)
class _ParsedLine:
    detail_id: str
    quantity: int
    purchase_order_id: str
    purchase_order_item_id: str
    image_id: str | None


@dataclass(frozen=True)
class _AssignmentContext:
    order_id: str
    order_no: str
    detail_id: str
    factory_id: str
    variant_id: str
    product_code: str
    product_name: str
    spec: str


class IncomingDifferenceService:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        id_factory: Callable[[], str] = lambda: str(uuid4()),
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock
        self._id_factory = id_factory

    def create_batch(
        self,
        *,
        submitter_id: str,
        feishu_chat_id: str | None = None,
        feishu_open_id: str | None = None,
    ) -> BatchView:
        current, business_date = self._now()
        prefix = f"IN{business_date:%Y%m%d}-"
        with self._session_factory() as session, session.begin():
            used = session.scalars(
                select(IncomingDiffBatch.batch_no).where(
                    IncomingDiffBatch.batch_no.like(f"{prefix}%")
                )
            ).all()
            # ponytail: 同秒并发建批次靠 uq_incoming_diff_batches_no 兜底重试，
            # 需要更强保证再上序号表
            sequence = (
                max(
                    (
                        int(batch_no.removeprefix(prefix))
                        for batch_no in used
                        if batch_no.removeprefix(prefix).isdigit()
                    ),
                    default=0,
                )
                + 1
            )
            batch = IncomingDiffBatch(
                batch_id=self._id_factory(),
                batch_no=f"{prefix}{sequence:02d}",
                submitter_id=submitter_id,
                feishu_chat_id=feishu_chat_id,
                feishu_open_id=feishu_open_id,
                status="COLLECTING",
                created_at=current,
                updated_at=current,
            )
            session.add(batch)
            session.flush()
            return BatchView(
                batch_id=batch.batch_id, batch_no=batch.batch_no, status=batch.status
            )

    def match_detail(
        self,
        *,
        factory_id: str | None = None,
        product_code: str | None = None,
        product_name: str | None = None,
        spec: str | None = None,
        variant_id: str | None = None,
        purchase_order_id: str | None = None,
        purchase_order_item_id: str | None = None,
    ) -> str | None:
        """唯一明细忽略未发数量，多明细沿用合同出货时间规则。"""
        if not factory_id or not (product_code or product_name) or not (spec or variant_id):
            return None
        sku = (
            select(ProductVariant.variant_id)
            .join(Product, Product.product_id == ProductVariant.product_id)
        )
        if product_code:
            sku = sku.where(Product.source_i_id == product_code)
        if product_name:
            sku = sku.where(Product.name == product_name)
        if spec:
            sku = sku.where(ProductVariant.properties_value == spec)
        if variant_id:
            sku = sku.where(ProductVariant.variant_id == variant_id)
        with self._session_factory() as session:
            variants = session.scalars(sku.limit(2)).all()
            if len(variants) != 1:
                return None
            statement = (
                select(OrderDetail)
                .join(Order, Order.order_id == OrderDetail.order_id)
                .where(
                    OrderDetail.matched_factory_id == factory_id,
                    OrderDetail.matched_variant_id == variants[0],
                    OrderDetail.purchase_order_id.is_not(None),
                    OrderDetail.purchase_order_id != "",
                    OrderDetail.purchase_order_item_id.is_not(None),
                    OrderDetail.purchase_order_item_id != "",
                    Order.deleted_at.is_(None),
                )
            )
            if purchase_order_id:
                statement = statement.where(OrderDetail.purchase_order_id == purchase_order_id)
            if purchase_order_item_id:
                statement = statement.where(
                    OrderDetail.purchase_order_item_id == purchase_order_item_id
                )
            candidates = session.scalars(statement.order_by(
                OrderDetail.contract_ship_date.is_(None),
                OrderDetail.contract_ship_date,
                OrderDetail.detail_id,
            )).all()
            if not candidates:
                return None
            if len(candidates) == 1:
                return candidates[0].detail_id
            ledger_rows = session.execute(
                select(QuantityLedger.order_assignment_id, func.sum(QuantityLedger.quantity_delta))
                .where(QuantityLedger.order_assignment_id.in_(
                    detail.assignment_id for detail in candidates if detail.assignment_id
                ))
                .group_by(QuantityLedger.order_assignment_id)
            ).all()
            totals = {row[0]: int(row[1]) for row in ledger_rows}
            pending = pending_totals(session, [detail.detail_id for detail in candidates])
            remaining = []
            for detail in candidates:
                quantity: int | None
                shipped: int | None
                assignment = session.get(OrderAssignment, detail.assignment_id) \
                    if detail.assignment_id else None
                if assignment and assignment.is_active and detail.dispatch_state == "ASSIGNED":
                    ship_date = assignment.contract_ship_date
                    quantity = assignment.assigned_quantity
                    shipped = assignment.initial_shipped_quantity + totals.get(
                        assignment.order_assignment_id, 0
                    )
                else:
                    ship_date = detail.contract_ship_date
                    quantity = detail.order_quantity
                    shipped = detail.source_shipped_quantity
                    if shipped is not None:
                        shipped += pending.get(detail.detail_id, 0)
                if quantity is not None and shipped is not None and quantity > shipped:
                    remaining.append((detail, ship_date))
            if not remaining:
                return None
            remaining.sort(key=lambda item: (item[1] is None, item[1] or date.max))
            if (len(remaining) > 1
                    and remaining[0][1] == remaining[1][1]):
                return None
            return remaining[0][0].detail_id

    def match_assignment(self, **criteria: Any) -> int | None:
        detail_id = self.match_detail(**criteria)
        with self._session_factory() as session:
            detail = session.get(OrderDetail, detail_id) if detail_id else None
            return detail.assignment_id if detail else None

    def confirm(self, *, batch_id: str, workbook_version: int, actor_id: str,
                review_revision: int | None = None) -> ConfirmResult:
        current, _business_date = self._now()
        idempotency_key = f"{batch_id}:{workbook_version}"
        with self._session_factory() as session, session.begin():
            actor = session.get(User, actor_id, with_for_update=True)
            if actor is None or not actor.is_enabled or actor.role != "admin":
                raise IncomingDifferencePermissionDenied("只有已启用的管理员可以确认来货出入")
            owned = session.get(IncomingDiffBatch, batch_id, with_for_update=True)
            if owned is None or owned.submitter_id != actor_id:
                raise IncomingDifferencePermissionDenied("只能确认自己提交的批次")
            if owned.source_kind == "FILE" or owned.review_revision:
                idempotency_key += f":{review_revision}"
            replay = session.scalar(
                select(IdempotencyRecord).where(
                    IdempotencyRecord.scope == CONFIRM_SCOPE,
                    IdempotencyRecord.idempotency_key == idempotency_key,
                ).with_for_update()
            )
            if replay is not None and replay.result:
                return _replayed_result(replay.result)

            batch = session.scalars(
                select(IncomingDiffBatch)
                .where(IncomingDiffBatch.batch_id == batch_id)
                .with_for_update()
            ).one_or_none()
            if batch is None:
                raise IncomingDifferenceNotFound("批次不存在")
            actor = session.get(User, actor_id)
            if actor is None or not actor.is_enabled or actor.role != "admin":
                raise IncomingDifferencePermissionDenied("只有已启用的管理员可以确认来货出入")
            if batch.submitter_id != actor_id:
                raise IncomingDifferencePermissionDenied("只能确认自己提交的批次")
            if ((batch.source_kind == "FILE" or batch.review_revision)
                    and batch.review_revision != review_revision):
                raise IncomingDifferenceConflict("导入汇总已过期，请使用最新确认")
            if batch.status != "READY":
                raise IncomingDifferenceConflict("批次当前状态不允许确认")
            workbook = session.scalars(
                select(IncomingDiffWorkbook).where(
                    IncomingDiffWorkbook.batch_id == batch_id,
                    IncomingDiffWorkbook.version == workbook_version,
                )
            ).one_or_none()
            if workbook is None:
                raise IncomingDifferenceNotFound("核对表版本不存在")
            if batch.current_workbook_id != workbook.workbook_id:
                raise IncomingDifferenceConflict("核对表版本已过期，请使用最新版本")

            image_ids = set(
                session.scalars(
                    select(IncomingDiffImage.image_id).where(
                        IncomingDiffImage.batch_id == batch_id
                    )
                ).all()
            )
            issues: list[dict[str, Any]] = []
            parsed: list[tuple[dict[str, Any], _ParsedLine]] = []
            for raw in workbook.line_snapshot or []:
                if raw.get("decision") == "skip":
                    continue
                reason = _line_reason(raw, image_ids, imported=batch.source_kind == "FILE")
                if batch.source_kind == "FILE":
                    source_file = session.get(IncomingDiffImportFile, raw.get("importFileId"))
                    if source_file is None or source_file.workbook_id != workbook.workbook_id:
                        reason = "文件行来源无效"
                if reason is not None:
                    issues.append(_issue(raw, reason))
                    continue
                detail_id = raw.get("detailId")
                if not detail_id and raw.get("orderAssignmentId"):
                    old_assignment = session.get(OrderAssignment, int(raw["orderAssignmentId"]))
                    detail_id = old_assignment.detail_id if old_assignment else None
                if not detail_id:
                    issues.append(_issue(raw, "未匹配到唯一订单明细"))
                    continue
                parsed.append(
                    (
                        raw,
                        _ParsedLine(
                            detail_id=str(detail_id),
                            quantity=int(raw["quantity"]),
                            purchase_order_id=str(raw["purchaseOrderId"]),
                            purchase_order_item_id=str(raw["purchaseOrderItemId"]),
                            image_id=str(raw["imageId"]) if raw.get("imageId") else None,
                        ),
                    )
                )
            if not issues and not parsed and not workbook.line_snapshot:
                raise IncomingDifferenceValidationError("核对表没有可登记的数据行", [])

            detail_ids = sorted({line.detail_id for _raw, line in parsed})
            order_ids = session.scalars(select(OrderDetail.order_id).where(
                OrderDetail.detail_id.in_(detail_ids)
            )).all()
            orders = {order.order_id: order for order in session.scalars(
                select(Order).where(Order.order_id.in_(order_ids))
                .order_by(Order.order_id).with_for_update()
            )}
            details = {detail.detail_id: detail for detail in session.scalars(
                select(OrderDetail).where(OrderDetail.detail_id.in_(detail_ids))
                .order_by(OrderDetail.detail_id).with_for_update()
            )}
            assignments = {
                detail_id: active_assignment(session, detail)
                for detail_id, detail in details.items()
            }
            contexts = _detail_contexts(session, detail_ids)
            for raw, line in parsed:
                detail = details.get(line.detail_id)
                if (detail is None or line.detail_id not in contexts
                        or orders[detail.order_id].deleted_at is not None):
                    issues.append(_issue(raw, "订单明细不存在或归属无效"))
                elif (detail.purchase_order_id != line.purchase_order_id
                      or detail.purchase_order_item_id != line.purchase_order_item_id
                      or (raw.get("variantId") and raw["variantId"] != detail.matched_variant_id)
                      or (raw.get("factoryId") and raw["factoryId"] != detail.matched_factory_id)):
                    issues.append(_issue(raw, "采购、工厂或 SKU 归属已变化"))
                elif batch.source_kind == "FILE":
                    context = contexts[line.detail_id]
                    factory = session.get(Factory, context.factory_id, with_for_update=True)
                    if (factory is None or not factory.is_enabled
                            or factory.factory_name != raw.get("factoryName")
                            or context.product_name != raw.get("productName")
                            or context.spec != raw.get("spec")):
                        issues.append(_issue(raw, "工厂、名称或规格已变化，请重新上传核对"))

            # 统一已发下限没有数据库约束，锁行之后重算再判断
            if issues:
                raise IncomingDifferenceValidationError(_issue_message(issues), issues)
            if batch.source_kind == "FILE" or batch.review_revision:
                evidence = duplicate_evidence(session, workbook.line_snapshot)
                if any(evidence.get(raw["number"], []) != raw.get("duplicates", [])
                       for raw, _line in parsed):
                    raise IncomingDifferenceConflict("出现新的疑似重复，请重新核对导入")
                if any(raw.get("duplicates") and raw.get("decision") != "register_new"
                       for raw, _line in parsed):
                    raise IncomingDifferenceConflict("疑似重复尚未处理完成")
            before: dict[str, int] = {}
            for detail_id, detail in details.items():
                shipped = detail_shipped(session, detail)
                if shipped is None:
                    raise IncomingDifferenceValidationError("明细已发数量未知，不能登记", [])
                before[detail_id] = shipped
            after = dict(before)
            for _raw, line in parsed:
                after[line.detail_id] += line.quantity
            for raw, line in parsed:
                resulting = after[line.detail_id]
                if resulting < 0:
                    issues.append(
                        _issue(raw, f"登记后统一已发数量为 {resulting}，不能小于 0")
                    )
            if issues:
                raise IncomingDifferenceValidationError(_issue_message(issues), issues)

            for detail in details.values():
                detail.version += 1
                detail.updated_at = current
            for order in orders.values():
                order.version += 1
                order.updated_at = current
            records: list[IncomingDiffRecord] = []
            for _raw, line in parsed:
                context = contexts[line.detail_id]
                assignment = assignments[line.detail_id]
                assignment_id = assignment.order_assignment_id if assignment else None
                record_id = self._id_factory()
                records.append(
                    IncomingDiffRecord(
                        record_id=record_id,
                        batch_id=batch_id,
                        workbook_id=workbook.workbook_id,
                        image_id=line.image_id,
                        import_file_id=_raw.get("importFileId"),
                        source_sheet_name=(
                            _raw.get("sheetName") if _raw.get("importFileId") else None),
                        source_row_number=(
                            _raw.get("rowNumber") if _raw.get("importFileId") else None),
                        order_id=context.order_id,
                        detail_id=context.detail_id,
                        order_assignment_id=assignment_id,
                        variant_id=context.variant_id,
                        purchase_order_id=line.purchase_order_id,
                        purchase_order_item_id=line.purchase_order_item_id,
                        quantity=line.quantity,
                        initial_quantity=line.quantity,
                        source_business_date=None,
                        product_code_snapshot=context.product_code,
                        product_name_snapshot=context.product_name,
                        spec_snapshot=context.spec,
                        registered_at=current,
                        registered_by=actor_id,
                        version=1,
                        created_at=current,
                        updated_at=current,
                    )
                )
                session.add(records[-1])
                session.add(
                    QuantityLedger(
                        order_assignment_id=assignment_id,
                        order_detail_id=line.detail_id if assignment_id is None else None,
                        source_type=LEDGER_SOURCE_TYPE,
                        source_id=record_id,
                        quantity_delta=line.quantity,
                        actor_id=actor_id,
                        created_at=current,
                    )
                )

            session.add(
                AuditLog(
                    request_id=batch_id[:64],
                    action="incoming_diff_registered",
                    target_type="incoming_diff_batch",
                    target_id=batch_id,
                    changes={
                        "batchNo": batch.batch_no,
                        "workbookId": workbook.workbook_id,
                        "workbookVersion": workbook.version,
                        "recordCount": len(records),
                        "assignments": {
                            str(assignment.order_assignment_id): {
                                "before": before[detail_id],
                                "after": after[detail_id],
                            }
                            for detail_id, assignment in assignments.items() if assignment
                        },
                        "details": {
                            detail_id: {"before": before[detail_id], "after": after[detail_id]}
                            for detail_id in detail_ids
                        },
                    },
                    actor_id=actor_id,
                    source_terminal="feishu-bot",
                )
            )

            grouped: dict[tuple[str, str], list[_ParsedLine]] = {}
            for _raw, line in parsed:
                context = contexts[line.detail_id]
                grouped.setdefault((context.factory_id, context.order_id), []).append(line)
            for (factory_id, order_id), lines in sorted(grouped.items()):
                order_no = next(
                    context.order_no
                    for context in contexts.values()
                    if context.order_id == order_id
                )
                session.add(
                    OutboxMessage(
                        event_type=REGISTERED_EVENT_TYPE,
                        aggregate_type="incoming_diff_batch",
                        aggregate_id=batch_id,
                        dedupe_key=f"incoming-diff:{batch_id}:{factory_id}:{order_id}",
                        payload={
                            "batchId": batch_id,
                            "batchNo": batch.batch_no,
                            "factoryId": factory_id,
                            "orderId": order_id,
                            "orderNo": order_no,
                            "recordCount": len(lines),
                            "registeredAt": current.isoformat(),
                        },
                        status="pending",
                        available_at=current,
                    )
                )

            factory_count = len({factory_id for factory_id, _order_id in grouped})
            batch.status = "CONFIRMED"
            batch.confirmed_by = actor_id
            batch.confirmed_at = current
            batch.confirmed_record_count = len(records)
            batch.confirmed_factory_count = factory_count
            batch.updated_at = current
            result = {
                "batchId": batch_id,
                "batchNo": batch.batch_no,
                "recordCount": len(records),
                "factoryCount": factory_count,
                "confirmedAt": current.isoformat(),
                "confirmedBy": actor_id,
            }
            session.add(
                IdempotencyRecord(
                    scope=CONFIRM_SCOPE,
                    idempotency_key=idempotency_key,
                    status="completed",
                    result=result,
                )
            )
            return ConfirmResult(
                batch_id=batch_id,
                batch_no=batch.batch_no,
                record_count=len(records),
                factory_count=factory_count,
                confirmed_at=current,
                confirmed_by=actor_id,
                replayed=False,
            )

    def adjust_quantity(
        self,
        *,
        actor_id: str,
        order_id: str,
        record_id: str,
        quantity: int,
        version: int,
        request_id: str,
    ) -> IncomingDifferenceView:
        current = self._now()[0]
        with self._session_factory() as session, session.begin():
            actor = session.get(User, actor_id)
            if actor is None or not actor.is_enabled or actor.role != "admin":
                raise IncomingDifferencePermissionDenied("只有已启用的管理员可以调整来货出入")
            order = session.get(Order, order_id, with_for_update=True)
            if order is None or order.deleted_at is not None:
                raise IncomingDifferenceNotFound("订单不存在")
            record = session.scalars(
                select(IncomingDiffRecord)
                .where(
                    IncomingDiffRecord.record_id == record_id,
                    IncomingDiffRecord.order_id == order_id,
                )
                .with_for_update()
            ).one_or_none()
            if record is None:
                raise IncomingDifferenceNotFound("来货出入记录不存在")
            if record.version != version:
                raise IncomingDifferenceConflict("记录已被修改，请刷新后重试")
            if quantity == 0:
                raise IncomingDifferenceValidationError("来货出入数量不能为 0", [])

            delta = quantity - record.quantity
            if delta == 0:
                return _record_view(session, record)

            detail = session.get(OrderDetail, record.detail_id, with_for_update=True)
            if detail is None or detail.matched_variant_id != record.variant_id:
                raise IncomingDifferenceValidationError("记录关联的订单明细已变化", [])
            assignment = active_assignment(session, detail)
            before_shipped = detail_shipped(session, detail)
            if before_shipped is None:
                raise IncomingDifferenceValidationError("明细已发数量未知，不能调整", [])
            after_shipped = before_shipped + delta
            if after_shipped < 0:
                raise IncomingDifferenceValidationError(
                    f"调整后统一已发数量为 {after_shipped}，不能小于 0", []
                )

            before_quantity = record.quantity
            adjustment_id = self._id_factory()
            session.add(
                IncomingDiffAdjustment(
                    adjustment_id=adjustment_id,
                    record_id=record_id,
                    before_quantity=before_quantity,
                    after_quantity=quantity,
                    delta=delta,
                    actor_id=actor_id,
                    request_id=request_id,
                    created_at=current,
                )
            )
            session.add(
                QuantityLedger(
                    order_assignment_id=assignment.order_assignment_id if assignment else None,
                    order_detail_id=detail.detail_id if assignment is None else None,
                    source_type="INCOMING_DIFF_ADJUST",
                    source_id=adjustment_id,
                    quantity_delta=delta,
                    actor_id=actor_id,
                    created_at=current,
                )
            )
            record.quantity = quantity
            record.version += 1
            record.updated_at = current
            detail.version += 1
            detail.updated_at = current
            order.version += 1
            order.updated_at = current
            session.add(
                AuditLog(
                    request_id=request_id,
                    action="incoming_diff_adjusted",
                    target_type="incoming_diff_record",
                    target_id=record_id,
                    changes={
                        "beforeQuantity": before_quantity,
                        "afterQuantity": quantity,
                        "delta": delta,
                        "beforeUnifiedShippedQuantity": before_shipped,
                        "afterUnifiedShippedQuantity": after_shipped,
                    },
                    actor_id=actor_id,
                    source_terminal="admin-web",
                )
            )
            order = session.get(Order, order_id)
            if order is None:
                raise IncomingDifferenceNotFound("订单不存在")
            session.add(
                OutboxMessage(
                    event_type=ADJUSTED_EVENT_TYPE,
                    aggregate_type="incoming_diff_record",
                    aggregate_id=record_id,
                    dedupe_key=f"incoming-diff:{record_id}:adjusted:{adjustment_id}",
                    payload={
                        "recordId": record_id,
                        "adjustmentId": adjustment_id,
                        "factoryId": detail.matched_factory_id,
                        "orderId": order_id,
                        "orderNo": order.order_no,
                        "beforeQuantity": before_quantity,
                        "afterQuantity": quantity,
                        "adjustedAt": current.isoformat(),
                    },
                    status="pending",
                    available_at=current,
                )
            )
            return _record_view(session, record)

    def list_for_order(self, *, actor_id: str, order_id: str) -> list[IncomingDifferenceView]:
        with self._session_factory() as session:
            actor = session.get(User, actor_id)
            if actor is None or not actor.is_enabled:
                raise IncomingDifferencePermissionDenied("账号不可用")
            order = session.get(Order, order_id)
            if order is None or order.deleted_at is not None:
                raise IncomingDifferenceNotFound("订单不存在")
            statement = (
                select(IncomingDiffRecord)
                .join(OrderDetail, OrderDetail.detail_id == IncomingDiffRecord.detail_id)
                .outerjoin(OrderAssignment,
                           OrderAssignment.order_assignment_id == OrderDetail.assignment_id)
                .where(IncomingDiffRecord.order_id == order_id)
                .order_by(IncomingDiffRecord.registered_at, IncomingDiffRecord.record_id)
            )
            is_admin = actor.role == "admin"
            if not is_admin:
                if not actor.factory_id:
                    raise IncomingDifferencePermissionDenied("账号未绑定工厂")
                statement = statement.where(
                    OrderAssignment.factory_id == actor.factory_id,
                    OrderAssignment.is_active.is_(True), OrderDetail.dispatch_state == "ASSIGNED",
                )
            records = session.scalars(statement).all()
        return [
            IncomingDifferenceView(
                sequence=index,
                registered_at=record.registered_at,
                product_name=record.product_name_snapshot,
                spec=record.spec_snapshot,
                quantity=record.quantity,
                record_id=record.record_id if is_admin else None,
                purchase_order_id=record.purchase_order_id if is_admin else None,
                product_code=record.product_code_snapshot if is_admin else None,
                version=record.version if is_admin else None,
            )
            for index, record in enumerate(records, 1)
        ]

    def _now(self) -> tuple[datetime, date]:
        current_aware = self._clock().astimezone(UTC)
        return (
            current_aware.replace(tzinfo=None),
            current_aware.astimezone(BUSINESS_TIME_ZONE).date(),
        )


def _line_reason(raw: dict[str, Any], image_ids: set[str], *, imported: bool = False) -> str | None:
    if not isinstance(raw, dict):
        return "数据行格式不正确"
    if not (raw.get("orderAssignmentId") or raw.get("detailId")):
        return "未匹配到唯一订单明细"
    if not raw.get("quantity"):
        return "数量不能为 0"
    if not raw.get("purchaseOrderId"):
        return "缺少采购主单号"
    if not raw.get("purchaseOrderItemId"):
        return "缺少采购子单号"
    if not imported and str(raw.get("imageId") or "") not in image_ids:
        return "数据行不属于本批次图片"
    return None


def _record_view(session: Session, record: IncomingDiffRecord) -> IncomingDifferenceView:
    record_ids = session.scalars(
        select(IncomingDiffRecord.record_id)
        .where(IncomingDiffRecord.order_id == record.order_id)
        .order_by(IncomingDiffRecord.registered_at, IncomingDiffRecord.record_id)
    ).all()
    return IncomingDifferenceView(
        sequence=record_ids.index(record.record_id) + 1,
        registered_at=record.registered_at,
        product_name=record.product_name_snapshot,
        spec=record.spec_snapshot,
        quantity=record.quantity,
        record_id=record.record_id,
        purchase_order_id=record.purchase_order_id,
        product_code=record.product_code_snapshot,
        version=record.version,
    )


def _issue(raw: dict[str, Any], reason: str) -> dict[str, Any]:
    sheet_name = str(raw.get("sheetName") or "") if isinstance(raw, dict) else ""
    row_number = raw.get("rowNumber") if isinstance(raw, dict) else None
    return {
        **({"fileName": raw["fileName"]} if raw.get("fileName") else {}),
        "sheetName": sheet_name,
        "rowNumber": int(row_number) if row_number else 0,
        "reason": reason,
    }


def _issue_message(issues: list[dict[str, Any]]) -> str:
    return "；".join(
        f"{issue['sheetName']} 第 {issue['rowNumber']} 行：{issue['reason']}"
        for issue in issues
    )


def _detail_contexts(
    session: Session, detail_ids: list[str]
) -> dict[str, _AssignmentContext]:
    rows = session.execute(
        select(
            OrderDetail.detail_id,
            OrderDetail.matched_factory_id.label("factory_id"),
            Order.order_id,
            Order.order_no,
            ProductVariant.variant_id.label("product_variant_id"),
            Product.name.label("product_name_snapshot"),
            ProductVariant.properties_value.label("properties_value_snapshot"),
            Product.source_i_id,
        )
        .select_from(OrderDetail)
        .join(Order, Order.order_id == OrderDetail.order_id)
        .join(ProductVariant, ProductVariant.variant_id == OrderDetail.matched_variant_id)
        .join(Product, Product.product_id == ProductVariant.product_id)
        .where(
            OrderDetail.detail_id.in_(detail_ids),
            OrderDetail.matched_factory_id.is_not(None),
            Order.deleted_at.is_(None),
        )
    ).all()
    return {
        row.detail_id: _AssignmentContext(
            order_id=row.order_id,
            order_no=row.order_no,
            detail_id=str(row.detail_id),
            factory_id=row.factory_id,
            variant_id=row.product_variant_id,
            product_code=row.source_i_id,
            product_name=row.product_name_snapshot,
            spec=row.properties_value_snapshot,
        )
        for row in rows
    }


def _replayed_result(result: dict[str, Any]) -> ConfirmResult:
    return ConfirmResult(
        batch_id=str(result["batchId"]),
        batch_no=str(result["batchNo"]),
        record_count=int(result["recordCount"]),
        factory_count=int(result["factoryCount"]),
        confirmed_at=datetime.fromisoformat(str(result["confirmedAt"])),
        confirmed_by=str(result["confirmedBy"]),
        replayed=True,
    )
