"""AC-15: one path, role projection for registered incoming differences."""

from collections.abc import Iterator
from datetime import UTC, date, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, delete
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import (
    AuditLog,
    Factory,
    IncomingDiffAdjustment,
    IncomingDiffBatch,
    IncomingDiffImage,
    IncomingDiffRecord,
    IncomingDiffWorkbook,
    Order,
    OrderAssignment,
    OrderDetail,
    OrderLine,
    OutboxMessage,
    Product,
    ProductVariant,
    QuantityLedger,
    StoredFile,
    User,
    UserSession,
)
from app.main import create_app
from app.modules.identity_access import IdentityAccessService
from app.modules.incoming_differences import IncomingDifferenceService

ADMIN = "idf-api-admin"
FACTORY_USER_A = "idf-api-factory-a-user"
FACTORY_USER_B = "idf-api-factory-b-user"
USER_IDS = [ADMIN, FACTORY_USER_A, FACTORY_USER_B]
FACTORY_A = "idf-api-factory-a"
FACTORY_B = "idf-api-factory-b"
FACTORY_IDS = [FACTORY_A, FACTORY_B]
ORDER_ID = "idf-api-order"
BATCH_ID = "idf-api-batch"
WORKBOOK_ID = "idf-api-workbook"
IMAGE_ID = "idf-api-image"
FILE_IDS = [9701, 9702]
SEED_TIME = datetime(2026, 9, 1, 8, 0)


def _clean(engine: Engine) -> None:
    with Session(engine) as session, session.begin():
        session.execute(delete(IncomingDiffAdjustment))
        session.execute(delete(QuantityLedger).where(QuantityLedger.actor_id.in_(USER_IDS)))
        session.execute(delete(AuditLog).where(AuditLog.action == "incoming_diff_adjusted"))
        session.execute(
            delete(OutboxMessage).where(OutboxMessage.event_type == "incoming_diff.adjusted")
        )
        session.execute(
            delete(IncomingDiffRecord).where(IncomingDiffRecord.order_id == ORDER_ID)
        )
        session.execute(
            IncomingDiffBatch.__table__.update().values(current_workbook_id=None)
        )
        session.execute(delete(IncomingDiffImage))
        session.execute(delete(IncomingDiffWorkbook))
        session.execute(delete(IncomingDiffBatch))
        session.execute(
            OrderAssignment.__table__.update().values(detail_id=None)
        )
        session.execute(delete(OrderDetail).where(OrderDetail.order_id == ORDER_ID))
        session.execute(delete(OrderAssignment))
        session.execute(delete(OrderLine).where(OrderLine.order_id == ORDER_ID))
        session.execute(delete(Order).where(Order.order_id == ORDER_ID))
        session.execute(delete(UserSession).where(UserSession.user_id.in_(USER_IDS)))
        session.execute(delete(StoredFile).where(StoredFile.file_id.in_(FILE_IDS)))
        session.execute(
            delete(ProductVariant).where(
                ProductVariant.variant_id.in_(["idf-api-variant-1", "idf-api-variant-2"])
            )
        )
        session.execute(delete(Product).where(Product.product_id == "idf-api-product"))
        session.execute(delete(User).where(User.user_id.in_(USER_IDS)))
        session.execute(delete(Factory).where(Factory.factory_id.in_(FACTORY_IDS)))


