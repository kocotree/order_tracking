from datetime import datetime

import pytest
from sqlalchemy import Engine, delete, select
from sqlalchemy.orm import Session, sessionmaker

from app.adapters.product import FakeJstProductSource, ProductSourceError, SourceProductVariant
from app.db.models import Product, ProductSyncRun, ProductVariant
from app.modules.product_sync import ProductSyncService


def source_variant(
    *,
    i_id: str,
    sku_id: str,
    category: str | None,
    enabled: int | None,
) -> SourceProductVariant:
    return SourceProductVariant(
        i_id=i_id,
        sku_id=sku_id,
        name=f"产品 {i_id}",
        properties_value="藏青,54",
        pic=None,
        category=category,
        enabled=enabled,
        source_modified_at=datetime(2026, 8, 21, 8, 0),
    )


@pytest.fixture(autouse=True)
def clean_product_tables(test_database_engine: Engine) -> None:
    with Session(test_database_engine) as session, session.begin():
        session.execute(delete(ProductVariant))
        session.execute(delete(ProductSyncRun))
        session.execute(delete(Product))


def test_initial_sync_only_makes_exact_allowlisted_enabled_variants_available(
    test_database_engine: Engine,
) -> None:
    session_factory = sessionmaker(test_database_engine, class_=Session, expire_on_commit=False)
    source = FakeJstProductSource(
        initial_pages=[
            [
                *[
                    source_variant(
                        i_id=f"ITEM-{index}",
                        sku_id=f"SKU-{index}",
                        category=category,
                        enabled=1,
                    )
                    for index, category in enumerate(
                        [
                            "童帽春夏",
                            "童配春夏",
                            "童装春夏",
                            "童帽秋冬",
                            "童配秋冬",
                            "童装秋冬",
                        ],
                        start=1,
                    )
                ],
                source_variant(i_id="HAT-2", sku_id="SKU-HAT-2", category="童帽春夏款", enabled=1),
                source_variant(i_id="HAT-3", sku_id="SKU-HAT-3", category="童帽春夏", enabled=0),
                source_variant(i_id="HAT-4", sku_id="SKU-HAT-4", category=None, enabled=1),
                source_variant(i_id="HAT-5", sku_id="SKU-HAT-5", category="童帽春夏", enabled=2),
            ]
        ],
        candidate_cursor="cursor-1",
    )

    result = ProductSyncService(session_factory, source=source).run_initial(
        request_id="request-initial-scope",
        worker_id="worker-test",
    )

    assert result.status == "succeeded"
    assert result.included_records == 6
    assert result.ignored_records == 4
    assert result.success_cursor == "cursor-1"
    with session_factory() as session:
        products = session.scalars(select(Product)).all()
        variants = session.scalars(select(ProductVariant)).all()
    assert sorted((product.source_i_id, product.is_available) for product in products) == [
        (f"ITEM-{index}", True) for index in range(1, 7)
    ]
    assert sorted((variant.source_sku_id, variant.is_available) for variant in variants) == [
        (f"SKU-{index}", True) for index in range(1, 7)
    ]


def test_failed_source_page_records_failure_without_advancing_the_last_success_cursor(
    test_database_engine: Engine,
) -> None:
    session_factory = sessionmaker(test_database_engine, class_=Session, expire_on_commit=False)
    successful_source = FakeJstProductSource(
        initial_pages=[
            [source_variant(i_id="HAT-1", sku_id="SKU-1", category="童帽秋冬", enabled=1)]
        ],
        candidate_cursor="cursor-success",
    )
    ProductSyncService(session_factory, source=successful_source).run_initial(
        request_id="request-success",
        worker_id="worker-test",
    )
    failing_source = FakeJstProductSource(
        initial_pages=[
            [source_variant(i_id="HAT-2", sku_id="SKU-2", category="童帽春夏", enabled=1)],
            [source_variant(i_id="HAT-3", sku_id="SKU-3", category="童配春夏", enabled=1)],
        ],
        candidate_cursor="cursor-not-committed",
        fail_initial_page=2,
    )

    with pytest.raises(ProductSourceError, match="product_source_page_failed"):
        ProductSyncService(session_factory, source=failing_source).run_initial(
            request_id="request-failed",
            worker_id="worker-test",
        )

    with session_factory() as session:
        runs = session.scalars(select(ProductSyncRun).order_by(ProductSyncRun.started_at)).all()
        variants = session.scalars(
            select(ProductVariant).order_by(ProductVariant.source_sku_id)
        ).all()
    assert [(run.status, run.success_cursor, run.error_code) for run in runs] == [
        ("succeeded", "cursor-success", None),
        ("failed", None, "product_source_page_failed"),
    ]
    assert [variant.source_sku_id for variant in variants] == ["SKU-1"]


