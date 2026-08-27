from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import RepairPreview, RepairPreviewLine, StoredFile
from app.modules.repairs.matching import InspectionCatalogMatcher
from app.modules.repairs.workbook import InspectionWorkbookSnapshot


class RepairPreviewNotFound(ValueError):
    pass


class RepairPreviewExpired(ValueError):
    pass


class RepairPreviewLocked(ValueError):
    pass


class RepairPreviewLineNotFound(ValueError):
    pass


class RepairPreviewStoredFileNotFound(ValueError):
    pass


@dataclass(frozen=True)
class RepairPreviewLineView:
    line_id: int
    source_row: int
    source_order: int
    supplier_number: str
    factory_name: str
    source_sku_id: str
    source_product_id: str
    product_name: str
    properties_value: str
    quantity: int
    box_number: str
    reason: str | None
    matched_product_id: str | None
    matched_variant_id: str | None


@dataclass(frozen=True)
class RepairPreviewView:
    preview_id: str
    status: str
    expires_at: datetime
    original_file_id: int
    original_filename: str
    factory_id: str | None
    factory_name: str
    line_count: int
    box_count: int
    total_quantity: int
    validation_errors: tuple[dict[str, str | int], ...]
    lines: tuple[RepairPreviewLineView, ...]


class RepairPreviewService:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._session_factory = session_factory
        self._matcher = InspectionCatalogMatcher(session_factory)
        self._clock = clock

    def create(
        self,
        *,
        snapshot: InspectionWorkbookSnapshot,
        original_file_id: int,
        source_sha256: str,
        uploaded_by: str,
        replaces_preview_id: str | None = None,
    ) -> RepairPreviewView:
        match = self._matcher.match(snapshot)
        now = self._clock().astimezone(UTC).replace(tzinfo=None)
        preview_id = str(uuid4())
        status = "READY" if not match.issues else "INVALID"
        matched_by_row = {line.source_line.source_row: line for line in match.lines}
        with self._session_factory() as session, session.begin():
            if replaces_preview_id is not None:
                replaced_preview = session.get(RepairPreview, replaces_preview_id)
                if replaced_preview is None:
                    raise RepairPreviewNotFound(replaces_preview_id)
                if replaced_preview.status == "CONFIRMED":
                    raise RepairPreviewLocked("返修单已创建，不能重新上传质检 Excel")
                for stored_file in session.scalars(
                    select(StoredFile).where(
                        StoredFile.file_id == replaced_preview.original_file_id
                    )
                ):
                    stored_file.replaced_at = now
                replaced_preview.expires_at = now
            session.add(
                RepairPreview(
                    preview_id=preview_id,
                    status=status,
                    original_file_id=original_file_id,
                    source_sha256=source_sha256,
                    uploaded_by=uploaded_by,
                    factory_id=match.factory_id,
                    line_count=len(snapshot.lines),
                    box_count=len(snapshot.box_numbers),
                    total_quantity=snapshot.total_quantity,
                    validation_errors=list(match.issues),
                    validation_warnings=[],
                    expires_at=now + timedelta(hours=24),
                )
            )
            for source_order, line in enumerate(snapshot.lines, 1):
                matched = matched_by_row.get(line.source_row)
                line_errors = [
                    issue for issue in match.issues if issue.get("row") == line.source_row
                ]
                session.add(
                    RepairPreviewLine(
                        preview_id=preview_id,
                        source_sheet="Sheet1",
                        source_row=line.source_row,
                        source_order=source_order,
                        box_number=line.box_number,
                        supplier_number=line.supplier_number,
                        factory_name=line.factory_name,
                        source_sku_id=line.source_sku_id,
                        source_product_id=line.source_product_id,
                        product_name=line.product_name,
                        properties_value=line.properties_value,
                        quantity=line.quantity,
                        reason=line.reason,
                        matched_product_id=matched.product_id if matched else None,
                        matched_variant_id=matched.variant_id if matched else None,
                        validation_errors=line_errors,
                        validation_warnings=[],
                    )
                )
        return self.get(preview_id)

    def get(self, preview_id: str) -> RepairPreviewView:
        with self._session_factory() as session:
            preview = session.get(RepairPreview, preview_id)
            if preview is None:
                raise RepairPreviewNotFound(preview_id)
            now = self._clock().astimezone(UTC).replace(tzinfo=None)
            if preview.expires_at <= now:
                raise RepairPreviewExpired("预览已失效，请重新上传质检 Excel")
            original_file = session.get(StoredFile, preview.original_file_id)
            if original_file is None:
                raise RepairPreviewStoredFileNotFound(str(preview.original_file_id))
            lines = session.scalars(
                select(RepairPreviewLine)
                .where(RepairPreviewLine.preview_id == preview_id)
                .order_by(RepairPreviewLine.source_order)
            ).all()
            return RepairPreviewView(
                preview_id=preview.preview_id,
                status=preview.status,
                expires_at=preview.expires_at,
                original_file_id=preview.original_file_id,
                original_filename=original_file.original_filename,
                factory_id=preview.factory_id,
                factory_name=lines[0].factory_name if lines else "",
                line_count=preview.line_count,
                box_count=preview.box_count,
                total_quantity=preview.total_quantity,
                validation_errors=tuple(preview.validation_errors),
                lines=tuple(
                    RepairPreviewLineView(
                        line_id=line.line_id,
                        source_row=line.source_row,
                        source_order=line.source_order,
                        supplier_number=line.supplier_number,
                        factory_name=line.factory_name,
                        source_sku_id=line.source_sku_id,
                        source_product_id=line.source_product_id,
                        product_name=line.product_name,
                        properties_value=line.properties_value,
                        quantity=line.quantity,
                        box_number=line.box_number,
                        reason=line.reason,
                        matched_product_id=line.matched_product_id,
                        matched_variant_id=line.matched_variant_id,
                    )
                    for line in lines
                ),
            )
