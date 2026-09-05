from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from io import BytesIO
from pathlib import Path
from threading import Barrier

import pytest
from openpyxl import load_workbook
from sqlalchemy import Engine, delete, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.adapters.private_files import FakePrivateFileStore, PrivateFileStoreUnavailable
from app.db.models import (
    ContractExport,
    ContractNumberCounter,
    Factory,
    Order,
    OrderAssignment,
    OrderLine,
    ProcessingContract,
    Product,
    ProductVariant,
    StoredFile,
    User,
    UserSession,
)
from app.modules.contracts import ContractService
from app.modules.contracts.workbook import ContractWorkbookRenderer

ADMIN_ID = "contract-admin"
FACTORY_ID = "contract-factory"
ORDER_ID = "contract-order"
SECOND_ORDER_ID = "contract-order-second"
PRODUCT_ID = "contract-product"
VARIANT_ID = "contract-variant"


def _clean(engine: Engine) -> None:
    with Session(engine) as session, session.begin():
        session.execute(delete(ContractExport).where(ContractExport.exported_by == ADMIN_ID))
        session.execute(delete(StoredFile).where(StoredFile.uploaded_by == ADMIN_ID))
        session.execute(
            delete(ProcessingContract).where(ProcessingContract.factory_id == FACTORY_ID)
        )
        session.execute(
            delete(ContractNumberCounter).where(ContractNumberCounter.factory_id == FACTORY_ID)
        )
        session.execute(delete(OrderAssignment).where(OrderAssignment.factory_id == FACTORY_ID))
        session.execute(
            delete(OrderLine).where(OrderLine.order_id.in_([ORDER_ID, SECOND_ORDER_ID]))
        )
        session.execute(delete(Order).where(Order.order_id.in_([ORDER_ID, SECOND_ORDER_ID])))
        session.execute(delete(ProductVariant).where(ProductVariant.variant_id == VARIANT_ID))
        session.execute(delete(Product).where(Product.product_id == PRODUCT_ID))
        session.execute(delete(UserSession).where(UserSession.user_id == ADMIN_ID))
        session.execute(delete(User).where(User.user_id == ADMIN_ID))
        session.execute(delete(Factory).where(Factory.factory_id == FACTORY_ID))


def _seed_published_order(engine: Engine) -> None:
    now = datetime(2026, 8, 24, 8, 0, tzinfo=UTC)
    with Session(engine) as session, session.begin():
        session.add(
            Factory(
                factory_id=FACTORY_ID,
                supplier_number="HT-001",
                factory_name="合同测试工厂",
                factory_code="HT",
                legal_name="合同测试工厂有限公司",
                address="浙江省杭州市测试路1号",
                legal_representative="测试法人",
                is_enabled=True,
            )
        )
        session.add(
            User(
                user_id=ADMIN_ID,
                role="admin",
                is_enabled=True,
                feishu_display_name="煎饼",
            )
        )
        session.add(
            Product(
                product_id=PRODUCT_ID,
                source_i_id="MZ2026-01",
                name="儿童遮阳帽",
                is_available=True,
                source_modified_at=now,
                first_synced_at=now,
                last_synced_at=now,
            )
        )
        session.add(
            ProductVariant(
                variant_id=VARIANT_ID,
                product_id=PRODUCT_ID,
                source_sku_id="6970000000001",
                properties_value="米色 / 52cm",
                source_category="童帽春夏",
                source_enabled=1,
                is_available=True,
                source_modified_at=now,
                first_synced_at=now,
                last_synced_at=now,
            )
        )
        session.flush()
        session.add(
            Order(
                order_id=ORDER_ID,
                order_no="HT-ORDER-001",
                source="manual",
                order_date=date(2026, 8, 20),
                tracker="松子",
                contract_ship_date=date(2026, 9, 10),
                lifecycle="PUBLISHED",
                version=2,
                created_by=ADMIN_ID,
                updated_by=ADMIN_ID,
                created_at=now,
                updated_at=now,
            )
        )
        session.flush()
        line = OrderLine(
            order_id=ORDER_ID,
            product_variant_id=VARIANT_ID,
            order_quantity=100,
            sku_id_snapshot="6970000000001",
            product_name_snapshot="儿童遮阳帽",
            properties_value_snapshot="米色 / 52cm",
            category_snapshot="童帽春夏",
            created_at=now,
            updated_at=now,
        )
        session.add(line)
        session.flush()
        session.add(
            OrderAssignment(
                order_line_id=line.order_line_id,
                factory_id=FACTORY_ID,
                assigned_quantity=100,
                factory_name_snapshot="合同测试工厂",
                created_at=now,
                updated_at=now,
            )
        )


