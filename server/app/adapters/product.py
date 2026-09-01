import json
import secrets
import socket
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from hashlib import md5
from ipaddress import ip_address
from pathlib import Path
from time import monotonic, sleep, time
from typing import Protocol
from urllib.parse import urljoin, urlparse
from zoneinfo import ZoneInfo

import httpx

from app.adapters.private_files import PrivateFileStore

BUSINESS_TZ = ZoneInfo("Asia/Shanghai")
JST_MAX_PAGE_INDEX = 800


class ProductSourceError(RuntimeError):
    """Stable product-source failure without upstream response or credential details."""


class ProductImageCacheError(RuntimeError):
    """Stable private-image-cache failure."""


class _JstRequestRejected(RuntimeError):
    def __init__(self, code: object) -> None:
        super().__init__("jst_request_rejected")
        self.code = str(code)


@dataclass(frozen=True)
class SourceProductVariant:
    i_id: str
    sku_id: str
    name: str
    properties_value: str | None
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
class JstProductSourceConfig:
    app_key: str
    app_secret: str
    initial_sync_begin: datetime
    endpoint: str = "https://openapi.jushuitan.com"
    token_cache_path: Path = Path("/tmp/order-tracking/jst-token.json")
    page_size: int = 50
    request_interval_seconds: float = 0.8
    retry_attempts: int = 3
    retry_base_delay_seconds: float = 1.0


@dataclass(frozen=True)
class _CachedJstToken:
    app_key: str
    access_token: str
    refresh_token: str
    access_expires_at: float
    refresh_expires_at: float

    def access_is_valid(self) -> bool:
        return bool(self.access_token) and time() < self.access_expires_at

    def refresh_is_valid(self) -> bool:
        return bool(self.refresh_token) and time() < self.refresh_expires_at


