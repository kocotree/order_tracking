import json
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
from typing import Any
from uuid import uuid4

from pydantic import TypeAdapter
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.adapters.order_source import AppCredentialFeishuOrderSource, FeishuOrderSource
from app.db.models import (
    Factory,
    IdempotencyRecord,
    Order,
    OrderChangePreview,
    OrderDetail,
    OrderImportSourceRecord,
    User,
)
from app.modules.order_import import OrderImportService, SourceOrderRow
from app.modules.orders.service import (
    TRACKERS,
    OrderConflict,
    OrderService,
    OrderSnapshot,
    OrderValidationError,
)

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
    "source_trackers": "跟单人员",
    "contract_ship_date": "合同出货时间",
}
RAW_FIELDS = {
    "source_sku_id": "产品编码",
    "product_name": "商品名称",
    "properties_value": "产品颜色&规格",
    "category": "一级分类",
    "factory_name": "工厂",
    "order_quantity": "下单数",
    "source_tracker": "跟单人员",
    "contract_ship_date": "合同出货时间",
}
SNAPSHOT = TypeAdapter(OrderSnapshot)


def _hash(value: object) -> str:
    if isinstance(value, dict) and isinstance(value.get("_purchase"), dict):
        value = {
            **value,
            "_purchase": {
                key: item
                for key, item in value["_purchase"].items()
                if key != "readAt"
            },
        }
    return sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


def _date(value: Any) -> date | None:
    return date.fromisoformat(value) if value else None


