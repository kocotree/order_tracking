from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import Engine, delete
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
    User,
)
from app.modules.repairs.confirmation import RepairConfirmationService


@pytest.fixture(autouse=True)
def clean_repair_confirmation_records(test_database_engine: Engine) -> Iterator[None]:
    def clean() -> None:
        with Session(test_database_engine) as session, session.begin():
            session.execute(delete(AuditLog).where(AuditLog.target_id == "confirm-repair"))
            session.execute(
                delete(OutboxMessage).where(OutboxMessage.aggregate_id == "confirm-repair")
            )
            session.execute(
                delete(IdempotencyRecord).where(
                    IdempotencyRecord.scope == "repair.confirm:confirm-admin"
                )
            )
            session.execute(
                delete(RepairInspectionLine).where(
                    RepairInspectionLine.repair_id == "confirm-repair"
                )
            )
            session.execute(delete(RepairOrder).where(RepairOrder.repair_id == "confirm-repair"))
            session.execute(
                delete(RepairPreviewLine).where(
                    RepairPreviewLine.preview_id.in_(
                        ["confirm-preview", "confirm-preview-duplicate"]
                    )
                )
            )
            session.execute(
                delete(RepairPreview).where(
                    RepairPreview.preview_id.in_(["confirm-preview", "confirm-preview-duplicate"])
                )
            )
            session.execute(
                delete(RepairNumberCounter).where(
                    RepairNumberCounter.business_date == date(2026, 8, 27)
                )
            )
            session.execute(delete(StoredFile).where(StoredFile.file_id.in_([9401, 9402, 9403])))
            session.execute(
                delete(ProductVariant).where(ProductVariant.variant_id == "confirm-variant")
            )
            session.execute(delete(Product).where(Product.product_id == "confirm-product"))
            session.execute(delete(Factory).where(Factory.factory_id == "confirm-factory"))
            session.execute(delete(User).where(User.user_id == "confirm-admin"))

    clean()
    yield
    clean()


