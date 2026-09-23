"""Slice 1 acceptance for incoming differences: AC-08/09/11/12/13/17 plus batch_no and matching."""

from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any

import pytest
from sqlalchemy import Engine, delete, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import (
    AuditLog,
    Factory,
    IdempotencyRecord,
    IncomingDiffAdjustment,
    IncomingDiffBatch,
    IncomingDiffImage,
    IncomingDiffRecord,
    IncomingDiffWorkbook,
    Notification,
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
)
from app.modules.incoming_differences import (
    IncomingDifferencePermissionDenied,
    IncomingDifferenceService,
    IncomingDifferenceValidationError,
)
from app.modules.notifications_audit import NotificationsAuditService

ADMIN = "idf-admin"
OTHER_ADMIN = "idf-admin-2"
DISABLED_ADMIN = "idf-admin-off"
FACTORY_USER = "idf-factory-user"
SECOND_FACTORY_USER = "idf-factory-user-2"
DISABLED_FACTORY_USER = "idf-factory-user-off"
USER_IDS = [
    ADMIN,
    OTHER_ADMIN,
    DISABLED_ADMIN,
    FACTORY_USER,
    SECOND_FACTORY_USER,
    DISABLED_FACTORY_USER,
]
FACTORY_A = "idf-factory-a"
FACTORY_B = "idf-factory-b"
FACTORY_IDS = [FACTORY_A, FACTORY_B]
ORDER_ID = "idf-order"
BATCH_ID = "idf-batch"
WORKBOOK_ID = "idf-workbook"
IMAGE_ID = "idf-image"
FILE_IDS = [9601, 9602]
NOW = datetime(2026, 9, 18, 2, 30, tzinfo=UTC)
SOURCE_TIME = datetime(2026, 9, 1, 8, 0)


def _clean(engine: Engine) -> None:
    with Session(engine) as session, session.begin():
        session.execute(
            delete(IncomingDiffAdjustment).where(
                IncomingDiffAdjustment.actor_id.in_(USER_IDS)
            )
        )
        session.execute(
            delete(IncomingDiffRecord).where(IncomingDiffRecord.order_id == ORDER_ID)
        )
        session.execute(
            delete(QuantityLedger).where(QuantityLedger.actor_id.in_(USER_IDS))
        )
        session.execute(
            delete(Notification).where(Notification.recipient_id.in_(USER_IDS))
        )
        session.execute(
            delete(OutboxMessage).where(
                OutboxMessage.dedupe_key.like("%incoming-diff:%")
            )
        )
        session.execute(
            delete(AuditLog).where(AuditLog.action.like("incoming_diff_%"))
        )
        session.execute(
            delete(IdempotencyRecord).where(
                IdempotencyRecord.scope == "incoming_diff_confirm"
            )
        )
        session.execute(
            IncomingDiffBatch.__table__.update().values(current_workbook_id=None)
        )
        session.execute(delete(IncomingDiffImage))
        session.execute(delete(IncomingDiffWorkbook))
        session.execute(delete(IncomingDiffBatch))
        session.execute(
            OrderAssignment.__table__.update()
            .where(
                OrderAssignment.detail_id.in_(
                    select(OrderDetail.detail_id).where(OrderDetail.order_id == ORDER_ID)
                )
            )
            .values(detail_id=None)
        )
        session.execute(delete(OrderDetail).where(OrderDetail.order_id == ORDER_ID))
        session.execute(
            delete(OrderAssignment).where(
                OrderAssignment.order_line_id.in_(
                    select(OrderLine.order_line_id).where(OrderLine.order_id == ORDER_ID)
                )
            )
        )
        session.execute(delete(OrderLine).where(OrderLine.order_id == ORDER_ID))
        session.execute(delete(Order).where(Order.order_id == ORDER_ID))
        session.execute(delete(StoredFile).where(StoredFile.file_id.in_(FILE_IDS)))
        session.execute(
            delete(ProductVariant).where(
                ProductVariant.variant_id.in_(["idf-variant-1", "idf-variant-2"])
            )
        )
        session.execute(delete(Product).where(Product.product_id == "idf-product"))
        session.execute(delete(User).where(User.user_id.in_(USER_IDS)))
        session.execute(delete(Factory).where(Factory.factory_id.in_(FACTORY_IDS)))


@pytest.fixture(autouse=True)
def clean_incoming_differences(test_database_engine: Engine) -> Iterator[None]:
    _clean(test_database_engine)
    yield
    _clean(test_database_engine)


