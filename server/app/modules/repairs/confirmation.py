from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import (
    AuditLog,
    Factory,
    IdempotencyRecord,
    OutboxMessage,
    Product,
    ProductVariant,
    RepairInspectionLine,
    RepairNumberCounter,
    RepairOrder,
    RepairPreview,
    RepairPreviewLine,
    StoredFile,
)

BUSINESS_TIME_ZONE = ZoneInfo("Asia/Shanghai")


class RepairConfirmationNotFound(ValueError):
    pass


class RepairConfirmationConflict(ValueError):
    pass


@dataclass(frozen=True)
class RepairFormalLineView:
    inspection_line_id: int
    source_row: int
    source_order: int
    box_number: str
    product_id: str
    variant_id: str
    source_sku_id: str
    source_product_id: str
    product_name: str
    properties_value: str
    warehouse_return_quantity: int
    reason: str | None


@dataclass(frozen=True)
class RepairOrderView:
    repair_id: str
    repair_no: str
    status: str
    return_date: date
    factory_id: str
    warehouse_return_quantity: int
    repaired_quantity: int
    scrapped_quantity: int
    returned_quantity: int
    original_file_id: int
    original_filename: str
    original_size_bytes: int
    factory_name: str
    created_at: datetime
    lines: tuple[RepairFormalLineView, ...]


