from collections.abc import Callable, Mapping
from datetime import datetime, timedelta
from threading import Event
from typing import Any

from app.modules.infrastructure import InfrastructureStore, utc_now

JobHandler = Callable[[dict[str, Any]], None]


class Worker:
    def __init__(
        self,
        *,
        store: InfrastructureStore,
        worker_id: str,
        handlers: Mapping[str, JobHandler],
        retry_limits: Mapping[str, int] | None = None,
        retry_delay_seconds: int = 30,
    ) -> None:
        self._store = store
        self._worker_id = worker_id
        self._handlers = handlers
        self._retry_limits = retry_limits or {}
        self._retry_delay_seconds = retry_delay_seconds

    def run_once(self, *, now: datetime | None = None) -> bool:
        claimed = self._store.claim_next_job(worker_id=self._worker_id, now=now or utc_now())
        if claimed is None:
            return False
        handler = self._handlers.get(claimed.job_type)
        if handler is None:
            self._store.fail_job(job_id=claimed.id, error_code="handler_not_registered")
            return True
        try:
            handler(claimed.payload)
        except Exception:
            retry_limit = self._retry_limits.get(claimed.job_type, 1)
            if claimed.attempts < retry_limit:
                self._store.retry_job(
                    job_id=claimed.id,
                    error_code="handler_failed",
                    available_at=(now or utc_now()) + timedelta(seconds=self._retry_delay_seconds),
                )
            else:
                self._store.fail_job(job_id=claimed.id, error_code="handler_failed")
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
