from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import Engine, delete
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import (
    Factory,
    Product,
    ProductVariant,
    RepairPreview,
    RepairPreviewLine,
    StoredFile,
    User,
)
from app.modules.repairs.preview import RepairPreviewService
from app.modules.repairs.workbook import InspectionWorkbookLine, InspectionWorkbookSnapshot


@pytest.fixture(autouse=True)
def clean_repair_preview_records(test_database_engine: Engine) -> Iterator[None]:
    def clean() -> None:
        with Session(test_database_engine) as session, session.begin():
            session.execute(delete(RepairPreviewLine))
            session.execute(delete(RepairPreview))
            session.execute(delete(StoredFile).where(StoredFile.file_id.in_([9001, 9002, 9003])))
            session.execute(
                delete(ProductVariant).where(ProductVariant.variant_id == "preview-variant")
            )
            session.execute(delete(Product).where(Product.product_id == "preview-product"))
            session.execute(delete(Factory).where(Factory.factory_id == "preview-factory"))
            session.execute(delete(User).where(User.user_id == "preview-admin"))

    clean()
    yield
    clean()


def test_service_persists_and_reads_ready_preview_with_24_hour_expiry(
    test_database_engine: Engine,
) -> None:
    now = datetime(2026, 8, 26, 1, 0, tzinfo=UTC)
    source_time = now.replace(tzinfo=None)
    with Session(test_database_engine) as session, session.begin():
        session.add_all(
            [
                User(
                    user_id="preview-admin",
                    role="admin",
                    is_super_admin=True,
                    is_enabled=True,
                    feishu_display_name="预览管理员",
                ),
                Factory(
                    factory_id="preview-factory",
                    supplier_number="PREVIEW-28",
                    factory_name="预览跃富",
                    factory_code="PF",
                    is_enabled=True,
                ),
                Product(
                    product_id="preview-product",
                    source_i_id="KQ26022",
                    name="小动物软檐鸭舌帽",
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
                variant_id="preview-variant",
                product_id="preview-product",
                source_sku_id="6941716599133",
                properties_value="兔兔奶糖S",
                is_available=True,
                source_modified_at=source_time,
                first_synced_at=source_time,
                last_synced_at=source_time,
            )
        )
        session.add(
            StoredFile(
                file_id=9001,
                bucket="repair-test",
                object_key="previews/source.xlsx",
                original_filename="E28质检.xlsx",
                mime_type=("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
                size_bytes=1234,
                content_sha256="a" * 64,
                uploaded_by="preview-admin",
            )
        )
    line = InspectionWorkbookLine(
        source_row=2,
        supplier_number="PREVIEW-28",
        factory_name="预览跃富",
        source_sku_id="6941716599133",
        source_product_id="KQ26022",
        product_name="小动物软檐鸭舌帽",
        properties_value="兔兔奶糖S",
        quantity=51,
        box_number="1号箱",
        reason=None,
    )
    snapshot = InspectionWorkbookSnapshot(
        supplier_number="PREVIEW-28",
        factory_name="预览跃富",
        total_quantity=51,
        box_numbers=("1号箱",),
        lines=(line,),
    )
    service = RepairPreviewService(
        sessionmaker(test_database_engine, class_=Session, expire_on_commit=False),
        clock=lambda: now,
    )

    created = service.create(
        snapshot=snapshot,
        original_file_id=9001,
        source_sha256="a" * 64,
        uploaded_by="preview-admin",
    )
    retrieved = service.get(created.preview_id)

    assert retrieved.status == "READY"
    assert retrieved.expires_at == datetime(2026, 8, 27, 1, 0)
    assert retrieved.factory_id == "preview-factory"
    assert retrieved.line_count == 1
    assert retrieved.box_count == 1
    assert retrieved.total_quantity == 51
    assert retrieved.validation_errors == ()
    assert len(retrieved.lines) == 1
    assert retrieved.lines[0].source_row == 2
    assert retrieved.lines[0].source_order == 1
    assert retrieved.lines[0].matched_product_id == "preview-product"
    assert retrieved.lines[0].matched_variant_id == "preview-variant"


def test_service_rejects_reading_an_expired_preview(
    test_database_engine: Engine,
) -> None:
    now = datetime(2026, 8, 27, 1, 0, tzinfo=UTC)
    with Session(test_database_engine) as session, session.begin():
        session.add(
            User(
                user_id="preview-admin",
                role="admin",
                is_super_admin=True,
                is_enabled=True,
                feishu_display_name="预览管理员",
            )
        )
        session.flush()
        session.add(
            StoredFile(
                file_id=9001,
                bucket="repair-test",
                object_key="previews/expired.xlsx",
                original_filename="已过期质检.xlsx",
                mime_type=("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
                size_bytes=1234,
                content_sha256="b" * 64,
                uploaded_by="preview-admin",
            )
        )
        session.flush()
        session.add(
            RepairPreview(
                preview_id="expired-preview",
                status="READY",
                original_file_id=9001,
                source_sha256="b" * 64,
                uploaded_by="preview-admin",
                factory_id=None,
                line_count=0,
                box_count=0,
                total_quantity=0,
                validation_errors=[],
                validation_warnings=[],
                expires_at=(now - timedelta(seconds=1)).replace(tzinfo=None),
            )
        )
    service = RepairPreviewService(
        sessionmaker(test_database_engine, class_=Session, expire_on_commit=False),
        clock=lambda: now,
    )

    with pytest.raises(ValueError, match="预览已失效，请重新上传质检 Excel"):
        service.get("expired-preview")


def test_service_replaces_an_old_preview_and_expires_it(
    test_database_engine: Engine,
) -> None:
    now = datetime(2026, 8, 26, 1, 0, tzinfo=UTC)
    source_time = now.replace(tzinfo=None)
    with Session(test_database_engine) as session, session.begin():
        session.add_all(
            [
                User(
                    user_id="preview-admin",
                    role="admin",
                    is_super_admin=True,
                    is_enabled=True,
                    feishu_display_name="预览管理员",
                ),
                Factory(
                    factory_id="preview-factory",
                    supplier_number="PREVIEW-28",
                    factory_name="预览跃富",
                    factory_code="PF",
                    is_enabled=True,
                ),
                Product(
                    product_id="preview-product",
                    source_i_id="KQ26022",
                    name="小动物软檐鸭舌帽",
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
                variant_id="preview-variant",
                product_id="preview-product",
                source_sku_id="6941716599133",
                properties_value="兔兔奶糖S",
                is_available=True,
                source_modified_at=source_time,
                first_synced_at=source_time,
                last_synced_at=source_time,
            )
        )
        session.add_all(
            [
                StoredFile(
                    file_id=9001,
                    bucket="repair-test",
                    object_key="previews/old-source.xlsx",
                    original_filename="旧质检.xlsx",
                    mime_type=("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
                    size_bytes=1234,
                    content_sha256="3" * 64,
                    uploaded_by="preview-admin",
                ),
                StoredFile(
                    file_id=9003,
                    bucket="repair-test",
                    object_key="previews/new-source.xlsx",
                    original_filename="新质检.xlsx",
                    mime_type=("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
                    size_bytes=2345,
                    content_sha256="5" * 64,
                    uploaded_by="preview-admin",
                ),
            ]
        )
        session.flush()
        session.add(
            RepairPreview(
                preview_id="old-preview",
                status="READY",
                original_file_id=9001,
                source_sha256="3" * 64,
                uploaded_by="preview-admin",
                factory_id="preview-factory",
                line_count=1,
                box_count=1,
                total_quantity=1,
                validation_errors=[],
                validation_warnings=[],
                expires_at=(now + timedelta(hours=24)).replace(tzinfo=None),
            )
        )
        session.flush()
        session.add(
            RepairPreviewLine(
                line_id=9101,
                preview_id="old-preview",
                source_sheet="Sheet1",
                source_row=2,
                source_order=1,
                box_number="1号箱",
                supplier_number="PREVIEW-28",
                factory_name="预览跃富",
                source_sku_id="6941716599133",
                source_product_id="KQ26022",
                product_name="小动物软檐鸭舌帽",
                properties_value="兔兔奶糖S",
                quantity=1,
                reason=None,
                matched_product_id="preview-product",
                matched_variant_id="preview-variant",
                validation_errors=[],
                validation_warnings=[],
            )
        )
    line = InspectionWorkbookLine(
        source_row=2,
        supplier_number="PREVIEW-28",
        factory_name="预览跃富",
        source_sku_id="6941716599133",
        source_product_id="KQ26022",
        product_name="小动物软檐鸭舌帽",
        properties_value="兔兔奶糖S",
        quantity=51,
        box_number="1号箱",
        reason=None,
    )
    snapshot = InspectionWorkbookSnapshot(
        supplier_number="PREVIEW-28",
        factory_name="预览跃富",
        total_quantity=51,
        box_numbers=("1号箱",),
        lines=(line,),
    )
    service = RepairPreviewService(
        sessionmaker(test_database_engine, class_=Session, expire_on_commit=False),
        clock=lambda: now,
    )

    replacement = service.create(
        snapshot=snapshot,
        original_file_id=9003,
        source_sha256="5" * 64,
        uploaded_by="preview-admin",
        replaces_preview_id="old-preview",
    )

    with pytest.raises(ValueError):
        service.get("old-preview")
    assert replacement.original_file_id == 9003