def _seed(engine: Engine) -> None:
    with Session(engine) as session, session.begin():
        session.add_all(
            [
                Factory(
                    factory_id=factory_id,
                    supplier_number=f"IDFAPI-{index}",
                    factory_name=f"投影工厂{index}",
                    factory_code=f"IDFAPI{index}",
                    is_enabled=True,
                )
                for index, factory_id in enumerate(FACTORY_IDS, 1)
            ]
        )
        session.flush()
        session.add_all(
            [
                User(
                    user_id=ADMIN, role="admin", is_enabled=True, feishu_display_name="投影管理员"
                ),
                User(
                    user_id=FACTORY_USER_A,
                    role="factory",
                    is_enabled=True,
                    feishu_display_name="投影工厂用户A",
                    factory_id=FACTORY_A,
                    factory_position="employee",
                ),
                User(
                    user_id=FACTORY_USER_B,
                    role="factory",
                    is_enabled=True,
                    feishu_display_name="投影工厂用户B",
                    factory_id=FACTORY_B,
                    factory_position="employee",
                ),
            ]
        )
        session.add(
            Product(
                product_id="idf-api-product",
                source_i_id="IDFAPI-ITEM",
                name="投影测试产品",
                is_available=True,
                image_cache_status="missing",
                source_modified_at=SEED_TIME,
                first_synced_at=SEED_TIME,
                last_synced_at=SEED_TIME,
            )
        )
        session.flush()
        session.add_all(
            [
                ProductVariant(
                    variant_id=f"idf-api-variant-{index}",
                    product_id="idf-api-product",
                    source_sku_id=f"IDFAPI-SKU-{index}",
                    properties_value=properties,
                    is_available=True,
                    source_modified_at=SEED_TIME,
                    first_synced_at=SEED_TIME,
                    last_synced_at=SEED_TIME,
                )
                for index, properties in enumerate(["红色 / 110", "蓝色 / 120"], 1)
            ]
        )
        session.add_all(
            [
                StoredFile(
                    file_id=FILE_IDS[0],
                    bucket="incoming-diff",
                    object_key="images/idf-api/1.jpg",
                    original_filename="来货.jpg",
                    mime_type="image/jpeg",
                    size_bytes=1024,
                    content_sha256="c" * 64,
                    uploaded_by=ADMIN,
                ),
                StoredFile(
                    file_id=FILE_IDS[1],
                    bucket="incoming-diff",
                    object_key="workbooks/idf-api/1.xlsx",
                    original_filename="核对表.xlsx",
                    mime_type=(
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    ),
                    size_bytes=2048,
                    content_sha256="d" * 64,
                    uploaded_by=ADMIN,
                ),
            ]
        )
        session.add(
            Order(
                order_id=ORDER_ID,
                order_no="IDFAPI-1",
                source="manual",
                order_date=date(2026, 9, 1),
                tracker="松子",
                trackers=["松子"],
                detail_mode=True,
                lifecycle="PUBLISHED",
                created_by=ADMIN,
                updated_by=ADMIN,
                created_at=SEED_TIME,
                updated_at=SEED_TIME,
            )
        )
        session.flush()
        assignments: list[OrderAssignment] = []
        for index, (factory_id, properties) in enumerate(
            [(FACTORY_A, "红色 / 110"), (FACTORY_B, "蓝色 / 120")], 1
        ):
            line = OrderLine(
                order_id=ORDER_ID,
                product_variant_id=f"idf-api-variant-{index}",
                order_quantity=100,
                sku_id_snapshot=f"IDFAPI-SKU-{index}",
                product_name_snapshot="投影测试产品",
                properties_value_snapshot=properties,
                created_at=SEED_TIME,
                updated_at=SEED_TIME,
            )
            session.add(line)
            session.flush()
            assignment = OrderAssignment(
                order_line_id=line.order_line_id,
                factory_id=factory_id,
                is_active=True,
                contract_ship_date=date(2026, 9, 20),
                assigned_quantity=100,
                initial_shipped_quantity=0,
                factory_name_snapshot=f"投影工厂{index}",
                created_at=SEED_TIME,
                updated_at=SEED_TIME,
            )
            session.add(assignment)
            session.flush()
            detail_id = f"idf-api-detail-{index}"
            session.add(
                OrderDetail(
                    detail_id=detail_id,
                    order_id=ORDER_ID,
                    origin="manual",
                    sort_order=index,
                    accepted_raw_fields={},
                    purchase_order_id=f"PO-API-{index}",
                    purchase_order_item_id=f"POI-API-{index}",
                    source_sku_id=f"IDFAPI-SKU-{index}",
                    product_name="投影测试产品",
                    properties_value=properties,
                    matched_variant_id=f"idf-api-variant-{index}",
                    matched_factory_id=factory_id,
                    order_quantity=100,
                    source_trackers=["松子"],
                    contract_ship_date=date(2026, 9, 20),
                    parse_issues=[],
                    assignment_id=assignment.order_assignment_id,
                    dispatch_state="ASSIGNED",
                    created_at=SEED_TIME,
                    updated_at=SEED_TIME,
                )
            )
            session.flush()
            assignment.detail_id = detail_id
            assignments.append(assignment)
        session.add(
            IncomingDiffBatch(
                batch_id=BATCH_ID,
                batch_no="IN20260917-01",
                submitter_id=ADMIN,
                status="CONFIRMED",
                created_at=SEED_TIME,
                updated_at=SEED_TIME,
            )
        )
        session.flush()
        session.add(
            IncomingDiffImage(
                image_id=IMAGE_ID,
                batch_id=BATCH_ID,
                sort_order=1,
                feishu_image_key="idf-api-key",
                file_id=FILE_IDS[0],
                content_sha256="c" * 64,
                ocr_status="SUCCEEDED",
                created_at=SEED_TIME,
            )
        )
        session.add(
            IncomingDiffWorkbook(
                workbook_id=WORKBOOK_ID,
                batch_id=BATCH_ID,
                version=1,
                direction="UPLOADED",
                file_id=FILE_IDS[1],
                content_sha256="d" * 64,
                line_snapshot=[],
                submitted_by=ADMIN,
                submitted_at=SEED_TIME,
            )
        )
        session.flush()
        # 前两条同规格同数量，用于验证不合并
        rows = [
            ("idf-api-record-1", assignments[0], 3, datetime(2026, 9, 17, 10, 0)),
            ("idf-api-record-2", assignments[0], 3, datetime(2026, 9, 17, 11, 0)),
            ("idf-api-record-3", assignments[1], -2, datetime(2026, 9, 17, 12, 0)),
        ]
        for record_id, assignment, quantity, registered_at in rows:
            index = 1 if assignment.factory_id == FACTORY_A else 2
            session.add(
                IncomingDiffRecord(
                    record_id=record_id,
                    batch_id=BATCH_ID,
                    workbook_id=WORKBOOK_ID,
                    image_id=IMAGE_ID,
                    order_id=ORDER_ID,
                    detail_id=f"idf-api-detail-{index}",
                    order_assignment_id=assignment.order_assignment_id,
                    variant_id=f"idf-api-variant-{index}",
                    purchase_order_id=f"PO-API-{index}",
                    purchase_order_item_id=f"POI-API-{index}",
                    quantity=quantity,
                    initial_quantity=quantity,
                    source_business_date=date(2026, 9, 16),
                    product_code_snapshot="IDFAPI-ITEM",
                    product_name_snapshot="投影测试产品",
                    spec_snapshot="红色 / 110" if index == 1 else "蓝色 / 120",
                    registered_at=registered_at,
                    registered_by=ADMIN,
                    version=1,
                    created_at=registered_at,
                    updated_at=registered_at,
                )
            )
            session.add(
                QuantityLedger(
                    order_assignment_id=assignment.order_assignment_id,
                    source_type="INCOMING_DIFF",
                    source_id=record_id,
                    quantity_delta=quantity,
                    actor_id=ADMIN,
                    created_at=registered_at,
                )
            )


