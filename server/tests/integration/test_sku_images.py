import json
from base64 import b64decode
from dataclasses import replace
from datetime import datetime, timedelta

import httpx
import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.adapters.private_files import FakePrivateFileStore, PrivateFileStoreUnavailable
from app.adapters.product import (
    FakeJstProductSource,
    FakeProductImageStore,
    PrivateProductImageStore,
    ProductImageCacheError,
    ProductSourceError,
    SourceProductVariant,
)
from app.db.models import BackgroundJob, Product, ProductVariant
from app.modules.product_sync import ProductCatalogService, ProductImageService, ProductSyncService


def test_each_sku_caches_its_own_color_and_size_image(test_database_engine: Engine) -> None:
    sessions = sessionmaker(test_database_engine, expire_on_commit=False)
    base = SourceProductVariant(
        i_id="STYLE", sku_id="BLUE-S", name="测试帽", properties_value="蓝色,S",
        pic="https://images.example/blue.jpg", category="童帽春夏", enabled=1,
        source_modified_at=datetime(2026, 9, 28),
    )
    records = [
        base, replace(base, sku_id="BLUE-M", properties_value="蓝色,M",
                      pic="https://images.example/blue-m.jpg"),
        replace(base, sku_id="RED-S", properties_value="红色,S",
                pic="https://images.example/red.jpg"),
        replace(base, sku_id="RED-M", properties_value="红色,M",
                pic="https://images.example/red-m.jpg"),
    ]
    ProductSyncService(sessions, source=FakeJstProductSource(
        initial_pages=[records], candidate_cursor="one",
    )).run_initial(request_id="colors", worker_id="test")
    store = FakeProductImageStore()
    images = ProductImageService(sessions, image_store=store)
    with Session(test_database_engine) as session:
        jobs = session.scalars(select(BackgroundJob).where(
            BackgroundJob.job_type == "product-image-cache",
        )).all()
    assert len(jobs) == 4
    for job in reversed(jobs):
        images.process(job.payload)
    catalog = ProductCatalogService(sessions)
    rows = catalog.list_available(keyword="", page=1, page_size=10,
                                  sort_by="skuId", sort_order="asc").items
    versions = {row.sku_id: row.image_version for row in rows}
    keys = {row.sku_id: catalog.get_cached_image_object_key(
        variant_id=row.variant_id, image_version=row.image_version,
    ) for row in rows if row.image_version is not None}
    assert all(row.image_available for row in rows)
    assert len(set(versions.values())) == 4
    assert len(set(keys.values())) == 4
    assert store.cached_refs == [job.payload["source_ref"] for job in reversed(jobs)]


def test_backfill_reuses_only_verified_matching_images_and_is_repeatable(
    test_database_engine: Engine,
) -> None:
    from app.modules.product_sync.backfill import ProductImageBackfill

    sessions = sessionmaker(test_database_engine, expire_on_commit=False)
    base = SourceProductVariant(
        i_id="STYLE", sku_id="BLUE", name="帽子", properties_value="蓝色",
        pic=None, category="童帽春夏", enabled=1, source_modified_at=datetime(2026, 9, 28),
    )
    ProductSyncService(sessions, source=FakeJstProductSource(
        initial_pages=[[base, replace(base, sku_id="BLUE-M", properties_value="蓝色,M")]],
        candidate_cursor="initial",
    )).run_initial(request_id="seed", worker_id="test")
    content = b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
    )
    files = FakePrivateFileStore(bucket="backfill")
    files.put(object_key="products/legacy-blue", content=content, content_type="image/png")
    with sessions() as session, session.begin():
        product = session.scalar(select(Product))
        product.image_source_ref = "https://images.example/blue"
        product.image_object_key = "products/legacy-blue"
        product.image_cache_status = "cached"
    downloads = []

    def respond(request: httpx.Request) -> httpx.Response:
        downloads.append(str(request.url))
        return httpx.Response(200, headers={"content-type": "image/png"}, content=content)

    service = ProductImageBackfill(
        sessions, source=FakeJstProductSource(targeted_pages=[[
            replace(base, pic="https://images.example/blue",
                    source_modified_at=datetime(2026, 9, 30)),
            replace(base, sku_id="BLUE-M", pic="https://images.example/blue-m",
                    properties_value="蓝色,M"),
        ]], candidate_cursor=""), file_store=files,
        image_store=PrivateProductImageStore(files, transport=httpx.MockTransport(respond),
                                             url_validator=lambda _: True),
    )
    preview = service.run(request_id="preview")
    assert preview["matched"] == 2 and preview["reused"] == 1 and preview["download"] == 1
    assert downloads == []
    result = service.run(request_id="apply", expected_digest=preview["digest"])
    assert result["downloaded"] == 1 and result["reused"] == 1 and result["failed"] == 0
    assert downloads == ["https://images.example/blue-m"]
    repeated = service.run(request_id="again")
    assert repeated["reused"] == 2 and repeated["download"] == 0
    service.run(request_id="again-apply", expected_digest=repeated["digest"])
    assert downloads == ["https://images.example/blue-m"]
    assert files.get(object_key="products/legacy-blue") == content
    ProductSyncService(sessions, source=FakeJstProductSource(incremental_pages=[[
        replace(base, pic="https://images.example/stale", source_modified_at=datetime(2026, 9, 29)),
    ]], candidate_cursor="older-staged-page")).run_incremental(
        request_id="older-staged", worker_id="test",
    )
    with sessions() as session:
        blue = session.scalar(select(ProductVariant).where(ProductVariant.source_sku_id == "BLUE"))
        assert blue.cached_image_key == "products/legacy-blue"
        assert blue.image_source_ref == "https://images.example/blue"


