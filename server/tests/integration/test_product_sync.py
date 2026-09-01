from datetime import datetime

import pytest
from sqlalchemy import Engine, delete, select
from sqlalchemy.orm import Session, sessionmaker

from app.adapters.product import FakeJstProductSource, ProductSourceError, SourceProductVariant
from app.db.models import (
    Product,
    ProductSyncRun,
    ProductSyncStagedVariant,
    ProductVariant,
)
from app.modules.product_sync import ProductSyncService


def source_variant(
    *,
    i_id: str,
    sku_id: str,
    category: str | None,
    enabled: int | None,
    name: str | None = None,
    properties_value: str | None = "藏青,54",
) -> SourceProductVariant:
    return SourceProductVariant(
        i_id=i_id,
        sku_id=sku_id,
        name=name or f"产品 {i_id}",
        properties_value=properties_value,
        pic=None,
        category=category,
        enabled=enabled,
        source_modified_at=datetime(2026, 8, 21, 8, 0),
    )


@pytest.fixture(autouse=True)
def clean_product_tables(test_database_engine: Engine) -> None:
    with Session(test_database_engine) as session, session.begin():
        session.execute(delete(ProductVariant))
        session.execute(delete(ProductSyncStagedVariant))
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


def test_initial_sync_preserves_unique_source_ids_when_display_fields_repeat(
    test_database_engine: Engine,
) -> None:
    session_factory = sessionmaker(test_database_engine, class_=Session, expire_on_commit=False)
    source = FakeJstProductSource(
        initial_pages=[
            [
                source_variant(
                    i_id="STYLE-DRAWING-1",
                    sku_id="SKU-DRAWING-BLUE",
                    name="儿童便携绘画本升级版",
                    category="童配春夏",
                    enabled=1,
                    properties_value="蓝色",
                ),
                source_variant(
                    i_id="STYLE-DRAWING-2",
                    sku_id="SKU-DRAWING-PINK",
                    name="儿童便携绘画本升级版",
                    category="童配春夏",
                    enabled=1,
                    properties_value="粉色",
                ),
                source_variant(
                    i_id="STYLE-SUIT",
                    sku_id="SKU-SUIT-OLD",
                    name="小风孔冰奶皮速干背心套装",
                    category="童装春夏",
                    enabled=1,
                    properties_value="星夜蓝100",
                ),
                source_variant(
                    i_id="STYLE-SUIT",
                    sku_id="SKU-SUIT-NEW",
                    name="小风孔冰奶皮速干背心套装",
                    category="童装春夏",
                    enabled=1,
                    properties_value="星夜蓝100",
                ),
            ]
        ],
        candidate_cursor="cursor-repeated-display-fields",
    )

    result = ProductSyncService(session_factory, source=source).run_initial(
        request_id="request-repeated-display-fields",
        worker_id="worker-test",
    )

    assert result.status == "succeeded"
    assert result.included_records == 4
    with session_factory() as session:
        products = session.scalars(select(Product).order_by(Product.source_i_id)).all()
        variants = session.scalars(
            select(ProductVariant).order_by(ProductVariant.source_sku_id)
        ).all()
    assert [(product.source_i_id, product.name) for product in products] == [
        ("STYLE-DRAWING-1", "儿童便携绘画本升级版"),
        ("STYLE-DRAWING-2", "儿童便携绘画本升级版"),
        ("STYLE-SUIT", "小风孔冰奶皮速干背心套装"),
    ]
    assert [(variant.source_sku_id, variant.properties_value) for variant in variants] == [
        ("SKU-DRAWING-BLUE", "蓝色"),
        ("SKU-DRAWING-PINK", "粉色"),
        ("SKU-SUIT-NEW", "星夜蓝100"),
        ("SKU-SUIT-OLD", "星夜蓝100"),
    ]


def test_initial_sync_ignores_out_of_scope_variant_missing_properties(
    test_database_engine: Engine,
) -> None:
    session_factory = sessionmaker(test_database_engine, class_=Session, expire_on_commit=False)
    source = FakeJstProductSource(
        initial_pages=[
            [
                source_variant(
                    i_id="SHOE-OUT",
                    sku_id="SKU-SHOE-OUT",
                    category="KQ童鞋（福建）",
                    enabled=1,
                    properties_value=None,
                ),
                source_variant(
                    i_id="HAT-IN",
                    sku_id="SKU-HAT-IN",
                    category="童帽春夏",
                    enabled=1,
                ),
            ]
        ],
        candidate_cursor="cursor-out-of-scope-missing-properties",
    )

    result = ProductSyncService(session_factory, source=source).run_initial(
        request_id="request-out-of-scope-missing-properties",
        worker_id="worker-test",
    )

    assert result.included_records == 1
    assert result.ignored_records == 1
    with session_factory() as session:
        variants = session.scalars(select(ProductVariant)).all()
    assert [variant.source_sku_id for variant in variants] == ["SKU-HAT-IN"]


