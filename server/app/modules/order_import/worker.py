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
        accumulated_rows = []
        page_number = 0
        for page_number, page in enumerate(self._source.read_pages(), start=1):
            accumulated_rows.extend(page)
            self._service.process_page(
                run_id=run_id,
                accumulated_rows=accumulated_rows,
                page_number=page_number,
                source_scope=self._source.source_scope,
            )
        if page_number == 0:
            self._service.process_page(
                run_id=run_id,
                accumulated_rows=[],
                page_number=0,
                source_scope=self._source.source_scope,
            )
        self._service.complete_run(run_id=run_id)

    def _fail(self, payload: dict[str, Any], error: Exception) -> None:
        run_id = payload.get("runId")
        if isinstance(run_id, str) and run_id:
            self._service.fail_run(run_id=run_id, error_code=type(error).__name__)
