import hashlib
import re
from collections import defaultdict
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, date, datetime
from io import BytesIO
from uuid import uuid4
from zoneinfo import ZoneInfo

from PIL import Image, UnidentifiedImageError
from sqlalchemy import Select, delete, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.adapters.private_files import PrivateFileStore
from app.db.models import (
    AuditLog,
    Factory,
    IdempotencyRecord,
    Order,
    OrderAssignment,
    OrderCompletionRecord,
    OrderLine,
    OutboxMessage,
    QuantityLedger,
    Shipment,
    ShipmentBox,
    ShipmentBoxItem,
    ShipmentFile,
    ShipmentLine,
    ShipmentNumberCounter,
    ShipmentReceipt,
    ShipmentReceiptItem,
    ShipmentReturnEvent,
    ShipmentReturnLine,
    ShipmentVoidRequest,
    StoredFile,
    User,
)
from app.modules.shipments.workbook import (
    ShipmentWorkbookLine,
    ShipmentWorkbookRenderer,
    ShipmentWorkbookSnapshot,
)

BUSINESS_TIME_ZONE = ZoneInfo("Asia/Shanghai")
SHIPMENT_FILE_MAX_BYTES = 5 * 1024 * 1024
SHIPMENT_FILE_MIME_BY_FORMAT = {
    "JPEG": "image/jpeg",
    "PNG": "image/png",
    "WEBP": "image/webp",
}
SHIPMENT_FILE_EXTENSION_BY_MIME = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
}


class ShipmentError(Exception):
    pass


class ShipmentNotFound(ShipmentError):
    pass


class ShipmentPermissionDenied(ShipmentError):
    pass


class ShipmentConflict(ShipmentError):
    pass


class ShipmentValidationError(ShipmentError):
    pass


@dataclass(frozen=True)
class DraftItemInput:
    assignment_id: int
    quantity: int


@dataclass(frozen=True)
class DraftBoxInput:
    box_no: int
    group_key: str | None
    items: list[DraftItemInput]


@dataclass(frozen=True)
class ReceiptItemInput:
    box_item_id: int
    quantity: int


@dataclass(frozen=True)
class ReceiptSnapshot:
    version: int
    status: str
    items: list[ReceiptItemInput]
    confirmed_by_name: str | None = None
    confirmed_at: datetime | None = None


@dataclass(frozen=True)
class ShipmentLineSnapshot:
    assignment_id: int
    order_id: str
    order_no: str
    sku_id: str
    product_name: str
    properties_value: str
    quantity: int
    line_id: int | None = None
    box_item_id: int | None = None
    returned_quantity: int = 0
    returnable_quantity: int = 0


@dataclass(frozen=True)
class ShipmentBoxSnapshot:
    box_no: int
    group_key: str | None
    items: list[ShipmentLineSnapshot]


@dataclass(frozen=True)
class ShipmentVoidRequestSnapshot:
    request_id: str
    shipment_id: str
    status: str
    reason: str
    requested_by: str
    requested_by_name: str
    requested_at: datetime
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    review_comment: str | None = None


@dataclass(frozen=True)
class ShipmentReturnInput:
    shipment_line_id: int
    quantity: int


@dataclass(frozen=True)
class ShipmentReturnLineSnapshot:
    shipment_line_id: int
    order_no: str
    sku_id: str
    product_name: str
    properties_value: str
    quantity: int
    before_shipped_quantity: int
    after_shipped_quantity: int


@dataclass(frozen=True)
class ShipmentReturnEventSnapshot:
    event_id: str
    shipment_id: str
    return_date: date
    reason: str
    returned_by: str
    returned_at: datetime
    lines: list[ShipmentReturnLineSnapshot] = field(default_factory=list)


@dataclass(frozen=True)
class ShipmentExportResult:
    filename: str
    content: bytes


@dataclass(frozen=True)
class ShipmentFileSnapshot:
    file_id: int
    filename: str
    mime_type: str
    size_bytes: int
    content_sha256: str
    display_order: int
    draft_version: int | None = None

    @property
    def content_url(self) -> str:
        return f"/api/v1/shipment-files/{self.file_id}/content"


@dataclass(frozen=True)
class ShipmentFileContent:
    content: bytes
    mime_type: str


@dataclass(frozen=True)
class ShipmentDraftSnapshot:
    shipment_id: str
    status: str
    factory_id: str
    created_by: str
    preferred_order_id: str | None
    created_at: datetime
    version: int = 1
    factory_name: str = ""
    submitted_at: datetime | None = None
    shipment_no: str | None = None
    business_date: date | None = None
    note: str = ""
    total_boxes: int = 0
    total_quantity: int = 0
    lines: list[ShipmentLineSnapshot] = field(default_factory=list)
    boxes: list[ShipmentBoxSnapshot] = field(default_factory=list)
    files: list[ShipmentFileSnapshot] = field(default_factory=list)
    void_request: ShipmentVoidRequestSnapshot | None = None
    return_events: list[ShipmentReturnEventSnapshot] = field(default_factory=list)
    receipt: ReceiptSnapshot | None = None
    receipt_differences: list[ShipmentLineSnapshot] = field(default_factory=list)
    withdrawal_draft_id: str | None = None
    can_edit_withdrawal: bool = False
    operations: list[dict[str, str]] = field(default_factory=list)


@dataclass(frozen=True)
class ShipmentCatalogItem:
    assignment_id: int
    order_id: str
    order_no: str
    contract_ship_date: date | None
    product_name: str
    properties_value: str
    assigned_quantity: int
    shipped_quantity: int
    pending_quantity: int