def test_confirm_creates_an_incomplete_repair_with_formal_lines_and_files(
    test_database_engine: Engine,
) -> None:
    now = datetime(2026, 8, 26, 16, 30, tzinfo=UTC)
    source_time = now.replace(tzinfo=None)
    with Session(test_database_engine) as session, session.begin():
        session.add_all(
            [
                User(
                    user_id="confirm-admin",
                    role="admin",
                    is_super_admin=True,
                    is_enabled=True,
                    feishu_display_name="确认管理员",
                ),
                Factory(
                    factory_id="confirm-factory",
                    supplier_number="CONFIRM",
                    factory_name="确认测试工厂",
                    factory_code="CF",
                    is_enabled=True,
                ),
                Product(
                    product_id="confirm-product",
                    source_i_id="CONFIRM-PRODUCT",
                    name="确认测试产品",
                    is_available=True,
                    image_cache_status="missing",
                    source_modified_at=source_time,
                    first_synced_at=source_time,
                    last_synced_at=source_time,
                ),
            ]
        )
        session.flush()
        session.add(
            ProductVariant(
                variant_id="confirm-variant",
                product_id="confirm-product",
                source_sku_id="CONFIRM-SKU",
                properties_value="确认规格",
                is_available=True,
                source_modified_at=source_time,
                first_synced_at=source_time,
                last_synced_at=source_time,
            )
        )
        session.add(
            StoredFile(
                file_id=9401,
                bucket="repair-confirm",
                object_key="previews/confirm/source.xlsx",
                original_filename="确认质检.xlsx",
                mime_type=("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
                size_bytes=1234,
                content_sha256="9" * 64,
                uploaded_by="confirm-admin",
            )
        )
        session.flush()
        session.add(
            RepairPreview(
                preview_id="confirm-preview",
                status="READY",
                original_file_id=9401,
                source_sha256="9" * 64,
                uploaded_by="confirm-admin",
                factory_id="confirm-factory",
                line_count=1,
                box_count=1,
                total_quantity=7,
                validation_errors=[],
                validation_warnings=[],
                expires_at=(now + timedelta(hours=1)).replace(tzinfo=None),
            )
        )
        session.flush()
        session.add(
            RepairPreviewLine(
                line_id=9401,
                preview_id="confirm-preview",
                source_sheet="Sheet1",
                source_row=2,
                source_order=1,
                box_number="1号箱",
                supplier_number="CONFIRM",
                factory_name="确认测试工厂",
                source_sku_id="CONFIRM-SKU",
                source_product_id="CONFIRM-PRODUCT",
                product_name="确认测试产品",
                properties_value="确认规格",
                quantity=7,
                reason="车线问题",
                matched_product_id="confirm-product",
                matched_variant_id="confirm-variant",
                validation_errors=[],
                validation_warnings=[],
            )
        )
    service = RepairConfirmationService(
        sessionmaker(test_database_engine, class_=Session, expire_on_commit=False),
        clock=lambda: now,
        id_factory=lambda: "confirm-repair",
    )

    created = service.confirm(
        preview_id="confirm-preview",
        confirmed_by="confirm-admin",
        idempotency_key="confirm-request-1",
    )
    repeated = service.confirm(
        preview_id="confirm-preview",
        confirmed_by="confirm-admin",
        idempotency_key="confirm-request-1",
    )
    retrieved = service.get("confirm-repair")

    assert created == retrieved
    assert repeated == created
    assert retrieved.repair_no == "FX20260827-001"
    assert retrieved.status == "INCOMPLETE"
    assert retrieved.return_date == date(2026, 8, 27)
    assert retrieved.factory_id == "confirm-factory"
    assert retrieved.warehouse_return_quantity == 7
    assert retrieved.repaired_quantity == 0
    assert retrieved.scrapped_quantity == 0
    assert retrieved.returned_quantity == 0
    assert retrieved.original_file_id == 9401
    assert len(retrieved.lines) == 1
    assert retrieved.lines[0].source_row == 2
    assert retrieved.lines[0].source_order == 1
    assert retrieved.lines[0].box_number == "1号箱"
    assert retrieved.lines[0].warehouse_return_quantity == 7
    assert retrieved.lines[0].reason == "车线问题"

    with Session(test_database_engine) as session, session.begin():
        session.add(
            StoredFile(
                file_id=9403,
                bucket="repair-confirm",
                object_key="previews/confirm/duplicate.xlsx",
                original_filename="重复质检.xlsx",
                mime_type=("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
                size_bytes=1234,
                content_sha256="9" * 64,
                uploaded_by="confirm-admin",
            )
        )
        session.flush()
        session.add(
            RepairPreview(
                preview_id="confirm-preview-duplicate",
                status="READY",
                original_file_id=9403,
                source_sha256="9" * 64,
                uploaded_by="confirm-admin",
                factory_id="confirm-factory",
                line_count=1,
                box_count=1,
                total_quantity=7,
                validation_errors=[],
                validation_warnings=[],
                expires_at=(now + timedelta(hours=1)).replace(tzinfo=None),
            )
        )
        session.flush()
        session.add(
            RepairPreviewLine(
                line_id=9403,
                preview_id="confirm-preview-duplicate",
                source_sheet="Sheet1",
                source_row=2,
                source_order=1,
                box_number="1号箱",
                supplier_number="CONFIRM",
                factory_name="确认测试工厂",
                source_sku_id="CONFIRM-SKU",
                source_product_id="CONFIRM-PRODUCT",
                product_name="确认测试产品",
                properties_value="确认规格",
                quantity=7,
                reason=None,
                matched_product_id="confirm-product",
                matched_variant_id="confirm-variant",
                validation_errors=[],
                validation_warnings=[],
            )
        )

    with pytest.raises(ValueError, match="FX20260827-001"):
        service.confirm(
            preview_id="confirm-preview-duplicate",
            confirmed_by="confirm-admin",
            idempotency_key="confirm-request-duplicate",
        )