class AppCredentialJstProductSource:
    """Read-only 聚水潭 SKU source with bounded modification-time windows."""

    def __init__(
        self,
        config: JstProductSourceConfig,
        *,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], datetime] | None = None,
        rate_clock: Callable[[], float] = monotonic,
        sleeper: Callable[[float], None] = sleep,
    ) -> None:
        self._config = config
        self._transport = transport
        self._clock = clock or (lambda: datetime.now(BUSINESS_TZ))
        self._rate_clock = rate_clock
        self._sleeper = sleeper
        self._last_business_request_at: float | None = None
        self._scan_mode: str | None = None
        self._scan_start: datetime | None = None
        self._scan_end: datetime | None = None
        self._window_start: datetime | None = None
        self._window_end: datetime | None = None
        self._api_page = 1
        self._expected_page = 1

    def fetch_initial_page(self, *, page_number: int) -> SourceProductPage:
        if page_number == 1:
            self._start_scan("initial", self._config.initial_sync_begin)
        return self._fetch_page(page_number=page_number)

    def fetch_incremental_page(
        self,
        *,
        start_cursor: str | None,
        page_number: int,
    ) -> SourceProductPage:
        if page_number == 1:
            start = (
                datetime.fromisoformat(start_cursor)
                if start_cursor
                else self._config.initial_sync_begin
            )
            self._start_scan("incremental", start)
        return self._fetch_page(page_number=page_number)

    def _start_scan(self, mode: str, start: datetime) -> None:
        scan_start = self._business_datetime(start)
        scan_end = self._business_datetime(self._clock()).replace(microsecond=0)
        if scan_start >= scan_end:
            scan_start = scan_end - timedelta(seconds=1)
        self._scan_mode = mode
        self._scan_start = scan_start
        self._scan_end = scan_end
        self._window_start = scan_start
        self._window_end = None
        self._api_page = 1
        self._expected_page = 1

    def _fetch_page(self, *, page_number: int) -> SourceProductPage:
        if (
            self._scan_mode is None
            or self._scan_end is None
            or self._window_start is None
            or page_number != self._expected_page
        ):
            raise ProductSourceError("product_source_pagination_invalid")
        if self._window_end is None:
            self._window_end = min(
                self._window_start + timedelta(days=7), self._scan_end
            )
        window_end = self._window_end
        while True:
            data = self._request_page(
                page_index=self._api_page,
                modified_begin=self._window_start,
                modified_end=window_end,
            )
            if self._api_page != 1 or self._page_count(data) <= JST_MAX_PAGE_INDEX:
                break
            window_seconds = int((window_end - self._window_start).total_seconds())
            if window_seconds <= 1:
                raise ProductSourceError("product_source_window_too_dense")
            window_end = self._window_start + timedelta(seconds=window_seconds // 2)
            self._window_end = window_end
        items = tuple(self._parse_item(item) for item in self._items(data))
        upstream_has_next = self._has_next(data, current_page=self._api_page)
        has_later_window = window_end < self._scan_end
        if upstream_has_next:
            self._api_page += 1
        elif has_later_window:
            self._window_start = window_end
            self._window_end = None
            self._api_page = 1
        self._expected_page += 1
        return SourceProductPage(
            page_number=page_number,
            items=items,
            has_next=upstream_has_next or has_later_window,
            candidate_cursor=self._scan_end.isoformat(),
            source_request_id=self._optional_text(data.get("requestId")),
        )

    def _request_page(
        self,
        *,
        page_index: int,
        modified_begin: datetime,
        modified_end: datetime,
    ) -> dict[str, object]:
        body = {
            "page_index": page_index,
            "page_size": self._config.page_size,
            "modified_begin": modified_begin.strftime("%Y-%m-%d %H:%M:%S"),
            "modified_end": modified_end.strftime("%Y-%m-%d %H:%M:%S"),
        }
        biz = json.dumps(body, ensure_ascii=False, separators=(",", ":"))
        try:
            access_token = self._get_access_token()
            payload = self._request_business_page(biz=biz, access_token=access_token)
        except (_JstRequestRejected, httpx.HTTPError, TypeError, ValueError) as error:
            raise ProductSourceError("product_source_unavailable") from error
        data = payload.get("data", payload)
        if not isinstance(data, dict):
            raise ProductSourceError("product_source_contract_invalid")
        return data

    def _request_business_page(
        self,
        *,
        biz: str,
        access_token: str,
    ) -> dict[str, object]:
        retries = 0
        token_refreshed = False
        while True:
            self._wait_for_business_slot()
            try:
                return self._post_form(
                    "/open/sku/query",
                    self._business_form(biz, access_token),
                )
            except _JstRequestRejected as error:
                if error.code == "100" and not token_refreshed:
                    access_token = self._renew_access_token()
                    token_refreshed = True
                    continue
                if error.code not in {"199", "200"} or retries >= self._config.retry_attempts:
                    raise
            except httpx.HTTPError as error:
                if (
                    not self._is_retryable_http_error(error)
                    or retries >= self._config.retry_attempts
                ):
                    raise
            delay = self._config.retry_base_delay_seconds * (2**retries)
            retries += 1
            self._sleeper(delay)

    @staticmethod
    def _is_retryable_http_error(error: httpx.HTTPError) -> bool:
        if isinstance(error, httpx.TransportError):
            return True
        if isinstance(error, httpx.HTTPStatusError):
            status_code = error.response.status_code
            return status_code == 429 or status_code >= 500
        return False

    def _wait_for_business_slot(self) -> None:
        now = self._rate_clock()
        if self._last_business_request_at is not None:
            remaining = (
                self._config.request_interval_seconds
                - (now - self._last_business_request_at)
            )
            if remaining > 0:
                self._sleeper(remaining)
                now = self._rate_clock()
        self._last_business_request_at = now

    def _business_form(self, biz: str, access_token: str) -> dict[str, str]:
        form = {
            "access_token": access_token,
            "app_key": self._config.app_key,
            "biz": biz,
            "charset": "utf-8",
            "timestamp": str(int(time())),
            "version": "2",
        }
        form["sign"] = self._sign(form)
        return form

    def _get_access_token(self) -> str:
        cached = self._load_token()
        if cached and cached.access_is_valid():
            return cached.access_token
        if cached and cached.refresh_is_valid():
            token_data = self._refresh_or_init(cached.refresh_token)
        else:
            token_data = self._init_token()
        return self._save_token(token_data).access_token

    def _renew_access_token(self) -> str:
        cached = self._load_token()
        token_data = (
            self._refresh_or_init(cached.refresh_token)
            if cached and cached.refresh_token
            else self._init_token()
        )
        return self._save_token(token_data).access_token

    def _refresh_or_init(self, refresh_token: str) -> dict[str, object]:
        try:
            return self._refresh_token(refresh_token)
        except _JstRequestRejected as error:
            if error.code != "140":
                raise
            return self._init_token()

    def _init_token(self) -> dict[str, object]:
        form = {
            "app_key": self._config.app_key,
            "timestamp": str(int(time())),
            "grant_type": "authorization_code",
            "charset": "utf-8",
            "code": secrets.token_hex(3),
        }
        form["sign"] = self._sign(form)
        return self._token_data(
            self._post_form("/openWeb/auth/getInitToken", form)
        )

    def _refresh_token(self, refresh_token: str) -> dict[str, object]:
        form = {
            "app_key": self._config.app_key,
            "timestamp": str(int(time())),
            "grant_type": "refresh_token",
            "charset": "utf-8",
            "refresh_token": refresh_token,
            "scope": "all",
        }
        form["sign"] = self._sign(form)
        return self._token_data(
            self._post_form("/openWeb/auth/refreshToken", form)
        )

    def _save_token(self, data: dict[str, object]) -> _CachedJstToken:
        try:
            expires_raw = data["expires_in"]
            access_raw = data["access_token"]
            refresh_raw = data["refresh_token"]
            if (
                isinstance(expires_raw, bool)
                or not isinstance(expires_raw, (str, int, float))
                or not isinstance(access_raw, str)
                or not access_raw
                or not isinstance(refresh_raw, str)
                or not refresh_raw
            ):
                raise ValueError("invalid token data")
            expires_in = int(expires_raw)
            access_token = access_raw
            refresh_token = refresh_raw
        except (KeyError, TypeError, ValueError) as error:
            raise ProductSourceError("product_source_token_contract_invalid") from error
        now = time()
        access_margin = min(24 * 3600, max(60, expires_in * 0.1))
        refresh_margin = min(12 * 3600, max(60, expires_in * 0.05))
        token = _CachedJstToken(
            app_key=self._config.app_key,
            access_token=access_token,
            refresh_token=refresh_token,
            access_expires_at=now + max(1, expires_in - access_margin),
            refresh_expires_at=now + max(1, expires_in - refresh_margin),
        )
        path = self._config.token_cache_path
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temp_path = path.with_suffix(path.suffix + ".tmp")
            temp_path.write_text(
                json.dumps(asdict(token), ensure_ascii=False, separators=(",", ":")),
                encoding="utf-8",
            )
            temp_path.chmod(0o600)
            temp_path.replace(path)
            path.chmod(0o600)
        except OSError as error:
            raise ProductSourceError("product_source_token_cache_unavailable") from error
        return token

    def _load_token(self) -> _CachedJstToken | None:
        try:
            payload = json.loads(
                self._config.token_cache_path.read_text(encoding="utf-8")
            )
            token = _CachedJstToken(**payload)
        except (FileNotFoundError, json.JSONDecodeError, OSError, TypeError):
            return None
        return token if token.app_key == self._config.app_key else None

    @staticmethod
    def _token_data(payload: dict[str, object]) -> dict[str, object]:
        data = payload.get("data")
        if not isinstance(data, dict):
            raise ProductSourceError("product_source_token_contract_invalid")
        return data

    def _post_form(self, path: str, form: dict[str, str]) -> dict[str, object]:
        with httpx.Client(timeout=30, transport=self._transport) as client:
            response = client.post(f"{self._config.endpoint.rstrip('/')}{path}", data=form)
            response.raise_for_status()
            payload = response.json()
        if not isinstance(payload, dict):
            raise ProductSourceError("product_source_contract_invalid")
        code = payload.get("code")
        if code not in (None, 0, "0") or payload.get("issuccess") is False:
            raise _JstRequestRejected(code)
        return payload

    def _sign(self, params: dict[str, str]) -> str:
        source = self._config.app_secret + "".join(
            f"{key}{params[key]}" for key in sorted(params)
        )
        return md5(
            source.encode("utf-8"), usedforsecurity=False
        ).hexdigest()

    @classmethod
    def _parse_item(cls, raw: object) -> SourceProductVariant:
        if not isinstance(raw, dict):
            raise ProductSourceError("product_source_contract_invalid")
        try:
            modified = datetime.strptime(
                cls._required_text(raw, "modified"), "%Y-%m-%d %H:%M:%S"
            ).replace(tzinfo=BUSINESS_TZ)
            enabled_raw = raw.get("enabled")
            if isinstance(enabled_raw, bool):
                raise ValueError("invalid enabled")
            enabled = int(enabled_raw) if enabled_raw is not None else None
            if enabled not in {-1, 0, 1, None}:
                raise ValueError("invalid enabled")
            return SourceProductVariant(
                i_id=cls._required_text(raw, "i_id"),
                sku_id=cls._required_text(raw, "sku_id"),
                name=cls._required_text(raw, "name"),
                properties_value=cls._optional_text(raw.get("properties_value")),
                pic=cls._optional_text(raw.get("pic")),
                category=cls._optional_text(raw.get("category")),
                enabled=enabled,
                source_modified_at=modified.astimezone(UTC).replace(tzinfo=None),
            )
        except (TypeError, ValueError) as error:
            raise ProductSourceError("product_source_contract_invalid") from error

    @staticmethod
    def _items(data: dict[str, object]) -> list[object]:
        items = data.get("datas")
        if not isinstance(items, list):
            raise ProductSourceError("product_source_contract_invalid")
        return items

    @staticmethod
    def _has_next(data: dict[str, object], *, current_page: int) -> bool:
        value = data.get("has_next")
        if isinstance(value, bool):
            return value
        page_count = data.get("page_count")
        if isinstance(page_count, int):
            return current_page < page_count
        raise ProductSourceError("product_source_contract_invalid")

    @staticmethod
    def _page_count(data: dict[str, object]) -> int:
        page_count = data.get("page_count")
        if isinstance(page_count, bool) or not isinstance(page_count, int) or page_count < 0:
            raise ProductSourceError("product_source_contract_invalid")
        return page_count

    @staticmethod
    def _required_text(payload: dict[object, object], key: str) -> str:
        value = AppCredentialJstProductSource._optional_text(payload.get(key))
        if value is None:
            raise ValueError(f"missing {key}")
        return value

    @staticmethod
    def _optional_text(value: object) -> str | None:
        if not isinstance(value, str):
            return None
        normalized = value.strip()
        return normalized or None

    @staticmethod
    def _business_datetime(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=BUSINESS_TZ)
        return value.astimezone(BUSINESS_TZ)


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


class PrivateProductImageStore:
    def __init__(
        self,
        file_store: PrivateFileStore,
        *,
        transport: httpx.BaseTransport | None = None,
        url_validator: Callable[[str], bool] | None = None,
        max_bytes: int = 10 * 1024 * 1024,
    ) -> None:
        self._file_store = file_store
        self._transport = transport
        self._url_validator = url_validator or self._is_public_https_url
        self._max_bytes = max_bytes

    def cache(self, *, source_ref: str, object_key: str) -> CachedProductImage:
        current_url = source_ref
        try:
            with httpx.Client(timeout=30, transport=self._transport) as client:
                for _redirect in range(4):
                    if not self._url_validator(current_url):
                        raise ProductImageCacheError("product_image_source_not_allowed")
                    response = client.get(current_url, follow_redirects=False)
                    if response.is_redirect:
                        location = response.headers.get("location")
                        if not location:
                            raise ProductImageCacheError(
                                "product_image_redirect_invalid"
                            )
                        current_url = urljoin(current_url, location)
                        continue
                    response.raise_for_status()
                    content_type = response.headers.get("content-type", "").split(";", 1)[0]
                    if not content_type.startswith("image/"):
                        raise ProductImageCacheError("product_image_type_invalid")
                    content = response.content
                    if len(content) > self._max_bytes:
                        raise ProductImageCacheError("product_image_too_large")
                    self._file_store.put(
                        object_key=object_key,
                        content=content,
                        content_type=content_type,
                    )
                    return CachedProductImage(object_key=object_key)
        except ProductImageCacheError:
            raise
        except Exception as error:
            raise ProductImageCacheError("product_image_cache_failed") from error
        raise ProductImageCacheError("product_image_redirect_limit_exceeded")

    @staticmethod
    def _is_public_https_url(value: str) -> bool:
        parsed = urlparse(value)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
        ):
            return False
        try:
            addresses = {
                item[4][0]
                for item in socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)
            }
        except OSError:
            return False
        return bool(addresses) and all(ip_address(address).is_global for address in addresses)


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