def _seed_masters(session: Session) -> None:
    session.add_all(
        [
            Factory(
                factory_id=factory_id,
                supplier_number=f"IDF-{index}",
                factory_name=f"来货测试工厂{index}",
                factory_code=f"IDF{index}",
                is_enabled=True,
            )
            for index, factory_id in enumerate(FACTORY_IDS, 1)
        ]
    )
    session.flush()
    session.add_all(
        [
            User(user_id=ADMIN, role="admin", is_enabled=True, feishu_display_name="来货管理员"),
            User(
                user_id=OTHER_ADMIN,
                role="admin",
                is_enabled=True,
                feishu_display_name="另一管理员",
            ),
            User(
                user_id=DISABLED_ADMIN,
                role="admin",
                is_enabled=False,
                feishu_display_name="停用管理员",
            ),
            User(
                user_id=FACTORY_USER,
                role="factory",
                is_enabled=True,
                feishu_display_name="工厂用户",
                factory_id=FACTORY_A,
                factory_position="employee",
            ),
        ]
    )
    session.add(
        Product(
            product_id="idf-product",
            source_i_id="IDF-ITEM",
            name="来货测试产品",
            is_available=True,
            image_cache_status="missing",
            source_modified_at=SOURCE_TIME,
            first_synced_at=SOURCE_TIME,
            last_synced_at=SOURCE_TIME,
        )
    )
    session.flush()
    session.add_all(
        [
            ProductVariant(
                variant_id="idf-variant-1",
                product_id="idf-product",
                source_sku_id="IDF-SKU-1",
                properties_value="红色 / 110",
                is_available=True,
                source_modified_at=SOURCE_TIME,
                first_synced_at=SOURCE_TIME,
                last_synced_at=SOURCE_TIME,
            ),
            ProductVariant(
                variant_id="idf-variant-2",
                product_id="idf-product",
                source_sku_id="IDF-SKU-2",
                properties_value="蓝色 / 120",
                is_available=True,
                source_modified_at=SOURCE_TIME,
                first_synced_at=SOURCE_TIME,
                last_synced_at=SOURCE_TIME,
            ),
        ]
    )
    session.add_all(
        [
            StoredFile(
                file_id=FILE_IDS[0],
                bucket="incoming-diff",
                object_key="images/idf/1.jpg",
                original_filename="来货.jpg",
                mime_type="image/jpeg",
                size_bytes=1024,
                content_sha256="a" * 64,
                uploaded_by=ADMIN,
            ),
            StoredFile(
                file_id=FILE_IDS[1],
                bucket="incoming-diff",
                object_key="workbooks/idf/1.xlsx",
                original_filename="核对表.xlsx",
                mime_type=(
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                ),
                size_bytes=2048,
                content_sha256="b" * 64,
                uploaded_by=ADMIN,
            ),
        ]
    )


def _seed_order(session: Session) -> tuple[int, int]:
    session.add(
        Order(
            order_id=ORDER_ID,
            order_no="IDF-ORDER-1",
            source="manual",
            order_date=date(2026, 9, 1),
            tracker="松子",
            trackers=["松子"],
            detail_mode=True,
            lifecycle="PUBLISHED",
            created_by=ADMIN,
            updated_by=ADMIN,
            created_at=SOURCE_TIME,
            updated_at=SOURCE_TIME,
        )
    )
    session.flush()
    lines = []
    for index, (variant_id, properties, quantity) in enumerate(
        [("idf-variant-1", "红色 / 110", 100), ("idf-variant-2", "蓝色 / 120", 50)], 1
    ):
        line = OrderLine(
            order_id=ORDER_ID,
            product_variant_id=variant_id,
            order_quantity=quantity,
            sku_id_snapshot=f"IDF-SKU-{index}",
            product_name_snapshot="来货测试产品",
            properties_value_snapshot=properties,
            created_at=SOURCE_TIME,
            updated_at=SOURCE_TIME,
        )
        session.add(line)
        lines.append(line)
    session.flush()
    assignments = []
    for index, (line, factory_id, initial_shipped) in enumerate(
        [(lines[0], FACTORY_A, 10), (lines[1], FACTORY_B, 0)], 1
    ):
        assignment = OrderAssignment(
            order_line_id=line.order_line_id,
            factory_id=factory_id,
            is_active=True,
            contract_ship_date=date(2026, 9, 20),
            assigned_quantity=line.order_quantity,
            initial_shipped_quantity=initial_shipped,
            factory_name_snapshot=f"来货测试工厂{index}",
            created_at=SOURCE_TIME,
            updated_at=SOURCE_TIME,
        )
        session.add(assignment)
        assignments.append(assignment)
    session.flush()
    for index, (line, assignment) in enumerate(zip(lines, assignments, strict=True), 1):
        detail_id = f"idf-detail-{index}"
        session.add(
            OrderDetail(
                detail_id=detail_id,
                order_id=ORDER_ID,
                origin="manual",
                sort_order=index,
                accepted_raw_fields={},
                purchase_order_id=f"PO-{index}",
                purchase_order_item_id=f"POI-{index}",
                source_sku_id=line.sku_id_snapshot,
                product_name="来货测试产品",
                properties_value=line.properties_value_snapshot,
                matched_variant_id=line.product_variant_id,
                matched_factory_id=assignment.factory_id,
                order_quantity=line.order_quantity,
                source_trackers=["松子"],
                contract_ship_date=date(2026, 9, 20),
                parse_issues=[],
                assignment_id=assignment.order_assignment_id,
                dispatch_state="ASSIGNED",
                created_at=SOURCE_TIME,
                updated_at=SOURCE_TIME,
            )
        )
    session.flush()
    for index, assignment in enumerate(assignments, 1):
        assignment.detail_id = f"idf-detail-{index}"
    session.flush()
    return assignments[0].order_assignment_id, assignments[1].order_assignment_id


