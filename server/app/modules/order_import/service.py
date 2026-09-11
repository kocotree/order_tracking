import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
from typing import Any
from uuid import uuid4

from sqlalchemy import delete, false, func, literal_column, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.sql.elements import ColumnElement

from app.db.models import (
    AuditLog,
    BackgroundJob,
    Factory,
    Order,
    OrderDetail,
    OrderImportCandidate,
    OrderImportCandidateLine,
    OrderImportRun,
    OrderImportSourceCursor,
    OrderImportSourceRecord,
    OrderImportValidationIssue,
    Product,
    ProductVariant,
    User,
)
from app.modules.orders.service import TRACKERS

ACTIVE_KEY = "feishu-order-import"
LOCAL_DEPENDENCY_ISSUES = frozenset(
    {
        "PRODUCT_VARIANT_NOT_MATCHED",
        "FACTORY_NOT_MATCHED",
        "FACTORY_HAS_NO_ENABLED_USER",
    }
)


# Python casefold is broader than MySQL LOWER (for example ß -> ss and ς -> σ).
# Fold only characters that can contribute to the search term, inside SQL.
_CASEFOLD_CHANGES = tuple(
    (character, character.casefold())
    for character in map(chr, range(0x110000))
    if character != character.casefold()
)


@dataclass(frozen=True)
class ImportRunSnapshot:
    run_id: str
    status: str
    started_at: datetime
    finished_at: datetime | None
    pages_read: int
    records_read: int
    candidates_created: int
    candidates_updated: int
    skipped_records: int
    failed_records: int
    error_code: str | None


@dataclass(frozen=True)
class CandidateLineSnapshot:
    candidate_line_id: int
    contract_ship_date: date | None
    source_contract_ship_date: date | None
    source_sku_id: str | None
    product_name: str | None
    properties_value: str | None
    category: str | None
    factory_name: str | None
    order_quantity: int | None
    shipped_quantity: int | None
    pending_quantity: int | None
    validation_issues: list[str]


@dataclass(frozen=True)
class CandidateSnapshot:
    candidate_id: str
    version: int
    contract_ship_dates: list[date]
    order_no: str
    status: str
    validation_state: str
    validation_issues: list[str]
    order_date: date | None
    tracker: str | None
    contract_ship_date: date | None
    category: str | None
    total_quantity: int | None
    shipped_quantity: int | None
    pending_quantity: int | None
    imported_order_id: str | None
    lines: list[CandidateLineSnapshot]
    updated_at: datetime


@dataclass(frozen=True)
class BatchConfirmItem:
    candidate_id: str
    succeeded: bool
    order_id: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class RevalidationSnapshot:
    checked_candidates: int
    updated_candidates: int


@dataclass(frozen=True)
class SourceOrderRow:
    record_id: str
    order_no: str | None
    source_sku_id: str | None
    product_name: str | None
    properties_value: str | None
    category: str | None
    factory_name: str | None
    order_quantity: int | None
    shipped_quantity: int | None
    pending_quantity: int | None
    tracker: str | None
    order_date: date | None
    contract_ship_date: date | None
    raw_fields: dict[str, object]
    source_detail_id: str | None = None
    source_modified_at: datetime | None = None