@pytest.mark.parametrize("mode", ["initial", "incremental", "targeted"])
def test_image_changes_missing_retry_and_old_jobs_are_sku_scoped(
    test_database_engine: Engine, mode: str,
) -> None:
    sessions = sessionmaker(test_database_engine, expire_on_commit=False)
    base = SourceProductVariant(
        i_id="STYLE", sku_id="BLUE", name="帽子", properties_value="蓝色",
        pic="blue-a", category="童帽春夏", enabled=1, source_modified_at=datetime(2026, 9, 28),
    )
    ProductSyncService(sessions, source=FakeJstProductSource(
        initial_pages=[[base, replace(base, sku_id="RED", pic="red", properties_value="红色")]],
        candidate_cursor="seed",
    )).run_initial(request_id="seed", worker_id="test")
    catalog = ProductCatalogService(sessions)
    store = FakeProductImageStore()
    images = ProductImageService(sessions, image_store=store)

    def jobs() -> list[BackgroundJob]:
        with sessions() as session:
            return list(session.scalars(select(BackgroundJob).where(
                BackgroundJob.job_type == "product-image-cache",
            ).order_by(BackgroundJob.id)))

    def versions() -> dict[str, str | None]:
        return {row.sku_id: row.image_version for row in catalog.list_available(
            keyword="", page=1, page_size=10, sort_by="skuId", sort_order="asc",
        ).items}

    old_jobs = jobs()
    for job in old_jobs:
        images.process(job.payload)
    red_version = versions()["RED"]

    def sync(pic: str | None, step: int) -> None:
        record = replace(base, pic=pic, source_modified_at=base.source_modified_at
                         + timedelta(minutes=step))
        service = ProductSyncService(sessions, source=FakeJstProductSource(
            initial_pages=[[record]], incremental_pages=[[record]], targeted_pages=[[record]],
            candidate_cursor=str(step),
        ))
        if mode == "targeted":
            preview = service.preview_targeted(i_id="STYLE")
            service.run_targeted(i_id="STYLE", expected_digest=preview["digest"],
                                 request_id=f"step-{step}", worker_id="test")
        elif mode == "initial":
            service.run_initial(request_id=f"step-{step}", worker_id="test")
        else:
            service.run_incremental(request_id=f"step-{step}", worker_id="test")

    sync("blue-b", 1)
    second = jobs()[-1]
    assert versions() == {"BLUE": None, "RED": red_version}
    sync("blue-a", 2)
    current = jobs()[-1]
    # A → B → A 后，早期 A 和 B 任务均不得回写。
    before = len(store.cached_refs)
    for job in [*old_jobs, second]:
        images.process(job.payload)
    assert len(store.cached_refs) == before
    assert versions() == {"BLUE": None, "RED": red_version}
    failing = ProductImageService(sessions, image_store=FakeProductImageStore(
        failures_before_success=1,
    ))
    with pytest.raises(ProductImageCacheError):
        failing.process(current.payload)
    assert versions() == {"BLUE": None, "RED": red_version}
    failing.process(current.payload)
    assert versions()["BLUE"] is not None
    sync(None, 3)
    images.process(current.payload)
    images.process({"product_id": "old-product", "source_ref": "legacy", "source_i_id": "STYLE"})
    assert versions() == {"BLUE": None, "RED": red_version}
    with sessions() as session:
        blue = session.scalar(select(ProductVariant).where(ProductVariant.source_sku_id == "BLUE"))
        assert blue.image_cache_status == "missing" and blue.image_object_key is None


@pytest.mark.parametrize("fail", [False, True])
def test_inflight_image_result_cannot_overwrite_a_newer_sku_revision(
    test_database_engine: Engine, fail: bool,
) -> None:
    sessions = sessionmaker(test_database_engine, expire_on_commit=False)
    base = SourceProductVariant(
        i_id="STYLE", sku_id="BLUE", name="帽子", properties_value="蓝色",
        pic="old", category="童帽春夏", enabled=1, source_modified_at=datetime(2026, 9, 28),
    )
    sync = ProductSyncService(sessions, source=FakeJstProductSource(
        initial_pages=[[base]], incremental_pages=[[
            replace(base, pic="new", source_modified_at=datetime(2026, 9, 29)),
        ]], candidate_cursor="next",
    ))
    sync.run_initial(request_id="old", worker_id="test")
    with sessions() as session:
        payload = session.scalar(select(BackgroundJob)).payload

    class UpdatingStore(FakeProductImageStore):
        def cache(self, *, source_ref: str, object_key: str):
            sync.run_incremental(request_id="new", worker_id="test")
            if fail:
                raise ProductImageCacheError("product_image_cache_failed")
            return super().cache(source_ref=source_ref, object_key=object_key)

    service = ProductImageService(sessions, image_store=UpdatingStore())
    if fail:
        with pytest.raises(ProductImageCacheError):
            service.process(payload)
    else:
        service.process(payload)
    with sessions() as session:
        variant = session.scalar(select(ProductVariant))
        assert variant.image_source_ref == "new" and variant.image_cache_status == "pending"
        assert variant.image_object_key is None and variant.image_cache_error is None