def test_initial_sync_rejects_allowlisted_variant_missing_properties(
    test_database_engine: Engine,
) -> None:
    session_factory = sessionmaker(test_database_engine, class_=Session, expire_on_commit=False)
    source = FakeJstProductSource(
        initial_pages=[
            [
                source_variant(
                    i_id="HAT-MISSING",
                    sku_id="SKU-HAT-MISSING",
                    category="童帽春夏",
                    enabled=1,
                    properties_value=None,
                )
            ]
        ],
        candidate_cursor="cursor-missing-properties",
    )

    with pytest.raises(ProductSourceError, match="product_source_contract_invalid"):
        ProductSyncService(session_factory, source=source).run_initial(
            request_id="request-missing-properties",
            worker_id="worker-test",
        )

    with session_factory() as session:
        run = session.scalar(select(ProductSyncRun))
        variants = session.scalars(select(ProductVariant)).all()
    assert run is not None
    assert (run.status, run.success_cursor, run.error_code) == (
        "failed",
        None,
        "product_source_contract_invalid",
    )
    assert variants == []


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


def test_initial_sync_stages_each_page_and_resumes_the_same_run_after_failure(
    test_database_engine: Engine,
) -> None:
    session_factory = sessionmaker(test_database_engine, class_=Session, expire_on_commit=False)
    first_record = source_variant(
        i_id="HAT-RESUME-1",
        sku_id="SKU-RESUME-1",
        category="童帽春夏",
        enabled=1,
    )
    second_record = source_variant(
        i_id="HAT-RESUME-2",
        sku_id="SKU-RESUME-2",
        category="童配秋冬",
        enabled=1,
    )
    failing_source = FakeJstProductSource(
        initial_pages=[[first_record], [second_record]],
        candidate_cursor="cursor-resume",
        fail_initial_page=2,
    )
    service = ProductSyncService(session_factory, source=failing_source)

    with pytest.raises(ProductSourceError, match="product_source_page_failed"):
        service.run_initial(request_id="request-resume", worker_id="worker-first")

    with session_factory() as session:
        failed_run = session.scalar(
            select(ProductSyncRun).where(ProductSyncRun.request_id == "request-resume")
        )
        staged = session.scalars(select(ProductSyncStagedVariant)).all()
        published = session.scalars(select(ProductVariant)).all()
    assert failed_run is not None
    assert (
        failed_run.status,
        failed_run.pages_read,
        failed_run.records_read,
        failed_run.next_page,
    ) == ("failed", 1, 1, 2)
    assert failed_run.source_checkpoint is not None
    assert [record.source_sku_id for record in staged] == ["SKU-RESUME-1"]
    assert published == []

    resumed_source = FakeJstProductSource(
        initial_pages=[[first_record], [second_record]],
        candidate_cursor="cursor-resume",
    )
    result = ProductSyncService(session_factory, source=resumed_source).run_initial(
        request_id="request-resume",
        worker_id="worker-second",
    )

    assert result.run_id == failed_run.run_id
    assert resumed_source.initial_page_numbers == [2]
    with session_factory() as session:
        run = session.get(ProductSyncRun, result.run_id)
        variants = session.scalars(
            select(ProductVariant).order_by(ProductVariant.source_sku_id)
        ).all()
        remaining_staged = session.scalars(select(ProductSyncStagedVariant)).all()
    assert run is not None
    assert (run.status, run.pages_read, run.records_read) == ("succeeded", 2, 2)
    assert [variant.source_sku_id for variant in variants] == [
        "SKU-RESUME-1",
        "SKU-RESUME-2",
    ]
    assert remaining_staged == []