@pytest.fixture(autouse=True)
def seeded(test_database_engine: Engine) -> Iterator[None]:
    _clean(test_database_engine)
    _seed(test_database_engine)
    yield
    _clean(test_database_engine)


def _client_app(
    test_database_engine: Engine, test_database_url: str
) -> tuple[FastAPI, IdentityAccessService]:
    sessions = sessionmaker(test_database_engine, class_=Session, expire_on_commit=False)
    identity = IdentityAccessService(
        sessions,
        token_secret=b"idf-api-token-secret",
        phone_encryption_secret=b"idf-api-phone-encryption",
        phone_digest_secret=b"idf-api-phone-digest",
    )
    app = create_app(
        database_url=test_database_url,
        identity_service=identity,
        incoming_difference_service=IncomingDifferenceService(
            sessions, clock=lambda: datetime(2026, 9, 18, 2, 30, tzinfo=UTC)
        ),
    )
    return app, identity


def test_admin_sees_every_column_and_records_are_not_merged(
    test_database_engine: Engine, test_database_url: str
) -> None:
    app, identity = _client_app(test_database_engine, test_database_url)
    session = identity.issue_session(user_id=ADMIN, terminal="web")
    with TestClient(app, base_url="https://testserver") as client:
        client.cookies.set("ot_web_session", session.access_token)
        response = client.get(f"/api/v1/orders/{ORDER_ID}/incoming-differences")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert [item["sequence"] for item in body["items"]] == [1, 2, 3]
    assert [item["recordId"] for item in body["items"]] == [
        "idf-api-record-1",
        "idf-api-record-2",
        "idf-api-record-3",
    ]
    first = body["items"][0]
    assert first["purchaseOrderId"] == "PO-API-1"
    assert first["productCode"] == "IDFAPI-ITEM"
    assert first["productName"] == "投影测试产品"
    assert first["spec"] == "红色 / 110"
    assert first["quantity"] == 3
    assert first["version"] == 1
    assert first["registeredAt"].startswith("2026-09-17T10:00:00")
    # 同规格同数量的两条各自成行
    assert body["items"][1]["quantity"] == 3
    assert body["items"][1]["spec"] == "红色 / 110"