class ShipmentService:
    def __init__(
        self,
        sessions: sessionmaker[Session],
        *,
        workbook_renderer: ShipmentWorkbookRenderer | None = None,
        file_store: PrivateFileStore | None = None,
    ) -> None:
        self._sessions = sessions
        self._workbook_renderer = workbook_renderer
        self._file_store = file_store

    def get_receipt(self, *, shipment_id: str) -> ReceiptSnapshot:
        with self._sessions() as session:
            shipment = session.get(Shipment, shipment_id)
            if (
                shipment is None
                or shipment.deleted_at is not None
                or shipment.status == "DRAFT"
                or shipment.source_shipment_id is not None
            ):
                raise ShipmentNotFound("shipment not found")
            return self._receipt_snapshot(session, shipment_id)

    @staticmethod
    def _receipt_snapshot(session: Session, shipment_id: str) -> ReceiptSnapshot:
        receipt = session.get(ShipmentReceipt, shipment_id)
        quantities = {
            item.box_item_id: item.quantity
            for item in session.scalars(
                select(ShipmentReceiptItem).where(ShipmentReceiptItem.shipment_id == shipment_id)
            )
        }
        originals = session.scalars(
            select(ShipmentBoxItem)
            .join(ShipmentBox)
            .where(ShipmentBox.shipment_id == shipment_id)
            .order_by(ShipmentBox.box_no, ShipmentBoxItem.item_id)
        )
        actor = (
            session.get(User, receipt.confirmed_by) if receipt and receipt.confirmed_by else None
        )
        return ReceiptSnapshot(
            version=receipt.version if receipt else 0,
            status=receipt.status if receipt else "DRAFT",
            items=[
                ReceiptItemInput(item.item_id, quantities.get(item.item_id, item.quantity))
                for item in originals
            ],
            confirmed_by_name=actor.feishu_display_name if actor else None,
            confirmed_at=receipt.confirmed_at if receipt else None,
        )

    @staticmethod
    def _receipt_shipment(session: Session, shipment_id: str) -> Shipment:
        shipment = session.scalar(
            select(Shipment)
            .where(Shipment.shipment_id == shipment_id, Shipment.deleted_at.is_(None))
            .with_for_update()
        )
        if shipment is None or shipment.status == "DRAFT" or shipment.source_shipment_id:
            raise ShipmentNotFound("shipment not found")
        return shipment

    @staticmethod
    def _require_receivable(session: Session, shipment: Shipment) -> None:
        if shipment.status == "WITHDRAWN":
            raise ShipmentConflict("发货单已撤回")
        if (
            shipment.status != "SHIPPED"
            or session.scalar(
                select(ShipmentReturnEvent.event_id)
                .where(ShipmentReturnEvent.shipment_id == shipment.shipment_id)
                .limit(1)
            )
            is not None
        ):
            raise ShipmentConflict("发货单已作废、撤回处理中或已有退回，不能核对收货")

    def save_receipt(
        self,
        *,
        shipment_id: str,
        actor_id: str,
        expected_version: int,
        items: list[ReceiptItemInput],
    ) -> ReceiptSnapshot:
        with self._sessions.begin() as session:
            shipment = self._receipt_shipment(session, shipment_id)
            self._require_receivable(session, shipment)
            before = self._receipt_snapshot(session, shipment_id)
            if before.status == "CONFIRMED":
                raise ShipmentConflict("已确认收货，不能再次修改")
            if expected_version != before.version:
                raise ShipmentConflict("核对版本已变化，请重新读取后再保存")
            if (
                len(items) != len(before.items)
                or {i.box_item_id for i in items} != {i.box_item_id for i in before.items}
                or any(
                    type(i.quantity) is not int or not 0 <= i.quantity <= 2147483647 for i in items
                )
            ):
                raise ShipmentValidationError("必须保留全部原箱内明细，数量为非负整数")
            current = datetime.now(UTC)
            receipt = session.get(ShipmentReceipt, shipment_id)
            if receipt is None:
                receipt = ShipmentReceipt(
                    shipment_id=shipment_id,
                    status="DRAFT",
                    version=1,
                    saved_by=actor_id,
                    saved_at=current,
                )
                session.add(receipt)
                session.flush()
            else:
                receipt.version += 1
                receipt.saved_by = actor_id
                receipt.saved_at = current
            session.execute(
                delete(ShipmentReceiptItem).where(ShipmentReceiptItem.shipment_id == shipment_id)
            )
            session.add_all(
                [
                    ShipmentReceiptItem(
                        shipment_id=shipment_id, box_item_id=i.box_item_id, quantity=i.quantity
                    )
                    for i in items
                ]
            )
            session.add(
                AuditLog(
                    request_id=str(uuid4()),
                    action="shipment_receipt_saved",
                    target_type="shipment",
                    target_id=shipment_id,
                    actor_id=actor_id,
                    source_terminal="admin-web",
                    changes={
                        "before": {str(i.box_item_id): i.quantity for i in before.items},
                        "after": {str(i.box_item_id): i.quantity for i in items},
                        "version": receipt.version,
                    },
                )
            )
            session.flush()
            return self._receipt_snapshot(session, shipment_id)

    def confirm_receipt(
        self, *, shipment_id: str, actor_id: str, expected_version: int, idempotency_key: str
    ) -> ShipmentDraftSnapshot:
        with self._sessions.begin() as session:
            shipment = self._receipt_shipment(session, shipment_id)
            before = self._receipt_snapshot(session, shipment_id)
            if expected_version != before.version:
                raise ShipmentConflict("核对版本已变化，请重新读取后再确认")
            if before.status == "CONFIRMED":
                return self._detail_snapshot(session, shipment)
            self._require_receivable(session, shipment)
            current = datetime.now(UTC)
            receipt = session.get(ShipmentReceipt, shipment_id)
            if receipt is None:
                receipt = ShipmentReceipt(
                    shipment_id=shipment_id,
                    status="DRAFT",
                    version=0,
                    saved_by=actor_id,
                    saved_at=current,
                )
                session.add(receipt)
                session.flush()
                session.add_all(
                    [
                        ShipmentReceiptItem(
                            shipment_id=shipment_id, box_item_id=i.box_item_id, quantity=i.quantity
                        )
                        for i in before.items
                    ]
                )
            originals = list(
                session.scalars(
                    select(ShipmentBoxItem)
                    .join(ShipmentBox)
                    .where(ShipmentBox.shipment_id == shipment_id)
                )
            )
            quantities = {i.box_item_id: i.quantity for i in before.items}
            deltas: dict[int, int] = defaultdict(int)
            for item in originals:
                deltas[item.order_assignment_id] += quantities[item.item_id] - item.quantity
            assignments = self._load_assignments(
                session, set(deltas), shipment.factory_id, lock=True, require_published=False
            )
            order_deltas: dict[str, int] = defaultdict(int)
            orders: dict[str, Order] = {}
            for assignment_id, delta in deltas.items():
                assignment, _line, order = assignments[assignment_id]
                order_deltas[order.order_id] += delta
                orders[order.order_id] = order
                if not delta:
                    continue
                system_quantity = int(
                    session.scalar(
                        select(func.coalesce(func.sum(QuantityLedger.quantity_delta), 0)).where(
                            QuantityLedger.order_assignment_id == assignment_id
                        )
                    )
                    or 0
                )
                before_quantity = assignment.initial_shipped_quantity + system_quantity
                session.add(
                    QuantityLedger(
                        order_assignment_id=assignment_id,
                        source_type="SHIPMENT_RECEIPT",
                        source_id=shipment_id,
                        quantity_delta=delta,
                        actor_id=actor_id,
                        created_at=current,
                    )
                )
                session.add(
                    AuditLog(
                        request_id=idempotency_key[:64],
                        action="shipment_receipt_confirmed",
                        target_type="order",
                        target_id=order.order_id,
                        actor_id=actor_id,
                        source_terminal="admin-web",
                        changes={
                            "shipmentId": shipment_id,
                            "orderAssignmentId": assignment_id,
                            "content": (
                                f"确认收货，{'多收' if delta > 0 else '少收'} {abs(delta):,} 件，"
                                f"已发数量 {before_quantity:,} → {before_quantity + delta:,}"
                            ),
                            "quantity": delta,
                            "before": before_quantity,
                            "after": before_quantity + delta,
                        },
                    )
                )
            for order_id, delta in order_deltas.items():
                order = orders[order_id]
                if delta >= 0 or order.lifecycle != "COMPLETED":
                    continue
                order.lifecycle = "PUBLISHED"
                order.version += 1
                order.completed_at = None
                order.completed_by = None
                order.updated_at = current
                order.updated_by = actor_id
                session.add(
                    OrderCompletionRecord(
                        order_id=order_id,
                        action="REOPEN",
                        reason=f"发货单 {shipment.shipment_no} 确认少收",
                        actor_id=actor_id,
                        source_terminal="admin-web",
                        before_lifecycle="COMPLETED",
                        after_lifecycle="PUBLISHED",
                        quantity_snapshot={"shipmentId": shipment_id, "delta": delta},
                        created_at=current,
                    )
                )
            receipt.status = "CONFIRMED"
            receipt.confirmed_by = actor_id
            receipt.confirmed_at = current
            session.add(
                AuditLog(
                    request_id=idempotency_key[:64],
                    action="shipment_receipt_confirmed",
                    target_type="shipment",
                    target_id=shipment_id,
                    actor_id=actor_id,
                    source_terminal="admin-web",
                    changes={
                        "version": receipt.version,
                        "before": {str(i.item_id): i.quantity for i in originals},
                        "after": {str(i.box_item_id): i.quantity for i in before.items},
                    },
                )
            )
            session.add(
                OutboxMessage(
                    event_type="shipment.receipt_confirmed",
                    aggregate_type="shipment",
                    aggregate_id=shipment_id,
                    dedupe_key=f"shipment-receipt:{shipment_id}",
                    payload={"shipmentId": shipment_id},
                    status="pending",
                    available_at=current,
                )
            )
            session.flush()
            return self._detail_snapshot(session, shipment)

    @staticmethod
    def _effective_line_quantities(session: Session, shipment_id: str) -> dict[int, int]:
        receipt = session.get(ShipmentReceipt, shipment_id)
        if receipt is None or receipt.status != "CONFIRMED":
            return {
                line.order_assignment_id: line.quantity
                for line in session.scalars(
                    select(ShipmentLine).where(ShipmentLine.shipment_id == shipment_id)
                )
            }
        return {
            int(assignment_id): int(quantity)
            for assignment_id, quantity in session.execute(
                select(ShipmentBoxItem.order_assignment_id, func.sum(ShipmentReceiptItem.quantity))
                .join(
                    ShipmentReceiptItem, ShipmentReceiptItem.box_item_id == ShipmentBoxItem.item_id
                )
                .where(ShipmentReceiptItem.shipment_id == shipment_id)
                .group_by(ShipmentBoxItem.order_assignment_id)
            )
        }

    def create_or_reuse_draft(
        self,
        *,
        actor_id: str,
        factory_id: str,
        preferred_order_id: str | None,
    ) -> tuple[ShipmentDraftSnapshot, bool]:
        with self._sessions.begin() as session:
            session.execute(select(User.user_id).where(User.user_id == actor_id).with_for_update())
            existing = session.scalar(
                select(Shipment).where(
                    Shipment.active_draft_owner_id == actor_id,
                    Shipment.status == "DRAFT",
                    Shipment.deleted_at.is_(None),
                )
            )
            if existing is not None:
                if existing.factory_id != factory_id:
                    raise ShipmentConflict("所属工厂已变化，请联系管理员处理原草稿")
                return self._detail_snapshot(session, existing), False

            if preferred_order_id is not None and not session.scalar(
                self._preferred_order_query(
                    order_id=preferred_order_id,
                    factory_id=factory_id,
                )
            ):
                raise ShipmentNotFound("preferred order is not available to this factory")

            draft = Shipment(
                shipment_id=str(uuid4()),
                factory_id=factory_id,
                status="DRAFT",
                preferred_order_id=preferred_order_id,
                created_by=actor_id,
                active_draft_owner_id=actor_id,
            )
            session.add(draft)
            session.flush()
            return self._snapshot(draft), True

    def list_catalog(self, *, factory_id: str) -> list[ShipmentCatalogItem]:
        with self._sessions() as session:
            ledger = (
                select(
                    QuantityLedger.order_assignment_id.label("assignment_id"),
                    func.coalesce(func.sum(QuantityLedger.quantity_delta), 0).label("quantity"),
                )
                .group_by(QuantityLedger.order_assignment_id)
                .subquery()
            )
            rows = session.execute(
                select(OrderAssignment, OrderLine, Order, func.coalesce(ledger.c.quantity, 0))
                .join(OrderLine, OrderLine.order_line_id == OrderAssignment.order_line_id)
                .join(Order, Order.order_id == OrderLine.order_id)
                .outerjoin(ledger, ledger.c.assignment_id == OrderAssignment.order_assignment_id)
                .where(
                    OrderAssignment.factory_id == factory_id,
                    Order.lifecycle == "PUBLISHED",
                    Order.deleted_at.is_(None),
                )
                .order_by(
                    OrderAssignment.contract_ship_date.is_(None),
                    OrderAssignment.contract_ship_date,
                    Order.order_no,
                    OrderLine.order_line_id,
                )
            ).all()
            return [
                ShipmentCatalogItem(
                    assignment_id=assignment.order_assignment_id,
                    order_id=order.order_id,
                    order_no=order.order_no,
                    contract_ship_date=assignment.contract_ship_date,
                    product_name=line.product_name_snapshot,
                    properties_value=line.properties_value_snapshot,
                    assigned_quantity=assignment.assigned_quantity,
                    shipped_quantity=assignment.initial_shipped_quantity + int(system_quantity),
                    pending_quantity=max(
                        assignment.assigned_quantity
                        - assignment.initial_shipped_quantity
                        - int(system_quantity),
                        0,
                    ),
                )
                for assignment, line, order, system_quantity in rows
            ]

    def save_draft(
        self,
        *,
        actor_id: str,
        factory_id: str,
        shipment_id: str,
        boxes: list[DraftBoxInput],
        note: str,
        expected_version: int = 1,
    ) -> ShipmentDraftSnapshot:
        with self._sessions.begin() as session:
            shipment = self._owned_shipment(session, shipment_id, actor_id, factory_id, lock=True)
            if shipment.status != "DRAFT":
                raise ShipmentConflict("submitted shipment cannot be edited")
            if shipment.version != expected_version:
                if shipment.source_shipment_id:
                    raise ShipmentConflict(
                        "这张发货单已被其他人修改，本次修改未保存，请重新加载最新内容。"
                    )
                if (
                    expected_version < shipment.version
                    and (shipment.note or "") == note.strip()
                    and self._box_inputs(session, shipment_id)
                    == sorted(boxes, key=lambda box: box.box_no)
                ):
                    return self._detail_snapshot(session, shipment)
                raise ShipmentConflict("草稿已更新，请重新进入后继续填写")
            self._validate_boxes(boxes, allow_empty=True)
            assignment_ids = {item.assignment_id for box in boxes for item in box.items}
            if assignment_ids:
                self._load_assignments(session, assignment_ids, factory_id)
            box_ids = select(ShipmentBox.box_id).where(ShipmentBox.shipment_id == shipment_id)
            session.execute(delete(ShipmentBoxItem).where(ShipmentBoxItem.box_id.in_(box_ids)))
            session.execute(delete(ShipmentBox).where(ShipmentBox.shipment_id == shipment_id))
            for box_input in sorted(boxes, key=lambda item: item.box_no):
                box = ShipmentBox(
                    shipment_id=shipment_id,
                    box_no=box_input.box_no,
                    group_key=box_input.group_key,
                )
                session.add(box)
                session.flush()
                for item in box_input.items:
                    session.add(
                        ShipmentBoxItem(
                            box_id=box.box_id,
                            order_assignment_id=item.assignment_id,
                            quantity=item.quantity,
                        )
                    )
            shipment.note = note.strip() or None
            shipment.version += 1
            session.flush()
            return self._detail_snapshot(session, shipment)

    def abandon_draft(
        self, *, actor_id: str, factory_id: str, shipment_id: str, expected_version: int,
    ) -> None:
        with self._sessions.begin() as session:
            shipment = self._owned_shipment(session, shipment_id, actor_id, factory_id, lock=True)
            if shipment.source_shipment_id:
                raise ShipmentConflict("撤回草稿不能作为普通草稿丢弃")
            if shipment.status != "DRAFT" or shipment.version != expected_version:
                raise ShipmentConflict("草稿已更新或已提交，请重新进入后操作")
            shipment.deleted_at = datetime.now(UTC)
            shipment.active_draft_owner_id = None
            shipment.version += 1

    def get_current_draft(self, *, actor_id: str, factory_id: str) -> ShipmentDraftSnapshot:
        with self._sessions() as session:
            shipment = session.scalar(
                select(Shipment).where(
                    Shipment.active_draft_owner_id == actor_id,
                    Shipment.factory_id == factory_id,
                    Shipment.status == "DRAFT",
                    Shipment.deleted_at.is_(None),
                )
            )
            if shipment is None:
                raise ShipmentNotFound("draft not found")
            return self._detail_snapshot(session, shipment)

    def upload_file(
        self,
        *,
        actor_id: str,
        factory_id: str,
        shipment_id: str,
        filename: str,
        declared_mime_type: str,
        content: bytes,
        idempotency_key: str,
        expected_version: int | None = None,
    ) -> tuple[ShipmentFileSnapshot, bool]:
        if self._file_store is None:
            raise ShipmentConflict("private file store is not configured")
        if not idempotency_key or len(idempotency_key) > 191:
            raise ShipmentValidationError("file idempotency key is invalid")
        actual_mime_type = self._validated_image_mime_type(
            content=content,
            declared_mime_type=declared_mime_type,
        )
        with self._sessions() as session:
            current_draft = self._owned_shipment(
                session, shipment_id, actor_id, factory_id, lock=False
            )
            existing = session.execute(
                select(ShipmentFile, StoredFile)
                .join(StoredFile, StoredFile.file_id == ShipmentFile.stored_file_id)
                .where(
                    StoredFile.uploaded_by == actor_id,
                    StoredFile.idempotency_key == idempotency_key,
                    ShipmentFile.shipment_id == shipment_id,
                )
            ).one_or_none()
            if existing is not None:
                relationship, stored = existing
                if current_draft.source_shipment_id and (
                    current_draft.status != "DRAFT"
                    or expected_version is None
                    or current_draft.version != expected_version + 1
                ):
                    raise ShipmentConflict("发货单已被修改，请重新加载最新内容")
                if relationship.shipment_id != shipment_id:
                    raise ShipmentConflict("file idempotency key belongs to another shipment")
                return replace(self._file_snapshot(relationship, stored),
                    draft_version=current_draft.version if current_draft.source_shipment_id
                    else None), False

        extension = SHIPMENT_FILE_EXTENSION_BY_MIME[actual_mime_type]
        object_key = f"shipments/{shipment_id}/{uuid4().hex}.{extension}"
        self._file_store.put(
            object_key=object_key,
            content=content,
            content_type=actual_mime_type,
        )
        try:
            with self._sessions.begin() as session:
                shipment = self._owned_shipment(
                    session, shipment_id, actor_id, factory_id, lock=True
                )
                if shipment.status != "DRAFT":
                    raise ShipmentConflict("submitted shipment cannot accept files")
                if shipment.source_shipment_id and shipment.version != expected_version:
                    raise ShipmentConflict("草稿已更新，请重新加载最新内容")
                existing_files = list(
                    session.scalars(
                        select(ShipmentFile)
                        .where(ShipmentFile.shipment_id == shipment_id)
                        .order_by(ShipmentFile.display_order)
                    )
                )
                if len(existing_files) >= 3:
                    raise ShipmentValidationError("shipment accepts at most 3 files")
                stored = StoredFile(
                    bucket=self._file_store.bucket,
                    object_key=object_key,
                    original_filename=(filename or "shipment-evidence")[:255],
                    mime_type=actual_mime_type,
                    size_bytes=len(content),
                    content_sha256=hashlib.sha256(content).hexdigest(),
                    uploaded_by=actor_id,
                    idempotency_key=idempotency_key,
                )
                session.add(stored)
                session.flush()
                relationship = ShipmentFile(
                    shipment_id=shipment_id,
                    stored_file_id=stored.file_id,
                    display_order=len(existing_files),
                )
                session.add(relationship)
                if shipment.source_shipment_id:
                    shipment.version += 1
                session.flush()
                return replace(self._file_snapshot(relationship, stored),
                    draft_version=shipment.version if shipment.source_shipment_id else None), True
        except Exception:
            self._file_store.delete(object_key=object_key)
            raise

    def get_file_content(
        self,
        *,
        file_id: int,
        actor_role: str | None,
        actor_factory_id: str | None,
        actor_id: str | None = None,
    ) -> ShipmentFileContent:
        if self._file_store is None:
            raise ShipmentNotFound("shipment file not found")
        with self._sessions() as session:
            rows = session.execute(
                select(ShipmentFile, StoredFile, Shipment)
                .join(StoredFile, StoredFile.file_id == ShipmentFile.stored_file_id)
                .join(Shipment, Shipment.shipment_id == ShipmentFile.shipment_id)
                .where(
                    StoredFile.file_id == file_id,
                    Shipment.deleted_at.is_(None),
                )
            ).all()
            for _relationship, stored, shipment in rows:
                if actor_role == "factory" and shipment.factory_id == actor_factory_id:
                    if shipment.status == "DRAFT":
                        owners = ((shipment.created_by, shipment.submitted_by)
                                  if shipment.source_shipment_id else (shipment.created_by,))
                        if actor_id not in owners:
                            continue
                elif actor_role == "admin" and shipment.status != "DRAFT":
                    pass
                else:
                    continue
                return ShipmentFileContent(
                    content=self._file_store.get(object_key=stored.object_key),
                    mime_type=stored.mime_type,
                )
            raise ShipmentNotFound("shipment file not found")

    def remove_file(
        self,
        *,
        actor_id: str,
        factory_id: str,
        shipment_id: str,
        file_id: int,
        now: datetime | None = None,
        expected_version: int | None = None,
    ) -> int:
        with self._sessions.begin() as session:
            shipment = self._owned_shipment(
                session, shipment_id, actor_id, factory_id, lock=True
            )
            if shipment.status != "DRAFT":
                raise ShipmentConflict("submitted shipment files cannot be removed")
            if shipment.source_shipment_id and shipment.version != expected_version:
                raise ShipmentConflict("草稿已更新，请重新加载最新内容")
            relationship = session.scalar(
                select(ShipmentFile).where(
                    ShipmentFile.shipment_id == shipment_id,
                    ShipmentFile.stored_file_id == file_id,
                )
            )
            if relationship is None:
                raise ShipmentNotFound("shipment file not found")
            stored = session.get(StoredFile, file_id)
            session.delete(relationship)
            session.flush()
            remaining = list(
                session.scalars(
                    select(ShipmentFile)
                    .where(ShipmentFile.shipment_id == shipment_id)
                    .order_by(ShipmentFile.display_order)
                )
            )
            for display_order, item in enumerate(remaining):
                item.display_order = display_order
            if stored is not None and not session.scalar(select(ShipmentFile.shipment_file_id)
                    .where(ShipmentFile.stored_file_id == file_id).limit(1)):
                stored.replaced_at = now or datetime.now(UTC)
            if shipment.source_shipment_id:
                shipment.version += 1
            return shipment.version

    def submit_draft(
        self,
        *,
        actor_id: str,
        factory_id: str,
        shipment_id: str,
        idempotency_key: str,
        now: datetime | None = None,
        expected_version: int | None = None,
    ) -> ShipmentDraftSnapshot:
        current = now or datetime.now(UTC)
        business_date = current.astimezone(BUSINESS_TIME_ZONE).date()
        with self._sessions.begin() as session:
            shipment = self._owned_shipment(session, shipment_id, actor_id, factory_id, lock=True)
            if shipment.source_shipment_id:
                return self._resubmit(
                    session, shipment, actor_id, expected_version, idempotency_key, current
                )
            if shipment.status == "SHIPPED":
                return self._detail_snapshot(session, shipment)
            if shipment.status != "DRAFT":
                raise ShipmentConflict("submitted shipment cannot be edited")
            if expected_version is not None and shipment.version != expected_version:
                raise ShipmentConflict("草稿已更新，请重新进入后核对再提交")
            boxes = self._box_inputs(session, shipment_id)
            self._validate_boxes(boxes)
            totals: dict[int, int] = defaultdict(int)
            for box in boxes:
                for item in box.items:
                    totals[item.assignment_id] += item.quantity
            assignments = self._load_assignments(session, set(totals), factory_id, lock=True)
            scope = f"shipment.submit:{actor_id}"
            existing_key = session.scalar(
                select(IdempotencyRecord).where(
                    IdempotencyRecord.scope == scope,
                    IdempotencyRecord.idempotency_key == idempotency_key,
                )
            )
            if existing_key is not None:
                return self._detail_snapshot(session, shipment)
            session.add(
                IdempotencyRecord(scope=scope, idempotency_key=idempotency_key, status="completed")
            )
            counter = session.get(ShipmentNumberCounter, business_date, with_for_update=True)
            if counter is None:
                counter = ShipmentNumberCounter(
                    business_date=business_date, next_sequence=2, updated_at=current
                )
                session.add(counter)
                sequence = 1
            else:
                sequence = counter.next_sequence
                counter.next_sequence += 1
                counter.updated_at = current
            shipment.shipment_no = f"FH{business_date:%Y%m%d}-{sequence:03d}"
            shipment.business_date = business_date
            shipment.status = "SHIPPED"
            shipment.submitted_by = actor_id
            shipment.submitted_at = current
            shipment.active_draft_owner_id = None
            for assignment_id, quantity in totals.items():
                assignment, line, order = assignments[assignment_id]
                session.add(
                    ShipmentLine(
                        shipment_id=shipment_id,
                        order_assignment_id=assignment_id,
                        quantity=quantity,
                        order_no_snapshot=order.order_no,
                        sku_id_snapshot=line.sku_id_snapshot,
                        product_name_snapshot=line.product_name_snapshot,
                        properties_value_snapshot=line.properties_value_snapshot,
                    )
                )
                session.add(
                    QuantityLedger(
                        order_assignment_id=assignment_id,
                        source_type="SHIPMENT",
                        source_id=shipment_id,
                        quantity_delta=quantity,
                        actor_id=actor_id,
                        created_at=current,
                    )
                )
                session.add(
                    AuditLog(
                        request_id=idempotency_key[:64],
                        action="shipment_submitted",
                        target_type="order",
                        target_id=order.order_id,
                        changes={"shipmentId": shipment_id, "quantity": quantity},
                        actor_id=actor_id,
                        source_terminal="factory-mini",
                    )
                )
            session.add(
                OutboxMessage(
                    event_type="shipment.submitted",
                    aggregate_type="shipment",
                    aggregate_id=shipment_id,
                    dedupe_key=f"shipment:{shipment_id}:submitted",
                    payload={"shipmentId": shipment_id, "shipmentNo": shipment.shipment_no},
                    status="pending",
                    available_at=current,
                )
            )
            session.flush()
            return self._detail_snapshot(session, shipment)

    def list_shipments(
        self, *, factory_id: str | None = None, order_id: str | None = None
    ) -> list[ShipmentDraftSnapshot]:
        with self._sessions() as session:
            query = select(Shipment).where(
                Shipment.status != "DRAFT", Shipment.deleted_at.is_(None),
                Shipment.source_shipment_id.is_(None),
            )
            if factory_id is not None:
                query = query.where(Shipment.factory_id == factory_id)
            if order_id is not None:
                related_ids = (
                    select(ShipmentLine.shipment_id)
                    .join(
                        OrderAssignment,
                        OrderAssignment.order_assignment_id == ShipmentLine.order_assignment_id,
                    )
                    .join(OrderLine, OrderLine.order_line_id == OrderAssignment.order_line_id)
                    .where(OrderLine.order_id == order_id)
                )
                query = query.where(Shipment.shipment_id.in_(related_ids))
            shipments = list(
                session.scalars(query.order_by(Shipment.submitted_at.desc(), Shipment.shipment_id))
            )
            return [self._detail_snapshot(session, item) for item in shipments]

    def get_shipment(
        self, *, shipment_id: str, factory_id: str | None = None, actor_id: str | None = None
    ) -> ShipmentDraftSnapshot:
        with self._sessions() as session:
            shipment = session.get(Shipment, shipment_id)
            if (shipment is None or shipment.status == "DRAFT" or shipment.deleted_at is not None
                    or shipment.source_shipment_id is not None):
                raise ShipmentNotFound("shipment not found")
            if factory_id is not None and shipment.factory_id != factory_id:
                raise ShipmentNotFound("shipment not found")
            result = self._detail_snapshot(session, shipment)
            draft = session.scalar(select(Shipment).where(
                Shipment.source_shipment_id == shipment_id, Shipment.status == "DRAFT",
                Shipment.deleted_at.is_(None),
            ))
            allowed = bool(
                draft and actor_id and actor_id in (draft.created_by, draft.submitted_by)
            )
            return replace(
                result,
                withdrawal_draft_id=draft.shipment_id if allowed and draft else None,
                can_edit_withdrawal=allowed,
            )

    def _copy_contents(self, session: Session, source: Shipment, target: Shipment) -> None:
        for old in session.scalars(
            select(ShipmentBox).where(ShipmentBox.shipment_id == source.shipment_id)
        ).all():
            box = ShipmentBox(
                shipment_id=target.shipment_id, box_no=old.box_no, group_key=old.group_key
            )
            session.add(box)
            session.flush()
            for item in session.scalars(
                select(ShipmentBoxItem).where(ShipmentBoxItem.box_id == old.box_id)
            ).all():
                session.add(
                    ShipmentBoxItem(
                        box_id=box.box_id,
                        order_assignment_id=item.order_assignment_id,
                        quantity=item.quantity,
                    )
                )
        for file_link in session.scalars(
            select(ShipmentFile).where(ShipmentFile.shipment_id == source.shipment_id)
        ).all():
            session.add(
                ShipmentFile(
                    shipment_id=target.shipment_id,
                    stored_file_id=file_link.stored_file_id,
                    display_order=file_link.display_order,
                )
            )
        for line in session.scalars(
            select(ShipmentLine).where(ShipmentLine.shipment_id == source.shipment_id)
        ).all():
            session.add(
                ShipmentLine(
                    shipment_id=target.shipment_id,
                    order_assignment_id=line.order_assignment_id,
                    quantity=line.quantity,
                    order_no_snapshot=line.order_no_snapshot,
                    sku_id_snapshot=line.sku_id_snapshot,
                    product_name_snapshot=line.product_name_snapshot,
                    properties_value_snapshot=line.properties_value_snapshot,
                )
            )

    def withdraw(
        self,
        *,
        actor_id: str,
        factory_id: str,
        shipment_id: str,
        reason: str,
        expected_version: int,
        idempotency_key: str,
    ) -> ShipmentDraftSnapshot:
        reason = reason.strip()
        if not reason or len(reason) > 500:
            raise ShipmentValidationError("请填写撤回原因")
        current = datetime.now(UTC)
        with self._sessions.begin() as session:
            original = self._receipt_shipment(session, shipment_id)
            if original.factory_id != factory_id or original.source_shipment_id:
                raise ShipmentNotFound("shipment not found")
            previous = session.scalar(
                select(AuditLog).where(
                    AuditLog.target_id == shipment_id,
                    AuditLog.action == "shipment_withdrawn",
                    AuditLog.request_id == idempotency_key[:64],
                    AuditLog.actor_id == actor_id,
                )
            )
            if previous:
                return self._detail_snapshot(session, original)
            self._require_receivable(session, original)
            receipt = session.get(ShipmentReceipt, shipment_id)
            if receipt and receipt.status == "CONFIRMED":
                raise ShipmentConflict("已确认收货，不能撤回")
            if original.version != expected_version:
                raise ShipmentConflict("发货单已更新，请刷新后再撤回")
            if not session.scalar(
                select(AuditLog.id)
                .where(
                    AuditLog.target_type == "shipment",
                    AuditLog.target_id == shipment_id,
                    AuditLog.action == "shipment_submitted",
                )
                .limit(1)
            ):
                session.add(
                    AuditLog(
                        request_id=idempotency_key[:64],
                        action="shipment_submitted",
                        target_type="shipment",
                        target_id=shipment_id,
                        actor_id=original.submitted_by or original.created_by,
                        source_terminal="factory-mini",
                        changes={},
                        created_at=original.submitted_at or original.created_at,
                    )
                )
            draft_id = str(uuid4())
            history_id = str(uuid4())
            # Preserve formal contents before creating the editable copy.
            for status in ("SHIPPED", "DRAFT"):
                copy = Shipment(
                    shipment_id=draft_id if status == "DRAFT" else history_id,
                    source_shipment_id=shipment_id,
                    factory_id=factory_id,
                    status=status,
                    created_by=actor_id,
                    submitted_by=original.submitted_by,
                    submitted_at=original.submitted_at if status == "SHIPPED" else None,
                    business_date=original.business_date,
                    note=original.note,
                    created_at=current,
                    version=1,
                )
                session.add(copy)
                session.flush()
                self._copy_contents(session, original, copy)
                if status == "SHIPPED":
                    for message in session.scalars(
                        select(OutboxMessage).where(
                            OutboxMessage.aggregate_id == shipment_id,
                            OutboxMessage.event_type == "shipment.submitted",
                        )
                    ).all():
                        if not message.payload.get("factShipmentId"):
                            message.payload = {
                                **message.payload,
                                "factShipmentId": copy.shipment_id,
                            }
                if status == "DRAFT":
                    session.flush()
                    session.execute(
                        delete(ShipmentLine).where(ShipmentLine.shipment_id == draft_id)
                    )
            quantities = self._effective_line_quantities(session, shipment_id)
            assignments = self._load_assignments(
                session, set(quantities), factory_id, lock=True, require_published=False
            )
            for assignment_id, quantity in quantities.items():
                if quantity:
                    session.add(
                        QuantityLedger(
                            order_assignment_id=assignment_id,
                            source_type="SHIPMENT_VOID",
                            source_id=draft_id,
                            quantity_delta=-quantity,
                            actor_id=actor_id,
                            created_at=current,
                        )
                    )
            for order in {v[2].order_id: v[2] for v in assignments.values()}.values():
                if order.lifecycle == "COMPLETED":
                    order.lifecycle = "PUBLISHED"
                    order.completed_at = None
                    order.completed_by = None
                    order.version += 1
                    order.updated_by = actor_id
                    order.updated_at = current
                    session.add(
                        OrderCompletionRecord(
                            order_id=order.order_id,
                            action="REOPEN",
                            reason=f"发货单 {original.shipment_no} 撤回",
                            actor_id=actor_id,
                            source_terminal="factory-mini",
                            before_lifecycle="COMPLETED",
                            after_lifecycle="PUBLISHED",
                            quantity_snapshot={"shipmentId": shipment_id},
                            created_at=current,
                        )
                    )
                session.add(
                    AuditLog(
                        request_id=idempotency_key[:64],
                        action="shipment_withdrawn",
                        target_type="order",
                        target_id=order.order_id,
                        actor_id=actor_id,
                        source_terminal="factory-mini",
                        changes={"shipmentId": shipment_id, "reason": reason, "draftId": draft_id},
                    )
                )
            receipt_history = asdict(self._receipt_snapshot(session, shipment_id))
            # These drafts have no confirmation timestamps; normalize the snapshot to JSON.
            session.add(
                AuditLog(
                    request_id=idempotency_key[:64],
                    action="shipment_withdrawn",
                    target_type="shipment",
                    target_id=shipment_id,
                    actor_id=actor_id,
                    source_terminal="factory-mini",
                    changes={
                        "reason": reason,
                        "draftId": draft_id,
                        "receiptDraft": receipt_history,
                    },
                )
            )
            if receipt:
                session.execute(
                    delete(ShipmentReceiptItem).where(
                        ShipmentReceiptItem.shipment_id == shipment_id
                    )
                )
                receipt.version += 1
            else:
                session.add(
                    ShipmentReceipt(
                        shipment_id=shipment_id,
                        status="DRAFT",
                        version=1,
                        saved_by=actor_id,
                        saved_at=current,
                    )
                )
            original.status = "WITHDRAWN"
            original.version += 1
            session.add(
                OutboxMessage(
                    event_type="shipment.withdrawn",
                    aggregate_type="shipment",
                    aggregate_id=shipment_id,
                    dedupe_key=f"shipment-withdrawn:{draft_id}",
                    payload={
                        "shipmentId": shipment_id,
                        "factShipmentId": history_id,
                        "reason": reason,
                        "actorId": actor_id,
                        "shipmentNo": original.shipment_no,
                        "occurredAt": current.isoformat(),
                        "quantity": sum(quantities.values()),
                    },
                    status="pending",
                    available_at=current,
                )
            )
            session.flush()
            return self._detail_snapshot(session, original)

    def get_withdrawal_draft(
        self, *, shipment_id: str, actor_id: str, factory_id: str
    ) -> ShipmentDraftSnapshot:
        with self._sessions() as session:
            draft = session.scalar(
                select(Shipment).where(
                    Shipment.source_shipment_id == shipment_id,
                    Shipment.status == "DRAFT",
                    Shipment.deleted_at.is_(None),
                )
            )
            if draft is None:
                raise ShipmentNotFound("withdrawal draft not found")
            draft = self._owned_shipment(
                session, draft.shipment_id, actor_id, factory_id, lock=False
            )
            result = self._detail_snapshot(session, draft)
            original = session.get(Shipment, shipment_id)
            return replace(result, shipment_no=original.shipment_no if original else None)

    def _resubmit(
        self,
        session: Session,
        draft: Shipment,
        actor_id: str,
        expected_version: int | None,
        key: str,
        current: datetime,
    ) -> ShipmentDraftSnapshot:
        original = session.get(Shipment, draft.source_shipment_id)
        if original is None:
            raise ShipmentNotFound("shipment not found")
        scope = f"shipment.resubmit:{draft.shipment_id}"
        previous = session.scalar(
            select(IdempotencyRecord).where(
                IdempotencyRecord.scope == scope, IdempotencyRecord.idempotency_key == key
            )
        )
        if previous:
            return self._detail_snapshot(session, original)
        if draft.status != "DRAFT" or original.status != "WITHDRAWN":
            raise ShipmentConflict("发货单已重新提交，不能继续修改")
        if expected_version != draft.version:
            raise ShipmentConflict("这张发货单已被其他人修改，请重新加载最新内容后再提交。")
        boxes = self._box_inputs(session, draft.shipment_id)
        self._validate_boxes(boxes)
        totals: dict[int, int] = defaultdict(int)
        for box in boxes:
            for item in box.items:
                totals[item.assignment_id] += item.quantity
        assignments = self._load_assignments(session, set(totals), draft.factory_id, lock=True)
        session.add(IdempotencyRecord(scope=scope, idempotency_key=key, status="completed"))
        for aid, quantity in totals.items():
            _, line, order = assignments[aid]
            session.add(
                ShipmentLine(
                    shipment_id=draft.shipment_id,
                    order_assignment_id=aid,
                    quantity=quantity,
                    order_no_snapshot=order.order_no,
                    sku_id_snapshot=line.sku_id_snapshot,
                    product_name_snapshot=line.product_name_snapshot,
                    properties_value_snapshot=line.properties_value_snapshot,
                )
            )
            session.add(
                QuantityLedger(
                    order_assignment_id=aid,
                    source_type="SHIPMENT",
                    source_id=draft.shipment_id,
                    quantity_delta=quantity,
                    actor_id=actor_id,
                    created_at=current,
                )
            )
            session.add(
                AuditLog(
                    request_id=key[:64],
                    action="shipment_resubmitted",
                    target_type="order",
                    target_id=order.order_id,
                    actor_id=actor_id,
                    source_terminal="factory-mini",
                    changes={"shipmentId": original.shipment_id, "quantity": quantity},
                )
            )
        session.flush()
        box_ids = select(ShipmentBox.box_id).where(ShipmentBox.shipment_id == original.shipment_id)
        session.execute(delete(ShipmentBoxItem).where(ShipmentBoxItem.box_id.in_(box_ids)))
        session.execute(delete(ShipmentBox).where(ShipmentBox.shipment_id == original.shipment_id))
        session.execute(
            delete(ShipmentLine).where(ShipmentLine.shipment_id == original.shipment_id)
        )
        session.execute(
            delete(ShipmentFile).where(ShipmentFile.shipment_id == original.shipment_id)
        )
        self._copy_contents(session, draft, original)
        original.note = draft.note
        original.status = draft.status = "SHIPPED"
        original.submitted_by = draft.submitted_by = actor_id
        original.submitted_at = draft.submitted_at = current
        original.business_date = draft.business_date = current.astimezone(BUSINESS_TIME_ZONE).date()
        original.version += 1
        draft.version += 1
        session.add(
            AuditLog(
                request_id=key[:64],
                action="shipment_resubmitted",
                target_type="shipment",
                target_id=original.shipment_id,
                actor_id=actor_id,
                source_terminal="factory-mini",
                changes={"draftId": draft.shipment_id},
            )
        )
        session.add(
            OutboxMessage(
                event_type="shipment.submitted",
                aggregate_type="shipment",
                aggregate_id=original.shipment_id,
                dedupe_key=f"shipment:{draft.shipment_id}:resubmitted",
                payload={
                    "shipmentId": original.shipment_id,
                    "factShipmentId": draft.shipment_id,
                    "shipmentNo": original.shipment_no,
                },
                status="pending",
                available_at=current,
            )
        )
        session.flush()
        return self._detail_snapshot(session, original)

    def request_void(
        self,
        *,
        actor_id: str,
        factory_id: str,
        shipment_id: str,
        reason: str,
        idempotency_key: str,
        now: datetime | None = None,
    ) -> ShipmentVoidRequestSnapshot:
        normalized_reason = reason.strip()
        if not normalized_reason:
            raise ShipmentValidationError("withdrawal reason is required")
        if len(normalized_reason) > 500:
            raise ShipmentValidationError("withdrawal reason is too long")
        current = now or datetime.now(UTC)
        with self._sessions.begin() as session:
            self._receipt_shipment(session, shipment_id)
            existing = session.scalar(
                select(ShipmentVoidRequest).where(
                    ShipmentVoidRequest.requested_by == actor_id,
                    ShipmentVoidRequest.idempotency_key == idempotency_key,
                )
            )
            if existing is not None:
                if existing.shipment_id != shipment_id:
                    raise ShipmentConflict("Idempotency-Key was used for another shipment")
                return self._void_request_snapshot(session, existing)

            shipment = session.scalar(
                select(Shipment)
                .where(
                    Shipment.shipment_id == shipment_id,
                    Shipment.factory_id == factory_id,
                    Shipment.deleted_at.is_(None),
                )
                .with_for_update()
            )
            if shipment is None:
                raise ShipmentNotFound("shipment not found")
            if shipment.status != "SHIPPED":
                raise ShipmentConflict("shipment cannot request withdrawal")

            request = ShipmentVoidRequest(
                request_id=str(uuid4()),
                shipment_id=shipment_id,
                active_shipment_id=shipment_id,
                requested_by=actor_id,
                reason=normalized_reason,
                status="PENDING",
                idempotency_key=idempotency_key,
                created_at=current,
            )
            session.add(request)
            shipment.status = "VOID_PENDING"
            session.add(
                AuditLog(
                    request_id=idempotency_key[:64],
                    action="shipment_void_requested",
                    target_type="shipment",
                    target_id=shipment_id,
                    changes={"requestId": request.request_id, "reason": normalized_reason},
                    actor_id=actor_id,
                    source_terminal="factory-mini",
                )
            )
            session.add(
                OutboxMessage(
                    event_type="shipment.void_requested",
                    aggregate_type="shipment",
                    aggregate_id=shipment_id,
                    dedupe_key=f"shipment-void-request:{request.request_id}",
                    payload={"shipmentId": shipment_id, "requestId": request.request_id},
                    status="pending",
                    available_at=current,
                )
            )
            session.flush()
            return self._void_request_snapshot(session, request)

    def review_void(
        self,
        *,
        actor_id: str,
        request_id: str,
        approve: bool,
        comment: str,
        idempotency_key: str,
        now: datetime | None = None,
    ) -> ShipmentVoidRequestSnapshot:
        normalized_comment = comment.strip()
        if not approve and not normalized_comment:
            raise ShipmentValidationError("rejection comment is required")
        if len(normalized_comment) > 500:
            raise ShipmentValidationError("review comment is too long")
        current = now or datetime.now(UTC)
        target_status = "APPROVED" if approve else "REJECTED"
        with self._sessions.begin() as session:
            session.scalar(
                select(Shipment)
                .where(
                    Shipment.shipment_id
                    == select(ShipmentVoidRequest.shipment_id)
                    .where(ShipmentVoidRequest.request_id == request_id)
                    .scalar_subquery()
                )
                .with_for_update()
            )
            request = session.scalar(
                select(ShipmentVoidRequest)
                .where(ShipmentVoidRequest.request_id == request_id)
                .with_for_update()
            )
            if request is None:
                raise ShipmentNotFound("withdrawal request not found")
            if request.status != "PENDING":
                if request.status == target_status:
                    return self._void_request_snapshot(session, request)
                raise ShipmentConflict("withdrawal request was already reviewed")
            shipment = session.scalar(
                select(Shipment)
                .where(Shipment.shipment_id == request.shipment_id)
                .with_for_update()
            )
            if shipment is None or shipment.status != "VOID_PENDING":
                raise ShipmentConflict("shipment withdrawal state changed")

            if approve:
                existing_return = session.scalar(
                    select(ShipmentReturnEvent.event_id)
                    .where(ShipmentReturnEvent.shipment_id == shipment.shipment_id)
                    .limit(1)
                )
                if existing_return is not None:
                    raise ShipmentConflict("returned shipment cannot be fully voided")
                lines = list(
                    session.scalars(
                        select(ShipmentLine)
                        .where(ShipmentLine.shipment_id == shipment.shipment_id)
                        .with_for_update()
                    )
                )
                if not lines:
                    raise ShipmentConflict("shipment has no reversible quantity")
                assignments = self._load_assignments(
                    session,
                    {line.order_assignment_id for line in lines},
                    shipment.factory_id,
                    lock=True,
                    require_published=False,
                )
                effective = self._effective_line_quantities(session, shipment.shipment_id)
                affected_orders: dict[str, Order] = {}
                for line in lines:
                    quantity = effective[line.order_assignment_id]
                    if quantity == 0:
                        continue
                    _assignment, _order_line, order = assignments[line.order_assignment_id]
                    affected_orders[order.order_id] = order
                    session.add(
                        QuantityLedger(
                            order_assignment_id=line.order_assignment_id,
                            source_type="SHIPMENT_VOID",
                            source_id=request.request_id,
                            quantity_delta=-quantity,
                            actor_id=actor_id,
                            created_at=current,
                        )
                    )
                    session.add(
                        AuditLog(
                            request_id=idempotency_key[:64],
                            action="shipment_void_approved",
                            target_type="order",
                            target_id=order.order_id,
                            changes={
                                "shipmentId": shipment.shipment_id,
                                "requestId": request.request_id,
                                "quantity": -quantity,
                                "orderAssignmentId": line.order_assignment_id,
                            },
                            actor_id=actor_id,
                            source_terminal="admin-web",
                        )
                    )
                for order in affected_orders.values():
                    if order.lifecycle != "COMPLETED":
                        continue
                    order.lifecycle = "PUBLISHED"
                    order.version += 1
                    order.completed_at = None
                    order.completed_by = None
                    order.updated_at = current
                    order.updated_by = actor_id
                    session.add(
                        OrderCompletionRecord(
                            order_id=order.order_id,
                            action="REOPEN",
                            reason=f"发货单 {shipment.shipment_no or shipment.shipment_id} 已作废",
                            actor_id=actor_id,
                            source_terminal="admin-web",
                            before_lifecycle="COMPLETED",
                            after_lifecycle="PUBLISHED",
                            quantity_snapshot={"shipmentId": shipment.shipment_id},
                            created_at=current,
                        )
                    )
                session.add(
                    AuditLog(
                        request_id=idempotency_key[:64],
                        action="shipment_void_approved",
                        target_type="shipment",
                        target_id=shipment.shipment_id,
                        actor_id=actor_id,
                        source_terminal="admin-web",
                        changes={"requestId": request_id, "quantity": -sum(effective.values())},
                    )
                )
                shipment.status = "VOIDED"
            else:
                shipment.status = "SHIPPED"

            request.status = target_status
            request.active_shipment_id = None
            request.reviewed_by = actor_id
            request.reviewed_at = current
            request.review_comment = normalized_comment or None
            session.add(
                OutboxMessage(
                    event_type=("shipment.void_approved" if approve else "shipment.void_rejected"),
                    aggregate_type="shipment",
                    aggregate_id=shipment.shipment_id,
                    dedupe_key=f"shipment-void-review:{request.request_id}:{target_status}",
                    payload={
                        "shipmentId": shipment.shipment_id,
                        "requestId": request.request_id,
                        "status": target_status,
                    },
                    status="pending",
                    available_at=current,
                )
            )
            session.flush()
            return self._void_request_snapshot(session, request)

    def return_shipment(
        self,
        *,
        actor_id: str,
        shipment_id: str,
        lines: list[ShipmentReturnInput],
        reason: str,
        idempotency_key: str,
        now: datetime | None = None,
    ) -> tuple[ShipmentReturnEventSnapshot, bool]:
        normalized_reason = reason.strip()
        if not normalized_reason:
            raise ShipmentValidationError("return reason is required")
        if len(normalized_reason) > 500:
            raise ShipmentValidationError("return reason is too long")
        if not lines or len({line.shipment_line_id for line in lines}) != len(lines):
            raise ShipmentValidationError("return lines must be unique")
        if any(type(line.quantity) is not int or line.quantity <= 0 for line in lines):
            raise ShipmentValidationError("return quantities must be positive integers")
        current = now or datetime.now(UTC)
        return_date = current.astimezone(BUSINESS_TIME_ZONE).date()
        with self._sessions.begin() as session:
            self._receipt_shipment(session, shipment_id)
            existing = session.scalar(
                select(ShipmentReturnEvent).where(
                    ShipmentReturnEvent.returned_by == actor_id,
                    ShipmentReturnEvent.idempotency_key == idempotency_key,
                )
            )
            if existing is not None:
                if existing.shipment_id != shipment_id:
                    raise ShipmentConflict("Idempotency-Key was used for another shipment")
                return self._return_event_snapshot(session, existing), False

            shipment = session.scalar(
                select(Shipment)
                .where(Shipment.shipment_id == shipment_id, Shipment.deleted_at.is_(None))
                .with_for_update()
            )
            if shipment is None:
                raise ShipmentNotFound("shipment not found")
            if shipment.status != "SHIPPED":
                raise ShipmentConflict("shipment is not returnable")

            effective = self._effective_line_quantities(session, shipment_id)
            line_ids = {line.shipment_line_id for line in lines}
            shipment_lines = list(
                session.scalars(
                    select(ShipmentLine)
                    .where(
                        ShipmentLine.shipment_id == shipment_id,
                        ShipmentLine.line_id.in_(line_ids),
                    )
                    .with_for_update()
                )
            )
            if {line.line_id for line in shipment_lines} != line_ids:
                raise ShipmentNotFound("shipment line not found")
            input_by_id = {line.shipment_line_id: line for line in lines}
            assignments = self._load_assignments(
                session,
                {line.order_assignment_id for line in shipment_lines},
                shipment.factory_id,
                lock=True,
                require_published=False,
            )
            event = ShipmentReturnEvent(
                event_id=str(uuid4()),
                shipment_id=shipment_id,
                returned_by=actor_id,
                return_date=return_date,
                reason=normalized_reason,
                idempotency_key=idempotency_key,
                created_at=current,
            )
            session.add(event)
            affected_orders: dict[str, Order] = {}
            for shipment_line in shipment_lines:
                return_quantity = input_by_id[shipment_line.line_id].quantity
                returned_quantity = int(
                    session.scalar(
                        select(func.coalesce(func.sum(ShipmentReturnLine.quantity), 0)).where(
                            ShipmentReturnLine.shipment_line_id == shipment_line.line_id
                        )
                    )
                    or 0
                )
                if (
                    return_quantity
                    > effective[shipment_line.order_assignment_id] - returned_quantity
                ):
                    raise ShipmentConflict("return quantity exceeds current returnable quantity")
                assignment, _order_line, order = assignments[shipment_line.order_assignment_id]
                affected_orders[order.order_id] = order
                system_quantity = int(
                    session.scalar(
                        select(func.coalesce(func.sum(QuantityLedger.quantity_delta), 0)).where(
                            QuantityLedger.order_assignment_id == shipment_line.order_assignment_id
                        )
                    )
                    or 0
                )
                before_quantity = assignment.initial_shipped_quantity + system_quantity
                after_quantity = before_quantity - return_quantity
                session.add(
                    ShipmentReturnLine(
                        event_id=event.event_id,
                        shipment_line_id=shipment_line.line_id,
                        quantity=return_quantity,
                        before_shipped_quantity=before_quantity,
                        after_shipped_quantity=after_quantity,
                    )
                )
                session.add(
                    QuantityLedger(
                        order_assignment_id=shipment_line.order_assignment_id,
                        source_type="SHIPMENT_RETURN",
                        source_id=event.event_id,
                        quantity_delta=-return_quantity,
                        actor_id=actor_id,
                        created_at=current,
                    )
                )
                session.add(
                    AuditLog(
                        request_id=idempotency_key[:64],
                        action="shipment_line_returned",
                        target_type="order",
                        target_id=order.order_id,
                        changes={
                            "shipmentId": shipment_id,
                            "eventId": event.event_id,
                            "shipmentLineId": shipment_line.line_id,
                            "quantity": return_quantity,
                            "before": before_quantity,
                            "after": after_quantity,
                            "reason": normalized_reason,
                        },
                        actor_id=actor_id,
                        source_terminal="admin-web",
                    )
                )
            for order in affected_orders.values():
                if order.lifecycle != "COMPLETED":
                    continue
                order.lifecycle = "PUBLISHED"
                order.version += 1
                order.completed_at = None
                order.completed_by = None
                order.updated_at = current
                order.updated_by = actor_id
                session.add(
                    OrderCompletionRecord(
                        order_id=order.order_id,
                        action="REOPEN",
                        reason=f"发货单 {shipment.shipment_no or shipment.shipment_id} 发生退回",
                        actor_id=actor_id,
                        source_terminal="admin-web",
                        before_lifecycle="COMPLETED",
                        after_lifecycle="PUBLISHED",
                        quantity_snapshot={"shipmentId": shipment_id, "eventId": event.event_id},
                        created_at=current,
                    )
                )
            session.add(
                OutboxMessage(
                    event_type="shipment.returned",
                    aggregate_type="shipment",
                    aggregate_id=shipment_id,
                    dedupe_key=f"shipment-return:{event.event_id}",
                    payload={"shipmentId": shipment_id, "eventId": event.event_id},
                    status="pending",
                    available_at=current,
                )
            )
            session.flush()
            return self._return_event_snapshot(session, event), True

    def has_valid_shipments(self, *, order_id: str) -> bool:
        with self._sessions() as session:
            return bool(
                session.scalar(
                    select(ShipmentLine.line_id)
                    .join(
                        OrderAssignment,
                        OrderAssignment.order_assignment_id == ShipmentLine.order_assignment_id,
                    )
                    .join(OrderLine, OrderLine.order_line_id == OrderAssignment.order_line_id)
                    .join(Shipment, Shipment.shipment_id == ShipmentLine.shipment_id)
                    .where(
                        OrderLine.order_id == order_id,
                        Shipment.status.in_(("SHIPPED", "VOID_PENDING")),
                        Shipment.source_shipment_id.is_(None),
                    )
                    .limit(1)
                )
            )

    def export_shipment(self, *, shipment_id: str) -> ShipmentExportResult:
        if self._workbook_renderer is None:
            raise ShipmentValidationError("shipment workbook renderer is unavailable")
        with self._sessions() as session:
            shipment = session.get(Shipment, shipment_id)
            if (
                shipment is None
                or shipment.status not in ("SHIPPED", "VOID_PENDING")
                or shipment.source_shipment_id is not None
                or shipment.deleted_at is not None
                or shipment.business_date is None
                or shipment.shipment_no is None
            ):
                raise ShipmentNotFound("shipment not found")
            factory = session.get(Factory, shipment.factory_id)
            if factory is None:
                raise ShipmentNotFound("shipment factory not found")
            rows = session.execute(
                select(ShipmentBox, ShipmentBoxItem, ShipmentLine)
                .join(ShipmentBoxItem, ShipmentBoxItem.box_id == ShipmentBox.box_id)
                .join(
                    ShipmentLine,
                    (ShipmentLine.shipment_id == ShipmentBox.shipment_id)
                    & (
                        ShipmentLine.order_assignment_id
                        == ShipmentBoxItem.order_assignment_id
                    ),
                )
                .where(ShipmentBox.shipment_id == shipment_id)
                .order_by(ShipmentBox.box_no, ShipmentBoxItem.item_id)
            ).all()
            if not rows:
                raise ShipmentConflict("shipment has no exportable contents")
            snapshot = ShipmentWorkbookSnapshot(
                business_date=shipment.business_date,
                total_boxes=len({box.box_no for box, _item, _line in rows}),
                lines=[
                    ShipmentWorkbookLine(
                        order_no=line.order_no_snapshot,
                        box_no=str(box.box_no),
                        sku_id=line.sku_id_snapshot,
                        product_name=line.product_name_snapshot,
                        properties_value=line.properties_value_snapshot,
                        packed_quantity=item.quantity,
                        total_quantity=item.quantity,
                    )
                    for box, item, line in rows
                ],
            )
            content = self._workbook_renderer.render(snapshot)
            safe_factory_name = re.sub(r"[\\/:*?\"<>|\x00-\x1f]+", "_", factory.factory_name)
            filename = (
                f"{safe_factory_name}_{shipment.business_date:%Y-%m-%d}_"
                f"{shipment.shipment_no}.xlsx"
            )
            return ShipmentExportResult(filename=filename, content=content)

    def has_pending_void_requests(self, *, order_id: str) -> bool:
        with self._sessions() as session:
            return bool(
                session.scalar(
                    select(ShipmentVoidRequest.request_id)
                    .join(Shipment, Shipment.shipment_id == ShipmentVoidRequest.shipment_id)
                    .join(ShipmentLine, ShipmentLine.shipment_id == Shipment.shipment_id)
                    .join(
                        OrderAssignment,
                        OrderAssignment.order_assignment_id == ShipmentLine.order_assignment_id,
                    )
                    .join(OrderLine, OrderLine.order_line_id == OrderAssignment.order_line_id)
                    .where(
                        OrderLine.order_id == order_id,
                        ShipmentVoidRequest.status == "PENDING",
                    )
                    .limit(1)
                )
            )

    @staticmethod
    def _preferred_order_query(*, order_id: str, factory_id: str) -> Select[tuple[str]]:
        return (
            select(Order.order_id)
            .join(OrderLine, OrderLine.order_id == Order.order_id)
            .join(OrderAssignment, OrderAssignment.order_line_id == OrderLine.order_line_id)
            .where(
                Order.order_id == order_id,
                Order.lifecycle == "PUBLISHED",
                Order.deleted_at.is_(None),
                OrderAssignment.factory_id == factory_id,
            )
            .limit(1)
        )

    @staticmethod
    def _snapshot(shipment: Shipment) -> ShipmentDraftSnapshot:
        return ShipmentDraftSnapshot(
            shipment_id=shipment.shipment_id,
            version=shipment.version,
            status=shipment.status,
            factory_id=shipment.factory_id,
            created_by=shipment.created_by,
            preferred_order_id=shipment.preferred_order_id,
            created_at=shipment.created_at,
        )

    @staticmethod
    def _validate_boxes(boxes: list[DraftBoxInput], *, allow_empty: bool = False) -> None:
        if not boxes or len({box.box_no for box in boxes}) != len(boxes):
            raise ShipmentValidationError("box numbers must be unique")
        for box in boxes:
            if (
                type(box.box_no) is not int or box.box_no <= 0
                or (not allow_empty and not box.items)
            ):
                raise ShipmentValidationError("each box requires contents")
            if len({item.assignment_id for item in box.items}) != len(box.items):
                raise ShipmentValidationError("duplicate assignment in box")
            if any(type(item.quantity) is not int or item.quantity <= 0 for item in box.items):
                raise ShipmentValidationError("box quantities must be positive integers")

    @staticmethod
    def _owned_shipment(
        session: Session, shipment_id: str, actor_id: str, factory_id: str, *, lock: bool
    ) -> Shipment:
        source_id = session.scalar(select(Shipment.source_shipment_id).where(
            Shipment.shipment_id == shipment_id))
        if source_id and lock:
            session.scalar(
                select(Shipment).where(Shipment.shipment_id == source_id).with_for_update()
            )
        query = select(Shipment).where(
            Shipment.shipment_id == shipment_id,
            Shipment.factory_id == factory_id,
            Shipment.deleted_at.is_(None),
        )
        if lock:
            query = query.with_for_update()
        shipment = session.scalar(query)
        if shipment is None:
            raise ShipmentNotFound("shipment not found")
        permitted = (actor_id in (shipment.created_by, shipment.submitted_by)
                     if shipment.source_shipment_id else shipment.created_by == actor_id)
        if not permitted:
            raise ShipmentNotFound("shipment not found")
        return shipment

    @staticmethod
    def _load_assignments(
        session: Session,
        assignment_ids: set[int],
        factory_id: str,
        *,
        lock: bool = False,
        require_published: bool = True,
    ) -> dict[int, tuple[OrderAssignment, OrderLine, Order]]:
        if not assignment_ids:
            raise ShipmentValidationError("shipment requires contents")
        query = (
            select(OrderAssignment, OrderLine, Order)
            .join(OrderLine, OrderLine.order_line_id == OrderAssignment.order_line_id)
            .join(Order, Order.order_id == OrderLine.order_id)
            .where(
                OrderAssignment.order_assignment_id.in_(assignment_ids),
                OrderAssignment.factory_id == factory_id,
                Order.deleted_at.is_(None),
            )
        )
        if require_published:
            query = query.where(Order.lifecycle == "PUBLISHED")
        if lock:
            query = query.order_by(
                Order.order_id, OrderAssignment.order_assignment_id
            ).with_for_update()
        rows = session.execute(query).all()
        result = {
            assignment.order_assignment_id: (assignment, line, order)
            for assignment, line, order in rows
        }
        if set(result) != assignment_ids:
            raise ShipmentNotFound("assignment is not available to this factory")
        return result

    @staticmethod
    def _box_inputs(session: Session, shipment_id: str) -> list[DraftBoxInput]:
        boxes = list(
            session.scalars(
                select(ShipmentBox)
                .where(ShipmentBox.shipment_id == shipment_id)
                .order_by(ShipmentBox.box_no)
            )
        )
        return [
            DraftBoxInput(
                box_no=box.box_no,
                group_key=box.group_key,
                items=[
                    DraftItemInput(assignment_id=item.order_assignment_id, quantity=item.quantity)
                    for item in session.scalars(
                        select(ShipmentBoxItem)
                        .where(ShipmentBoxItem.box_id == box.box_id)
                        .order_by(ShipmentBoxItem.item_id)
                    )
                ],
            )
            for box in boxes
        ]

    def _detail_snapshot(self, session: Session, shipment: Shipment) -> ShipmentDraftSnapshot:
        box_inputs = self._box_inputs(session, shipment.shipment_id)
        receipt_record = session.get(ShipmentReceipt, shipment.shipment_id)
        receipt = (
            self._receipt_snapshot(session, shipment.shipment_id)
            if receipt_record and receipt_record.status == "CONFIRMED"
            else None
        )
        box_item_ids = {
            (box.box_no, item.order_assignment_id): item.item_id
            for box, item in session.execute(
                select(ShipmentBox, ShipmentBoxItem)
                .join(ShipmentBoxItem)
                .where(ShipmentBox.shipment_id == shipment.shipment_id)
            )
        }
        confirmed_quantities = {i.box_item_id: i.quantity for i in receipt.items} if receipt else {}
        if receipt:
            box_inputs = [
                DraftBoxInput(
                    box.box_no,
                    box.group_key,
                    [
                        DraftItemInput(
                            item.assignment_id,
                            confirmed_quantities[box_item_ids[(box.box_no, item.assignment_id)]],
                        )
                        for item in box.items
                    ],
                )
                for box in box_inputs
            ]
        effective_lines = self._effective_line_quantities(session, shipment.shipment_id)
        assignment_ids = {item.assignment_id for box in box_inputs for item in box.items}
        assignments = (
            self._load_assignments(
                session,
                assignment_ids,
                shipment.factory_id,
                require_published=shipment.status == "DRAFT",
            )
            if assignment_ids
            else {}
        )
        factory = session.get(Factory, shipment.factory_id)
        persisted_lines = {
            line.order_assignment_id: line
            for line in session.scalars(
                select(ShipmentLine).where(ShipmentLine.shipment_id == shipment.shipment_id)
            )
        }
        returned_by_line = {
            int(line_id): int(quantity)
            for line_id, quantity in session.execute(
                select(
                    ShipmentReturnLine.shipment_line_id,
                    func.sum(ShipmentReturnLine.quantity),
                )
                .join(
                    ShipmentReturnEvent,
                    ShipmentReturnEvent.event_id == ShipmentReturnLine.event_id,
                )
                .where(ShipmentReturnEvent.shipment_id == shipment.shipment_id)
                .group_by(ShipmentReturnLine.shipment_line_id)
            )
        }
        boxes: list[ShipmentBoxSnapshot] = []
        totals: dict[int, int] = defaultdict(int)
        for box in box_inputs:
            items = []
            for item in box.items:
                assignment, line, order = assignments[item.assignment_id]
                persisted_line = persisted_lines.get(item.assignment_id)
                returned_quantity = (
                    returned_by_line.get(persisted_line.line_id, 0)
                    if persisted_line is not None
                    else 0
                )
                value = ShipmentLineSnapshot(
                    assignment_id=item.assignment_id,
                    order_id=order.order_id,
                    order_no=order.order_no,
                    sku_id=line.sku_id_snapshot,
                    product_name=line.product_name_snapshot,
                    properties_value=line.properties_value_snapshot,
                    quantity=item.quantity,
                    box_item_id=box_item_ids[(box.box_no, item.assignment_id)],
                    line_id=persisted_line.line_id if persisted_line is not None else None,
                    returned_quantity=returned_quantity,
                    returnable_quantity=(
                        max(
                            effective_lines.get(persisted_line.order_assignment_id, 0)
                            - returned_quantity,
                            0,
                        )
                        if persisted_line is not None
                        else 0
                    ),
                )
                items.append(value)
                totals[item.assignment_id] += item.quantity
            boxes.append(
                ShipmentBoxSnapshot(box_no=box.box_no, group_key=box.group_key, items=items)
            )
        lines = []
        for assignment_id, quantity in totals.items():
            _assignment, line, order = assignments[assignment_id]
            persisted_line = persisted_lines.get(assignment_id)
            returned_quantity = (
                returned_by_line.get(persisted_line.line_id, 0) if persisted_line is not None else 0
            )
            lines.append(
                ShipmentLineSnapshot(
                    assignment_id=assignment_id,
                    order_id=order.order_id,
                    order_no=order.order_no,
                    sku_id=line.sku_id_snapshot,
                    product_name=line.product_name_snapshot,
                    properties_value=line.properties_value_snapshot,
                    quantity=quantity,
                    line_id=persisted_line.line_id if persisted_line is not None else None,
                    returned_quantity=returned_quantity,
                    returnable_quantity=(
                        max(
                            effective_lines.get(persisted_line.order_assignment_id, 0)
                            - returned_quantity,
                            0,
                        )
                        if persisted_line is not None
                        else 0
                    ),
                )
            )
        void_request = session.scalar(
            select(ShipmentVoidRequest)
            .where(ShipmentVoidRequest.shipment_id == shipment.shipment_id)
            .order_by(ShipmentVoidRequest.created_at.desc(), ShipmentVoidRequest.request_id.desc())
            .limit(1)
        )
        return_events = list(
            session.scalars(
                select(ShipmentReturnEvent)
                .where(ShipmentReturnEvent.shipment_id == shipment.shipment_id)
                .order_by(ShipmentReturnEvent.created_at, ShipmentReturnEvent.event_id)
            )
        )
        file_rows = session.execute(
            select(ShipmentFile, StoredFile)
            .join(StoredFile, StoredFile.file_id == ShipmentFile.stored_file_id)
            .where(ShipmentFile.shipment_id == shipment.shipment_id)
            .order_by(ShipmentFile.display_order)
        ).all()
        return ShipmentDraftSnapshot(
            shipment_id=shipment.shipment_id,
            version=shipment.version,
            shipment_no=shipment.shipment_no,
            status=shipment.status,
            factory_id=shipment.factory_id,
            factory_name=factory.factory_name if factory is not None else "",
            created_by=shipment.created_by,
            preferred_order_id=shipment.preferred_order_id,
            business_date=shipment.business_date,
            note=shipment.note or "",
            total_boxes=len(boxes),
            total_quantity=sum(totals.values()),
            lines=lines,
            boxes=boxes,
            files=[self._file_snapshot(link, stored) for link, stored in file_rows],
            created_at=shipment.created_at,
            submitted_at=shipment.submitted_at,
            void_request=(
                self._void_request_snapshot(session, void_request)
                if void_request is not None
                else None
            ),
            return_events=[self._return_event_snapshot(session, item) for item in return_events],
            receipt=receipt,
            receipt_differences=[
                ShipmentLineSnapshot(
                    assignment_id=value.assignment_id,
                    order_id=value.order_id,
                    order_no=value.order_no,
                    sku_id=value.sku_id,
                    product_name=value.product_name,
                    properties_value=value.properties_value,
                    quantity=value.quantity - persisted_lines[value.assignment_id].quantity,
                )
                for value in lines
                if receipt and value.quantity != persisted_lines[value.assignment_id].quantity
            ],
            operations=[
                {
                    "action": log.action,
                    "reason": str(log.changes.get("reason", "")),
                    "actorName": actor.feishu_display_name or "工厂用户",
                    "createdAt": log.created_at.isoformat(),
                }
                for log, actor in session.execute(
                    select(AuditLog, User)
                    .join(User, User.user_id == AuditLog.actor_id)
                    .where(
                        AuditLog.target_type == "shipment",
                        AuditLog.target_id == shipment.shipment_id,
                        AuditLog.action.in_(
                            ["shipment_submitted", "shipment_withdrawn", "shipment_resubmitted"]
                        ),
                    )
                    .order_by(AuditLog.created_at)
                ).all()
            ],
        )

    @staticmethod
    def _validated_image_mime_type(*, content: bytes, declared_mime_type: str) -> str:
        if not content or len(content) > SHIPMENT_FILE_MAX_BYTES:
            raise ShipmentValidationError("shipment file size is invalid")
        try:
            with Image.open(BytesIO(content)) as image:
                image.verify()
                actual_mime_type = SHIPMENT_FILE_MIME_BY_FORMAT.get(image.format or "")
        except (UnidentifiedImageError, OSError, ValueError):
            actual_mime_type = None
        if actual_mime_type is None or actual_mime_type != declared_mime_type:
            raise ShipmentValidationError("shipment file type is invalid")
        return actual_mime_type

    @staticmethod
    def _file_snapshot(
        relationship: ShipmentFile,
        stored: StoredFile,
    ) -> ShipmentFileSnapshot:
        return ShipmentFileSnapshot(
            file_id=stored.file_id,
            filename=stored.original_filename,
            mime_type=stored.mime_type,
            size_bytes=stored.size_bytes,
            content_sha256=stored.content_sha256,
            display_order=relationship.display_order,
        )

    @staticmethod
    def _void_request_snapshot(
        session: Session, request: ShipmentVoidRequest
    ) -> ShipmentVoidRequestSnapshot:
        requester = session.get(User, request.requested_by)
        return ShipmentVoidRequestSnapshot(
            request_id=request.request_id,
            shipment_id=request.shipment_id,
            status=request.status,
            reason=request.reason,
            requested_by=request.requested_by,
            requested_by_name=(
                requester.feishu_display_name if requester is not None else request.requested_by
            ),
            requested_at=request.created_at,
            reviewed_by=request.reviewed_by,
            reviewed_at=request.reviewed_at,
            review_comment=request.review_comment,
        )

    @staticmethod
    def _return_event_snapshot(
        session: Session, event: ShipmentReturnEvent
    ) -> ShipmentReturnEventSnapshot:
        rows = session.execute(
            select(ShipmentReturnLine, ShipmentLine)
            .join(ShipmentLine, ShipmentLine.line_id == ShipmentReturnLine.shipment_line_id)
            .where(ShipmentReturnLine.event_id == event.event_id)
            .order_by(ShipmentReturnLine.return_line_id)
        ).all()
        return ShipmentReturnEventSnapshot(
            event_id=event.event_id,
            shipment_id=event.shipment_id,
            return_date=event.return_date,
            reason=event.reason,
            returned_by=event.returned_by,
            returned_at=event.created_at,
            lines=[
                ShipmentReturnLineSnapshot(
                    shipment_line_id=line.shipment_line_id,
                    order_no=shipment_line.order_no_snapshot,
                    sku_id=shipment_line.sku_id_snapshot,
                    product_name=shipment_line.product_name_snapshot,
                    properties_value=shipment_line.properties_value_snapshot,
                    quantity=line.quantity,
                    before_shipped_quantity=line.before_shipped_quantity,
                    after_shipped_quantity=line.after_shipped_quantity,
                )
                for line, shipment_line in rows
            ],
        )
