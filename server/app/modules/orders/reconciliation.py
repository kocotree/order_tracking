"""Reconcile complete source membership while retaining executed assignment identities."""

from collections import defaultdict
from datetime import date
from typing import Any
from uuid import uuid4

from sqlalchemy import select

from app.db.models import (
    OrderAssignment,
    OrderDetail,
    OrderImportSourceRecord,
    OrderLine,
    QuantityLedger,
)
from app.modules.order_import import OrderImportService, SourceOrderRow
from app.modules.orders.dispatch import OrderDispatchService
from app.modules.orders.service import OrderConflict
from app.modules.orders.source_update import _hash


def discovery_fields(row: SourceOrderRow) -> dict[str, object]:
    """Compare source facts without treating ERP receipts or read times as source edits."""
    fields = OrderImportService._normalized_source_fields(row)
    for name in ("shippedQuantity", "pendingQuantity", "contractDateMappingVersion"):
        fields.pop(name, None)
    fields["orderQuantity"] = row.raw_fields.get("下单数", row.order_quantity)
    fields["sourceDetailId"] = row.source_detail_id
    fields["purchaseLinks"] = [
        row.raw_fields.get(name)
        for name in (
            "采购单号",
            "采购子订单号-人工确认",
            "采购子订单号-映射",
        )
    ]
    return fields


