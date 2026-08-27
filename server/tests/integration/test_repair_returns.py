from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from threading import Barrier

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, delete, select
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import (
    AuditLog,
    Factory,
    IdempotencyRecord,
    OutboxMessage,
    Product,
    ProductVariant,
    RepairInspectionLine,
    RepairOrder,
    RepairReturnBatch,
    RepairReturnLine,
    StoredFile,
    User,
    UserSession,
)
from app.main import create_app
from app.modules.identity_access import IdentityAccessService
from app.modules.repairs.returns import (
    RepairReturnConflict,
    RepairReturnLineInput,
    RepairReturnNotFound,
    RepairReturnService,
    RepairReturnValidationError,
)


@pytest.fixture(autouse=True)
def clean_repair_return_records(test_database_engine: Engine) -> Iterator[None]:
    def clean() -> None:
        with Session(test_database_engine) as session, session.begin():
            session.execute(
                delete(AuditLog).where(
                    AuditLog.target_type == "repair",
                    AuditLog.target_id == "return-repair",
                )
            )
            session.execute(
                delete(OutboxMessage).where(OutboxMessage.aggregate_id == "return-repair")
            )
            session.execute(
                delete(IdempotencyRecord).where(
                    IdempotencyRecord.scope.like("repair.archive:return-repair:%")
                )
            )
            batch_ids = session.scalars(
                select(RepairReturnBatch.batch_id).where(
                    RepairReturnBatch.repair_id == "return-repair"
                )
            ).all()
            if batch_ids:
                session.execute(
                    delete(RepairReturnLine).where(RepairReturnLine.batch_id.in_(batch_ids))
                )
            session.execute(
                delete(RepairReturnBatch).where(RepairReturnBatch.repair_id == "return-repair")
            )
            session.execute(
                delete(RepairInspectionLine).where(
                    RepairInspectionLine.repair_id == "return-repair"
                )
            )
            session.execute(delete(RepairOrder).where(RepairOrder.repair_id == "return-repair"))
            session.execute(delete(StoredFile).where(StoredFile.file_id == 9501))
            session.execute(
                delete(ProductVariant).where(ProductVariant.variant_id == "return-variant")
            )
            session.execute(delete(Product).where(Product.product_id == "return-product"))
            session.execute(
                delete(UserSession).where(
                    UserSession.user_id.in_(["return-admin", "return-factory-user"])
                )
            )
            session.execute(
                delete(User).where(User.user_id.in_(["return-admin", "return-factory-user"]))
            )
            session.execute(delete(Factory).where(Factory.factory_id == "return-factory"))

    clean()
    yield
    clean()


