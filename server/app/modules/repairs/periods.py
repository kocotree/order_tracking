from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import (
    AuditLog,
    Factory,
    OutboxMessage,
    RepairInspectionLine,
    RepairOrder,
    RepairPeriod,
    RepairPeriodBatch,
    RepairPeriodDraft,
    RepairReturnBatch,
    RepairReturnLine,
    StoredFile,
    User,
)
from app.db.natural_sort import natural_sort_keys
from app.modules.repairs.confirmation import (
    BUSINESS_TIME_ZONE,
    RepairOrderView,
    RepairReturnBatchView,
    RepairReturnLineView,
    RepairSpecView,
)
from app.modules.repairs.returns import (
    RepairArchiveView,
    RepairDraftView,
    RepairReturnConflict,
    RepairReturnLineInput,
    RepairReturnNotFound,
    RepairReturnService,
    RepairReturnValidationError,
)

"""Factory half-year periods; source inspection sheets remain independent facts."""


def period_bounds(day: date) -> tuple[date, date, str]:
    if 2 <= day.month <= 7:
        return date(day.year, 2, 1), date(day.year, 7, 31), f"{day.year}.2-{day.year}.7"
    year = day.year - (day.month == 1)
    return date(year, 8, 1), date(year + 1, 1, 31), f"{year}.8-{year + 1}.1"


@dataclass(frozen=True)
class RepairAttachmentView:
    file_id: int
    filename: str
    size_bytes: int


@dataclass(frozen=True)
class RepairPeriodView(RepairOrderView):
    attachments: tuple[RepairAttachmentView, ...]


def attach_period(session: Session, factory_id: str, day: date) -> str:
    """Caller holds the factory row lock, shared with archive and return operations."""
    start, end, label = period_bounds(day)
    period = session.scalar(
        select(RepairPeriod)
        .where(RepairPeriod.factory_id == factory_id, RepairPeriod.start_date == start)
        .with_for_update()
    )
    if period is None:
        period = RepairPeriod(
            period_id=str(uuid4()),
            factory_id=factory_id,
            start_date=start,
            end_date=end,
            label=label,
        )
        session.add(period)
        session.flush()
    if period.archived_at is not None:
        raise RepairReturnConflict("该返修周期已归档，不能继续创建质检单")
    return period.period_id


def attachment_names(orders: Sequence[RepairOrder]) -> dict[int, str]:
    groups: dict[date, list[RepairOrder]] = defaultdict(list)
    for order in orders:
        groups[order.return_date].append(order)
    names = {}
    for day, group in groups.items():
        for index, order in enumerate(sorted(group, key=lambda x: (x.created_at, x.repair_no)), 1):
            suffix = f"-{index:02d}" if len(group) > 1 else ""
            names[order.original_file_id] = f"{day.isoformat()}{suffix}.xlsx"
    return names


