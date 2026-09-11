"""Detail-level dispatch: preview, validate and confirm for #90.

Built directly on the #89 source preview/confirm service:

- ``dispatch_preview`` reuses ``preview(detail_ids=...)``. When the selected
  details have source differences the response only points at that refresh
  preview; the admin confirms it through the existing source-refresh confirm
  endpoint (an independent confirmation that a cancelled dispatch cannot
  undo), then re-runs the dispatch preview.
- When no differences exist, each selected detail is validated against the
  dispatch rules and a short-lived dispatch preview is stored.
- ``dispatch_confirm`` re-reads the source, verifies it still matches the
  accepted detail values, re-locks products/factories/accounts in a fixed
  order and re-validates everything before a single transaction creates the
  execution records and the per-factory notification events.
"""

import json
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
from typing import Any
from uuid import uuid4

from pydantic import TypeAdapter
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

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
from app.modules.orders.service import (
    TRACKERS,
    OrderConflict,
    OrderSnapshot,
    OrderValidationError,
)
from app.modules.orders.source_update import FIELDS, OrderSourceUpdateService

_SNAPSHOT = TypeAdapter(OrderSnapshot)

DISPATCH_PREVIEW_MINUTES = 5


def _hash(value: object) -> str:
    return sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


class OrderDispatchService(OrderSourceUpdateService):
    """Dispatch execution records on top of #89 source update flows."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        source: Any,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        super().__init__(session_factory, source=source, clock=clock)

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

        # Reuse the #89 preview: reads the latest source for exactly these
        # details, verifies the selection is still unassigned and the order
        # version is current. Rejects missing/duplicated/renamed source rows.
        source_preview = self.preview(
            actor_id=actor_id,
            order_id=order_id,
            version=version,
            request_id=request_id,
            detail_ids=detail_ids,
            allow_legacy=True,
        )
        if source_preview["differences"]:
            # The admin must accept the source update first (independent
            # confirmation via the #89 endpoint), then re-run this preview.
            return {
                "preview_id": None,
                "version": version,
                "expires_at": None,
                "requires_source_confirmation": True,
                "source_preview": source_preview,
                "validations": [],
                "all_ok": False,
            }

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
                    "source_preview_id": source_preview["preview_id"],
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
                return _SNAPSHOT.validate_python(repeated.result)
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

        # Network read outside the write transaction (same contract as #89).
        from app.adapters.errors import ExternalAdapterUnavailable

        try:
            _, fetched = self._read(order_id, actor_id, version, detail_ids, allow_legacy=True)
        except (OrderConflict, ExternalAdapterUnavailable):
            # A competing retry may have committed during the source read.
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
            if not order.detail_mode or order.version != version:
                raise OrderConflict("订单状态或版本已变化，请重新加载")
            if order.lifecycle not in {"DRAFT", "PUBLISHED"}:
                raise OrderConflict("当前订单不支持明细派工")
            preview = session.get(OrderChangePreview, preview_id)
            if (
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
                if row.version != preview.payload["versions"][row.detail_id]:
                    raise OrderConflict("明细版本已变化，请重新检查")

            # The dispatch must execute exactly the accepted values that were
            # validated in the preview. If the source (or its match result)
            # changed again, require a new preview instead of silently using
            # either the old or the new values.
            for row in ordered:
                latest = self._values(session, fetched[row.detail_id], row)
                for key in FIELDS:
                    if key == "contract_ship_date" and row.date_override_enabled:
                        continue
                    before = getattr(row, key)
                    after = latest[key]
                    if isinstance(before, date):
                        before = before.isoformat()
                    if before != after:
                        raise OrderConflict("来源资料或匹配结果已变化，请重新预览并确认")

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
                trackers = {(row.source_tracker or "").strip() for row in ordered}
                if len(trackers) != 1 or not trackers <= TRACKERS:
                    raise OrderConflict("来源跟单信息缺失或不一致，不能首次派工")
                order.tracker = next(iter(trackers))
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
                        image_object_key_snapshot=product.image_object_key,
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
                row.dispatch_batch_id = batch_id
                row.dispatch_state = "ASSIGNED"
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
                    "sourcePreviewId": preview.payload["source_preview_id"],
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
                    result=json.loads(_SNAPSHOT.dump_json(result)),
                )
            )
            return result

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

        trackers = {(row.source_tracker or "").strip() for row in rows}
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
            tracker = (row.source_tracker or "").strip()
            if not tracker:
                problems.append("跟单人员缺失")
            elif tracker not in TRACKERS:
                problems.append("跟单人员无效")
            elif order.tracker_locked_at is not None and tracker != order.tracker:
                problems.append("跟单人员与已锁定执行跟单人不一致")
            elif order.tracker_locked_at is None and len(trackers) > 1:
                problems.append("跟单人员与所选其他明细不一致")
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