class OrderImportService:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock

    def create_or_reuse_run(
        self, *, actor_id: str, request_id: str, idempotency_key: str | None = None
    ) -> ImportRunSnapshot:
        now = self._clock().replace(tzinfo=None)
        run_id = str(uuid4())
        try:
            with self._session_factory() as session, session.begin():
                actor = session.get(User, actor_id)
                if actor is None or actor.role != "admin" or not actor.is_enabled:
                    raise PermissionError("enabled admin required")
                if idempotency_key:
                    repeated = session.scalar(
                        select(OrderImportRun).where(
                            OrderImportRun.idempotency_key == idempotency_key
                        )
                    )
                    if repeated is not None:
                        return self._snapshot(repeated)
                active = session.scalar(
                    select(OrderImportRun).where(OrderImportRun.active_key == ACTIVE_KEY)
                )
                if active is not None:
                    return self._snapshot(active)
                run = OrderImportRun(
                    run_id=run_id,
                    status="PENDING",
                    active_key=ACTIVE_KEY,
                    started_at=now,
                    requested_by=actor_id,
                    request_id=request_id,
                    idempotency_key=idempotency_key,
                    created_at=now,
                )
                session.add(run)
                session.add(
                    BackgroundJob(
                        job_type="order_import",
                        dedupe_key=run_id,
                        payload={"runId": run_id},
                        status="pending",
                        available_at=now,
                        created_at=now,
                        updated_at=now,
                    )
                )
                session.add(
                    AuditLog(
                        request_id=request_id,
                        action="order_import.run_created",
                        target_type="order_import_run",
                        target_id=run_id,
                        changes={},
                        actor_id=actor_id,
                        source_terminal="web_admin",
                        created_at=now,
                    )
                )
                session.flush()
                return self._snapshot(run)
        except IntegrityError:
            with self._session_factory() as session:
                active = session.scalar(
                    select(OrderImportRun).where(OrderImportRun.active_key == ACTIVE_KEY)
                )
                if active is None:
                    raise
                return self._snapshot(active)

    def process_run(
        self,
        *,
        run_id: str,
        rows: list[SourceOrderRow],
        pages_read: int,
        source_scope: str = "feishu-production-orders",
        finalize: bool = True,
    ) -> ImportRunSnapshot:
        now = self._clock().replace(tzinfo=None)
        with self._session_factory() as session, session.begin():
            run = session.get(OrderImportRun, run_id)
            if run is None or run.active_key != ACTIVE_KEY:
                raise ValueError("active import run not found")
            run.status = "RUNNING"
            affected_order_nos: set[str] = set()
            accepted_by_order: dict[str, int] = {}
            seen_record_ids: set[str] = set()
            skipped = 0
            failed = 0
            for row in rows:
                normalized_order_no = (row.order_no or "").strip().upper() or None
                if normalized_order_no and len(normalized_order_no) > 100:
                    normalized_order_no = None
                if not row.record_id.strip() or len(row.record_id) > 100:
                    failed += 1
                    continue
                if row.record_id in seen_record_ids:
                    skipped += 1
                    continue
                seen_record_ids.add(row.record_id)
                source = session.scalar(
                    select(OrderImportSourceRecord).where(
                        OrderImportSourceRecord.source_scope == source_scope,
                        OrderImportSourceRecord.source_record_id == row.record_id,
                    )
                )
                if source is not None and source.last_seen_run_id == run_id:
                    skipped += 1
                    continue
                existing_order_no = source.order_no if source is not None else None
                if any(
                    self._order_is_frozen(session, order_no)
                    for order_no in {existing_order_no, normalized_order_no}
                    if order_no is not None
                ):
                    skipped += 1
                    continue
                normalized_fields = self._normalized_source_fields(row)
                if source is None:
                    source = OrderImportSourceRecord(
                        source_scope=source_scope,
                        source_record_id=row.record_id,
                        source_detail_id=row.source_detail_id,
                        order_no=normalized_order_no,
                        raw_fields=row.raw_fields,
                        normalized_fields=normalized_fields,
                        source_modified_at=row.source_modified_at,
                        parse_status="PARSED",
                        first_seen_run_id=run_id,
                        last_seen_run_id=run_id,
                        first_seen_at=now,
                        last_seen_at=now,
                    )
                    session.add(source)
                    session.flush()
                else:
                    if (
                        source.source_modified_at is not None
                        and row.source_modified_at is not None
                        and (
                            row.source_modified_at < source.source_modified_at
                            or (
                                row.source_modified_at == source.source_modified_at
                                and (source.normalized_fields or {}).get(
                                    "contractDateMappingVersion"
                                )
                                == 3
                            )
                        )
                    ):
                        skipped += 1
                        continue
                    if (
                        source.normalized_fields == normalized_fields
                        and source.raw_fields == row.raw_fields
                    ):
                        source.source_detail_id = row.source_detail_id
                        source.raw_fields = row.raw_fields
                        source.source_modified_at = row.source_modified_at
                        source.last_seen_run_id = run_id
                        source.last_seen_at = now
                        skipped += 1
                        continue
                    source.order_no = normalized_order_no
                    source.source_detail_id = row.source_detail_id
                    source.raw_fields = row.raw_fields
                    source.normalized_fields = normalized_fields
                    source.source_modified_at = row.source_modified_at
                    source.parse_status = "PARSED"
                    source.last_seen_run_id = run_id
                    source.last_seen_at = now
                affected_order_nos.update(
                    order_no
                    for order_no in (existing_order_no, normalized_order_no)
                    if order_no is not None
                )
                if normalized_order_no is None:
                    failed += 1
                else:
                    accepted_by_order[normalized_order_no] = (
                        accepted_by_order.get(normalized_order_no, 0) + 1
                    )
            created = 0
            updated = 0
            for order_no in sorted(affected_order_nos):
                source_records = list(
                    session.scalars(
                        select(OrderImportSourceRecord)
                        .where(
                            OrderImportSourceRecord.source_scope == source_scope,
                            OrderImportSourceRecord.order_no == order_no,
                        )
                        .order_by(OrderImportSourceRecord.source_record_pk)
                    )
                )
                group = [
                    (self._source_row(source), source)
                    for source in source_records
                    if source.normalized_fields is not None
                ]
                candidate = session.scalar(
                    select(OrderImportCandidate)
                    .where(OrderImportCandidate.order_no == order_no)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
                if not group:
                    if candidate is not None and candidate.status == "PENDING":
                        self._delete_pending_candidate(session, candidate)
                    continue
                if not any(self._needs_import(row) for row, _ in group):
                    if candidate is not None and candidate.status == "PENDING":
                        self._delete_pending_candidate(session, candidate)
                    skipped += accepted_by_order.get(order_no, 0)
                    continue
                if candidate is not None and candidate.status != "PENDING":
                    skipped += accepted_by_order.get(order_no, 0)
                    continue
                if candidate is None:
                    candidate = OrderImportCandidate(
                        candidate_id=str(uuid4()),
                        order_no=order_no,
                        status="PENDING",
                        validation_state="INVALID",
                        validation_issues=[],
                        created_at=now,
                        updated_at=now,
                    )
                    session.add(candidate)
                    session.flush()
                    created += 1
                else:
                    updated += 1
                    session.execute(
                        delete(OrderImportValidationIssue).where(
                            OrderImportValidationIssue.candidate_id == candidate.candidate_id
                        )
                    )
                    session.execute(
                        delete(OrderImportCandidateLine).where(
                            OrderImportCandidateLine.candidate_id == candidate.candidate_id
                        )
                    )
                self._refresh_candidate(session, candidate=candidate, group=group, now=now)
            run.pages_read = pages_read
            run.records_read += len(rows)
            run.candidates_created += created
            run.candidates_updated += updated
            run.skipped_records += skipped
            run.failed_records += failed
            if finalize:
                run.status = "SUCCEEDED"
                run.active_key = None
                run.finished_at = now
            session.flush()
            return self._snapshot(run)

    def process_page(
        self,
        *,
        run_id: str,
        rows: list[SourceOrderRow],
        page_number: int,
        source_scope: str,
    ) -> ImportRunSnapshot:
        return self.process_run(
            run_id=run_id,
            rows=rows,
            pages_read=page_number,
            source_scope=source_scope,
            finalize=False,
        )

    def start_run_attempt(self, *, run_id: str) -> None:
        with self._session_factory() as session, session.begin():
            run = session.get(OrderImportRun, run_id)
            if run is None or run.active_key != ACTIVE_KEY:
                raise ValueError("active import run not found")
            run.status = "RUNNING"
            run.pages_read = 0
            run.records_read = 0
            run.candidates_created = 0
            run.candidates_updated = 0
            run.skipped_records = 0
            run.failed_records = 0

    def successful_watermark(self, source_scope: str) -> datetime | None:
        with self._session_factory() as session:
            cursor = session.get(OrderImportSourceCursor, source_scope)
            return cursor.successful_modified_at if cursor is not None else None

    def complete_run(
        self,
        *,
        run_id: str,
        source_scope: str | None = None,
        successful_modified_at: datetime | None = None,
    ) -> ImportRunSnapshot:
        now = self._clock().replace(tzinfo=None)
        with self._session_factory() as session, session.begin():
            run = session.get(OrderImportRun, run_id)
            if run is None or run.active_key != ACTIVE_KEY:
                raise ValueError("active import run not found")
            run.status = "SUCCEEDED"
            run.active_key = None
            run.finished_at = now
            if source_scope is not None and successful_modified_at is not None:
                cursor = session.get(OrderImportSourceCursor, source_scope)
                if cursor is None:
                    session.add(
                        OrderImportSourceCursor(
                            source_scope=source_scope,
                            successful_modified_at=successful_modified_at,
                            successful_run_id=run_id,
                            successful_at=now,
                        )
                    )
                elif successful_modified_at >= cursor.successful_modified_at:
                    cursor.successful_modified_at = successful_modified_at
                    cursor.successful_run_id = run_id
                    cursor.successful_at = now
            session.flush()
            return self._snapshot(run)

    def fail_run(self, *, run_id: str, error_code: str) -> None:
        now = self._clock().replace(tzinfo=None)
        with self._session_factory() as session, session.begin():
            run = session.get(OrderImportRun, run_id)
            if run is None or run.active_key != ACTIVE_KEY:
                return
            run.status = "FAILED"
            run.active_key = None
            run.finished_at = now
            run.error_code = error_code[:100]

    def exclude_candidate(self, *, actor_id: str, candidate_id: str, request_id: str) -> None:
        now = self._clock().replace(tzinfo=None)
        with self._session_factory() as session, session.begin():
            self._require_admin(session, actor_id)
            candidate = self._locked_pending_candidate(session, candidate_id)
            candidate.status = "EXCLUDED"
            candidate.excluded_by = actor_id
            candidate.excluded_at = now
            candidate.updated_at = now
            self._add_candidate_audit(
                session,
                request_id=request_id,
                action="order_import.candidate_excluded",
                candidate=candidate,
                actor_id=actor_id,
            )

    def get_run(self, *, actor_id: str, run_id: str) -> ImportRunSnapshot:
        with self._session_factory() as session:
            self._require_admin(session, actor_id)
            run = session.get(OrderImportRun, run_id)
            if run is None:
                raise ValueError("import run not found")
            return self._snapshot(run)

    def latest_run(self, *, actor_id: str) -> ImportRunSnapshot | None:
        with self._session_factory() as session:
            self._require_admin(session, actor_id)
            run = session.scalar(
                select(OrderImportRun)
                .where(OrderImportRun.active_key == ACTIVE_KEY)
                .order_by(OrderImportRun.started_at.desc(), OrderImportRun.run_id.desc())
            )
            if run is None:
                run = session.scalar(
                    select(OrderImportRun)
                    .where(OrderImportRun.status == "SUCCEEDED")
                    .order_by(OrderImportRun.started_at.desc(), OrderImportRun.run_id.desc())
                )
            return self._snapshot(run) if run else None

    def pending_count(self, *, actor_id: str) -> int:
        with self._session_factory() as session:
            self._require_admin(session, actor_id)
            return len(
                list(
                    session.scalars(
                        select(OrderImportCandidate.candidate_id).where(
                            OrderImportCandidate.status == "PENDING"
                        )
                    )
                )
            )

    def list_candidates(
        self,
        *,
        actor_id: str,
        status: str = "PENDING",
        keyword: str = "",
        category: str | None = None,
        factory_names: list[str] | None = None,
        trackers: list[str] | None = None,
        validation_state: str | None = None,
        sort_by: str = "default",
        sort_order: str = "asc",
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[CandidateSnapshot], int]:
        if status not in {"PENDING", "IMPORTED"}:
            raise ValueError("invalid candidate status")
        with self._session_factory() as session:
            self._require_admin(session, actor_id)
            candidate = OrderImportCandidate
            line = OrderImportCandidateLine
            query = select(candidate).where(candidate.status == status)
            normalized_keyword = keyword.strip().casefold()
            if normalized_keyword:
                keyword_characters = set(normalized_keyword)
                changes = [
                    (original, replacement)
                    for original, replacement in _CASEFOLD_CHANGES
                    if not keyword_characters.isdisjoint(replacement)
                ]

                # LOCATE treats %, _ and backslashes literally, unlike LIKE.
                def contains(column: Any) -> ColumnElement[bool]:
                    folded: ColumnElement[Any] = func.coalesce(column, "").collate(
                        "utf8mb4_0900_bin"
                    )
                    for original, replacement in changes:
                        folded = func.replace(folded, original, replacement)
                    return func.locate(normalized_keyword, folded) > 0

                query = query.where(
                    or_(
                        contains(candidate.order_no),
                        select(line.candidate_line_id)
                        .where(
                            line.candidate_id == candidate.candidate_id,
                            or_(contains(line.product_name), contains(line.properties_value)),
                        )
                        .exists(),
                    )
                )
            if category and "、" in category:
                query = query.where(false())
            elif category:
                query = query.where(
                    func.locate(
                        f"、{category}、",
                        func.concat("、", func.coalesce(candidate.category, ""), "、").collate(
                            "utf8mb4_0900_bin"
                        ),
                    )
                    > 0
                )
            if trackers:
                query = query.where(candidate.tracker.collate("utf8mb4_0900_bin").in_(trackers))
            if validation_state:
                query = query.where(
                    candidate.validation_state.collate("utf8mb4_0900_bin") == validation_state
                )
            if factory_names:
                query = query.where(
                    select(line.candidate_line_id)
                    .where(
                        line.candidate_id == candidate.candidate_id,
                        line.factory_name.collate("utf8mb4_0900_bin").in_(factory_names),
                    )
                    .exists()
                )
            if sort_order not in {"asc", "desc"}:
                raise ValueError("invalid sort order")

            # Binary NO PAD collation preserves Python's case, accent and trailing-space order.
            def string_key(column: Any) -> ColumnElement[str]:
                return func.coalesce(column, "").collate("utf8mb4_0900_bin")

            keys: dict[str, list[ColumnElement[Any]]] = {
                "default": [
                    candidate.validation_state != "READY",
                    -func.coalesce(func.to_days(candidate.order_date), 0),
                    string_key(candidate.order_no),
                ],
                "orderNo": [string_key(candidate.order_no)],
                "category": [string_key(candidate.category)],
                "tracker": [string_key(candidate.tracker)],
                "validationState": [string_key(candidate.validation_state)],
                "updatedAt": [candidate.updated_at.__clause_element__()],
            }
            sort_keys: list[ColumnElement[Any]]
            if sort_by in {"productName", "factory"}:
                # Fixed whitelist SQL: preserve every line, its ID order and empty values.
                field = "product_name" if sort_by == "productName" else "factory_name"
                combined = (
                    select(
                        func.group_concat(
                            literal_column(
                                f"COALESCE(order_import_candidate_lines.{field}, '') "
                                "ORDER BY order_import_candidate_lines.candidate_line_id "
                                "SEPARATOR '、'"
                            )
                        )
                    )
                    .where(line.candidate_id == candidate.candidate_id)
                    .scalar_subquery()
                )
                sort_keys = [string_key(combined)]
            elif sort_by in keys:
                sort_keys = keys[sort_by]
            else:
                raise ValueError("invalid candidate sort")
            sort_keys = [key.desc() if sort_order == "desc" else key.asc() for key in sort_keys]
            total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
            candidates = list(
                session.scalars(
                    query.prefix_with(
                        "/*+ SET_VAR(group_concat_max_len=4294967295) "
                        "SET_VAR(max_sort_length=8388608) */"
                    )
                    .order_by(*sort_keys, candidate.updated_at.desc())
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            )
            lines_by_candidate: dict[str, list[OrderImportCandidateLine]] = {
                item.candidate_id: [] for item in candidates
            }
            if candidates:
                for item_line in session.scalars(
                    select(line)
                    .where(line.candidate_id.in_(lines_by_candidate))
                    .order_by(line.candidate_line_id)
                ):
                    lines_by_candidate[item_line.candidate_id].append(item_line)
            return [
                self._candidate_snapshot(session, item, lines=lines_by_candidate[item.candidate_id])
                for item in candidates
            ], total

    def get_candidate(self, *, actor_id: str, candidate_id: str) -> CandidateSnapshot:
        with self._session_factory() as session:
            self._require_admin(session, actor_id)
            candidate = session.get(OrderImportCandidate, candidate_id)
            if candidate is None or candidate.status == "EXCLUDED":
                raise ValueError("candidate not found")
            return self._candidate_snapshot(session, candidate)

    def save_candidate_date(
        self,
        *,
        actor_id: str,
        candidate_id: str,
        candidate_line_id: int,
        version: int,
        contract_ship_date: date | None,
        request_id: str,
    ) -> CandidateSnapshot:
        with self._session_factory() as session, session.begin():
            self._require_admin(session, actor_id)
            candidate = self._locked_pending_candidate(session, candidate_id)
            if candidate.version != version:
                raise ValueError("candidate version changed; reload before saving")
            rows = self._candidate_lines(session, candidate_id)
            line = next(
                (item for item in rows if item.candidate_line_id == candidate_line_id), None
            )
            if line is None:
                raise ValueError("candidate line changed; reload before saving")
            key = f"source:{line.source_record_pk}"
            candidate.date_overrides = {
                **candidate.date_overrides,
                key: contract_ship_date.isoformat() if contract_ship_date else None,
            }
            for item in rows:
                if item.source_record_pk == line.source_record_pk:
                    item.contract_ship_date = contract_ship_date
            candidate.validation_state = (
                "READY"
                if not candidate.validation_issues and all(item.contract_ship_date for item in rows)
                else "INVALID"
            )
            candidate.version += 1
            candidate.updated_at = self._clock().replace(tzinfo=None)
            self._add_candidate_audit(
                session,
                request_id=request_id,
                action="order_import.date_updated",
                candidate=candidate,
                actor_id=actor_id,
            )
            session.flush()
            return self._candidate_snapshot(session, candidate)

    @staticmethod
    def _date_key(sku: str | None, factory: str | None) -> str:
        return json.dumps(
            [sku.strip() if sku else None, factory.strip() if factory else None], ensure_ascii=False
        )

    def confirm_candidate(
        self, *, actor_id: str, candidate_id: str, request_id: str, version: int | None = None
    ) -> str:
        now = self._clock().replace(tzinfo=None)
        order_id = str(uuid4())
        try:
            with self._session_factory() as session, session.begin():
                self._require_admin(session, actor_id)
                candidate = session.scalar(
                    select(OrderImportCandidate)
                    .where(OrderImportCandidate.candidate_id == candidate_id)
                    .with_for_update()
                )
                if candidate is None:
                    raise ValueError("pending candidate not found")
                if candidate.status == "IMPORTED" and candidate.imported_order_id:
                    return candidate.imported_order_id
                if candidate.status != "PENDING":
                    raise ValueError("pending candidate not found")
                if version is not None and candidate.version != version:
                    raise ValueError("candidate version changed; reload before importing")
                rows = self._candidate_lines(session, candidate_id)
                if not rows or len(rows) != candidate.source_record_count:
                    raise ValueError("candidate source details are incomplete")
                session.add(
                    Order(
                        order_id=order_id,
                        order_no=candidate.order_no,
                        source="feishu",
                        detail_mode=True,
                        order_date=candidate.order_date,
                        tracker=candidate.tracker if candidate.tracker in TRACKERS else None,
                        lifecycle="DRAFT",
                        created_by=actor_id,
                        updated_by=actor_id,
                        created_at=now,
                        updated_at=now,
                    )
                )
                session.flush()
                for index, line in enumerate(rows, 1):
                    source = session.get(OrderImportSourceRecord, line.source_record_pk)
                    if (
                        source is None
                        or not source.source_record_id.strip()
                        or source.order_no != candidate.order_no
                    ):
                        raise ValueError("candidate source identity changed")
                    fields = source.normalized_fields or {}
                    if fields.get("contractDateMappingVersion") != 3:
                        raise ValueError("来源解析规则已更新，请先重新获取飞书订单再导入")
                    date_key = f"source:{source.source_record_pk}"
                    old_date_key = self._date_key(line.source_sku_id, line.factory_name)
                    session.add(
                        OrderDetail(
                            detail_id=str(uuid4()),
                            order_id=order_id,
                            origin="feishu",
                            source_record_pk=source.source_record_pk,
                            sort_order=index,
                            accepted_raw_fields=source.raw_fields,
                            accepted_source_modified_at=source.source_modified_at,
                            accepted_source_hash=sha256(
                                json.dumps(
                                    source.raw_fields,
                                    sort_keys=True,
                                    ensure_ascii=False,
                                    separators=(",", ":"),
                                ).encode()
                            ).hexdigest(),
                            source_sku_id=line.source_sku_id,
                            product_name=line.product_name,
                            properties_value=line.properties_value,
                            category=line.category,
                            factory_name=line.factory_name,
                            matched_variant_id=line.matched_variant_id,
                            matched_factory_id=line.matched_factory_id,
                            order_quantity=line.order_quantity,
                            source_shipped_quantity=line.shipped_quantity,
                            source_tracker=fields.get("tracker"),
                            source_contract_ship_date=line.source_contract_ship_date,
                            contract_ship_date=line.contract_ship_date,
                            date_override_enabled=(
                                date_key in candidate.date_overrides
                                or old_date_key in candidate.date_overrides
                            ),
                            parse_issues=line.validation_issues,
                            dispatch_state="UNASSIGNED",
                            created_at=now,
                            updated_at=now,
                        )
                    )
                candidate.status = "IMPORTED"
                candidate.imported_order_id = order_id
                candidate.imported_by = actor_id
                candidate.imported_at = now
                candidate.version += 1
                candidate.updated_at = now
                self._add_candidate_audit(
                    session,
                    request_id=request_id,
                    action="order_import.candidate_imported",
                    candidate=candidate,
                    actor_id=actor_id,
                )
                total = candidate.total_quantity
                initial = candidate.shipped_quantity
                pending = candidate.pending_quantity
                session.add(
                    AuditLog(
                        request_id=request_id,
                        action="order.imported_from_feishu",
                        target_type="order",
                        target_id=order_id,
                        changes={
                            "orderQuantity": total,
                            "initialShippedQuantity": initial,
                            "pendingQuantity": pending,
                            "content": (
                                "从飞书导入订单："
                                f"订单数量 {total if total is not None else '—'}，"
                                f"初始已发数量 {initial if initial is not None else '—'}，"
                                f"未发数量 {pending if pending is not None else '—'}。"
                            ),
                        },
                        actor_id=actor_id,
                        source_terminal="web_admin",
                        created_at=now,
                    )
                )
                session.flush()
        except IntegrityError as error:
            raise ValueError("order number already exists") from error
        return order_id

    def confirm_candidates(
        self, *, actor_id: str, candidate_ids: list[str], request_id: str
    ) -> list[BatchConfirmItem]:
        results: list[BatchConfirmItem] = []
        for candidate_id in list(dict.fromkeys(candidate_ids)):
            try:
                order_id = self.confirm_candidate(
                    actor_id=actor_id,
                    candidate_id=candidate_id,
                    request_id=request_id,
                )
                results.append(BatchConfirmItem(candidate_id, True, order_id=order_id))
            except Exception as error:
                results.append(BatchConfirmItem(candidate_id, False, error=str(error)))
        return results

    def revalidate_pending_candidates(
        self,
        *,
        factory_names: list[str] | None = None,
        source_sku_ids: list[str] | None = None,
        reason: str,
        request_id: str,
        actor_id: str | None = None,
    ) -> RevalidationSnapshot:
        normalized_factories = {name.strip() for name in factory_names or [] if name.strip()}
        normalized_skus = {sku.strip() for sku in source_sku_ids or [] if sku.strip()}
        now = self._clock().replace(tzinfo=None)
        checked = 0
        updated = 0
        with self._session_factory() as session, session.begin():
            candidates = session.scalars(
                select(OrderImportCandidate)
                .where(OrderImportCandidate.status == "PENDING")
                .order_by(OrderImportCandidate.candidate_id)
            )
            for candidate in candidates:
                locked_candidate = session.scalar(
                    select(OrderImportCandidate)
                    .where(OrderImportCandidate.candidate_id == candidate.candidate_id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
                if locked_candidate is None or locked_candidate.status != "PENDING":
                    continue
                candidate = locked_candidate
                lines = self._candidate_lines(session, candidate.candidate_id)
                if (normalized_factories or normalized_skus) and not any(
                    line.factory_name in normalized_factories
                    or line.source_sku_id in normalized_skus
                    for line in lines
                ):
                    continue
                checked += 1
                if self._revalidate_candidate_dependencies(
                    session,
                    candidate=candidate,
                    lines=lines,
                    now=now,
                ):
                    updated += 1
            session.add(
                AuditLog(
                    request_id=request_id,
                    action="order_import.candidates_revalidated",
                    target_type="order_import_revalidation",
                    target_id=request_id,
                    changes={
                        "reason": reason,
                        "checkedCandidates": checked,
                        "updatedCandidates": updated,
                    },
                    actor_id=actor_id,
                    source_terminal="worker",
                    created_at=now,
                )
            )
        return RevalidationSnapshot(
            checked_candidates=checked,
            updated_candidates=updated,
        )

    def _revalidate_candidate_dependencies(
        self,
        session: Session,
        *,
        candidate: OrderImportCandidate,
        lines: list[OrderImportCandidateLine],
        now: datetime,
    ) -> bool:
        candidate_issues = [
            code for code in candidate.validation_issues if code not in LOCAL_DEPENDENCY_ISSUES
        ]
        line_updates: list[
            tuple[OrderImportCandidateLine, list[str], str | None, str | None, str | None]
        ] = []
        for line in lines:
            line_issues = [
                code for code in line.validation_issues if code not in LOCAL_DEPENDENCY_ISSUES
            ]
            variant = session.scalar(
                select(ProductVariant)
                .join(Product, Product.product_id == ProductVariant.product_id)
                .where(
                    ProductVariant.source_sku_id == (line.source_sku_id or "").strip(),
                    ProductVariant.properties_value == (line.properties_value or "").strip(),
                    ProductVariant.is_available.is_(True),
                    Product.name == (line.product_name or "").strip(),
                    Product.is_available.is_(True),
                )
            )
            product = session.get(Product, variant.product_id) if variant else None
            if variant is None:
                line_issues.append("PRODUCT_VARIANT_NOT_MATCHED")
            factory = session.scalar(
                select(Factory).where(
                    Factory.factory_name == (line.factory_name or "").strip(),
                    Factory.is_enabled.is_(True),
                )
            )
            if factory is None:
                line_issues.append("FACTORY_NOT_MATCHED")
            elif (
                session.scalar(
                    select(User.user_id)
                    .where(
                        User.factory_id == factory.factory_id,
                        User.role == "factory",
                        User.is_enabled.is_(True),
                    )
                    .limit(1)
                )
                is None
            ):
                line_issues.append("FACTORY_HAS_NO_ENABLED_USER")
            candidate_issues.extend(line_issues)
            line_updates.append(
                (
                    line,
                    line_issues,
                    variant.variant_id if variant else None,
                    factory.factory_id if factory else None,
                    product.image_object_key if product else None,
                )
            )
        candidate_issues = list(dict.fromkeys(candidate_issues))
        changed = candidate.validation_issues != candidate_issues or any(
            line.validation_issues != issues
            or line.matched_variant_id != variant_id
            or line.matched_factory_id != factory_id
            or line.image_object_key_snapshot != image_key
            for line, issues, variant_id, factory_id, image_key in line_updates
        )
        if not changed:
            return False
        for line, issues, variant_id, factory_id, image_key in line_updates:
            line.validation_issues = issues
            line.matched_variant_id = variant_id
            line.matched_factory_id = factory_id
            line.image_object_key_snapshot = image_key
        candidate.validation_issues = candidate_issues
        candidate.issue_count = len(candidate_issues)
        candidate.validation_state = (
            "READY"
            if not candidate_issues and all(line.contract_ship_date for line in lines)
            else "INVALID"
        )
        candidate.updated_at = now
        session.execute(
            delete(OrderImportValidationIssue).where(
                OrderImportValidationIssue.candidate_id == candidate.candidate_id
            )
        )
        for sort_order, code in enumerate(candidate_issues, start=1):
            field_name, message = self._issue_details(code)
            session.add(
                OrderImportValidationIssue(
                    candidate_id=candidate.candidate_id,
                    code=code,
                    field_name=field_name,
                    message=message,
                    sort_order=sort_order,
                )
            )
        return True

    @staticmethod
    def _normalized_source_fields(row: SourceOrderRow) -> dict[str, object]:
        return {
            "contractDateMappingVersion": 3,
            "orderNo": row.order_no,
            "sourceSkuId": row.source_sku_id,
            "productName": row.product_name,
            "propertiesValue": row.properties_value,
            "category": row.category,
            "factoryName": row.factory_name,
            "orderQuantity": OrderImportService._quantity(row.order_quantity, minimum=1),
            "shippedQuantity": OrderImportService._quantity(row.shipped_quantity),
            "pendingQuantity": OrderImportService._quantity(row.pending_quantity),
            "tracker": row.tracker,
            "orderDate": row.order_date.isoformat() if row.order_date else None,
            "contractShipDate": (
                row.contract_ship_date.isoformat() if row.contract_ship_date else None
            ),
        }

    @staticmethod
    def _order_is_frozen(session: Session, order_no: str) -> bool:
        candidate = session.scalar(
            select(OrderImportCandidate).where(OrderImportCandidate.order_no == order_no)
        )
        return candidate is not None and candidate.status != "PENDING"

    @staticmethod
    def _source_row(source: OrderImportSourceRecord) -> SourceOrderRow:
        fields = source.normalized_fields
        if fields is None:
            raise ValueError("normalized source snapshot missing")
        order_date = fields.get("orderDate")
        contract_ship_date = fields.get("contractShipDate")
        return SourceOrderRow(
            record_id=source.source_record_id,
            order_no=fields.get("orderNo") if isinstance(fields.get("orderNo"), str) else None,
            source_sku_id=(
                fields.get("sourceSkuId") if isinstance(fields.get("sourceSkuId"), str) else None
            ),
            product_name=(
                fields.get("productName") if isinstance(fields.get("productName"), str) else None
            ),
            properties_value=(
                fields.get("propertiesValue")
                if isinstance(fields.get("propertiesValue"), str)
                else None
            ),
            category=(fields.get("category") if isinstance(fields.get("category"), str) else None),
            factory_name=(
                fields.get("factoryName") if isinstance(fields.get("factoryName"), str) else None
            ),
            order_quantity=(
                fields.get("orderQuantity")
                if isinstance(fields.get("orderQuantity"), int)
                else None
            ),
            shipped_quantity=fields.get("shippedQuantity"),
            pending_quantity=fields.get("pendingQuantity"),
            tracker=fields.get("tracker") if isinstance(fields.get("tracker"), str) else None,
            order_date=date.fromisoformat(order_date) if isinstance(order_date, str) else None,
            contract_ship_date=(
                date.fromisoformat(contract_ship_date)
                if isinstance(contract_ship_date, str)
                else None
            ),
            raw_fields=source.raw_fields,
            source_detail_id=source.source_detail_id,
            source_modified_at=source.source_modified_at,
        )

    @staticmethod
    def _delete_pending_candidate(session: Session, candidate: OrderImportCandidate) -> None:
        session.execute(
            delete(OrderImportValidationIssue).where(
                OrderImportValidationIssue.candidate_id == candidate.candidate_id
            )
        )
        session.execute(
            delete(OrderImportCandidateLine).where(
                OrderImportCandidateLine.candidate_id == candidate.candidate_id
            )
        )
        session.delete(candidate)

    def _refresh_candidate(
        self,
        session: Session,
        *,
        candidate: OrderImportCandidate,
        group: list[tuple[SourceOrderRow, OrderImportSourceRecord]],
        now: datetime,
    ) -> None:
        rows = [row for row, _ in group]
        issues: list[str] = []
        tracker = self._unique_value([row.tracker for row in rows])
        order_date = next((row.order_date for row in rows if row.order_date is not None), None)
        effective_dates: dict[int, date | None] = {}
        for row, source in group:
            key = f"source:{source.source_record_pk}"
            old_key = self._date_key(row.source_sku_id, row.factory_name)
            override_key = key if key in candidate.date_overrides else old_key
            original = row.contract_ship_date
            effective_dates[source.source_record_pk] = (
                (
                    date.fromisoformat(candidate.date_overrides[override_key])
                    if isinstance(candidate.date_overrides.get(override_key), str)
                    else None
                )
                if override_key in candidate.date_overrides
                else (
                    original - timedelta(days=4) if original and original >= date(1, 1, 5) else None
                )
            )
        candidate.version += 1
        if tracker is None or tracker not in TRACKERS:
            issues.append("INVALID_TRACKER")
        categories = {self._display_category(row.category) for row in rows if row.category}
        candidate.tracker = tracker
        candidate.order_date = order_date
        candidate.contract_ship_date = None
        candidate.category = (
            "、".join(name for name in ("服装", "帽子") if name in categories)
            if categories
            else None
        )
        candidate.total_quantity = self._nullable_sum([row.order_quantity for row in rows])
        candidate.shipped_quantity = self._nullable_sum([row.shipped_quantity for row in rows])
        candidate.pending_quantity = self._nullable_sum(
            [self._pending(row.order_quantity, row.shipped_quantity) for row in rows]
        )
        candidate.source_record_count = len(rows)
        for row, source in group:
            line_issues: list[str] = []
            variant = session.scalar(
                select(ProductVariant)
                .join(Product, Product.product_id == ProductVariant.product_id)
                .where(
                    ProductVariant.source_sku_id == (row.source_sku_id or "").strip(),
                    ProductVariant.properties_value == (row.properties_value or "").strip(),
                    ProductVariant.is_available.is_(True),
                    Product.name == (row.product_name or "").strip(),
                    Product.is_available.is_(True),
                )
            )
            if variant is None:
                line_issues.append("PRODUCT_VARIANT_NOT_MATCHED")
            product = session.get(Product, variant.product_id) if variant else None
            factory = session.scalar(
                select(Factory).where(
                    Factory.factory_name == (row.factory_name or "").strip(),
                    Factory.is_enabled.is_(True),
                )
            )
            if factory is None:
                line_issues.append("FACTORY_NOT_MATCHED")
            elif (
                session.scalar(
                    select(User.user_id)
                    .where(
                        User.factory_id == factory.factory_id,
                        User.role == "factory",
                        User.is_enabled.is_(True),
                    )
                    .limit(1)
                )
                is None
            ):
                line_issues.append("FACTORY_HAS_NO_ENABLED_USER")
            if (
                row.order_quantity is None
                or isinstance(row.order_quantity, bool)
                or row.order_quantity <= 0
            ):
                line_issues.append("INVALID_ORDER_QUANTITY")
            if row.shipped_quantity is None or row.shipped_quantity < 0:
                line_issues.append("INVALID_INITIAL_SHIPPED_QUANTITY")
            issues.extend(line_issues)
            candidate_line = OrderImportCandidateLine(
                candidate_id=candidate.candidate_id,
                source_record_pk=source.source_record_pk,
                source_contract_ship_date=row.contract_ship_date,
                contract_ship_date=effective_dates[source.source_record_pk],
                source_sku_id=row.source_sku_id,
                product_name=row.product_name,
                properties_value=row.properties_value,
                category=row.category,
                factory_name=row.factory_name,
                order_quantity=row.order_quantity,
                shipped_quantity=row.shipped_quantity,
                pending_quantity=self._pending(row.order_quantity, row.shipped_quantity),
                matched_variant_id=variant.variant_id if variant else None,
                matched_factory_id=factory.factory_id if factory else None,
                image_object_key_snapshot=(
                    product.image_object_key if variant and product else None
                ),
                validation_issues=line_issues,
            )
            session.add(candidate_line)
        candidate.validation_issues = list(dict.fromkeys(issues))
        candidate.issue_count = len(candidate.validation_issues)
        candidate.validation_state = (
            "READY" if not issues and all(effective_dates.values()) else "INVALID"
        )
        candidate.updated_at = now
        for sort_order, code in enumerate(candidate.validation_issues, start=1):
            field_name, message = self._issue_details(code)
            session.add(
                OrderImportValidationIssue(
                    candidate_id=candidate.candidate_id,
                    code=code,
                    field_name=field_name,
                    message=message,
                    sort_order=sort_order,
                )
            )

    @staticmethod
    def _display_category(source_category: str | None) -> str:
        return "服装" if source_category in {"童装春夏", "童装秋冬"} else "帽子"

    @staticmethod
    def _issue_details(code: str) -> tuple[str | None, str]:
        details = {
            "INVALID_TRACKER": ("跟单人员", "跟单人员缺失、不一致或不在允许范围"),
            "INCONSISTENT_CONTRACT_SHIP_DATE": (
                "合同出货时间",
                "合同出货时间缺失或明细不一致",
            ),
            "PRODUCT_VARIANT_NOT_MATCHED": ("产品编码", "产品编码、名称或颜色规格未严格匹配"),
            "FACTORY_NOT_MATCHED": ("工厂", "工厂不存在或未启用"),
            "FACTORY_HAS_NO_ENABLED_USER": ("工厂", "工厂没有已启用账号"),
            "INVALID_ORDER_QUANTITY": ("下单数", "下单数必须为正整数"),
            "INVALID_INITIAL_SHIPPED_QUANTITY": (
                "出货总数",
                "初始已发数量必须为非负整数",
            ),
            "INITIAL_SHIPPED_EXCEEDS_ORDER_QUANTITY": (
                "出货总数",
                "初始已发数量不能大于下单数量",
            ),
        }
        return details.get(code, (None, "来源资料待处理"))

    @staticmethod
    def _candidate_lines(session: Session, candidate_id: str) -> list[OrderImportCandidateLine]:
        return list(
            session.scalars(
                select(OrderImportCandidateLine)
                .where(OrderImportCandidateLine.candidate_id == candidate_id)
                .order_by(OrderImportCandidateLine.candidate_line_id)
            )
        )

    @classmethod
    def _candidate_snapshot(
        cls,
        session: Session,
        candidate: OrderImportCandidate,
        *,
        lines: list[OrderImportCandidateLine] | None = None,
    ) -> CandidateSnapshot:
        if lines is None:
            lines = cls._candidate_lines(session, candidate.candidate_id)
        return CandidateSnapshot(
            candidate_id=candidate.candidate_id,
            version=candidate.version,
            contract_ship_dates=sorted(
                {line.contract_ship_date for line in lines if line.contract_ship_date}
            ),
            order_no=candidate.order_no,
            status=candidate.status,
            validation_state=candidate.validation_state,
            validation_issues=list(candidate.validation_issues),
            order_date=candidate.order_date,
            tracker=candidate.tracker,
            contract_ship_date=min(
                (line.contract_ship_date for line in lines if line.contract_ship_date), default=None
            ),
            category=candidate.category,
            total_quantity=candidate.total_quantity,
            shipped_quantity=candidate.shipped_quantity,
            pending_quantity=candidate.pending_quantity,
            imported_order_id=candidate.imported_order_id,
            lines=[
                CandidateLineSnapshot(
                    candidate_line_id=line.candidate_line_id,
                    contract_ship_date=line.contract_ship_date,
                    source_contract_ship_date=line.source_contract_ship_date,
                    source_sku_id=line.source_sku_id,
                    product_name=line.product_name,
                    properties_value=line.properties_value,
                    category=line.category,
                    factory_name=line.factory_name,
                    order_quantity=line.order_quantity,
                    shipped_quantity=line.shipped_quantity,
                    pending_quantity=line.pending_quantity,
                    validation_issues=list(line.validation_issues),
                )
                for line in lines
            ],
            updated_at=candidate.updated_at,
        )

    @staticmethod
    def _require_admin(session: Session, actor_id: str) -> None:
        actor = session.get(User, actor_id)
        if actor is None or actor.role != "admin" or not actor.is_enabled:
            raise PermissionError("enabled admin required")

    @staticmethod
    def _locked_pending_candidate(session: Session, candidate_id: str) -> OrderImportCandidate:
        candidate = session.scalar(
            select(OrderImportCandidate)
            .where(OrderImportCandidate.candidate_id == candidate_id)
            .with_for_update()
        )
        if candidate is None or candidate.status != "PENDING":
            raise ValueError("pending candidate not found")
        return candidate

    @staticmethod
    def _add_candidate_audit(
        session: Session,
        *,
        request_id: str,
        action: str,
        candidate: OrderImportCandidate,
        actor_id: str,
    ) -> None:
        session.add(
            AuditLog(
                request_id=request_id,
                action=action,
                target_type="order_import_candidate",
                target_id=candidate.candidate_id,
                changes={"orderNo": candidate.order_no, "status": candidate.status},
                actor_id=actor_id,
                source_terminal="web_admin",
            )
        )

    @staticmethod
    def _unique_value(values: list[object | None]):  # type: ignore[no-untyped-def]
        if not values or any(value is None for value in values):
            return None
        unique = {value for value in values if value is not None}
        return next(iter(unique)) if len(unique) == 1 else None

    @staticmethod
    def _quantity(value: object, *, minimum: int = 0) -> int | None:
        return value if type(value) is int and minimum <= value <= 2147483647 else None

    @staticmethod
    def _nullable_sum(values: list[int | None]) -> int | None:
        return (
            None
            if any(value is None for value in values)
            else sum(value for value in values if value is not None)
        )

    @staticmethod
    def _pending(quantity: int | None, shipped: int | None) -> int | None:
        if quantity is None or shipped is None or quantity <= 0 or shipped < 0:
            return None
        return max(quantity - shipped, 0)

    @staticmethod
    def _needs_import(row: SourceOrderRow) -> bool:
        quantity = row.order_quantity
        if quantity is None or type(quantity) is not int or quantity <= 0:
            return True
        shipped = row.shipped_quantity
        if type(shipped) is not int or shipped < 0:
            return True
        return shipped * 100 < quantity * 95

    @staticmethod
    def _snapshot(run: OrderImportRun) -> ImportRunSnapshot:
        return ImportRunSnapshot(
            run_id=run.run_id,
            status=run.status,
            started_at=run.started_at,
            finished_at=run.finished_at,
            pages_read=run.pages_read,
            records_read=run.records_read,
            candidates_created=run.candidates_created,
            candidates_updated=run.candidates_updated,
            skipped_records=run.skipped_records,
            failed_records=run.failed_records,
            error_code=run.error_code,
        )
