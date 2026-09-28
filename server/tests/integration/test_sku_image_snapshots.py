from datetime import date
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, select, text
from sqlalchemy.orm import sessionmaker

from app.adapters.order_source import FakeFeishuOrderSource
from app.adapters.private_files import FakePrivateFileStore
from app.db.models import (
    Factory,
    Order,
    OrderImportCandidateLine,
    OrderLine,
    ProcessingContract,
    Product,
    ProductVariant,
)
from app.modules.contracts import ContractService
from app.modules.contracts.workbook import ContractWorkbookRenderer
from app.modules.order_import import OrderImportService
from app.modules.order_import.auto_sync import OrderAutoSync
from app.modules.orders import AssignmentInput, DraftLineInput, OrderService
from app.modules.orders.dispatch import OrderDispatchService
from tests.integration.test_order_dispatch import _row
from tests.integration.test_order_import import _seed_import_dependencies
from tests.integration.test_order_lifecycle import _seed_order_dependencies


def test_automatic_import_and_dispatch_freeze_the_sku_image(
    test_database_engine: Engine,
) -> None:
    _seed_import_dependencies(test_database_engine)
    sessions = sessionmaker(test_database_engine, expire_on_commit=False)
    with sessions() as session, session.begin():
        session.get(Product, "product-import").image_object_key = "products/wrong-common"
        variant = session.get(ProductVariant, "variant-import")
        variant.image_object_key = "products/sku-auto"
        variant.image_cache_status = "cached"
    sync = OrderAutoSync(sessions, source=FakeFeishuOrderSource([[_row()]]))
    run_id = sync.ensure_due()
    assert run_id is not None
    for _ in range(100):
        if sync.run_step({"runId": run_id}):
            break
    else:
        raise AssertionError("自动同步未完成")
    with sessions() as session:
        assert session.scalar(select(Order)).lifecycle == "PUBLISHED"
        assert session.scalar(select(OrderLine)).image_object_key_snapshot == "products/sku-auto"


def test_import_dispatch_and_contract_freeze_sku_image_without_rewriting_history(
    test_database_engine: Engine,
) -> None:
    _seed_import_dependencies(test_database_engine)
    sessions = sessionmaker(test_database_engine, expire_on_commit=False)
    with sessions() as session, session.begin():
        session.get(Product, "product-import").image_object_key = "products/wrong-common"
        variant = session.get(ProductVariant, "variant-import")
        variant.image_object_key = "products/blue-v1"
        variant.image_cache_status = "cached"
        factory = session.get(Factory, "factory-import")
        factory.legal_name = "测试公司"
        factory.address = "测试地址"
        factory.legal_representative = "测试法人"
    importer = OrderImportService(sessions)
    run = importer.create_or_reuse_run(actor_id="admin-order-import", request_id="image-import")
    importer.process_run(run_id=run.run_id, pages_read=1, rows=[_row()], source_scope="images")
    candidates, _ = importer.list_candidates(actor_id="admin-order-import")
    with sessions() as session:
        assert session.scalar(select(OrderImportCandidateLine)).image_object_key_snapshot == (
            "products/blue-v1"
        )
    order_id = importer.confirm_candidate(
        actor_id="admin-order-import", candidate_id=candidates[0].candidate_id,
        request_id="image-confirm",
    )
    templates = Path(__file__).resolve().parents[2] / "app/templates"
    contracts = ContractService(
        sessions, workbook_renderer=ContractWorkbookRenderer(
            template_paths={"v2": templates / "processing_contract_v2.xlsx"},
        ), file_store=FakePrivateFileStore(bucket="images"),
    )
    contracts.create_export(
        actor_id="admin-order-import", order_id=order_id, factory_id="factory-import",
        signing_date=date(2026, 9, 28), idempotency_key="first", request_id="first",
    )
    with sessions() as session:
        snapshot = session.scalar(select(ProcessingContract)).contract_snapshot
        assert snapshot["lines"][0]["imageObjectKey"] == "products/blue-v1"
    dispatch = OrderDispatchService(sessions, source=FakeFeishuOrderSource([[_row()]]))
    order = dispatch.get(order_id=order_id)
    preview = dispatch.dispatch_preview(
        actor_id="admin-order-import", order_id=order_id, version=order.version,
        detail_ids=[order.details[0].detail_id], request_id="dispatch",
    )
    dispatch.dispatch_confirm(
        actor_id="admin-order-import", order_id=order_id, version=order.version,
        preview_id=preview["preview_id"], idempotency_key="dispatch", request_id="dispatch",
    )
    with sessions() as session, session.begin():
        assert session.scalar(select(OrderLine)).image_object_key_snapshot == "products/blue-v1"
        session.get(ProductVariant, "variant-import").image_object_key = "products/blue-v2"
    contracts.create_export(
        actor_id="admin-order-import", order_id=order_id, factory_id="factory-import",
        signing_date=date(2026, 9, 28), idempotency_key="repeat", request_id="repeat",
    )
    with sessions() as session:
        assert session.scalar(select(ProcessingContract)).contract_snapshot == snapshot
        assert session.scalar(select(OrderLine)).image_object_key_snapshot == "products/blue-v1"


def test_manual_order_uses_sku_cache_and_migration_preserves_old_references(
    test_database_engine: Engine, test_database_url: str,
) -> None:
    admin, factory, _, variant_id = _seed_order_dependencies(test_database_engine)
    sessions = sessionmaker(test_database_engine, expire_on_commit=False)
    with sessions() as session, session.begin():
        variant = session.get(ProductVariant, variant_id)
        product = session.get(Product, variant.product_id)
        product.image_object_key = "products/legacy-common"
        variant.image_object_key = "products/sku-snapshot"
        variant.image_cache_status = "cached"
    order = OrderService(sessions).create_draft(
        actor_id=admin, order_no="IMAGE-MIGRATION", order_date=date(2026, 9, 28), tracker="松子",
        lines=[DraftLineInput(variant_id, 10, [AssignmentInput(
            factory, 10, contract_ship_date=date(2026, 12, 1),
        )])], request_id="manual-image",
    )
    assert order.lines[0].image_object_key == "products/sku-snapshot"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", test_database_url)
    command.downgrade(config, "20260924_0045")
    with test_database_engine.connect() as connection:
        previous = connection.execute(text("SELECT * FROM order_lines")).mappings().all()
    command.upgrade(config, "head")
    with test_database_engine.connect() as connection:
        assert connection.execute(text("SELECT * FROM order_lines")).mappings().all() == previous
    with sessions() as session:
        variant = session.get(ProductVariant, variant_id)
        assert variant.image_cache_status == "missing" and variant.image_object_key is None
        assert session.get(Product, variant.product_id).image_object_key == "products/legacy-common"