def _seed_second_published_order(engine: Engine) -> None:
    now = datetime(2026, 8, 24, 8, 30, tzinfo=UTC)
    with Session(engine) as session, session.begin():
        session.add(
            Order(
                order_id=SECOND_ORDER_ID,
                order_no="HT-ORDER-002",
                source="manual",
                order_date=date(2026, 8, 21),
                tracker="松子",
                contract_ship_date=date(2026, 9, 11),
                lifecycle="PUBLISHED",
                version=2,
                created_by=ADMIN_ID,
                updated_by=ADMIN_ID,
                created_at=now,
                updated_at=now,
            )
        )
        session.flush()
        line = OrderLine(
            order_id=SECOND_ORDER_ID,
            product_variant_id=VARIANT_ID,
            order_quantity=30,
            sku_id_snapshot="6970000000001",
            product_name_snapshot="儿童遮阳帽",
            properties_value_snapshot="米色 / 52cm",
            category_snapshot="童帽春夏",
            created_at=now,
            updated_at=now,
        )
        session.add(line)
        session.flush()
        session.add(
            OrderAssignment(
                order_line_id=line.order_line_id,
                factory_id=FACTORY_ID,
                assigned_quantity=30,
                factory_name_snapshot="合同测试工厂",
                created_at=now,
                updated_at=now,
            )
        )


def test_published_order_lists_factory_as_ready_for_first_contract_export(
    test_database_engine: Engine,
) -> None:
    _clean(test_database_engine)
    _seed_published_order(test_database_engine)
    service = ContractService(
        sessionmaker(test_database_engine, class_=Session, expire_on_commit=False)
    )

    try:
        states = service.list_for_order(actor_id=ADMIN_ID, order_id=ORDER_ID)

        assert len(states) == 1
        state = states[0]
        assert state.factory_id == FACTORY_ID
        assert state.factory_name == "合同测试工厂"
        assert state.contract_ready is True
        assert state.missing_contract_fields == []
        assert state.eligible is True
        assert state.contract_no is None
        assert state.signing_date is None
    finally:
        _clean(test_database_engine)


def test_initial_shipped_quantity_makes_contract_ineligible(
    test_database_engine: Engine,
) -> None:
    _clean(test_database_engine)
    _seed_published_order(test_database_engine)
    with Session(test_database_engine) as session, session.begin():
        session.query(OrderAssignment).filter_by(
            factory_id=FACTORY_ID
        ).one().initial_shipped_quantity = 1
    service = ContractService(
        sessionmaker(test_database_engine, class_=Session, expire_on_commit=False)
    )
    try:
        state = service.list_for_order(actor_id=ADMIN_ID, order_id=ORDER_ID)[0]
        assert state.eligible is False
        assert state.ineligible_reason == "order_has_shipments"
    finally:
        _clean(test_database_engine)


def test_first_export_allocates_stable_number_snapshot_and_private_xlsx(
    test_database_engine: Engine,
) -> None:
    _clean(test_database_engine)
    _seed_published_order(test_database_engine)
    file_store = FakePrivateFileStore(bucket="contract-test")
    template = Path(__file__).resolve().parents[2] / "app/templates/processing_contract_v1.xlsx"
    service = ContractService(
        sessionmaker(test_database_engine, class_=Session, expire_on_commit=False),
        workbook_renderer=ContractWorkbookRenderer(template_path=template),
        file_store=file_store,
        clock=lambda: datetime(2026, 8, 24, 9, 30, tzinfo=UTC),
    )

    try:
        result = service.create_export(
            actor_id=ADMIN_ID,
            order_id=ORDER_ID,
            factory_id=FACTORY_ID,
            signing_date=date(2026, 8, 24),
            idempotency_key="contract-first-export",
            request_id="contract-request-1",
        )

        assert result.status == "READY"
        assert result.contract_no == "20260824-KK-HT"
        assert result.signing_date == date(2026, 8, 24)
        assert result.filename == "20260824-KK-HT HT-ORDER-001 儿童遮阳帽.xlsx"
        assert file_store.object_count == 1
        filename, content, content_type = service.download(
            actor_id=ADMIN_ID, export_id=result.export_id
        )
        assert filename == result.filename
        assert content == file_store.get(object_key=result.object_key)
        assert content_type == ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        with Session(test_database_engine) as session:
            contract = session.get(ProcessingContract, result.contract_id)
            assert contract is not None
            assert contract.contract_snapshot["lines"] == [
                {
                    "productId": PRODUCT_ID,
                    "itemNo": "MZ2026-01",
                    "productName": "儿童遮阳帽",
                    "propertiesValue": "米色 / 52cm",
                    "quantity": 100,
                    "imageObjectKey": None,
                }
            ]
            serialized = str(contract.contract_snapshot).lower()
            assert "price" not in serialized
            assert "amount" not in serialized
    finally:
        _clean(test_database_engine)


