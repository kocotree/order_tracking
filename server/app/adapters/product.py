from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


class ProductSourceError(RuntimeError):
    """Stable product-source failure without upstream response or credential details."""


class ProductImageCacheError(RuntimeError):
    """Stable private-image-cache failure."""


@dataclass(frozen=True)
class SourceProductVariant:
    i_id: str
    sku_id: str
    name: str
    properties_value: str
    pic: str | None
    category: str | None
    enabled: int | None
    source_modified_at: datetime


@dataclass(frozen=True)
class SourceProductPage:
    page_number: int
    items: tuple[SourceProductVariant, ...]
    has_next: bool
    candidate_cursor: str
    source_request_id: str | None = None


class JstProductSource(Protocol):
    def fetch_initial_page(self, *, page_number: int) -> SourceProductPage: ...

    def fetch_incremental_page(
        self,
        *,
        start_cursor: str | None,
        page_number: int,
    ) -> SourceProductPage: ...


@dataclass(frozen=True)
class CachedProductImage:
    object_key: str


class ProductImageStore(Protocol):
    def cache(self, *, source_ref: str, object_key: str) -> CachedProductImage: ...


class DisabledJstProductSource:
    def fetch_initial_page(self, *, page_number: int) -> SourceProductPage:
        del page_number
        raise ProductSourceError("product_source_not_configured")

    def fetch_incremental_page(
        self,
        *,
        start_cursor: str | None,
        page_number: int,
    ) -> SourceProductPage:
        del start_cursor, page_number
        raise ProductSourceError("product_source_not_configured")


class DisabledProductImageStore:
    def cache(self, *, source_ref: str, object_key: str) -> CachedProductImage:
        del source_ref, object_key
        raise ProductImageCacheError("product_image_store_not_configured")


class FakeProductImageStore:
    def __init__(self, *, failures_before_success: int = 0) -> None:
        self._failures_remaining = failures_before_success
        self.cached_refs: list[str] = []

    def cache(self, *, source_ref: str, object_key: str) -> CachedProductImage:
        self.cached_refs.append(source_ref)
        if self._failures_remaining > 0:
            self._failures_remaining -= 1
            raise ProductImageCacheError("product_image_cache_failed")
        return CachedProductImage(object_key=object_key)


class FakeJstProductSource:
    """Explicit test/local-demo source. It is never selected by production settings."""

    def __init__(
        self,
        *,
        initial_pages: Sequence[Sequence[SourceProductVariant]] = (),
        incremental_pages: Sequence[Sequence[SourceProductVariant]] = (),
        candidate_cursor: str,
        fail_initial_page: int | None = None,
        fail_incremental_page: int | None = None,
    ) -> None:
        self._initial_pages = tuple(tuple(page) for page in initial_pages)
        self._incremental_pages = tuple(tuple(page) for page in incremental_pages)
        self._candidate_cursor = candidate_cursor
        self._fail_initial_page = fail_initial_page
        self._fail_incremental_page = fail_incremental_page
        self.incremental_start_cursors: list[str | None] = []

    def fetch_initial_page(self, *, page_number: int) -> SourceProductPage:
        if page_number == self._fail_initial_page:
            raise ProductSourceError("product_source_page_failed")
        return self._page(self._initial_pages, page_number)

    def fetch_incremental_page(
        self,
        *,
        start_cursor: str | None,
        page_number: int,
    ) -> SourceProductPage:
        self.incremental_start_cursors.append(start_cursor)
        if page_number == self._fail_incremental_page:
            raise ProductSourceError("product_source_page_failed")
        return self._page(self._incremental_pages, page_number)

    def _page(
        self,
        pages: tuple[tuple[SourceProductVariant, ...], ...],
        page_number: int,
    ) -> SourceProductPage:
        if page_number < 1 or page_number > max(1, len(pages)):
            raise ProductSourceError("product_source_pagination_invalid")
        items = pages[page_number - 1] if pages else ()
        return SourceProductPage(
            page_number=page_number,
            items=items,
            has_next=page_number < len(pages),
            candidate_cursor=self._candidate_cursor,
            source_request_id=f"fake-product-page-{page_number}",
        )