class OrderReconciliationService(OrderDispatchService):
    def reconcile_automatically(
        self,
        *,
        order_id: str,
        record_ids: list[str],
        run_id: str,
        request_id: str,
    ) -> int:
        if not record_ids or len(set(record_ids)) != len(record_ids):
            raise OrderConflict("来源明细缺失或重复，原资料保持不变")
        with self._session_factory() as session:
            order = self._require_order(session, order_id)
            version, order_no = order.version, order.order_no
            details = self._details(session, order_id)
            links = {}
            for detail in details:
                source = session.get(OrderImportSourceRecord, detail.source_record_pk)
                if source and detail.purchase_order_id and detail.purchase_order_item_id:
                    links[source.source_record_id] = (
                        detail.purchase_order_id,
                        detail.purchase_order_item_id,
                    )
        fetched = self._source.read_records(record_ids, purchase_links=links)
        if (
            len(fetched) != len(record_ids)
            or {row.record_id for row in fetched} != set(record_ids)
            or any((row.order_no or "").strip().upper() != order_no for row in fetched)
        ):
            raise OrderConflict("完整订单来源集合已变化")
        self._product_importer.recover_products(fetched, request_id=request_id)
        with self._session_factory() as session, session.begin():
            order = self._check(session, None, order_id, version, lock=True)
            if order.source != "feishu" or order.deleted_at is not None:
                raise OrderConflict("当前订单不参与来源对账")
            details = self._details(session, order_id, lock=True)
            sources = {
                detail.detail_id: session.get(OrderImportSourceRecord, detail.source_record_pk)
                for detail in details
                if detail.source_record_pk
            }
            if any(
                source and source.source_scope != self._source.source_scope
                for source in sources.values()
            ):
                raise OrderConflict("来源作用域不一致")
            by_record = {row.record_id: row for row in fetched}
            by_identity: dict[tuple[str | None, ...], list[SourceOrderRow]] = defaultdict(list)
            purchase_ids = set()
            for row in fetched:
                po, poi = OrderImportService.purchase_link_ids(row.raw_fields)
                variant, factory, _ = OrderImportService.match_source_row(session, row)
                if po and poi:
                    if (po, poi) in purchase_ids:
                        raise OrderConflict("同一采购明细重复出现在来源中")
                    purchase_ids.add((po, poi))
                    if variant and factory:
                        by_identity[(po, poi, variant.source_sku_id, factory.factory_id)].append(
                            row
                        )

            updates: dict[str, dict[str, Any]] = {}
            bindings = {}
            used = set()
            splits: list[dict[str, Any]] = []
            assignments = {}
            for detail in details:
                source = sources.get(detail.detail_id)
                if source is None:
                    continue
                if source.source_record_id in by_record and (
                    source.source_detail_id != by_record[source.source_record_id].source_detail_id
                ):
                    raise OrderConflict("来源明细身份已变化")
                current_row = by_record.get(source.source_record_id)
                selected: SourceOrderRow | None = current_row
                if detail.dispatch_state == "ASSIGNED":
                    identity = (
                        detail.purchase_order_id,
                        detail.purchase_order_item_id,
                        detail.source_sku_id,
                        detail.matched_factory_id,
                    )
                    candidates = by_identity.get(identity, []) if all(identity) else []
                    if len(candidates) == 1 and not detail.factory_override_enabled:
                        selected = candidates[0]
                    if selected is None:
                        raise OrderConflict("已派工明细没有唯一的原工厂采购来源")
                    row = selected
                    if (
                        any(identity[:2])
                        and OrderImportService.purchase_link_ids(row.raw_fields) != identity[:2]
                    ):
                        raise OrderConflict("已派工明细采购归属已变化")
                    variant, factory, _ = OrderImportService.match_source_row(session, row)
                    if (
                        variant is None
                        or variant.variant_id != detail.matched_variant_id
                        or (
                            not detail.factory_override_enabled
                            and (factory is None or factory.factory_id != detail.matched_factory_id)
                        )
                    ):
                        raise OrderConflict("已派工明细无法保留原工厂或SKU归属")
                    assignment = session.get(
                        OrderAssignment, detail.assignment_id, with_for_update=True
                    )
                    if assignment is None or not assignment.is_active:
                        raise OrderConflict("原派工已变化")
                    assignments[detail.detail_id] = assignment
                    changed = (
                        row.record_id != source.source_record_id
                        or row.order_quantity != assignment.assigned_quantity
                        or (
                            "下单数" in detail.accepted_raw_fields
                            and row.raw_fields.get("下单数") != detail.accepted_raw_fields["下单数"]
                        )
                    )
                    if changed:
                        if detail.factory_override_enabled or detail.shipped_override_enabled:
                            raise OrderConflict("人工覆盖明细不自动拆分")
                        if (
                            not all(identity)
                            or OrderImportService.purchase_link_ids(row.raw_fields) != identity[:2]
                        ):
                            raise OrderConflict("拆分采购身份不唯一")
                        if (
                            row.order_quantity is None
                            or isinstance(row.order_quantity, bool)
                            or row.order_quantity <= 0
                        ):
                            raise OrderConflict("拆分后的下单数量无效")
                        self._validate_incoming(
                            session,
                            detail,
                            {
                                "matched_factory_id": detail.matched_factory_id,
                                "matched_variant_id": detail.matched_variant_id,
                                "purchase_order_id": detail.purchase_order_id,
                                "purchase_order_item_id": detail.purchase_order_item_id,
                            },
                        )
                        ledger = list(
                            session.scalars(
                                select(QuantityLedger)
                                .where(
                                    QuantityLedger.order_assignment_id
                                    == assignment.order_assignment_id
                                )
                                .with_for_update()
                            )
                        )
                        shipped = assignment.initial_shipped_quantity + sum(
                            r.quantity_delta for r in ledger
                        )
                        if row.order_quantity < shipped:
                            raise OrderConflict("拆分后的下单数量不足以承接原工厂已发量")
                        old_group = [d for d in details if d.source_sku_id == detail.source_sku_id]
                        new_group = [r for r in fetched if r.source_sku_id == detail.source_sku_id]
                        if (
                            any(d.order_quantity is None for d in old_group)
                            or any(r.order_quantity is None for r in new_group)
                            or sum(d.order_quantity or 0 for d in old_group)
                            != sum(r.order_quantity or 0 for r in new_group)
                        ):
                            raise OrderConflict("拆分前后同SKU总量不守恒")
                        splits.append(
                            {
                                "detailId": detail.detail_id,
                                "sourceSkuId": detail.source_sku_id,
                                "before": assignment.assigned_quantity,
                                "after": row.order_quantity,
                                "shippedQuantity": shipped,
                                "sourceBefore": source.source_record_id,
                                "sourceAfter": row.record_id,
                            }
                        )
                        updates[detail.detail_id] = {
                            "order_quantity": row.order_quantity,
                            "accepted_raw_fields": row.raw_fields,
                            "accepted_source_hash": _hash(row.raw_fields),
                            "accepted_source_modified_at": row.source_modified_at.isoformat()
                            if row.source_modified_at
                            else None,
                        }
                else:
                    if selected is None:
                        raise OrderConflict("未派工来源明细缺失")
                    row = selected
                    values = self._values(session, row, detail)
                    if self._changed(detail, values):
                        updates[detail.detail_id] = values
                if row.record_id in used:
                    raise OrderConflict("多条系统明细对应同一来源")
                used.add(row.record_id)
                bindings[detail.detail_id] = row

            additions: list[OrderDetail] = []
            split_skus = {split["sourceSkuId"] for split in splits}
            assigned_sources = {
                bindings[detail.detail_id].record_id
                for detail in details
                if detail.dispatch_state == "ASSIGNED" and detail.detail_id in bindings
            }
            for row in fetched:
                if row.source_sku_id in split_skus and row.record_id not in assigned_sources:
                    purchase = row.raw_fields.get("_purchase")
                    variant, factory, _ = OrderImportService.match_source_row(session, row)
                    if (
                        not all(OrderImportService.purchase_link_ids(row.raw_fields))
                        or not isinstance(purchase, dict)
                        or purchase.get("skuId") != row.source_sku_id
                        or variant is None
                        or factory is None
                        or row.shipped_quantity is None
                        or row.shipped_quantity < 0
                    ):
                        raise OrderConflict("拆分新工厂缺少精确采购明细或已发基线")
                if row.record_id in used:
                    continue
                if any(
                    d.source_record_pk is None and d.source_sku_id == row.source_sku_id
                    for d in details
                ):
                    raise OrderConflict("新增来源与无来源关联的系统明细冲突")
                detail = OrderDetail(
                    detail_id=str(uuid4()),
                    order_id=order_id,
                    origin="feishu",
                    sort_order=max((d.sort_order for d in details), default=0) + len(additions) + 1,
                    accepted_raw_fields={},
                    parse_issues=[],
                    dispatch_state="UNASSIGNED",
                    date_override_enabled=False,
                    factory_override_enabled=False,
                    shipped_override_enabled=False,
                    auto_dispatch_paused=False,
                    version=1,
                    created_at=self._now(),
                    updated_at=self._now(),
                )
                updates[detail.detail_id] = self._values(session, row, detail)
                bindings[detail.detail_id] = row
                additions.append(detail)

            accepted_sources = {}
            for row in fetched:
                source = session.scalar(
                    select(OrderImportSourceRecord)
                    .where(
                        OrderImportSourceRecord.source_scope == self._source.source_scope,
                        OrderImportSourceRecord.source_record_id == row.record_id,
                    )
                    .with_for_update()
                )
                if source is not None and (
                    source.order_no != order_no or (source.source_detail_id != row.source_detail_id)
                ):
                    raise OrderConflict("来源身份或归属已变化")
                if source is None:
                    source = OrderImportSourceRecord(
                        source_scope=self._source.source_scope,
                        source_record_id=row.record_id,
                        first_seen_run_id=run_id,
                        first_seen_at=self._now(),
                    )
                    session.add(source)
                source.source_detail_id, source.order_no = row.source_detail_id, order_no
                source.raw_fields = row.raw_fields
                source.normalized_fields = {
                    **OrderImportService._normalized_source_fields(row),
                    "reconciliationFields": discovery_fields(row),
                }
                source.source_modified_at = row.source_modified_at
                source.parse_status = "PARSED"
                source.last_seen_run_id, source.last_seen_at = run_id, self._now()
                source.error_code = source.error_message = None
                session.flush()
                accepted_sources[row.record_id] = source
            rebound = [
                d
                for d in details
                if d.detail_id in bindings
                and d.source_record_pk
                != accepted_sources[bindings[d.detail_id].record_id].source_record_pk
            ]
            for detail in rebound:
                detail.source_record_pk = None
            session.flush()
            for detail in details + additions:
                if detail.detail_id in bindings:
                    detail.source_record_pk = accepted_sources[
                        bindings[detail.detail_id].record_id
                    ].source_record_pk
            for split in splits:
                assignment = assignments[split["detailId"]]
                delta = split["after"] - assignment.assigned_quantity
                assignment.assigned_quantity = split["after"]
                assignment.updated_at = self._now()
                line = session.get(OrderLine, assignment.order_line_id, with_for_update=True)
                if line is None or line.order_quantity + delta <= 0:
                    raise OrderConflict("拆分后的产品行数量无效")
                line.order_quantity += delta
                line.updated_at = self._now()
            if updates or rebound:
                self._apply_source_values(order, details + additions, updates, None)
            session.add_all(additions)
            session.flush()
            self._add_audit(
                session,
                request_id=request_id,
                action="order.source_refreshed" if updates or rebound else "order.source_checked",
                order_id=order_id,
                actor_id=None,
                changes={
                    "content": "自动核对完整订单来源明细",
                    "sources": updates,
                    "addedDetailIds": [d.detail_id for d in additions],
                    "factorySplits": splits,
                },
            )
            return order.version

    @staticmethod
    def _changed(detail: OrderDetail, values: dict[str, Any]) -> bool:
        for key, value in values.items():
            current = getattr(detail, key)
            if isinstance(current, date):
                current = current.isoformat()
            if key == "accepted_raw_fields":
                if _hash(current) != _hash(value):
                    return True
            elif current != value:
                return True
        return False