def test_repeat_export_reuses_first_snapshot_and_same_request_is_idempotent(
    test_database_engine: Engine,
) -> None:
    _clean(test_database_engine)
    _seed_published_order(test_database_engine)
    file_store = FakePrivateFileStore(bucket="contract-test")
    template = Path(__file__).resolve().parents[2] / "app/templates/processing_contract_v1.xlsx"
    service = ContractService(
        sessionmaker(test_database_engine, class_=Session, expire_on_commit=False),
        workbook_renderer=ContractWorkbookRenderer(template_path=template),
        file_store=file_store,
        clock=lambda: datetime(2026, 8, 24, 9, 30, tzinfo=UTC),
    )

    try:
        first = service.create_export(
            actor_id=ADMIN_ID,
            order_id=ORDER_ID,
            factory_id=FACTORY_ID,
            signing_date=date(2026, 8, 24),
            idempotency_key="contract-repeat-first",
            request_id="contract-repeat-request-1",
        )
        same_request = service.create_export(
            actor_id=ADMIN_ID,
            order_id=ORDER_ID,
            factory_id=FACTORY_ID,
            signing_date=date(2026, 8, 24),
            idempotency_key="contract-repeat-first",
            request_id="contract-repeat-request-1-retry",
        )
        assert same_request.export_id == first.export_id
        assert file_store.object_count == 1

        with Session(test_database_engine) as session, session.begin():
            factory = session.get(Factory, FACTORY_ID)
            product = session.get(Product, PRODUCT_ID)
            order = session.get(Order, ORDER_ID)
            assert factory is not None and product is not None and order is not None
            factory.factory_code = None
            factory.legal_name = "修改后的工厂名称"
            product.source_i_id = "NEW-ITEM-NO"
            product.name = "修改后的产品名称"
            order.order_no = "CHANGED-ORDER-NO"

        assert service.list_for_order(actor_id=ADMIN_ID, order_id=ORDER_ID)[0].eligible
        repeated = service.create_export(
            actor_id=ADMIN_ID,
            order_id=ORDER_ID,
            factory_id=FACTORY_ID,
            signing_date=None,
            idempotency_key="contract-repeat-second",
            request_id="contract-repeat-request-2",
        )

        assert repeated.export_id != first.export_id
        assert repeated.contract_id == first.contract_id
        assert repeated.contract_no == first.contract_no
        assert repeated.signing_date == first.signing_date
        assert repeated.filename == first.filename
        assert file_store.object_count == 2
        _filename, content, _content_type = service.download(
            actor_id=ADMIN_ID, export_id=repeated.export_id
        )
        sheet = load_workbook(BytesIO(content), data_only=False)["合同"]
        assert sheet["A4"].value == "供方：合同测试工厂有限公司"
        assert sheet["A8"].value == "MZ2026-01"
        assert sheet["B8"].value == "儿童遮阳帽"
    finally:
        _clean(test_database_engine)