class RepairConfirmationService:
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

    def confirm(
        self,
        *,
        preview_id: str,
        confirmed_by: str,
        idempotency_key: str,
    ) -> RepairOrderView:
        if not idempotency_key.strip() or len(idempotency_key) > 191:
            raise RepairConfirmationConflict("无效的幂等键")
        current_aware = self._clock().astimezone(UTC)
        current = current_aware.replace(tzinfo=None)
        business_date = current_aware.astimezone(BUSINESS_TIME_ZONE).date()
        repair_id = self._id_factory()

        with self._session_factory() as session, session.begin():
            preview = session.scalar(
                select(RepairPreview)
                .where(RepairPreview.preview_id == preview_id)
                .with_for_update()
            )
            if preview is None:
                raise RepairConfirmationNotFound(preview_id)
            if preview.status == "CONFIRMED" and preview.confirmed_repair_id is not None:
                return self.get(preview.confirmed_repair_id)
            if preview.expires_at <= current:
                raise RepairConfirmationConflict("预览已失效，请重新上传质检 Excel")
            if preview.status != "READY" or preview.validation_errors:
                raise RepairConfirmationConflict("当前预览不可确认")
            if preview.factory_id is None:
                raise RepairConfirmationConflict("当前预览未匹配工厂")
            factory = session.get(Factory, preview.factory_id, with_for_update=True)
            if factory is None or not factory.is_enabled:
                raise RepairConfirmationConflict("工厂已停用或不存在")
            duplicate = session.scalar(
                select(RepairOrder).where(RepairOrder.source_sha256 == preview.source_sha256)
            )
            if duplicate is not None:
                raise RepairConfirmationConflict(f"该质检 Excel 已创建返修单 {duplicate.repair_no}")

            preview_lines = session.scalars(
                select(RepairPreviewLine)
                .where(RepairPreviewLine.preview_id == preview_id)
                .order_by(RepairPreviewLine.source_order)
                .with_for_update()
            ).all()
            if not preview_lines:
                raise RepairConfirmationConflict("当前预览没有可确认明细")
            if any(
                line.matched_product_id is None or line.matched_variant_id is None
                for line in preview_lines
            ):
                raise RepairConfirmationConflict("当前预览存在未匹配明细")
            for line in preview_lines:
                product = session.get(Product, line.matched_product_id, with_for_update=True)
                variant = session.get(
                    ProductVariant,
                    line.matched_variant_id,
                    with_for_update=True,
                )
                if (
                    product is None
                    or variant is None
                    or not product.is_available
                    or not variant.is_available
                    or variant.product_id != product.product_id
                    or product.source_i_id != line.source_product_id
                    or product.name != line.product_name
                    or variant.source_sku_id != line.source_sku_id
                    or variant.properties_value != line.properties_value
                ):
                    raise RepairConfirmationConflict(
                        f"Sheet1 第 {line.source_row} 行产品规格已失效"
                    )

            counter_statement = mysql_insert(RepairNumberCounter).values(
                business_date=business_date,
                next_sequence=2,
                updated_at=current,
            )
            counter_statement = counter_statement.on_duplicate_key_update(
                next_sequence=RepairNumberCounter.next_sequence + 1,
                updated_at=current,
            )
            session.execute(counter_statement)
            next_sequence = session.scalar(
                select(RepairNumberCounter.next_sequence).where(
                    RepairNumberCounter.business_date == business_date
                )
            )
            if next_sequence is None:
                raise RepairConfirmationConflict("返修单号分配失败")
            sequence = next_sequence - 1
            repair_no = f"FX{business_date:%Y%m%d}-{sequence:03d}"

            session.add(
                IdempotencyRecord(
                    scope=f"repair.confirm:{confirmed_by}",
                    idempotency_key=idempotency_key,
                    status="completed",
                )
            )
            repair = RepairOrder(
                repair_id=repair_id,
                repair_no=repair_no,
                factory_id=preview.factory_id,
                status="INCOMPLETE",
                warehouse_return_quantity=preview.total_quantity,
                repaired_quantity=0,
                scrapped_quantity=0,
                returned_quantity=0,
                return_date=business_date,
                original_file_id=preview.original_file_id,
                source_sha256=preview.source_sha256,
                created_by=confirmed_by,
                archived_by=None,
                archived_at=None,
                created_at=current,
                updated_at=current,
            )
            session.add(repair)
            session.flush()

            for preview_line in preview_lines:
                formal_line = RepairInspectionLine(
                    repair_id=repair_id,
                    source_sheet=preview_line.source_sheet,
                    source_row=preview_line.source_row,
                    source_order=preview_line.source_order,
                    box_number=preview_line.box_number,
                    product_id=preview_line.matched_product_id,
                    variant_id=preview_line.matched_variant_id,
                    source_sku_id=preview_line.source_sku_id,
                    source_product_id=preview_line.source_product_id,
                    product_name=preview_line.product_name,
                    properties_value=preview_line.properties_value,
                    warehouse_return_quantity=preview_line.quantity,
                    reason=preview_line.reason,
                )
                session.add(formal_line)
            session.flush()
            preview.status = "CONFIRMED"
            preview.confirmed_at = current
            preview.confirmed_repair_id = repair_id
            session.add(
                AuditLog(
                    request_id=idempotency_key[:64],
                    action="repair_confirmed",
                    target_type="repair",
                    target_id=repair_id,
                    changes={"previewId": preview_id, "repairNo": repair_no},
                    actor_id=confirmed_by,
                    source_terminal="admin-web",
                )
            )
            session.add(
                OutboxMessage(
                    event_type="repair.created",
                    aggregate_type="repair",
                    aggregate_id=repair_id,
                    dedupe_key=f"repair:{repair_id}:created",
                    payload={"repairId": repair_id, "repairNo": repair_no},
                    status="pending",
                    available_at=current,
                )
            )
            session.flush()

        return self.get(repair_id)

    def get(self, repair_id: str) -> RepairOrderView:
        with self._session_factory() as session:
            repair = session.get(RepairOrder, repair_id)
            if repair is None:
                raise RepairConfirmationNotFound(repair_id)
            factory = session.get(Factory, repair.factory_id)
            original_file = session.get(StoredFile, repair.original_file_id)
            if factory is None or original_file is None:
                raise RepairConfirmationConflict("返修单关联资料不存在")
            lines = session.scalars(
                select(RepairInspectionLine)
                .where(RepairInspectionLine.repair_id == repair_id)
                .order_by(RepairInspectionLine.source_order)
            ).all()
            return RepairOrderView(
                repair_id=repair.repair_id,
                repair_no=repair.repair_no,
                status=repair.status,
                return_date=repair.return_date,
                factory_id=repair.factory_id,
                warehouse_return_quantity=repair.warehouse_return_quantity,
                repaired_quantity=repair.repaired_quantity,
                scrapped_quantity=repair.scrapped_quantity,
                returned_quantity=repair.returned_quantity,
                original_file_id=repair.original_file_id,
                original_filename=original_file.original_filename,
                original_size_bytes=original_file.size_bytes,
                factory_name=factory.factory_name,
                created_at=repair.created_at,
                lines=tuple(
                    RepairFormalLineView(
                        inspection_line_id=line.inspection_line_id,
                        source_row=line.source_row,
                        source_order=line.source_order,
                        box_number=line.box_number,
                        product_id=line.product_id,
                        variant_id=line.variant_id,
                        source_sku_id=line.source_sku_id,
                        source_product_id=line.source_product_id,
                        product_name=line.product_name,
                        properties_value=line.properties_value,
                        warehouse_return_quantity=line.warehouse_return_quantity,
                        reason=line.reason,
                    )
                    for line in lines
                ),
            )

    def list_all(self, *, factory_id: str | None = None) -> tuple[RepairOrderView, ...]:
        with self._session_factory() as session:
            query = select(RepairOrder.repair_id).where(RepairOrder.archived_at.is_(None))
            if factory_id is not None:
                query = query.where(RepairOrder.factory_id == factory_id)
            repair_ids = session.scalars(
                query.order_by(RepairOrder.return_date.desc(), RepairOrder.repair_no.desc())
            ).all()
        return tuple(self.get(repair_id) for repair_id in repair_ids)
