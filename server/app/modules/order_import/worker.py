from collections.abc import Callable, Mapping
from typing import Any

from app.adapters.order_source import FeishuOrderSource
from app.modules.order_import.service import OrderImportService


class OrderImportWorkerHandlers:
    def __init__(self, *, service: OrderImportService, source: FeishuOrderSource) -> None:
        self._service = service
        self._source = source

    def handlers(self) -> Mapping[str, Callable[[dict[str, Any]], None]]:
        return {"order_import": self._run}

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