@pytest.mark.parametrize("new_code", ["HT", "NEW"])
def test_same_day_same_factory_contract_numbers_keep_stable_sequence(
    test_database_engine: Engine, new_code: str,
) -> None:
    _clean(test_database_engine)
    _seed_published_order(test_database_engine)
    _seed_second_published_order(test_database_engine)
    file_store = FakePrivateFileStore(bucket="contract-test")
    template = Path(__file__).resolve().parents[2] / "app/templates/processing_contract_v1.xlsx"
    service = ContractService(
        sessionmaker(test_database_engine, class_=Session, expire_on_commit=False),
        workbook_renderer=ContractWorkbookRenderer(template_path=template),
        file_store=file_store,
        clock=lambda: datetime(2026, 8, 24, 10, 0, tzinfo=UTC),
    )

    try:
        first = service.create_export(
            actor_id=ADMIN_ID,
            order_id=ORDER_ID,
            factory_id=FACTORY_ID,
            signing_date=date(2026, 8, 24),
            idempotency_key="contract-sequence-first",
            request_id="contract-sequence-request-1",
        )
        with Session(test_database_engine) as session, session.begin():
            session.get(Factory, FACTORY_ID).factory_code = new_code
        second = service.create_export(
            actor_id=ADMIN_ID,
            order_id=SECOND_ORDER_ID,
            factory_id=FACTORY_ID,
            signing_date=date(2026, 8, 24),
            idempotency_key="contract-sequence-second",
            request_id="contract-sequence-request-2",
        )

        assert first.contract_no == "20260824-KK-HT"
        assert second.contract_no == f"20260824-KK-{new_code}-1"
        with Session(test_database_engine) as session:
            sequences = list(
                session.scalars(
                    select(ProcessingContract.daily_sequence).order_by(
                        ProcessingContract.daily_sequence
                    )
                )
            )
            assert sequences == [0, 1]
    finally:
        _clean(test_database_engine)


def test_failed_upload_keeps_contract_number_but_never_creates_downloadable_file(
    test_database_engine: Engine,
) -> None:
    _clean(test_database_engine)
    _seed_published_order(test_database_engine)
    file_store = FakePrivateFileStore(bucket="contract-test", fail_put=True)
    template = Path(__file__).resolve().parents[2] / "app/templates/processing_contract_v1.xlsx"
    service = ContractService(
        sessionmaker(test_database_engine, class_=Session, expire_on_commit=False),
        workbook_renderer=ContractWorkbookRenderer(template_path=template),
        file_store=file_store,
        clock=lambda: datetime(2026, 8, 24, 10, 30, tzinfo=UTC),
    )

    try:
        with pytest.raises(PrivateFileStoreUnavailable):
            service.create_export(
                actor_id=ADMIN_ID,
                order_id=ORDER_ID,
                factory_id=FACTORY_ID,
                signing_date=date(2026, 8, 24),
                idempotency_key="contract-failed-upload",
                request_id="contract-failed-request",
            )

        assert file_store.object_count == 0
        with Session(test_database_engine) as session:
            contract = session.scalar(
                select(ProcessingContract).where(
                    ProcessingContract.order_id == ORDER_ID,
                    ProcessingContract.factory_id == FACTORY_ID,
                )
            )
            export = session.scalar(
                select(ContractExport).where(
                    ContractExport.idempotency_key == "contract-failed-upload"
                )
            )
            assert contract is not None
            assert contract.contract_no == "20260824-KK-HT"
            assert export is not None
            assert export.status == "FAILED"
            assert export.stored_file_id is None
            assert (
                session.scalar(select(StoredFile.file_id).where(StoredFile.uploaded_by == ADMIN_ID))
                is None
            )
    finally:
        _clean(test_database_engine)


def test_concurrent_first_exports_for_same_order_create_one_stable_contract(
    test_database_engine: Engine,
) -> None:
    _clean(test_database_engine)
    _seed_published_order(test_database_engine)
    file_store = FakePrivateFileStore(bucket="contract-concurrency-test")
    template = Path(__file__).resolve().parents[2] / "app/templates/processing_contract_v1.xlsx"
    service = ContractService(
        sessionmaker(test_database_engine, class_=Session, expire_on_commit=False),
        workbook_renderer=ContractWorkbookRenderer(template_path=template),
        file_store=file_store,
        clock=lambda: datetime(2026, 8, 24, 12, 0, tzinfo=UTC),
    )
    barrier = Barrier(2)

    def export(key: str):  # type: ignore[no-untyped-def]
        barrier.wait()
        return service.create_export(
            actor_id=ADMIN_ID,
            order_id=ORDER_ID,
            factory_id=FACTORY_ID,
            signing_date=date(2026, 8, 24),
            idempotency_key=key,
            request_id=f"request-{key}",
        )

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(export, ["same-order-a", "same-order-b"]))

        assert {result.contract_id for result in results} == {results[0].contract_id}
        assert {result.contract_no for result in results} == {"20260824-KK-HT"}
        assert len({result.export_id for result in results}) == 2
        with Session(test_database_engine) as session:
            assert session.scalar(select(func.count(ProcessingContract.contract_id))) == 1
    finally:
        _clean(test_database_engine)