@pytest.mark.parametrize(
    "failure", ["missing", "unmatched", "download", "forbidden", "changed", "source"],
)
def test_backfill_reports_incomplete_images_and_rejects_stale_preview(
    test_database_engine: Engine, failure: str,
) -> None:
    from app.modules.product_sync.backfill import ProductImageBackfill

    sessions = sessionmaker(test_database_engine, expire_on_commit=False)
    base = SourceProductVariant(
        i_id="STYLE", sku_id="BLUE", name="帽子", properties_value="蓝色",
        pic="https://images.example/blue", category="童帽春夏", enabled=1,
        source_modified_at=datetime(2026, 9, 28),
    )
    ProductSyncService(sessions, source=FakeJstProductSource(
        initial_pages=[[base]], candidate_cursor="initial",
    )).run_initial(request_id="seed", worker_id="test")
    if failure == "missing":
        record = replace(base, pic=None)
    elif failure == "unmatched":
        record = replace(base, sku_id="OTHER")
    else:
        record = base

    class ForbiddenStore(FakePrivateFileStore):
        def get(self, *, object_key: str) -> bytes:
            raise PrivateFileStoreUnavailable("access denied")

    files = ForbiddenStore(bucket="test") if failure == "forbidden" else FakePrivateFileStore(
        bucket="test",
    )
    if failure == "forbidden":
        with sessions() as session, session.begin():
            product = session.scalar(select(Product))
            product.image_source_ref = base.pic
            product.image_object_key = "products/legacy"
    service = ProductImageBackfill(
        sessions, source=FakeJstProductSource(
            targeted_pages=[] if failure == "source" else [[record]], candidate_cursor="",
        ),
        file_store=files, image_store=FakeProductImageStore(failures_before_success=1),
    )
    preview = service.run(request_id="preview")
    if failure == "changed":
        with sessions() as session, session.begin():
            session.scalar(select(ProductVariant)).image_revision = "newer"
        with pytest.raises(ProductSourceError, match="product_preview_changed"):
            service.run(request_id="commit", expected_digest=preview["digest"])
        return
    result = service.run(request_id="commit", expected_digest=preview["digest"])
    count = "failed" if failure in {"download", "forbidden", "source"} else failure
    assert result[count] == 1
    assert result["downloaded"] == 0 and result["reused"] == 0
    if failure == "download":
        with sessions() as session:
            variant = session.scalar(select(ProductVariant))
            assert variant.image_cache_status == "failed"
            assert variant.image_cache_error == "product_image_cache_failed"


def test_images_cli_previews_then_applies_only_to_the_isolated_database(
    test_database_engine: Engine, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture,
) -> None:
    from app.settings.config import Settings
    from scripts import enqueue_product_sync as cli

    sessions = sessionmaker(test_database_engine, expire_on_commit=False)
    record = SourceProductVariant(
        i_id="CLI", sku_id="CLI-SKU", name="测试帽", properties_value="蓝色",
        pic=None, category="童帽春夏", enabled=1, source_modified_at=datetime(2026, 9, 28),
    )
    source = FakeJstProductSource(
        initial_pages=[[record]], targeted_pages=[[record]], candidate_cursor="cli",
    )
    ProductSyncService(sessions, source=source).run_initial(request_id="seed", worker_id="test")
    settings = Settings(
        jst_product_app_key="test", jst_product_app_secret="test",
        oss_endpoint="https://oss.example.test", oss_region="test",
        oss_access_key_id="test", oss_access_key_secret="test", oss_bucket="isolated-test",
    )
    monkeypatch.setattr(cli, "Settings", lambda: settings)
    monkeypatch.setattr(cli, "AppCredentialJstProductSource", lambda *_: source)
    monkeypatch.setattr(cli, "AliyunOssPrivateFileStore", lambda **_: FakePrivateFileStore(
        bucket="isolated-test",
    ))
    monkeypatch.setattr("sys.argv", ["enqueue_product_sync", "images"])
    assert cli.main() == 0
    preview = json.loads(capsys.readouterr().out)
    assert preview["applied"] is False and preview["missing"] == 1
    assert preview["environment"]["database"] == test_database_engine.url.database
    monkeypatch.setattr("sys.argv", [
        "enqueue_product_sync", "images", "--commit", preview["digest"],
    ])
    assert cli.main() == 0
    assert json.loads(capsys.readouterr().out)["applied"] is True