class OrderSourceUpdateService(OrderService):
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        source: FeishuOrderSource,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        super().__init__(session_factory, clock=clock)
        self._source = source

    def _check(
        self, session: Session, actor_id: str, order_id: str, version: int, *, lock: bool = False
    ) -> Order:
        self._require_admin(session, actor_id)
        order = (
            self._locked_order(session, order_id)
            if lock
            else self._require_order(session, order_id)
        )
        if not order.detail_mode or order.lifecycle not in {"DRAFT", "PUBLISHED"}:
            raise OrderConflict("当前订单不支持未派工明细更新")
        if order.version != version:
            raise OrderConflict("订单版本已变化，请重新加载后重试")
        return order

    @staticmethod
    def _details(session: Session, order_id: str, *, lock: bool = False) -> list[OrderDetail]:
        query = (
            select(OrderDetail)
            .where(OrderDetail.order_id == order_id)
            .order_by(OrderDetail.detail_id)
        )
        return list(session.scalars(query.with_for_update() if lock else query))

    def save_date(
        self,
        *,
        actor_id: str,
        order_id: str,
        version: int,
        detail_id: str,
        detail_version: int,
        contract_ship_date: date | None,
        request_id: str,
    ) -> OrderSnapshot:
        return self.save_fields(
            actor_id=actor_id, order_id=order_id, version=version,
            detail_id=detail_id, detail_version=detail_version,
            changes={"contract_ship_date": contract_ship_date}, request_id=request_id,
        )

    def save_fields(
        self,
        *,
        actor_id: str,
        order_id: str,
        version: int,
        detail_id: str,
        detail_version: int,
        changes: dict[str, object],
        request_id: str,
    ) -> OrderSnapshot:
        return self.save_fields_batch(
            actor_id=actor_id,
            order_id=order_id,
            version=version,
            updates=[(detail_id, detail_version, changes)],
            request_id=request_id,
        )

    def save_fields_batch(
        self,
        *,
        actor_id: str,
        order_id: str,
        version: int,
        updates: list[tuple[str, int, dict[str, object]]],
        request_id: str,
    ) -> OrderSnapshot:
        allowed = {"factory_id", "contract_ship_date", "shipped_quantity"}
        if (
            not updates
            or len({detail_id for detail_id, _, _ in updates}) != len(updates)
            or any(not changes or not set(changes) <= allowed for _, _, changes in updates)
        ):
            raise OrderValidationError("未提供可保存的明细字段")
        with self._session_factory() as session, session.begin():
            order = self._check(session, actor_id, order_id, version, lock=True)
            rows = self._details(session, order_id, lock=True)
            rows_by_id = {row.detail_id: row for row in rows}
            audits: list[dict[str, object]] = []
            state_changed = False
            for detail_id, detail_version, changes in updates:
                detail = rows_by_id.get(detail_id)
                if (
                    detail is None
                    or detail.version != detail_version
                    or detail.dispatch_state != "UNASSIGNED"
                ):
                    raise OrderConflict("明细版本或派工状态已变化，请重新加载")
                audit: dict[str, object] = {
                    "detailId": detail_id,
                    "detailLabel": detail.properties_value or detail.product_name or detail_id,
                }
                detail_changed = False
                if "factory_id" in changes:
                    factory_id = changes["factory_id"]
                    if not isinstance(factory_id, str):
                        raise OrderValidationError("工厂不能为空")
                    factory = session.get(Factory, factory_id)
                    if factory is None or not factory.is_enabled:
                        raise OrderValidationError("工厂不存在或已停用")
                    detail_changed |= (
                        detail.factory_name != factory.factory_name
                        or detail.matched_factory_id != factory.factory_id
                        or not detail.factory_override_enabled
                    )
                    if detail.factory_name != factory.factory_name:
                        audit["factory"] = {
                            "before": detail.factory_name,
                            "after": factory.factory_name,
                        }
                    detail.factory_name = factory.factory_name
                    detail.matched_factory_id = factory.factory_id
                    detail.factory_override_enabled = True
                if "contract_ship_date" in changes:
                    contract_ship_date = changes["contract_ship_date"]
                    if contract_ship_date is not None and not isinstance(contract_ship_date, date):
                        raise OrderValidationError("合同出货时间无效")
                    before_date = detail.contract_ship_date
                    detail_changed |= (
                        before_date != contract_ship_date or not detail.date_override_enabled
                    )
                    if before_date != contract_ship_date:
                        audit["contractShipDate"] = {
                            "before": before_date.isoformat() if before_date else None,
                            "after": contract_ship_date.isoformat() if contract_ship_date else None,
                        }
                    detail.contract_ship_date = contract_ship_date
                    detail.date_override_enabled = True
                if "shipped_quantity" in changes:
                    shipped = changes["shipped_quantity"]
                    if isinstance(shipped, bool) or not isinstance(shipped, int) or shipped < 0:
                        raise OrderValidationError("已发数量须为非负整数")
                    detail_changed |= (
                        detail.source_shipped_quantity != shipped
                        or not detail.shipped_override_enabled
                    )
                    if detail.source_shipped_quantity != shipped:
                        audit["shippedQuantity"] = {
                            "before": detail.source_shipped_quantity,
                            "after": shipped,
                        }
                    detail.source_shipped_quantity = shipped
                    detail.shipped_override_enabled = True
                if not detail_changed:
                    continue
                state_changed = True
                issues = list(detail.parse_issues)
                if "factory_id" in changes:
                    issues = [
                        code
                        for code in issues
                        if code not in {"FACTORY_NOT_MATCHED", "FACTORY_HAS_NO_ENABLED_USER"}
                    ]
                    if session.scalar(
                        select(User.user_id)
                        .where(
                            User.factory_id == detail.matched_factory_id,
                            User.role == "factory",
                            User.is_enabled.is_(True),
                        )
                        .limit(1)
                    ) is None:
                        issues.append("FACTORY_HAS_NO_ENABLED_USER")
                if "shipped_quantity" in changes:
                    issues = [
                        code
                        for code in issues
                        if code != "INVALID_INITIAL_SHIPPED_QUANTITY"
                    ]
                detail.parse_issues = list(dict.fromkeys(issues))
                detail.version += 1
                detail.updated_at = self._now()
                if len(audit) > 2:
                    audits.append(audit)
            if not state_changed:
                return self._source_snapshot(session, order, rows)
            self._touch(order, actor_id)
            if audits:
                self._add_audit(
                    session,
                    request_id=request_id,
                    action="order.detail_updated",
                    order_id=order_id,
                    actor_id=actor_id,
                    changes=(
                        audits[0]
                        if len(audits) == 1
                        else {"details": audits, "content": f"修改订单明细 {len(audits)} 条"}
                    ),
                )
            session.flush()
            return self._source_snapshot(session, order, rows)

    def _read(
        self,
        order_id: str,
        actor_id: str,
        version: int,
        detail_ids: list[str] | None,
        *,
        allow_legacy: bool = False,
    ) -> tuple[dict[str, int], dict[str, SourceOrderRow]]:
        # Close this transaction before making any network request.
        with self._session_factory() as session:
            order = self._check(session, actor_id, order_id, version)
            rows = self._details(session, order_id)
            selected = [
                row
                for row in rows
                if row.dispatch_state == "UNASSIGNED"
                and (detail_ids is None or row.detail_id in detail_ids)
            ]
            if not selected or (
                detail_ids is not None and {r.detail_id for r in selected} != set(detail_ids)
            ):
                raise OrderConflict("没有可更新的未派工明细")
            identities = {}
            versions = {}
            legacy = {}
            purchase_links = {}
            for row in selected:
                source = (
                    session.get(OrderImportSourceRecord, row.source_record_pk)
                    if row.source_record_pk
                    else None
                )
                if source is None and row.origin == "legacy" and allow_legacy:
                    legacy[row.detail_id] = SourceOrderRow(
                        row.detail_id,
                        order.order_no,
                        row.source_sku_id,
                        row.product_name,
                        row.properties_value,
                        row.category,
                        row.factory_name,
                        row.order_quantity,
                        row.source_shipped_quantity,
                        None,
                        row.source_tracker,
                        None,
                        row.contract_ship_date,
                        row.accepted_raw_fields,
                    )
                    versions[row.detail_id] = row.version
                    continue
                if source is None or source.source_scope != self._source.source_scope:
                    raise OrderConflict("明细没有可靠的来源关联，不能更新")
                identities[source.source_record_id] = (row.detail_id, source.source_detail_id)
                versions[row.detail_id] = row.version
                if row.purchase_order_id and row.purchase_order_item_id:
                    purchase_links[source.source_record_id] = (
                        row.purchase_order_id,
                        row.purchase_order_item_id,
                    )
            order_no = order.order_no
        fetched = (
            self._source.read_records(list(identities), purchase_links=purchase_links)
            if identities
            else []
        )
        if len(fetched) != len(identities) or {r.record_id for r in fetched} != set(identities):
            raise OrderConflict("来源明细缺失或重复，原资料保持不变")
        result = dict(legacy)
        for fetched_row in fetched:
            detail_id, source_detail_id = identities[fetched_row.record_id]
            if (
                fetched_row.order_no or ""
            ).strip().upper() != order_no or fetched_row.source_detail_id != source_detail_id:
                raise OrderConflict("来源订单号或明细身份变化，原资料保持不变")
            result[detail_id] = fetched_row
        return versions, result

    @staticmethod
    def _values(session: Session, row: SourceOrderRow, detail: OrderDetail) -> dict[str, Any]:
        variant, factory, issues = OrderImportService.match_source_row(session, row)
        purchase_order_id, purchase_order_item_id = OrderImportService.purchase_link_ids(
            row.raw_fields
        )
        if not purchase_order_id or not purchase_order_item_id:
            purchase_order_id = detail.purchase_order_id
            purchase_order_item_id = detail.purchase_order_item_id
        if detail.factory_override_enabled:
            factory = session.get(Factory, detail.matched_factory_id)
            issues = [
                code
                for code in issues
                if code not in {"FACTORY_NOT_MATCHED", "FACTORY_HAS_NO_ENABLED_USER"}
            ]
            if factory is not None and session.scalar(
                select(User.user_id)
                .where(
                    User.factory_id == factory.factory_id,
                    User.role == "factory",
                    User.is_enabled.is_(True),
                )
                .limit(1)
            ) is None:
                issues.append("FACTORY_HAS_NO_ENABLED_USER")
        if detail.origin == "legacy" and detail.source_record_pk is None:
            values = {key: getattr(detail, key) for key in FIELDS}
            return {
                key: value.isoformat() if isinstance(value, date) else value
                for key, value in values.items()
            }
        source_date = row.contract_ship_date
        effective_date = (
            detail.contract_ship_date
            if detail.date_override_enabled
            else (
                source_date - timedelta(days=4)
                if source_date and source_date >= date(1, 1, 5)
                else None
            )
        )
        return {
            "parse_issues": issues,
            "source_sku_id": row.source_sku_id,
            "product_name": row.product_name,
            "properties_value": row.properties_value,
            "category": row.category,
            "factory_name": (
                detail.factory_name if detail.factory_override_enabled else row.factory_name
            ),
            "matched_variant_id": variant.variant_id if variant else None,
            "matched_factory_id": factory.factory_id if factory else None,
            "order_quantity": OrderImportService._quantity(row.order_quantity, minimum=1),
            "source_shipped_quantity": (
                detail.source_shipped_quantity
                if detail.shipped_override_enabled
                else OrderImportService._quantity(row.shipped_quantity)
            ),
            "source_tracker": row.tracker,
            "source_trackers": list(
                row.trackers or ((row.tracker,) if row.tracker else ())
            ),
            "source_contract_ship_date": source_date.isoformat() if source_date else None,
            "contract_ship_date": effective_date.isoformat() if effective_date else None,
            "accepted_raw_fields": row.raw_fields,
            "purchase_order_id": purchase_order_id,
            "purchase_order_item_id": purchase_order_item_id,
            "accepted_source_hash": _hash(row.raw_fields),
            "accepted_source_modified_at": row.source_modified_at.isoformat()
            if row.source_modified_at
            else None,
        }

    def preview(
        self,
        *,
        actor_id: str,
        order_id: str,
        version: int,
        request_id: str,
        detail_ids: list[str] | None = None,
        allow_legacy: bool = False,
    ) -> dict[str, Any]:
        versions, fetched = self._read(
            order_id, actor_id, version, detail_ids, allow_legacy=allow_legacy
        )
        with self._session_factory() as session, session.begin():
            self._check(session, actor_id, order_id, version, lock=True)
            rows = self._details(session, order_id, lock=True)
            updates, differences = {}, []
            for detail in sorted(rows, key=lambda row: (row.sort_order, row.detail_id)):
                if detail.detail_id not in fetched:
                    continue
                if (
                    detail.version != versions[detail.detail_id]
                    or detail.dispatch_state != "UNASSIGNED"
                ):
                    raise OrderConflict("明细已变化，请重新检查来源")
                values = self._values(session, fetched[detail.detail_id], detail)
                updates[detail.detail_id] = values
                for key, label in FIELDS.items():
                    if self._protected(detail, key):
                        continue
                    before = getattr(detail, key)
                    after = values[key]
                    if isinstance(before, date):
                        before = before.isoformat()
                    raw_key = RAW_FIELDS.get(key)
                    if raw_key:
                        if before is None:
                            before = AppCredentialFeishuOrderSource._text(
                                detail.accepted_raw_fields.get(raw_key)
                            )
                        if after is None:
                            after = AppCredentialFeishuOrderSource._text(
                                fetched[detail.detail_id].raw_fields.get(raw_key)
                            )
                    if before != after:
                        if key in {"matched_variant_id", "matched_factory_id"}:
                            before = "已匹配" if before else "未匹配"
                            after = "已匹配" if after else "未匹配"
                        differences.append(
                            {
                                "detail_id": detail.detail_id,
                                "label": (
                                    f"第{detail.sort_order}条 · {detail.properties_value or '—'}"
                                ),
                                "field": label,
                                "before": before,
                                "after": after,
                            }
                        )
            now = self._now()
            preview = OrderChangePreview(
                preview_id=str(uuid4()),
                order_id=order_id,
                actor_id=actor_id,
                version=version,
                created_at=now,
                expires_at=now + timedelta(minutes=5),
                payload={
                    "kind": "refresh",
                    "versions": versions,
                    "updates": updates,
                    "differences": differences,
                },
            )
            session.add(preview)
            return {
                "preview_id": preview.preview_id,
                "version": version,
                "expires_at": preview.expires_at,
                "differences": differences,
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
        if not idempotency_key.strip() or len(idempotency_key) > 191:
            raise OrderConflict("请提供有效的幂等标识")
        scope = f"order.refresh:{actor_id}:{order_id}"
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
                    raise OrderConflict("同一幂等标识不能用于不同更新")
                return SNAPSHOT.validate_python(repeated.result)
            pending = session.get(OrderChangePreview, preview_id)
            if (
                pending is None
                or pending.order_id != order_id
                or pending.actor_id != actor_id
                or pending.version != version
                or pending.consumed_at is not None
                or pending.expires_at <= self._now()
                or pending.payload.get("kind") != "refresh"
            ):
                raise OrderConflict("来源预览已失效，请重新检查来源")
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
                    raise OrderConflict("同一幂等标识不能用于不同更新")
                return SNAPSHOT.validate_python(repeated.result)
            self._check(session, actor_id, order_id, version)
            preview = session.get(OrderChangePreview, preview_id)
            if (
                preview is None
                or preview.order_id != order_id
                or preview.actor_id != actor_id
                or preview.version != version
                or preview.consumed_at is not None
                or preview.expires_at <= self._now()
                or preview.payload.get("kind") != "refresh"
            ):
                raise OrderConflict("来源预览已失效，请重新检查来源")
            rows = self._details(session, order_id, lock=True)
            selected = {
                row.detail_id: row for row in rows if row.detail_id in preview.payload["updates"]
            }
            if set(selected) != set(preview.payload["versions"]):
                raise OrderConflict("来源明细集合已变化")
            for detail_id, detail in selected.items():
                if (
                    detail.version != preview.payload["versions"][detail_id]
                    or detail.dispatch_state != "UNASSIGNED"
                ):
                    raise OrderConflict("明细版本或派工状态已变化，请重新检查")
                for key, value in preview.payload["updates"][detail_id].items():
                    if key in {"contract_ship_date", "source_contract_ship_date"}:
                        value = _date(value)
                    elif key == "accepted_source_modified_at":
                        value = datetime.fromisoformat(value) if value else None
                    setattr(detail, key, value)
                detail.version += 1
                detail.updated_at = self._now()
            if order.tracker_locked_at is None:
                trackers = list(dict.fromkeys(
                    tracker
                    for row in sorted(rows, key=lambda item: (item.sort_order, item.detail_id))
                    for tracker in (
                        row.source_trackers or ([row.source_tracker] if row.source_tracker else [])
                    )
                    if tracker in TRACKERS
                ))
                order.trackers = trackers
                order.tracker = trackers[0] if trackers else None
            self._touch(order, actor_id)
            preview.consumed_at = self._now()
            self._add_audit(
                session,
                request_id=request_id,
                action="order.source_refreshed",
                order_id=order_id,
                actor_id=actor_id,
                changes={
                    "previewId": preview_id,
                    "differences": preview.payload["differences"],
                    "sources": preview.payload["updates"],
                    "protectedDates": [
                        row.detail_id for row in selected.values() if row.date_override_enabled
                    ],
                },
            )
            session.flush()
            result = self._source_snapshot(session, order, rows)
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

    @staticmethod
    def _protected(detail: OrderDetail, key: str) -> bool:
        return (
            (key == "contract_ship_date" and detail.date_override_enabled)
            or (key in {"factory_name", "matched_factory_id"} and detail.factory_override_enabled)
            or (key == "source_shipped_quantity" and detail.shipped_override_enabled)
        )

    def _touch(self, order: Order, actor_id: str) -> None:
        order.version += 1
        order.updated_by = actor_id
        order.updated_at = self._now()