def _seed_batch(
    session: Session,
    *,
    lines: list[dict[str, Any]],
    status: str = "READY",
    submitter_id: str = ADMIN,
    version: int = 1,
) -> None:
    session.add(
        IncomingDiffBatch(
            batch_id=BATCH_ID,
            batch_no="IN20260918-01",
            submitter_id=submitter_id,
            feishu_chat_id="chat-1",
            feishu_open_id="open-1",
            status=status,
            created_at=SOURCE_TIME,
            updated_at=SOURCE_TIME,
            frozen_at=SOURCE_TIME,
        )
    )
    session.flush()
    session.add(
        IncomingDiffImage(
            image_id=IMAGE_ID,
            batch_id=BATCH_ID,
            sort_order=1,
            feishu_message_id="msg-1",
            feishu_image_key="img-key-1",
            file_id=FILE_IDS[0],
            content_sha256="a" * 64,
            ocr_status="SUCCEEDED",
            created_at=SOURCE_TIME,
        )
    )
    session.add(
        IncomingDiffWorkbook(
            workbook_id=WORKBOOK_ID,
            batch_id=BATCH_ID,
            version=version,
            direction="UPLOADED",
            file_id=FILE_IDS[1],
            content_sha256="b" * 64,
            line_snapshot=lines,
            submitted_by=submitter_id,
            submitted_at=SOURCE_TIME,
        )
    )
    session.flush()
    batch = session.get(IncomingDiffBatch, BATCH_ID)
    assert batch is not None
    batch.current_workbook_id = WORKBOOK_ID


def _line(
    assignment_id: int,
    quantity: int,
    *,
    purchase_order_id: str | None = "PO-1",
    purchase_order_item_id: str | None = "POI-1",
    row_number: int = 2,
    sheet_name: str = "来货测试工厂1",
    source_business_date: str | None = "2026-09-17",
    image_id: str = IMAGE_ID,
) -> dict[str, Any]:
    return {
        "imageId": image_id,
        "sheetName": sheet_name,
        "rowNumber": row_number,
        "orderAssignmentId": assignment_id,
        "purchaseOrderId": purchase_order_id,
        "purchaseOrderItemId": purchase_order_item_id,
        "quantity": quantity,
        "sourceBusinessDate": source_business_date,
    }


def _service(engine: Engine) -> IncomingDifferenceService:
    sessions = sessionmaker(engine, class_=Session, expire_on_commit=False)
    return IncomingDifferenceService(sessions, clock=lambda: NOW)


def _unified_shipped(session: Session, assignment_id: int) -> int:
    assignment = session.get(OrderAssignment, assignment_id)
    assert assignment is not None
    ledger_total = int(
        session.scalar(
            select(func.coalesce(func.sum(QuantityLedger.quantity_delta), 0)).where(
                QuantityLedger.order_assignment_id == assignment_id
            )
        )
        or 0
    )
    return assignment.initial_shipped_quantity + ledger_total


