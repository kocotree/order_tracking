"""Validate and dispatch selected saved order details."""

import json
from datetime import timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.db.models import (
    Factory,
    IdempotencyRecord,
    IncomingDiffRecord,
    Order,
    OrderAssignment,
    OrderChangePreview,
    OrderDetail,
    OrderLine,
    OutboxMessage,
    Product,
    ProductVariant,
    QuantityLedger,
    User,
)
from app.modules.orders.service import (
    TRACKERS,
    OrderConflict,
    OrderSnapshot,
    OrderValidationError,
)
from app.modules.orders.source_update import SNAPSHOT, OrderSourceUpdateService, _hash

DISPATCH_PREVIEW_MINUTES = 5


class OrderDispatchService(OrderSourceUpdateService):
    """Dispatch execution records on top of #89 source update flows."""

    # ------------------------------------------------------------------
    # preview
    # ------------------------------------------------------------------
    def dispatch_preview(
        self,
        *,
        actor_id: str,
        order_id: str,
        version: int,
        detail_ids: list[str],
        request_id: str,
    ) -> dict[str, Any]:
        if not detail_ids:
            raise OrderConflict("请至少选择一条未派工明细")
        if len(detail_ids) != len(set(detail_ids)):
            raise OrderConflict("明细选择不能重复")

        with self._session_factory() as session, session.begin():
            order = self._check(session, actor_id, order_id, version, lock=True)
            rows = self._details(session, order_id, lock=True)
            selected = {row.detail_id: row for row in rows if row.detail_id in set(detail_ids)}
            if set(selected) != set(detail_ids):
                raise OrderConflict("所选明细已变化，请重新加载")
            for row in selected.values():
                if row.dispatch_state != "UNASSIGNED":
                    raise OrderConflict("所选明细包含已派工行，请重新选择")
            ordered = sorted(selected.values(), key=lambda row: (row.sort_order, row.detail_id))
            validations, _context = self._validate_dispatch_rows(session, order, ordered)
            all_ok = all(item["passes"] for item in validations)
            now = self._now()
            preview = OrderChangePreview(
                preview_id=str(uuid4()),
                order_id=order_id,
                actor_id=actor_id,
                version=version,
                created_at=now,
                expires_at=now + timedelta(minutes=DISPATCH_PREVIEW_MINUTES),
                payload={
                    "kind": "dispatch",
                    "source_preview_id": None,
                    "detail_ids": list(detail_ids),
                    "versions": {row.detail_id: row.version for row in ordered},
                    "validations": validations,
                    "all_ok": all_ok,
                },
            )
            session.add(preview)
            return {
                "preview_id": preview.preview_id,
                "version": version,
                "expires_at": preview.expires_at,
                "requires_source_confirmation": False,
                "source_preview": None,
                "validations": validations,
                "all_ok": all_ok,
            }

    # ------------------------------------------------------------------
    # confirm
    # ------------------------------------------------------------------
    def dispatch_confirm(
        self,
        *,
        actor_id: str,
        order_id: str,
        version: int,
        preview_id: str,
        idempotency_key: str,
        request_id: str,
    ) -> OrderSnapshot:
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
                return SNAPSHOT.validate_python(repeated.result)
            pending = session.get(OrderChangePreview, preview_id)
            if (
                pending is None
                or pending.order_id != order_id
                or pending.actor_id != actor_id
                or pending.version != version
                or pending.consumed_at is not None
                or pending.expires_at <= self._now()
                or pending.payload.get("kind") != "dispatch"
            ):
                raise OrderConflict("派工预览已失效，请重新检查")
            detail_ids: list[str] = list(pending.payload["detail_ids"])
            versions = dict(pending.payload["versions"])

        return self._dispatch_saved(
            actor_id=actor_id, order_id=order_id, version=version,
            detail_ids=detail_ids, versions=versions, request_id=request_id,
            scope=scope, idempotency_key=idempotency_key, request_hash=request_hash,
            preview_id=preview_id,
        )

    def _dispatch_saved(
        self, *, actor_id: str | None, order_id: str, version: int,
        detail_ids: list[str], versions: dict[str, int], request_id: str,
        scope: str, idempotency_key: str, request_hash: str,
        preview_id: str | None = None,
    ) -> OrderSnapshot:
        with self._session_factory() as session, session.begin():
            if actor_id is not None:
                self._require_admin(session, actor_id)
            order = self._locked_order(session, order_id)
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
                return SNAPSHOT.validate_python(repeated.result)
            if not order.detail_mode or order.version != version:
                raise OrderConflict("订单状态或版本已变化，请重新加载")
            if order.lifecycle not in {"DRAFT", "PUBLISHED"}:
                raise OrderConflict("当前订单不支持明细派工")
            preview = session.get(OrderChangePreview, preview_id) if preview_id else None
            if preview_id and (
                preview is None
                or preview.order_id != order_id
                or preview.actor_id != actor_id
                or preview.version != version
                or preview.consumed_at is not None
                or preview.expires_at <= self._now()
                or preview.payload.get("kind") != "dispatch"
            ):
                raise OrderConflict("派工预览已失效，请重新检查")

            rows = self._details(session, order_id, lock=True)
            selected = {row.detail_id: row for row in rows if row.detail_id in set(detail_ids)}
            if set(selected) != set(detail_ids):
                raise OrderConflict("所选明细已变化，请重新加载")
            ordered = sorted(selected.values(), key=lambda row: (row.sort_order, row.detail_id))
            for row in ordered:
                if row.dispatch_state != "UNASSIGNED":
                    raise OrderConflict("所选明细包含已派工行，请重新选择")
                if row.version != versions[row.detail_id]:
                    raise OrderConflict("明细版本已变化，请重新检查")
                if actor_id is None and row.auto_dispatch_paused:
                    raise OrderConflict("人工撤回明细暂停自动派工")
            if actor_id is None:
                factory_ids = {row.matched_factory_id for row in ordered}
                if len(factory_ids) != 1 or None in factory_ids:
                    raise OrderConflict("自动派工工厂匹配无效")
                factory_id = ordered[0].matched_factory_id
                factory = session.get(Factory, factory_id)
                complete_ids = {
                    row.detail_id for row in rows
                    if row.dispatch_state == "UNASSIGNED"
                    and (row.matched_factory_id == factory_id
                         or (factory and row.factory_name == factory.factory_name))
                }
                if complete_ids != set(detail_ids):
                    raise OrderConflict("同厂待派工明细已变化")

            # Re-validate under locks; products, factories and accounts are
            # read with row locks in a fixed sorted order so a concurrent
            # deactivation cannot slip between the check and the write.
            validations, context = self._validate_dispatch_rows(session, order, ordered)
            if not all(item["passes"] for item in validations):
                failed = [
                    f"{item['label']}（{'；'.join(item['issues'])}）"
                    for item in validations
                    if not item["passes"]
                ]
                raise OrderValidationError(
                    "所选明细存在未通过项，本次不会派工：" + "；".join(failed)
                )

            now = self._now()
            batch_id = str(uuid4())
            factory_lines: dict[str, list[dict[str, Any]]] = {}
            factory_assignment_ids: dict[str, list[int]] = {}

            if order.tracker_locked_at is None:
                all_rows = sorted(
                    self._details(session, order_id),
                    key=lambda row: (row.sort_order, row.detail_id),
                )
                trackers = list(dict.fromkeys(
                    tracker
                    for row in all_rows
                    for tracker in self._row_trackers(row)
                    if tracker and (actor_id is not None or tracker in TRACKERS)
                ))
                if not trackers or any(tracker not in TRACKERS for tracker in trackers):
                    raise OrderConflict("来源跟单信息缺失或无效，不能首次派工")
                order.trackers = trackers
                order.tracker = trackers[0]
                order.tracker_locked_at = now

            for row in ordered:
                variant = context["variants"][row.matched_variant_id]
                product = context["products"][variant.product_id] if variant else None
                factory = context["factories"][row.matched_factory_id]
                if variant is None or product is None or factory is None:
                    # _validate_dispatch_rows already rejected these rows.
                    raise OrderValidationError("所选明细存在未通过项，本次不会派工")
                quantity = row.order_quantity
                shipped = row.source_shipped_quantity
                if quantity is None or quantity <= 0 or shipped is None or shipped < 0:
                    raise OrderValidationError("所选明细数量无效，本次不会派工")

                line = session.scalar(
                    select(OrderLine)
                    .where(
                        OrderLine.order_id == order_id,
                        OrderLine.product_variant_id == variant.variant_id,
                    )
                    .with_for_update()
                    .limit(1)
                )
                if line is None:
                    line = OrderLine(
                        order_id=order_id,
                        product_variant_id=variant.variant_id,
                        order_quantity=quantity,
                        sku_id_snapshot=variant.source_sku_id,
                        product_name_snapshot=product.name,
                        properties_value_snapshot=variant.properties_value,
                        category_snapshot=variant.source_category,
                        image_object_key_snapshot=variant.cached_image_key,
                        created_at=now,
                        updated_at=now,
                    )
                    session.add(line)
                    session.flush()
                else:
                    line.order_quantity += quantity
                    line.updated_at = now

                assignment = OrderAssignment(
                    order_line_id=line.order_line_id,
                    factory_id=factory.factory_id,
                    detail_id=row.detail_id,
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

                row.assignment_id = assignment.order_assignment_id
                session.execute(update(QuantityLedger).where(
                    QuantityLedger.order_detail_id == row.detail_id
                ).values(order_assignment_id=assignment.order_assignment_id, order_detail_id=None))
                session.execute(update(IncomingDiffRecord).where(
                    IncomingDiffRecord.detail_id == row.detail_id,
                    IncomingDiffRecord.order_assignment_id.is_(None),
                ).values(order_assignment_id=assignment.order_assignment_id))
                row.dispatch_batch_id = batch_id
                row.dispatch_state = "ASSIGNED"
                row.auto_dispatch_paused = False
                row.version += 1
                row.updated_at = now

                factory_lines.setdefault(factory.factory_id, []).append(
                    {
                        "skuId": row.source_sku_id,
                        "productName": row.product_name,
                        "propertiesValue": row.properties_value,
                        "contractShipDate": row.contract_ship_date.isoformat()
                        if row.contract_ship_date
                        else None,
                        "assignedQuantity": quantity,
                        "initialShippedQuantity": shipped,
                    }
                )
                factory_assignment_ids.setdefault(factory.factory_id, []).append(
                    assignment.order_assignment_id
                )

            before_lifecycle = order.lifecycle
            if order.lifecycle == "DRAFT":
                order.lifecycle = "PUBLISHED"
                order.published_at = now
                order.published_by = actor_id
            order.version += 1
            order.updated_at = now
            order.updated_by = actor_id
            if preview is not None:
                preview.consumed_at = now

            self._add_audit(
                session,
                request_id=request_id,
                action="order.detail_dispatched",
                order_id=order_id,
                actor_id=actor_id,
                changes={
                    "batchId": batch_id,
                    "detailIds": list(detail_ids),
                    "factoryIds": sorted(factory_lines),
                    "factoryNames": [
                        (
                            context["factories"][fid].factory_name
                            if context["factories"][fid]
                            else fid
                        )
                        for fid in sorted(factory_lines)
                    ],
                    "assignmentIds": [
                        aid
                        for fid in sorted(factory_assignment_ids)
                        for aid in factory_assignment_ids[fid]
                    ],
                    "sourcePreviewId": preview.payload["source_preview_id"] if preview else None,
                    "lifecycleBefore": before_lifecycle,
                    "lifecycleAfter": order.lifecycle,
                },
            )

            # One notification event per factory per batch; the payload fixes
            # the batch scope so a later dispatch can never leak into an
            # earlier batch's notification.
            for factory_id in sorted(factory_lines):
                session.add(
                    OutboxMessage(
                        event_type="order_detail_dispatched",
                        aggregate_type="order",
                        aggregate_id=order_id,
                        dedupe_key=f"order_detail_dispatched:{order_id}:{batch_id}:{factory_id}",
                        payload={
                            "orderId": order_id,
                            "factoryId": factory_id,
                            "batchId": batch_id,
                            "assignmentIds": factory_assignment_ids[factory_id],
                            "lines": factory_lines[factory_id],
                        },
                        available_at=now,
                    )
                )

            all_rows = self._details(session, order_id)
            result = self._source_snapshot(session, order, all_rows)
            session.add(
                IdempotencyRecord(
                    scope=scope,
                    idempotency_key=idempotency_key,
                    status="completed",
                    request_hash=request_hash,
                    result=json.loads(SNAPSHOT.dump_json(result)),
                )
            )
            return result

    def dispatch_automatically(self, *, order_id: str, request_id: str) -> dict[str, Any]:
        with self._session_factory() as session:
            order = self._require_order(session, order_id)
            if order.source != "feishu" or order.lifecycle not in {"DRAFT", "PUBLISHED"}:
                raise OrderConflict("当前订单不参与自动派工")
            rows = self._details(session, order_id)
            factory_names = {
                factory.factory_id: factory.factory_name
                for factory in session.scalars(select(Factory))
            }
            groups: dict[str, list[str]] = {}
            for row in rows:
                if row.dispatch_state != "UNASSIGNED":
                    continue
                factory_id = row.matched_factory_id
                if factory_id is None:
                    factory_id = next((fid for fid, name in factory_names.items()
                                       if name == row.factory_name), None)
                if factory_id is not None:
                    groups.setdefault(factory_id, []).append(row.detail_id)
            versions = {row.detail_id: row.version for row in rows}
            version = order.version
        dispatched = 0
        failures = {}
        for factory_id, detail_ids in sorted(groups.items()):
            try:
                result = self._dispatch_saved(
                    actor_id=None, order_id=order_id, version=version,
                    detail_ids=detail_ids, versions=versions, request_id=request_id,
                    scope=f"order.auto_dispatch:{order_id}",
                    idempotency_key=f"{request_id}:{factory_id}",
                    request_hash=_hash([detail_ids, versions]),
                )
                version = result.version
                dispatched += 1
            except (OrderConflict, OrderValidationError) as error:
                failures[factory_id] = str(error)
        return {"dispatched_groups": dispatched, "blocked_factories": failures}

    # ------------------------------------------------------------------
    # validation
    # ------------------------------------------------------------------
    def _validate_dispatch_rows(
        self, session: Session, order: Order, rows: list[OrderDetail]
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Validate the selected detail rows against the dispatch rules.

        Related products, factories and factory accounts are read with row
        locks in a fixed sorted order so that the confirm transaction
        serializes with concurrent deactivation.
        """
        variant_ids = sorted({row.matched_variant_id for row in rows if row.matched_variant_id})
        variants: dict[str, ProductVariant | None] = {
            variant_id: session.get(ProductVariant, variant_id, with_for_update=True)
            for variant_id in variant_ids
        }
        product_ids = sorted(
            {variant.product_id for variant in variants.values() if variant is not None}
        )
        products: dict[str, Product | None] = {
            product_id: session.get(Product, product_id, with_for_update=True)
            for product_id in product_ids
        }
        factory_ids = sorted({row.matched_factory_id for row in rows if row.matched_factory_id})
        factories: dict[str, Factory | None] = {
            factory_id: session.get(Factory, factory_id, with_for_update=True)
            for factory_id in factory_ids
        }
        accounts: dict[str, list[User]] = {}
        for factory_id in factory_ids:
            accounts[factory_id] = list(
                session.scalars(
                    select(User)
                    .where(
                        User.role == "factory",
                        User.factory_id == factory_id,
                        User.is_enabled.is_(True),
                    )
                    .order_by(User.user_id)
                    .with_for_update()
                )
            )

        validations: list[dict[str, Any]] = []
        for row in rows:
            problems: list[str] = []
            variant = variants.get(row.matched_variant_id) if row.matched_variant_id else None
            if variant is None:
                problems.append("产品资料未匹配")
            elif not variant.is_available:
                problems.append("产品资料不可用")
            factory = factories.get(row.matched_factory_id) if row.matched_factory_id else None
            if factory is None:
                problems.append("工厂未匹配")
            elif not factory.is_enabled:
                problems.append("工厂未启用")
            elif not accounts[factory.factory_id]:
                problems.append("工厂无审核通过且已启用账号")
            if row.contract_ship_date is None:
                problems.append("缺合同出货时间")
            if row.order_quantity is None or row.order_quantity <= 0:
                problems.append("下单数量须为正整数")
            if row.source_shipped_quantity is None or row.source_shipped_quantity < 0:
                problems.append("初始已发数量须为非负整数")
            trackers = self._row_trackers(row)
            if not trackers:
                problems.append("跟单人员缺失")
            elif any(tracker not in TRACKERS for tracker in trackers):
                problems.append("跟单人员无效")
            validations.append(
                {
                    "detail_id": row.detail_id,
                    "label": f"第{row.sort_order}条 · {row.properties_value or '—'}",
                    "factory_name": row.factory_name or "—",
                    "passes": not problems,
                    "issues": problems,
                }
            )
        context = {
            "variants": variants,
            "products": products,
            "factories": factories,
            "accounts": accounts,
        }
        return validations, context

    @staticmethod
    def _row_trackers(row: OrderDetail) -> list[str]:
        return list(row.source_trackers or ([row.source_tracker] if row.source_tracker else []))