def test_concurrent_same_day_factory_exports_allocate_unique_sequence(
    test_database_engine: Engine,
) -> None:
    _clean(test_database_engine)
    _seed_published_order(test_database_engine)
    _seed_second_published_order(test_database_engine)
    file_store = FakePrivateFileStore(bucket="contract-concurrency-test")
    template = Path(__file__).resolve().parents[2] / "app/templates/processing_contract_v1.xlsx"
    service = ContractService(
        sessionmaker(test_database_engine, class_=Session, expire_on_commit=False),
        workbook_renderer=ContractWorkbookRenderer(template_path=template),
        file_store=file_store,
        clock=lambda: datetime(2026, 8, 24, 12, 30, tzinfo=UTC),
    )
    barrier = Barrier(2)

    def export(order_id: str):  # type: ignore[no-untyped-def]
        barrier.wait()
        return service.create_export(
            actor_id=ADMIN_ID,
            order_id=order_id,
            factory_id=FACTORY_ID,
            signing_date=date(2026, 8, 24),
            idempotency_key=f"different-order-{order_id}",
            request_id=f"request-{order_id}",
        )

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(export, [ORDER_ID, SECOND_ORDER_ID]))

        assert {result.contract_no for result in results} == {
            "20260824-KK-HT",
            "20260824-KK-HT-1",
        }
    finally:
        _clean(test_database_engine)


def test_empty_code_blocks_first_export_and_migration_preserves_existing_contract(
    test_database_engine: Engine,
    tmp_path: Path,
) -> None:
    from app.modules.contracts.service import ContractValidationError
    from scripts.migrate_factory_codes import apply_plan, preview, rollback

    _seed_published_order(test_database_engine)
    _seed_second_published_order(test_database_engine)
    sessions = sessionmaker(test_database_engine, class_=Session, expire_on_commit=False)
    template = Path(__file__).resolve().parents[2] / "app/templates/processing_contract_v1.xlsx"
    service = ContractService(
        sessions,
        workbook_renderer=ContractWorkbookRenderer(template_path=template),
        file_store=FakePrivateFileStore(bucket="contract-test"),
    )
    first = service.create_export(
        actor_id=ADMIN_ID,
        order_id=ORDER_ID,
        factory_id=FACTORY_ID,
        signing_date=date(2026, 8, 24),
        idempotency_key="before-migration",
        request_id="before-migration",
    )
    with sessions() as session, session.begin():
        original_snapshot = dict(
            session.get(ProcessingContract, first.contract_id).contract_snapshot
        )
        session.add(
            Factory(
                factory_id="duplicate-factory",
                supplier_number="DUP",
                factory_name="重复代码工厂",
                factory_code="HT-分厂",
            )
        )
    plan = preview(sessions)
    backup = tmp_path / "backup.json"
    apply_plan(sessions, plan, backup)
    assert not service.list_for_order(actor_id=ADMIN_ID, order_id=SECOND_ORDER_ID)[0].eligible
    with pytest.raises(ContractValidationError, match="factoryCode"):
        service.create_export(
            actor_id=ADMIN_ID,
            order_id=SECOND_ORDER_ID,
            factory_id=FACTORY_ID,
            signing_date=date(2026, 8, 24),
            idempotency_key="blocked",
            request_id="blocked",
        )
    repeated = service.create_export(
        actor_id=ADMIN_ID,
        order_id=ORDER_ID,
        factory_id=FACTORY_ID,
        signing_date=None,
        idempotency_key="after-migration",
        request_id="after-migration",
    )
    assert repeated.contract_no == first.contract_no
    with sessions() as session:
        assert (
            session.get(ProcessingContract, first.contract_id).contract_snapshot
            == original_snapshot
        )
    rollback(sessions, backup)
    with sessions() as session:
        assert session.get(Factory, FACTORY_ID).factory_code == "HT"
        assert (
            session.get(ProcessingContract, first.contract_id).contract_snapshot
            == original_snapshot
        )