def test_confirm_writes_records_ledger_audit_and_one_outbox_per_factory_and_order(
    test_database_engine: Engine,
) -> None:
    with Session(test_database_engine) as session, session.begin():
        _seed_masters(session)
        first, second = _seed_order(session)
        _seed_batch(
            session,
            lines=[
                _line(first, 5, row_number=2),
                _line(first, -3, row_number=3),
                _line(
                    second,
                    2,
                    purchase_order_id="PO-2",
                    purchase_order_item_id="POI-2",
                    row_number=2,
                    sheet_name="来货测试工厂2",
                ),
            ],
        )

    result = _service(test_database_engine).confirm(
        batch_id=BATCH_ID, workbook_version=1, actor_id=ADMIN
    )

    assert result.record_count == 3
    assert result.factory_count == 2
    with Session(test_database_engine) as session:
        records = list(
            session.scalars(
                select(IncomingDiffRecord)
                .where(IncomingDiffRecord.order_id == ORDER_ID)
                .order_by(IncomingDiffRecord.registered_at, IncomingDiffRecord.record_id)
            )
        )
        assert sorted(record.quantity for record in records) == [-3, 2, 5]
        assert {record.initial_quantity for record in records} == {5, -3, 2}
        assert all(record.version == 1 for record in records)
        assert all(record.detail_id.startswith("idf-detail-") for record in records)
        assert all(record.product_name_snapshot == "来货测试产品" for record in records)
        assert all(record.product_code_snapshot == "IDF-ITEM" for record in records)
        assert all(record.source_business_date == date(2026, 9, 17) for record in records)
        ledger = list(
            session.scalars(
                select(QuantityLedger)
                .where(QuantityLedger.source_type == "INCOMING_DIFF")
                .order_by(QuantityLedger.ledger_id)
            )
        )
        assert len(ledger) == 3
        assert {row.source_id for row in ledger} == {record.record_id for record in records}
        # AC-13: 多货可以让统一已发超过下单数量，本例 10 + 5 - 3 = 12
        assert _unified_shipped(session, first) == 12
        assert _unified_shipped(session, second) == 2
        batch = session.get(IncomingDiffBatch, BATCH_ID)
        assert batch is not None
        assert batch.status == "CONFIRMED"
        assert batch.confirmed_by == ADMIN
        assert batch.confirmed_record_count == 3
        assert batch.confirmed_factory_count == 2
        messages = list(
            session.scalars(
                select(OutboxMessage)
                .where(OutboxMessage.event_type == "incoming_diff.registered")
                .order_by(OutboxMessage.id)
            )
        )
        assert {message.dedupe_key for message in messages} == {
            f"incoming-diff:{BATCH_ID}:{FACTORY_A}:{ORDER_ID}",
            f"incoming-diff:{BATCH_ID}:{FACTORY_B}:{ORDER_ID}",
        }
        audits = list(
            session.scalars(
                select(AuditLog).where(AuditLog.action == "incoming_diff_registered")
            )
        )
        assert len(audits) == 1
        changes = audits[0].changes
        assert changes["recordCount"] == 3
        assert changes["assignments"][str(first)] == {"before": 10, "after": 12}
        assert changes["assignments"][str(second)] == {"before": 0, "after": 2}
        # 订单完成状态不因来货出入回退
        order = session.get(Order, ORDER_ID)
        assert order is not None and order.lifecycle == "PUBLISHED"


def test_confirm_allows_over_shipping_beyond_ordered_quantity(
    test_database_engine: Engine,
) -> None:
    with Session(test_database_engine) as session, session.begin():
        _seed_masters(session)
        first, _second = _seed_order(session)
        _seed_batch(session, lines=[_line(first, 200)])

    _service(test_database_engine).confirm(
        batch_id=BATCH_ID, workbook_version=1, actor_id=ADMIN
    )

    with Session(test_database_engine) as session:
        assignment_id = session.scalar(
            select(IncomingDiffRecord.order_assignment_id).where(
                IncomingDiffRecord.order_id == ORDER_ID
            )
        )
        assert assignment_id is not None
        assert _unified_shipped(session, assignment_id) == 210


