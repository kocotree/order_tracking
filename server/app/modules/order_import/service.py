from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from uuid import uuid4

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import (
    AuditLog,
    BackgroundJob,
    Factory,
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
from app.modules.orders.service import (
    TRACKERS,
    AssignmentInput,
    DraftLineInput,
    OrderService,
)

ACTIVE_KEY = "feishu-order-import"
LOCAL_DEPENDENCY_ISSUES = frozenset(
    {
        "PRODUCT_VARIANT_NOT_MATCHED",
        "FACTORY_NOT_MATCHED",
        "FACTORY_HAS_NO_ENABLED_USER",
    }
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
    source_sku_id: str | None
    product_name: str | None
    properties_value: str | None
    category: str | None
    factory_name: str | None
    order_quantity: int | None
    shipped_quantity: int
    pending_quantity: int
    validation_issues: list[str]


@dataclass(frozen=True)
class CandidateSnapshot:
    candidate_id: str
    order_no: str
    status: str
    validation_state: str
    validation_issues: list[str]
    order_date: date | None
    tracker: str | None
    contract_ship_date: date | None
    category: str | None
    total_quantity: int
    shipped_quantity: int
    pending_quantity: int
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
    shipped_quantity: int
    pending_quantity: int
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
        self._orders = OrderService(session_factory, clock=clock)

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
                if not row.record_id:
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
                        and row.source_modified_at <= source.source_modified_at
                    ):
                        skipped += 1
                        continue
                    if source.normalized_fields == normalized_fields:
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
            for order_no in affected_order_nos:
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
                    select(OrderImportCandidate).where(
                        OrderImportCandidate.order_no == order_no
                    )
                )
                if not group:
                    if candidate is not None and candidate.status == "PENDING":
                        self._delete_pending_candidate(session, candidate)
                    continue
                if not any(self._is_below_half(row) for row, _ in group):
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
                    .order_by(
                        OrderImportRun.started_at.desc(), OrderImportRun.run_id.desc()
                    )
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
            candidates = list(
                session.scalars(
                    select(OrderImportCandidate)
                    .where(OrderImportCandidate.status == status)
                    .order_by(OrderImportCandidate.updated_at.desc())
                )
            )
            normalized_keyword = keyword.strip().casefold()
            filtered: list[OrderImportCandidate] = []
            for candidate in candidates:
                lines = self._candidate_lines(session, candidate.candidate_id)
                if normalized_keyword and not any(
                    normalized_keyword in (value or "").casefold()
                    for value in [
                        candidate.order_no,
                        *[line.product_name for line in lines],
                        *[line.properties_value for line in lines],
                    ]
                ):
                    continue
                if category and category not in (candidate.category or "").split("、"):
                    continue
                if trackers and candidate.tracker not in trackers:
                    continue
                if validation_state and candidate.validation_state != validation_state:
                    continue
                if factory_names and not set(factory_names).intersection(
                    {line.factory_name for line in lines}
                ):
                    continue
                filtered.append(candidate)
            if sort_order not in {"asc", "desc"}:
                raise ValueError("invalid sort order")
            allowed_sorts = {
                "default": lambda item: (
                    item.validation_state != "READY",
                    -(item.order_date.toordinal() if item.order_date else 0),
                    item.order_no,
                ),
                "orderNo": lambda item: item.order_no,
                "productName": lambda item: "、".join(
                    line.product_name or ""
                    for line in self._candidate_lines(session, item.candidate_id)
                ),
                "category": lambda item: item.category or "",
                "tracker": lambda item: item.tracker or "",
                "factory": lambda item: "、".join(
                    line.factory_name or ""
                    for line in self._candidate_lines(session, item.candidate_id)
                ),
                "validationState": lambda item: item.validation_state,
                "updatedAt": lambda item: item.updated_at,
            }
            sort_key = allowed_sorts.get(sort_by)
            if sort_key is None:
                raise ValueError("invalid candidate sort")
            filtered.sort(key=sort_key, reverse=sort_order == "desc")
            total = len(filtered)
            start = (page - 1) * page_size
            return [
                self._candidate_snapshot(session, item)
                for item in filtered[start : start + page_size]
            ], total

    def get_candidate(self, *, actor_id: str, candidate_id: str) -> CandidateSnapshot:
        with self._session_factory() as session:
            self._require_admin(session, actor_id)
            candidate = session.get(OrderImportCandidate, candidate_id)
            if candidate is None or candidate.status == "EXCLUDED":
                raise ValueError("candidate not found")
            return self._candidate_snapshot(session, candidate)

    def confirm_candidate(self, *, actor_id: str, candidate_id: str, request_id: str) -> str:
        now = self._clock().replace(tzinfo=None)
        order_id = str(uuid4())
        try:
            with self._session_factory() as session, session.begin():
                self._require_admin(session, actor_id)
                candidate = self._locked_pending_candidate(session, candidate_id)
                if candidate.validation_state != "READY":
                    raise ValueError("candidate is not ready")
                rows = list(
                    session.scalars(
                        select(OrderImportCandidateLine)
                        .where(OrderImportCandidateLine.candidate_id == candidate_id)
                        .order_by(OrderImportCandidateLine.candidate_line_id)
                    )
                )
                if candidate.contract_ship_date is None or candidate.tracker is None or not rows:
                    raise ValueError("candidate is incomplete")
                self._validate_candidate_for_confirm(session, candidate, rows)
                lines = [
                    DraftLineInput(
                        variant_id=self._required(line.matched_variant_id),
                        order_quantity=self._required_quantity(line.order_quantity),
                        assignments=[
                            AssignmentInput(
                                factory_id=self._required(line.matched_factory_id),
                                quantity=self._required_quantity(line.order_quantity),
                                initial_shipped_quantity=line.shipped_quantity,
                            )
                        ],
                    )
                    for line in rows
                ]
                self._orders.create_draft_in_session(
                    session,
                    actor_id=actor_id,
                    order_id=order_id,
                    order_no=candidate.order_no,
                    order_date=candidate.order_date,
                    tracker=candidate.tracker,
                    contract_ship_date=candidate.contract_ship_date,
                    lines=lines,
                    source="feishu",
                    request_id=request_id,
                    now=now,
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
                pending = max(total - initial, 0)
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
                                f"订单数量 {total:,}，"
                                f"初始已发数量 {initial:,}，"
                                f"未发数量 {pending:,}。"
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
            code
            for code in candidate.validation_issues
            if code not in LOCAL_DEPENDENCY_ISSUES
        ]
        line_updates: list[
            tuple[OrderImportCandidateLine, list[str], str | None, str | None, str | None]
        ] = []
        for line in lines:
            line_issues = [
                code
                for code in line.validation_issues
                if code not in LOCAL_DEPENDENCY_ISSUES
            ]
            variant = session.scalar(
                select(ProductVariant)
                .join(Product, Product.product_id == ProductVariant.product_id)
                .where(
                    ProductVariant.source_sku_id == (line.source_sku_id or "").strip(),
                    ProductVariant.properties_value
                    == (line.properties_value or "").strip(),
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
        changed = (
            candidate.validation_issues != candidate_issues
            or any(
                line.validation_issues != issues
                or line.matched_variant_id != variant_id
                or line.matched_factory_id != factory_id
                or line.image_object_key_snapshot != image_key
                for line, issues, variant_id, factory_id, image_key in line_updates
            )
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
        candidate.validation_state = "READY" if not candidate_issues else "INVALID"
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
            "orderNo": row.order_no,
            "sourceSkuId": row.source_sku_id,
            "productName": row.product_name,
            "propertiesValue": row.properties_value,
            "category": row.category,
            "factoryName": row.factory_name,
            "orderQuantity": row.order_quantity,
            "shippedQuantity": row.shipped_quantity,
            "pendingQuantity": row.pending_quantity,
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
                fields.get("sourceSkuId")
                if isinstance(fields.get("sourceSkuId"), str)
                else None
            ),
            product_name=(
                fields.get("productName")
                if isinstance(fields.get("productName"), str)
                else None
            ),
            properties_value=(
                fields.get("propertiesValue")
                if isinstance(fields.get("propertiesValue"), str)
                else None
            ),
            category=(
                fields.get("category") if isinstance(fields.get("category"), str) else None
            ),
            factory_name=(
                fields.get("factoryName")
                if isinstance(fields.get("factoryName"), str)
                else None
            ),
            order_quantity=(
                fields.get("orderQuantity")
                if isinstance(fields.get("orderQuantity"), int)
                else None
            ),
            shipped_quantity=int(fields.get("shippedQuantity") or 0),
            pending_quantity=int(fields.get("pendingQuantity") or 0),
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
    def _delete_pending_candidate(
        session: Session, candidate: OrderImportCandidate
    ) -> None:
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
        contract_date = self._unique_value([row.contract_ship_date for row in rows])
        if tracker is None or tracker not in TRACKERS:
            issues.append("INVALID_TRACKER")
        if contract_date is None:
            issues.append("INCONSISTENT_CONTRACT_SHIP_DATE")
        categories = {self._display_category(row.category) for row in rows if row.category}
        candidate.tracker = tracker
        candidate.order_date = order_date
        candidate.contract_ship_date = contract_date
        candidate.category = (
            "、".join(name for name in ("服装", "帽子") if name in categories)
            if categories
            else None
        )
        candidate.total_quantity = sum(row.order_quantity or 0 for row in rows)
        candidate.shipped_quantity = sum(row.shipped_quantity for row in rows)
        candidate.pending_quantity = sum(
            max((row.order_quantity or 0) - row.shipped_quantity, 0) for row in rows
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
            elif row.shipped_quantity < 0:
                line_issues.append("INVALID_INITIAL_SHIPPED_QUANTITY")
            elif row.shipped_quantity > row.order_quantity:
                line_issues.append("INITIAL_SHIPPED_EXCEEDS_ORDER_QUANTITY")
            issues.extend(line_issues)
            candidate_line = OrderImportCandidateLine(
                candidate_id=candidate.candidate_id,
                source_record_pk=source.source_record_pk,
                source_sku_id=row.source_sku_id,
                product_name=row.product_name,
                properties_value=row.properties_value,
                category=row.category,
                factory_name=row.factory_name,
                order_quantity=row.order_quantity,
                shipped_quantity=row.shipped_quantity,
                pending_quantity=max((row.order_quantity or 0) - row.shipped_quantity, 0),
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
        candidate.validation_state = "READY" if not issues else "INVALID"
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
        cls, session: Session, candidate: OrderImportCandidate
    ) -> CandidateSnapshot:
        lines = cls._candidate_lines(session, candidate.candidate_id)
        return CandidateSnapshot(
            candidate_id=candidate.candidate_id,
            order_no=candidate.order_no,
            status=candidate.status,
            validation_state=candidate.validation_state,
            validation_issues=list(candidate.validation_issues),
            order_date=candidate.order_date,
            tracker=candidate.tracker,
            contract_ship_date=candidate.contract_ship_date,
            category=candidate.category,
            total_quantity=candidate.total_quantity,
            shipped_quantity=candidate.shipped_quantity,
            pending_quantity=candidate.pending_quantity,
            imported_order_id=candidate.imported_order_id,
            lines=[
                CandidateLineSnapshot(
                    candidate_line_id=line.candidate_line_id,
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
    def _required(value: str | None) -> str:
        if value is None:
            raise ValueError("candidate match is missing")
        return value

    @staticmethod
    def _required_quantity(value: int | None) -> int:
        if value is None or value <= 0:
            raise ValueError("candidate quantity is invalid")
        return value

    @staticmethod
    def _validate_candidate_for_confirm(
        session: Session,
        candidate: OrderImportCandidate,
        rows: list[OrderImportCandidateLine],
    ) -> None:
        if candidate.validation_issues or candidate.tracker not in TRACKERS:
            raise ValueError("candidate is not ready")
        for line in rows:
            variant = session.get(ProductVariant, line.matched_variant_id)
            product = session.get(Product, variant.product_id) if variant else None
            factory = session.get(Factory, line.matched_factory_id)
            factory_user = (
                session.scalar(
                    select(User.user_id)
                    .where(
                        User.factory_id == factory.factory_id,
                        User.role == "factory",
                        User.is_enabled.is_(True),
                    )
                    .limit(1)
                )
                if factory
                else None
            )
            if (
                variant is None
                or product is None
                or not variant.is_available
                or not product.is_available
                or variant.source_sku_id != (line.source_sku_id or "").strip()
                or variant.properties_value != (line.properties_value or "").strip()
                or product.name != (line.product_name or "").strip()
                or factory is None
                or not factory.is_enabled
                or factory.factory_name != (line.factory_name or "").strip()
                or factory_user is None
            ):
                raise ValueError("candidate dependencies changed")

    @staticmethod
    def _unique_value(values: list[object | None]):  # type: ignore[no-untyped-def]
        if not values or any(value is None for value in values):
            return None
        unique = {value for value in values if value is not None}
        return next(iter(unique)) if len(unique) == 1 else None

    @staticmethod
    def _is_below_half(row: SourceOrderRow) -> bool:
        quantity = row.order_quantity
        if quantity is None or type(quantity) is not int or quantity <= 0:
            return True
        return row.shipped_quantity * 2 < quantity

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
