import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import uuid4

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.sql.elements import ColumnElement

from app.adapters.product import JstProductSource, ProductImageStore, SourceProductVariant
from app.db.models import AuditLog, BackgroundJob, Product, ProductSyncRun, ProductVariant
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
    variant_id: str
    i_id: str
    sku_id: str
    name: str
    properties_value: str
    image_available: bool


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
                    variant_id=variant.variant_id,
                    i_id=product.source_i_id,
                    sku_id=variant.source_sku_id,
                    name=product.name,
                    properties_value=variant.properties_value,
                    image_available=(
                        product.image_cache_status == "cached"
                        and product.image_object_key is not None
                    ),
                )
                for variant, product in rows
            ],
            total=int(total or 0),
            page=page,
            page_size=page_size,
        )


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
        run_id = str(uuid4())
        started_at = utc_now()
        with self._session_factory() as session, session.begin():
            session.add(
                ProductSyncRun(
                    run_id=run_id,
                    run_type="initial",
                    status="running",
                    active_key="product-sync",
                    start_cursor=None,
                    candidate_cursor=None,
                    success_cursor=None,
                    started_at=started_at,
                    worker_id=worker_id,
                    request_id=request_id,
                )
            )
        try:
            records, pages_read, candidate_cursor = self._read_initial_pages()
            unique_records = self._deduplicate(records)
            eligible = [record for record in unique_records if self._is_available(record)]
            ignored = len(unique_records) - len(eligible)
            with self._session_factory() as session, session.begin():
                now = utc_now()
                created = 0
                updated = 0
                for record in eligible:
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
                run = session.get(ProductSyncRun, run_id)
                if run is None:
                    raise RuntimeError("product_sync_run_missing")
                run.status = "succeeded"
                run.active_key = None
                run.candidate_cursor = candidate_cursor
                run.success_cursor = candidate_cursor
                run.finished_at = now
                run.pages_read = pages_read
                run.records_read = len(records)
                run.included_records = len(eligible)
                run.created_records = created
                run.updated_records = updated
                run.ignored_records = ignored
                session.add(
                    AuditLog(
                        request_id=request_id,
                        action="product_sync.succeeded",
                        target_type="product_sync_run",
                        target_id=run_id,
                        changes={"runType": "initial", "recordsRead": len(records)},
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
            included_records=len(eligible),
            ignored_records=ignored,
            success_cursor=candidate_cursor,
        )

    def run_incremental(
        self,
        *,
        request_id: str,
        worker_id: str,
        actor_id: str | None = None,
    ) -> ProductSyncResult:
        start_cursor = self._last_success_cursor()
        run_id = str(uuid4())
        started_at = utc_now()
        with self._session_factory() as session, session.begin():
            session.add(
                ProductSyncRun(
                    run_id=run_id,
                    run_type="incremental",
                    status="running",
                    active_key="product-sync",
                    start_cursor=start_cursor,
                    candidate_cursor=None,
                    success_cursor=None,
                    started_at=started_at,
                    worker_id=worker_id,
                    request_id=request_id,
                )
            )
        try:
            records, pages_read, candidate_cursor = self._read_incremental_pages(
                start_cursor=start_cursor
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
                for record in self._deduplicate(records):
                    available = self._is_available(record)
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
                    variant.properties_value = record.properties_value
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
                run.candidate_cursor = candidate_cursor
                run.success_cursor = candidate_cursor
                run.finished_at = now
                run.pages_read = pages_read
                run.records_read = len(records)
                run.included_records = included
                run.created_records = created
                run.updated_records = updated
                run.ignored_records = ignored
                run.disabled_records = disabled
                run.moved_out_records = moved_out
                session.add(
                    AuditLog(
                        request_id=request_id,
                        action="product_sync.succeeded",
                        target_type="product_sync_run",
                        target_id=run_id,
                        changes={"runType": "incremental", "recordsRead": len(records)},
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
            success_cursor=candidate_cursor,
        )

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

    def _read_initial_pages(self) -> tuple[list[SourceProductVariant], int, str]:
        records: list[SourceProductVariant] = []
        page_number = 1
        candidate_cursor: str | None = None
        while True:
            page = self._source.fetch_initial_page(page_number=page_number)
            if page.page_number != page_number:
                raise ValueError("product_source_pagination_invalid")
            if candidate_cursor is not None and page.candidate_cursor != candidate_cursor:
                raise ValueError("product_source_cursor_changed")
            candidate_cursor = page.candidate_cursor
            records.extend(page.items)
            if not page.has_next:
                break
            page_number += 1
        if candidate_cursor is None:
            raise ValueError("product_source_cursor_missing")
        return records, page_number, candidate_cursor

    def _read_incremental_pages(
        self, *, start_cursor: str | None
    ) -> tuple[list[SourceProductVariant], int, str]:
        records: list[SourceProductVariant] = []
        page_number = 1
        candidate_cursor: str | None = None
        while True:
            page = self._source.fetch_incremental_page(
                start_cursor=start_cursor,
                page_number=page_number,
            )
            if page.page_number != page_number:
                raise ValueError("product_source_pagination_invalid")
            if candidate_cursor is not None and page.candidate_cursor != candidate_cursor:
                raise ValueError("product_source_cursor_changed")
            candidate_cursor = page.candidate_cursor
            records.extend(page.items)
            if not page.has_next:
                break
            page_number += 1
        if candidate_cursor is None:
            raise ValueError("product_source_cursor_missing")
        return records, page_number, candidate_cursor

    @staticmethod
    def _deduplicate(records: list[SourceProductVariant]) -> list[SourceProductVariant]:
        by_sku: dict[str, SourceProductVariant] = {}
        for record in records:
            existing = by_sku.get(record.sku_id)
            if existing is not None and existing != record:
                raise ValueError("product_source_duplicate_conflict")
            by_sku[record.sku_id] = record
        return list(by_sku.values())

    @staticmethod
    def _is_available(record: SourceProductVariant) -> bool:
        return record.category in PRODUCT_CATEGORY_ALLOWLIST and record.enabled == 1

    @staticmethod
    def _upsert_available(
        session: Session,
        *,
        record: SourceProductVariant,
        now: datetime,
    ) -> Product:
        product = session.scalar(select(Product).where(Product.source_i_id == record.i_id))
        if product is None:
            same_name = session.scalar(select(Product).where(Product.name == record.name))
            if same_name is not None:
                raise ValueError("product_source_identity_conflict")
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
            same_name = session.scalar(
                select(Product).where(
                    Product.name == record.name,
                    Product.product_id != product.product_id,
                )
            )
            if same_name is not None:
                raise ValueError("product_source_identity_conflict")
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
                    properties_value=record.properties_value,
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
            variant.properties_value = record.properties_value
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