def test_repeat_confirm_of_the_same_version_returns_the_original_result(
    test_database_engine: Engine,
) -> None:
    with Session(test_database_engine) as session, session.begin():
        _seed_masters(session)
        first, _second = _seed_order(session)
        _seed_batch(session, lines=[_line(first, 5)])

    service = _service(test_database_engine)
    first_result = service.confirm(batch_id=BATCH_ID, workbook_version=1, actor_id=ADMIN)
    second_result = service.confirm(batch_id=BATCH_ID, workbook_version=1, actor_id=ADMIN)

    assert second_result.record_count == first_result.record_count
    assert second_result.confirmed_at == first_result.confirmed_at
    assert second_result.replayed is True
    with Session(test_database_engine) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(QuantityLedger)
                .where(QuantityLedger.source_type == "INCOMING_DIFF")
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(IncomingDiffRecord)
                .where(IncomingDiffRecord.order_id == ORDER_ID)
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(OutboxMessage)
                .where(OutboxMessage.event_type == "incoming_diff.registered")
            )
            == 1
        )


def test_one_failing_line_rolls_the_whole_batch_back(test_database_engine: Engine) -> None:
    with Session(test_database_engine) as session, session.begin():
        _seed_masters(session)
        first, second = _seed_order(session)
        _seed_batch(
            session,
            lines=[
                _line(first, 5, row_number=2),
                _line(second, 2, purchase_order_id=None, row_number=3),
            ],
        )

    with pytest.raises(IncomingDifferenceValidationError) as failure:
        _service(test_database_engine).confirm(
            batch_id=BATCH_ID, workbook_version=1, actor_id=ADMIN
        )

    assert failure.value.issues == [
        {"sheetName": "来货测试工厂1", "rowNumber": 3, "reason": "缺少采购主单号"}
    ]
    with Session(test_database_engine) as session:
        assert (
            session.scalar(select(func.count()).select_from(IncomingDiffRecord)) == 0
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(QuantityLedger)
                .where(QuantityLedger.source_type == "INCOMING_DIFF")
            )
            == 0
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(OutboxMessage)
                .where(OutboxMessage.event_type == "incoming_diff.registered")
            )
            == 0
        )
        batch = session.get(IncomingDiffBatch, BATCH_ID)
        assert batch is not None and batch.status == "READY"


def test_confirm_rejects_the_batch_when_unified_shipped_would_drop_below_zero(
    test_database_engine: Engine,
) -> None:
    with Session(test_database_engine) as session, session.begin():
        _seed_masters(session)
        first, second = _seed_order(session)
        _seed_batch(
            session,
            lines=[
                _line(first, 5, row_number=2),
                _line(
                    second,
                    -1,
                    purchase_order_id="PO-2",
                    purchase_order_item_id="POI-2",
                    row_number=3,
                    sheet_name="来货测试工厂2",
                ),
            ],
        )

    with pytest.raises(IncomingDifferenceValidationError) as failure:
        _service(test_database_engine).confirm(
            batch_id=BATCH_ID, workbook_version=1, actor_id=ADMIN
        )

    assert "统一已发数量" in str(failure.value)
    with Session(test_database_engine) as session:
        assert session.scalar(select(func.count()).select_from(IncomingDiffRecord)) == 0
        assert _unified_shipped(session, first) == 10
        assert _unified_shipped(session, second) == 0


def test_incoming_difference_does_not_net_against_a_receipt_difference(
    test_database_engine: Engine,
) -> None:
    with Session(test_database_engine) as session, session.begin():
        _seed_masters(session)
        first, _second = _seed_order(session)
        _seed_batch(session, lines=[_line(first, -2)])
        session.add(
            QuantityLedger(
                order_assignment_id=first,
                source_type="SHIPMENT_RECEIPT",
                source_id="idf-shipment",
                quantity_delta=-2,
                actor_id=ADMIN,
                created_at=SOURCE_TIME,
            )
        )

    _service(test_database_engine).confirm(
        batch_id=BATCH_ID, workbook_version=1, actor_id=ADMIN
    )

    with Session(test_database_engine) as session:
        assignment_id = session.scalar(
            select(IncomingDiffRecord.order_assignment_id).where(
                IncomingDiffRecord.order_id == ORDER_ID
            )
        )
        assert assignment_id is not None
        # 10 - 2（收货差额）- 2（来货出入）= 6，两个事实各自生效
        assert _unified_shipped(session, assignment_id) == 6
        assert (
            session.scalar(
                select(func.count())
                .select_from(QuantityLedger)
                .where(QuantityLedger.order_assignment_id == assignment_id)
            )
            == 2
        )


