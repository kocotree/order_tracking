from collections.abc import Callable, Mapping
from datetime import datetime, timedelta
from threading import Event
from typing import Any

from app.modules.infrastructure import InfrastructureStore, utc_now

JobHandler = Callable[[dict[str, Any]], None]
TerminalFailureHandler = Callable[[dict[str, Any], Exception], None]


class Worker:
    def __init__(
        self,
        *,
        store: InfrastructureStore,
        worker_id: str,
        handlers: Mapping[str, JobHandler],
        terminal_failure_handlers: Mapping[str, TerminalFailureHandler] | None = None,
        retry_limits: Mapping[str, int] | None = None,
        retry_delay_seconds: int = 30,
        maintenance: Callable[[], None] | None = None,
        work_sources: list[Callable[[], bool]] | None = None,
    ) -> None:
        self._store = store
        self._worker_id = worker_id
        self._handlers = handlers
        self._terminal_failure_handlers = terminal_failure_handlers or {}
        self._retry_limits = retry_limits or {}
        self._retry_delay_seconds = retry_delay_seconds
        self._maintenance = maintenance
        self._work_sources = work_sources or []

    def run_once(self, *, now: datetime | None = None) -> bool:
        if self._maintenance is not None:
            self._maintenance()
        claimed = self._store.claim_next_job(worker_id=self._worker_id, now=now or utc_now())
        if claimed is None:
            return any(source() for source in self._work_sources)
        handler = self._handlers.get(claimed.job_type)
        if handler is None:
            self._store.fail_job(job_id=claimed.id, error_code="handler_not_registered")
            return True
        try:
            handler(claimed.payload)
        except Exception as error:
            retry_limit = self._retry_limits.get(claimed.job_type, 1)
            if claimed.attempts < retry_limit:
                self._store.retry_job(
                    job_id=claimed.id,
                    error_code="handler_failed",
                    available_at=(now or utc_now()) + timedelta(seconds=self._retry_delay_seconds),
                )
            else:
                self._store.fail_job(job_id=claimed.id, error_code="handler_failed")
                terminal_failure_handler = self._terminal_failure_handlers.get(
                    claimed.job_type
                )
                if terminal_failure_handler is not None:
                    terminal_failure_handler(claimed.payload, error)
            return True
        self._store.complete_job(job_id=claimed.id)
        return True

    def run(self, *, stop_event: Event, poll_interval: float = 1.0) -> int:
        processed = 0
        while not stop_event.is_set():
            if self.run_once():
                processed += 1
                continue
            stop_event.wait(poll_interval)
        return processed