class RepairPeriodService:
    def __init__(
        self,
        sessions: sessionmaker[Session],
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._session_factory = sessions
        self._clock = clock

    def resolve(self, session: Session, identifier: str) -> RepairPeriod:
        period = session.get(RepairPeriod, identifier)
        if period is None:
            source = session.get(RepairOrder, identifier)
            period = (
                session.get(RepairPeriod, source.period_id) if source and source.period_id else None
            )
        if period is None:
            raise RepairReturnNotFound("返修周期不存在")
        return period

    def _lock(self, session: Session, identifier: str) -> RepairPeriod:
        period = self.resolve(session, identifier)
        session.scalar(
            select(Factory).where(Factory.factory_id == period.factory_id).with_for_update()
        )
        return session.scalars(
            select(RepairPeriod)
            .where(RepairPeriod.period_id == period.period_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).one()

    def page(
        self,
        *,
        factory_id: str | None = None,
        keyword: str = "",
        status: str = "all",
        factories: list[str] | None = None,
        period: str = "",
        sort_by: str = "",
        sort_order: str = "asc",
        page: int = 1,
        page_size: int = 10,
    ) -> tuple[list[dict[str, Any]], int]:
        totals = (
            select(
                RepairOrder.period_id.label("id"),
                *[
                    func.sum(getattr(RepairOrder, f)).label(f)
                    for f in (
                        "warehouse_return_quantity",
                        "repaired_quantity",
                        "scrapped_quantity",
                        "returned_quantity",
                    )
                ],
            )
            .where(RepairOrder.period_id.is_not(None))
            .group_by(RepairOrder.period_id)
            .subquery()
        )
        state = case(
            (totals.c.returned_quantity == totals.c.warehouse_return_quantity, "COMPLETED"),
            else_="INCOMPLETE",
        )
        query = (
            select(
                RepairPeriod.period_id.label("repair_id"),
                RepairPeriod.label.label("repair_no"),
                RepairPeriod.start_date.label("return_date"),
                RepairPeriod.factory_id,
                Factory.factory_name,
                state.label("status"),
                totals.c.warehouse_return_quantity,
                totals.c.repaired_quantity,
                totals.c.scrapped_quantity,
                totals.c.returned_quantity,
            )
            .join(totals, totals.c.id == RepairPeriod.period_id)
            .join(Factory, Factory.factory_id == RepairPeriod.factory_id)
            .where(RepairPeriod.archived_at.is_(None))
        )
        if factory_id:
            query = query.where(RepairPeriod.factory_id == factory_id)
        if keyword.strip():
            query = query.where(
                func.lower(func.concat(RepairPeriod.label, " ", Factory.factory_name))
                .collate("utf8mb4_0900_bin")
                .contains(keyword.strip().lower(), autoescape=True)
            )
        if status != "all":
            query = query.where(state.collate("utf8mb4_0900_bin") == status)
        if factories:
            query = query.where(Factory.factory_name.collate("utf8mb4_0900_bin").in_(factories))
        if period:
            query = query.where(RepairPeriod.label == period)
        fields = dict(
            repairNo=RepairPeriod.start_date,
            factoryName=Factory.factory_name,
            status=state,
            repairedQuantity=totals.c.repaired_quantity,
            scrappedQuantity=totals.c.scrapped_quantity,
            returnedQuantity=totals.c.returned_quantity,
            warehouseReturnQuantity=totals.c.warehouse_return_quantity,
        )
        count_query = select(func.count()).select_from(query.subquery())
        order = []
        if sort_by == "factoryName":
            keys = natural_sort_keys(
                query.with_only_columns(
                    RepairPeriod.period_id.label("id"), Factory.factory_name.label("value")
                ),
                name="period_sort",
            )
            query = query.join(keys, keys.c.id == RepairPeriod.period_id)
            order.append(keys.c.sort_key.desc() if sort_order == "desc" else keys.c.sort_key.asc())
        elif sort_by in fields:
            field = fields[sort_by]
            order.append(field.desc() if sort_order == "desc" else field.asc())
        order.extend([RepairPeriod.start_date.desc(), RepairPeriod.period_id.desc()])
        with self._session_factory() as session:
            total = session.scalar(count_query) or 0
            rows = session.execute(
                query.prefix_with(
                    "/*+ SET_VAR(cte_max_recursion_depth=1000000) "
                    "SET_VAR(max_sort_length=8388608) */"
                )
                .order_by(*order)
                .offset((page - 1) * page_size)
                .limit(page_size)
            ).mappings()
            return [dict(row) for row in rows], total

    def get(self, repair_id: str, *, include_history: bool = True) -> RepairPeriodView:
        with self._session_factory() as session:
            period = self.resolve(session, repair_id)
            if period.archived_at is not None:
                raise RepairReturnNotFound("返修周期不存在")
            sources = session.scalars(
                select(RepairOrder)
                .where(RepairOrder.period_id == period.period_id)
                .order_by(RepairOrder.created_at, RepairOrder.repair_no, RepairOrder.repair_id)
            ).all()
            if not sources:
                raise RepairReturnNotFound("返修周期不存在")
            ids = [source.repair_id for source in sources]
            files = {
                f.file_id: f
                for f in session.scalars(
                    select(StoredFile).where(
                        StoredFile.file_id.in_([o.original_file_id for o in sources])
                    )
                )
            }
            names = attachment_names(sources)
            attachments = tuple(
                RepairAttachmentView(
                    o.original_file_id,
                    names[o.original_file_id],
                    files[o.original_file_id].size_bytes,
                )
                for o in sources
            )
            inspection = session.scalars(
                select(RepairInspectionLine)
                .where(RepairInspectionLine.repair_id.in_(ids))
                .order_by(RepairInspectionLine.inspection_line_id)
            ).all()
            quantities: dict[str, list[int]] = {}
            metadata: dict[str, RepairInspectionLine] = {}
            for line in inspection:
                metadata.setdefault(line.variant_id, line)
                quantities.setdefault(line.variant_id, [0, 0, 0])[0] += (
                    line.warehouse_return_quantity
                )
            returned = session.execute(
                select(
                    RepairReturnLine.variant_id,
                    func.sum(RepairReturnLine.repaired_quantity),
                    func.sum(RepairReturnLine.scrapped_quantity),
                )
                .join(RepairReturnBatch, RepairReturnBatch.batch_id == RepairReturnLine.batch_id)
                .where(RepairReturnBatch.repair_id.in_(ids))
                .group_by(RepairReturnLine.variant_id)
            ).all()
            for variant, repaired, scrapped in returned:
                quantities[variant][1:] = [int(repaired), int(scrapped)]
            specs = tuple(
                RepairSpecView(
                    variant,
                    metadata[variant].source_sku_id,
                    metadata[variant].source_product_id,
                    metadata[variant].product_name,
                    metadata[variant].properties_value,
                    q[0],
                    q[1],
                    q[2],
                    q[1] + q[2],
                    q[0] - q[1] - q[2],
                )
                for variant, q in quantities.items()
            )
            batches: list[RepairReturnBatchView] = []
            if include_history:
                history = session.execute(
                    select(RepairReturnBatch, RepairReturnLine)
                    .join(RepairReturnLine, RepairReturnLine.batch_id == RepairReturnBatch.batch_id)
                    .where(RepairReturnBatch.repair_id.in_(ids))
                    .order_by(
                        RepairReturnBatch.submitted_at.desc(),
                        RepairReturnBatch.batch_id.desc(),
                        RepairReturnLine.line_order,
                    )
                ).all()
                grouped: dict[str, dict[str, list[int]]] = {}
                headers = {}
                for batch, line in history:
                    key = batch.period_batch_id or batch.batch_id
                    headers[key] = batch
                    q = grouped.setdefault(key, {}).setdefault(line.variant_id, [0, 0])
                    q[0] += line.repaired_quantity
                    q[1] += line.scrapped_quantity
                for key, variants in grouped.items():
                    header = headers[key]
                    batches.append(
                        RepairReturnBatchView(
                            key,
                            header.submitted_at,
                            header.submitted_at.replace(tzinfo=UTC)
                            .astimezone(BUSINESS_TIME_ZONE)
                            .date(),
                            header.submitted_by,
                            tuple(
                                RepairReturnLineView(
                                    v,
                                    metadata[v].source_sku_id,
                                    metadata[v].source_product_id,
                                    metadata[v].product_name,
                                    metadata[v].properties_value,
                                    quantities[v][0],
                                    q[0],
                                    q[1],
                                    sum(q),
                                )
                                for v, q in variants.items()
                            ),
                        )
                    )
            warehouse = sum(o.warehouse_return_quantity for o in sources)
            repaired = sum(o.repaired_quantity for o in sources)
            scrapped = sum(o.scrapped_quantity for o in sources)
            factory = session.get(Factory, period.factory_id)
            assert factory is not None
            return RepairPeriodView(
                period.period_id,
                period.label,
                "COMPLETED" if repaired + scrapped == warehouse else "INCOMPLETE",
                period.start_date,
                period.factory_id,
                warehouse,
                repaired,
                scrapped,
                repaired + scrapped,
                attachments[0].file_id,
                attachments[0].filename,
                attachments[0].size_bytes,
                factory.factory_name,
                sources[0].created_at,
                (),
                specs,
                tuple(batches),
                attachments,
            )

    def submit(
        self,
        *,
        repair_id: str,
        factory_id: str,
        submitted_by: str,
        idempotency_key: str,
        lines: Sequence[RepairReturnLineInput],
        draft_version: int | None = None,
    ) -> RepairPeriodView:
        RepairReturnService._validate_lines(lines)
        key = idempotency_key.strip()
        if not key or len(key) > 191:
            raise RepairReturnValidationError("无效的幂等键")
        now = self._clock().astimezone(UTC).replace(tzinfo=None)
        with self._session_factory() as session, session.begin():
            period = self._lock(session, repair_id)
            period_id = period.period_id
            self._factory_actor(session, period, factory_id, submitted_by)
            digest = RepairReturnService._request_sha256(period_id, lines)
            existing = session.scalar(
                select(RepairPeriodBatch)
                .where(
                    RepairPeriodBatch.submitted_by == submitted_by,
                    RepairPeriodBatch.idempotency_key == key,
                )
                .with_for_update()
            )
            if existing:
                if existing.period_id != period_id or existing.request_sha256 != digest:
                    raise RepairReturnConflict("同一幂等键不能用于不同的发回内容")
            else:
                sources = session.scalars(
                    select(RepairOrder)
                    .where(RepairOrder.period_id == period_id)
                    .order_by(RepairOrder.created_at, RepairOrder.repair_no, RepairOrder.repair_id)
                    .with_for_update()
                ).all()
                if all(o.returned_quantity == o.warehouse_return_quantity for o in sources):
                    raise RepairReturnConflict("已完成返修周期不能继续发回")
                draft = session.get(
                    RepairPeriodDraft, (period_id, submitted_by), with_for_update=True
                )
                if draft_version is not None and (
                    draft is None or draft.version != draft_version or draft.submission_key != key
                ):
                    raise RepairReturnConflict("草稿已变化，请重新进入核对")
                ids = [o.repair_id for o in sources]
                balances = {
                    (r, v): int(q)
                    for r, v, q in session.execute(
                        select(
                            RepairInspectionLine.repair_id,
                            RepairInspectionLine.variant_id,
                            func.sum(RepairInspectionLine.warehouse_return_quantity),
                        )
                        .where(RepairInspectionLine.repair_id.in_(ids))
                        .group_by(RepairInspectionLine.repair_id, RepairInspectionLine.variant_id)
                        .with_for_update()
                    )
                }
                for r, v, q in session.execute(
                    select(
                        RepairReturnBatch.repair_id,
                        RepairReturnLine.variant_id,
                        func.sum(
                            RepairReturnLine.repaired_quantity + RepairReturnLine.scrapped_quantity
                        ),
                    )
                    .join(RepairReturnLine, RepairReturnLine.batch_id == RepairReturnBatch.batch_id)
                    .where(RepairReturnBatch.repair_id.in_(ids))
                    .group_by(RepairReturnBatch.repair_id, RepairReturnLine.variant_id)
                    .with_for_update()
                ):
                    balances[(r, v)] -= int(q)
                allocations: dict[str, list[RepairReturnLineInput]] = defaultdict(list)
                for line in lines:
                    if not any(v == line.variant_id for _, v in balances):
                        raise RepairReturnValidationError("返修规格不存在")
                    repaired, scrapped = line.repaired_quantity, line.scrapped_quantity
                    for source in sources:
                        remaining = balances.get((source.repair_id, line.variant_id), 0)
                        a = min(remaining, repaired)
                        b = min(remaining - a, scrapped)
                        if a + b:
                            allocations[source.repair_id].append(
                                RepairReturnLineInput(line.variant_id, a, b)
                            )
                        repaired -= a
                        scrapped -= b
                    if repaired + scrapped:
                        raise RepairReturnConflict("返修进度已变化，请重新核对")
                batch_id = str(uuid4())
                session.add(
                    RepairPeriodBatch(
                        batch_id=batch_id,
                        period_id=period_id,
                        submitted_by=submitted_by,
                        submitted_at=now,
                        idempotency_key=key,
                        request_sha256=digest,
                    )
                )
                session.flush()
                first_child = ""
                for source in sources:
                    allocated = allocations.get(source.repair_id, [])
                    if not allocated:
                        continue
                    child_id = str(uuid4())
                    if not first_child:
                        first_child = child_id
                    session.add(
                        RepairReturnBatch(
                            batch_id=child_id,
                            repair_id=source.repair_id,
                            period_batch_id=batch_id,
                            submitted_by=submitted_by,
                            submitted_at=now,
                            idempotency_key=child_id,
                            request_sha256=digest,
                            created_at=now,
                        )
                    )
                    session.flush()
                    for index, line in enumerate(allocated, 1):
                        session.add(
                            RepairReturnLine(
                                batch_id=child_id,
                                line_order=index,
                                variant_id=line.variant_id,
                                repaired_quantity=line.repaired_quantity,
                                scrapped_quantity=line.scrapped_quantity,
                                created_at=now,
                            )
                        )
                    source.repaired_quantity += sum(x.repaired_quantity for x in allocated)
                    source.scrapped_quantity += sum(x.scrapped_quantity for x in allocated)
                    source.returned_quantity = source.repaired_quantity + source.scrapped_quantity
                    source.status = (
                        "COMPLETED"
                        if source.returned_quantity == source.warehouse_return_quantity
                        else "INCOMPLETE"
                    )
                    source.updated_at = now
                if draft:
                    draft.entries = []
                    draft.version += 1
                    draft.submission_key = str(uuid4())
                session.add(
                    AuditLog(
                        request_id=key[:64],
                        action="repair_period_return_submitted",
                        target_type="repair_period",
                        target_id=period_id,
                        changes={
                            "batchId": batch_id,
                            "sourceIds": list(allocations),
                            "repairedQuantity": sum(x.repaired_quantity for x in lines),
                            "scrappedQuantity": sum(x.scrapped_quantity for x in lines),
                        },
                        actor_id=submitted_by,
                        source_terminal="factory-mini",
                    )
                )
                # One event per physical batch; the notification reader resolves the period.
                session.add(
                    OutboxMessage(
                        event_type="repair.return_submitted",
                        aggregate_type="repair",
                        aggregate_id=next(iter(allocations)),
                        dedupe_key=f"repair-period:{batch_id}",
                        payload={
                            "repairId": next(iter(allocations)),
                            "batchId": first_child,
                            "periodId": period_id,
                            "periodBatchId": batch_id,
                        },
                        status="pending",
                        available_at=now,
                    )
                )
        return self.get(period_id)

    @staticmethod
    def _factory_actor(
        session: Session, period: RepairPeriod, factory_id: str, user_id: str
    ) -> None:
        user = session.get(User, user_id)
        if (
            period.archived_at is not None
            or period.factory_id != factory_id
            or user is None
            or not user.is_enabled
            or user.role != "factory"
            or user.factory_id != factory_id
        ):
            raise RepairReturnNotFound("返修周期不存在")

    def get_draft(self, *, repair_id: str, factory_id: str, user_id: str) -> RepairDraftView:
        with self._session_factory() as session, session.begin():
            repair_id = self._draft_repair(session, repair_id, factory_id, user_id).period_id
            draft = session.get(RepairPeriodDraft, (repair_id, user_id), with_for_update=True)
            return (
                RepairDraftView(draft.version, draft.entries, draft.submission_key)
                if draft
                else RepairDraftView(0, [], "")
            )

    def save_draft(
        self,
        *,
        repair_id: str,
        factory_id: str,
        user_id: str,
        version: int,
        entries: list[dict[str, Any]],
    ) -> RepairDraftView:
        if type(version) is not int or version < 0 or len(entries) > 1000:
            raise RepairReturnValidationError("无效草稿")
        seen: set[str] = set()
        for entry in entries:
            if (
                set(entry) != {"variantId", "selected", "repaired", "scrapped"}
                or not isinstance(entry["variantId"], str)
                or entry["variantId"] in seen
                or type(entry["selected"]) is not bool
                or any(
                    not isinstance(entry[field], str) or len(entry[field]) > 32
                    for field in ("repaired", "scrapped")
                )
            ):
                raise RepairReturnValidationError("无效草稿规格")
            seen.add(entry["variantId"])
        with self._session_factory() as session, session.begin():
            repair_id = self._draft_repair(session, repair_id, factory_id, user_id).period_id
            variants = set(
                session.scalars(
                    select(RepairInspectionLine.variant_id).where(
                        RepairInspectionLine.repair_id.in_(
                            select(RepairOrder.repair_id).where(RepairOrder.period_id == repair_id)
                        )
                    )
                )
            )
            if not seen.issubset(variants):
                raise RepairReturnValidationError("返修规格不存在")
            draft = session.get(RepairPeriodDraft, (repair_id, user_id), with_for_update=True)
            current_version = draft.version if draft else 0
            if version != current_version:
                # Retry after a lost successful response is safe only for the same content.
                if draft and entries and version + 1 == draft.version and entries == draft.entries:
                    return RepairDraftView(draft.version, draft.entries, draft.submission_key)
                raise RepairReturnConflict("草稿已在其他页面更新，请重新进入核对")
            if draft is None:
                draft = RepairPeriodDraft(
                    repair_id=repair_id,
                    user_id=user_id,
                    version=0,
                    entries=[],
                    submission_key=str(uuid4()),
                )
                session.add(draft)
            draft.entries = entries
            draft.version += 1
            session.flush()
            return RepairDraftView(draft.version, draft.entries, draft.submission_key)

    def _draft_repair(
        self, session: Session, repair_id: str, factory_id: str, user_id: str
    ) -> RepairPeriod:
        period = self._lock(session, repair_id)
        self._factory_actor(session, period, factory_id, user_id)
        pending = session.scalar(
            select(func.sum(RepairOrder.warehouse_return_quantity - RepairOrder.returned_quantity))
            .where(RepairOrder.period_id == period.period_id)
            .with_for_update()
        )
        if not pending:
            raise RepairReturnConflict("已完成返修周期不能继续填写")
        return period

    def archive(
        self, *, repair_id: str, archived_by: str, idempotency_key: str
    ) -> RepairArchiveView:
        from app.db.models import IdempotencyRecord

        key = idempotency_key.strip()
        if not key or len(key) > 191:
            raise RepairReturnValidationError("无效的幂等键")
        now = self._clock().astimezone(UTC).replace(tzinfo=None)
        with self._session_factory() as session, session.begin():
            period = self._lock(session, repair_id)
            actor = session.get(User, archived_by)
            if actor is None or not actor.is_enabled or actor.role != "admin":
                raise RepairReturnNotFound("返修周期不存在")
            scope = f"period.archive:{period.period_id}"
            existing = session.scalar(
                select(IdempotencyRecord)
                .where(IdempotencyRecord.scope == scope, IdempotencyRecord.idempotency_key == key)
                .with_for_update()
            )
            if period.archived_at is not None:
                if existing:
                    return RepairArchiveView(
                        period.period_id, period.archived_at, period.archived_by or archived_by
                    )
                raise RepairReturnConflict("返修周期已归档")
            sources = session.scalars(
                select(RepairOrder)
                .where(RepairOrder.period_id == period.period_id)
                .with_for_update()
            ).all()
            if not sources or any(
                o.returned_quantity != o.warehouse_return_quantity for o in sources
            ):
                raise RepairReturnConflict("只有已完成的返修周期可以归档")
            period.archived_at, period.archived_by = now, archived_by
            for source in sources:
                source.archived_at, source.archived_by = now, archived_by
            session.add(IdempotencyRecord(scope=scope, idempotency_key=key, status="completed"))
            session.add(
                AuditLog(
                    request_id=key[:64],
                    action="repair_period_archived",
                    target_type="repair_period",
                    target_id=period.period_id,
                    changes={"sourceIds": [o.repair_id for o in sources]},
                    actor_id=archived_by,
                    source_terminal="admin-web",
                )
            )
            return RepairArchiveView(period.period_id, now, archived_by)