@pytest.mark.parametrize(
    ("actor_id", "submitter_id"),
    [
        (FACTORY_USER, ADMIN),
        (DISABLED_ADMIN, DISABLED_ADMIN),
        (OTHER_ADMIN, ADMIN),
    ],
)
def test_confirm_only_accepts_an_enabled_admin_confirming_their_own_batch(
    test_database_engine: Engine, actor_id: str, submitter_id: str
) -> None:
    with Session(test_database_engine) as session, session.begin():
        _seed_masters(session)
        first, _second = _seed_order(session)
        _seed_batch(session, lines=[_line(first, 5)], submitter_id=submitter_id)

    with pytest.raises(IncomingDifferencePermissionDenied):
        _service(test_database_engine).confirm(
            batch_id=BATCH_ID, workbook_version=1, actor_id=actor_id
        )

    with Session(test_database_engine) as session:
        assert session.scalar(select(func.count()).select_from(IncomingDiffRecord)) == 0
        assert (
            session.scalar(
                select(func.count())
                .select_from(QuantityLedger)
                .where(QuantityLedger.source_type == "INCOMING_DIFF")
            )
            == 0
        )


def test_batch_no_uses_shanghai_date_with_a_two_digit_daily_sequence(
    test_database_engine: Engine,
) -> None:
    with Session(test_database_engine) as session, session.begin():
        _seed_masters(session)
    # 2026-09-18 02:30 UTC 是上海时间 2026-09-18 10:30
    service = _service(test_database_engine)

    first = service.create_batch(submitter_id=ADMIN)
    second = service.create_batch(submitter_id=ADMIN)

    assert first.batch_no == "IN20260918-01"
    assert second.batch_no == "IN20260918-02"
    assert first.status == "COLLECTING"


def test_registered_event_notifies_every_enabled_factory_user(
    test_database_engine: Engine,
) -> None:
    with Session(test_database_engine) as session, session.begin():
        _seed_masters(session)
        first, _second = _seed_order(session)
        _seed_batch(session, lines=[_line(first, 5)])
        session.add(
            User(
                user_id=SECOND_FACTORY_USER,
                role="factory",
                is_enabled=True,
                feishu_display_name="同厂用户",
                factory_id=FACTORY_A,
                factory_position="employee",
            )
        )
        session.add(
            User(
                user_id=DISABLED_FACTORY_USER,
                role="factory",
                is_enabled=False,
                feishu_display_name="停用工厂用户",
                factory_id=FACTORY_A,
                factory_position="employee",
            )
        )
    _service(test_database_engine).confirm(
        batch_id=BATCH_ID, workbook_version=1, actor_id=ADMIN
    )
    sessions = sessionmaker(test_database_engine, class_=Session, expire_on_commit=False)
    notifications = NotificationsAuditService(sessions)

    assert notifications.consume_next_business_event(worker_id="idf-worker") is True

    with Session(test_database_engine) as session:
        rows = list(
            session.scalars(
                select(Notification)
                .where(Notification.event_type == "incoming_diff.registered")
                .order_by(Notification.recipient_id)
            )
        )
        assert [row.recipient_id for row in rows] == [FACTORY_USER, SECOND_FACTORY_USER]
        assert {row.category for row in rows} == {"INCOMING_DIFF"}
        assert rows[0].title == "订单来货出入已登记"
        assert "IDF-ORDER-1" in rows[0].summary
        assert rows[0].target_path.startswith("/pages/factory-task-detail/factory-task-detail")


def test_candidate_matching_needs_exactly_one_assignment(
    test_database_engine: Engine,
) -> None:
    with Session(test_database_engine) as session, session.begin():
        _seed_masters(session)
        first, _second = _seed_order(session)
    service = _service(test_database_engine)

    assert (
        service.match_assignment(
            factory_id=FACTORY_A,
            product_code="IDF-ITEM",
            product_name="来货测试产品",
            variant_id="idf-variant-1",
            source_business_date=date(2026, 9, 17),
        )
        == first
    )
    # 只按产品匹配时两个规格都是候选，多于一个即不唯一
    assert (
        service.match_assignment(
            product_code="IDF-ITEM",
            product_name="来货测试产品",
            source_business_date=date(2026, 9, 17),
        )
        is None
    )
    # 补上采购主单号后重新唯一
    assert (
        service.match_assignment(
            product_code="IDF-ITEM",
            product_name="来货测试产品",
            purchase_order_id="PO-1",
            source_business_date=date(2026, 9, 17),
        )
        == first
    )
    assert (
        service.match_assignment(
            product_code="NOT-EXIST",
            product_name="来货测试产品",
            source_business_date=date(2026, 9, 17),
        )
        is None
    )
