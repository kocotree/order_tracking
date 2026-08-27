import hashlib
import json
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import (
    AuditLog,
    IdempotencyRecord,
    OutboxMessage,
    RepairInspectionLine,
    RepairOrder,
    RepairReturnBatch,
    RepairReturnLine,
    User,
)
from app.modules.repairs.confirmation import (
    RepairConfirmationNotFound,
    RepairConfirmationService,
    RepairOrderView,
)


class RepairReturnNotFound(ValueError):
    pass


class RepairReturnConflict(ValueError):
    pass


class RepairReturnValidationError(ValueError):
    pass


@dataclass(frozen=True)
class RepairReturnLineInput:
    variant_id: str
    repaired_quantity: int
    scrapped_quantity: int


@dataclass(frozen=True)
class RepairArchiveView:
    repair_id: str
    archived_at: datetime
    archived_by: str


class RepairReturnService:
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
        self._reader = RepairConfirmationService(session_factory)

    def get(self, repair_id: str) -> RepairOrderView:
        try:
            return self._reader.get(repair_id)
        except RepairConfirmationNotFound as error:
            raise RepairReturnNotFound("返修单不存在") from error

    def list_all(self, *, factory_id: str | None = None) -> tuple[RepairOrderView, ...]:
        return self._reader.list_all(factory_id=factory_id)

    def archive(
        self,
        *,
        repair_id: str,
        archived_by: str,
        idempotency_key: str,
    ) -> RepairArchiveView:
        normalized_key = idempotency_key.strip()
        if not normalized_key or len(normalized_key) > 191:
            raise RepairReturnValidationError("无效的幂等键")
        current = self._clock().astimezone(UTC).replace(tzinfo=None)
        scope = f"repair.archive:{repair_id}:{archived_by}"

        with self._session_factory() as session, session.begin():
            repair = session.scalar(
                select(RepairOrder).where(RepairOrder.repair_id == repair_id).with_for_update()
            )
            if repair is None:
                raise RepairReturnNotFound("返修单不存在")
            existing = session.scalar(
                select(IdempotencyRecord).where(
                    IdempotencyRecord.scope == scope,
                    IdempotencyRecord.idempotency_key == normalized_key,
                )
            )
            if existing is not None and repair.archived_at is not None:
                return RepairArchiveView(
                    repair_id=repair.repair_id,
                    archived_at=repair.archived_at,
                    archived_by=repair.archived_by or archived_by,
                )
            if repair.archived_at is not None:
                raise RepairReturnConflict("返修单已归档")
            actor = session.get(User, archived_by)
            if actor is None or not actor.is_enabled or actor.role != "admin":
                raise RepairReturnNotFound("返修单不存在")
            if repair.status != "COMPLETED":
                raise RepairReturnConflict("只有已完成的返修单可以归档")
            session.add(
                IdempotencyRecord(
                    scope=scope,
                    idempotency_key=normalized_key,
                    status="completed",
                )
            )
            repair.archived_at = current
            repair.archived_by = archived_by
            repair.updated_at = current
            session.add(
                AuditLog(
                    request_id=normalized_key[:64],
                    action="repair_archived",
                    target_type="repair",
                    target_id=repair_id,
                    changes={"archivedAt": current.isoformat()},
                    actor_id=archived_by,
                    source_terminal="admin-web",
                )
            )
            session.flush()
            return RepairArchiveView(
                repair_id=repair.repair_id,
                archived_at=current,
                archived_by=archived_by,
            )

    def submit(
        self,
        *,
        repair_id: str,
        factory_id: str,
        submitted_by: str,
        idempotency_key: str,
        lines: Sequence[RepairReturnLineInput],
    ) -> RepairOrderView:
        normalized_key = idempotency_key.strip()
        if not normalized_key or len(normalized_key) > 191:
            raise RepairReturnValidationError("无效的幂等键")
        normalized_lines = tuple(lines)
        self._validate_lines(normalized_lines)
        request_sha256 = self._request_sha256(repair_id, normalized_lines)
        current = self._clock().astimezone(UTC).replace(tzinfo=None)
        replayed = False

        with self._session_factory() as session, session.begin():
            repair = session.scalar(
                select(RepairOrder).where(RepairOrder.repair_id == repair_id).with_for_update()
            )
            if repair is None or repair.archived_at is not None or repair.factory_id != factory_id:
                raise RepairReturnNotFound("返修单不存在")
            existing = session.scalar(
                select(RepairReturnBatch).where(
                    RepairReturnBatch.submitted_by == submitted_by,
                    RepairReturnBatch.idempotency_key == normalized_key,
                )
            )
            if existing is not None:
                if existing.request_sha256 != request_sha256 or existing.repair_id != repair_id:
                    raise RepairReturnConflict("同一幂等键不能用于不同的发回内容")
                replayed = True
            else:
                actor = session.get(User, submitted_by)
                if (
                    actor is None
                    or not actor.is_enabled
                    or actor.role != "factory"
                    or actor.factory_id != factory_id
                ):
                    raise RepairReturnNotFound("返修单不存在")
                if repair.status != "INCOMPLETE":
                    raise RepairReturnConflict("已完成返修单不能继续发回")
                inspection_lines = session.scalars(
                    select(RepairInspectionLine)
                    .where(RepairInspectionLine.repair_id == repair_id)
                    .order_by(RepairInspectionLine.source_order)
                    .with_for_update()
                ).all()
                existing_return_lines = session.scalars(
                    select(RepairReturnLine)
                    .join(
                        RepairReturnBatch,
                        RepairReturnBatch.batch_id == RepairReturnLine.batch_id,
                    )
                    .where(RepairReturnBatch.repair_id == repair_id)
                    .with_for_update()
                ).all()
                warehouse_by_variant: dict[str, int] = {}
                for inspection_line in inspection_lines:
                    warehouse_by_variant[inspection_line.variant_id] = (
                        warehouse_by_variant.get(inspection_line.variant_id, 0)
                        + inspection_line.warehouse_return_quantity
                    )
                returned_by_variant: dict[str, int] = {}
                for existing_return_line in existing_return_lines:
                    returned_by_variant[existing_return_line.variant_id] = (
                        returned_by_variant.get(existing_return_line.variant_id, 0)
                        + existing_return_line.repaired_quantity
                        + existing_return_line.scrapped_quantity
                    )
                for submitted_line in normalized_lines:
                    warehouse_quantity = warehouse_by_variant.get(submitted_line.variant_id)
                    if warehouse_quantity is None:
                        raise RepairReturnValidationError("返修规格不存在")
                    pending_quantity = warehouse_quantity - returned_by_variant.get(
                        submitted_line.variant_id, 0
                    )
                    if (
                        submitted_line.repaired_quantity + submitted_line.scrapped_quantity
                        > pending_quantity
                    ):
                        raise RepairReturnConflict("返修进度已变化，请重新核对")

                batch_id = self._id_factory()
                session.add(
                    RepairReturnBatch(
                        batch_id=batch_id,
                        repair_id=repair_id,
                        submitted_by=submitted_by,
                        submitted_at=current,
                        idempotency_key=normalized_key,
                        request_sha256=request_sha256,
                        created_at=current,
                    )
                )
                for index, submitted_line in enumerate(normalized_lines, start=1):
                    session.add(
                        RepairReturnLine(
                            batch_id=batch_id,
                            line_order=index,
                            variant_id=submitted_line.variant_id,
                            repaired_quantity=submitted_line.repaired_quantity,
                            scrapped_quantity=submitted_line.scrapped_quantity,
                            created_at=current,
                        )
                    )
                repaired_delta = sum(line.repaired_quantity for line in normalized_lines)
                scrapped_delta = sum(line.scrapped_quantity for line in normalized_lines)
                previous_status = repair.status
                repair.repaired_quantity += repaired_delta
                repair.scrapped_quantity += scrapped_delta
                repair.returned_quantity += repaired_delta + scrapped_delta
                if repair.returned_quantity == repair.warehouse_return_quantity:
                    repair.status = "COMPLETED"
                repair.updated_at = current
                session.add(
                    AuditLog(
                        request_id=normalized_key[:64],
                        action="repair_return_submitted",
                        target_type="repair",
                        target_id=repair_id,
                        changes={
                            "batchId": batch_id,
                            "repairedQuantity": repaired_delta,
                            "scrappedQuantity": scrapped_delta,
                            "returnedQuantity": repaired_delta + scrapped_delta,
                            "statusBefore": previous_status,
                            "statusAfter": repair.status,
                        },
                        actor_id=submitted_by,
                        source_terminal="factory-mini",
                    )
                )
                session.add(
                    OutboxMessage(
                        event_type="repair.return_submitted",
                        aggregate_type="repair",
                        aggregate_id=repair_id,
                        dedupe_key=f"repair:{repair_id}:return:{batch_id}",
                        payload={"repairId": repair_id, "batchId": batch_id},
                        status="pending",
                        available_at=current,
                    )
                )
                if previous_status != repair.status and repair.status == "COMPLETED":
                    session.add(
                        OutboxMessage(
                            event_type="repair.completed",
                            aggregate_type="repair",
                            aggregate_id=repair_id,
                            dedupe_key=f"repair:{repair_id}:completed",
                            payload={"repairId": repair_id},
                            status="pending",
                            available_at=current,
                        )
                    )
                session.flush()

        if replayed:
            return self.get(repair_id)
        return self.get(repair_id)

    @staticmethod
    def _validate_lines(lines: Sequence[RepairReturnLineInput]) -> None:
        if not lines:
            raise RepairReturnValidationError("请至少选择一个本次发回的产品规格")
        seen: set[str] = set()
        for line in lines:
            if not line.variant_id.strip() or line.variant_id in seen:
                raise RepairReturnValidationError("同一产品规格不能重复提交")
            seen.add(line.variant_id)
            if (
                type(line.repaired_quantity) is not int
                or type(line.scrapped_quantity) is not int
                or line.repaired_quantity < 0
                or line.scrapped_quantity < 0
            ):
                raise RepairReturnValidationError("返修数量和报废数量只能填写非负整数")
            if line.repaired_quantity + line.scrapped_quantity == 0:
                raise RepairReturnValidationError("返修数量和报废数量不能同时为0")

    @staticmethod
    def _request_sha256(repair_id: str, lines: Sequence[RepairReturnLineInput]) -> str:
        payload = {
            "repairId": repair_id,
            "lines": [asdict(line) for line in lines],
        }
        content = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        return hashlib.sha256(content).hexdigest()
