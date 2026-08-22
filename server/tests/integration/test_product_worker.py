from datetime import datetime

from sqlalchemy import Engine, delete, select
from sqlalchemy.orm import Session, sessionmaker

from app.adapters.product import (
    FakeJstProductSource,
    FakeProductImageStore,
    SourceProductVariant,
)
from app.db.models import BackgroundJob, Product, ProductSyncRun, ProductVariant
from app.modules.infrastructure import InfrastructureStore
from app.modules.product_sync import ProductImageService, ProductSyncService, ProductWorkerHandlers
from app.worker.runtime import Worker


def test_image_job_failure_retries_and_successfully_replaces_the_private_cache(
    test_database_engine: Engine,
) -> None:
    session_factory = sessionmaker(test_database_engine, class_=Session, expire_on_commit=False)
    with session_factory() as session, session.begin():
        session.execute(delete(ProductVariant))
        session.execute(delete(ProductSyncRun))
        session.execute(delete(Product))
        session.execute(delete(BackgroundJob))
    source = FakeJstProductSource(
        initial_pages=[
            [
                SourceProductVariant(
                    i_id="HAT-IMAGE",
                    sku_id="SKU-IMAGE",
                    name="图片测试帽",
                    properties_value="蓝色,52",
                    pic="fake-image-ref",
                    category="童帽春夏",
                    enabled=1,
                    source_modified_at=datetime(2026, 8, 21, 9, 0),
                )
            ]
        ],
        candidate_cursor="cursor-image",
    )
    ProductSyncService(session_factory, source=source).run_initial(
        request_id="request-image",
        worker_id="sync-worker",
    )
    image_store = FakeProductImageStore(failures_before_success=1)
    image_service = ProductImageService(session_factory, image_store=image_store)
    worker = Worker(
        store=InfrastructureStore(session_factory),
        worker_id="image-worker",
        handlers={"product-image-cache": image_service.process},
        retry_limits={"product-image-cache": 3},
        retry_delay_seconds=0,
    )
    with session_factory() as session:
        now = session.scalar(
            select(BackgroundJob.available_at).where(
                BackgroundJob.job_type == "product-image-cache",
                BackgroundJob.status == "pending",
            )
        )
    assert now is not None

    assert worker.run_once(now=now) is True
    with session_factory() as session:
        product = session.scalar(select(Product).where(Product.source_i_id == "HAT-IMAGE"))
        job = session.scalar(
            select(BackgroundJob).where(BackgroundJob.job_type == "product-image-cache")
        )
    assert product is not None and product.image_cache_status == "failed"
    assert job is not None and job.status == "pending" and job.attempts == 1

    assert worker.run_once(now=now) is True
    with session_factory() as session:
        product = session.scalar(select(Product).where(Product.source_i_id == "HAT-IMAGE"))
        job = session.scalar(
            select(BackgroundJob).where(BackgroundJob.job_type == "product-image-cache")
        )
    assert product is not None
    assert product.image_cache_status == "cached"
    assert product.image_object_key == "products/HAT-IMAGE/fake-image-ref"
    assert job is not None and job.status == "completed" and job.attempts == 2

    changed_source = FakeJstProductSource(
        incremental_pages=[
            [
                SourceProductVariant(
                    i_id="HAT-IMAGE",
                    sku_id="SKU-IMAGE",
                    name="图片测试帽",
                    properties_value="蓝色,52",
                    pic="fake-image-ref-v2",
                    category="童帽春夏",
                    enabled=1,
                    source_modified_at=datetime(2026, 8, 21, 11, 0),
                )
            ]
        ],
        candidate_cursor="cursor-image-v2",
    )
    ProductSyncService(session_factory, source=changed_source).run_incremental(
        request_id="request-image-v2",
        worker_id="sync-worker",
    )
    with session_factory() as session:
        incremental_now = session.scalar(
            select(BackgroundJob.available_at).where(
                BackgroundJob.job_type == "product-image-cache",
                BackgroundJob.status == "pending",
            )
        )
    assert incremental_now is not None
    assert worker.run_once(now=incremental_now) is True
    with session_factory() as session:
        product = session.scalar(select(Product).where(Product.source_i_id == "HAT-IMAGE"))
    assert product is not None
    assert product.image_object_key == "products/HAT-IMAGE/fake-image-ref-v2"


def test_worker_claims_and_completes_an_initial_product_sync_job(
    test_database_engine: Engine,
) -> None:
    session_factory = sessionmaker(test_database_engine, class_=Session, expire_on_commit=False)
    with session_factory() as session, session.begin():
        session.execute(delete(ProductVariant))
        session.execute(delete(ProductSyncRun))
        session.execute(delete(Product))
        session.execute(delete(BackgroundJob))
    source = FakeJstProductSource(
        initial_pages=[
            [
                SourceProductVariant(
                    i_id="HAT-WORKER",
                    sku_id="SKU-WORKER",
                    name="worker 童帽",
                    properties_value="粉色,50",
                    pic=None,
                    category="童帽秋冬",
                    enabled=1,
                    source_modified_at=datetime(2026, 8, 21, 10, 0),
                )
            ]
        ],
        candidate_cursor="cursor-worker",
    )
    store = InfrastructureStore(session_factory)
    job_id = store.enqueue_job(
        job_type="product-sync-initial",
        dedupe_key="product-sync-initial:test",
        payload={"request_id": "request-worker", "actor_id": "operator-test"},
        available_at=datetime(2026, 8, 21, 10, 0),
    )
    handlers = ProductWorkerHandlers(
        sync_service=ProductSyncService(session_factory, source=source)
    )
    worker = Worker(
        store=store,
        worker_id="sync-worker",
        handlers=handlers.handlers(),
    )

    assert worker.run_once(now=datetime(2026, 8, 21, 10, 0)) is True
    assert store.get_job(job_id=job_id).status == "completed"
    with session_factory() as session:
        product = session.scalar(select(Product).where(Product.source_i_id == "HAT-WORKER"))
    assert product is not None and product.is_available is True