def seed_return_repair(
    test_database_engine: Engine,
    *,
    status: str = "INCOMPLETE",
    repaired_quantity: int = 0,
    scrapped_quantity: int = 0,
) -> None:
    source_time = datetime(2026, 8, 27, 2, 30)
    with Session(test_database_engine) as session, session.begin():
        session.add_all(
            [
                User(
                    user_id="return-admin",
                    role="admin",
                    is_super_admin=True,
                    is_enabled=True,
                    feishu_display_name="返修管理员",
                ),
                Factory(
                    factory_id="return-factory",
                    supplier_number="RETURN",
                    factory_name="返修测试工厂",
                    factory_code="RF",
                    is_enabled=True,
                ),
                Product(
                    product_id="return-product",
                    source_i_id="RETURN-PRODUCT",
                    name="返修测试产品",
                    is_available=True,
                    image_cache_status="missing",
                    source_modified_at=source_time,
                    first_synced_at=source_time,
                    last_synced_at=source_time,
                ),
            ]
        )
        session.flush()
        session.add_all(
            [
                User(
                    user_id="return-factory-user",
                    role="factory",
                    is_super_admin=False,
                    is_enabled=True,
                    factory_id="return-factory",
                    feishu_display_name="返修工厂用户",
                ),
                ProductVariant(
                    variant_id="return-variant",
                    product_id="return-product",
                    source_sku_id="RETURN-SKU",
                    properties_value="返修规格",
                    is_available=True,
                    source_modified_at=source_time,
                    first_synced_at=source_time,
                    last_synced_at=source_time,
                ),
                StoredFile(
                    file_id=9501,
                    bucket="repair-return",
                    object_key="repairs/return/source.xlsx",
                    original_filename="返修质检.xlsx",
                    mime_type=("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
                    size_bytes=1024,
                    content_sha256="8" * 64,
                    uploaded_by="return-admin",
                ),
            ]
        )
        session.flush()
        returned_quantity = repaired_quantity + scrapped_quantity
        session.add(
            RepairOrder(
                repair_id="return-repair",
                repair_no="FX20260827-001",
                factory_id="return-factory",
                status=status,
                warehouse_return_quantity=12,
                repaired_quantity=repaired_quantity,
                scrapped_quantity=scrapped_quantity,
                returned_quantity=returned_quantity,
                return_date=date(2026, 8, 27),
                original_file_id=9501,
                source_sha256="8" * 64,
                created_by="return-admin",
                created_at=source_time,
                updated_at=source_time,
            )
        )
        session.flush()
        session.add(
            RepairInspectionLine(
                repair_id="return-repair",
                source_sheet="Sheet1",
                source_row=2,
                source_order=1,
                box_number="1号箱",
                product_id="return-product",
                variant_id="return-variant",
                source_sku_id="RETURN-SKU",
                source_product_id="RETURN-PRODUCT",
                product_name="返修测试产品",
                properties_value="返修规格",
                warehouse_return_quantity=12,
                reason="车线问题",
            )
        )


def test_factory_can_submit_the_first_partial_return_for_an_aggregated_spec(
    test_database_engine: Engine,
) -> None:
    now = datetime(2026, 8, 27, 2, 30, tzinfo=UTC)
    source_time = now.replace(tzinfo=None)
    with Session(test_database_engine) as session, session.begin():
        session.add_all(
            [
                User(
                    user_id="return-admin",
                    role="admin",
                    is_super_admin=True,
                    is_enabled=True,
                    feishu_display_name="返修管理员",
                ),
                Factory(
                    factory_id="return-factory",
                    supplier_number="RETURN",
                    factory_name="返修测试工厂",
                    factory_code="RF",
                    is_enabled=True,
                ),
                Product(
                    product_id="return-product",
                    source_i_id="RETURN-PRODUCT",
                    name="返修测试产品",
                    is_available=True,
                    image_cache_status="missing",
                    source_modified_at=source_time,
                    first_synced_at=source_time,
                    last_synced_at=source_time,
                ),
            ]
        )
        session.flush()
        session.add_all(
            [
                User(
                    user_id="return-factory-user",
                    role="factory",
                    is_super_admin=False,
                    is_enabled=True,
                    factory_id="return-factory",
                    feishu_display_name="返修工厂用户",
                ),
                ProductVariant(
                    variant_id="return-variant",
                    product_id="return-product",
                    source_sku_id="RETURN-SKU",
                    properties_value="返修规格",
                    is_available=True,
                    source_modified_at=source_time,
                    first_synced_at=source_time,
                    last_synced_at=source_time,
                ),
                StoredFile(
                    file_id=9501,
                    bucket="repair-return",
                    object_key="repairs/return/source.xlsx",
                    original_filename="返修质检.xlsx",
                    mime_type=("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
                    size_bytes=1024,
                    content_sha256="8" * 64,
                    uploaded_by="return-admin",
                ),
            ]
        )
        session.flush()
        session.add(
            RepairOrder(
                repair_id="return-repair",
                repair_no="FX20260827-001",
                factory_id="return-factory",
                status="INCOMPLETE",
                warehouse_return_quantity=12,
                repaired_quantity=0,
                scrapped_quantity=0,
                returned_quantity=0,
                return_date=date(2026, 8, 27),
                original_file_id=9501,
                source_sha256="8" * 64,
                created_by="return-admin",
                created_at=source_time,
                updated_at=source_time,
            )
        )
        session.flush()
        session.add_all(
            [
                RepairInspectionLine(
                    repair_id="return-repair",
                    source_sheet="Sheet1",
                    source_row=2,
                    source_order=1,
                    box_number="1号箱",
                    product_id="return-product",
                    variant_id="return-variant",
                    source_sku_id="RETURN-SKU",
                    source_product_id="RETURN-PRODUCT",
                    product_name="返修测试产品",
                    properties_value="返修规格",
                    warehouse_return_quantity=7,
                    reason="车线问题",
                ),
                RepairInspectionLine(
                    repair_id="return-repair",
                    source_sheet="Sheet1",
                    source_row=3,
                    source_order=2,
                    box_number="2号箱",
                    product_id="return-product",
                    variant_id="return-variant",
                    source_sku_id="RETURN-SKU",
                    source_product_id="RETURN-PRODUCT",
                    product_name="返修测试产品",
                    properties_value="返修规格",
                    warehouse_return_quantity=5,
                    reason="面料问题",
                ),
            ]
        )

    service = RepairReturnService(
        sessionmaker(test_database_engine, class_=Session, expire_on_commit=False),
        clock=lambda: now,
        id_factory=lambda: "return-batch-1",
    )

    submitted = service.submit(
        repair_id="return-repair",
        factory_id="return-factory",
        submitted_by="return-factory-user",
        idempotency_key="return-request-1",
        lines=(
            RepairReturnLineInput(
                variant_id="return-variant",
                repaired_quantity=4,
                scrapped_quantity=1,
            ),
        ),
    )
    detail = service.get("return-repair")

    assert submitted == detail
    assert detail.status == "INCOMPLETE"
    assert detail.repaired_quantity == 4
    assert detail.scrapped_quantity == 1
    assert detail.returned_quantity == 5
    assert len(detail.specs) == 1
    assert detail.specs[0].variant_id == "return-variant"
    assert detail.specs[0].warehouse_return_quantity == 12
    assert detail.specs[0].returned_quantity == 5
    assert detail.specs[0].pending_quantity == 7
    assert len(detail.return_batches) == 1
    assert detail.return_batches[0].batch_id == "return-batch-1"
    assert detail.return_batches[0].submitted_at == source_time
    assert detail.return_batches[0].lines[0].repaired_quantity == 4
    assert detail.return_batches[0].lines[0].scrapped_quantity == 1


def test_admin_can_archive_only_completed_repairs_and_hide_them_from_business_queries(
    test_database_engine: Engine,
) -> None:
    now = datetime(2026, 8, 27, 4, 0, tzinfo=UTC)
    seed_return_repair(test_database_engine)
    service = RepairReturnService(
        sessionmaker(test_database_engine, class_=Session, expire_on_commit=False),
        clock=lambda: now,
    )

    with pytest.raises(RepairReturnConflict, match="只有已完成"):
        service.archive(
            repair_id="return-repair",
            archived_by="return-admin",
            idempotency_key="archive-incomplete-request",
        )
    with Session(test_database_engine) as session, session.begin():
        repair = session.get(RepairOrder, "return-repair")
        assert repair is not None
        repair.status = "COMPLETED"
        repair.repaired_quantity = 10
        repair.scrapped_quantity = 2
        repair.returned_quantity = 12

    archived = service.archive(
        repair_id="return-repair",
        archived_by="return-admin",
        idempotency_key="archive-request-1",
    )

    assert archived.repair_id == "return-repair"
    assert archived.archived_at == now.replace(tzinfo=None)
    with pytest.raises(RepairReturnNotFound):
        service.get("return-repair")
    assert service.list_all() == ()
    assert service.list_all(factory_id="return-factory") == ()


def test_concurrent_returns_are_serialized_against_the_same_remaining_quantity(
    test_database_engine: Engine,
) -> None:
    seed_return_repair(test_database_engine)
    sessions = sessionmaker(test_database_engine, class_=Session, expire_on_commit=False)
    barrier = Barrier(2)

    def submit(key: str) -> str:
        service = RepairReturnService(sessions)
        barrier.wait()
        try:
            service.submit(
                repair_id="return-repair",
                factory_id="return-factory",
                submitted_by="return-factory-user",
                idempotency_key=key,
                lines=(RepairReturnLineInput("return-variant", 8, 0),),
            )
            return "submitted"
        except RepairReturnConflict:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(submit, ("concurrent-1", "concurrent-2")))

    assert sorted(results) == ["conflict", "submitted"]
    assert RepairReturnService(sessions).get("return-repair").returned_quantity == 8


def test_return_validation_rejects_non_integers_empty_lines_and_zero_totals(
    test_database_engine: Engine,
) -> None:
    seed_return_repair(test_database_engine)
    service = RepairReturnService(
        sessionmaker(test_database_engine, class_=Session, expire_on_commit=False)
    )

    with pytest.raises(RepairReturnValidationError, match="至少选择"):
        service.submit(
            repair_id="return-repair",
            factory_id="return-factory",
            submitted_by="return-factory-user",
            idempotency_key="empty-lines",
            lines=(),
        )
    with pytest.raises(RepairReturnValidationError, match="非负整数"):
        service.submit(
            repair_id="return-repair",
            factory_id="return-factory",
            submitted_by="return-factory-user",
            idempotency_key="boolean-quantity",
            lines=(RepairReturnLineInput("return-variant", True, 0),),
        )
    with pytest.raises(RepairReturnValidationError, match="不能同时为0"):
        service.submit(
            repair_id="return-repair",
            factory_id="return-factory",
            submitted_by="return-factory-user",
            idempotency_key="zero-quantity",
            lines=(RepairReturnLineInput("return-variant", 0, 0),),
        )


def test_factory_return_api_updates_the_shared_admin_detail(
    test_database_engine: Engine,
    test_database_url: str,
) -> None:
    seed_return_repair(test_database_engine)
    sessions = sessionmaker(test_database_engine, class_=Session, expire_on_commit=False)
    identity = IdentityAccessService(
        sessions,
        token_secret=b"repair-return-api-token",
        phone_encryption_secret=b"repair-return-api-encryption",
        phone_digest_secret=b"repair-return-api-digest",
    )
    factory_session = identity.issue_session(user_id="return-factory-user", terminal="mini")
    admin_session = identity.issue_session(user_id="return-admin", terminal="web")
    app = create_app(database_url=test_database_url, identity_service=identity)

    with TestClient(app, base_url="https://testserver") as factory_client:
        submitted = factory_client.post(
            "/api/v1/factory/repairs/return-repair/return-batches",
            headers={
                "Authorization": f"Bearer {factory_session.access_token}",
                "Idempotency-Key": "return-api-request-1",
            },
            json={
                "lines": [
                    {
                        "variantId": "return-variant",
                        "repairedQuantity": 3,
                        "scrappedQuantity": 2,
                    }
                ]
            },
        )

    assert submitted.status_code == 201
    assert submitted.json()["returnedQuantity"] == 5
    assert submitted.json()["specs"][0]["pendingQuantity"] == 7

    with TestClient(app, base_url="https://testserver") as admin_client:
        admin_client.cookies.set("ot_web_session", admin_session.access_token)
        detail = admin_client.get("/api/v1/admin/repairs/return-repair")

    assert detail.status_code == 200
    assert detail.json()["returnBatches"][0]["lines"][0] == {
        "variantId": "return-variant",
        "sourceSkuId": "RETURN-SKU",
        "sourceProductId": "RETURN-PRODUCT",
        "productName": "返修测试产品",
        "propertiesValue": "返修规格",
        "warehouseReturnQuantity": 12,
        "repairedQuantity": 3,
        "scrappedQuantity": 2,
        "returnedQuantity": 5,
    }


def test_final_batch_completes_the_repair_and_an_idempotent_retry_reuses_it(
    test_database_engine: Engine,
) -> None:
    seed_return_repair(test_database_engine)
    batch_ids = iter(["return-batch-1", "return-batch-2"])
    service = RepairReturnService(
        sessionmaker(test_database_engine, class_=Session, expire_on_commit=False),
        id_factory=lambda: next(batch_ids),
    )
    service.submit(
        repair_id="return-repair",
        factory_id="return-factory",
        submitted_by="return-factory-user",
        idempotency_key="return-request-1",
        lines=(RepairReturnLineInput("return-variant", 4, 1),),
    )
    completed = service.submit(
        repair_id="return-repair",
        factory_id="return-factory",
        submitted_by="return-factory-user",
        idempotency_key="return-request-2",
        lines=(RepairReturnLineInput("return-variant", 5, 2),),
    )
    repeated = service.submit(
        repair_id="return-repair",
        factory_id="return-factory",
        submitted_by="return-factory-user",
        idempotency_key="return-request-2",
        lines=(RepairReturnLineInput("return-variant", 5, 2),),
    )

    assert repeated == completed
    assert completed.status == "COMPLETED"
    assert completed.repaired_quantity == 9
    assert completed.scrapped_quantity == 3
    assert completed.returned_quantity == 12
    assert completed.specs[0].pending_quantity == 0
    assert [batch.batch_id for batch in completed.return_batches] == [
        "return-batch-2",
        "return-batch-1",
    ]

    with pytest.raises(RepairReturnConflict, match="已完成"):
        service.submit(
            repair_id="return-repair",
            factory_id="return-factory",
            submitted_by="return-factory-user",
            idempotency_key="return-request-3",
            lines=(RepairReturnLineInput("return-variant", 1, 0),),
        )


def test_admin_archive_api_hides_completed_repair_details_and_attachment(
    test_database_engine: Engine,
    test_database_url: str,
) -> None:
    seed_return_repair(test_database_engine)
    sessions = sessionmaker(test_database_engine, class_=Session, expire_on_commit=False)
    identity = IdentityAccessService(
        sessions,
        token_secret=b"repair-archive-api-token",
        phone_encryption_secret=b"repair-archive-api-encryption",
        phone_digest_secret=b"repair-archive-api-digest",
    )
    factory_session = identity.issue_session(user_id="return-factory-user", terminal="mini")
    admin_session = identity.issue_session(user_id="return-admin", terminal="web")
    app = create_app(database_url=test_database_url, identity_service=identity)

    with TestClient(app, base_url="https://testserver") as factory_client:
        factory_client.headers["Authorization"] = f"Bearer {factory_session.access_token}"
        completed = factory_client.post(
            "/api/v1/factory/repairs/return-repair/return-batches",
            headers={"Idempotency-Key": "return-api-complete"},
            json={
                "lines": [
                    {
                        "variantId": "return-variant",
                        "repairedQuantity": 10,
                        "scrappedQuantity": 2,
                    }
                ]
            },
        )
        assert completed.status_code == 201
        assert completed.json()["status"] == "COMPLETED"

        with TestClient(app, base_url="https://testserver") as admin_client:
            admin_client.cookies.set("ot_web_session", admin_session.access_token)
            admin_client.cookies.set("ot_csrf", admin_session.csrf_token or "")
            write_headers = {
                "X-CSRF-Token": admin_session.csrf_token or "",
                "Idempotency-Key": "archive-api-request-1",
            }
            archived = admin_client.post(
                "/api/v1/admin/repairs/return-repair/archive",
                headers=write_headers,
            )
            repeated = admin_client.post(
                "/api/v1/admin/repairs/return-repair/archive",
                headers=write_headers,
            )

            assert archived.status_code == 200
            assert repeated.json() == archived.json()
            assert admin_client.get("/api/v1/admin/repairs").json()["items"] == []
            assert admin_client.get("/api/v1/admin/repairs/return-repair").status_code == 404
            assert admin_client.get("/api/v1/files/9501/download").status_code == 404

        assert factory_client.get("/api/v1/factory/repairs").json()["items"] == []
        assert factory_client.get("/api/v1/factory/repairs/return-repair").status_code == 404
        assert factory_client.get("/api/v1/files/9501/download").status_code == 404