def test_incremental_sync_updates_enter_exit_disable_and_reenable_without_deleting_history(
    test_database_engine: Engine,
) -> None:
    session_factory = sessionmaker(test_database_engine, class_=Session, expire_on_commit=False)
    initial = FakeJstProductSource(
        initial_pages=[
            [
                source_variant(i_id="KEEP", sku_id="SKU-KEEP", category="童装春夏", enabled=1),
                source_variant(i_id="OFF", sku_id="SKU-OFF", category="童帽春夏", enabled=1),
                source_variant(i_id="OUT", sku_id="SKU-OUT", category="童配秋冬", enabled=1),
                source_variant(i_id="BACK", sku_id="SKU-BACK", category="童装秋冬", enabled=1),
                source_variant(i_id="ENTER", sku_id="SKU-ENTER", category="邮费", enabled=1),
            ]
        ],
        candidate_cursor="cursor-initial",
    )
    ProductSyncService(session_factory, source=initial).run_initial(
        request_id="request-initial",
        worker_id="worker-test",
    )
    increment = FakeJstProductSource(
        incremental_pages=[
            [
                source_variant(i_id="KEEP", sku_id="SKU-KEEP", category="童装春夏", enabled=1),
                source_variant(i_id="OFF", sku_id="SKU-OFF", category="童帽春夏", enabled=0),
                source_variant(i_id="OUT", sku_id="SKU-OUT", category="成人帽", enabled=1),
                source_variant(i_id="BACK", sku_id="SKU-BACK", category="童装秋冬", enabled=0),
                source_variant(i_id="ENTER", sku_id="SKU-ENTER", category="童配春夏", enabled=1),
            ]
        ],
        candidate_cursor="cursor-increment-1",
    )

    result = ProductSyncService(session_factory, source=increment).run_incremental(
        request_id="request-increment-1",
        worker_id="worker-test",
    )

    assert result.success_cursor == "cursor-increment-1"
    assert increment.incremental_start_cursors == ["cursor-initial"]
    with session_factory() as session:
        variants = session.scalars(
            select(ProductVariant).order_by(ProductVariant.source_sku_id)
        ).all()
    assert [(variant.source_sku_id, variant.is_available) for variant in variants] == [
        ("SKU-BACK", False),
        ("SKU-ENTER", True),
        ("SKU-KEEP", True),
        ("SKU-OFF", False),
        ("SKU-OUT", False),
    ]

    reenable = FakeJstProductSource(
        incremental_pages=[
            [source_variant(i_id="BACK", sku_id="SKU-BACK", category="童装秋冬", enabled=1)]
        ],
        candidate_cursor="cursor-increment-2",
    )
    ProductSyncService(session_factory, source=reenable).run_incremental(
        request_id="request-increment-2",
        worker_id="worker-test",
    )
    with session_factory() as session:
        restored = session.scalar(
            select(ProductVariant).where(ProductVariant.source_sku_id == "SKU-BACK")
        )
    assert restored is not None
    assert restored.is_available is True
    assert reenable.incremental_start_cursors == ["cursor-increment-1"]


def test_repeated_pages_and_repeated_initial_window_are_idempotent(
    test_database_engine: Engine,
) -> None:
    session_factory = sessionmaker(test_database_engine, class_=Session, expire_on_commit=False)
    record = source_variant(
        i_id="HAT-IDEMPOTENT",
        sku_id="SKU-IDEMPOTENT",
        category="童帽春夏",
        enabled=1,
    )
    source = FakeJstProductSource(
        initial_pages=[[record], [record]],
        candidate_cursor="cursor-idempotent",
    )

    first = ProductSyncService(session_factory, source=source).run_initial(
        request_id="request-idempotent-1",
        worker_id="worker-test",
    )
    second = ProductSyncService(session_factory, source=source).run_initial(
        request_id="request-idempotent-2",
        worker_id="worker-test",
    )

    assert first.included_records == 1
    assert second.included_records == 1
    with session_factory() as session:
        assert len(session.scalars(select(Product)).all()) == 1
        assert len(session.scalars(select(ProductVariant)).all()) == 1
        runs = session.scalars(select(ProductSyncRun).order_by(ProductSyncRun.started_at)).all()
    assert [(run.created_records, run.updated_records) for run in runs] == [(1, 0), (0, 1)]
