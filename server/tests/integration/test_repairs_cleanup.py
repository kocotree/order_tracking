from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import Engine, delete
from sqlalchemy.orm import Session, sessionmaker

from app.adapters.private_files import FakePrivateFileStore
from app.db.models import (
    Factory,
    RepairOrder,
    RepairPreview,
    RepairPreviewLine,
    StoredFile,
    User,
)
from app.modules.repairs.cleanup import RepairPreviewCleanupService
from app.modules.repairs.preview import RepairPreviewService


@pytest.fixture(autouse=True)
def clean_repair_cleanup_records(test_database_engine: Engine) -> Iterator[None]:
    def clean() -> None:
        with Session(test_database_engine) as session, session.begin():
            session.execute(delete(RepairOrder).where(RepairOrder.repair_id == "cleanup-formal"))
            session.execute(
                delete(RepairPreviewLine).where(
                    RepairPreviewLine.preview_id.in_(["cleanup-expired", "cleanup-confirmed"])
                )
            )
            session.execute(
                delete(RepairPreview).where(
                    RepairPreview.preview_id.in_(["cleanup-expired", "cleanup-confirmed"])
                )
            )
            session.execute(delete(StoredFile).where(StoredFile.file_id.in_([9301, 9302, 9303])))
            session.execute(delete(Factory).where(Factory.factory_id == "cleanup-factory"))
            session.execute(delete(User).where(User.user_id == "cleanup-admin"))

    clean()
    yield
    clean()


def test_cleanup_removes_an_expired_unconfirmed_preview_and_its_temporary_files(
    test_database_engine: Engine,
) -> None:
    now = datetime(2026, 8, 27, 1, 0, tzinfo=UTC)
    with Session(test_database_engine) as session, session.begin():
        session.add(
            User(
                user_id="cleanup-admin",
                role="admin",
                is_super_admin=True,
                is_enabled=True,
                feishu_display_name="清理管理员",
            )
        )
        session.flush()
        session.add(
            StoredFile(
                file_id=9301,
                bucket="repair-cleanup",
                object_key="previews/expired/source.xlsx",
                original_filename="过期质检.xlsx",
                mime_type=("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
                size_bytes=1234,
                content_sha256="6" * 64,
                uploaded_by="cleanup-admin",
            )
        )
        session.flush()
        session.add(
            RepairPreview(
                preview_id="cleanup-expired",
                status="READY",
                original_file_id=9301,
                source_sha256="6" * 64,
                uploaded_by="cleanup-admin",
                factory_id=None,
                line_count=1,
                box_count=1,
                total_quantity=1,
                validation_errors=[],
                validation_warnings=[],
                expires_at=(now - timedelta(seconds=1)).replace(tzinfo=None),
            )
        )
        session.flush()
        session.add(
            RepairPreviewLine(
                line_id=9301,
                preview_id="cleanup-expired",
                source_sheet="Sheet1",
                source_row=2,
                source_order=1,
                box_number="1号箱",
                supplier_number="E28",
                factory_name="跃富",
                source_sku_id="SKU-1",
                source_product_id="PRODUCT-1",
                product_name="产品1",
                properties_value="规格1",
                quantity=1,
                reason=None,
                matched_product_id=None,
                matched_variant_id=None,
                validation_errors=[],
                validation_warnings=[],
            )
        )
    file_store = FakePrivateFileStore(bucket="repair-cleanup")
    file_store.put(
        object_key="previews/expired/source.xlsx",
        content=b"xlsx",
        content_type=("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    )
    session_factory = sessionmaker(
        test_database_engine,
        class_=Session,
        expire_on_commit=False,
    )
    service = RepairPreviewCleanupService(
        session_factory,
        file_store=file_store,
        clock=lambda: now,
    )

    result = service.run()

    assert result.deleted_previews == 1
    assert result.deleted_files == 1
    assert file_store.object_count == 0
    with pytest.raises(ValueError):
        RepairPreviewService(session_factory, clock=lambda: now).get("cleanup-expired")


def test_cleanup_keeps_a_file_referenced_by_a_confirmed_repair(
    test_database_engine: Engine,
) -> None:
    now = datetime(2026, 8, 27, 1, 0, tzinfo=UTC)
    with Session(test_database_engine) as session, session.begin():
        session.add_all(
            [
                User(
                    user_id="cleanup-admin",
                    role="admin",
                    is_super_admin=True,
                    is_enabled=True,
                    feishu_display_name="清理管理员",
                ),
                Factory(
                    factory_id="cleanup-factory",
                    supplier_number="CLEANUP",
                    factory_name="清理测试工厂",
                    factory_code="CL",
                    is_enabled=True,
                ),
            ]
        )
        session.flush()
        session.add(
            StoredFile(
                file_id=9303,
                bucket="repair-cleanup",
                object_key="repairs/formal/source.xlsx",
                original_filename="正式质检.xlsx",
                mime_type=("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
                size_bytes=1234,
                content_sha256="8" * 64,
                uploaded_by="cleanup-admin",
            )
        )
        session.flush()
        session.add(
            RepairPreview(
                preview_id="cleanup-confirmed",
                status="CONFIRMED",
                original_file_id=9303,
                source_sha256="8" * 64,
                uploaded_by="cleanup-admin",
                factory_id="cleanup-factory",
                line_count=1,
                box_count=1,
                total_quantity=1,
                validation_errors=[],
                validation_warnings=[],
                expires_at=(now - timedelta(seconds=1)).replace(tzinfo=None),
                confirmed_at=(now - timedelta(hours=1)).replace(tzinfo=None),
                confirmed_repair_id="cleanup-formal",
            )
        )
        session.add(
            RepairOrder(
                repair_id="cleanup-formal",
                repair_no="FX20260827-001",
                factory_id="cleanup-factory",
                status="INCOMPLETE",
                warehouse_return_quantity=1,
                repaired_quantity=0,
                scrapped_quantity=0,
                returned_quantity=0,
                return_date=date(2026, 8, 27),
                original_file_id=9303,
                source_sha256="8" * 64,
                created_by="cleanup-admin",
                archived_by=None,
                archived_at=None,
                created_at=now.replace(tzinfo=None),
                updated_at=now.replace(tzinfo=None),
            )
        )
    file_store = FakePrivateFileStore(bucket="repair-cleanup")
    file_store.put(
        object_key="repairs/formal/source.xlsx",
        content=b"formal-xlsx",
        content_type=("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    )
    service = RepairPreviewCleanupService(
        sessionmaker(test_database_engine, class_=Session, expire_on_commit=False),
        file_store=file_store,
        clock=lambda: now,
    )

    result = service.run()

    assert result.deleted_previews == 0
    assert result.deleted_files == 0
    assert file_store.get(object_key="repairs/formal/source.xlsx") == b"formal-xlsx"