def test_initial_sync_retries_publication_without_refetching_completed_source(
    test_database_engine: Engine,
) -> None:
    session_factory = sessionmaker(test_database_engine, class_=Session, expire_on_commit=False)
    ProductSyncService(
        session_factory,
        source=FakeJstProductSource(
            initial_pages=[
                [
                    SourceProductVariant(
                        i_id="EXISTING",
                        sku_id="SKU-EXISTING",
                        name="现有产品",
                        properties_value="蓝色,52",
                        pic=None,
                        category="童帽春夏",
                        enabled=1,
                        source_modified_at=datetime(2026, 8, 21, 8, 0),
                    )
                ]
            ],
            candidate_cursor="cursor-existing",
        ),
    ).run_initial(request_id="request-existing", worker_id="worker-test")
    pending = SourceProductVariant(
        i_id="PENDING",
        sku_id="SKU-EXISTING",
        name="待发布产品",
        properties_value="红色,54",
        pic=None,
        category="童配秋冬",
        enabled=1,
        source_modified_at=datetime(2026, 8, 21, 9, 0),
    )

    with pytest.raises(ValueError, match="product_source_identity_conflict"):
        ProductSyncService(
            session_factory,
            source=FakeJstProductSource(
                initial_pages=[[pending]],
                candidate_cursor="cursor-pending",
            ),
        ).run_initial(request_id="request-publish-retry", worker_id="worker-first")

    with session_factory() as session:
        failed_run = session.scalar(
            select(ProductSyncRun).where(
                ProductSyncRun.request_id == "request-publish-retry"
            )
        )
    assert failed_run is not None
    assert failed_run.source_completed is True
    with session_factory() as session, session.begin():
        existing_variant = session.scalar(
            select(ProductVariant).where(
                ProductVariant.source_sku_id == "SKU-EXISTING"
            )
        )
        assert existing_variant is not None
        session.delete(existing_variant)
        existing_product = session.scalar(
            select(Product).where(Product.source_i_id == "EXISTING")
        )
        assert existing_product is not None
        session.delete(existing_product)

    retry_source = FakeJstProductSource(
        initial_pages=[[pending]],
        candidate_cursor="cursor-pending",
    )
    result = ProductSyncService(session_factory, source=retry_source).run_initial(
        request_id="request-publish-retry",
        worker_id="worker-second",
    )

    assert result.run_id == failed_run.run_id
    assert retry_source.initial_page_numbers == []
    with session_factory() as session:
        published = session.scalar(
            select(ProductVariant).where(ProductVariant.source_sku_id == "SKU-EXISTING")
        )
    assert published is not None and published.is_available is True


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
                source_variant(
                    i_id="OUT",
                    sku_id="SKU-OUT",
                    category="成人帽",
                    enabled=1,
                    properties_value=None,
                ),
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
    moved_out = next(
        variant for variant in variants if variant.source_sku_id == "SKU-OUT"
    )
    assert moved_out.properties_value == "藏青,54"

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


def test_incremental_sync_stages_pages_and_resumes_without_partial_publication(
    test_database_engine: Engine,
) -> None:
    session_factory = sessionmaker(test_database_engine, class_=Session, expire_on_commit=False)
    ProductSyncService(
        session_factory,
        source=FakeJstProductSource(
            initial_pages=[
                [source_variant(i_id="KEEP", sku_id="SKU-KEEP", category="童装春夏", enabled=1)]
            ],
            candidate_cursor="cursor-initial",
        ),
    ).run_initial(request_id="request-initial", worker_id="worker-test")
    disabled = source_variant(
        i_id="KEEP",
        sku_id="SKU-KEEP",
        category="童装春夏",
        enabled=0,
    )
    added = source_variant(
        i_id="ADD",
        sku_id="SKU-ADD",
        category="童配秋冬",
        enabled=1,
    )
    failing_source = FakeJstProductSource(
        incremental_pages=[[disabled], [added]],
        candidate_cursor="cursor-increment",
        fail_incremental_page=2,
    )

    with pytest.raises(ProductSourceError, match="product_source_page_failed"):
        ProductSyncService(session_factory, source=failing_source).run_incremental(
            request_id="request-increment-resume",
            worker_id="worker-first",
        )

    with session_factory() as session:
        still_available = session.scalar(
            select(ProductVariant).where(ProductVariant.source_sku_id == "SKU-KEEP")
        )
        failed_run = session.scalar(
            select(ProductSyncRun).where(
                ProductSyncRun.request_id == "request-increment-resume"
            )
        )
    assert still_available is not None and still_available.is_available is True
    assert failed_run is not None
    assert (failed_run.status, failed_run.pages_read, failed_run.next_page) == (
        "failed",
        1,
        2,
    )

    resumed_source = FakeJstProductSource(
        incremental_pages=[[disabled], [added]],
        candidate_cursor="cursor-increment",
    )
    result = ProductSyncService(session_factory, source=resumed_source).run_incremental(
        request_id="request-increment-resume",
        worker_id="worker-second",
    )

    assert result.run_id == failed_run.run_id
    assert resumed_source.incremental_page_numbers == [2]
    with session_factory() as session:
        variants = session.scalars(
            select(ProductVariant).order_by(ProductVariant.source_sku_id)
        ).all()
        staged = session.scalars(select(ProductSyncStagedVariant)).all()
    assert [(variant.source_sku_id, variant.is_available) for variant in variants] == [
        ("SKU-ADD", True),
        ("SKU-KEEP", False),
    ]
    assert staged == []


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