def test_factory_sees_only_its_own_rows_without_sourcing_fields(
    test_database_engine: Engine, test_database_url: str
) -> None:
    app, identity = _client_app(test_database_engine, test_database_url)
    session = identity.issue_session(user_id=FACTORY_USER_A, terminal="mini")
    with TestClient(app, base_url="https://testserver") as client:
        client.headers["Authorization"] = f"Bearer {session.access_token}"
        response = client.get(f"/api/v1/orders/{ORDER_ID}/incoming-differences")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    for item in body["items"]:
        assert set(item) == {"sequence", "registeredAt", "productName", "spec", "quantity"}
    assert [item["quantity"] for item in body["items"]] == [3, 3]


def test_other_factory_sees_only_its_own_row_and_unknown_order_is_not_found(
    test_database_engine: Engine, test_database_url: str
) -> None:
    app, identity = _client_app(test_database_engine, test_database_url)
    factory_b = identity.issue_session(user_id=FACTORY_USER_B, terminal="mini")
    with TestClient(app, base_url="https://testserver") as client:
        client.headers["Authorization"] = f"Bearer {factory_b.access_token}"
        visible = client.get(f"/api/v1/orders/{ORDER_ID}/incoming-differences")
        assert visible.status_code == 200
        assert visible.json()["total"] == 1
        assert visible.json()["items"][0]["quantity"] == -2
        missing = client.get("/api/v1/orders/does-not-exist/incoming-differences")
        assert missing.status_code == 404


def test_anonymous_request_is_rejected(
    test_database_engine: Engine, test_database_url: str
) -> None:
    app, _identity = _client_app(test_database_engine, test_database_url)
    with TestClient(app, base_url="https://testserver") as client:
        assert (
            client.get(f"/api/v1/orders/{ORDER_ID}/incoming-differences").status_code == 401
        )


def test_admin_can_adjust_quantity_and_stale_version_is_rejected(
    test_database_engine: Engine, test_database_url: str
) -> None:
    app, identity = _client_app(test_database_engine, test_database_url)
    session = identity.issue_session(user_id=ADMIN, terminal="web")
    with TestClient(app, base_url="https://testserver") as client:
        client.cookies.set("ot_web_session", session.access_token)
        updated = client.patch(
            f"/api/v1/admin/orders/{ORDER_ID}/incoming-differences/idf-api-record-1",
            json={"quantity": 4, "version": 1},
        )
        stale = client.patch(
            f"/api/v1/admin/orders/{ORDER_ID}/incoming-differences/idf-api-record-1",
            json={"quantity": 5, "version": 1},
        )
        below_zero = client.patch(
            f"/api/v1/admin/orders/{ORDER_ID}/incoming-differences/idf-api-record-1",
            json={"quantity": -10, "version": 2},
        )

    assert updated.status_code == 200
    assert updated.json()["quantity"] == 4
    assert updated.json()["version"] == 2
    assert stale.status_code == 409
    assert stale.json()["message"] == "记录已被修改，请刷新后重试"
    assert below_zero.status_code == 422
    assert "不能小于 0" in below_zero.json()["message"]


def test_factory_cannot_adjust_quantity(
    test_database_engine: Engine, test_database_url: str
) -> None:
    app, identity = _client_app(test_database_engine, test_database_url)
    session = identity.issue_session(user_id=FACTORY_USER_A, terminal="mini")
    with TestClient(app, base_url="https://testserver") as client:
        client.headers["Authorization"] = f"Bearer {session.access_token}"
        response = client.patch(
            f"/api/v1/admin/orders/{ORDER_ID}/incoming-differences/idf-api-record-1",
            json={"quantity": 4, "version": 1},
        )

    assert response.status_code == 403
