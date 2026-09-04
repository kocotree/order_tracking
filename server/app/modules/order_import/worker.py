from collections.abc import Callable, Mapping
from typing import Any

from app.adapters.order_source import FeishuOrderSource
from app.modules.order_import.service import OrderImportService


class OrderImportWorkerHandlers:
    def __init__(self, *, service: OrderImportService, source: FeishuOrderSource) -> None:
        self._service = service
        self._source = source

    def handlers(self) -> Mapping[str, Callable[[dict[str, Any]], None]]:
        return {
            "order_import": self._run,
            "order_import_revalidate": self._revalidate,
        }

    def terminal_failure_handlers(
        self,
    ) -> Mapping[str, Callable[[dict[str, Any], Exception], None]]:
        return {"order_import": self._fail}

    def _run(self, payload: dict[str, Any]) -> None:
        run_id = payload.get("runId")
        if not isinstance(run_id, str) or not run_id:
            raise ValueError("order_import_job_payload_invalid")
        source_scope = self._source.source_scope
        watermark = self._service.successful_watermark(source_scope)
        maximum_modified_at = watermark
        pages_read = 0
        rows = []
        for page in self._source.read_pages(modified_since=watermark):
            pages_read += 1
            rows.extend(page)
            page_modified_times = [
                row.source_modified_at for row in page if row.source_modified_at is not None
            ]
            if page_modified_times:
                page_maximum = max(page_modified_times)
                maximum_modified_at = (
                    page_maximum
                    if maximum_modified_at is None
                    else max(maximum_modified_at, page_maximum)
                )
        self._service.start_run_attempt(run_id=run_id)
        self._service.process_page(
            run_id=run_id,
            rows=rows,
            page_number=pages_read,
            source_scope=source_scope,
        )
        self._service.complete_run(
            run_id=run_id,
            source_scope=source_scope,
            successful_modified_at=maximum_modified_at,
        )

    def _fail(self, payload: dict[str, Any], error: Exception) -> None:
        run_id = payload.get("runId")
        if isinstance(run_id, str) and run_id:
            self._service.fail_run(run_id=run_id, error_code=type(error).__name__)

    def _revalidate(self, payload: dict[str, Any]) -> None:
        factory_names = payload.get("factoryNames")
        source_sku_ids = payload.get("sourceSkuIds")
        reason = payload.get("reason")
        request_id = payload.get("requestId")
        actor_id = payload.get("actorId")
        if not isinstance(reason, str) or not reason:
            raise ValueError("order_import_revalidation_payload_invalid")
        if not isinstance(request_id, str) or not request_id:
            raise ValueError("order_import_revalidation_payload_invalid")
        if actor_id is not None and not isinstance(actor_id, str):
            raise ValueError("order_import_revalidation_payload_invalid")
        if factory_names is not None and (
            not isinstance(factory_names, list)
            or not all(isinstance(name, str) for name in factory_names)
        ):
            raise ValueError("order_import_revalidation_payload_invalid")
        if source_sku_ids is not None and (
            not isinstance(source_sku_ids, list)
            or not all(isinstance(sku, str) for sku in source_sku_ids)
        ):
            raise ValueError("order_import_revalidation_payload_invalid")
        self._service.revalidate_pending_candidates(
            factory_names=factory_names,
            source_sku_ids=source_sku_ids,
            reason=reason,
            request_id=request_id,
            actor_id=actor_id,
        )
