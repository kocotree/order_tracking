import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import uuid4

from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.sql.elements import ColumnElement

from app.adapters.product import (
    JstProductSource,
    ProductImageStore,
    ProductSourceError,
    SourceProductVariant,
)
from app.db.models import (
    AuditLog,
    BackgroundJob,
    Product,
    ProductSyncRun,
    ProductSyncStagedVariant,
    ProductVariant,
)
from app.modules.infrastructure import utc_now

PRODUCT_CATEGORY_ALLOWLIST = frozenset(
    {
        "童帽春夏",
        "童配春夏",
        "童装春夏",
        "童帽秋冬",
        "童配秋冬",
        "童装秋冬",
    }
)


@dataclass(frozen=True)
class ProductSyncResult:
    run_id: str
    status: str
    included_records: int
    ignored_records: int
    success_cursor: str | None


@dataclass(frozen=True)
class ProductListItem:
    product_id: str
    variant_id: str
    i_id: str
    sku_id: str
    name: str
    properties_value: str
    image_available: bool
    image_version: str | None


@dataclass(frozen=True)
class ProductListPage:
    items: list[ProductListItem]
    total: int
    page: int
    page_size: int


class ProductCatalogService:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def list_available(
        self,
        *,
        keyword: str,
        page: int,
        page_size: int,
        sort_by: Literal["iId", "skuId", "name", "propertiesValue"],
        sort_order: Literal["asc", "desc"],
    ) -> ProductListPage:
        filters: list[ColumnElement[bool]] = [
            ProductVariant.is_available.is_(True),
            Product.is_available.is_(True),
        ]
        normalized_keyword = keyword.strip()
        if normalized_keyword:
            filters.append(
                or_(
                    Product.source_i_id.contains(normalized_keyword, autoescape=True),
                    ProductVariant.source_sku_id.contains(normalized_keyword, autoescape=True),
                    Product.name.contains(normalized_keyword, autoescape=True),
                    ProductVariant.properties_value.contains(normalized_keyword, autoescape=True),
                )
            )
        sort_columns = {
            "iId": Product.source_i_id,
            "skuId": ProductVariant.source_sku_id,
            "name": Product.name,
            "propertiesValue": ProductVariant.properties_value,
        }
        order_column = sort_columns[sort_by]
        order = order_column.desc() if sort_order == "desc" else order_column.asc()
        with self._session_factory() as session:
            total = session.scalar(
                select(func.count(ProductVariant.variant_id))
                .join(Product, Product.product_id == ProductVariant.product_id)
                .where(*filters)
            )
            rows = session.execute(
                select(ProductVariant, Product)
                .join(Product, Product.product_id == ProductVariant.product_id)
                .where(*filters)
                .order_by(order, ProductVariant.variant_id.asc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            ).all()
        return ProductListPage(
            items=[
                ProductListItem(
                    product_id=product.product_id,
                    variant_id=variant.variant_id,
                    i_id=product.source_i_id,
                    sku_id=variant.source_sku_id,
                    name=product.name,
                    properties_value=variant.properties_value,
                    image_available=(
                        product.image_cache_status == "cached"
                        and product.image_object_key is not None
                    ),
                    image_version=(
                        hashlib.sha256(product.image_object_key.encode()).hexdigest()[:16]
                        if product.image_cache_status == "cached"
                        and product.image_object_key is not None
                        else None
                    ),
                )
                for variant, product in rows
            ],
            total=int(total or 0),
            page=page,
            page_size=page_size,
        )

    def get_cached_image_object_key(
        self,
        *,
        product_id: str,
        image_version: str,
    ) -> str | None:
        with self._session_factory() as session:
            product = session.get(Product, product_id)
            if (
                product is None
                or not product.is_available
                or product.image_cache_status != "cached"
                or product.image_object_key is None
            ):
                return None
            current_version = hashlib.sha256(product.image_object_key.encode()).hexdigest()[:16]
            if image_version != current_version:
                return None
            return product.image_object_key


class ProductSyncService:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        source: JstProductSource,
    ) -> None:
        self._session_factory = session_factory
        self._source = source

    def run_initial(
        self,
        *,
        request_id: str,
        worker_id: str,
        actor_id: str | None = None,
    ) -> ProductSyncResult:
        run_id = self._start_or_resume_run(
            run_type="initial",
            start_cursor=None,
            request_id=request_id,
            worker_id=worker_id,
        )
        try:
            if not self._source_completed(run_id=run_id):
                self._stage_initial_pages(run_id=run_id)
            with self._session_factory() as session, session.begin():
                now = utc_now()
                created = 0
                updated = 0
                included = 0
                staged_records = session.scalars(
                    select(ProductSyncStagedVariant)
                    .where(
                        ProductSyncStagedVariant.run_id == run_id,
                        ProductSyncStagedVariant.category.in_(PRODUCT_CATEGORY_ALLOWLIST),
                        ProductSyncStagedVariant.enabled == 1,
                    )
                    .order_by(ProductSyncStagedVariant.staged_id)
                )
                for staged in staged_records:
                    record = self._staged_record(staged)
                    self._required_properties_value(record)
                    existing_variant = session.scalar(
                        select(ProductVariant.variant_id).where(
                            ProductVariant.source_sku_id == record.sku_id
                        )
                    )
                    self._upsert_available(session, record=record, now=now)
                    if existing_variant is None:
                        created += 1
                    else:
                        updated += 1
                    included += 1
                run = session.get(ProductSyncRun, run_id)
                if run is None:
                    raise RuntimeError("product_sync_run_missing")
                staged_total = int(
                    session.scalar(
                        select(func.count(ProductSyncStagedVariant.staged_id)).where(
                            ProductSyncStagedVariant.run_id == run_id
                        )
                    )
                    or 0
                )
                ignored = staged_total - included
                run.status = "succeeded"
                run.active_key = None
                run.success_cursor = run.candidate_cursor
                run.finished_at = now
                run.included_records = included
                run.created_records = created
                run.updated_records = updated
                run.ignored_records = ignored
                run.source_checkpoint = None
                success_cursor = run.success_cursor
                session.execute(
                    delete(ProductSyncStagedVariant).where(
                        ProductSyncStagedVariant.run_id == run_id
                    )
                )
                session.add(
                    AuditLog(
                        request_id=request_id,
                        action="product_sync.succeeded",
                        target_type="product_sync_run",
                        target_id=run_id,
                        changes={"runType": "initial", "recordsRead": run.records_read},
                        actor_id=actor_id,
                        source_terminal="worker",
                    )
                )
        except Exception as error:
            self._record_failure(run_id=run_id, error=error, actor_id=actor_id)
            raise
        return ProductSyncResult(
            run_id=run_id,
            status="succeeded",
            included_records=included,
            ignored_records=ignored,
            success_cursor=success_cursor,
        )

    def _start_or_resume_run(
        self,
        *,
        run_type: str,
        start_cursor: str | None,
        request_id: str,
        worker_id: str,
    ) -> str:
        with self._session_factory() as session, session.begin():
            run = session.scalar(
                select(ProductSyncRun)
                .where(
                    ProductSyncRun.run_type == run_type,
                    ProductSyncRun.request_id == request_id,
                    ProductSyncRun.status == "failed",
                )
                .order_by(ProductSyncRun.started_at.desc(), ProductSyncRun.run_id.desc())
                .limit(1)
            )
            if run is None:
                run = ProductSyncRun(
                    run_id=str(uuid4()),
                    run_type=run_type,
                    status="running",
                    active_key="product-sync",
                    start_cursor=start_cursor,
                    candidate_cursor=None,
                    success_cursor=None,
                    started_at=utc_now(),
                    worker_id=worker_id,
                    request_id=request_id,
                )
                session.add(run)
            else:
                run.status = "running"
                run.active_key = "product-sync"
                run.finished_at = None
                run.worker_id = worker_id
                run.error_code = None
            return run.run_id

    def _stage_initial_pages(self, *, run_id: str) -> None:
        with self._session_factory() as session:
            run = session.get(ProductSyncRun, run_id)
            if run is None:
                raise RuntimeError("product_sync_run_missing")
            page_number = run.next_page
            checkpoint = run.source_checkpoint
            candidate_cursor = run.candidate_cursor
        while True:
            page = self._source.fetch_initial_page(
                page_number=page_number,
                checkpoint=checkpoint,
            )
            if page.page_number != page_number:
                raise ValueError("product_source_pagination_invalid")
            if candidate_cursor is not None and page.candidate_cursor != candidate_cursor:
                raise ValueError("product_source_cursor_changed")
            if page.has_next and page.next_checkpoint is None:
                raise ValueError("product_source_checkpoint_missing")
            candidate_cursor = page.candidate_cursor
            with self._session_factory() as session, session.begin():
                run = session.get(ProductSyncRun, run_id)
                if run is None:
                    raise RuntimeError("product_sync_run_missing")
                for record in page.items:
                    if self._is_available(record):
                        self._required_properties_value(record)
                    self._stage_record(session, run_id=run_id, record=record)
                run.candidate_cursor = candidate_cursor
                run.pages_read += 1
                run.records_read += len(page.items)
                run.next_page = page_number + 1
                run.source_checkpoint = page.next_checkpoint
                run.source_completed = not page.has_next
            if not page.has_next:
                return
            assert page.next_checkpoint is not None
            checkpoint = page.next_checkpoint
            page_number += 1

    @staticmethod
    def _stage_record(
        session: Session,
        *,
        run_id: str,
        record: SourceProductVariant,
    ) -> None:
        staged = session.scalar(
            select(ProductSyncStagedVariant).where(
                ProductSyncStagedVariant.run_id == run_id,
                ProductSyncStagedVariant.source_sku_id == record.sku_id,
            )
        )
        if staged is None:
            session.add(
                ProductSyncStagedVariant(
                    run_id=run_id,
                    source_i_id=record.i_id,
                    source_sku_id=record.sku_id,
                    name=record.name,
                    properties_value=record.properties_value,
                    pic=record.pic,
                    category=record.category,
                    enabled=record.enabled,
                    source_modified_at=record.source_modified_at,
                )
            )
            return
        if staged.source_i_id != record.i_id:
            raise ValueError("product_source_identity_conflict")
        staged_record = ProductSyncService._staged_record(staged)
        if record.source_modified_at < staged.source_modified_at:
            return
        if record.source_modified_at == staged.source_modified_at and record != staged_record:
            raise ValueError("product_source_duplicate_conflict")
        staged.name = record.name
        staged.properties_value = record.properties_value
        staged.pic = record.pic
        staged.category = record.category
        staged.enabled = record.enabled
        staged.source_modified_at = record.source_modified_at

    @staticmethod
    def _staged_record(staged: ProductSyncStagedVariant) -> SourceProductVariant:
        return SourceProductVariant(
            i_id=staged.source_i_id,
            sku_id=staged.source_sku_id,
            name=staged.name,
            properties_value=staged.properties_value,
            pic=staged.pic,
            category=staged.category,
            enabled=staged.enabled,
            source_modified_at=staged.source_modified_at,
        )

    def _source_completed(self, *, run_id: str) -> bool:
        with self._session_factory() as session:
            completed = session.scalar(
                select(ProductSyncRun.source_completed).where(
                    ProductSyncRun.run_id == run_id
                )
            )
        if completed is None:
            raise RuntimeError("product_sync_run_missing")
        return bool(completed)

    def run_incremental(
        self,
        *,
        request_id: str,
        worker_id: str,
        actor_id: str | None = None,
    ) -> ProductSyncResult:
        start_cursor = self._last_success_cursor()
        run_id = self._start_or_resume_run(
            run_type="incremental",
            start_cursor=start_cursor,
            request_id=request_id,
            worker_id=worker_id,
        )
        try:
            with self._session_factory() as session:
                run = session.get(ProductSyncRun, run_id)
                if run is None:
                    raise RuntimeError("product_sync_run_missing")
                persisted_start_cursor = run.start_cursor
            if not self._source_completed(run_id=run_id):
                self._stage_incremental_pages(
                    run_id=run_id,
                    start_cursor=persisted_start_cursor,
                )
            with self._session_factory() as session, session.begin():
                now = utc_now()
                included = 0
                ignored = 0
                created = 0
                updated = 0
                disabled = 0
                moved_out = 0
                touched_products: set[str] = set()
                staged_records = session.scalars(
                    select(ProductSyncStagedVariant)
                    .where(ProductSyncStagedVariant.run_id == run_id)
                    .order_by(ProductSyncStagedVariant.staged_id)
                )
                for staged in staged_records:
                    record = self._staged_record(staged)
                    available = self._is_available(record)
                    properties_value = (
                        self._required_properties_value(record) if available else None
                    )
                    variant = session.scalar(
                        select(ProductVariant).where(ProductVariant.source_sku_id == record.sku_id)
                    )
                    if variant is None and not available:
                        ignored += 1
                        continue
                    if variant is None:
                        created_product = self._upsert_available(session, record=record, now=now)
                        touched_products.add(created_product.product_id)
                        included += 1
                        created += 1
                        continue
                    existing_product = session.get(Product, variant.product_id)
                    if existing_product is None or existing_product.source_i_id != record.i_id:
                        raise ValueError("product_source_identity_conflict")
                    if record.source_modified_at < variant.source_modified_at:
                        ignored += 1
                        continue
                    was_available = variant.is_available
                    image_changed = existing_product.image_source_ref != record.pic
                    existing_product.name = record.name
                    existing_product.image_source_ref = record.pic
                    if record.pic is None:
                        existing_product.image_cache_status = "missing"
                        existing_product.image_object_key = None
                        existing_product.image_cache_error = None
                    elif image_changed:
                        existing_product.image_cache_status = "pending"
                        existing_product.image_cache_error = None
                        self._enqueue_image_job(
                            session,
                            product=existing_product,
                            record=record,
                            now=now,
                        )
                    existing_product.source_modified_at = max(
                        existing_product.source_modified_at, record.source_modified_at
                    )
                    existing_product.last_synced_at = now
                    if properties_value is not None:
                        variant.properties_value = properties_value
                    variant.source_category = record.category
                    variant.source_enabled = record.enabled
                    variant.is_available = available
                    variant.source_modified_at = record.source_modified_at
                    variant.last_synced_at = now
                    touched_products.add(existing_product.product_id)
                    updated += 1
                    if available:
                        included += 1
                    elif was_available and record.enabled != 1:
                        disabled += 1
                    elif was_available:
                        moved_out += 1
                session.flush()
                for product_id in touched_products:
                    touched_product = session.get(Product, product_id)
                    if touched_product is not None:
                        touched_product.is_available = bool(
                            session.scalar(
                                select(ProductVariant.variant_id)
                                .where(
                                    ProductVariant.product_id == product_id,
                                    ProductVariant.is_available.is_(True),
                                )
                                .limit(1)
                            )
                        )
                run = session.get(ProductSyncRun, run_id)
                if run is None:
                    raise RuntimeError("product_sync_run_missing")
                run.status = "succeeded"
                run.active_key = None
                run.success_cursor = run.candidate_cursor
                run.finished_at = now
                run.included_records = included
                run.created_records = created
                run.updated_records = updated
                run.ignored_records = ignored
                run.disabled_records = disabled
                run.moved_out_records = moved_out
                run.source_checkpoint = None
                success_cursor = run.success_cursor
                session.execute(
                    delete(ProductSyncStagedVariant).where(
                        ProductSyncStagedVariant.run_id == run_id
                    )
                )
                session.add(
                    AuditLog(
                        request_id=request_id,
                        action="product_sync.succeeded",
                        target_type="product_sync_run",
                        target_id=run_id,
                        changes={"runType": "incremental", "recordsRead": run.records_read},
                        actor_id=actor_id,
                        source_terminal="worker",
                    )
                )
        except Exception as error:
            self._record_failure(run_id=run_id, error=error, actor_id=actor_id)
            raise
        return ProductSyncResult(
            run_id=run_id,
            status="succeeded",
            included_records=included,
            ignored_records=ignored,
            success_cursor=success_cursor,
        )

    def _stage_incremental_pages(
        self,
        *,
        run_id: str,
        start_cursor: str | None,
    ) -> None:
        with self._session_factory() as session:
            run = session.get(ProductSyncRun, run_id)
            if run is None:
                raise RuntimeError("product_sync_run_missing")
            page_number = run.next_page
            checkpoint = run.source_checkpoint
            candidate_cursor = run.candidate_cursor
        while True:
            page = self._source.fetch_incremental_page(
                start_cursor=start_cursor,
                page_number=page_number,
                checkpoint=checkpoint,
            )
            if page.page_number != page_number:
                raise ValueError("product_source_pagination_invalid")
            if candidate_cursor is not None and page.candidate_cursor != candidate_cursor:
                raise ValueError("product_source_cursor_changed")
            if page.has_next and page.next_checkpoint is None:
                raise ValueError("product_source_checkpoint_missing")
            candidate_cursor = page.candidate_cursor
            with self._session_factory() as session, session.begin():
                run = session.get(ProductSyncRun, run_id)
                if run is None:
                    raise RuntimeError("product_sync_run_missing")
                for record in page.items:
                    if self._is_available(record):
                        self._required_properties_value(record)
                    self._stage_record(session, run_id=run_id, record=record)
                run.candidate_cursor = candidate_cursor
                run.pages_read += 1
                run.records_read += len(page.items)
                run.next_page = page_number + 1
                run.source_checkpoint = page.next_checkpoint
                run.source_completed = not page.has_next
            if not page.has_next:
                return
            assert page.next_checkpoint is not None
            checkpoint = page.next_checkpoint
            page_number += 1

    def _last_success_cursor(self) -> str | None:
        with self._session_factory() as session:
            return session.scalar(
                select(ProductSyncRun.success_cursor)
                .where(ProductSyncRun.status == "succeeded")
                .order_by(ProductSyncRun.finished_at.desc(), ProductSyncRun.run_id.desc())
                .limit(1)
            )

    def _record_failure(
        self,
        *,
        run_id: str,
        error: Exception,
        actor_id: str | None,
    ) -> None:
        error_code = str(error)
        if not error_code.startswith("product_"):
            error_code = "product_sync_failed"
        error_code = error_code[:100]
        with self._session_factory() as session, session.begin():
            run = session.get(ProductSyncRun, run_id)
            if run is None:
                return
            run.status = "failed"
            run.active_key = None
            run.finished_at = utc_now()
            run.error_code = error_code
            session.add(
                AuditLog(
                    request_id=run.request_id,
                    action="product_sync.failed",
                    target_type="product_sync_run",
                    target_id=run_id,
                    changes={"runType": run.run_type, "errorCode": error_code},
                    actor_id=actor_id,
                    source_terminal="worker",
                )
            )

    @staticmethod
    def _is_available(record: SourceProductVariant) -> bool:
        return record.category in PRODUCT_CATEGORY_ALLOWLIST and record.enabled == 1

    @staticmethod
    def _required_properties_value(record: SourceProductVariant) -> str:
        value = record.properties_value
        if not isinstance(value, str) or not value.strip():
            raise ProductSourceError("product_source_contract_invalid")
        return value

    @staticmethod
    def _upsert_available(
        session: Session,
        *,
        record: SourceProductVariant,
        now: datetime,
    ) -> Product:
        properties_value = ProductSyncService._required_properties_value(record)
        product = session.scalar(select(Product).where(Product.source_i_id == record.i_id))
        if product is None:
            product = Product(
                product_id=str(uuid4()),
                source_i_id=record.i_id,
                name=record.name,
                is_available=True,
                image_source_ref=record.pic,
                image_cache_status="pending" if record.pic else "missing",
                source_modified_at=record.source_modified_at,
                first_synced_at=now,
                last_synced_at=now,
            )
            session.add(product)
            session.flush()
        else:
            image_changed = product.image_source_ref != record.pic
            product.name = record.name
            product.is_available = True
            product.image_source_ref = record.pic
            if record.pic is None:
                product.image_cache_status = "missing"
                product.image_object_key = None
                product.image_cache_error = None
            elif image_changed:
                product.image_cache_status = "pending"
                product.image_cache_error = None
            product.source_modified_at = max(product.source_modified_at, record.source_modified_at)
            product.last_synced_at = now
        variant = session.scalar(
            select(ProductVariant).where(ProductVariant.source_sku_id == record.sku_id)
        )
        if variant is None:
            session.add(
                ProductVariant(
                    variant_id=str(uuid4()),
                    product_id=product.product_id,
                    source_sku_id=record.sku_id,
                    properties_value=properties_value,
                    source_category=record.category,
                    source_enabled=record.enabled,
                    is_available=True,
                    source_modified_at=record.source_modified_at,
                    first_synced_at=now,
                    last_synced_at=now,
                )
            )
        else:
            if variant.product_id != product.product_id:
                raise ValueError("product_source_identity_conflict")
            variant.properties_value = properties_value
            variant.source_category = record.category
            variant.source_enabled = record.enabled
            variant.is_available = True
            variant.source_modified_at = max(variant.source_modified_at, record.source_modified_at)
            variant.last_synced_at = now
        if record.pic:
            ProductSyncService._enqueue_image_job(
                session,
                product=product,
                record=record,
                now=now,
            )
        return product

    @staticmethod
    def _enqueue_image_job(
        session: Session,
        *,
        product: Product,
        record: SourceProductVariant,
        now: datetime,
    ) -> bool:
        if not record.pic:
            return False
        image_version = hashlib.sha256(record.pic.encode()).hexdigest()[:24]
        dedupe_key = f"product-image:{product.product_id}:{image_version}"
        existing_job = session.scalar(
            select(BackgroundJob.id).where(
                BackgroundJob.job_type == "product-image-cache",
                BackgroundJob.dedupe_key == dedupe_key,
            )
        )
        if existing_job is not None:
            return False
        session.add(
            BackgroundJob(
                job_type="product-image-cache",
                dedupe_key=dedupe_key,
                payload={
                    "product_id": product.product_id,
                    "source_ref": record.pic,
                    "source_i_id": record.i_id,
                },
                available_at=now,
            )
        )
        return True


class ProductImageService:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        image_store: ProductImageStore,
    ) -> None:
        self._session_factory = session_factory
        self._image_store = image_store

    def process(self, payload: dict[str, object]) -> None:
        product_id = payload.get("product_id")
        source_ref = payload.get("source_ref")
        source_i_id = payload.get("source_i_id")
        if not all(
            isinstance(value, str) and value for value in (product_id, source_ref, source_i_id)
        ):
            raise ValueError("product_image_payload_invalid")
        assert isinstance(product_id, str)
        assert isinstance(source_ref, str)
        assert isinstance(source_i_id, str)
        try:
            cached = self._image_store.cache(
                source_ref=source_ref,
                object_key=f"products/{source_i_id}/{source_ref}",
            )
        except Exception:
            with self._session_factory() as session, session.begin():
                product = session.get(Product, product_id)
                if product is not None and product.image_source_ref == source_ref:
                    product.image_cache_status = "failed"
                    product.image_cache_error = "product_image_cache_failed"
            raise
        with self._session_factory() as session, session.begin():
            product = session.get(Product, product_id)
            if product is None or product.image_source_ref != source_ref:
                return
            product.image_object_key = cached.object_key
            product.image_cache_status = "cached"
            product.image_cache_error = None
